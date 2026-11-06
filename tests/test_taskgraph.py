"""Tests for the parallel task-graph runner."""
from __future__ import annotations

import threading
import time
import unittest

from babymind.taskgraph import Task, TaskGraphError, TaskGraphRunner, validate_graph


def sample_tasks():
    return [
        Task("a", "BM-01", "task a"),
        Task("b", "BM-02", "task b"),
        Task("c", "BM-03", "task c", depends_on=["a", "b"]),
        Task("d", "BM-04", "task d", depends_on=["c"]),
    ]


class TaskGraphValidationTests(unittest.TestCase):
    def test_cycle_is_rejected(self):
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "BM-01", "x", depends_on=["b"]),
                            Task("b", "BM-02", "y", depends_on=["a"])])

    def test_unknown_dependency_is_rejected(self):
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "BM-01", "x", depends_on=["nope"])])

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(TaskGraphError):
            validate_graph([Task("a", "BM-01", "x"), Task("a", "BM-02", "y")])


class TaskGraphRunnerTests(unittest.TestCase):
    def test_independent_tasks_run_in_parallel(self):
        running = 0
        peak = 0
        lock = threading.Lock()

        def worker(task, context):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.15)
            with lock:
                running -= 1
            return f"done-{task.task_id}"

        result = TaskGraphRunner(worker, max_workers=4).run(sample_tasks())
        self.assertEqual(result["completed"], 4)
        self.assertGreaterEqual(peak, 2, "independent tasks should overlap")
        outputs = {t["task_id"]: t["output"] for t in result["tasks"]}
        self.assertEqual(outputs["d"], "done-d")

    def test_dependency_receives_completed_context(self):
        seen = {}

        def worker(task, context):
            seen[task.task_id] = sorted(context)
            return task.task_id

        result = TaskGraphRunner(worker, max_workers=2).run(sample_tasks())
        self.assertEqual(seen["c"], ["a", "b"])
        self.assertEqual(seen["d"], ["a", "b", "c"])
        self.assertEqual(result["completed"], 4)

    def test_failed_dependency_skips_dependents(self):
        def worker(task, context):
            if task.task_id == "a":
                raise RuntimeError("boom")
            return task.task_id

        result = TaskGraphRunner(worker, max_workers=2).run(sample_tasks())
        self.assertEqual(result["failed"], 1)
        statuses = {t["task_id"]: t["status"] for t in result["tasks"]}
        self.assertEqual(statuses["c"], "skipped")
        self.assertEqual(statuses["d"], "skipped")
        self.assertEqual(statuses["b"], "completed")


if __name__ == "__main__":
    unittest.main()


class TaskGraphCancellationTests(unittest.TestCase):
    def test_cancel_with_queued_futures_records_every_task(self):
        started, release = threading.Event(), threading.Event()
        def worker(task, context):
            started.set()
            release.wait(3)
            return task.task_id
        runner = TaskGraphRunner(worker, max_workers=1)
        result_box = {}
        def run():
            try:
                result_box['result'] = runner.run([Task(str(i), 'BM-01', 'work') for i in range(8)])
            except Exception as error:
                result_box['error'] = error
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(started.wait(2))
        runner.cancel()
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertNotIn('error', result_box)
        self.assertTrue(result_box['result']['cancelled'])
        self.assertEqual(len(result_box['result']['tasks']), 8)
        self.assertGreater(result_box['result']['skipped'], 0)

    def test_registered_graph_can_be_cancelled_by_id(self):
        from babymind import taskgraph
        started = threading.Event()

        def worker(task, context):
            started.set()
            time.sleep(5)
            return task.task_id

        runner = TaskGraphRunner(worker, max_workers=1)
        result_box = {}

        def run():
            result_box["result"] = runner.run([Task("only", "BM-01", "slow")], graph_id="g1")

        t = threading.Thread(target=run)
        t.start()
        started.wait(5)
        outcome = taskgraph.cancel_running("g1")
        self.assertTrue(outcome["cancelled"])
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertTrue(result_box["result"]["cancelled"])
        self.assertEqual(taskgraph.cancel_running("g1")["cancelled"], False)
