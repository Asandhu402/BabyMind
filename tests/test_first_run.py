"""Tests for the portable Windows first-run setup helpers."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.first_run import (
    MODEL_SHA256,
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
