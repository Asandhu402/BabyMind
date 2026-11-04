"""Read-only health checks for a BabyMind installation."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from urllib.request import urlopen

from .agents import AGENTS, validate_registry


def _check_local_model(timeout: float = 3.0) -> tuple[str, str]:
    """Check only BabyMind's supported local llama.cpp runtime."""
    executable_value = os.getenv("BABYMIND_LLAMA_SERVER", "").strip()
    model_value = os.getenv("BABYMIND_GGUF_MODEL", "").strip()
    if not executable_value or not model_value:
        return "WARN", "Set BABYMIND_LLAMA_SERVER and BABYMIND_GGUF_MODEL for the local llama.cpp runtime."
    executable = Path(executable_value).expanduser()
    model = Path(model_value).expanduser()
    missing = [str(path) for path in (executable, model) if not path.is_file()]
    if missing:
        return "FAIL", "Missing local llama.cpp file(s): " + ", ".join(missing)
    port = os.getenv("BABYMIND_LLAMA_PORT", "1235")
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout):
            return "PASS", f"llama.cpp server is healthy on 127.0.0.1:{port}."
    except Exception:
        return "WARN", "llama.cpp files exist, but its local server is not running."


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
