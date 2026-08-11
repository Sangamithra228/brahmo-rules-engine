import unittest

from backend.models import User
from backend.pipeline.permission_compiler import compile_permissions


def u(role, dept, ceiling, wceil=None, clearance=None):
    return User("U-T", "supra", "Test", role, dept, ceiling, wceil,
                clearance or [])


class TestPermissionCompiler(unittest.TestCase):
    def test_produces_o1_lookup_over_all_15_levels(self):
        c = compile_permissions(u("VIEWER", "ortho", 10))
        self.assertEqual(sorted(c.level_map.keys()), list(range(1, 16)))
        self.assertIsInstance(c.level_map[10], dict)

    def test_viewer_reads_at_or_below_ceiling_only(self):
        c = compile_permissions(u("VIEWER", "ortho", 10))
        self.assertTrue(c.can_read_level(10))
        self.assertTrue(c.can_read_level(12))
        self.assertFalse(c.can_read_level(8))
        self.assertFalse(c.can_read_level(5))

    def test_viewer_cannot_write_anywhere(self):
        c = compile_permissions(u("VIEWER", "ortho", 10))
        self.assertFalse(any(v["can_write"] for v in c.level_map.values()))

    def test_hod_reads_all_levels(self):
        c = compile_permissions(u("HOD", "ortho", 4, 4))
        self.assertTrue(all(v["can_read"] for v in c.level_map.values()))

    def test_hod_mnpi_is_scoped_to_own_department(self):
        c = compile_permissions(u("HOD", "ortho", 4, 4))
        self.assertTrue(c.clears_tags(["MNPI"], "ortho"))
        self.assertFalse(c.clears_tags(["MNPI"], "cardiology"))

    def test_all_tags_required_not_any(self):
        c = compile_permissions(u("HOD", "ortho", 4, 4))
        self.assertFalse(c.clears_tags(["MNPI", "CONFIDENTIAL"], "ortho"))

    def test_admin_clears_everything(self):
        c = compile_permissions(
            u("ADMIN", "admin", 1, 1, ["MNPI", "PHI", "CONFIDENTIAL"]))
        self.assertTrue(c.clears_tags(["MNPI", "CONFIDENTIAL"], "cardiology"))

    def test_untagged_node_visible_to_everyone(self):
        c = compile_permissions(u("VIEWER", "ortho", 10))
        self.assertTrue(c.clears_tags([], "ortho"))

    def test_unknown_role_fails_closed(self):
        c = compile_permissions(u("SUPERUSER_LOL", "ortho", 1))
        self.assertFalse(c.clears_tags(["MNPI"], "ortho"))
        self.assertEqual(c.policy.role, "UNKNOWN")

    def test_explicit_clearance_is_not_department_scoped(self):
        """Sunita's MNPI is granted on her user row, so it works everywhere."""
        c = compile_permissions(u("QUALITY", "quality", 6, 8, ["MNPI"]))
        self.assertTrue(c.clears_tags(["MNPI"], "ortho"))
        self.assertTrue(c.clears_tags(["MNPI"], "cardiology"))
        self.assertFalse(c.clears_tags(["CONFIDENTIAL"], "cardiology"))


if __name__ == "__main__":
    unittest.main()
