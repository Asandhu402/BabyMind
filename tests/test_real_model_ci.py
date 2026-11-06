"""The real-model acceptance job must stay permanent CI, never opt-in.

The pinned model is the application's brain: the installer, the ~2.71 GB
download, the pinned checksum and real inference have to be exercised on every
push and pull request, not only when someone dispatches the workflow by hand.
These checks read the workflow file itself; they do not run a model.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/tests.yml"
JOB = "real-model-installer"


def job_bodies(text: str) -> dict[str, str]:
    """Map each top-level job key to the text of its body."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


class RealModelJobIsPermanentTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.jobs = job_bodies(self.text)

    def test_workflow_runs_on_every_push_and_pull_request(self):
        triggers = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        for event in ("push:", "pull_request:"):
            self.assertIn(event, triggers, f"{event} is not a workflow trigger")
        for block in re.findall(r"(?m)^  (?:push|pull_request):\n((?:    .*\n)+)", triggers):
            self.assertIn("branches: [main]", block)

    def test_real_model_job_exists(self):
        self.assertIn(JOB, self.jobs)

    def test_real_model_job_is_not_gated_by_any_condition(self):
        # A job-level `if:` is the only thing that can make it optional again.
        body = self.jobs[JOB]
        gated = re.findall(r"(?m)^    if:.*$", body)
        self.assertEqual(gated, [], f"{JOB} is gated by a job-level condition: {gated}")

    def test_no_dispatch_input_can_switch_the_real_model_job_off_or_on(self):
        self.assertNotIn("real_model_test", self.text)
        dispatch = self.text.split("\n  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertNotIn(JOB, dispatch, "the job must not depend on a dispatch input")

    def test_real_model_job_still_uses_the_real_installer_model_and_harnesses(self):
        body = self.jobs[JOB]
        for expected in ("install-linux.sh",
                         "scripts/verify_installed_desktop.py",
                         "scripts/verify_real_model_roles.py"):
            self.assertIn(expected, body, f"{JOB} no longer runs {expected}")

    def test_real_model_failures_are_reported_as_annotations_and_exit_nonzero(self):
        body = self.jobs[JOB]
        self.assertEqual(body.count("ci_acceptance_diagnostics.py"), 3)
        self.assertEqual(body.count("exit \"$status\""), 3)


if __name__ == "__main__":
    unittest.main()
