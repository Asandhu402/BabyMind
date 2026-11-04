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

    def test_no_generated_code_runs_without_verified_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            model = home / ".babymind/models/model.gguf"
            executable = home / ".local/share/babymind/current/llama.cpp/llama-server"
            model.parent.mkdir(parents=True)
            executable.parent.mkdir(parents=True)
            model.write_bytes(b"fixture")
            executable.write_bytes(b"fixture")
            mission = {"status": "completed", "counts": {"contributed": 50}, "agents_recorded": 50,
                       "runs": [], "summary": "unverified"}
            with patch.object(verifier, "MODEL_FILENAME", "model.gguf"), \
                 patch.object(verifier, "MODEL_SHA256", "fixture"), \
                 patch.object(verifier, "_sha256", return_value="fixture"), \
                 patch.object(verifier, "LlamaCppProvider"), \
                 patch.object(verifier, "BabyMindCoordinator") as coordinator, \
                 patch.object(verifier, "assist_with_code", return_value="generated code"), \
                 patch.object(verifier, "MissionStore"), \
                 patch.object(verifier, "Orchestrator") as orchestrator, \
                 patch.object(verifier.sandbox, "self_test", return_value={"verified": False}), \
                 patch.object(verifier.runner, "run_unit_tests") as run_tests, \
                 patch.dict(verifier.os.environ, {}, clear=False), redirect_stdout(io.StringIO()):
                coordinator.return_value.ask.side_effect = [
                    SimpleNamespace(response="4"), SimpleNamespace(response="blue"),
                    SimpleNamespace(response="To recover lost data.")]
                orchestrator.return_value.run_now.return_value = mission
                result = verifier.run(SimpleNamespace(home=str(home), workdir=tmp))
                run_tests.assert_not_called()
                orchestrator.return_value._run_self_edit.assert_not_called()
                self.assertEqual(result["self_edit"]["status"], "not tested")
                self.assertTrue(any("sandbox" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
