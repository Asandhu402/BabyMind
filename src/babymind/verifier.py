"""Independent coding verification and debugging.

Unlike the self-development loop (which proposes and applies its own patches),
this module *verifies* a checkout independently: compile check plus the full
test suite, both executed through the broker's sandboxed gateway. On failure,
``debug()`` asks the coordinator to analyze the captured failure output and
propose a fix — the fix is returned as a proposal only and is never applied
without the normal review/approval path.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import broker, runner

MAX_FAILURE_CHARS = 12_000


def verify(root: str | Path, *, timeout: int = 300) -> dict:
    """Run compile + unit tests for ``root`` through the sandboxed broker."""
    root = Path(root).resolve()
    if not (root / "src" / "babymind").is_dir():
        raise ValueError("The verification root does not contain src/babymind.")
    compile_result = broker.run_compile_check(root, sandbox_mode="require")
    tests_result = broker.run_unit_tests(root, timeout=timeout, sandbox_mode="require")
    summary = tests_result.get("summary", {})
    passed = bool(compile_result.get("ok")) and bool(summary.get("passed"))
    return {
        "root": str(root),
        "passed": passed,
        "compile_ok": bool(compile_result.get("ok")),
        "compile_stderr": (compile_result.get("stderr") or "")[-MAX_FAILURE_CHARS:],
        "tests": summary,
        "test_stdout": (tests_result.get("stdout") or "")[-MAX_FAILURE_CHARS:],
        "test_stderr": (tests_result.get("stderr") or "")[-MAX_FAILURE_CHARS:],
        "sandboxed": bool(compile_result.get("sandboxed") and tests_result.get("sandboxed")),
    }


def extract_failures(report: dict) -> str:
    """Pull the most useful failure excerpts from a verification report."""
    chunks = []
    if not report["compile_ok"] and report["compile_stderr"]:
        chunks.append("COMPILE ERRORS:\n" + report["compile_stderr"])
    for line in (report["test_stderr"] + "\n" + report["test_stdout"]).splitlines():
        if re.search(r"\b(FAILED|ERROR|Error|Traceback)\b", line):
            chunks.append(line.strip())
    text = "\n".join(chunks)[:MAX_FAILURE_CHARS]
    return text or "No failure excerpt was captured; rerun with full output."


def debug(report: dict, *, coordinator) -> dict:
    """Analyze a failed verification and propose (not apply) a fix."""
    if report["passed"]:
        return {"status": "passed", "proposal": None,
                "note": "Verification passed; nothing to debug."}
    excerpt = extract_failures(report)
    system = (
        "You are BabyMind's independent debugging reviewer. Analyze the failure "
        "output and return ONLY JSON: {\"diagnosis\": \"...\", \"suspect_files\": "
        "[\"src/babymind/example.py\"], \"proposed_fix\": \"...\", \"confidence\": "
        "\"low|medium|high\"}. Never claim a fix is verified; verification runs "
        "separately."
    )
    user = f"Verification failed at {report['root']}.\n\nFAILURE EXCERPT:\n{excerpt}"
    from .orchestrator import _extract_json
    import json
    proposal = json.loads(_extract_json(coordinator.provider.complete(system, user)))
    return {"status": "failed", "proposal": proposal,
            "note": "Proposal only — apply through the reviewed self-development path."}
