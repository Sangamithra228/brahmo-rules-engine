import hashlib
import json
import unittest

from backend.pipeline.engine import EngineOptions
from backend.tests.conftest_helper import engine

ALL = ["U-PRIYA", "U-VIKRAM", "U-ANANYA", "U-SHARMA", "U-RAVI",
       "U-SUNITA", "U-SURESH"]


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def run_for(self, uid, **kw):
        return self.eng.run(self.repo.get_user(uid), EngineOptions(**kw))

    def ids(self, uid, **kw):
        return {c.id for c in self.run_for(uid, **kw).candidate_set}

    # ---- the headline property ---------------------------------------
    def test_same_graph_different_users_different_results(self):
        sets = {u: self.ids(u) for u in ALL}
        distinct = {frozenset(v) for v in sets.values()}
        self.assertGreaterEqual(
            len(distinct), 6,
            f"pipeline is not differentiating: {[len(v) for v in sets.values()]}",
        )

    def test_privilege_ordering_holds(self):
        self.assertLess(len(self.ids("U-PRIYA")), len(self.ids("U-VIKRAM")))
        self.assertLess(len(self.ids("U-VIKRAM")), len(self.ids("U-SURESH")))

    def test_entry_points_differ_by_user(self):
        self.assertEqual(self.run_for("U-PRIYA").entry_point, "HL-10-ORTHO-W")
        self.assertEqual(self.run_for("U-VIKRAM").entry_point, "HL-05-ORTHO")
        self.assertEqual(self.run_for("U-ANANYA").entry_point, "HL-08-MED-GEN")
        self.assertEqual(self.run_for("U-SHARMA").entry_point, "HL-05-MED")

    # ---- isolation ----------------------------------------------------
    def test_priya_sees_no_other_department(self):
        for c in self.run_for("U-PRIYA").candidate_set:
            self.assertIn(c.department, (None, "ortho"),
                          f"leaked {c.id} from {c.department}")

    def test_ortho_and_medicine_users_do_not_overlap_on_dept_nodes(self):
        p = {c.id for c in self.run_for("U-PRIYA").candidate_set
             if c.department == "ortho"}
        a = {c.id for c in self.run_for("U-ANANYA").candidate_set
             if c.department == "medicine"}
        self.assertEqual(p & a, set())

    # ---- silent exclusion --------------------------------------------
    def test_public_response_reveals_nothing_about_exclusions(self):
        body = json.dumps(self.run_for("U-PRIYA").to_public_dict()).lower()
        for word in ["denied", "forbidden", "unauthorized", "unauthorised",
                     "restricted", "hidden", "redacted", "excluded"]:
            self.assertNotIn(word, body)

    def test_no_placeholder_rows_for_removed_nodes(self):
        res = self.run_for("U-PRIYA")
        self.assertEqual(len(res.candidate_set), res.funnel["after_derivability"])

    def test_audit_trail_is_opt_in_and_separate(self):
        plain = self.run_for("U-PRIYA")
        self.assertEqual(plain.exclusions, [])
        audited = self.run_for("U-PRIYA", include_audit=True)
        self.assertGreater(len(audited.exclusions), 0)
        self.assertNotIn("exclusions", audited.to_public_dict())

    # ---- zone 2 -------------------------------------------------------
    def test_zone2_toggle_changes_the_result(self):
        on = self.ids("U-PRIYA")
        off = self.ids("U-PRIYA", zone2_enabled=False)
        self.assertGreater(len(on), len(off))
        self.assertIn("N-G01", on)
        self.assertNotIn("N-G01", off)

    def test_zone2_nodes_still_pass_through_all_five_checks(self):
        """N-G04 (0.75) and N-G06 (0.80) are Zone 2 but derivable, so they
        must still be removed by check 5."""
        got = self.ids("U-PRIYA")
        self.assertNotIn("N-G04", got)
        self.assertNotIn("N-G06", got)

    # ---- annotation ---------------------------------------------------
    def test_every_candidate_carries_the_contract_fields(self):
        for c in self.run_for("U-VIKRAM").candidate_set:
            d = c.to_dict()
            for key in ["id", "type", "title", "content", "importance", "zone",
                        "hierarchy_level", "distance_from_entry",
                        "compression_hint", "source"]:
                self.assertIn(key, d)
            self.assertIn(d["compression_hint"],
                          ["FULL", "COMPRESSED", "CONSTRAINT_ONLY"])

    def test_compression_hint_tracks_distance(self):
        for c in self.run_for("U-PRIYA").candidate_set:
            if c.distance_from_entry <= 1:
                self.assertEqual(c.compression_hint, "FULL")

    # ---- determinism and performance ----------------------------------
    def test_output_is_byte_identical_across_runs(self):
        def digest():
            d = self.run_for("U-VIKRAM", now="2026-08-12T00:00:00+00:00")
            payload = d.to_public_dict()
            payload.pop("pipeline_timing")
            return hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest(), digest())
        self.assertEqual(digest(), digest())

    def test_pipeline_is_well_under_the_500ms_budget(self):
        for uid in ALL:
            total = self.run_for(uid).timing_ms["total_ms"]
            self.assertLess(total, 500.0, f"{uid} took {total}ms")

    # ---- no LLM -------------------------------------------------------
    def test_no_network_or_model_imports_anywhere_in_the_pipeline(self):
        import pathlib
        banned = ["openai", "anthropic", "requests", "httpx", "urllib.request",
                  "transformers", "sentence_transformers", "langchain",
                  "socket"]
        root = pathlib.Path(__file__).resolve().parents[1] / "pipeline"
        for f in root.glob("*.py"):
            src = f.read_text()
            for b in banned:
                self.assertNotIn(f"import {b}", src, f"{f.name} imports {b}")


if __name__ == "__main__":
    unittest.main()


class TestPipelineOrder(unittest.TestCase):
    """Stage ordering, and that BFS stays upward-only inside the engine."""

    @classmethod
    def setUpClass(cls):
        cls.repo, cls.eng = engine()

    def run_for(self, uid, **kw):
        return self.eng.run(self.repo.get_user(uid), EngineOptions(**kw))

    def ids(self, uid, **kw):
        return {c.id for c in self.run_for(uid, **kw).candidate_set}

    def test_core_pipeline_reaches_only_ancestors(self):
        """The engine must not reach tiers below the entry point for a user
        whose department has a home in the DAG."""
        from backend.pipeline.entry_point_resolver import resolve_entry_point
        from backend.pipeline.permission_compiler import compile_permissions

        by_id = {l.id: l for l in self.eng.levels()}
        for uid in ["U-PRIYA", "U-VIKRAM", "U-ANANYA", "U-SHARMA"]:
            user = self.repo.get_user(uid)
            entry = resolve_entry_point(compile_permissions(user), self.eng.levels())
            ancestors, stack = {entry.level_id}, [entry.level_id]
            while stack:
                for p in by_id[stack.pop()].parent_ids:
                    if p not in ancestors:
                        ancestors.add(p)
                        stack.append(p)
            for c in self.eng.run(user, EngineOptions()).candidate_set:
                if c.source == "ZONE2":
                    continue
                tier = self.repo._conn.execute(
                    "SELECT hierarchy_level_id h FROM knowledge_nodes WHERE id=?",
                    (c.id,)).fetchone()["h"]
                self.assertIn(tier, ancestors,
                              f"{uid} received {c.id} from non-ancestor tier {tier}")

    def test_zone2_is_injected_after_bfs_and_before_the_checks(self):
        f = self.run_for("U-PRIYA").funnel
        self.assertGreater(f["after_zone2"], f["after_bfs"],
                           "injection must widen the set after BFS")
        self.assertLessEqual(f["after_isolation"], f["after_zone2"],
                             "check 1 must run on the injected set")

    def test_zone2_nodes_are_subject_to_every_check(self):
        """Global nodes are candidates, not grants."""
        priya = self.ids("U-PRIYA")
        self.assertNotIn("N-G04", priya)   # derivability 0.75
        self.assertNotIn("N-G06", priya)   # derivability 0.80
        self.assertIn("N-G01", priya)

    def test_five_checks_appear_in_the_specified_order(self):
        f = self.run_for("U-VIKRAM").funnel
        order = [k for k in f if k.startswith("after_")]
        self.assertEqual(order[2:], [
            "after_isolation", "after_compliance", "after_permission",
            "after_temporal", "after_derivability"])

    def test_bfs_reports_the_ancestor_path_it_walked(self):
        from backend import api
        t = api.run_pipeline(self.repo, self.eng, {"user": "U-PRIYA"})["traversal"]
        self.assertEqual(t["ancestor_path"][0], "HL-10-ORTHO-W")
        self.assertEqual(t["ancestor_path"][-1], "HL-01")
        self.assertFalse(t["org_wide_scope"])
