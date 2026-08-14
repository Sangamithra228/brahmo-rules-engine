"""
BFS traversal: upward only, FIFO queue, visited set, multi-parent, cycles.
"""

import unittest

from backend.data.seed_data import HIERARCHY_LEVELS
from backend.models import HierarchyLevel
from backend.pipeline.bfs_traversal import (
    detect_cycles, traverse, would_create_cycle,
)


def levels():
    return [HierarchyLevel(i, "supra", n, nm, d, list(p), z)
            for (i, n, nm, d, p, z) in HIERARCHY_LEVELS]


class TestUpwardTraversal(unittest.TestCase):
    def test_walks_upward_to_root(self):
        r = traverse("HL-10-ORTHO-W", levels())
        for expected in ["HL-08-ORTHO-GEN", "HL-05-ORTHO", "HL-03-CLIN", "HL-01"]:
            self.assertIn(expected, r.reachable, f"{expected} not reached")

    def test_distances_are_shortest(self):
        r = traverse("HL-10-ORTHO-W", levels())
        self.assertEqual(r.reachable["HL-10-ORTHO-W"], 0)
        self.assertEqual(r.reachable["HL-08-ORTHO-GEN"], 1)
        self.assertEqual(r.reachable["HL-05-ORTHO"], 2)
        self.assertEqual(r.reachable["HL-03-CLIN"], 3)
        self.assertEqual(r.reachable["HL-01"], 4)

    def test_distance_increases_monotonically_up_the_chain(self):
        """FIFO order means a tier is first dequeued via a shortest path."""
        by_id = {l.id: l for l in levels()}
        r = traverse("HL-10-ORTHO-W", levels())
        for level_id, distance in r.reachable.items():
            for parent in by_id[level_id].parent_ids:
                if parent in r.reachable:
                    self.assertLessEqual(
                        r.reachable[parent], distance + 1,
                        f"{parent} recorded further than one hop above {level_id}")

    def test_does_not_walk_downward(self):
        """A user inherits the tiers ABOVE them, never those beneath.

        From the Ortho Ward the TKR Unit, the Post-TKR area and the patient
        tier are all siblings or descendants, not ancestors, so an upward walk
        must not reach them.
        """
        r = traverse("HL-10-ORTHO-W", levels())
        for below in ["HL-12-RAJAN", "HL-08-ORTHO-TKR", "HL-08-POST-TKR"]:
            self.assertNotIn(below, r.reachable,
                             f"{below} is not an ancestor of the Ortho Ward")

    def test_root_entry_reaches_only_itself(self):
        r = traverse("HL-01", levels())
        self.assertEqual(set(r.reachable), {"HL-01"})

    def test_reaches_only_genuine_ancestors(self):
        """Every tier reached must be an ancestor of the entry point."""
        by_id = {l.id: l for l in levels()}
        entry = "HL-10-ORTHO-W"
        ancestors, stack = set(), [entry]
        while stack:
            cur = stack.pop()
            for p in by_id[cur].parent_ids:
                if p not in ancestors:
                    ancestors.add(p)
                    stack.append(p)
        r = traverse(entry, levels())
        self.assertEqual(set(r.reachable) - {entry}, ancestors)

    def test_no_cross_department_reach(self):
        """Department isolation falls out of the DAG's shape: Cardiology is
        never an ancestor of the Ortho Ward."""
        r = traverse("HL-10-ORTHO-W", levels())
        for foreign in ["HL-05-CARDIO", "HL-05-PAEDS", "HL-05-MED",
                        "HL-05-ICU", "HL-05-SURG", "HL-10-MED-W",
                        "HL-12-PADMA", "HL-03-ADMIN"]:
            self.assertNotIn(foreign, r.reachable)


class TestMultiParent(unittest.TestCase):
    """Post-TKR Protocol has parent_ids = [Ortho, Surgery]."""

    def test_both_parents_are_reached(self):
        r = traverse("HL-08-POST-TKR", levels())
        self.assertIn("HL-05-ORTHO", r.reachable)
        self.assertIn("HL-05-SURG", r.reachable)
        self.assertEqual(r.reachable["HL-05-ORTHO"], 1)
        self.assertEqual(r.reachable["HL-05-SURG"], 1)

    def test_converging_ancestor_processed_once(self):
        """Both parents lead to Clinical Division. The visited set means it is
        expanded once, at its shortest distance."""
        r = traverse("HL-08-POST-TKR", levels())
        self.assertEqual(r.reachable["HL-03-CLIN"], 2)
        self.assertIn("HL-03-CLIN", r.multi_parent_hits)
        self.assertEqual(r.nodes_visited, len(r.reachable))

    def test_no_tier_appears_twice(self):
        r = traverse("HL-08-POST-TKR", levels())
        self.assertEqual(len(set(r.reachable)), len(r.reachable))


class TestCycleProtection(unittest.TestCase):
    def test_seed_graph_is_acyclic(self):
        self.assertEqual(detect_cycles(levels()), [])

    def test_traversal_terminates_on_a_cyclic_graph(self):
        """The visited set is the runtime guarantee. Inject a real cycle and
        prove the walk halts rather than looping."""
        patched = []
        for l in levels():
            if l.id == "HL-01":
                patched.append(HierarchyLevel(
                    l.id, l.org_id, l.level_number, l.level_name,
                    l.department, ["HL-10-ORTHO-W"], l.zone))
            else:
                patched.append(l)
        self.assertNotEqual(detect_cycles(patched), [],
                            "cycle should be detected at load time")
        r = traverse("HL-10-ORTHO-W", patched)  # must not hang
        self.assertGreater(len(r.reachable), 0)
        self.assertEqual(r.nodes_visited, len(r.reachable))

    def test_insert_time_cycle_guard(self):
        ls = levels()
        self.assertTrue(would_create_cycle(ls, "HL-01", "HL-10-ORTHO-W"))
        self.assertFalse(would_create_cycle(ls, "HL-05-MED", "HL-05-ORTHO"))

    def test_unknown_entry_point_is_rejected(self):
        with self.assertRaises(ValueError):
            traverse("HL-DOES-NOT-EXIST", levels())


if __name__ == "__main__":
    unittest.main()
