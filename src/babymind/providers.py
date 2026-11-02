"""Local model provider adapters for BabyMind."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Protocol


class ChatProvider(Protocol):
    """Common interface for model backends."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return one model response."""
        ...


class ProviderError(RuntimeError):
    """Raised when a model provider cannot complete a request."""


class LMStudioProvider:
    """OpenAI-compatible client for a model served locally by LM Studio."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = (base_url or os.getenv(
            "BABYMIND_BASE_URL", "http://127.0.0.1:1234/v1"
        )).rstrip("/")
        self.model = model or os.getenv("BABYMIND_MODEL")
        self.api_key = api_key or os.getenv("BABYMIND_API_KEY")
        self.timeout = timeout

    def _request_json(self, url: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(url, data=data, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"LM Studio returned HTTP {error.code}: {detail[:500]}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProviderError(
                "Could not reach LM Studio. Start its local server and check "
                f"the address {self.base_url}. Details: {error}"
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderError("LM Studio returned invalid JSON.") from error

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        response = self._request_json(f"{self.base_url}/models")
        models = response.get("data", [])
        if not models or not models[0].get("id"):
            raise ProviderError(
                "No model is available. Load a model in LM Studio, or set "
                "BABYMIND_MODEL to a model ID."
            )
        return str(models[0]["id"])

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self._resolve_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
        }
        response = self._request_json(
            f"{self.base_url}/chat/completions", payload
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "LM Studio response did not contain a chat completion."
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("LM Studio returned an empty response.")
        return content.strip()
