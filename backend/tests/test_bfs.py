import unittest

from backend.data.seed_data import HIERARCHY_LEVELS
from backend.models import HierarchyLevel
from backend.pipeline.bfs_traversal import (
    detect_cycles, traverse, would_create_cycle,
)


def levels():
    return [HierarchyLevel(i, "supra", n, nm, d, list(p), z)
            for (i, n, nm, d, p, z) in HIERARCHY_LEVELS]


class TestBFS(unittest.TestCase):
    def test_walks_upward_to_root(self):
        r = traverse("HL-10-ORTHO-W", levels(), "ortho")
        for expected in ["HL-08-ORTHO-GEN", "HL-05-ORTHO", "HL-03-CLIN", "HL-01"]:
            self.assertIn(expected, r.reachable, f"{expected} not reached")

    def test_distances_are_shortest(self):
        r = traverse("HL-10-ORTHO-W", levels(), "ortho")
        self.assertEqual(r.reachable["HL-10-ORTHO-W"], 0)
        self.assertEqual(r.reachable["HL-08-ORTHO-GEN"], 1)
        self.assertEqual(r.reachable["HL-05-ORTHO"], 2)
        self.assertEqual(r.reachable["HL-01"], 4)

    def test_multi_parent_node_processed_once(self):
        """Post-TKR has parents [Ortho, Surgery]. It must appear exactly once."""
        r = traverse("HL-05-ORTHO", levels(), "ortho")
        self.assertIn("HL-08-POST-TKR", r.reachable)
        self.assertEqual(
            list(r.reachable.keys()).count("HL-08-POST-TKR"), 1
        )
        self.assertEqual(r.nodes_visited, len(r.reachable))

    def test_multi_parent_does_not_bridge_into_other_department(self):
        """Reaching a jointly-owned node must not hand over the co-owner's
        department."""
        r = traverse("HL-10-ORTHO-W", levels(), "ortho")
        self.assertNotIn("HL-05-SURG", r.reachable)
        self.assertIn("HL-05-SURG", r.blocked_foreign_parents)

    def test_no_cross_department_reach(self):
        r = traverse("HL-10-ORTHO-W", levels(), "ortho")
        for foreign in ["HL-05-CARDIO", "HL-05-PAEDS", "HL-05-MED",
                        "HL-05-ICU", "HL-10-MED-W", "HL-12-PADMA"]:
            self.assertNotIn(foreign, r.reachable)

    def test_cross_department_flag_opens_everything(self):
        r = traverse("HL-01", levels(), "admin", cross_department=True)
        self.assertEqual(len(r.reachable), len(levels()))

    def test_seed_graph_is_acyclic(self):
        self.assertEqual(detect_cycles(levels()), [])

    def test_bfs_terminates_on_a_cyclic_graph(self):
        """Visited set is the runtime guarantee. Inject a cycle and prove the
        traversal still halts."""
        ls = levels()
        patched = []
        for l in ls:
            if l.id == "HL-01":
                patched.append(HierarchyLevel(
                    l.id, l.org_id, l.level_number, l.level_name,
                    l.department, ["HL-10-ORTHO-W"], l.zone))
            else:
                patched.append(l)
        self.assertNotEqual(detect_cycles(patched), [],
                            "cycle should be detected")
        r = traverse("HL-10-ORTHO-W", patched, "ortho")  # must not hang
        self.assertGreater(len(r.reachable), 0)

    def test_insert_time_cycle_guard(self):
        ls = levels()
        self.assertTrue(would_create_cycle(ls, "HL-01", "HL-10-ORTHO-W"))
        self.assertFalse(would_create_cycle(ls, "HL-05-MED", "HL-05-ORTHO"))


if __name__ == "__main__":
    unittest.main()
