"""Unified execution broker: the single choke point for running commands.

All untrusted or generated code execution (app builder, sandbox self-tests)
must go through :func:`execute`. The broker enforces a fail-closed sandbox
policy by default, records every allow/refuse decision, and reports the
state of the security boundary via :func:`status`.

This is a single choke point with an auditable decision log; it is not a
claim of a formally verified security boundary.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import runner, sandbox

DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 600
_DECISION_LOG: list[dict] = []
_LOG_LOCK = threading.Lock()
_LOG_LIMIT = 200


class BrokerError(ValueError):
    """Raised when a broker request is rejected before execution."""


def _record(decision: dict) -> None:
    with _LOG_LOCK:
        _DECISION_LOG.append(decision)
        del _DECISION_LOG[:-_LOG_LIMIT]


def execute(argv: list[str], *, cwd: str | Path | None = None,
            allowed_root: str | Path | None = None, timeout: int = DEFAULT_TIMEOUT,
            env: dict[str, str] | None = None, sandbox_mode: str = "require") -> dict:
    """Run one command through the shared runner under the sandbox policy.

    ``sandbox_mode`` defaults to ``require`` (fail closed when no OS sandbox
    backend exists). Every decision is recorded in the broker log.
    """
    try:
        seconds = int(timeout)
    except (TypeError, ValueError) as error:
        raise BrokerError("Timeout must be an integer number of seconds.") from error
    if not 1 <= seconds <= MAX_TIMEOUT:
        raise BrokerError(f"Timeout must be between 1 and {MAX_TIMEOUT} seconds.")
    backend = sandbox.backend()
    try:
        result = runner.run_command(
            list(argv), cwd=cwd, allowed_root=allowed_root,
            timeout=seconds, env=env, sandbox=sandbox_mode,
        )
        _record({"ts": time.time(), "argv": result.get("argv", [str(a) for a in argv]),
                 "decision": "allowed",
                 "sandboxed": result.get("sandboxed"), "sandbox": result.get("sandbox"),
                 "exit_code": result.get("exit_code")})
        return result
    except runner.CommandRejected as error:
        _record({"ts": time.time(), "argv": [str(a) for a in argv], "decision": "refused",
                 "reason": str(error), "sandboxed": False})
        raise


def run_unit_tests(root, *, timeout: int = DEFAULT_TIMEOUT, sandbox_mode: str = "require") -> dict:
    """Gateway wrapper: unit tests only run through the broker, sandboxed by default."""
    return runner.run_unit_tests(root, timeout=timeout, sandbox=sandbox_mode)


def run_compile_check(root, *, sandbox_mode: str = "require") -> dict:
    """Gateway wrapper: compile checks only run through the broker, sandboxed by default."""
    return runner.run_compile_check(root, sandbox=sandbox_mode)


def status() -> dict:
    """Report the execution boundary: backend, policy, and decision log."""
    backend = sandbox.backend()
    probe = sandbox.status(probe=False)
    with _LOG_LOCK:
        decisions = list(_DECISION_LOG)
    return {
        "policy": "sandbox=require (fail closed when no OS backend is available)",
        "backend": backend.name,
        "backend_available": backend.available,
        "backend_detail": backend.detail,
        "nested_sandbox_detected": sandbox.nested_sandbox_detected(),
        "limits": probe.get("mechanisms", {}).get("limits"),
        "decisions_total": len(decisions),
        "refused_total": sum(1 for d in decisions if d["decision"] == "refused"),
        "recent_decisions": decisions[-10:],
        "note": ("Single choke point with an auditable decision log. Not a formally "
                 "verified security boundary; adversarial escape tests live in "
                 "tests/test_sandbox_escape.py."),
    }
