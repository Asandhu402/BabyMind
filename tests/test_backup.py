"""Tests for authenticated, password-protected BabyMind backups."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from babymind.backup import create_backup, restore_backup
from babymind.secure_store import SecureTextStore


class BackupTests(unittest.TestCase):
    def make_home(self, home: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        app_store = SecureTextStore(home / "app.key")
        connection = sqlite3.connect(home / "app.sqlite3")
        connection.execute("CREATE TABLE conversations (id TEXT, title TEXT)")
        connection.execute("INSERT INTO conversations VALUES (?, ?)", ("one", app_store.encrypt("Private chat title")))
        connection.execute("CREATE TABLE messages (content TEXT)")
        connection.execute("INSERT INTO messages VALUES (?)", (app_store.encrypt("Private conversation"),))
        connection.commit()
        connection.close()

        memory_store = SecureTextStore(home / "memory.key")
        connection = sqlite3.connect(home / "memory.sqlite3")
        connection.execute("CREATE TABLE memories (task TEXT, response TEXT)")
        connection.execute("INSERT INTO memories VALUES (?, ?)", (
            memory_store.encrypt("Private memory task"), memory_store.encrypt("Private memory response")
        ))
        connection.commit()
        connection.close()

    def test_backup_round_trip_preserves_encrypted_databases_and_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, restored = root / "original", root / "restored"
            backup = root / "BabyMind.bmbak"
            self.make_home(original)
            created = create_backup(original, backup, "a-long-backup-password")
            self.assertTrue(backup.is_file())
            self.assertIn("app.sqlite3", created["files"])
            self.assertIn("memory.sqlite3", created["files"])

            result = restore_backup(
                restored, backup, "a-long-backup-password",
                confirmation="RESTORE BABYMIND",
            )
            self.assertEqual(set(result["restored"]), {
                "app.sqlite3", "app.key", "memory.sqlite3", "memory.key"
            })
            app_store = SecureTextStore(restored / "app.key")
            memory_store = SecureTextStore(restored / "memory.key")
            connection = sqlite3.connect(restored / "app.sqlite3")
            encrypted_title = connection.execute("SELECT title FROM conversations").fetchone()[0]
            encrypted_message = connection.execute("SELECT content FROM messages").fetchone()[0]
            connection.close()
            self.assertEqual(app_store.decrypt(encrypted_title), "Private chat title")
            self.assertEqual(app_store.decrypt(encrypted_message), "Private conversation")
            connection = sqlite3.connect(restored / "memory.sqlite3")
            task, response = connection.execute("SELECT task, response FROM memories").fetchone()
            connection.close()
            self.assertEqual(memory_store.decrypt(task), "Private memory task")
            self.assertEqual(memory_store.decrypt(response), "Private memory response")

    def test_backup_restores_and_validates_development_review_text(self):
        with tempfile.TemporaryDirectory() as folder:
            from babymind.development_review import DevelopmentReviews
            root = Path(folder)
            original, restored = root / "original", root / "restored"
            self.make_home(original)
            store = SecureTextStore(original / "app.key")
            with sqlite3.connect(original / "app.sqlite3") as connection:
                DevelopmentReviews.create_tables(connection)
                connection.execute("INSERT INTO development_reviews VALUES (?, ?, ?, ?, ?, ?)",
                                   ('r', store.encrypt('Private task'), store.encrypt('Private context'), 'reviewed', 'time', 'time'))
                connection.execute("INSERT INTO development_review_roles VALUES (?, ?, ?, ?, ?, ?)",
                                   ('r', 1, 'Architect', 'Objective', 'completed', store.encrypt('Private report')))
            backup = root / "review.bmbak"
            create_backup(original, backup, "a-long-backup-password")
            restore_backup(restored, backup, "a-long-backup-password", confirmation="RESTORE BABYMIND")
            with sqlite3.connect(restored / "app.sqlite3") as connection:
                task = connection.execute("SELECT task FROM development_reviews").fetchone()[0]
                report = connection.execute("SELECT response FROM development_review_roles").fetchone()[0]
            restored_store = SecureTextStore(restored / "app.key")
            self.assertEqual(restored_store.decrypt(task), 'Private task')
            self.assertEqual(restored_store.decrypt(report), 'Private report')

    def test_wrong_password_does_not_modify_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, restored = root / "original", root / "restored"
            backup = root / "BabyMind.bmbak"
            self.make_home(original)
            create_backup(original, backup, "a-long-backup-password")
            restored.mkdir()
            sentinel = restored / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "password is incorrect"):
                restore_backup(
                    restored, backup, "wrong-password-123",
                    confirmation="RESTORE BABYMIND",
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((restored / "app.sqlite3").exists())

    def test_restore_requires_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, restored = root / "original", root / "restored"
            backup = root / "BabyMind.bmbak"
            self.make_home(original)
            create_backup(original, backup, "a-long-backup-password")
            with self.assertRaises(PermissionError):
                restore_backup(restored, backup, "a-long-backup-password", confirmation="yes")

    def test_short_password_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_home(root / "data")
            with self.assertRaisesRegex(ValueError, "12"):
                create_backup(root / "data", root / "BabyMind.bmbak", "short")


if __name__ == "__main__":
    unittest.main()
