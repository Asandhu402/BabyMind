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
    def test_lm_studio_is_default_backend(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(create_provider(), LMStudioProvider)

    def test_unknown_backend_is_rejected(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_ENGINE": "cloud-service"}, clear=True):
            with self.assertRaises(ProviderError):
                create_provider()

    def test_llama_cpp_requires_explicit_local_paths(self) -> None:
        env = {"BABYMIND_ENGINE": "llama.cpp"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ProviderError, "BABYMIND_LLAMA_SERVER"):
                create_provider()

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
