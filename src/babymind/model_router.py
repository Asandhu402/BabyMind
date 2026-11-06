"""Configurable per-role model routing with a safe shared-provider fallback.

BABYMIND_AGENT_MODEL_MAP is optional JSON. Keys may be agent IDs (BM-01),
domains (development), or "*" for a default route. Values are objects with
base_url, model, and optional api_key_env. Secrets are read from the named
environment variable and are never stored in the routing map or logged.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .agents import AGENT_BY_ID
from .providers import ChatProvider, LlamaCppHTTPClient, ProviderError, create_provider


class ModelRouter:
    """Route each specialist request to its configured backend or shared fallback."""

    def __init__(self, fallback: ChatProvider | None = None, routes: dict[str, Any] | None = None):
        self.fallback = fallback if fallback is not None else create_provider()
        self.routes = routes if routes is not None else self._load_routes()
        self._providers: dict[str, ChatProvider] = {}

    @staticmethod
    def _load_routes() -> dict[str, Any]:
        raw = os.getenv("BABYMIND_AGENT_MODEL_MAP", "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderError("BABYMIND_AGENT_MODEL_MAP must be valid JSON.") from error
        if not isinstance(value, dict):
            raise ProviderError("BABYMIND_AGENT_MODEL_MAP must be a JSON object.")
        return value

    def _route_key(self, agent_id: str) -> str | None:
        normalized = agent_id.strip().upper()
        agent = AGENT_BY_ID.get(normalized)
        if agent is None:
            raise KeyError(f"Unknown agent ID: {normalized}")
        for key in (normalized, agent.domain, "*"):
            if key in self.routes:
                return key
        return None

    def _provider(self, key: str) -> ChatProvider:
        if key in self._providers:
            return self._providers[key]
        config = self.routes[key]
        if not isinstance(config, dict):
            raise ProviderError(f"Model route {key!r} must be an object.")
        base_url = str(config.get("base_url", "")).strip()
        model = str(config.get("model", "")).strip()
        if not base_url or not model:
            raise ProviderError(f"Model route {key!r} requires base_url and model.")
        # Local HTTP is permitted; remote endpoints must use HTTPS.
        if not (base_url.startswith("https://") or base_url.startswith("http://127.0.0.1:")
                or base_url.startswith("http://localhost:")):
            raise ProviderError("Model routes must use HTTPS or a loopback HTTP endpoint.")
        api_key_env = str(config.get("api_key_env", "")).strip()
        api_key = os.getenv(api_key_env) if api_key_env else None
        if api_key_env and not api_key:
            raise ProviderError(f"Environment variable {api_key_env!r} for model route {key!r} is not set.")
        provider = LlamaCppHTTPClient(base_url=base_url, model=model, api_key=api_key,
                                      timeout=int(config.get("timeout", 120)))
        self._providers[key] = provider
        return provider

    def complete_for(self, agent_id: str, system_prompt: str, user_prompt: str) -> str:
        """Complete using the most specific route for a registered specialist."""
        key = self._route_key(agent_id)
        provider = self._provider(key) if key is not None else self.fallback
        return provider.complete(system_prompt, user_prompt)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Default-provider interface for callers without a specialist identity."""
        return self.fallback.complete(system_prompt, user_prompt)

    def routing_status(self) -> dict[str, Any]:
        """Expose route names and model IDs, never credentials."""
        return {
            "configured_routes": {
                key: {"base_url": str(value.get("base_url", "")),
                      "model": str(value.get("model", ""))}
                for key, value in self.routes.items() if isinstance(value, dict)
            },
            "fallback": "configured BabyMind provider",
            "agent_count": len(AGENT_BY_ID),
            "secrets_exposed": False,
        }
