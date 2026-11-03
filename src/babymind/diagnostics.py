"""Read-only health checks for a BabyMind installation."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from .agents import AGENTS, validate_registry


def _check_local_model(timeout: float = 3.0) -> tuple[str, str]:
    engine = os.getenv("BABYMIND_ENGINE", "lm-studio").strip().lower()
    if engine in {"lm-studio", "lmstudio"}:
        base_url = os.getenv("BABYMIND_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
        headers = {"Accept": "application/json"}
        api_key = os.getenv("BABYMIND_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            request = Request(f"{base_url}/models", headers=headers)
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read(256_000).decode("utf-8"))
            models = payload.get("data", [])
            if not models:
                return "WARN", "LM Studio is reachable but has no loaded model."
            model_names = [str(item.get("id", "unnamed")) for item in models[:5]]
            return "PASS", "LM Studio connected; loaded model(s): " + ", ".join(model_names)
        except Exception as error:
            return "WARN", f"LM Studio not reachable at {base_url}: {error}"

    if engine in {"llama.cpp", "llamacpp", "llama-cpp"}:
        executable = Path(os.getenv("BABYMIND_LLAMA_SERVER", "")).expanduser()
        model = Path(os.getenv("BABYMIND_GGUF_MODEL", "")).expanduser()
        if not str(executable) or not str(model):
            return "WARN", "Set BABYMIND_LLAMA_SERVER and BABYMIND_GGUF_MODEL."
        missing = [str(path) for path in (executable, model) if not path.is_file()]
        if missing:
            return "FAIL", "Missing local llama.cpp file(s): " + ", ".join(missing)
        port = os.getenv("BABYMIND_LLAMA_PORT", "1235")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout):
                return "PASS", f"llama.cpp server is healthy on 127.0.0.1:{port}."
        except Exception:
            return "WARN", "llama.cpp files exist, but its local server is not running."
    return "FAIL", f"Unknown BABYMIND_ENGINE value: {engine!r}"


def run_diagnostics(
    *,
    home: str | Path | None = None,
    check_model: bool = True,
) -> list[dict[str, str]]:
    """Return non-destructive checks; never launches a model or executes code."""
    results: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        results.append({"name": name, "status": status, "detail": detail})

    add(
        "Python",
        "PASS" if sys.version_info >= (3, 10) else "FAIL",
        f"{platform.python_version()} (BabyMind requires Python 3.10+)",
    )
    try:
        validate_registry(AGENTS)
        add("Specialist registry", "PASS", f"{len(AGENTS)} validated roles; one shared model.")
    except Exception as error:
        add("Specialist registry", "FAIL", str(error))

    data_home = Path(home) if home is not None else Path(
        os.getenv("BABYMIND_HOME", Path.home() / ".babymind")
    )
    database = data_home / "memory.sqlite3"
    key_file = data_home / "memory.key"
    try:
        if not data_home.exists():
            add("Local storage", "WARN", f"Storage has not been initialized: {data_home}")
        elif not data_home.is_dir():
            add("Local storage", "FAIL", f"Storage path is not a directory: {data_home}")
        else:
            probe = data_home / ".babymind-doctor-probe"
            try:
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                add("Local storage", "PASS", f"Storage directory is writable: {data_home}")
            except OSError as error:
                add("Local storage", "FAIL", f"Storage directory is not writable: {error}")
        if database.exists() and not key_file.exists():
            add("Memory encryption key", "FAIL", "memory.sqlite3 exists but memory.key is missing; do not create a replacement key.")
        elif database.exists() and key_file.exists():
            try:
                from .memory import LocalMemory
                LocalMemory(database).recent(limit=1)
                add("Memory database", "PASS", "Database opened and existing encrypted memory was readable.")
            except Exception as error:
                add("Memory database", "FAIL", str(error))
        else:
            add("Memory database", "WARN", "No memory database exists yet; it will be created when memory is first used.")
    except Exception as error:
        add("Local storage", "FAIL", str(error))

    if check_model:
        status, detail = _check_local_model()
        add("Local model", status, detail)
    else:
        add("Local model", "SKIP", "Model connection check was not requested.")

    try:
        from .approval import WORKSPACE_FILE_ACTIONS_ENABLED
        if WORKSPACE_FILE_ACTIONS_ENABLED:
            add("Workspace security gate", "WARN", "Workspace actions are enabled; independently verify the native broker and threat-model gates.")
        else:
            add("Workspace security gate", "BLOCKED", "File actions remain disabled by default; this is the expected safe state until review.")
    except Exception as error:
        add("Workspace security gate", "FAIL", str(error))

    add("Execution policy", "BLOCKED", "Project-code execution is not enabled by this diagnostic; a reviewed OS-level sandbox is required.")
    add("Network exposure", "INFO", "Default deployment should remain loopback-only; LAN mode is an explicit opt-in.")
    return results
