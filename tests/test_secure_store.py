"""Tests for authenticated encryption of local BabyMind text."""
import os
import tempfile
import unittest
from pathlib import Path

from babymind.secure_store import SecureTextStore


class SecureTextStoreTests(unittest.TestCase):
    def test_encrypts_and_round_trips_text(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecureTextStore(Path(folder) / "key")
            encrypted = store.encrypt("private conversation")
            self.assertTrue(encrypted.startswith("bmenc:v1:"))
            self.assertNotIn("private conversation", encrypted)
            self.assertEqual(store.decrypt(encrypted), "private conversation")

    def test_marker_prefixed_user_input_is_encrypted_as_plaintext(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecureTextStore(Path(folder) / "key")
            value = "bmenc:v1:private text that looks encrypted"
            encrypted = store.encrypt(value)
            self.assertNotIn(value, encrypted)
            self.assertEqual(store.decrypt(encrypted), value)
            self.assertEqual(store.encrypt_legacy(encrypted), encrypted)

    def test_encryption_is_randomized(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecureTextStore(Path(folder) / "key")
            first = store.encrypt("same text")
            second = store.encrypt("same text")
            self.assertNotEqual(first, second)
            self.assertEqual(store.decrypt(first), "same text")
            self.assertEqual(store.decrypt(second), "same text")

    def test_legacy_plaintext_remains_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecureTextStore(Path(folder) / "key")
            self.assertEqual(store.decrypt("old unencrypted note"), "old unencrypted note")

    def test_wrong_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            first = SecureTextStore(Path(folder) / "first.key")
            second = SecureTextStore(Path(folder) / "second.key")
            encrypted = first.encrypt("secret")
            with self.assertRaises(RuntimeError):
                second.decrypt(encrypted)

    def test_key_file_is_created_with_private_permissions_where_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key"
            SecureTextStore(path)
            self.assertTrue(path.is_file())
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
