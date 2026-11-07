"""Tests for the deterministic operational self-evaluation."""
import tempfile
import unittest
from pathlib import Path

from babymind.cognitive_core import CognitiveCore
from babymind.self_evaluation import run_self_evaluation


class SelfEvaluationTests(unittest.TestCase):
    def test_all_operational_checks_pass_without_external_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = CognitiveCore(Path(temporary) / "cognitive.sqlite3")
            report = run_self_evaluation(core)
        self.assertTrue(report["all_passed"], report["checks"])
        self.assertEqual(report["passed"], report["total"])
        self.assertGreaterEqual(report["total"], 7)
        self.assertIn("not proof of consciousness", report["interpretation"].lower())

    def test_evaluation_does_not_mutate_real_core_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = CognitiveCore(Path(temporary) / "cognitive.sqlite3")
            before = core.status()
            run_self_evaluation(core)
            after = core.status()
        self.assertEqual(before["active_goals"], after["active_goals"])
        self.assertEqual(before["notes"], after["notes"])
        self.assertEqual(before["cycles"], after["cycles"])

    def test_single_babymind_identity_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = run_self_evaluation(CognitiveCore(Path(temporary) / "cognitive.sqlite3"))
        roles = next(item for item in report["checks"] if item["name"] == "role_registry_integrity")
        self.assertTrue(roles["passed"], roles["evidence"])


if __name__ == "__main__":
    unittest.main()
