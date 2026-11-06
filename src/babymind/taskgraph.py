"""Task-graph execution: independent agent tasks with dependencies, run in parallel.

Replaces purely sequential role prompting for structured work: a mission brief
can be decomposed into a DAG of tasks, each assigned to an agent role. Tasks
whose dependencies have all completed start immediately and run concurrently
(up to ``max_workers``); every result is recorded.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from pathlib import Path

MAX_TASKS = 50
MAX_DEPENDS = 60  # a phase-to-phase graph can depend on a whole previous phase

# Registry of in-flight graphs so HTTP callers can cancel them by id.
_RUNNING: dict[str, "TaskGraphRunner"] = {}
_REGISTRY_LOCK = threading.Lock()


def register(graph_id: str, runner: "TaskGraphRunner") -> None:
    with _REGISTRY_LOCK:
        _RUNNING[graph_id] = runner


def cancel_running(graph_id: str) -> dict:
    with _REGISTRY_LOCK:
        runner = _RUNNING.get(graph_id)
    if runner is None:
        return {"cancelled": False, "notice": f"No running task graph with id {graph_id}."}
    runner.cancel()
    return {"cancelled": True, "notice": "Cancellation requested; running tasks finish or hit their timeout, pending tasks are skipped."}


def unregister(graph_id: str) -> None:
    with _REGISTRY_LOCK:
        _RUNNING.pop(graph_id, None)


class TaskGraphError(ValueError):
    """Raised when a task graph is malformed."""


@dataclass
class Task:
    task_id: str
    agent_id: str
    brief: str
    depends_on: list[str] = field(default_factory=list)
    input: dict = field(default_factory=dict)  # typed input payload for the worker


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
        """Request cancellation: pending futures are cancelled and running
        tasks are asked to stop at their next checkpoint (should_cancel)."""
        self._cancelled = True

    def run(self, tasks: list[Task], *, graph_id: str | None = None,
            should_cancel=None, store: "TaskGraphStore | None" = None,
            resume: bool = False) -> dict:
        validate_graph(tasks)
        self._should_cancel = should_cancel
        prior: dict[str, TaskResult] = {}
        if resume and store is not None and graph_id:
            prior = store.completed_results(graph_id, tasks)
        if graph_id:
            register(graph_id, self)
        try:
            if store is not None and graph_id:
                store.save(graph_id, tasks, self._result_payload(tasks, prior, False))
            result = self._execute(
                tasks, prior,
                on_change=(
                    (lambda current: store.save(graph_id, tasks, current))
                    if store is not None and graph_id else None
                ),
            )
            if store is not None and graph_id:
                store.save(graph_id, tasks, result)
            return result
        finally:
            if graph_id:
                unregister(graph_id)

    def _is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        checker = getattr(self, "_should_cancel", None)
        return bool(checker and checker())

    @staticmethod
    def _result_payload(tasks: list[Task], results: dict[str, TaskResult],
                        cancelled: bool) -> dict:
        ordered = [results[t.task_id].__dict__ for t in tasks if t.task_id in results]
        return {
            "tasks": ordered,
            "completed": sum(1 for item in ordered if item["status"] == "completed"),
            "failed": sum(1 for item in ordered if item["status"] == "failed"),
            "skipped": sum(1 for item in ordered if item["status"] == "skipped"),
            "cancelled": cancelled,
        }

    def _execute(self, tasks: list[Task], prior: dict[str, TaskResult] | None = None,
                 on_change=None) -> dict:
        by_id = {t.task_id: t for t in tasks}
        results: dict[str, TaskResult] = dict(prior or {})
        pending = set(by_id) - set(results)
        futures: dict[Future, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            while pending or futures:
                if self._is_cancelled():
                    for future in futures:
                        future.cancel()
                    for task_id in pending:
                        results[task_id] = TaskResult(
                            task_id, by_id[task_id].agent_id, "skipped", error="Cancelled.")
                    pending.clear()
                    # Running calls cannot be killed safely. Wait for them to
                    # finish and persist their real outcome instead of falsely
                    # recording them as skipped.
                    for future, task_id in list(futures.items()):
                        if future.cancelled():
                            results[task_id] = TaskResult(
                                task_id, by_id[task_id].agent_id, "skipped",
                                error="Cancelled before task started.")
                        else:
                            results[task_id] = future.result()
                        if on_change:
                            on_change(self._result_payload(tasks, results, True))
                    futures.clear()
                    if on_change:
                        on_change(self._result_payload(tasks, results, True))
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
                    if on_change:
                        on_change(self._result_payload(tasks, results, self._is_cancelled()))

        return self._result_payload(tasks, results, self._is_cancelled())

    def _run_one(self, task: Task, context: dict[str, TaskResult]) -> TaskResult:
        started = time.monotonic()
        if self._is_cancelled():
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


class TaskGraphStore:
    """Durable, resumable graph state: every run is persisted as JSON under
    ``<root>/state/taskgraph/`` so a crashed or cancelled graph can resume
    without re-running completed tasks."""

    def __init__(self, root) -> None:
        self.dir = Path(root) / "state" / "taskgraph"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _fingerprint(tasks: list[Task]) -> str:
        canonical = json.dumps(
            [task.__dict__ for task in tasks],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, graph_id: str) -> Path:
        safe = "".join(c for c in graph_id if c.isalnum() or c in {"-", "_"})[:64]
        return self.dir / f"{safe or 'graph'}.json"

    def save(self, graph_id: str, tasks: list[Task], result: dict) -> None:
        import json
        payload = {
            "id": graph_id,
            "fingerprint": self._fingerprint(tasks),
            "saved_at": time.time(),
            "tasks": [t.__dict__ for t in tasks],
            "result": result,
        }
        path = self._path(graph_id)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        with self._lock:
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(path)
            # Persist the directory entry as well as the file contents.
            try:
                directory_fd = os.open(self.dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Some filesystems do not support directory fsync; the
                # atomic replace still prevents readers seeing partial JSON.
                pass

    def load(self, graph_id: str) -> dict | None:
        import json
        path = self._path(graph_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def completed_results(self, graph_id: str,
                          tasks: list[Task] | None = None) -> dict[str, TaskResult]:
        record = self.load(graph_id)
        if not record:
            return {}
        # Never replay results against a changed task graph. Legacy records
        # without a fingerprint are deliberately treated as non-resumable.
        if tasks is not None and record.get("fingerprint") != self._fingerprint(tasks):
            return {}
        out = {}
        for item in record.get("result", {}).get("tasks", []):
            if item.get("status") == "completed":
                out[item["task_id"]] = TaskResult(
                    item["task_id"], item["agent_id"], "completed",
                    output=item.get("output", ""), error=item.get("error", ""),
                    started_at=item.get("started_at", 0.0), finished_at=item.get("finished_at", 0.0))
        return out
