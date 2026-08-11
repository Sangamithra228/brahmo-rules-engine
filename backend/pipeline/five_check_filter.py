"""
Stage 5 - The Five-Check Sequential Filter.

Each check contributes ONE SQL predicate. The repository ANDs them
progressively, so stage k runs with predicates 1..k and the row set entering
check k+1 is literally the row set that survived check k.

Why sequential and not parallel: the checks are ordered by blast radius, not
by cost. Compliance runs before permission so that an MNPI node is gone before
anything reasons about hierarchy. If they ran in parallel you would still get
the same final set on this dataset, but every check would see rows it has no
business seeing, and the audit trail would say a node was "excluded by
permission" when the truthful, legally relevant answer is "excluded by
compliance". Order encodes intent.

Why in SQL and not in Python: GAP 5. If all 50 rows are pulled into the
process and filtered there, restricted content has already crossed the network
boundary. Discarding it afterwards is not access control, it is politeness.
The predicates below run inside the database, so a node Priya may not see is
never read off disk on her behalf.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Tuple

from backend.policy.role_policy import KNOWN_COMPLIANCE_TAGS
from backend.pipeline.permission_compiler import CompiledPermissions

# Statuses that mean "this node no longer represents current truth".
# LEGAL_HOLD is deliberately NOT here: it restricts modification, not reading.
STALE_STATUSES = ("SUPERSEDED", "EXPIRED")

Predicate = Tuple[str, str, List[Any]]


@dataclass(frozen=True)
class FilterConfig:
    derivability_threshold: float = 0.7
    now: str = None

    def resolved_now(self) -> str:
        return self.now or datetime.now(timezone.utc).isoformat()


def build_predicates(
    perms: CompiledPermissions,
    org_id: str,
    config: FilterConfig,
    scope_exempt_level_ids: List[str] = None,
) -> List[Predicate]:
    """Turn a compiled permission set into the five ordered SQL predicates."""
    preds: List[Predicate] = []

    # ---- Check 1: ISOLATION -------------------------------------------
    # Multi-tenant boundary. Single-org demo, so everything passes - but the
    # predicate is real, and it is FIRST, because a cross-tenant row must not
    # be evaluated by any later rule.
    preds.append(("ISOLATION", "org_id = ?", [org_id]))

    # ---- Check 2: COMPLIANCE ------------------------------------------
    # A node is withheld unless the user clears EVERY tag it carries.
    # `required_tags` is ',MNPI,CONFIDENTIAL,' shaped, so an uncleared tag is
    # a LIKE miss. Department-scoped clearance (a HOD clears their own
    # department's MNPI, not Cardiology's) becomes an OR on department.
    frags: List[str] = []
    params: List[Any] = []
    scoped = perms.policy.clearance_scoped_to_department
    for tag in KNOWN_COMPLIANCE_TAGS:
        if tag in perms.explicit_clearance:
            continue  # granted outright on the user row, never scoped
        if tag in perms.clearance:
            if scoped:
                # Cleared, but only within the user's own department.
                frags.append("(required_tags NOT LIKE ? OR department = ?)")
                params.extend([f"%,{tag},%", perms.department])
            continue  # cleared everywhere
        frags.append("required_tags NOT LIKE ?")
        params.append(f"%,{tag},%")
    preds.append(("COMPLIANCE", " AND ".join(frags) if frags else "", params))

    # ---- Check 3: PERMISSION ------------------------------------------
    # O(1) compiled level map -> a literal IN list. No per-node query.
    readable = [lvl for lvl, v in sorted(perms.level_map.items()) if v["can_read"]]
    if len(readable) == len(perms.level_map):
        frag, prm = "", []  # role reads every tier; predicate is a no-op
    else:
        q = ",".join("?" * len(readable)) if readable else "NULL"
        alts = [f"hierarchy_level IN ({q})"]
        prm = list(readable)

        if perms.policy.zone2_bypasses_ceiling:
            # Zone 2 is a hospital-wide broadcast. Its hierarchy position
            # records where it was AUTHORED, not who may read it. Without
            # this, a ward nurse loses every drug-safety constraint and
            # Scenario 4 has nothing to demonstrate.
            alts.append("zone = 2")

        # scope_aware mode: BFS has already proved these tiers are inside the
        # user's own branch, so the ceiling does not re-litigate them. It
        # still bites on tiers reached by a cross-department fallback walk.
        exempt = scope_exempt_level_ids or []
        if exempt:
            alts.append(
                "hierarchy_level_id IN (%s)" % ",".join("?" * len(exempt))
            )
            prm += list(exempt)

        frag = "(" + " OR ".join(alts) + ")"
    # `hierarchy_level` is denormalised onto the node row - indexed compare.
    preds.append(("PERMISSION", frag, prm))

    # ---- Check 4: TEMPORAL --------------------------------------------
    stale_q = ",".join("?" * len(STALE_STATUSES))
    preds.append((
        "TEMPORAL",
        f"status NOT IN ({stale_q}) AND (valid_until IS NULL OR valid_until > ?)",
        list(STALE_STATUSES) + [config.resolved_now()],
    ))

    # ---- Check 5: DERIVABILITY ----------------------------------------
    # Pre-computed score, compared to an org-configurable threshold. No LLM,
    # no embedding lookup, no runtime analysis - one indexed numeric compare.
    preds.append((
        "DERIVABILITY", "derivability_score < ?", [config.derivability_threshold]
    ))

    return preds
