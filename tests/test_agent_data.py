"""Tests for inspecting and purging removed agent/role/mission/review data.

The purge is destructive, so these tests focus on what it must *not* do: touch
conversations or memories, drop schema, run without confirmation, delete
anything on a dry run, or claim to have modified backups.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from babymind import agent_data

LEGACY_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT)",
    "CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, content TEXT)",
    "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, task TEXT, response TEXT)",
    "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT)",
    "CREATE TABLE IF NOT EXISTS execution_proposals (id TEXT PRIMARY KEY, payload TEXT)",
    "CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, brief TEXT)",
    "CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, mission_id TEXT, agent_id TEXT)",
    "CREATE TABLE IF NOT EXISTS development_reviews (id TEXT PRIMARY KEY, task TEXT)",
    "CREATE TABLE IF NOT EXISTS development_review_roles (review_id TEXT, role_id INTEGER)",
    "CREATE TABLE IF NOT EXISTS development_review_attempts (id INTEGER PRIMARY KEY, review_id TEXT)",
)


class PurgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.db = self.home / "app.sqlite3"
        with sqlite3.connect(self.db) as connection:
            for statement in LEGACY_SCHEMA:
                connection.execute(statement)
            # The removed features left data behind; the user's own data did not.
            connection.execute("INSERT INTO messages VALUES ('m1', 'my own conversation')")
            connection.execute("INSERT INTO memories VALUES (1, 'my task', 'my response')")
            connection.execute("INSERT INTO missions VALUES ('ms1', 'old brief')")
            connection.execute("INSERT INTO agent_runs VALUES ('r1', 'ms1', 'BM-07')")
            connection.execute("INSERT INTO agent_runs VALUES ('r2', 'ms1', 'BM-08')")
            connection.execute("INSERT INTO development_reviews VALUES ('d1', 'old review')")
            connection.execute("INSERT INTO development_review_roles VALUES ('d1', 1)")
            connection.execute("INSERT INTO development_review_attempts VALUES (1, 'd1')")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def counts(self) -> dict[str, int]:
        with sqlite3.connect(self.db) as connection:
            return {
                name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in agent_data.PURGE_TABLES + agent_data.PRESERVED
            }

    def test_report_counts_removable_rows_without_deleting(self) -> None:
        report = agent_data.agent_data_report(self.home)
        self.assertEqual(report["removable_rows"], 6)  # 1 mission + 2 runs + 1 review + 1 role + 1 attempt
        self.assertEqual(self.counts()["missions"], 1)
        self.assertEqual(self.counts()["agent_runs"], 2)

    def test_report_handles_an_installation_with_no_legacy_tables(self) -> None:
        empty = self.home / "empty"
        empty.mkdir()
        with sqlite3.connect(empty / "app.sqlite3") as connection:
            connection.execute("CREATE TABLE conversations (id TEXT)")
        report = agent_data.agent_data_report(empty)
        self.assertEqual(report["removable_rows"], 0)
        self.assertEqual(report["databases"][0]["present"], [])

    def test_dry_run_deletes_nothing(self) -> None:
        before = self.counts()
        report = agent_data.purge_agent_data(dry_run=True, home=self.home)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["deleted_total"], 0)
        self.assertGreater(report["would_delete"], 0)
        self.assertEqual(self.counts(), before)

    def test_purge_without_confirmation_refuses(self) -> None:
        before = self.counts()
        for kwargs in ({}, {"confirm": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionError):
                agent_data.purge_agent_data(home=self.home, **kwargs)
        self.assertEqual(self.counts(), before)

    def test_purge_removes_agent_data_and_preserves_user_data(self) -> None:
        report = agent_data.purge_agent_data(confirm=True, home=self.home)
        after = self.counts()
        for table in agent_data.PURGE_TABLES:
            self.assertEqual(after[table], 0, f"{table} should be empty")
        # The user's own records must be untouched.
        self.assertEqual(after["messages"], 1)
        self.assertEqual(after["memories"], 1)
        self.assertEqual(report["deleted"]["app.sqlite3"]["agent_runs"], 2)
        self.assertTrue(report["backups_untouched"])

    def test_purge_keeps_the_schema_so_older_versions_can_still_open_the_database(self) -> None:
        agent_data.purge_agent_data(confirm=True, home=self.home)
        with sqlite3.connect(self.db) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue(set(agent_data.PURGE_TABLES) <= tables)

    def test_purge_does_not_touch_backup_archives(self) -> None:
        backup = self.home / "BabyMind.bmbak"
        backup.write_bytes(b"BMBK1pretend-archive")
        agent_data.purge_agent_data(confirm=True, home=self.home)
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), b"BMBK1pretend-archive")

    def test_purge_is_idempotent(self) -> None:
        first = agent_data.purge_agent_data(confirm=True, home=self.home)
        second = agent_data.purge_agent_data(confirm=True, home=self.home)
        self.assertEqual(first["deleted_total"], 6)
        self.assertEqual(second["deleted_total"], 0)
        self.assertEqual(second["failures"], [])

    def test_a_missing_home_is_reported_not_created(self) -> None:
        missing = self.home / "nope"
        report = agent_data.agent_data_report(missing)
        self.assertEqual(report["databases"], [])
        self.assertEqual(report["removable_rows"], 0)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
