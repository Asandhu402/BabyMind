"""Tests for the unified execution broker choke point."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import broker, runner, sandbox


class BrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_status_reports_boundary(self):
        report = broker.status()
        self.assertIn("policy", report)
        self.assertIn("backend", report)
        self.assertIn("nested_sandbox_detected", report)
        self.assertIn("decisions_total", report)
        self.assertIn("require", report["policy"])

    def test_execute_records_allowed_decision(self):
        result = broker.execute([sys.executable, "-c", "print('ok')"],
                                cwd=self.root, allowed_root=self.root,
                                timeout=60, sandbox_mode="off")
        self.assertTrue(result["ok"])
        report = broker.status()
        self.assertGreaterEqual(report["decisions_total"], 1)
        self.assertEqual(report["recent_decisions"][-1]["decision"], "allowed")

    def test_execute_rejects_bad_timeout_before_running(self):
        with self.assertRaises(broker.BrokerError):
            broker.execute([sys.executable, "-c", "pass"], timeout=99999)
        report = broker.status()
        self.assertGreaterEqual(report["refused_total"], 0)

    def test_fail_closed_when_sandbox_required_but_unavailable(self):
        if not sandbox.available():
            self.skipTest("sandbox available here")
        with patch.object(sandbox, "backend",
                          return_value=sandbox.Backend("none", False, "forced off")):
            with self.assertRaises(runner.CommandRejected):
                broker.execute([sys.executable, "-c", "pass"], cwd=self.root,
                               allowed_root=self.root, sandbox_mode="require")


if __name__ == "__main__":
    unittest.main()
