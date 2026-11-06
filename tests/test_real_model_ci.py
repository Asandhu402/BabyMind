"""BabyMind's CI must not have optional paths.

The pinned model is the application's brain, and the installer, the ~2.71 GB
download, the pinned checksum, the installed desktop and real inference have to
be exercised on every push and pull request - not only when someone dispatches
the workflow by hand or ticks a box first. These checks read the workflow file
itself; they do not run a model.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/tests.yml"
JOB = "real-model-installer"

# A step may be skipped only to avoid running after a cancelled run or a failed
# prerequisite - never to leave part of BabyMind untested.
ALLOWED_STEP_CONDITIONS = {"!cancelled()", "steps.installer.outcome == 'success'"}


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
        gated = re.findall(r"(?m)^    if:.*$", self.jobs[JOB])
        self.assertEqual(gated, [], f"{JOB} is gated by a job-level condition: {gated}")

    def test_real_model_job_still_uses_the_real_installer_model_and_harnesses(self):
        body = self.jobs[JOB]
        for expected in ("install-linux.sh",
                         "scripts/verify_installed_desktop.py",
                         "scripts/verify_real_model_roles.py"):
            self.assertIn(expected, body, f"{JOB} no longer runs {expected}")

    def test_the_full_gui_question_set_runs_every_time(self):
        # The extended question set used to be a manual variant; it is now the
        # only path, so no run can pass on the single smoke question alone.
        body = self.jobs[JOB]
        self.assertIn("--extended-chat", body)
        self.assertIn("--report", body)
        self.assertNotIn("EXTENDED_CHAT", body)

    def test_real_model_failures_are_reported_as_annotations_and_exit_nonzero(self):
        body = self.jobs[JOB]
        self.assertEqual(body.count("ci_acceptance_diagnostics.py"), 3)
        self.assertEqual(body.count("exit \"$status\""), 3)


class NoOptionalCiPathTests(unittest.TestCase):
    """No job may be skippable, and no switch may select a subset of the jobs."""

    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.jobs = job_bodies(self.text)

    def test_there_are_jobs_to_check(self):
        self.assertGreaterEqual(len(self.jobs), 5)

    def test_no_job_is_gated_by_a_condition(self):
        gated = {name: re.findall(r"(?m)^    if:.*$", body)
                 for name, body in self.jobs.items()}
        self.assertEqual({name: c for name, c in gated.items() if c}, {},
                         "these jobs can be skipped")

    def test_no_dispatch_switch_selects_a_subset_of_the_jobs(self):
        self.assertNotIn("inputs.", self.text,
                         "a workflow_dispatch input can still select which jobs run")

    def test_step_conditions_only_propagate_failures(self):
        for name, body in self.jobs.items():
            for condition in re.findall(r"(?m)^        if:.*$", body):
                inner = condition.split("if:", 1)[1].strip()
                inner = inner.removeprefix("${{").removesuffix("}}").strip()
                parts = {part.strip() for part in inner.split("&&")}
                self.assertTrue(parts <= ALLOWED_STEP_CONDITIONS,
                                f"{name}: unexpected step condition {condition!r}")


if __name__ == "__main__":
    unittest.main()
