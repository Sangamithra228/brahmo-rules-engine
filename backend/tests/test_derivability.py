import unittest

from backend.data.seed_data import KNOWLEDGE_NODES
from backend.derivability.scorer import score_text, validate_against_seed


class TestDerivabilityScorer(unittest.TestCase):
    def test_the_edge_case_from_the_thinking_guide(self):
        """Same drug, opposite verdicts - which is the whole problem."""
        generic = score_text(
            "Paracetamol Mechanism of Action",
            "Paracetamol (acetaminophen) is an analgesic and antipyretic. "
            "Standard adult dose: 500-1000mg every 4-6 hours.")
        specific = score_text(
            "Paracetamol First-Line Post-TKR",
            "Supra Ortho uses Paracetamol 650mg QDS as first-line post-TKR "
            "pain management. Decision by Dr. Vikram, Jan 2025.")
        self.assertGreater(generic.score, 0.7)
        self.assertLess(specific.score, 0.7)

    def test_definitional_titles_score_high(self):
        for title, body in [
            ("What is a Total Knee Replacement",
             "Total knee replacement is a surgical procedure. Also called TKA."),
            ("What is Deep Vein Thrombosis",
             "Deep vein thrombosis is a blood clot in a deep vein. "
             "Risk factors: surgery, immobility."),
        ]:
            self.assertGreater(score_text(title, body).score, 0.7, title)

    def test_organisational_fingerprints_score_low(self):
        s = score_text(
            "Ortho Department Budget Allocation 2026",
            "FY 2026 budget: Rs 4.2 Cr. Budget review: Dr. Vikram quarterly.")
        self.assertLess(s.score, 0.3)

    def test_score_is_bounded(self):
        for n in KNOWLEDGE_NODES:
            s = score_text(n[3], n[4], n[0]).score
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_scorer_is_deterministic(self):
        a = score_text("What is DVT", "DVT is a blood clot.").score
        b = score_text("What is DVT", "DVT is a blood clot.").score
        self.assertEqual(a, b)

    def test_explains_itself(self):
        e = score_text("What is a TKR", "TKR is a surgical procedure.")
        self.assertTrue(e.generic_hits)

    def test_agrees_with_seeded_scores_on_which_side_of_the_threshold(self):
        v = validate_against_seed(KNOWLEDGE_NODES, threshold=0.7)
        self.assertGreaterEqual(
            v["agreement"], 0.90,
            f"only {v['agreement']:.0%} agreement: {v['disagreements']}")


if __name__ == "__main__":
    unittest.main()
