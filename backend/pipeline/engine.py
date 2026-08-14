"""
The Rules Engine (L2). ZERO LLM. Fully deterministic.

  compile permissions -> resolve entry -> BFS -> inject Zone 2
  -> five sequential checks (in SQL) -> assemble candidate set

There is no model call, no embedding lookup, no similarity score and no
randomness anywhere in this file or anything it imports. Every decision is a
binary predicate over stored data. Run it twice with the same inputs and you
get byte-identical output - `tests/test_pipeline.py` asserts exactly that.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.models import ExclusionRecord, PipelineResult, User
from backend.pipeline.bfs_traversal import traverse
from backend.pipeline.candidate_assembler import assemble
from backend.pipeline.entry_point_resolver import resolve_entry_point
from backend.pipeline.five_check_filter import FilterConfig, build_predicates
from backend.pipeline.permission_compiler import compile_permissions
from backend.pipeline.zone2_injector import inject
from backend.repository.base import Repository

CHECK_ORDER = ["ISOLATION", "COMPLIANCE", "PERMISSION", "TEMPORAL", "DERIVABILITY"]


@dataclass
class EngineOptions:
    zone2_enabled: bool = True          # Scenario 4 toggles this
    derivability_threshold: float = 0.7
    include_audit: bool = False         # operator-only exclusion trail
    now: Optional[str] = None           # pin time for reproducible tests
    # "strict"      - ceiling compares against every node's tier (spec literal)
    # "scope_aware" - ceiling only bites on tiers BFS did not already scope
    # See docs/architecture.md, "Decision 4". Default is strict.
    permission_mode: str = "strict"


class RulesEngine:
    def __init__(self, repo: Repository, org_id: str = "supra"):
        self.repo = repo
        self.org_id = org_id
        # The hierarchy is static for this assessment, so it is read once and
        # held. At 15,000 nodes this is still only the level DAG (tens of
        # rows), not the knowledge nodes.
        self._levels = None

    def levels(self):
        if self._levels is None:
            self._levels = self.repo.list_hierarchy(self.org_id)
        return self._levels

    def run(self, user: User, opts: EngineOptions = None) -> PipelineResult:
        opts = opts or EngineOptions()
        timing: Dict[str, float] = {}
        notes: List[str] = []
        t_total = time.perf_counter()

        # ---- 1. permission compilation (once per session) --------------
        t = time.perf_counter()
        perms = compile_permissions(user)
        timing["permission_compile_ms"] = _ms(t)
        notes.append(
            f"Compiled {len(perms.level_map)} levels into an O(1) map; "
            f"effective clearance={sorted(perms.clearance) or 'none'}"
        )

        # ---- 2. entry point --------------------------------------------
        t = time.perf_counter()
        entry = resolve_entry_point(perms, self.levels())
        timing["entry_point_ms"] = _ms(t)
        notes.append(f"Entry point {entry.level_id}: {entry.reason}")

        # ---- 3. BFS (upward only) ---------------------------------------
        t = time.perf_counter()
        walk = traverse(entry_level_id=entry.level_id, levels=self.levels())
        scope = dict(walk.reachable)

        # A user whose department has no tier in the DAG enters at the root,
        # where an upward walk reaches nothing. Roles marked as
        # cross-organisation in the policy table (ADMIN, QUALITY, AUDITOR) are
        # granted org-wide scope instead. This is a scope grant driven by role
        # policy, NOT a traversal - BFS above is strictly upward. Distance is
        # tier depth below the entry point, used only for the compression hint.
        org_wide = entry.is_fallback and perms.policy.cross_department_on_fallback
        if org_wide:
            for level in self.levels():
                if level.id not in scope:
                    scope[level.id] = max(
                        level.level_number - entry.level_number, 1
                    )
            notes.append(
                f"Role {user.role} has org-wide scope: department "
                f"'{user.department}' has no tier in the DAG, so all "
                f"{len(scope)} tiers are in scope (still subject to all five checks)"
            )

        timing["bfs_ms"] = _ms(t)
        notes.append(
            f"BFS walked up from {entry.level_id} and reached "
            f"{len(walk.reachable)} tier(s)"
        )
        if walk.multi_parent_hits:
            notes.append(
                "Multi-parent tiers re-encountered and skipped by the visited "
                f"set: {', '.join(walk.multi_parent_hits)}"
            )

        after_bfs = self.repo.count_candidates(
            self.org_id, list(scope.keys()), []
        )

        # ---- 4. Zone 2 injection ---------------------------------------
        t = time.perf_counter()
        injection = inject(
            reachable=scope,
            zone2_node_ids=self.repo.zone2_node_ids(self.org_id),
            enabled=opts.zone2_enabled,
        )
        timing["zone2_inject_ms"] = _ms(t)
        after_zone2 = self.repo.count_candidates(
            self.org_id, injection.level_ids, injection.injected_node_ids
        )
        if not opts.zone2_enabled:
            notes.append("Zone 2 injection DISABLED for this run (demo toggle)")

        # ---- 5. five sequential checks, executed in SQL -----------------
        config = FilterConfig(
            derivability_threshold=opts.derivability_threshold, now=opts.now
        )
        predicates = build_predicates(
            perms, self.org_id, config,
            scope_exempt_level_ids=(
                list(scope.keys())
                if opts.permission_mode == "scope_aware" else []
            ),
            dialect=getattr(self.repo, "dialect", "sqlite"),
        )

        t = time.perf_counter()
        checked = self.repo.run_checks(
            org_id=self.org_id,
            candidate_level_ids=injection.level_ids,
            predicates=predicates,
            fetch_rows_at_end=True,
            collect_ids_per_stage=opts.include_audit,
            extra_node_ids=injection.injected_node_ids,
        )
        checks_total = _ms(t)

        stage_counts = {s["check"]: s["count"] for s in checked["stages"]}
        # Per-check timing is apportioned across the stages actually executed.
        per = round(checks_total / max(len(checked["stages"]), 1), 3)
        for name in CHECK_ORDER:
            timing[f"check_{name.lower()}_ms"] = per

        # ---- 6. assemble -----------------------------------------------
        t = time.perf_counter()
        candidates = assemble(
            nodes=checked["rows"],
            distances=injection.distances,
            injected_node_ids=injection.injected_node_ids,
        )
        timing["assemble_ms"] = _ms(t)
        timing["total_ms"] = _ms(t_total)

        funnel = {
            "total_nodes": self.repo.total_node_count(self.org_id),
            "after_bfs": after_bfs,
            "after_zone2": after_zone2,
            "after_isolation": stage_counts.get("ISOLATION", 0),
            "after_compliance": stage_counts.get("COMPLIANCE", 0),
            "after_permission": stage_counts.get("PERMISSION", 0),
            "after_temporal": stage_counts.get("TEMPORAL", 0),
            "after_derivability": stage_counts.get("DERIVABILITY", 0),
        }

        exclusions: List[ExclusionRecord] = []
        if opts.include_audit:
            exclusions = self._audit(checked, injection.level_ids)

        return PipelineResult(
            user=user,
            entry_point=entry.level_id,
            entry_point_name=entry.level_name,
            funnel=funnel,
            timing_ms=timing,
            candidate_set=candidates,
            exclusions=exclusions,
            notes=notes,
        )

    # ------------------------------------------------------------------
    def _audit(self, checked, all_level_ids) -> List[ExclusionRecord]:
        """Attribute each excluded node to the FIRST check that removed it.

        Operator-only. Never merged into the user-facing response - that is
        what silent exclusion means.
        """
        reasons = {
            "ISOLATION": "belongs to a different organisation",
            "COMPLIANCE": "carries a compliance tag the user does not clear",
            "PERMISSION": "sits at a hierarchy tier above the user's ceiling",
            "TEMPORAL": "superseded or past its validity window",
            "DERIVABILITY": "derivable from general knowledge; spending tokens "
                            "on it would teach the model nothing",
        }
        records: List[ExclusionRecord] = []
        stages = checked["stages"]
        if not stages or stages[0].get("ids") is None:
            return records

        previous = set(stages[0]["ids"])
        # Anything in the injected level set but absent from stage 1.
        for i, stage in enumerate(stages):
            current = set(stage["ids"])
            removed = previous - current if i > 0 else set()
            for nid in sorted(removed):
                records.append(
                    ExclusionRecord(
                        node_id=nid, node_title="",
                        check=stage["check"], reason=reasons[stage["check"]],
                    )
                )
            previous = current

        titles = getattr(self.repo, "titles_for", lambda ids: {})(
            [r.node_id for r in records]
        )
        for r in records:
            r.node_title = titles.get(r.node_id, "")
        return records


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 3)
