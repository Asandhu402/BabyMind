"""Unit tests for the local interaction log and diagnostics report."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from babymind import interaction_log


class InteractionLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.home = Path(self.temp.name) / "data"
        self.home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def entries(self):
        path = interaction_log.log_path(self.home)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_record_appends_jsonl_and_recent_returns_newest_last(self) -> None:
        interaction_log.record(self.home, kind="api", method="get", path="/api/health?verbose=1", status=200, duration_ms=12.345)
        interaction_log.record(self.home, kind="api", method="GET", path="/api/unknown", status=404, error="Not found")
        entries = interaction_log.recent(self.home, 10)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["method"], "GET")
        self.assertEqual(entries[0]["path"], "/api/health")  # query string stripped
        self.assertTrue(entries[0]["ok"])
        self.assertEqual(entries[0]["duration_ms"], 12.3)
        self.assertEqual(entries[1]["status"], 404)
        self.assertFalse(entries[1]["ok"])
        self.assertEqual(entries[1]["error"], "Not found")

    def test_error_text_is_collapsed_and_truncated(self) -> None:
        message = "line one\n\n  line two\twith   extra spaces\n" + ("x" * 1000)
        entry = interaction_log.record(self.home, kind="api", method="GET", path="/api/x", status=500, error=message)
        self.assertNotIn("\n", entry["error"])
        self.assertNotIn("  ", entry["error"])
        self.assertLessEqual(len(entry["error"]), interaction_log.MAX_ERROR_CHARS)

    def test_client_error_entry_marks_not_ok(self) -> None:
        entry = interaction_log.record(self.home, kind="client_error", method="CLIENT", path="/", status=0, ok=False, error="TypeError: boom", detail="stack trace\nline 2")
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["kind"], "client_error")
        self.assertIn("boom", entry["error"])
        self.assertNotIn("\n", entry["detail"])

    def test_clear_removes_log_and_reports_count(self) -> None:
        for index in range(5):
            interaction_log.record(self.home, kind="api", method="GET", path=f"/api/{index}", status=200)
        self.assertEqual(interaction_log.clear(self.home), 5)
        self.assertEqual(interaction_log.recent(self.home, 10), [])
        self.assertEqual(interaction_log.clear(self.home), 0)

    def test_file_is_trimmed_to_max_entries(self) -> None:
        for index in range(interaction_log.MAX_FILE_ENTRIES + 20):
            interaction_log.record(self.home, kind="api", method="GET", path=f"/api/item/{index}", status=200)
        entries = self.entries()
        self.assertLessEqual(len(entries), interaction_log.MAX_FILE_ENTRIES)
        self.assertEqual(entries[-1]["path"], f"/api/item/{interaction_log.MAX_FILE_ENTRIES + 19}")

    def test_export_report_contains_version_and_error_details(self) -> None:
        interaction_log.record(self.home, kind="api", method="POST", path="/api/memory", status=500, error="db is locked")
        report = interaction_log.export_report(self.home, version="0.6.0")
        self.assertIn("## BabyMind diagnostics report", report)
        self.assertIn("BabyMind: 0.6.0", report)
        self.assertIn(str(self.home), report)
        self.assertIn("POST /api/memory", report)
        self.assertIn("ERROR 500", report)
        self.assertIn("db is locked", report)

    def test_export_report_handles_empty_log(self) -> None:
        report = interaction_log.export_report(self.home, version="0.6.0")
        self.assertIn("no interactions recorded yet", report)

    def test_recent_honours_limit(self) -> None:
        for index in range(10):
            interaction_log.record(self.home, kind="api", method="GET", path=f"/api/{index}", status=200)
        self.assertEqual(len(interaction_log.recent(self.home, 3)), 3)


if __name__ == "__main__":
    unittest.main()
