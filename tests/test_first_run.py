"""Tests for the portable Windows first-run setup helpers."""

import builtins
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

    def test_verified_existing_model_does_not_import_tkinter(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            path.write_bytes(b"verified model fixture")
            real_import = builtins.__import__
            def no_tk(name, *args, **kwargs):
                if name == "tkinter":
                    raise AssertionError("Tkinter must not be imported for a verified model")
                return real_import(name, *args, **kwargs)
            with patch("babymind.first_run._sha256", return_value=MODEL_SHA256) as verify, \
                 patch("builtins.__import__", side_effect=no_tk):
                _ensure_model(path)
            verify.assert_called_once_with(path)
            self.assertEqual(path.with_suffix(".gguf.sha256").read_text(encoding="ascii"), MODEL_SHA256)

    def test_missing_tkinter_explains_first_run_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.gguf"
            real_import = builtins.__import__
            def no_tk(name, *args, **kwargs):
                if name == "tkinter":
                    raise ModuleNotFoundError("No module named 'tkinter'", name="tkinter")
                return real_import(name, *args, **kwargs)
            with patch("builtins.__import__", side_effect=no_tk), \
                 patch("babymind.first_run._download_model") as download:
                with self.assertRaisesRegex(RuntimeError, "Tkinter is required.*BABYMIND_GGUF_MODEL"):
                    _ensure_model(path)
            download.assert_not_called()
            self.assertFalse(path.exists())

    def test_finds_bundled_llama_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama.cpp"
            runtime.mkdir()
            executable = runtime / "llama-server.exe"
            executable.write_bytes(b"test")
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(_find_llama_server(Path(folder)), executable)

    def test_finds_nested_llama_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama.cpp" / "bin"
            runtime.mkdir(parents=True)
            executable = runtime / "llama-server.exe"
            executable.write_bytes(b"test")
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(_find_llama_server(Path(folder)), executable)


if __name__ == "__main__":
    unittest.main()
