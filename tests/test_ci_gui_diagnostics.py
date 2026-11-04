"""Tests for retaining actionable diagnostics when the native GUI aborts."""
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest


spec = importlib.util.spec_from_file_location(
    "ci_gui_diagnostics", Path(__file__).resolve().parents[1] / "scripts" / "ci_gui_diagnostics.py"
)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class GuiDiagnosticTests(unittest.TestCase):
    def test_failure_annotation_escapes_workflow_commands(self):
        result = diagnostics.annotation("qt failure: 50%\r\n::error::untrusted", "134")
        self.assertTrue(result.startswith("::error title=Qt GUI smoke test::"))
        self.assertIn("exited 134", result)
        self.assertIn("50%25", result)
        self.assertIn("%0A::error::untrusted", result)
        self.assertNotIn("\n", result)

    def test_empty_and_large_logs_are_bounded(self):
        self.assertIn("log was empty", diagnostics.annotation("", "134"))
        result = diagnostics.annotation("error " + "x" * 100000, "134")
        self.assertLess(len(result), 25000)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires bash")
    def test_workflow_preserves_abort_and_emits_failure_annotation(self):
        repo = Path(__file__).resolve().parents[1]
        workflow = (repo / ".github/workflows/tests.yml").read_text()
        step = workflow.split("      - name: Exercise real Qt window with a local fixture\n", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
        script = script.replace(".venv/bin/python", shlex.quote(sys.executable))
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "xvfb-run"
            stub.write_text('#!/bin/sh\necho "Cannot load libxcb-cursor.so.0" >&2\nexit 134\n')
            stub.chmod(0o755)
            env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}", "RUNNER_TEMP": directory}
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                    cwd=repo, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 134, result.stdout + result.stderr)
        self.assertIn("::error title=Qt GUI smoke test::Qt GUI smoke test exited 134", result.stdout)
        self.assertIn("libxcb-cursor.so.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
