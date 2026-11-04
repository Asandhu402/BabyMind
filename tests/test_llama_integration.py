"""Optional real llama.cpp inference using an explicitly supplied test GGUF.

This exercises the runtime/provider plumbing only. A random fixture cannot
establish the quality or compatibility of BabyMind's pinned real model.
"""
import os
import socket
import unittest
from unittest.mock import patch

from babymind.providers import LlamaCppProvider


@unittest.skipUnless(
    os.getenv("BABYMIND_TEST_LLAMA_SERVER") and os.getenv("BABYMIND_TEST_GGUF_MODEL"),
    "requires an explicit test llama-server and GGUF fixture",
)
class LlamaIntegrationTests(unittest.TestCase):
    def test_runtime_starts_and_handles_a_completion(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {
            "BABYMIND_LLAMA_SERVER": os.environ["BABYMIND_TEST_LLAMA_SERVER"],
            "BABYMIND_GGUF_MODEL": os.environ["BABYMIND_TEST_GGUF_MODEL"],
            "BABYMIND_LLAMA_PORT": str(port),
            "BABYMIND_CONTEXT_SIZE": "4096",
            "BABYMIND_MAX_TOKENS": "12",
            "BABYMIND_TEMPERATURE": "0",
            "OMP_NUM_THREADS": "2",
        }
        with patch.dict(os.environ, env):
            provider = LlamaCppProvider()
            try:
                properties = provider._request_json(f"http://127.0.0.1:{port}/props")
                self.assertEqual(properties["default_generation_settings"]["n_ctx"], 4096)
                text = provider.complete("You are a test fixture.", "Say hello.")
                self.assertIsInstance(text, str)
                self.assertTrue(text.strip())
            finally:
                provider.stop()
