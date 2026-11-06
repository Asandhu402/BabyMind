"""Tests for independent per-role model routing."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from babymind.model_router import ModelRouter
from babymind.providers import ProviderError


class ModelRouterTests(unittest.TestCase):
    def test_role_route_overrides_domain_and_fallback(self):
        fallback = MagicMock()
        role = MagicMock()
        domain = MagicMock()
        router = ModelRouter(fallback, {
            "BM-03": {"base_url": "http://127.0.0.1:9001/v1", "model": "coder"},
            "development": {"base_url": "http://127.0.0.1:9002/v1", "model": "developer"},
        })
        with patch.object(router, "_provider", return_value=role):
            self.assertEqual(router.complete_for("BM-03", "s", "u"), role.complete.return_value)
            role.complete.assert_called_once_with("s", "u")
        with patch.object(router, "_provider", return_value=domain):
            router.complete_for("BM-04", "s", "u")
            domain.complete.assert_called_once_with("s", "u")
        fallback.complete.assert_not_called()

    def test_unconfigured_role_uses_shared_fallback(self):
        fallback = MagicMock()
        router = ModelRouter(fallback, {})
        router.complete_for("BM-01", "s", "u")
        fallback.complete.assert_called_once_with("s", "u")

    def test_unknown_role_is_rejected(self):
        router = ModelRouter(MagicMock(), {})
        with self.assertRaises(KeyError):
            router.complete_for("BM-51", "s", "u")

    def test_remote_route_requires_https(self):
        router = ModelRouter(MagicMock(), {"*": {"base_url": "http://example.com/v1", "model": "x"}})
        with self.assertRaises(ProviderError):
            router.complete_for("BM-01", "s", "u")

    def test_route_api_key_is_loaded_from_environment_not_config(self):
        router = ModelRouter(MagicMock(), {"*": {
            "base_url": "https://models.example/v1", "model": "x", "api_key_env": "BABYMIND_TEST_SECRET"
        }})
        with patch.dict(os.environ, {"BABYMIND_TEST_SECRET": "secret-value"}),              patch("babymind.model_router.LlamaCppHTTPClient") as client:
            router.complete_for("BM-01", "s", "u")
            self.assertEqual(client.call_args.kwargs["api_key"], "secret-value")
        self.assertNotIn("secret-value", json.dumps(router.routing_status()))

    def test_environment_route_json_must_be_object(self):
        with patch.dict(os.environ, {"BABYMIND_AGENT_MODEL_MAP": "[]"}):
            with self.assertRaises(ProviderError):
                ModelRouter(MagicMock())


if __name__ == "__main__":
    unittest.main()
