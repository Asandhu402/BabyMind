#!/usr/bin/env python3
"""Real-model role, coding and disposable self-edit smoke test.

CI runs this on every push and pull request against an ephemeral host with the
pinned model installed by install-linux.sh. This runs 50 sequential model
calls and can take a long time. Generated code is executed only if the OS
sandbox's own boundary probes pass, and only inside a throwaway project. It
does not test the frozen desktop's self-edit capability.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path

from babymind import runner, sandbox
from babymind.agents import AGENTS
from babymind.coordinator import BabyMindCoordinator
from babymind.first_run import MODEL_FILENAME, MODEL_SHA256, _sha256
from babymind.integrations.coding import assist_with_code
from babymind.orchestrator import MissionStore, Orchestrator
from babymind.providers import LlamaCppProvider


def annotate(label: str, text: str) -> None:
    # Model output is untrusted: keep newlines/control characters escaped so
    # it cannot issue GitHub workflow commands by starting a new log line.
    print(f"{label}: {json.dumps(text, ensure_ascii=True)}", flush=True)
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


def copy_real_source_checkout(destination: Path) -> str:
    """Create a disposable copy for a real-source edit; never edit this checkout."""
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo, destination, ignore=shutil.ignore_patterns(
        ".git", ".venv", "venv", "build", "dist", "state", "__pycache__",
        ".pytest_cache", "node_modules", "*.pyc"))
    return (destination / "src" / "babymind" / "__init__.py").read_text(encoding="utf-8")


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
                if question.startswith("What is 2 plus 2") and not re.fullmatch(r"\s*(?:4|four)[.!]?\s*", response, re.IGNORECASE):
                    report["failures"].append("Arithmetic chat response was not the requested answer 4.")
                if question.startswith("What color") and not re.fullmatch(r"\s*blue[.!]?\s*", response, re.IGNORECASE):
                    report["failures"].append("Sky-color chat response was not the requested answer blue.")
            except Exception as error:
                report["failures"].append(f"Chat error: {error}")
        with tempfile.TemporaryDirectory(prefix="babymind-acceptance-", dir=args.workdir) as temp:
            root = Path(temp) / "project"
            test_project(root)
            try:
                evidence = sandbox.self_test(root)
            except Exception as error:
                # A broken probe must fail closed, without suppressing the
                # remaining read-only model/role checks.
                evidence = {"verified": False, "reason": f"Sandbox probe failed: {error}"}
            report["sandbox"] = evidence
            if not evidence.get("verified"):
                report["failures"].append("OS sandbox probes did not pass; generated coding and self-edit code was not executed.")
            os.environ["BABYMIND_MAX_TOKENS"] = "256"
            try:
                response = assist_with_code(provider, "Write a complete Python function named add(a, b) that returns the sum. Return only code.")
                report["coding_response"] = response
                annotate("Coding response", response)
                if evidence.get("verified"):
                    solution = root / "src" / "solution.py"
                    coding_test = root / "tests" / "test_solution.py"
                    try:
                        solution.write_text(extract_code(response), encoding="utf-8")
                        coding_test.write_text(
                            "import unittest\nfrom solution import add\nclass Coding(unittest.TestCase):\n"
                            " def test_numbers(self):\n  self.assertEqual(add(2, 3), 5)\n  self.assertEqual(add(-1, 4), 3)\n")
                        result = runner.run_unit_tests(root, timeout=120, sandbox="require")
                        report["coding_test"] = result["summary"]
                        annotate("Sandboxed coding test", json.dumps(result["summary"]))
                        if not result["sandboxed"] or not result["summary"]["passed"]:
                            report["failures"].append("Model-generated coding answer failed its sandboxed tests.")
                    finally:
                        solution.unlink(missing_ok=True)
                        coding_test.unlink(missing_ok=True)
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

            # Exercise the actual source on a disposable copy, not a fixture
            # masquerading as the application's core and never the live checkout.
            real_root = Path(temp) / "babymind-source-copy"
            real_content = copy_real_source_checkout(real_root)
            os.environ["BABYMIND_DEV_ROOT"] = str(real_root)
            brief = (
                "Review and improve src/babymind/__init__.py, whose complete current content follows:\n"
                + real_content + "\nPreserve that existing content and add a function "
                "is_valid_agent_id(value) that returns True only for strings BM-01 through BM-50 "
                "inclusive and False for all other values. Edit only src/babymind/__init__.py. "
                "Give concrete advice and tests; role outputs are suggestions, not actions."
            )
            # Bounded responses make a full 50-role pass practical on a CPU VM.
            os.environ["BABYMIND_MAX_TOKENS"] = "72"
            def update(_id, role):
                excerpt = json.dumps((role.output or role.error)[:160], ensure_ascii=True)
                print(f"ROLE {role.agent_id} {role.status} {role.seconds:.1f}s: {excerpt}", flush=True)
                if role.agent_id == AGENTS[-1].agent_id:
                    # The JSON file proposal needs more room than a role reply.
                    os.environ["BABYMIND_MAX_TOKENS"] = "512"
            worker = Orchestrator(provider, MissionStore(Path(temp) / "mission-records"),
                                  max_seconds=4200, on_update=update)
            mission = worker.run_now(brief, self_edit=bool(evidence.get("verified")))
            report["mission"] = {key: mission[key] for key in ("status", "counts", "agents_recorded", "runs", "summary")}
            real_edit = mission.get("self_edit") or {
                "status": "not tested", "reason": "OS sandbox probes failed or no self-edit was recorded"}
            report["real_source_self_edit"] = real_edit
            annotate("Real source mission self-edit", json.dumps(real_edit))
            if real_edit.get("status") != "applied" or real_edit.get("files") != ["src/babymind/__init__.py"]:
                report["failures"].append("Mission did not apply the requested edit to the disposable real-source copy.")
            elif not (real_root / "src" / "babymind" / "__init__.py").read_text(encoding="utf-8").startswith(real_content):
                report["failures"].append("Real-source edit did not preserve the original file content.")
            elif evidence.get("verified"):
                try:
                    (real_root / "tests" / "test_acceptance_agent_id.py").write_text(
                        "import unittest\nfrom babymind import is_valid_agent_id, AGENT_COUNT\n"
                        "class AgentId(unittest.TestCase):\n"
                        " def test_valid(self):\n"
                        "  for value in ('BM-01', 'BM-09', 'BM-10', 'BM-50'): self.assertIs(is_valid_agent_id(value), True)\n"
                        " def test_invalid(self):\n"
                        "  for value in ('BM-00', 'BM-51', 'BM-1', 'BM-01x', '', None, 1): self.assertIs(is_valid_agent_id(value), False)\n"
                        " def test_original_constant(self): self.assertEqual(AGENT_COUNT, 50)\n",
                        encoding="utf-8")
                    checked = runner.run_unit_tests(real_root, timeout=300, sandbox="require")
                    report["real_source_self_edit_test"] = checked["summary"]
                    annotate("Sandboxed real source behavior test", json.dumps(checked["summary"]))
                    if not checked["sandboxed"] or not checked["summary"]["passed"]:
                        report["failures"].append("Real-source edit failed independent sandboxed behavior tests.")
                except Exception as error:
                    report["failures"].append(f"Real-source self-edit behavior test error: {error}")
            annotate("50-role mission", mission["summary"])
            expected_ids = {agent.agent_id for agent in AGENTS}
            role_ids = [item["agent_id"] for item in mission["runs"]]
            if (mission["agents_recorded"] != len(expected_ids)
                    or mission["counts"].get("contributed", 0) != len(expected_ids)
                    or len(role_ids) != len(expected_ids) or set(role_ids) != expected_ids):
                report["failures"].append("Not every distinct registered role returned text.")
            report["warnings"].append("Role status checks only nonempty text; competence and correctness need independent review.")
            # Keep bounded samples for every role in check annotations as well
            # as the full artifact, which may not be downloadable on all hosts.
            for start in range(0, len(mission["runs"]), 10):
                group = mission["runs"][start:start + 10]
                annotate(f"Role outputs {start + 1}-{start + len(group)}", "\n".join(
                    f"{r['agent_id']} ({r.get('status', 'unknown')}): "
                    f"{(r['output'] or r['error'])[:300]}" for r in group))
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
