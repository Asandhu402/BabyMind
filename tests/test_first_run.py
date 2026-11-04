"""Tests for the portable Linux first-run setup helpers."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.first_run import (
    MODEL_SHA256,
    _ensure_model,
    _find_llama_server,
    _sha256,
)


class FirstRunSetupTests(unittest.TestCase):
    def test_pinned_model_checksum_is_sha256(self) -> None:
        self.assertRegex(MODEL_SHA256, r"^[0-9a-f]{64}$")

    def test_sha256_reads_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.bin"
            path.write_bytes(b"BabyMind local model test")
            self.assertEqual(_sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_existing_model_is_rehashed_even_when_marker_matches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            path.write_bytes(b"model bytes")
            marker = path.with_suffix(path.suffix + ".sha256")
            marker.write_text(MODEL_SHA256, encoding="ascii")
            with patch("babymind.first_run._sha256", return_value=MODEL_SHA256) as verify:
                _ensure_model(path)
            verify.assert_called_once_with(path)

    def test_existing_mismatched_model_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            path.write_bytes(b"do not delete this file")
            with self.assertRaisesRegex(RuntimeError, "not deleted"):
                _ensure_model(path)
            self.assertEqual(path.read_bytes(), b"do not delete this file")

    def test_missing_model_invokes_downloader_and_rechecks_hash(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            with patch("babymind.first_run._sha256", return_value=MODEL_SHA256):
                _ensure_model(path, lambda target: target.write_bytes(b"fixture"))
            self.assertTrue(path.exists())

    def test_downloader_cannot_bypass_verification(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            with self.assertRaisesRegex(RuntimeError, "verified pinned model"):
                _ensure_model(path, lambda target: target.write_bytes(b"bad"))

    def test_missing_model_without_downloader_explains_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "desktop window"):
                _ensure_model(Path(folder) / "model.gguf")

    def test_finds_bundled_llama_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama.cpp"
            runtime.mkdir()
            executable = runtime / "llama-server"
            executable.write_bytes(b"test")
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(_find_llama_server(Path(folder)), executable)

    def test_finds_nested_llama_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama.cpp" / "bin"
            runtime.mkdir(parents=True)
            executable = runtime / "llama-server"
            executable.write_bytes(b"test")
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(_find_llama_server(Path(folder)), executable)


if __name__ == "__main__":
    unittest.main()
