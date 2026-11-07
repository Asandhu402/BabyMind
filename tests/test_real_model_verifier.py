"""Tests for the real-model acceptance script's control flow.

These drive ``scripts/verify_real_model_roles.py`` with patched providers so the
script's own logic is exercised without a model, a sandbox or a network.

The script no longer runs a 50-role mission (that feature was removed), so the
role-count and duplicate-role assertions are gone. It now drives the same
self-development path the learning cycle uses: ``coding_engine.develop``.
"""
from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_real_model_roles.py"
spec = importlib.util.spec_from_file_location("verify_real_model_roles", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class RealModelVerifierTests(unittest.TestCase):
    def test_extract_code(self):
        self.assertEqual(verifier.extract_code("```python\nprint(1)\n```"), "print(1)")
        self.assertEqual(verifier.extract_code("print(2)"), "print(2)")

    def test_annotation_escapes_untrusted_workflow_commands(self):
        stream = io.StringIO()
        with redirect_stdout(stream), patch.dict(verifier.os.environ,
                                                 {"GITHUB_ACTIONS": "true"}):
            verifier.annotate("Coding response", "hello\n::error::forged%message")
        lines = stream.getvalue().splitlines()
        self.assertIn("hello%0A::error::forged%25message", lines[1])
        self.assertFalse(any(line.startswith("::error::") for line in lines))

    def _exercise(self, *, probe, mode="ok", expect_run_tests=0,
                  chat_responses=("4", "blue", "To recover lost data.")):
        """Run the script end to end with every external boundary patched.

        ``mode`` selects what the fake self-development engine does:

        * ``"ok"``      -- the disposable core edit is applied and verified;
        * ``"reject"``  -- the engine rolls back, so no verification runs;
        * ``"real"``    -- the real-source copy edit is also applied;
        * ``"error"``   -- the sandboxed test runner raises.

        ``expect_run_tests`` is the exact number of sandboxed suite runs:
        the coding check, then the disposable core edit, then the real-source
        copy edit, minus any skipped because the sandbox probe failed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            model = home / ".babymind/models/model.gguf"
            executable = home / ".local/share/babymind/current/llama.cpp/llama-server"
            model.parent.mkdir(parents=True)
            executable.parent.mkdir(parents=True)
            model.write_bytes(b"fixture")
            executable.write_bytes(b"fixture")

            def develop(provider, brief, *, attempts=1):
                if mode == "reject":
                    # Nothing is applied, so no verification run may follow.
                    return {"status": "rolled_back", "result": {"files": []}}
                if "__init__.py" in brief:
                    self.assertIn("double(n)", brief)
                    copied = Path(verifier.os.environ["BABYMIND_DEV_ROOT"])
                    source = copied / "src" / "babymind" / "__init__.py"
                    source.write_text(source.read_text() + "\ndef double(n): return n * 2\n")
                    return {"status": "applied",
                            "result": {"files": [{"path": "src/babymind/__init__.py"}]}}
                self.assertIn("add(a, b)", brief)
                copied = Path(verifier.os.environ["BABYMIND_DEV_ROOT"])
                core = copied / "src" / "babymind" / "core.py"
                core.write_text(core.read_text() + "\ndef add(a, b): return a + b\n")
                return {"status": "applied",
                        "result": {"files": [{"path": "src/babymind/core.py"}]}}

            with patch.object(verifier, "MODEL_FILENAME", "model.gguf"), \
                 patch.object(verifier, "MODEL_SHA256", "fixture"), \
                 patch.object(verifier, "_sha256", return_value="fixture"), \
                 patch.object(verifier, "LlamaCppProvider"), \
                 patch.object(verifier, "BabyMindCoordinator") as coordinator, \
                 patch.object(verifier, "assist_with_code", return_value="generated code"), \
                 patch.object(verifier, "coding_engine") as engine, \
                 patch.object(verifier.sandbox, "self_test", side_effect=probe) as sandbox_probe, \
                 patch.object(verifier.runner, "run_unit_tests") as run_tests, \
                 patch.dict(verifier.os.environ, {}, clear=False), redirect_stdout(io.StringIO()):
                coordinator.return_value.ask.side_effect = [
                    SimpleNamespace(response=response) for response in chat_responses
                ]
                engine.develop.side_effect = develop
                if mode == "error":
                    run_tests.side_effect = RuntimeError("simulated runner error")
                else:
                    run_tests.return_value = {"sandboxed": True, "summary": {"passed": True}}
                result = verifier.run(SimpleNamespace(home=str(home), workdir=tmp))
                self.assertEqual(run_tests.call_count, expect_run_tests)
                if expect_run_tests:
                    self.assertEqual(run_tests.call_args.kwargs["sandbox"], "require")
                sandbox_probe.assert_called_once()
                # The live checkout must never be modified by any run.
                original = (SCRIPT.parents[1] / "src/babymind/__init__.py").read_text()
                self.assertNotIn("def double(n)", original)
                return result

    def test_chat_does_not_accept_incorrect_answers_that_mention_expected_words(self):
        result = self._exercise(probe=lambda root: {"verified": False},
                                chat_responses=("The answer is not 4", "Not blue", "Backups help."))
        self.assertTrue(any("Arithmetic" in item for item in result["failures"]))
        self.assertTrue(any("Sky-color" in item for item in result["failures"]))

    def test_no_generated_code_runs_without_verified_sandbox(self):
        result = self._exercise(probe=lambda root: {"verified": False})
        self.assertEqual(result["self_edit"]["status"], "not tested")
        self.assertTrue(any("sandbox" in item for item in result["failures"]))

    def test_probe_exception_fails_closed(self):
        def fail_probe(root):
            raise RuntimeError("probe failed")

        result = self._exercise(probe=fail_probe)
        self.assertIn("probe failed", result["sandbox"]["reason"])
        self.assertTrue(any("sandbox" in item for item in result["failures"]))
        self.assertEqual(result["self_edit"]["status"], "not tested")

    def test_coding_runner_exception_cleans_fixture_before_self_edit(self):
        # The coding check runs, then the disposable core edit's check fails.
        result = self._exercise(probe=lambda root: {"verified": True}, mode="error",
                                expect_run_tests=3)
        self.assertTrue(any("simulated runner error" in item for item in result["failures"]))

    def test_real_source_edit_is_verified_on_a_disposable_copy(self):
        original = (SCRIPT.parents[1] / "src/babymind/__init__.py").read_text()
        # Coding check, disposable core edit check, then the real-source copy.
        result = self._exercise(probe=lambda root: {"verified": True}, mode="real",
                                expect_run_tests=3)
        self.assertEqual(result["real_source_self_edit"]["status"], "applied")
        self.assertTrue(result["real_source_self_edit_test"]["passed"])
        # The live checkout must never be modified.
        self.assertEqual((SCRIPT.parents[1] / "src/babymind/__init__.py").read_text(), original)

    def test_a_rejected_edit_is_recorded_as_a_failure(self):
        # A verified sandbox still runs the coding check once, but a rolled-back
        # edit must never reach a verification run of its own.
        result = self._exercise(probe=lambda root: {"verified": True}, mode="reject",
                                expect_run_tests=1)
        self.assertTrue(any("disposable core edit" in item for item in result["failures"]))
        self.assertTrue(any("real-source copy" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
