"""Tests for non-destructive BabyMind diagnostics."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.diagnostics import run_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_reports_registry_and_safe_disabled_workspace_state(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("babymind.diagnostics._check_local_model", return_value=("PASS", "mock model")):
                results = run_diagnostics(home=Path(folder), check_model=True)
        by_name = {item["name"]: item for item in results}
        self.assertEqual(by_name["Specialist registry"]["status"], "PASS")
        self.assertEqual(by_name["Workspace security gate"]["status"], "BLOCKED")
        self.assertEqual(by_name["Execution policy"]["status"], "BLOCKED")
        self.assertEqual(by_name["Local model"]["status"], "PASS")

    def test_does_not_create_memory_database_or_key(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "not-created"
            with patch("babymind.diagnostics._check_local_model", return_value=("WARN", "offline")):
                run_diagnostics(home=home, check_model=True)
            self.assertFalse(home.exists())

    def test_missing_encryption_key_is_reported_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "memory.sqlite3").write_bytes(b"existing database placeholder")
            with patch("babymind.diagnostics._check_local_model", return_value=("WARN", "offline")):
                results = run_diagnostics(home=home, check_model=True)
            by_name = {item["name"]: item for item in results}
            self.assertEqual(by_name["Memory encryption key"]["status"], "FAIL")
            self.assertFalse((home / "memory.key").exists())

    def test_can_skip_model_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            results = run_diagnostics(home=folder, check_model=False)
        by_name = {item["name"]: item for item in results}
        self.assertEqual(by_name["Local model"]["status"], "SKIP")


if __name__ == "__main__":
    unittest.main()
