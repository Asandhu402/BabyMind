"""Task-graph execution: independent agent tasks with dependencies, run in parallel.

Replaces purely sequential role prompting for structured work: a mission brief
can be decomposed into a DAG of tasks, each assigned to an agent role. Tasks
whose dependencies have all completed start immediately and run concurrently
(up to ``max_workers``); every result is recorded.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from dataclasses import dataclass, field

MAX_TASKS = 50
MAX_DEPENDS = 10


class TaskGraphError(ValueError):
    """Raised when a task graph is malformed."""


@dataclass
class Task:
    task_id: str
    agent_id: str
    brief: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    agent_id: str
    status: str  # completed | failed | skipped
    output: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


def validate_graph(tasks: list[Task]) -> None:
    if not tasks:
        raise TaskGraphError("The task graph is empty.")
    if len(tasks) > MAX_TASKS:
        raise TaskGraphError(f"At most {MAX_TASKS} tasks per graph.")
    ids = [t.task_id for t in tasks]
    if len(set(ids)) != len(ids):
        raise TaskGraphError("Duplicate task ids.")
    for task in tasks:
        if not task.brief.strip():
            raise TaskGraphError(f"Task {task.task_id} has an empty brief.")
        if len(task.depends_on) > MAX_DEPENDS:
            raise TaskGraphError(f"Task {task.task_id} has too many dependencies.")
        for dep in task.depends_on:
            if dep not in ids:
                raise TaskGraphError(f"Task {task.task_id} depends on unknown task {dep}.")
            if dep == task.task_id:
                raise TaskGraphError(f"Task {task.task_id} depends on itself.")
    # Cycle detection via Kahn's algorithm.
    remaining = {t.task_id: set(t.depends_on) for t in tasks}
    ready = [tid for tid, deps in remaining.items() if not deps]
    seen = 0
    while ready:
        node = ready.pop()
        seen += 1
        for tid, deps in remaining.items():
            if node in deps:
                deps.discard(node)
                if not deps and tid not in ready:
                    ready.append(tid)
    if seen != len(remaining):
        raise TaskGraphError("The task graph contains a dependency cycle.")


class TaskGraphRunner:
    """Execute a validated task graph with parallel independent tasks."""

    def __init__(self, worker, *, max_workers: int = 4) -> None:
        # worker(task: Task, context: dict[str, TaskResult]) -> str
        self.worker = worker
        self.max_workers = max(1, min(max_workers, MAX_TASKS))
        self._lock = threading.Lock()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self, tasks: list[Task]) -> dict:
        validate_graph(tasks)
        by_id = {t.task_id: t for t in tasks}
        results: dict[str, TaskResult] = {}
        pending = set(by_id)
        futures: dict[Future, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            while pending or futures:
                if self._cancelled:
                    for future in futures:
                        future.cancel()
                    break
                # Launch every task whose dependencies are satisfied.
                for task_id in sorted(pending):
                    task = by_id[task_id]
                    if all(dep in results and results[dep].status == "completed"
                           for dep in task.depends_on):
                        pending.discard(task_id)
                        context = {tid: res for tid, res in results.items()}
                        futures[pool.submit(self._run_one, task, context)] = task_id
                if not futures:
                    if pending:
                        # Dependencies failed: skip the rest.
                        for task_id in pending:
                            results[task_id] = TaskResult(
                                task_id, by_id[task_id].agent_id, "skipped",
                                error="A dependency did not complete.")
                        pending.clear()
                    break
                # Wait for at least one running task to finish.
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    task_id = futures.pop(future)
                    results[task_id] = future.result()

        return {
            "tasks": [results[t.task_id].__dict__ for t in tasks],
            "completed": sum(1 for r in results.values() if r.status == "completed"),
            "failed": sum(1 for r in results.values() if r.status == "failed"),
            "skipped": sum(1 for r in results.values() if r.status == "skipped"),
            "cancelled": self._cancelled,
        }

    def _run_one(self, task: Task, context: dict[str, TaskResult]) -> TaskResult:
        started = time.monotonic()
        if self._cancelled:
            return TaskResult(task.task_id, task.agent_id, "skipped",
                              error="Cancelled.", started_at=started,
                              finished_at=time.monotonic())
        try:
            output = self.worker(task, context)
            return TaskResult(task.task_id, task.agent_id, "completed", output=output,
                              started_at=started, finished_at=time.monotonic())
        except Exception as error:  # a failing task must not kill the graph
            return TaskResult(task.task_id, task.agent_id, "failed", error=str(error),
                              started_at=started, finished_at=time.monotonic())
