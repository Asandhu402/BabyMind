"""Tests for bounded command execution."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from babymind import runner


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_runs_a_python_command_and_captures_output(self) -> None:
        result = runner.run_command(
            [sys.executable, "-c", "print('hello runner')"],
            cwd=self.root, allowed_root=self.root, timeout=30,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello runner", result["stdout"])
        self.assertFalse(result["timed_out"])

    def test_timeout_kills_the_process(self) -> None:
        result = runner.run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=self.root, allowed_root=self.root, timeout=1,
        )
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["ok"])
        self.assertLess(result["seconds"], 20)

    def test_output_is_capped(self) -> None:
        result = runner.run_command(
            [sys.executable, "-c", "print('x' * 200000)"],
            cwd=self.root, allowed_root=self.root, timeout=30,
        )
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"]), runner.MAX_OUTPUT_CHARS)

    def test_disallowed_executable_is_rejected(self) -> None:
        with self.assertRaises(runner.CommandRejected):
            runner.run_command(["/bin/sh", "-c", "echo nope"], cwd=self.root, timeout=10)

    def test_working_directory_must_stay_inside_the_root(self) -> None:
        outside = Path(self.temp.name).parent
        with self.assertRaises(runner.CommandRejected):
            runner.run_command([sys.executable, "-c", "print(1)"],
                               cwd=outside, allowed_root=self.root, timeout=10)

    def test_environment_is_scrubbed_of_secrets(self) -> None:
        result = runner.run_command(
            [sys.executable, "-c", "import os; print(os.getenv('MY_SECRET','MISSING'))"],
            cwd=self.root, allowed_root=self.root, timeout=30,
            env={"MY_SECRET": "leak", "SAFE_VALUE": "ok"},
        )
        self.assertIn("MISSING", result["stdout"])

    def test_timeout_bounds_are_enforced(self) -> None:
        for value in (0, -5, runner.MAX_TIMEOUT + 1, "abc"):
            with self.subTest(value=value), self.assertRaises(runner.CommandRejected):
                runner.run_command([sys.executable, "-c", "print(1)"], cwd=self.root, timeout=value)

    def test_isolation_report_does_not_claim_a_sandbox(self) -> None:
        report = runner.isolation_report()
        self.assertFalse(report["os_sandbox"])
        self.assertFalse(report["network_isolation"])
        self.assertTrue(report["environment_scrubbed"])


if __name__ == "__main__":
    unittest.main()
