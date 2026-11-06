"""Tests for bounded autonomy, environment drift, permissions, and benchmarks."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.autonomy import ActionPolicy, AutonomyController
from babymind.benchmarks import run_benchmarks
from babymind.cognitive_core import CognitiveCore


class ScriptedProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, system_prompt, user_prompt):
        self.calls += 1
        if "post-action reflection stage" in system_prompt:
            return json.dumps({
                "reflection": "Local result was verified.",
                "learning": "Carry forward only verified outcomes.",
                "confidence": 0.9,
            })
        return json.dumps({
            "understanding": "The current environment is observed.",
            "plan": "Create a small local goal.",
            "action": {"type": "create_goal", "title": "Autonomy test", "description": "Bounded multi-cycle test."},
            "expected": "A local goal should be persisted.",
        })


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = CognitiveCore(Path(self.temp.name) / "cognitive.sqlite3")
        self.controller = AutonomyController(self.core)

    def test_permission_policy_is_allowlist_and_fail_closed(self):
        self.assertTrue(ActionPolicy.authorize({"type": "wait"})["allowed"])
        self.assertTrue(ActionPolicy.authorize({"type": "create_goal"})["allowed"])
        self.assertFalse(ActionPolicy.authorize({"type": "shell"})["allowed"])
        self.assertTrue(ActionPolicy.authorize({"type": "shell"})["requires_approval"])
        self.assertFalse(ActionPolicy.authorize({"type": "invented_action"})["allowed"])

    def test_environment_baseline_persists_and_detects_drift(self):
        baseline = {
            "system": "Linux", "distribution": "Ubuntu 26.10",
            "kernel": "6.1", "architecture": "x86_64", "python": "3.14",
            "python_executable": "/usr/bin/python3", "home_directory": "/home/test",
            "babymind_home": "/home/test/.babymind",
            "agent_count": 50, "agent_ids": [],
            "capabilities": {},
        }
        changed = dict(baseline, kernel="6.2")
        with patch("babymind.autonomy.environment_snapshot", side_effect=[baseline, baseline, changed]):
            first = self.controller.observe_environment()
            second = self.controller.observe_environment()
            third = self.controller.observe_environment()
        self.assertFalse(first["baseline_available"])
        self.assertTrue(second["baseline_available"])
        self.assertTrue(third["changed"])
        self.assertEqual(third["changes"][0]["field"], "kernel")

    def test_autonomy_is_finite_and_persists_multi_step_goal(self):
        report = self.controller.run(ScriptedProvider(), cycles=2)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["completed_cycles"], 2)
        self.assertEqual(len(self.core.active_goals()), 2)
        self.assertIn("No arbitrary shell", report["autonomy_boundary"])

    def test_cycle_and_interval_limits_are_enforced(self):
        with self.assertRaises(ValueError):
            self.controller.run(ScriptedProvider(), cycles=26)
        with self.assertRaises(ValueError):
            self.controller.run(ScriptedProvider(), cycles=1, interval=3601)

    def test_benchmark_reports_dimensions_without_consciousness_claim(self):
        report = run_benchmarks(self.core)
        self.assertIn("identity_and_environment", report["dimensions"])
        self.assertGreaterEqual(report["total"], 10)
        self.assertIn("cannot establish consciousness", report["interpretation"])


if __name__ == "__main__":
    unittest.main()
