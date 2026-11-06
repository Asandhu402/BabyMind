"""Tests for BabyMind's llama.cpp local model engine."""

import os
import socket
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import babymind.providers as providers_module
from babymind.providers import (
    LlamaCppHTTPClient,
    LlamaCppProvider,
    ProviderError,
    _context_size,
    create_provider,
)


class ProviderSelectionTests(unittest.TestCase):
    def test_generation_settings_are_sent_to_local_chat_api(self) -> None:
        provider = LlamaCppHTTPClient(base_url="http://127.0.0.1:1235/v1", model="local")
        with patch.dict(os.environ, {
            "BABYMIND_TEMPERATURE": "0.35",
            "BABYMIND_TOP_P": "0.92",
            "BABYMIND_MAX_TOKENS": "1536",
        }, clear=True), patch.object(provider, "_request_json", return_value={
            "choices": [{"message": {"content": "A complete answer."}}]
        }) as request:
            result = provider.complete("system", "question")
        self.assertEqual(result, "A complete answer.")
        payload = request.call_args.args[1]
        self.assertEqual(payload["temperature"], 0.35)
        self.assertEqual(payload["top_p"], 0.92)
        self.assertEqual(payload["max_tokens"], 1536)
        self.assertNotIn("chat_template_kwargs", payload)

    def test_llama_cpp_disables_hidden_thinking_in_chat_template(self) -> None:
        provider = LlamaCppProvider.__new__(LlamaCppProvider)
        self.assertEqual(
            provider._request_options(),
            {"chat_template_kwargs": {"enable_thinking": False}},
        )

    def test_invalid_generation_settings_fail_clearly(self) -> None:
        provider = LlamaCppHTTPClient(base_url="http://127.0.0.1:1235/v1", model="local")
        with patch.dict(os.environ, {"BABYMIND_MAX_TOKENS": "not-a-number"}, clear=True):
            with self.assertRaisesRegex(ProviderError, "valid numeric values"):
                provider.complete("system", "question")

    def test_local_engine_default_stays_available_before_first_run_setup(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = create_provider()
            self.assertEqual(provider.base_url, "http://127.0.0.1:1235/v1")
            with self.assertRaisesRegex(ProviderError, "first-run setup"):
                provider.complete("system", "question")

    def test_unknown_backend_is_rejected(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_ENGINE": "cloud-service"}, clear=True):
            with self.assertRaises(ProviderError):
                create_provider()

    def test_llama_cpp_requires_explicit_local_paths_when_constructed(self) -> None:
        env = {"BABYMIND_ENGINE": "llama.cpp"}
        with patch.dict(os.environ, env, clear=True):
            provider = create_provider()
            self.assertEqual(provider.__class__.__name__, "UnconfiguredLlamaCppProvider")

    def test_llama_cpp_rejects_missing_executable(self) -> None:
        env = {
            "BABYMIND_ENGINE": "llama.cpp",
            "BABYMIND_LLAMA_SERVER": "/missing/llama-server",
            "BABYMIND_GGUF_MODEL": "/missing/model.gguf",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ProviderError, "executable not found"):
                LlamaCppProvider()

    def test_refuses_any_occupied_port_without_launching(self) -> None:
        # The listener need not speak HTTP or return a successful /health.
        with tempfile.TemporaryDirectory() as folder, socket.socket() as listener:
            executable = Path(folder) / "llama-server"
            model = Path(folder) / "model.gguf"
            executable.write_bytes(b"fixture")
            model.write_bytes(b"fixture")
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            env = {"BABYMIND_LLAMA_SERVER": str(executable), "BABYMIND_GGUF_MODEL": str(model),
                   "BABYMIND_LLAMA_PORT": str(listener.getsockname()[1])}
            with patch.dict(os.environ, env, clear=True), patch("subprocess.Popen") as popen:
                with self.assertRaisesRegex(ProviderError, "will not reuse"):
                    LlamaCppProvider()
                popen.assert_not_called()

    def test_managed_server_uses_one_slot_for_the_full_context(self) -> None:
        with tempfile.TemporaryDirectory() as folder, socket.socket() as probe:
            executable = Path(folder) / "llama-server"
            model = Path(folder) / "model.gguf"
            executable.touch()
            model.touch()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            env = {"BABYMIND_LLAMA_SERVER": str(executable), "BABYMIND_GGUF_MODEL": str(model),
                   "BABYMIND_LLAMA_PORT": str(port), "BABYMIND_CONTEXT_SIZE": "4096"}
            process = MagicMock()
            process.poll.return_value = None
            with patch.dict(os.environ, env, clear=True), \
                 patch("subprocess.Popen", return_value=process) as popen, \
                 patch("babymind.providers.urlopen"), patch("atexit.register"):
                LlamaCppProvider()
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--parallel") + 1], "1")
            self.assertEqual(command[command.index("--ctx-size") + 1], "4096")

    def test_invalid_port_is_reported_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "llama-server"
            model = Path(folder) / "model.gguf"
            executable.touch()
            model.touch()
            for port in ("abc", "0", "65536", "-1"):
                with self.subTest(port=port), patch.dict(os.environ, {
                    "BABYMIND_LLAMA_SERVER": str(executable), "BABYMIND_GGUF_MODEL": str(model),
                    "BABYMIND_LLAMA_PORT": port,
                }, clear=True), patch("subprocess.Popen") as popen:
                    with self.assertRaisesRegex(ProviderError, "between 1 and 65535"):
                        LlamaCppProvider()
                    popen.assert_not_called()

    def test_stop_reaps_process_after_forced_kill(self) -> None:
        provider = LlamaCppProvider.__new__(LlamaCppProvider)
        provider._process = MagicMock()
        provider._process.poll.return_value = None
        provider._process.wait.side_effect = [subprocess.TimeoutExpired("llama-server", 5), 0]
        provider.stop()
        provider._process.terminate.assert_called_once()
        provider._process.kill.assert_called_once()
        self.assertEqual(provider._process.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()


class ContextSizeTests(unittest.TestCase):
    def test_default_context_size_is_4096(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_context_size(), 4096)

    def test_valid_context_sizes_are_accepted(self) -> None:
        for raw, want in (("512", 512), ("4096", 4096), ("8192", 8192), ("131072", 131072)):
            with patch.dict(os.environ, {"BABYMIND_CONTEXT_SIZE": raw}, clear=True):
                self.assertEqual(_context_size(), want)

    def test_invalid_context_sizes_fail_clearly(self) -> None:
        for raw in ("not-a-number", "", "4096.5", "100", "131073"):
            with patch.dict(os.environ, {"BABYMIND_CONTEXT_SIZE": raw}, clear=True):
                with self.assertRaises(ProviderError):
                    _context_size()

    def test_invalid_context_size_fails_before_launching(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "llama-server"
            exe.write_text("#!/bin/sh\nexit 0\n")
            model = Path(folder) / "model.gguf"
            model.write_bytes(b"gguf")
            env = {
                "BABYMIND_LLAMA_SERVER": str(exe),
                "BABYMIND_GGUF_MODEL": str(model),
                "BABYMIND_CONTEXT_SIZE": "abc",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ProviderError, "whole number of tokens"):
                    LlamaCppProvider()

    def test_context_size_reaches_llama_server_argv(self) -> None:
        with tempfile.TemporaryDirectory() as folder, socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "llama-server"
            exe.write_text("#!/bin/sh\nexit 0\n")
            exe.chmod(0o755)
            model = Path(folder) / "model.gguf"
            model.write_bytes(b"gguf")
            env = {
                "BABYMIND_LLAMA_SERVER": str(exe),
                "BABYMIND_GGUF_MODEL": str(model),
                "BABYMIND_CONTEXT_SIZE": "8192",
                "BABYMIND_LLAMA_PORT": str(port),
            }
            fake_process = MagicMock()
            fake_process.poll.return_value = None
            env_patch = patch.dict(os.environ, env, clear=True)
            popen_patch = patch.object(providers_module.subprocess, "Popen", return_value=fake_process)
            health_patch = patch.object(providers_module, "urlopen", return_value=MagicMock())
            env_patch.start()
            popen_patch.start()
            health_patch.start()
            try:
                provider = LlamaCppProvider()
                argv = providers_module.subprocess.Popen.call_args.args[0]
                self.assertEqual(argv[argv.index("--ctx-size") + 1], "8192")
                provider.stop()
            finally:
                health_patch.stop()
                popen_patch.stop()
                env_patch.stop()
