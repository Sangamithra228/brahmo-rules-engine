import unittest

from backend.pipeline.engine import EngineOptions
from backend.tests.conftest_helper import engine


class TestFiveChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def run_for(self, uid, **kw):
        return self.eng.run(self.repo.get_user(uid), EngineOptions(**kw))

    def ids(self, uid, **kw):
        return {c.id for c in self.run_for(uid, **kw).candidate_set}

    # ---- ordering ----------------------------------------------------
    def test_checks_run_in_the_specified_order(self):
        f = self.run_for("U-PRIYA").funnel
        keys = [k for k in f if k.startswith("after_")]
        self.assertEqual(
            keys,
            ["after_bfs", "after_zone2", "after_isolation", "after_compliance",
             "after_permission", "after_temporal", "after_derivability"],
        )

    def test_each_check_is_monotonically_narrowing(self):
        """Output of check N is the input to check N+1, so counts can only
        stay level or fall."""
        for uid in ["U-PRIYA", "U-VIKRAM", "U-ANANYA", "U-SHARMA",
                    "U-RAVI", "U-SUNITA", "U-SURESH"]:
            f = self.run_for(uid).funnel
            seq = [f["after_zone2"], f["after_isolation"], f["after_compliance"],
                   f["after_permission"], f["after_temporal"],
                   f["after_derivability"]]
            for a, b in zip(seq, seq[1:]):
                self.assertGreaterEqual(a, b, f"{uid} count grew: {seq}")

    # ---- check 1: isolation ------------------------------------------
    def test_isolation_keeps_only_the_users_org(self):
        f = self.run_for("U-SURESH").funnel
        self.assertEqual(f["after_isolation"], f["after_zone2"])

    # ---- check 2: compliance -----------------------------------------
    def test_mnpi_hidden_from_uncleared_user(self):
        self.assertNotIn("N-O11", self.ids("U-PRIYA"))
        self.assertNotIn("N-O12", self.ids("U-PRIYA"))

    def test_hod_sees_own_department_mnpi_but_not_confidential(self):
        v = self.ids("U-VIKRAM")
        self.assertIn("N-O11", v, "HOD should see own-dept MNPI budget node")
        self.assertNotIn("N-O12", v, "MNPI+CONFIDENTIAL needs admin clearance")

    def test_admin_sees_confidential(self):
        s = self.ids("U-SURESH")
        self.assertIn("N-A01", s)
        self.assertIn("N-C04", s)

    # ---- check 3: permission -----------------------------------------
    def test_ceiling_excludes_tiers_above_the_user(self):
        """Sunita clears MNPI, so compliance lets the budget node through.
        Only the ceiling stops her - which is the check doing real work."""
        f = self.run_for("U-SUNITA").funnel
        self.assertLess(f["after_permission"], f["after_compliance"])
        self.assertNotIn("N-O11", self.ids("U-SUNITA"))

    def test_zone2_survives_the_ceiling(self):
        """A ward nurse's ceiling must not delete hospital-wide drug safety."""
        self.assertIn("N-G01", self.ids("U-PRIYA"))

    # ---- check 4: temporal -------------------------------------------
    def test_superseded_node_excluded_for_everyone(self):
        for uid in ["U-PRIYA", "U-ANANYA", "U-SHARMA", "U-SURESH"]:
            self.assertNotIn("N-M08", self.ids(uid), f"{uid} saw Sepsis v2")

    def test_current_version_survives_for_medicine_users(self):
        self.assertIn("N-M02", self.ids("U-SHARMA"))

    def test_legal_hold_is_not_treated_as_expired(self):
        """LEGAL_HOLD restricts modification, not reading."""
        self.assertIn("N-A04", self.ids("U-SURESH"))

    # ---- check 5: derivability ---------------------------------------
    def test_general_knowledge_excluded_from_every_user(self):
        for uid in ["U-PRIYA", "U-VIKRAM", "U-ANANYA", "U-SHARMA",
                    "U-RAVI", "U-SUNITA", "U-SURESH"]:
            got = self.ids(uid)
            for nid in ["N-D01", "N-D02", "N-D03", "N-D04", "N-D05"]:
                self.assertNotIn(nid, got, f"{uid} got derivable {nid}")

    def test_threshold_is_configurable(self):
        loose = self.ids("U-SURESH", derivability_threshold=0.99)
        tight = self.ids("U-SURESH", derivability_threshold=0.2)
        self.assertGreater(len(loose), len(tight))

    def test_org_specific_node_about_a_generic_drug_survives(self):
        """'Paracetamol is an analgesic' goes; 'Supra uses Paracetamol 650mg
        QDS post-TKR' stays."""
        v = self.ids("U-VIKRAM")
        self.assertIn("N-O02", v)
        self.assertNotIn("N-D02", v)


if __name__ == "__main__":
    unittest.main()
