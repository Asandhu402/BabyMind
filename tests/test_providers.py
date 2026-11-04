"""Tests for BabyMind's selectable local model engines."""

import os
import unittest
from unittest.mock import patch

from babymind.providers import (
    LMStudioProvider,
    LlamaCppProvider,
    ProviderError,
    create_provider,
)


class ProviderSelectionTests(unittest.TestCase):
    def test_generation_settings_are_sent_to_local_chat_api(self) -> None:
        provider = LMStudioProvider(base_url="http://127.0.0.1:1234/v1", model="local")
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
        provider = LMStudioProvider(base_url="http://127.0.0.1:1234/v1", model="local")
        with patch.dict(os.environ, {"BABYMIND_MAX_TOKENS": "not-a-number"}, clear=True):
            with self.assertRaisesRegex(ProviderError, "valid numeric values"):
                provider.complete("system", "question")

    def test_local_engine_default_stays_available_before_first_run_setup(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = create_provider()
            self.assertEqual(provider.base_url, "http://127.0.0.1:1235/v1")
            with self.assertRaisesRegex(ProviderError, "first-run setup"):
                provider.complete("system", "question")

    def test_lm_studio_is_only_selected_explicitly(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_ENGINE": "lm-studio"}, clear=True):
            self.assertIsInstance(create_provider(), LMStudioProvider)

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
            "BABYMIND_LLAMA_SERVER": "Z:\\missing\\llama-server.exe",
            "BABYMIND_GGUF_MODEL": "Z:\\missing\\model.gguf",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ProviderError, "executable not found"):
                LlamaCppProvider()


if __name__ == "__main__":
    unittest.main()
