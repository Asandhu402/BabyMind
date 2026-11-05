"""Tests of acceptance harness safety logic, not actual model inference."""
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
        self.assertEqual(verifier.extract_code("Here:\n```python\ndef add(a, b): return a+b\n```"),
                         "def add(a, b): return a+b")
        self.assertEqual(verifier.extract_code("x = 1\n"), "x = 1")

    def test_annotation_escapes_untrusted_workflow_commands(self):
        output = io.StringIO()
        with patch.dict(verifier.os.environ, {"GITHUB_ACTIONS": "true"}), redirect_stdout(output):
            verifier.annotate("Model output", "hello\n::error::forged%message")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(r"hello\n::error::forged%message", lines[0])
        self.assertIn("hello%0A::error::forged%25message", lines[1])
        self.assertFalse(any(line.startswith("::error::") for line in lines))

    def _exercise(self, *, probe, mission_runs=None, test_error=False, real_success=False,
                  chat_responses=("4", "blue", "To recover lost data.")):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            model = home / ".babymind/models/model.gguf"
            executable = home / ".local/share/babymind/current/llama.cpp/llama-server"
            model.parent.mkdir(parents=True)
            executable.parent.mkdir(parents=True)
            model.write_bytes(b"fixture")
            executable.write_bytes(b"fixture")
            mission = {"status": "completed", "counts": {"contributed": 50}, "agents_recorded": 50,
                       "runs": [{"agent_id": agent.agent_id, "output": "text", "error": ""}
                                for agent in verifier.AGENTS], "summary": "unverified"}
            if mission_runs is not None:
                mission["runs"] = mission_runs
            with patch.object(verifier, "MODEL_FILENAME", "model.gguf"), \
                 patch.object(verifier, "MODEL_SHA256", "fixture"), \
                 patch.object(verifier, "_sha256", return_value="fixture"), \
                 patch.object(verifier, "LlamaCppProvider"), \
                 patch.object(verifier, "BabyMindCoordinator") as coordinator, \
                 patch.object(verifier, "assist_with_code", return_value="generated code"), \
                 patch.object(verifier, "MissionStore"), \
                 patch.object(verifier, "Orchestrator") as orchestrator, \
                 patch.object(verifier.sandbox, "self_test", side_effect=probe) as sandbox_probe, \
                 patch.object(verifier.runner, "run_unit_tests") as run_tests, \
                 patch.dict(verifier.os.environ, {}, clear=False), redirect_stdout(io.StringIO()):
                coordinator.return_value.ask.side_effect = [SimpleNamespace(response=response)
                                                            for response in chat_responses]
                orchestrator.return_value.run_now.return_value = mission
                if real_success:
                    def apply_real_edit(brief, *, self_edit):
                        self.assertTrue(self_edit)
                        copied = Path(verifier.os.environ["BABYMIND_DEV_ROOT"])
                        source = copied / "src/babymind/__init__.py"
                        source.write_text(source.read_text() + "\ndef is_valid_agent_id(value): return True\n")
                        return {**mission, "self_edit": {"status": "applied", "files": ["src/babymind/__init__.py"]}}
                    orchestrator.return_value.run_now.side_effect = apply_real_edit
                    orchestrator.return_value._run_self_edit.return_value = {"status": "no_change"}
                    run_tests.return_value = {"sandboxed": True, "summary": {"passed": True}}
                if test_error:
                    run_tests.side_effect = RuntimeError("simulated runner error")
                    def check_cleanup(*args):
                        root = sandbox_probe.call_args.args[0]
                        self.assertFalse((root / "src" / "solution.py").exists())
                        self.assertFalse((root / "tests" / "test_solution.py").exists())
                        return {"status": "no_change"}
                    orchestrator.return_value._run_self_edit.side_effect = check_cleanup
                result = verifier.run(SimpleNamespace(home=str(home), workdir=tmp))
                if test_error:
                    self.assertEqual(run_tests.call_count, 1)
                    orchestrator.return_value._run_self_edit.assert_called_once()
                elif real_success:
                    self.assertEqual(run_tests.call_count, 2)
                    self.assertEqual(run_tests.call_args.kwargs["sandbox"], "require")
                    self.assertIn("babymind-source-copy", str(run_tests.call_args.args[0]))
                else:
                    run_tests.assert_not_called()
                    orchestrator.return_value._run_self_edit.assert_not_called()
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

    def test_probe_exception_fails_closed_but_roles_are_exercised(self):
        def fail_probe(root):
            raise RuntimeError("probe failed")
        result = self._exercise(probe=fail_probe)
        self.assertEqual(result["mission"]["agents_recorded"], 50)
        self.assertIn("probe failed", result["sandbox"]["reason"])
        self.assertTrue(any("sandbox" in item for item in result["failures"]))

    def test_coding_runner_exception_cleans_fixture_before_self_edit(self):
        result = self._exercise(probe=lambda root: {"verified": True}, test_error=True)
        self.assertTrue(any("simulated runner error" in item for item in result["failures"]))

    def test_completed_mission_checks_disposable_real_source_in_sandbox(self):
        original = (SCRIPT.parents[1] / "src/babymind/__init__.py").read_text()
        result = self._exercise(probe=lambda root: {"verified": True}, real_success=True)
        self.assertEqual(result["real_source_self_edit"]["status"], "applied")
        self.assertTrue(result["real_source_self_edit_test"]["passed"])
        self.assertEqual((SCRIPT.parents[1] / "src/babymind/__init__.py").read_text(), original)

    def test_duplicate_roles_are_not_accepted_as_all_roles(self):
        runs = [{"agent_id": "BM-01", "output": "text", "error": ""} for _ in range(50)]
        result = self._exercise(probe=lambda root: {"verified": False}, mission_runs=runs)
        self.assertTrue(any("distinct registered role" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
