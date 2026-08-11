"""
The surprise test: profiles that do NOT exist in the seed data.

These users are constructed here, never inserted, never referenced by any
module. If the pipeline handles them, the five checks really are driven by
user-profile data rather than by role names baked into the code.

The three shapes the assessment names explicitly:
  Pharmacist       VIEWER,  L12, department with no home in the DAG
  Quality Officer  QUALITY, L6,  cross-department
  External Auditor AUDITOR, L3,  read-only, MNPI-cleared
"""

import unittest

from backend.models import User
from backend.pipeline.engine import EngineOptions
from backend.tests.conftest_helper import engine


def profile(uid, role, dept, ceiling, wceil=None, clearance=None):
    return User(uid, "supra", uid.title(), role, dept, ceiling, wceil,
                clearance or [])


class TestSurpriseUsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def ids(self, user, **kw):
        return {c.id for c in self.eng.run(user, EngineOptions(**kw)).candidate_set}

    # ---- the three named shapes ---------------------------------------
    def test_pharmacist_runs_without_code_changes(self):
        p = profile("U-PHARM", "VIEWER", "pharmacy", 12)
        got = self.ids(p)
        self.assertGreater(len(got), 0)
        self.assertIn("N-G01", got, "must still receive global drug safety")
        self.assertNotIn("N-O11", got, "no MNPI clearance")

    def test_quality_officer_reaches_across_departments(self):
        q = profile("U-QO", "QUALITY", "quality", 6, 8, ["MNPI"])
        got = self.ids(q)
        depts = {c.department for c in
                 self.eng.run(q, EngineOptions()).candidate_set}
        self.assertGreaterEqual(
            len([d for d in depts if d]), 2,
            "a cross-department role should see more than one department")

    def test_external_auditor_sees_mnpi_but_is_still_ceiling_limited(self):
        a = profile("U-AUDIT", "AUDITOR", "audit", 3)
        got = self.ids(a)
        self.assertIn("N-O11", got,
                      "auditor clearance should let MNPI through check 2")
        self.assertNotIn("N-O12", got,
                         "MNPI+CONFIDENTIAL still needs admin clearance")

    def test_auditor_is_read_only(self):
        from backend.pipeline.permission_compiler import compile_permissions
        c = compile_permissions(profile("U-AUDIT", "AUDITOR", "audit", 3))
        self.assertFalse(any(v["can_write"] for v in c.level_map.values()))

    # ---- anti-hardcoding probes ---------------------------------------
    def test_new_user_does_not_reproduce_priyas_result(self):
        pharm = self.ids(profile("U-PHARM", "VIEWER", "pharmacy", 12))
        priya = self.ids(self.repo.get_user("U-PRIYA"))
        self.assertNotEqual(pharm, priya, "output looks hardcoded to Priya")

    def test_ceiling_alone_changes_the_result(self):
        """Same role, same department, different ceiling -> different set."""
        a = self.ids(profile("U-X1", "VIEWER", "ortho", 10))
        b = self.ids(profile("U-X2", "VIEWER", "ortho", 5))
        self.assertNotEqual(a, b)

    def test_department_alone_changes_the_result(self):
        a = self.ids(profile("U-Y1", "VIEWER", "ortho", 10))
        b = self.ids(profile("U-Y2", "VIEWER", "medicine", 10))
        self.assertNotEqual(a, b)

    def test_clearance_alone_changes_the_result(self):
        plain = self.ids(profile("U-Z1", "HOD", "cardiology", 4, 4))
        cleared = self.ids(
            profile("U-Z2", "HOD", "cardiology", 4, 4, ["CONFIDENTIAL"]))
        self.assertIn("N-C04", cleared)
        self.assertNotIn("N-C04", plain)

    def test_a_department_that_does_not_exist_degrades_safely(self):
        """No crash, no leak. Falls back to root, gets globals only."""
        got = self.ids(profile("U-NEW", "VIEWER", "radiology", 9))
        self.assertGreater(len(got), 0)
        for nid in ["N-O11", "N-O12", "N-A01", "N-C04"]:
            self.assertNotIn(nid, got)

    def test_unknown_role_is_not_granted_privilege(self):
        got = self.ids(profile("U-WAT", "CHIEF_WIZARD", "ortho", 1))
        for nid in ["N-O11", "N-O12", "N-A01", "N-A02", "N-C04"]:
            self.assertNotIn(nid, got, "unknown role must fail closed")

    def test_timing_varies_with_reach_not_fixed(self):
        """A fixed runtime regardless of user would suggest nothing is
        actually being traversed."""
        small = self.eng.run(profile("U-S", "VIEWER", "ortho", 12))
        large = self.eng.run(self.repo.get_user("U-SURESH"))
        self.assertNotEqual(small.funnel["after_bfs"],
                            large.funnel["after_bfs"])


if __name__ == "__main__":
    unittest.main()
