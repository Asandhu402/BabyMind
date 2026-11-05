"""Unit coverage for the opt-in installed-desktop smoke-test harness.

These fakes do not test Qt, Ubuntu, a model or an installation.
"""
import importlib.util
import io
import tempfile
from contextlib import redirect_stdout
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_installed_desktop.py"
spec = importlib.util.spec_from_file_location("verify_installed_desktop", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
diagnostics_spec = importlib.util.spec_from_file_location(
    "ci_acceptance_diagnostics", SCRIPT.parent / "ci_acceptance_diagnostics.py"
)
diagnostics = importlib.util.module_from_spec(diagnostics_spec)
diagnostics_spec.loader.exec_module(diagnostics)


class InstalledDesktopVerifierTests(unittest.TestCase):
    def test_source_failure_annotation_finds_failure_before_long_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log"
            path.write_text("=" * 70 + "\nFAIL: test_bad (example.Test)\n" + "-" * 70 +
                            "\nTraceback: broken\n" + "-" * 70 +
                            "\nRan 1 test in 0.1s\nFAILED (failures=1)\n" + "x" * 4000)
            annotation = diagnostics.annotation(path, "Source tests", "1")
            self.assertIn("FAIL: test_bad", annotation)
            self.assertIn("Traceback: broken", annotation)

    def test_failure_annotation_escapes_workflow_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log"
            path.write_text("error 50%\nsecond line\r")
            annotation = diagnostics.annotation(path, "Installer", "1")
            self.assertIn("error 50%25%0Asecond line%0D", annotation)
            self.assertNotIn("\n", annotation)

    def test_extended_questions_record_wrong_answers_and_manual_review(self):
        questions = [("Arithmetic?", "4", True), ("Context?", "orbit", False),
                     ("Explain?", None, True), ("Product?", "63", True)]
        device = unittest.mock.Mock()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(verifier, "EXTENDED_QUESTIONS", questions), \
             patch.object(verifier, "wait_for", side_effect=["4", "ORBIT", "some explanation", "64"]), \
             patch.dict(verifier.os.environ, {"GITHUB_ACTIONS": "true"}), redirect_stdout(output):
            path = Path(tmp) / "report.json"
            result = verifier.run_extended_chat(device, path)
            self.assertEqual(verifier.json.loads(path.read_text())["requested"], 4)
        self.assertEqual(result["counts"]["matched expected answer"], 2)
        self.assertEqual(result["counts"]["manual review"], 1)
        self.assertEqual(result["counts"]["incorrect or format mismatch"], 1)
        calls = [call.args[0] for call in device.evaluate.call_args_list]
        self.assertIn("#newChat", calls[0])
        self.assertNotIn("#newChat", calls[1])
        self.assertIn("#newChat", calls[2])
        self.assertIn("GUI questions 1-4", output.getvalue())

    def test_extended_questions_keep_partial_report_on_timeout(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(verifier, "EXTENDED_QUESTIONS", [("question", "4", True)]), \
             patch.object(verifier, "wait_for", side_effect=TimeoutError("no answer")), \
             redirect_stdout(io.StringIO()):
            path = Path(tmp) / "report.json"
            result = verifier.run_extended_chat(unittest.mock.Mock(), path)
            self.assertEqual(result["counts"]["error"], 1)
            self.assertIn("no answer", verifier.json.loads(path.read_text())["results"][0]["error"])

    def test_missing_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "not found"):
                verifier.run(Path(tmp) / "missing", Path(tmp) / "log")

    def _run_with_answer(self, answer, *, expect_rejection=False):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "app"
            executable.write_text("fixture")
            executable.chmod(0o700)
            log = Path(tmp) / "desktop.log"
            output = io.StringIO()
            with patch.object(verifier.subprocess, "Popen") as popen, \
                 patch.object(verifier, "wait_for_page", return_value="ws://127.0.0.1:1/x"), \
                 patch.object(verifier, "DevTools") as devtools, \
                 patch.object(verifier, "wait_for", side_effect=[True, answer]), \
                 patch.object(verifier.os, "killpg"), redirect_stdout(output):
                if expect_rejection:
                    with self.assertRaisesRegex(RuntimeError, "expected answer"):
                        verifier.run(executable, log)
                else:
                    verifier.run(executable, log)
                popen.assert_called_once()
                env = popen.call_args.kwargs["env"]
                self.assertEqual(env["BABYMIND_MAX_TOKENS"], "64")
                self.assertTrue(env["QTWEBENGINE_REMOTE_DEBUGGING"].startswith("127.0.0.1:"))
                devtools.return_value.close.assert_called_once()
                popen.return_value.wait.assert_called_once()
            return output.getvalue()

    def test_model_output_cannot_emit_workflow_commands(self):
        with patch.dict(verifier.os.environ, {"GITHUB_ACTIONS": "true"}):
            output = self._run_with_answer("4\n::error::forged%message", expect_rejection=True)
        self.assertIn(r'GUI response: "4\n::error::forged%message"', output)
        self.assertFalse(any(line.startswith("::error::") for line in output.splitlines()))

    def test_accepts_correct_response(self):
        self._run_with_answer("4")

    def test_rejects_inference_error(self):
        with self.assertRaisesRegex(RuntimeError, "inference error"):
            self._run_with_answer("I couldn't complete that request. Error 4")

    def test_rejects_wrong_answer(self):
        for answer in ("5", "It is not 4", "4 and 5"):
            with self.subTest(answer=answer), self.assertRaisesRegex(RuntimeError, "expected answer"):
                self._run_with_answer(answer)


if __name__ == "__main__":
    unittest.main()
