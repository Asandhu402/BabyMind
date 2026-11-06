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
    # Hard gates: compile, tests, runtime behavior, security boundary.
    report["passed"] = (
        report["compile_ok"] and bool(summary.get("passed"))
        and report["behavior"]["ok"] and report["security"]["ok"]
    )
    if coordinator is not None and brief:
        # Preliminary only (same shared model): reported, but not a hard gate.
        report["fulfilment"] = _fulfilment_check(coordinator, root, brief)
    return report


def _behavior_check(root: Path) -> dict:
    """Run a generated app entry point (if any) inside the sandbox and check
    that it produces output and exits cleanly — runtime behavior, not just
    compile/tests."""
    apps = root / "apps"
    entries = sorted(set(apps.glob("*/*/app.py")) | set(apps.glob("*/app.py"))) if apps.is_dir() else []
    if not entries:
        return {"ok": True, "detail": "No generated app entry point present; behavior check not applicable."}
    import sys
    results = []
    for entry in entries:
        app_dir = entry.parent
        result = broker.execute([sys.executable, "-u", entry.name],
                                cwd=app_dir, allowed_root=app_dir, timeout=60,
                                sandbox_mode="require")
        results.append({
            "entry": str(entry.relative_to(root)),
            "exit_code": result["exit_code"],
            "stdout": result["stdout"][-2000:],
            "sandboxed": result["sandboxed"],
            "ok": result["exit_code"] == 0 and bool(result["stdout"].strip()) and result["sandboxed"],
        })
    return {"ok": all(r["ok"] for r in results), "apps": results,
            "checked": len(results)}


def _security_check(root: Path) -> dict:
    """Prove the sandbox boundary with the live adversarial self-test."""
    from . import sandbox
    if not sandbox.available():
        return {"ok": False, "detail": "No OS sandbox backend; security properties cannot be verified."}
    evidence = sandbox.self_test(root)
    return {"ok": bool(evidence["verified"]), "backend": evidence["backend"],
            "checks": {k: v.get("ok") for k, v in evidence["checks"].items()}}


def _fulfilment_check(coordinator, root: Path, brief: str) -> dict:
    """Preliminary acceptance review against the brief, inspecting bounded
    file CONTENTS (not just paths). Honest limitation: this uses the same
    shared local model, so it is a preliminary review, not a genuinely
    independent inspection — recorded as such."""
    from .orchestrator import parse_model_json
    chunks = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            continue
        if total > 40_000:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(text)
        chunks.append(f"--- {path.relative_to(root)} ---\n{text[:4000]}")
    system = ("You are an acceptance reviewer. You share one local model with the "
              "system under review, so this is a PRELIMINARY review, not independent "
              "verification. Return ONLY JSON: {\"fulfilled\": true|false, \"evidence\": "
              "\"...\", \"gaps\": \"...\"}. Judge against the brief and the actual file "
              "contents; do not trust claims.")
    user = f"BRIEF:\n{brief}\n\nFILE CONTENTS (bounded):\n" + "\n".join(chunks)
    verdict = parse_model_json(coordinator.provider.complete(system, user))
    if not isinstance(verdict, dict):
        raise ValueError("the model did not return a JSON object")
    return {"fulfilled": bool(verdict.get("fulfilled")),
            "independence": "preliminary — same shared local model, not an independent inspection",
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
    from .orchestrator import parse_model_json
    proposal = parse_model_json(coordinator.provider.complete(system, user))
    if not isinstance(proposal, dict):
        raise ValueError("the model did not return a JSON object")
    return {"status": "failed", "proposal": proposal,
            "note": "Proposal only — apply through the reviewed self-development path."}
