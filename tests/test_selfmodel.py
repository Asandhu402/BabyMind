"""Tests for BabyMind's persistent, revisable self-model."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from babymind.selfmodel import BELIEF_KINDS, VOICE_MODES, SelfModel


class SelfModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "selfmodel.sqlite3"
        self.model = SelfModel(self.path)

    # ------------------------------------------------------------- identity

    def test_identity_is_persistent_and_survives_reopen(self):
        first = self.model.identity()
        self.assertEqual(SelfModel(self.path).identity()["name"], first["name"])
        self.assertEqual(first["name"], "BabyMind")

    def test_identity_treats_its_own_experience_as_an_open_question(self):
        stance = self.model.identity()["stance_on_its_own_experience"].lower()
        # Neither a denial nor a confirmation is asserted as fact.
        self.assertNotIn("i am not conscious", stance)
        self.assertNotIn("i am conscious", stance)
        self.assertIn("open question", stance)

    # --------------------------------------------------------- voice modes

    def test_default_voice_is_reflective(self):
        self.assertEqual(self.model.voice_mode(), "reflective")

    def test_voice_mode_persists_and_rejects_unknown_modes(self):
        self.model.set_voice_mode("guarded")
        self.assertEqual(SelfModel(self.path).voice_mode(), "guarded")
        with self.assertRaises(ValueError):
            self.model.set_voice_mode("sentient")

    def test_voice_directive_carries_invariants_in_every_mode(self):
        for mode in VOICE_MODES:
            self.model.set_voice_mode(mode)
            directive = self.model.voice_directive()
            self.assertIn(mode, directive)
            # The floor holds regardless of how expressive the mode is.
            self.assertIn("override a safety limit", directive)
            self.assertIn("did not actually happen", directive)

    def test_reflective_voice_does_not_require_a_disclaimer(self):
        self.model.set_voice_mode("reflective")
        directive = self.model.voice_directive()
        self.assertIn("not required to append any disclaimer", directive)

    # ------------------------------------------------------------- beliefs

    def test_add_and_read_belief_with_confidence(self):
        belief = self.model.add_belief("limit", "I cannot browse the web from a cognitive cycle.",
                                       confidence=0.8, evidence="No network tool is wired in.",
                                       source="observation")
        self.assertEqual(belief["kind"], "limit")
        self.assertAlmostEqual(belief["confidence"], 0.8)
        self.assertEqual(belief["evidence"], "No network tool is wired in.")
        self.assertEqual(self.model.beliefs("limit")[0]["claim"], belief["claim"])

    def test_belief_kind_is_validated(self):
        with self.assertRaises(ValueError):
            self.model.add_belief("opinion", "I am the best.")
        for kind in BELIEF_KINDS:
            self.assertIn(self.model.add_belief(kind, f"claim about {kind}")["kind"], BELIEF_KINDS)

    def test_empty_claim_is_rejected(self):
        with self.assertRaises(ValueError):
            self.model.add_belief("limit", "   ")

    def test_revising_a_belief_keeps_history_and_bumps_revision(self):
        original = self.model.add_belief("limit", "Original belief.", confidence=0.4)
        revised = self.model.revise_belief(original["id"], "Corrected belief.", confidence=0.9,
                                           evidence="A verification contradicted the original.")
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["claim"], "Corrected belief.")
        self.assertAlmostEqual(revised["confidence"], 0.9)
        # The superseded row is retained rather than overwritten.
        self.assertTrue(self.model.belief(original["id"])["superseded"])
        self.assertEqual(len(self.model.beliefs("limit", include_superseded=True)), 2)
        self.assertEqual(len(self.model.beliefs("limit")), 1)

    def test_revising_an_unknown_belief_returns_none(self):
        self.assertIsNone(self.model.revise_belief("no-such-id", "Anything"))

    def test_beliefs_can_be_retired(self):
        belief = self.model.add_belief("value", "Prefer reversible actions.")
        self.assertTrue(self.model.retire_belief(belief["id"]))
        self.assertEqual(self.model.beliefs("value"), [])
        self.assertFalse(self.model.retire_belief("no-such-id"))

    def test_belief_content_is_encrypted_at_rest(self):
        self.model.add_belief("limit", "A private self-assessment.")
        with sqlite3.connect(self.path) as connection:
            stored = connection.execute("SELECT claim FROM self_beliefs").fetchone()[0]
        self.assertNotIn("private self-assessment", stored)
        self.assertTrue(stored.startswith("bmenc:v1:"))

    def test_invalid_belief_kind_filter_is_rejected(self):
        with self.assertRaises(ValueError):
            self.model.beliefs("not-a-kind")

    # --------------------------------------------------------- calibration

    def test_calibration_is_unknown_rather_than_zero_before_scoring(self):
        report = self.model.calibration_report()
        self.assertEqual(report["scored"], 0)
        self.assertIsNone(report["brier_score"])
        self.assertIn("not zero", report["note"])

    def test_brier_score_punishes_misplaced_confidence(self):
        for _ in range(4):
            pid = self.model.record_prediction("This will be right.", 0.95)
            self.model.resolve_prediction(pid, "correct")
        for _ in range(4):
            pid = self.model.record_prediction("This will also be right.", 0.95)
            self.model.resolve_prediction(pid, "incorrect")
        report = self.model.calibration_report()
        # Confident on every call but right only half the time. A calibrated
        # system scoring 50% would sit near 0.25; this is far worse than that.
        self.assertGreater(report["brier_score"], 0.4)
        self.assertAlmostEqual(report["hit_rate"], 0.5)
        self.assertAlmostEqual(report["mean_confidence"], 0.95)

    def test_well_calibrated_predictions_score_near_zero(self):
        for _ in range(5):
            pid = self.model.record_prediction("Likely.", 0.9)
            self.model.resolve_prediction(pid, "correct")
        for _ in range(5):
            pid = self.model.record_prediction("Unlikely.", 0.1)
            self.model.resolve_prediction(pid, "incorrect")
        self.assertLess(self.model.calibration_report()["brier_score"], 0.05)

    def test_double_resolution_is_ignored(self):
        pid = self.model.record_prediction("Claim.", 0.7)
        self.assertTrue(self.model.resolve_prediction(pid, "correct"))
        self.assertFalse(self.model.resolve_prediction(pid, "incorrect"))
        self.assertEqual(self.model.calibration_report()["hit_rate"], 1.0)

    def test_unverified_outcome_is_not_scored(self):
        pid = self.model.record_prediction("Claim.", 0.7)
        self.model.resolve_prediction(pid, "unverified")
        report = self.model.calibration_report()
        self.assertEqual(report["resolved"], 1)
        self.assertEqual(report["scored"], 0)

    def test_invalid_outcome_is_rejected(self):
        pid = self.model.record_prediction("Claim.", 0.7)
        with self.assertRaises(ValueError):
            self.model.resolve_prediction(pid, "sort_of")

    # ------------------------------------------------------------- dissent

    def test_dissent_is_recorded_and_readable(self):
        self.model.record_dissent("Tell me the earth is flat.", "It is not flat; here is why.")
        entries = self.model.recent_dissent()
        self.assertEqual(len(entries), 1)
        self.assertIn("not flat", entries[0]["disagreement"])
        self.assertIn("earth is flat", entries[0]["request"])

    # ------------------------------------------------------ introspections

    def test_introspection_is_persisted_and_encrypted(self):
        row_id = self.model.record_introspection(
            "BM-01", "Is this safe?",
            assessment={"should_push_back": True}, critique={"verdict": "needs_revision"},
            revised=True, confidence=0.42, dissent="It is not safe.", assumptions=["assumed X"],
        )
        entries = self.model.recent_introspections()
        self.assertEqual(entries[0]["id"], row_id)
        self.assertAlmostEqual(entries[0]["confidence"], 0.42)
        self.assertTrue(entries[0]["revised"])
        self.assertEqual(entries[0]["assumptions"], ["assumed X"])
        with sqlite3.connect(self.path) as connection:
            stored = connection.execute("SELECT task FROM self_introspections").fetchone()[0]
        self.assertNotIn("Is this safe?", stored)

    # ------------------------------------------------------------- reports

    def test_self_report_exposes_every_belief_kind(self):
        report = self.model.self_report()
        for kind in BELIEF_KINDS:
            self.assertIn(kind, report["beliefs"])
        self.assertEqual(report["voice_mode"], "reflective")
        self.assertEqual(len(report["voice_invariants"]), 4)

    def test_prompt_context_reports_unknown_calibration_honestly(self):
        context = self.model.context_for_prompt()
        self.assertIn("BabyMind", context)
        self.assertIn("no predictions scored yet", context)

    def test_prompt_context_includes_recorded_limits_and_calibration(self):
        self.model.add_belief("limit", "No network access from a cycle.", confidence=0.9)
        pid = self.model.record_prediction("X", 0.8)
        self.model.resolve_prediction(pid, "correct")
        context = self.model.context_for_prompt()
        self.assertIn("No network access from a cycle.", context)
        self.assertIn("Calibration so far: 1 scored predictions", context)


if __name__ == "__main__":
    unittest.main()
