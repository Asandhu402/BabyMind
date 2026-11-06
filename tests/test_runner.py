"""Tests for bounded command execution."""
from __future__ import annotations

import sys
from unittest.mock import patch
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

    def test_versioned_active_interpreter_is_allowed_but_not_impostors(self) -> None:
        actual = self.root / "python3.10"
        actual.symlink_to(sys.executable)
        result = runner.run_command([str(actual), "-c", "print('interpreter works')"],
                                    cwd=self.root, timeout=30)
        self.assertTrue(result["ok"], result)
        self.assertIn("interpreter works", result["stdout"])
        impostor = self.root / "python3.12"
        impostor.write_text("#!/bin/sh\necho not-python\n")
        impostor.chmod(0o755)
        with self.assertRaises(runner.CommandRejected):
            runner.run_command([str(impostor)], cwd=self.root, timeout=30)

    def test_frozen_executable_is_not_accepted_as_interpreter(self) -> None:
        alias = self.root / "python3.10"
        alias.symlink_to(sys.executable)
        with patch.object(sys, "frozen", True, create=True), self.assertRaises(runner.CommandRejected):
            runner._resolve_executable([str(alias)])

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


class UnitTestRecordingTests(unittest.TestCase):
    """The failing set must survive the console output cap.

    The tail is capped and kept from the end, so a suite with many failures
    loses its earliest FAIL:/ERROR: headings. That made a hosted packaged
    staging run undecidable: 50 problems reported, 46 ids recoverable.
    """

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_mix.py").write_text(
            "import unittest\n\n\nclass Mix(unittest.TestCase):\n"
            "    def test_good(self): pass\n"
            "    def test_bad(self): self.fail('boom')\n"
            "    def test_err(self): raise RuntimeError('kaboom')\n"
            "    @unittest.skip('nope')\n    def test_skip(self): pass\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_problem_ids_are_recorded_and_match_the_console_headings(self) -> None:
        import re

        result = runner.run_unit_tests(self.root, timeout=120)
        self.assertEqual(result["summary"]["problems"], 2, result["summary"])
        self.assertIn("problem_ids", result)
        scraped = set(re.findall(r"^(?:FAIL|ERROR): (.+)$", result.get("stderr") or "", re.MULTILINE))
        # Same strings, so ids stay comparable across runs that do and do not
        # have a recorded report.
        self.assertEqual(set(result["problem_ids"]), scraped)
        self.assertEqual(len(result["problem_ids"]), 2)

    def test_subtest_failures_are_recorded_as_problem_ids(self) -> None:
        # Parametrized subTest failures are counted in the summary but reported
        # through addSubTest; without recording them, attribution never completes
        # and the pre-edit verification gate refuses every sandboxed suite.
        (self.root / "tests" / "test_mix.py").unlink()
        (self.root / "tests" / "test_params.py").write_text(
            "import unittest\n\n\nclass Params(unittest.TestCase):\n"
            "    def test_matrix(self):\n"
            "        for value in ('a', 'b', 'c'):\n"
            "            with self.subTest(value=value):\n"
            "                self.assertEqual(value, 'a')\n")
        result = runner.run_unit_tests(self.root, timeout=120)
        self.assertEqual(result["summary"]["problems"], 2, result["summary"])
        self.assertEqual(len(result["problem_ids"]), result["summary"]["problems"])
        self.assertTrue(any("value='b'" in p for p in result["problem_ids"]))
        self.assertTrue(any("value='c'" in p for p in result["problem_ids"]))

    def test_generated_driver_and_report_do_not_survive_the_run(self) -> None:
        runner.run_unit_tests(self.root, timeout=120)
        leftovers = sorted(path.name for path in self.root.glob(".babymind-unittest-*"))
        self.assertEqual(leftovers, [])

    def test_recording_survives_a_run_that_exceeds_the_output_cap(self) -> None:
        # One failing test whose traceback is far larger than MAX_OUTPUT_CHARS.
        (self.root / "tests" / "test_loud.py").write_text(
            "import unittest\n\n\nclass Loud(unittest.TestCase):\n"
            "    def test_loud(self):\n"
            f"        self.fail('x' * {runner.MAX_OUTPUT_CHARS + 20000})\n")
        result = runner.run_unit_tests(self.root, timeout=180)
        self.assertTrue(result["truncated"], "expected the console tail to be capped")
        self.assertGreater(len(result.get("stderr") or ""), 0)
        self.assertEqual(result["summary"]["problems"], 3, result["summary"])
        # The heading is gone from the tail, but the data is not.
        self.assertEqual(len(result["problem_ids"]), 3, result["problem_ids"])
        self.assertIn("test_loud (test_loud.Loud.test_loud)", result["problem_ids"])


if __name__ == "__main__":
    unittest.main()
