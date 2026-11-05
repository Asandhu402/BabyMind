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


def verify(root: str | Path, *, timeout: int = 300, coordinator=None, brief: str = "") -> dict:
    """Independently verify ``root``: compile, tests, runtime behavior, and
    (when a sandbox backend exists) the security boundary itself. With a
    coordinator and brief, also judge requirement fulfilment — model
    self-attestation is never treated as a pass."""
    root = Path(root).resolve()
    if not (root / "src" / "babymind").is_dir():
        raise ValueError("The verification root does not contain src/babymind.")
    compile_result = broker.run_compile_check(root, sandbox_mode="require")
    tests_result = broker.run_unit_tests(root, timeout=timeout, sandbox_mode="require")
    summary = tests_result.get("summary", {})
    report = {
        "root": str(root),
        "compile_ok": bool(compile_result.get("ok")),
        "compile_stderr": (compile_result.get("stderr") or "")[-MAX_FAILURE_CHARS:],
        "tests": summary,
        "test_stdout": (tests_result.get("stdout") or "")[-MAX_FAILURE_CHARS:],
        "test_stderr": (tests_result.get("stderr") or "")[-MAX_FAILURE_CHARS:],
        "sandboxed": bool(compile_result.get("sandboxed") and tests_result.get("sandboxed")),
        "behavior": _behavior_check(root),
        "security": _security_check(root),
        "fulfilment": None,
    }
    report["passed"] = (
        report["compile_ok"] and bool(summary.get("passed"))
        and report["behavior"]["ok"] and report["security"]["ok"]
    )
    if coordinator is not None and brief:
        report["fulfilment"] = _fulfilment_check(coordinator, root, brief)
        report["passed"] = report["passed"] and bool(report["fulfilment"]["fulfilled"])
    return report


def _behavior_check(root: Path) -> dict:
    """Run a generated app entry point (if any) inside the sandbox and check
    that it produces output and exits cleanly — runtime behavior, not just
    compile/tests."""
    apps = root / "apps"
    entries = sorted(apps.glob("*/*/app.py")) + sorted(apps.glob("*/app.py")) if apps.is_dir() else []
    if not entries:
        return {"ok": True, "detail": "No generated app entry point present; behavior check not applicable."}
    entry = entries[0]
    app_dir = entry.parent
    result = broker.execute([__import__("sys").executable, "-u", entry.name],
                            cwd=app_dir, allowed_root=app_dir, timeout=60,
                            sandbox_mode="require")
    ok = result["exit_code"] == 0 and bool(result["stdout"].strip()) and result["sandboxed"]
    return {"ok": ok, "entry": str(entry.relative_to(root)),
            "exit_code": result["exit_code"], "stdout": result["stdout"][-2000:],
            "sandboxed": result["sandboxed"]}


def _security_check(root: Path) -> dict:
    """Prove the sandbox boundary with the live adversarial self-test."""
    from . import sandbox
    if not sandbox.available():
        return {"ok": False, "detail": "No OS sandbox backend; security properties cannot be verified."}
    evidence = sandbox.self_test(root)
    return {"ok": bool(evidence["verified"]), "backend": evidence["backend"],
            "checks": {k: v.get("ok") for k, v in evidence["checks"].items()}}


def _fulfilment_check(coordinator, root: Path, brief: str) -> dict:
    """Ask the model to judge whether the implementation fulfils the brief.
    Recorded as evidence, never as a self-attested pass."""
    import json
    from .orchestrator import _extract_json
    tree = [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()][:200]
    system = ("You are an independent acceptance reviewer. Return ONLY JSON: "
              '{"fulfilled": true|false, "evidence": "...", "gaps": "..."}. '
              "Judge against the brief and the actual files; do not trust claims.")
    user = f"BRIEF:\n{brief}\n\nFILES:\n" + "\n".join(tree)
    verdict = json.loads(_extract_json(coordinator.provider.complete(system, user)))
    return {"fulfilled": bool(verdict.get("fulfilled")),
            "evidence": str(verdict.get("evidence", ""))[:1000],
            "gaps": str(verdict.get("gaps", ""))[:1000]}


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
