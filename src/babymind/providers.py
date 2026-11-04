"""Local model provider adapters for BabyMind."""

import json
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Protocol

from .response_quality import strip_internal_reasoning


class ChatProvider(Protocol):
    """Common interface for model backends."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return one model response."""
        ...


class ProviderError(RuntimeError):
    """Raised when a model provider cannot complete a request."""


class LlamaCppHTTPClient:
    """OpenAI-compatible HTTP client used by BabyMind's local llama.cpp server."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int = 120,
    ) -> None:
        port = os.getenv("BABYMIND_LLAMA_PORT", "1235")
        self.base_url = (base_url or f"http://127.0.0.1:{port}/v1").rstrip("/")
        self.model = model or os.getenv("BABYMIND_MODEL")
        self.api_key = api_key
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
                f"Local model server returned HTTP {error.code}: {detail[:500]}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProviderError(
                "Could not reach the local model server. Start the configured engine and check "
                f"the address {self.base_url}. Details: {error}"
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProviderError("Local model server returned invalid JSON.") from error

    def _resolve_model(self) -> str:
        if self.model:
            return self.model
        response = self._request_json(f"{self.base_url}/models")
        models = response.get("data", [])
        if not models or not models[0].get("id"):
            raise ProviderError(
                "No model is available from the local model server; set "
                "BABYMIND_MODEL to a model ID."
            )
        return str(models[0]["id"])

    def _request_options(self) -> dict:
        """Return backend-specific OpenAI-compatible request options."""
        return {}

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Configurable conservative defaults for local inference.
        try:
            temperature = float(os.getenv("BABYMIND_TEMPERATURE", "0.4"))
            top_p = float(os.getenv("BABYMIND_TOP_P", "0.9"))
            max_tokens = int(os.getenv("BABYMIND_MAX_TOKENS", "2048"))
        except ValueError as error:
            raise ProviderError(
                "BABYMIND_TEMPERATURE, BABYMIND_TOP_P, and BABYMIND_MAX_TOKENS "
                "must be valid numeric values."
            ) from error
        if not 0.0 <= temperature <= 2.0:
            raise ProviderError("BABYMIND_TEMPERATURE must be between 0 and 2.")
        if not 0.0 < top_p <= 1.0:
            raise ProviderError("BABYMIND_TOP_P must be greater than 0 and at most 1.")
        if not 1 <= max_tokens <= 32768:
            raise ProviderError("BABYMIND_MAX_TOKENS must be between 1 and 32768.")
        payload = {
            "model": self._resolve_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        payload.update(self._request_options())
        response = self._request_json(
            f"{self.base_url}/chat/completions", payload
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Local model server response did not contain a chat completion."
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Local model server returned an empty response.")
        try:
            return strip_internal_reasoning(content)
        except ValueError as error:
            raise ProviderError(str(error)) from error

class LlamaCppProvider(LlamaCppHTTPClient):
    """Launch and use a local llama.cpp server with a user-supplied GGUF model.

    No model is downloaded automatically. The executable and model remain
    under the user's control and inference runs on this computer.
    """

    def _request_options(self) -> dict:
        # Qwen-family instruct templates can spend the entire token budget in
        # hidden reasoning unless the template is explicitly told to disable it.
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def __init__(self, timeout: int = 600) -> None:
        import atexit
        import socket
        import time
        from pathlib import Path

        executable = os.getenv("BABYMIND_LLAMA_SERVER", "").strip()
        model_path = os.getenv("BABYMIND_GGUF_MODEL", "").strip()
        if not executable or not model_path:
            raise ProviderError(
                "The BabyMind llama.cpp engine needs BABYMIND_LLAMA_SERVER "
                "(path to llama-server) and BABYMIND_GGUF_MODEL "
                "(path to a .gguf model file)."
            )
        exe = Path(executable).expanduser()
        model = Path(model_path).expanduser()
        if not exe.is_file():
            raise ProviderError(f"llama-server executable not found: {exe}")
        if not model.is_file() or model.suffix.lower() != ".gguf":
            raise ProviderError(f"GGUF model file not found: {model}")
        try:
            port = int(os.getenv("BABYMIND_LLAMA_PORT", "1235"))
            if not 1 <= port <= 65535:
                raise ValueError("out of range")
        except ValueError as error:
            raise ProviderError("BABYMIND_LLAMA_PORT must be a port number between 1 and 65535.") from error
        super().__init__(
            base_url=f"http://127.0.0.1:{port}/v1",
            model=os.getenv("BABYMIND_MODEL"),
            api_key=None,
            timeout=timeout,
        )
        self._process = None
        # A service returning 404 or 503 (or a non-HTTP service) still owns
        # the port. An HTTP health probe alone treats those as a free port.
        # There remains a race between releasing this probe and llama binding.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise ProviderError(
                f"Port {port} is unavailable; BabyMind will not reuse an unverified "
                "server. Choose a free BABYMIND_LLAMA_PORT."
            ) from error
        command = [
            str(exe), "--model", str(model), "--host", "127.0.0.1",
            "--port", str(port), "--ctx-size",
            os.getenv("BABYMIND_CONTEXT_SIZE", "4096"),
            # BabyMind serializes inference. Auto-selected multiple llama
            # slots divide the configured context and can reject normal chats.
            "--parallel", "1",
            "--reasoning-format", "none",
        ]
        # PyInstaller adjusts LD_LIBRARY_PATH for the frozen app; do not pass
        # its private Qt/Python libraries to the independent llama executable.
        child_env = os.environ.copy()
        if "LD_LIBRARY_PATH_ORIG" in child_env:
            child_env["LD_LIBRARY_PATH"] = child_env.pop("LD_LIBRARY_PATH_ORIG")
        elif getattr(sys, "frozen", False):
            child_env.pop("LD_LIBRARY_PATH", None)
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=child_env,
            )
        except OSError as error:
            raise ProviderError(f"Could not start llama.cpp: {error}") from error
        atexit.register(self.stop)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise ProviderError(
                    "llama.cpp server exited during startup. Check the model, "
                    "runtime files, and available memory."
                )
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                    break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.5)
        else:
            self.stop()
            raise ProviderError("Timed out while loading the local GGUF model.")

    def stop(self) -> None:
        """Stop only the llama-server process started by this provider."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()

    def _request_json(self, url: str, payload: dict | None = None) -> dict:
        try:
            return super()._request_json(url, payload)
        except ProviderError as error:
            raise ProviderError(f"BabyMind local llama.cpp engine: {error}") from error


class UnconfiguredLlamaCppProvider(LlamaCppHTTPClient):
    """Keep the app importable until first-run setup supplies local runtime paths."""

    def __init__(self) -> None:
        port = int(os.getenv("BABYMIND_LLAMA_PORT", "1235"))
        super().__init__(base_url=f"http://127.0.0.1:{port}/v1", timeout=600)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise ProviderError(
            "BabyMind standalone llama.cpp is not configured yet. Complete first-run "
            "setup so BABYMIND_LLAMA_SERVER and BABYMIND_GGUF_MODEL point to the "
            "bundled runtime and pinned model."
        )


def create_provider() -> ChatProvider:
    """Select the local inference backend from BABYMIND_ENGINE."""
    engine = os.getenv("BABYMIND_ENGINE", "llama.cpp").strip().lower()
    if engine in {"llama.cpp", "llamacpp", "llama-cpp"}:
        if not os.getenv("BABYMIND_LLAMA_SERVER", "").strip() or not os.getenv("BABYMIND_GGUF_MODEL", "").strip():
            return UnconfiguredLlamaCppProvider()
        return LlamaCppProvider()
    raise ProviderError(
        f"Unknown BABYMIND_ENGINE '{engine}'. Use 'llama.cpp'."
    )
