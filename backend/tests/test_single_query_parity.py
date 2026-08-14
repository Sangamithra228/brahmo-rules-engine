"""
The optimized single-statement path must return exactly what the progressive
seven-round-trip path returns.

`run_checks` (progressive: one COUNT per stage, then a fetch) is the reference
implementation. `run_pipeline_single_query` collapses the same logic into one
statement of chained CTEs. These tests run BOTH against the same inputs and
require identical funnels and identical candidate ids - for every seeded user,
for unseen profiles, and with Zone 2 on and off.

If these ever disagree, the optimization has changed behaviour and is wrong.
"""

import unittest

from backend.models import User
from backend.pipeline.bfs_traversal import traverse
from backend.pipeline.engine import EngineOptions
from backend.pipeline.entry_point_resolver import resolve_entry_point
from backend.pipeline.five_check_filter import FilterConfig, build_predicates
from backend.pipeline.permission_compiler import compile_permissions
from backend.tests.conftest_helper import engine

ORG = "supra"


class TestSingleQueryParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    # -- helpers ------------------------------------------------------
    def _inputs(self, user, zone2=True):
        perms = compile_permissions(user)
        levels = self.repo.list_hierarchy(ORG)
        entry = resolve_entry_point(perms, levels)
        walk = traverse(entry.level_id, levels)
        scope = dict(walk.reachable)
        if entry.is_fallback and perms.policy.cross_department_on_fallback:
            for lvl in levels:
                scope.setdefault(lvl.id, max(lvl.level_number - entry.level_number, 1))
        z2 = zone2
        preds = build_predicates(
            perms, ORG, FilterConfig(now="2026-01-01T00:00:00+00:00"),
            dialect=self.repo.dialect)
        return list(scope.keys()), z2, preds

    def _progressive(self, user, zone2=True):
        levels, z2, preds = self._inputs(user, zone2)
        out = self.repo.run_checks(
            org_id=ORG, candidate_level_ids=levels, predicates=preds,
            fetch_rows_at_end=True, collect_ids_per_stage=False,
            extra_node_ids=self.repo.zone2_node_ids(ORG) if z2 else [])
        counts = {s["check"]: s["count"] for s in out["stages"]}
        return counts, [n.id for n in out["rows"]]

    def _single(self, user, zone2=True):
        levels, z2, preds = self._inputs(user, zone2)
        out = self.repo.run_pipeline_single_query(
            org_id=ORG, candidate_level_ids=levels,
            zone2_enabled=z2, predicates=preds)
        f = out["funnel"]
        counts = {
            "ISOLATION": f["after_isolation"], "COMPLIANCE": f["after_compliance"],
            "PERMISSION": f["after_permission"], "TEMPORAL": f["after_temporal"],
            "DERIVABILITY": f["after_derivability"],
        }
        return counts, [n.id for n in out["rows"]]

    def _assert_parity(self, user, zone2=True):
        pc, pids = self._progressive(user, zone2)
        sc, sids = self._single(user, zone2)
        label = f"{user.id} zone2={zone2}"
        self.assertEqual(pc, sc, f"funnel differs for {label}")
        self.assertEqual(sorted(pids), sorted(sids),
                         f"candidate ids differ for {label}")

    # -- every seeded user --------------------------------------------
    def test_parity_for_every_seeded_user(self):
        for user in self.repo.list_users():
            self._assert_parity(user)

    def test_parity_with_zone2_disabled(self):
        for user in self.repo.list_users():
            self._assert_parity(user, zone2=False)

    # -- unseen profiles ----------------------------------------------
    def test_parity_for_unseen_profiles(self):
        profiles = [
            User("U-P1", ORG, "Pharmacist", "VIEWER", "pharmacy", 12, None, []),
            User("U-P2", ORG, "Quality Officer", "QUALITY", "quality", 6, 8, ["MNPI"]),
            User("U-P3", ORG, "External Auditor", "AUDITOR", "audit", 3, None, []),
            User("U-P4", ORG, "New HOD", "HOD", "cardiology", 4, 4, []),
            User("U-P5", ORG, "Unknown Role", "CHIEF_WIZARD", "ortho", 1, None, []),
        ]
        for p in profiles:
            self._assert_parity(p)
            self._assert_parity(p, zone2=False)

    # -- the engine end to end ----------------------------------------
    def test_engine_matches_the_progressive_path_end_to_end(self):
        """Audit mode uses the progressive path; normal mode uses the single
        statement. Both must yield the same candidate set."""
        for user in self.repo.list_users():
            fast = self.eng.run(user, EngineOptions(now="2026-01-01T00:00:00+00:00"))
            slow = self.eng.run(user, EngineOptions(
                include_audit=True, now="2026-01-01T00:00:00+00:00"))
            self.assertEqual(
                [c.id for c in fast.candidate_set],
                [c.id for c in slow.candidate_set],
                f"{user.id}: optimized and reference paths disagree")
            for key in ["total_nodes", "after_bfs", "after_zone2",
                        "after_isolation", "after_compliance",
                        "after_permission", "after_temporal",
                        "after_derivability"]:
                self.assertEqual(fast.funnel[key], slow.funnel[key],
                                 f"{user.id}: funnel[{key}] differs")

    def test_candidate_metadata_survives_the_optimization(self):
        for user in self.repo.list_users():
            for c in self.eng.run(user, EngineOptions()).candidate_set:
                for field in ["id", "type", "content", "importance", "zone",
                              "hierarchy_level", "distance_from_entry",
                              "compression_hint"]:
                    self.assertIn(field, c.to_dict())

    def test_zone2_node_on_the_ancestor_path_is_not_duplicated(self):
        """The pool is a UNION, so a global node that is also BFS-reachable
        must appear exactly once."""
        self.repo._conn.execute(
            "UPDATE knowledge_nodes SET hierarchy_level_id='HL-05-ORTHO', "
            "hierarchy_level=5 WHERE id='N-G01'")
        self.repo._conn.commit()
        try:
            _c, ids = self._single(self.repo.get_user("U-VIKRAM"))
            self.assertEqual(ids.count("N-G01"), 1)
            self.assertEqual(len(ids), len(set(ids)))
        finally:
            self.repo._conn.execute(
                "UPDATE knowledge_nodes SET hierarchy_level_id='HL-GLOBAL', "
                "hierarchy_level=3 WHERE id='N-G01'")
            self.repo._conn.commit()

    def test_checks_remain_sequential_in_the_generated_sql(self):
        """Each check must read the previous check's CTE, not the raw pool."""
        from backend.repository import pipeline_sql
        user = self.repo.get_user("U-PRIYA")
        levels, z2, preds = self._inputs(user)
        sql, _p = pipeline_sql.build("supra", levels, True, preds)
        for prev, nxt in zip(pipeline_sql.CHECK_CTE, pipeline_sql.CHECK_CTE[1:]):
            self.assertIn(f"{nxt} AS (SELECT * FROM {prev}", sql,
                          f"{nxt} does not read {prev}")
        self.assertIn("c1_isolation AS (SELECT n.id,", sql,
                      "check 1 must read from knowledge_nodes via the pool")


if __name__ == "__main__":
    unittest.main()


class TestGap5ContentIsNotReadEarly(unittest.TestCase):
    """GAP 5: permission must be enforced before node content is retrieved.

    Two separate properties:
      1. Nothing unfiltered is pulled into Python - all five checks run as SQL.
      2. Inside the statement, the check chain carries METADATA only. `content`
         and `title` are joined on after check 5, so a node excluded by any
         check never has its payload read.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def _sql(self, uid="U-PRIYA"):
        from backend.repository import pipeline_sql
        user = self.repo.get_user(uid)
        perms = compile_permissions(user)
        levels = self.repo.list_hierarchy(ORG)
        entry = resolve_entry_point(perms, levels)
        walk = traverse(entry.level_id, levels)
        preds = build_predicates(perms, ORG, FilterConfig(),
                                 dialect=self.repo.dialect)
        sql, _params = pipeline_sql.build(
            ORG, list(walk.reachable), True, preds, dialect=self.repo.dialect)
        return sql

    def test_check_chain_never_selects_content_or_title(self):
        sql = self._sql()
        chain = sql.split("SELECT counts.")[0]
        self.assertNotIn("content", chain,
                         "content must not travel through the check chain")
        self.assertNotIn("title", chain)
        self.assertNotIn("n.*", chain, "no wildcard select before check 5")

    def test_content_is_joined_only_to_survivors_of_check_five(self):
        sql = self._sql()
        final = sql.split("SELECT counts.")[1]
        self.assertIn("JOIN c5_derivability", final,
                      "content must be joined to the check-5 output")

    def test_every_filter_column_the_predicates_use_is_carried(self):
        """If a predicate referenced a column the chain drops, the statement
        would error. Guard the column list against drift."""
        from backend.repository import pipeline_sql
        sql = self._sql()
        for column in ["org_id", "hierarchy_level", "zone", "status",
                       "superseded_by", "valid_until", "derivability_score",
                       "department"]:
            self.assertIn(column, sql, f"{column} dropped from the chain")
        self.assertIn("required_tags", pipeline_sql.filter_columns("sqlite"))
        self.assertIn("compliance_tags", pipeline_sql.filter_columns("postgres"))
        self.assertNotIn("content", pipeline_sql.filter_columns("postgres"))

    def test_no_unfiltered_fetch_reaches_python(self):
        """The engine must never call a bare 'fetch everything' method."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "pipeline" / "engine.py").read_text()
        self.assertNotIn("SELECT * FROM knowledge_nodes", src)
        self.assertNotIn("list_all_nodes", src)

    def test_restricted_node_content_never_reaches_the_candidate_set(self):
        """End to end: nodes Priya may not see are absent, content and all."""
        from backend.pipeline.engine import EngineOptions
        got = self.eng.run(self.repo.get_user("U-PRIYA"), EngineOptions())
        blob = " ".join(c.content for c in got.candidate_set)
        # Content unique to nodes she is not cleared for.
        for secret in ["Rs 4.2 Cr", "Zimmer contract", "ATOM-2026",
                       "Board resolution", "L&T"]:
            self.assertNotIn(secret, blob,
                             f"restricted content leaked: {secret}")
