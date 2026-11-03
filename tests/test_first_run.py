"""Tests for the portable Windows first-run setup helpers."""

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

    def test_custom_gguf_is_not_compared_to_bundled_model_checksum(self) -> None:
        from babymind.first_run import prepare_local_engine
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama-server.exe"
            runtime.write_bytes(b"runtime")
            model = Path(folder) / "custom-model.gguf"
            model.write_bytes(b"user-selected model")
            env = {
                "BABYMIND_ENGINE": "llama.cpp",
                "BABYMIND_GGUF_MODEL": str(model),
            }
            with patch.dict("os.environ", env, clear=True), \
                 patch("babymind.first_run._app_directory", return_value=Path(folder)), \
                 patch("babymind.first_run._find_llama_server", return_value=runtime), \
                 patch("babymind.first_run._ensure_model") as ensure:
                prepare_local_engine()
                ensure.assert_not_called()
                self.assertEqual(Path(__import__("os").environ["BABYMIND_GGUF_MODEL"]), model)

    def test_missing_custom_gguf_is_rejected(self) -> None:
        from babymind.first_run import prepare_local_engine
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / "llama-server.exe"
            runtime.write_bytes(b"runtime")
            env = {
                "BABYMIND_ENGINE": "llama.cpp",
                "BABYMIND_GGUF_MODEL": str(Path(folder) / "missing.gguf"),
            }
            with patch.dict("os.environ", env, clear=True), \
                 patch("babymind.first_run._app_directory", return_value=Path(folder)), \
                 patch("babymind.first_run._find_llama_server", return_value=runtime):
                with self.assertRaisesRegex(RuntimeError, "existing user-selected"):
                    prepare_local_engine()

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
