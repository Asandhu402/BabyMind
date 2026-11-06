"""Tests for disposable worktree isolation and fail-closed auto mode."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import runner, taskgraph, worktree


def make_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "f.txt").write_text("hello\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, env=env, check=True)


class AutoModeTests(unittest.TestCase):
    def test_auto_fails_closed_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BABYMIND_ALLOW_UNSANDBOXED_AUTO", None)
            self.assertEqual(runner._sandbox_mode("auto"), "require")

    def test_auto_allowed_only_with_explicit_opt_in(self):
        with patch.dict(os.environ, {"BABYMIND_ALLOW_UNSANDBOXED_AUTO": "true"}):
            self.assertEqual(runner._sandbox_mode("auto"), "auto")


class WorktreeTests(unittest.TestCase):
    def test_create_and_discard_worktree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            tree = worktree.create_worktree(root)
            self.assertTrue((tree / "src" / "f.txt").is_file())
            (tree / "src" / "f.txt").write_text("changed\n")
            worktree.discard_worktree(root, tree)
            # primary checkout untouched
            self.assertEqual((root / "src" / "f.txt").read_text(), "hello\n")

    def test_non_git_repo_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(worktree.WorktreeError):
                worktree.create_worktree(Path(tmp))

    def test_preverification_worktree_includes_dirty_and_untracked_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            (root / "src" / "f.txt").write_text("working copy change\\n")
            (root / "tests").mkdir()
            (root / "tests" / "new_test.py").write_text("VALUE = 42\\n")
            tree = worktree.create_worktree(root, include_working_tree=True)
            try:
                self.assertEqual((tree / "src" / "f.txt").read_text(), "working copy change\\n")
                self.assertEqual((tree / "tests" / "new_test.py").read_text(), "VALUE = 42\\n")
                self.assertEqual((root / "src" / "f.txt").read_text(), "working copy change\\n")
            finally:
                worktree.discard_worktree(root, tree)


class TaskGraphStoreTests(unittest.TestCase):
    def test_durable_state_and_resume(self):
        with TemporaryDirectory() as tmp:
            store = taskgraph.TaskGraphStore(tmp)
            tasks = [taskgraph.Task("a", "BM-01", "x"), taskgraph.Task("b", "BM-02", "y", depends_on=["a"])]
            calls = []

            def worker(task, context):
                calls.append(task.task_id)
                return "out-" + task.task_id

            runner1 = taskgraph.TaskGraphRunner(worker, max_workers=2)
            r1 = runner1.run(tasks, graph_id="g1", store=store)
            self.assertEqual(r1["completed"], 2)
            self.assertIsNotNone(store.load("g1"))
            self.assertEqual(sorted(store.completed_results("g1")), ["a", "b"])

            # Resume: nothing re-runs.
            runner2 = taskgraph.TaskGraphRunner(worker, max_workers=2)
            r2 = runner2.run(tasks, graph_id="g1", store=store, resume=True)
            self.assertEqual(calls, ["a", "b"])
            self.assertEqual(r2["completed"], 2)

    def test_typed_input_is_carried(self):
        seen = {}

        def worker(task, context):
            seen[task.task_id] = task.input
            return "ok"

        t = taskgraph.Task("a", "BM-01", "x", input={"key": "value"})
        taskgraph.TaskGraphRunner(worker).run([t])
        self.assertEqual(seen["a"], {"key": "value"})


if __name__ == "__main__":
    unittest.main()
