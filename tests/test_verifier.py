"""Tests for the independent verifier/debugger."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import broker, verifier


class StaticProvider:
    def __init__(self, text): self.text = text
    def complete(self, system, user): return self.text


class FakeCoordinator:
    def __init__(self, text): self.provider = StaticProvider(text)


def make_checkout(root: Path, *, broken: bool = False) -> None:
    (root / "src" / "babymind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "babymind" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "babymind" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text(
        "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
        + ("    def test_ok(self):\n        self.assertEqual(1, 2)\n" if broken else
           "    def test_ok(self):\n        self.assertEqual(1, 1)\n"),
        encoding="utf-8")


class VerifierTests(unittest.TestCase):
    def test_verify_passes_on_healthy_checkout(self):
        with TemporaryDirectory() as tmp:
            make_checkout(Path(tmp))
            report = verifier.verify(tmp, timeout=120)
            self.assertTrue(report["passed"], report)
            self.assertTrue(report["sandboxed"])

    def test_verify_fails_on_broken_checkout(self):
        with TemporaryDirectory() as tmp:
            make_checkout(Path(tmp), broken=True)
            report = verifier.verify(tmp, timeout=120)
            self.assertFalse(report["passed"])

    def test_debug_passing_report_needs_no_fix(self):
        report = {"passed": True, "root": "/x"}
        result = verifier.debug(report, coordinator=FakeCoordinator("{}"))
        self.assertEqual(result["status"], "passed")

    def test_debug_proposes_fix_without_applying(self):
        report = {"passed": False, "root": "/x", "compile_ok": True,
                  "compile_stderr": "", "test_stdout": "FAILED", "test_stderr": "AssertionError"}
        proposal = '{"diagnosis": "assertion mismatch", "suspect_files": ["tests/test_ok.py"], "proposed_fix": "fix the assertion", "confidence": "medium"}'
        result = verifier.debug(report, coordinator=FakeCoordinator(proposal))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["proposal"]["diagnosis"], "assertion mismatch")
        self.assertIn("proposal only", result["note"].lower())


if __name__ == "__main__":
    unittest.main()


class VerifierDepthTests(unittest.TestCase):
    def test_verify_includes_security_and_behavior_sections(self):
        with TemporaryDirectory() as tmp:
            make_checkout(Path(tmp))
            report = verifier.verify(tmp, timeout=120)
            self.assertIn("security", report)
            self.assertIn("behavior", report)
            self.assertTrue(report["security"]["ok"])
            self.assertTrue(report["behavior"]["ok"])

    def test_fulfilment_check_uses_coordinator_and_never_self_attests(self):
        with TemporaryDirectory() as tmp:
            make_checkout(Path(tmp))
            verdict = '{"fulfilled": true, "evidence": "tests pass", "gaps": ""}'
            report = verifier.verify(tmp, timeout=120, coordinator=FakeCoordinator(verdict),
                                     brief="build a hello app")
            self.assertTrue(report["fulfilment"]["fulfilled"])
            self.assertTrue(report["passed"])
