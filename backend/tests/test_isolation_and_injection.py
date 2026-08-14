"""
Check 1 (isolation) against a genuine second tenant, and Zone 2 injection
de-duplication.

The supplied seed data contains one organization, so `org_id = ?` always
matched everything and check 1 could never actually be observed doing its job.
These tests insert a second tenant as a TEST FIXTURE - it is not added to the
assessment seed data.
"""

import json
import unittest

from backend.pipeline.engine import EngineOptions
from backend.tests.conftest_helper import engine


class TestOrganizationIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()
        cls._insert_foreign_tenant(cls.repo)
        cls.eng._levels = None

    @classmethod
    def tearDownClass(cls):
        cls.repo._conn.execute("DELETE FROM knowledge_nodes WHERE org_id='rival'")
        cls.repo._conn.execute("DELETE FROM hierarchy_levels WHERE org_id='rival'")
        cls.repo._conn.execute("DELETE FROM organizations WHERE id='rival'")
        cls.repo._conn.commit()
        cls.eng._levels = None

    @staticmethod
    def _insert_foreign_tenant(repo):
        """A rival hospital, including a node planted on a tier id that Supra
        users genuinely traverse. Only org_id separates it."""
        repo._conn.execute(
            "INSERT OR REPLACE INTO organizations (id,name,segment,config) "
            "VALUES ('rival','Rival Hospital','hospital','{}')")
        repo._conn.execute(
            "INSERT OR REPLACE INTO hierarchy_levels "
            "(id,org_id,level_number,level_name,department,parent_ids,zone) "
            "VALUES ('HL-RIVAL-01','rival',1,'Rival Hospital',NULL,?,1)",
            (json.dumps([]),))
        rows = [
            # Planted directly on tiers Supra users reach, so ONLY check 1
            # can remove them.
            ("N-RIVAL-01", "HL-05-ORTHO", 1, "ortho", 0.10),
            ("N-RIVAL-02", "HL-10-ORTHO-W", 1, "ortho", 0.10),
            # And a rival Zone 2 node, which injection must not pick up.
            ("N-RIVAL-G1", "HL-GLOBAL", 2, None, 0.10),
        ]
        for nid, tier, zone, dept, deriv in rows:
            repo._conn.execute(
                "INSERT OR REPLACE INTO knowledge_nodes "
                "(id,org_id,hierarchy_level_id,type,title,content,importance,"
                "zone,status,derivability_score,compliance_tags,required_tags,"
                "department,hierarchy_level) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, "rival", tier, "FACT", "Rival tenant record",
                 "Belongs to another organization.", 0.90, zone, "ACTIVE",
                 deriv, json.dumps([]), ",", dept,
                 10 if "10" in tier else 5 if "05" in tier else 3))
        repo._conn.commit()

    def ids(self, uid, **kw):
        return {c.id for c in
                self.eng.run(self.repo.get_user(uid), EngineOptions(**kw)).candidate_set}

    def test_fixture_really_is_reachable_but_for_isolation(self):
        """Guard the guard: if the fixture were unreachable anyway, the tests
        below would pass for the wrong reason."""
        row = self.repo._conn.execute(
            "SELECT hierarchy_level_id h FROM knowledge_nodes WHERE id='N-RIVAL-02'"
        ).fetchone()
        self.assertEqual(row["h"], "HL-10-ORTHO-W")
        supra_here = self.repo._conn.execute(
            "SELECT COUNT(*) c FROM knowledge_nodes "
            "WHERE hierarchy_level_id='HL-10-ORTHO-W' AND org_id='supra'"
        ).fetchone()["c"]
        self.assertGreater(supra_here, 0, "Supra users do traverse this tier")

    def test_no_foreign_tenant_node_reaches_any_user(self):
        for uid in ["U-PRIYA", "U-VIKRAM", "U-ANANYA", "U-SHARMA",
                    "U-RAVI", "U-SUNITA", "U-SURESH"]:
            got = self.ids(uid)
            for nid in ["N-RIVAL-01", "N-RIVAL-02", "N-RIVAL-G1"]:
                self.assertNotIn(nid, got, f"{uid} received foreign tenant {nid}")

    def test_admin_is_not_exempt_from_isolation(self):
        """The most privileged user in the tenant still sees nothing of another
        tenant. Isolation is not a permission level."""
        self.assertNotIn("N-RIVAL-01", self.ids("U-SURESH"))

    def test_foreign_zone2_node_is_not_injected(self):
        """Zone 2 injection must be tenant-scoped, or a global node from
        another hospital would be broadcast into this one."""
        self.assertNotIn("N-RIVAL-G1", self.repo.zone2_node_ids("supra"))
        self.assertNotIn("N-RIVAL-G1", self.ids("U-PRIYA"))

    def test_node_counts_stay_tenant_scoped(self):
        self.assertEqual(self.repo.total_node_count("supra"), 50)
        self.assertEqual(self.repo.total_node_count("rival"), 3)

    def test_isolation_is_attributed_to_check_1(self):
        res = self.eng.run(self.repo.get_user("U-PRIYA"),
                           EngineOptions(include_audit=True))
        excluded = {e.node_id for e in res.exclusions}
        # The foreign rows never enter the candidate pool at all, which is
        # stronger than being excluded later: they are filtered by the base
        # org predicate before any check reasons about them.
        self.assertNotIn("N-RIVAL-02", excluded)
        self.assertNotIn("N-RIVAL-02", {c.id for c in res.candidate_set})


class TestZone2Injection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def ids_list(self, uid, **kw):
        return [c.id for c in
                self.eng.run(self.repo.get_user(uid), EngineOptions(**kw)).candidate_set]

    def test_candidate_set_contains_no_duplicates(self):
        """Injection merges the global set with the BFS set. If a global node
        also sat on the ancestor path it must still appear once."""
        for uid in ["U-PRIYA", "U-VIKRAM", "U-SURESH", "U-SUNITA"]:
            ids = self.ids_list(uid)
            self.assertEqual(len(ids), len(set(ids)), f"{uid} has duplicates")

    def test_duplicate_is_impossible_even_when_sets_overlap(self):
        """Force the overlap: put a zone-2 node on a tier Priya traverses, so
        it is both BFS-reachable and injected."""
        self.repo._conn.execute(
            "UPDATE knowledge_nodes SET hierarchy_level_id='HL-05-ORTHO', "
            "hierarchy_level=5 WHERE id='N-G01'")
        self.repo._conn.commit()
        try:
            ids = self.ids_list("U-PRIYA")
            self.assertEqual(ids.count("N-G01"), 1,
                             "a node in both the BFS set and the global set "
                             "must be returned once")
            self.assertEqual(len(ids), len(set(ids)))
        finally:
            self.repo._conn.execute(
                "UPDATE knowledge_nodes SET hierarchy_level_id='HL-GLOBAL', "
                "hierarchy_level=3 WHERE id='N-G01'")
            self.repo._conn.commit()

    def test_injection_widens_the_pool_then_the_checks_narrow_it(self):
        f = self.eng.run(self.repo.get_user("U-PRIYA"), EngineOptions()).funnel
        self.assertGreater(f["after_zone2"], f["after_bfs"])
        self.assertLessEqual(f["after_derivability"], f["after_zone2"])


if __name__ == "__main__":
    unittest.main()


class TestAdminEndpointGate(unittest.TestCase):
    """The exclusion trail names the nodes the pipeline withheld, so the
    /admin routes must not be readable by anyone who can reach the API."""

    def setUp(self):
        from backend.config import settings
        self._saved = settings.admin_token
        settings.admin_token = ""

    def tearDown(self):
        from backend.config import settings
        settings.admin_token = self._saved

    def test_loopback_is_allowed_so_the_local_demo_works(self):
        from backend import api
        api.require_admin("127.0.0.1")
        api.require_admin("::1")

    def test_remote_client_is_refused_when_no_token_is_configured(self):
        from backend import api
        with self.assertRaises(api.ApiError) as ctx:
            api.require_admin("203.0.113.9")
        self.assertEqual(ctx.exception.status, 404)

    def test_refusal_is_404_not_403(self):
        """A 403 would confirm the endpoint exists and has something behind
        it - the same disclosure silent exclusion prevents."""
        from backend import api
        with self.assertRaises(api.ApiError) as ctx:
            api.require_admin("203.0.113.9")
        self.assertEqual(ctx.exception.status, 404)
        self.assertNotIn("forbidden", ctx.exception.message.lower())
        self.assertNotIn("admin", ctx.exception.message.lower())

    def test_token_is_required_from_every_host_once_configured(self):
        from backend import api
        from backend.config import settings
        settings.admin_token = "s3cret"
        with self.assertRaises(api.ApiError):
            api.require_admin("127.0.0.1")           # loopback no longer enough
        with self.assertRaises(api.ApiError):
            api.require_admin("127.0.0.1", "wrong")
        api.require_admin("203.0.113.9", "s3cret")   # correct header passes

    def test_health_reports_whether_the_admin_api_is_token_protected(self):
        from backend import api
        from backend.config import settings
        repo, eng = engine()
        self.assertFalse(api.health(repo, eng)["admin_api_token_required"])
        settings.admin_token = "s3cret"
        self.assertTrue(api.health(repo, eng)["admin_api_token_required"])

    def test_cors_does_not_allow_a_wildcard_origin(self):
        """A wildcard would let any website read the trail from a browser."""
        from backend.config import settings
        self.assertNotIn("*", settings.cors_origins)
        self.assertTrue(all(o.startswith("http") for o in settings.cors_origins))

    def test_normal_pipeline_endpoint_is_not_gated(self):
        """The gate must not break the demo path."""
        repo, eng = engine()
        from backend import api
        r = api.run_pipeline(repo, eng, {"user": "U-PRIYA"})
        self.assertGreater(len(r["candidate_set"]), 0)
