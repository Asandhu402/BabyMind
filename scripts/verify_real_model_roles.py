#!/usr/bin/env python3
"""Opt-in real-model role, coding and disposable self-edit smoke test.

Use an ephemeral host with a pinned model installed by install-linux.sh. This
runs 50 sequential model calls and can take a long time. Generated code is
executed only if the OS sandbox's own boundary probes pass, and only inside a
throwaway project. It does not test the frozen desktop's self-edit capability.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
from pathlib import Path

from babymind import runner, sandbox
from babymind.coordinator import BabyMindCoordinator
from babymind.first_run import MODEL_FILENAME, MODEL_SHA256, _sha256
from babymind.integrations.coding import assist_with_code
from babymind.orchestrator import MissionStore, Orchestrator
from babymind.providers import LlamaCppProvider


def annotate(label: str, text: str) -> None:
    print(f"{label}: {text}", flush=True)
    if os.getenv("GITHUB_ACTIONS") == "true":
        safe = text[:5000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title={label}::{safe}", flush=True)


def extract_code(text: str) -> str:
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def test_project(root: Path) -> None:
    (root / "src" / "babymind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'disposable-check'\n")
    (root / "src" / "babymind" / "__init__.py").write_text("")
    (root / "src" / "babymind" / "core.py").write_text("VALUE = 1\n")
    (root / "tests" / "test_baseline.py").write_text(
        "import unittest\nfrom babymind.core import VALUE\n"
        "class Baseline(unittest.TestCase):\n"
        " def test_value(self): self.assertEqual(VALUE, 1)\n"
    )


def run(args) -> dict:
    model = Path(args.home) / ".babymind" / "models" / MODEL_FILENAME
    executable = Path(args.home) / ".local/share/babymind/current/llama.cpp/llama-server"
    if not model.is_file() or _sha256(model) != MODEL_SHA256:
        raise RuntimeError("Installed model is missing or does not match the pinned SHA-256.")
    if not executable.is_file():
        raise RuntimeError("Installed llama-server is missing.")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    os.environ.update({"BABYMIND_LLAMA_SERVER": str(executable), "BABYMIND_GGUF_MODEL": str(model),
                       "BABYMIND_LLAMA_PORT": str(port), "BABYMIND_CONTEXT_SIZE": "4096",
                       "BABYMIND_MAX_TOKENS": "96", "BABYMIND_TEMPERATURE": "0",
                       "OMP_NUM_THREADS": "2", "BABYMIND_SANDBOX": "require"})
    report = {"model_sha256": MODEL_SHA256, "questions": [], "warnings": [], "failures": []}
    provider = LlamaCppProvider()
    try:
        coordinator = BabyMindCoordinator(provider=provider)
        for question in ("What is 2 plus 2? Answer with the number only.",
                         "What color is a clear daytime sky? Answer in one word.",
                         "Why should someone keep backups? Answer in one sentence."):
            try:
                response = coordinator.ask("BM-01", question).response
                report["questions"].append({"question": question, "response": response})
                annotate("Chat response", f"{question} {response}")
                if question.startswith("What is 2 plus 2") and not re.search(r"\b(?:4|four)\b", response, re.IGNORECASE):
                    report["failures"].append("Arithmetic chat response did not contain 4.")
                if question.startswith("What color") and not re.search(r"\bblue\b", response, re.IGNORECASE):
                    report["failures"].append("Sky-color chat response did not contain blue.")
            except Exception as error:
                report["failures"].append(f"Chat error: {error}")
        with tempfile.TemporaryDirectory(prefix="babymind-acceptance-", dir=args.workdir) as temp:
            root = Path(temp) / "project"
            test_project(root)
            evidence = sandbox.self_test(root)
            report["sandbox"] = evidence
            if not evidence.get("verified"):
                report["failures"].append("OS sandbox probes did not pass; generated coding and self-edit code was not executed.")
            os.environ["BABYMIND_MAX_TOKENS"] = "256"
            try:
                response = assist_with_code(provider, "Write a complete Python function named add(a, b) that returns the sum. Return only code.")
                report["coding_response"] = response
                annotate("Coding response", response)
                if evidence.get("verified"):
                    (root / "src" / "solution.py").write_text(extract_code(response), encoding="utf-8")
                    (root / "tests" / "test_solution.py").write_text(
                        "import unittest\nfrom solution import add\nclass Coding(unittest.TestCase):\n"
                        " def test_numbers(self):\n  self.assertEqual(add(2, 3), 5)\n  self.assertEqual(add(-1, 4), 3)\n")
                    result = runner.run_unit_tests(root, timeout=120, sandbox="require")
                    report["coding_test"] = result["summary"]
                    annotate("Sandboxed coding test", json.dumps(result["summary"]))
                    if not result["sandboxed"] or not result["summary"]["passed"]:
                        report["failures"].append("Model-generated coding answer failed its sandboxed tests.")
                    (root / "src" / "solution.py").unlink(missing_ok=True)
                    (root / "tests" / "test_solution.py").unlink(missing_ok=True)
            except Exception as error:
                report["failures"].append(f"Coding test error: {error}")

            if evidence.get("verified"):
                os.environ.update({"BABYMIND_DEV_ROOT": str(root), "BABYMIND_SELF_DEVELOPMENT_ENABLED": "true"})
                store = MissionStore(Path(temp) / "selfedit-records")
                worker = Orchestrator(provider, store, max_seconds=120)
                brief = ("In src/babymind/core.py, whose complete current content is VALUE = 1, "
                         "preserve VALUE and add a Python function add(a, b) returning a + b. "
                         "Edit only src/babymind/core.py, not tests or other files.")
                try:
                    edit = worker._run_self_edit("disposable-test", brief, [])
                    report["self_edit"] = edit
                    annotate("Source self-edit", json.dumps(edit))
                    if edit.get("status") != "applied" or edit.get("files") != ["src/babymind/core.py"]:
                        report["failures"].append("Model did not apply the requested disposable core edit.")
                    else:
                        (root / "tests" / "test_added.py").write_text(
                            "import unittest\nfrom babymind.core import add\nclass Added(unittest.TestCase):\n"
                            " def test_numbers(self):\n  self.assertEqual(add(2, 3), 5)\n  self.assertEqual(add(-1, 4), 3)\n")
                        checked = runner.run_unit_tests(root, timeout=120, sandbox="require")
                        report["self_edit_test"] = checked["summary"]
                        annotate("Sandboxed self-edit behavior test", json.dumps(checked["summary"]))
                        if not checked["sandboxed"] or not checked["summary"]["passed"]:
                            report["failures"].append("Self-edit did not pass the independent sandboxed behavior test.")
                except Exception as error:
                    report["failures"].append(f"Self-edit test error: {error}")
            else:
                report["self_edit"] = {"status": "not tested", "reason": "OS sandbox probes failed"}

            # Bounded responses make a full 50-role pass practical on a CPU VM.
            os.environ["BABYMIND_MAX_TOKENS"] = "72"
            def update(_id, role):
                print(f"ROLE {role.agent_id} {role.status} {role.seconds:.1f}s: {(role.output or role.error)[:160]}", flush=True)
            worker = Orchestrator(provider, MissionStore(Path(temp) / "mission-records"),
                                  max_seconds=4200, on_update=update)
            mission = worker.run_now("Review a small Python function that adds two numbers. Give specific advice and tests.")
            report["mission"] = {key: mission[key] for key in ("status", "counts", "agents_recorded", "runs", "summary")}
            annotate("50-role mission", mission["summary"])
            if mission["agents_recorded"] != 50 or mission["counts"].get("contributed", 0) != 50:
                report["failures"].append("Not all 50 role calls returned text.")
            report["warnings"].append("Role status checks only nonempty text; competence and correctness need independent review.")
            group = mission["runs"][:3]
            annotate("Role output sample", "\n".join(f"{r['agent_id']}: {(r['output'] or r['error'])[:180]}" for r in group))
    finally:
        provider.stop()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    try:
        report = run(args)
    except Exception as error:
        report = {"failures": [str(error)]}
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    annotate("Acceptance summary", json.dumps({"failures": report.get("failures"), "warnings": report.get("warnings")}))
    return 1 if report.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
