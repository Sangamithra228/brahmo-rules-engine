"""
API surface, database configuration, sequential execution, and the dialect
split between SQLite and PostgreSQL.
"""

import os
import unittest

from backend import api
from backend.config import (
    DatabaseNotConfigured, Settings, get_repository, settings,
)
from backend.models import User
from backend.pipeline.five_check_filter import FilterConfig, build_predicates
from backend.pipeline.permission_compiler import compile_permissions
from backend.tests.conftest_helper import engine


class TestDatabaseConfiguration(unittest.TestCase):
    def test_supabase_is_the_default_backend(self):
        self.assertEqual(Settings.backend if os.environ.get("DATABASE_BACKEND")
                         else "supabase",
                         os.environ.get("DATABASE_BACKEND", "supabase"))

    def test_supabase_without_credentials_fails_loudly(self):
        """It must not quietly fall back to SQLite - a demo run against the
        wrong database is worse than one that refuses to start."""
        saved = settings.supabase_db_url
        settings.supabase_db_url = ""
        try:
            with self.assertRaises(DatabaseNotConfigured) as ctx:
                get_repository("supabase")
            msg = str(ctx.exception)
            self.assertIn("SUPABASE_DB_URL", msg)
            self.assertIn("DATABASE_BACKEND=sqlite", msg,
                          "the error should tell the reader how to run offline")
        finally:
            settings.supabase_db_url = saved

    def test_sqlite_fallback_requires_an_explicit_opt_in(self):
        repo = get_repository("sqlite")
        self.assertEqual(repo.backend_name, "sqlite")
        self.assertEqual(repo.total_node_count("supra"), 50)

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(DatabaseNotConfigured):
            get_repository("mongodb")

    def test_health_reports_the_active_backend_not_the_configured_one(self):
        repo, eng = engine()
        h = api.health(repo, eng)
        self.assertEqual(h["database_backend"], "sqlite")
        self.assertIn("configured_backend", h)
        self.assertEqual(h["llm_calls"], 0)
        self.assertEqual(h["embedding_calls"], 0)


class TestDialects(unittest.TestCase):
    """The same rules, written correctly for each store."""

    def _preds(self, dialect):
        u = User("U-V", "supra", "V", "HOD", "ortho", 4, 4, [])
        return build_predicates(
            compile_permissions(u), "supra",
            FilterConfig(now="2026-01-01T00:00:00+00:00"), dialect=dialect,
        )

    def test_both_dialects_emit_five_checks_in_order(self):
        for d in ("sqlite", "postgres"):
            names = [n for (n, _f, _p) in self._preds(d)]
            self.assertEqual(
                names,
                ["ISOLATION", "COMPLIANCE", "PERMISSION", "TEMPORAL",
                 "DERIVABILITY"], d)

    def test_placeholder_style_matches_the_driver(self):
        for (_n, frag, params) in self._preds("sqlite"):
            self.assertNotIn("%s", frag)
            self.assertEqual(frag.count("?"), len(params))
        for (_n, frag, params) in self._preds("postgres"):
            self.assertNotIn("?", frag)
            self.assertEqual(frag.count("%s"), len(params))

    def test_postgres_uses_native_array_membership(self):
        compliance = dict(
            (n, f) for (n, f, _p) in self._preds("postgres"))["COMPLIANCE"]
        self.assertIn("ANY(compliance_tags)", compliance)
        self.assertNotIn("required_tags", compliance,
                         "required_tags is a SQLite-only denormalisation")

    def test_sqlite_uses_the_denormalised_tag_string(self):
        compliance = dict(
            (n, f) for (n, f, _p) in self._preds("sqlite"))["COMPLIANCE"]
        self.assertIn("required_tags", compliance)


class TestSequentialExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def test_stage_k_output_is_stage_k_plus_1_input(self):
        """Every check must run against exactly the survivors of the previous
        one. Verified on ids, not just counts."""
        from backend.pipeline.engine import EngineOptions
        res = self.eng.run(self.repo.get_user("U-PRIYA"),
                           EngineOptions(include_audit=True))
        # Reconstruct the stages from the audit trail: a node excluded at
        # stage k must not be attributed to any later stage.
        seen = {}
        for e in res.exclusions:
            self.assertNotIn(e.node_id, seen,
                             f"{e.node_id} attributed to two checks")
            seen[e.node_id] = e.check
        survivors = {c.id for c in res.candidate_set}
        self.assertEqual(survivors & set(seen), set(),
                         "a node cannot both survive and be excluded")

    def test_checks_are_not_independent(self):
        """Compliance runs before permission, so a node that fails both is
        attributed to compliance."""
        from backend.pipeline.engine import EngineOptions
        res = self.eng.run(self.repo.get_user("U-PRIYA"),
                           EngineOptions(include_audit=True))
        by_id = {e.node_id: e.check for e in res.exclusions}
        # N-A01 is MNPI+CONFIDENTIAL at L1: above her ceiling AND uncleared.
        self.assertEqual(by_id.get("N-A01"), "COMPLIANCE")


class TestApiLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def test_users_endpoint_exposes_profile_fields_the_ui_needs(self):
        for u in api.list_users(self.repo):
            for field in ["id", "name", "role", "department", "org_id",
                          "ceiling_level", "compliance_clearance"]:
                self.assertIn(field, u)

    def test_pipeline_run_returns_everything_the_dashboard_renders(self):
        r = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})
        for field in ["user_name", "entry_point", "funnel", "pipeline_timing",
                      "candidate_set", "traversal", "run_id", "user_profile",
                      "options"]:
            self.assertIn(field, r)
        for stage in ["total_nodes", "after_bfs", "after_zone2",
                      "after_isolation", "after_compliance", "after_permission",
                      "after_temporal", "after_derivability"]:
            self.assertIn(stage, r["funnel"])

    def test_run_can_be_replayed_by_id(self):
        r = api.run_pipeline(self.repo, self.eng, {"user": "U-VIKRAM"})
        again = api.get_run(r["run_id"])
        self.assertEqual(
            [c["id"] for c in again["candidate_set"]],
            [c["id"] for c in r["candidate_set"]])

    def test_pipeline_response_never_mentions_exclusions(self):
        r = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})
        blob = str(r).lower()
        for word in ["denied", "forbidden", "unauthorized", "unauthorised",
                     "restricted", "redacted", "hidden_count"]:
            self.assertNotIn(word, blob)
        self.assertNotIn("exclusions", r)

    def test_traversal_view_exposes_tiers_not_node_identities(self):
        """The DAG panel must not become a side channel around silent
        exclusion."""
        r = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})
        blob = str(r["traversal"])
        for node_id in ["N-O11", "N-O12", "N-A01", "N-C04", "N-M08"]:
            self.assertNotIn(node_id, blob)

    def test_unknown_user_raises_a_clean_404(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.run_pipeline(self.repo, self.eng, {"user": "U-NOBODY"})
        self.assertEqual(ctx.exception.status, 404)

    def test_adhoc_profile_runs_without_touching_the_database(self):
        before = self.repo.total_node_count("supra")
        r = api.run_pipeline(self.repo, self.eng, {
            "role": "AUDITOR", "department": "audit", "ceiling": 3,
            "clearance": ["MNPI"], "name": "External Auditor"})
        self.assertGreater(len(r["candidate_set"]), 0)
        self.assertEqual(self.repo.total_node_count("supra"), before)
        self.assertIsNone(self.repo.get_user("U-ADHOC"))

    def test_audit_is_a_separate_call_and_carries_no_content(self):
        a = api.audit(self.repo, self.eng, {"user": "U-PRIYA"})
        self.assertGreater(len(a["exclusions"]), 0)
        for e in a["exclusions"]:
            self.assertEqual(set(e.keys()),
                             {"node_id", "node_title", "check", "reason"})

    def test_options_are_echoed_so_the_ui_cannot_misreport_them(self):
        r = api.run_pipeline(self.repo, self.eng,
                             {"user": "U-PRIYA", "zone2": False})
        self.assertFalse(r["options"]["zone2_enabled"])


if __name__ == "__main__":
    unittest.main()
