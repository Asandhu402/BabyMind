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
    def test_failure_annotation_escapes_workflow_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log"
            path.write_text("error 50%\nsecond line\r")
            annotation = diagnostics.annotation(path, "Installer", "1")
            self.assertIn("error 50%25%0Asecond line%0D", annotation)
            self.assertNotIn("\n", annotation)

    def test_missing_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "not found"):
                verifier.run(Path(tmp) / "missing", Path(tmp) / "log")

    def _run_with_answer(self, answer):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "app"
            executable.write_text("fixture")
            executable.chmod(0o700)
            log = Path(tmp) / "desktop.log"
            with patch.object(verifier.subprocess, "Popen") as popen, \
                 patch.object(verifier, "wait_for_page", return_value="ws://127.0.0.1:1/x"), \
                 patch.object(verifier, "DevTools") as devtools, \
                 patch.object(verifier, "wait_for", side_effect=[True, answer]), \
                 patch.object(verifier.os, "killpg"), redirect_stdout(io.StringIO()):
                verifier.run(executable, log)
                popen.assert_called_once()
                env = popen.call_args.kwargs["env"]
                self.assertEqual(env["BABYMIND_MAX_TOKENS"], "64")
                self.assertTrue(env["QTWEBENGINE_REMOTE_DEBUGGING"].startswith("127.0.0.1:"))
                devtools.return_value.close.assert_called_once()
                popen.return_value.wait.assert_called_once()

    def test_accepts_correct_response(self):
        self._run_with_answer("4")

    def test_rejects_inference_error(self):
        with self.assertRaisesRegex(RuntimeError, "inference error"):
            self._run_with_answer("I couldn't complete that request. Error 4")

    def test_rejects_wrong_answer(self):
        with self.assertRaisesRegex(RuntimeError, "expected answer"):
            self._run_with_answer("5")


if __name__ == "__main__":
    unittest.main()
