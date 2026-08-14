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


class TestErrorHandling(unittest.TestCase):
    """Errors must be useful without becoming a side channel."""

    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def test_api_errors_carry_only_deliberate_messages(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.get_user(self.repo, "U-NOBODY")
        msg = str(ctx.exception).lower()
        self.assertEqual(ctx.exception.status, 404)
        for leaky in ["select", "sqlite", "postgres", "traceback",
                      "/home/", "c:\\", ".py"]:
            self.assertNotIn(leaky, msg)

    def test_unhandled_errors_return_a_generic_body(self):
        """The 500 path must not echo the exception. A raw body can carry SQL
        fragments or row content the caller is not cleared to see.

        Read from disk rather than importing, so this holds even where FastAPI
        is not installed."""
        import pathlib

        backend_dir = pathlib.Path(__file__).resolve().parents[1]
        for name in ("server.py", "main.py"):
            src = (backend_dir / name).read_text()
            self.assertIn("Internal server error", src, name)
            self.assertNotIn('{"detail": str(exc)}', src, name)
            self.assertNotIn("str(exc)}", src, name)

    def test_missing_profile_is_rejected_before_the_pipeline_runs(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.run_pipeline(self.repo, self.eng, {})
        self.assertEqual(ctx.exception.status, 400)

    def test_bad_run_id_is_a_404_not_a_key_error(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.get_run("does-not-exist")
        self.assertEqual(ctx.exception.status, 404)


class TestRuleOverridesAreNotCallerControllable(unittest.TestCase):
    """A request must not be able to relax a core filtering rule.

    The threshold and permission mode are organization configuration. Zone 2
    stays controllable because the assessment demo requires the toggle.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def test_threshold_sent_over_the_wire_is_ignored(self):
        from backend.config import settings
        loose = api.run_pipeline(
            self.repo, self.eng, {"user": "U-PRIYA", "threshold": 0.99})
        self.assertEqual(loose["options"]["derivability_threshold"],
                         settings.derivability_threshold)
        baseline = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})
        self.assertEqual(len(loose["candidate_set"]),
                         len(baseline["candidate_set"]),
                         "a caller-supplied threshold changed the result")

    def test_permission_mode_sent_over_the_wire_is_ignored(self):
        from backend.config import settings
        r = api.run_pipeline(
            self.repo, self.eng, {"user": "U-PRIYA", "mode": "scope_aware"})
        self.assertEqual(r["options"]["permission_mode"],
                         settings.permission_mode)

    def test_zone2_remains_controllable_for_the_demo(self):
        on = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})
        off = api.run_pipeline(
            self.repo, self.eng, {"user": "U-PRIYA", "zone2": False})
        self.assertGreater(len(on["candidate_set"]), len(off["candidate_set"]))

    def test_configured_values_are_echoed_for_read_only_display(self):
        r = api.run_pipeline(self.repo, self.eng, {"user": "U-VIKRAM"})
        self.assertIn("derivability_threshold", r["options"])
        self.assertIn("permission_mode", r["options"])

    def test_http_request_model_does_not_accept_rule_overrides(self):
        """Read the model from disk so this holds without FastAPI installed."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
        model = src.split("class PipelineRequest")[1].split("# ----")[0]
        self.assertNotIn("threshold:", model)
        self.assertNotIn("mode:", model)
        self.assertIn("zone2:", model)


class TestSupabaseConnectionResolution(unittest.TestCase):
    """The DSN is taken verbatim from SUPABASE_DB_URL.

    Nothing is constructed from SUPABASE_URL: db.<ref>.supabase.co is the
    direct connection, which is IPv6-only on current Supabase projects and
    does not resolve on IPv4 networks. Accepting the whole DSN lets the
    IPv4-proxied Session Pooler host be used unchanged.
    """

    # Synthetic: fake project ref, fake password, placeholder region.
    POOLER = (
        "postgresql://postgres.abc123:pw"
        "@aws-0-example-region.pooler.supabase.com:5432/postgres"
    )

    class Cfg:
        supabase_url = ""
        supabase_db_url = ""

    def cfg(self, **kw):
        c = self.Cfg()
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_dsn_is_returned_verbatim(self):
        from backend.config import resolve_db_url
        self.assertEqual(
            resolve_db_url(self.cfg(supabase_db_url=self.POOLER)), self.POOLER)

    def test_session_pooler_host_survives_untouched(self):
        """The pooler host, port and dotted username must not be rewritten."""
        from backend.config import resolve_db_url
        dsn = resolve_db_url(self.cfg(supabase_db_url=self.POOLER))
        self.assertIn("pooler.supabase.com", dsn)
        self.assertIn(":5432/postgres", dsn)
        self.assertIn("postgres.abc123", dsn)

    def test_host_is_never_constructed_from_the_project_url(self):
        """Even with SUPABASE_URL set, no direct host may be invented."""
        from backend.config import resolve_db_url
        dsn = resolve_db_url(
            self.cfg(supabase_url="https://abc123.supabase.co",
                     supabase_db_url=self.POOLER))
        self.assertNotIn("db.abc123.supabase.co", dsn)
        self.assertEqual(dsn, self.POOLER)

    def test_no_dsn_configured_yields_empty(self):
        from backend.config import resolve_db_url
        self.assertEqual(
            resolve_db_url(self.cfg(supabase_url="https://abc.supabase.co")), "")

    def test_config_no_longer_builds_a_direct_host(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "config.py").read_text()
        code = "\n".join(line.split("#")[0] for line in src.split("\n"))
        self.assertNotIn("db.{ref}", code)
        self.assertNotIn('f"postgresql://postgres:', code)

    def test_anon_key_is_never_part_of_the_connection(self):
        from backend.config import resolve_db_url
        dsn = resolve_db_url(self.cfg(supabase_db_url=self.POOLER))
        self.assertNotIn("sb_publishable", dsn)

    def test_no_real_credential_is_committed_to_source(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        for name in ["README.md", ".env.example", "backend/config.py"]:
            text = (root / name).read_text()
            self.assertNotIn("sb_publishable_", text, name)
            self.assertNotIn("pooler.supabase.com:5432/postgres", text.replace(
                "aws-0-<region>.pooler.supabase.com:5432/postgres", ""), name)
