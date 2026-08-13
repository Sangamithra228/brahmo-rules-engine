"""
Temporal edge cases and candidate metadata.

The supplied dataset contains a SUPERSEDED node but no node with an expiry
date, so the valid_until path is exercised with a fixture node inserted into
the test database. That fixture is a TEST ARTEFACT - it is not added to the
assessment seed data, which is left exactly as supplied.
"""

import json
import unittest

from backend.pipeline.candidate_assembler import _hint
from backend.pipeline.engine import EngineOptions
from backend.tests.conftest_helper import engine


class TestTemporal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()
        cls._insert_fixtures(cls.repo)

    @staticmethod
    def _insert_fixtures(repo):
        """Two fixture nodes on Priya's own ward tier, so BFS reaches them and
        only the temporal check can remove them."""
        rows = [
            ("N-TEST-EXPIRED", "expired ward notice", "2020-01-01T00:00:00+00:00",
             None, "ACTIVE"),
            ("N-TEST-FUTURE", "still-valid ward notice", "2099-01-01T00:00:00+00:00",
             None, "ACTIVE"),
            ("N-TEST-REPLACED", "replaced ward notice", None,
             "N-TEST-FUTURE", "ACTIVE"),
        ]
        for nid, title, valid_until, superseded_by, status in rows:
            repo._conn.execute(
                "INSERT OR REPLACE INTO knowledge_nodes "
                "(id,org_id,hierarchy_level_id,type,title,content,importance,"
                "zone,status,derivability_score,compliance_tags,required_tags,"
                "department,hierarchy_level,valid_until,superseded_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, "supra", "HL-10-ORTHO-W", "FACT", title,
                 "Ward-level fixture used to exercise the temporal check.",
                 0.50, 1, status, 0.10, json.dumps([]), ",", "ortho", 10,
                 valid_until, superseded_by),
            )
        repo._conn.commit()

    def ids(self, uid="U-PRIYA", **kw):
        u = self.repo.get_user(uid)
        return {c.id for c in self.eng.run(u, EngineOptions(**kw)).candidate_set}

    def test_node_past_its_valid_until_is_excluded(self):
        self.assertNotIn("N-TEST-EXPIRED", self.ids())

    def test_node_with_future_validity_survives(self):
        self.assertIn("N-TEST-FUTURE", self.ids())

    def test_node_pointing_at_a_replacement_is_excluded(self):
        """superseded_by is honoured even when status was never flipped."""
        self.assertIn("N-TEST-REPLACED", {r["id"] for r in self.repo._conn.execute(
            "SELECT id FROM knowledge_nodes").fetchall()})
        self.assertNotIn("N-TEST-REPLACED", self.ids())

    def test_superseded_status_is_excluded_from_the_seed_data(self):
        self.assertNotIn("N-M08", self.ids("U-SHARMA"))

    def test_temporal_check_is_the_one_doing_the_removing(self):
        """Attribute the exclusion to check 4, not to a later check."""
        u = self.repo.get_user("U-PRIYA")
        res = self.eng.run(u, EngineOptions(include_audit=True))
        by_id = {e.node_id: e.check for e in res.exclusions}
        self.assertEqual(by_id.get("N-TEST-EXPIRED"), "TEMPORAL")
        self.assertEqual(by_id.get("N-TEST-REPLACED"), "TEMPORAL")

    def test_time_can_be_pinned_for_reproducibility(self):
        past = self.ids(now="2019-01-01T00:00:00+00:00")
        self.assertIn("N-TEST-EXPIRED", past,
                      "with the clock set before expiry the node should survive")


class TestCompressionHint(unittest.TestCase):
    """distance -> hint, per the assessment specification."""

    def test_distance_zero_and_one_are_full(self):
        self.assertEqual(_hint(0, 0.5), "FULL")
        self.assertEqual(_hint(1, 0.5), "FULL")

    def test_distance_two_is_compressed(self):
        self.assertEqual(_hint(2, 0.5), "COMPRESSED")

    def test_distance_three_or_more_is_constraint_only(self):
        self.assertEqual(_hint(3, 0.5), "CONSTRAINT_ONLY")
        self.assertEqual(_hint(9, 0.5), "CONSTRAINT_ONLY")

    def test_life_safety_nodes_are_not_reduced_to_constraint_only(self):
        """A 0.99-importance contraindication keeps more of its wording than
        distance alone would allow."""
        self.assertEqual(_hint(4, 0.99), "COMPRESSED")

    def test_every_candidate_has_a_valid_hint(self):
        repo, eng = engine()
        for uid in ["U-PRIYA", "U-VIKRAM", "U-SURESH"]:
            for c in eng.run(repo.get_user(uid), EngineOptions()).candidate_set:
                self.assertIn(c.compression_hint,
                              ["FULL", "COMPRESSED", "CONSTRAINT_ONLY"])
                self.assertGreaterEqual(c.distance_from_entry, 0)


if __name__ == "__main__":
    unittest.main()
