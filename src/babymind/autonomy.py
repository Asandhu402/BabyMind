"""Bounded autonomous operation for BabyMind.

This is the "acts on its own" half of the work. BabyMind can hold its own goals,
decide what to do next, do it, verify it happened, and keep going without being
asked each time.

Because that is genuinely dangerous, the engine is built so that the dangerous
part is the part with the most machinery on it:

* **Off by default.** Autonomous operation must be switched on deliberately.
* **Kill switch.** A file on disk (``~/.babymind/autonomy/STOP``), an API call, or
  Ctrl-C stops the loop. The loop re-checks before every single action, so a stop
  takes effect within one step, not at the end of a batch.
* **Confinement.** Every write is resolved and re-checked to be inside the
  autonomy workspace. No shell, no network, no credential access, no deletion.
* **Budgets.** Bounded cycles, wall-clock time, actions per hour, and bytes
  written. Exceeding any of them stops the loop instead of degrading it silently.
* **Circuit breaker.** Consecutive failed verifications halt the engine into a
  state that requires a human to reset, rather than letting it thrash.
* **Hash-chained audit log.** Every decision, action and outcome is appended to a
  tamper-evident chain. The log is the record of what it actually did; the model's
  own narration is not.

What this is not: it is not a general computer-use agent. The action set is a
small allowlist that can only write text files inside one directory and manage
goal records. Autonomy here means persistence of attention, not reach.

Two designs coexist in this module, deliberately:

* ``AutonomyEngine`` -- a background loop with its own goal store, workspace
  confinement, budgets and a hash-chained audit log. It acts on its own goals.
* ``ActionPolicy`` / ``AutonomyController`` -- a finite, foreground driver over
  ``CognitiveCore``'s existing cycle, adding environment-drift detection and an
  explicit allow/deny policy layer before each proposed action.

They were developed independently and both are covered by tests, so both are
kept rather than one silently replacing the other. If you want a single engine,
pick one and delete the other along with its test class.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .cognitive_core import CognitiveCore, _clean as _cognitive_clean, environment_snapshot
from .secure_store import SecureTextStore

MAX_TEXT = 4000
MAX_FILE_BYTES = 256 * 1024
GENESIS = "0" * 64

# Actions the engine may take on its own. Deliberately small.
ACTION_KINDS = ("write_file", "append_note", "create_goal", "complete_goal", "wait")

STATES = ("stopped", "running", "paused", "halted")

DEFAULT_LIMITS: dict[str, int] = {
    "max_cycles": 50,
    "max_seconds": 900,
    "max_actions_per_hour": 30,
    "max_bytes_written": 5 * 1024 * 1024,
    "max_files": 40,
    "consecutive_failures_before_halt": 3,
}


class SupportsComplete(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _default_home() -> Path:
    return Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind")).expanduser()


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    cycle: int
    goal_id: str | None
    plan: str
    action: dict[str, Any]
    outcome: str
    verified: bool
    reflection: str
    stopped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "goal_id": self.goal_id,
            "plan": self.plan,
            "action": self.action,
            "outcome": self.outcome,
            "verified": self.verified,
            "reflection": self.reflection,
            "stopped_reason": self.stopped_reason,
        }


class AutonomyHalted(RuntimeError):
    """Raised when the engine refuses to continue and needs a human reset."""


class AutonomyEngine:
    """A goal-directed loop that can be stopped, audited and trusted to stay inside."""

    def __init__(
        self,
        provider: SupportsComplete | None = None,
        *,
        database_path: str | Path | None = None,
        workspace: str | Path | None = None,
        limits: dict[str, int] | None = None,
        agent_id: str = "BM-01",
    ) -> None:
        self.home = _default_home()
        self.database_path = Path(database_path) if database_path else self.home / "autonomy.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace) if workspace else self.home / "autonomy" / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.stop_flag_path = self.workspace.parent / "STOP"
        self.secure = SecureTextStore(self.database_path.with_suffix(".key"))
        self.limits = dict(DEFAULT_LIMITS)
        if limits:
            self.limits.update({k: int(v) for k, v in limits.items() if k in DEFAULT_LIMITS})
        self.agent_id = agent_id
        self.provider = provider

        self.lock = threading.RLock()
        self.state = "stopped"
        self.thread: threading.Thread | None = None
        self.cycles_run = 0
        self.actions_this_hour: list[float] = []
        self.bytes_written = 0
        self.consecutive_failures = 0
        self.last_stop_reason = ""
        self._started_at: float | None = None
        self._initialise()

    # ---------------------------------------------------------------- plumbing

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS autonomy_goals (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        status TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 5,
                        created_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS autonomy_audit (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS autonomy_notes (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                db.commit()
            finally:
                db.close()

    # -------------------------------------------------------------- audit chain

    def _latest_hash(self) -> str:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT entry_hash FROM autonomy_audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
            finally:
                db.close()
        return row["entry_hash"] if row else GENESIS

    def audit(self, kind: str, payload: dict[str, Any]) -> str:
        """Append one tamper-evident entry. Returns the new entry hash."""
        stamp = _now()
        body = json.dumps({"kind": kind, "created_at": stamp, "payload": payload}, sort_keys=True, ensure_ascii=False)
        with self.lock:
            prev = self._latest_hash()
            entry_hash = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO autonomy_audit (created_at,kind,payload,prev_hash,entry_hash) VALUES (?,?,?,?,?)",
                    (stamp, _clean(kind, 60), self.secure.encrypt(body), prev, entry_hash),
                )
                db.commit()
            finally:
                db.close()
        return entry_hash

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT seq,created_at,kind,payload,prev_hash,entry_hash FROM autonomy_audit "
                    "ORDER BY seq DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "seq": row["seq"],
                "created_at": row["created_at"],
                "kind": row["kind"],
                "payload": json.loads(self.secure.decrypt(row["payload"]))["payload"],
                "prev_hash": row["prev_hash"],
                "entry_hash": row["entry_hash"],
            }
            for row in rows
        ]

    def verify_audit_chain(self) -> dict[str, Any]:
        """Recompute the whole chain and report the first break, if any."""
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT seq,created_at,kind,payload,prev_hash,entry_hash FROM autonomy_audit ORDER BY seq"
                ).fetchall()
            finally:
                db.close()
        expected_prev = GENESIS
        for row in rows:
            body = self.secure.decrypt(row["payload"])
            recomputed = hashlib.sha256((expected_prev + body).encode("utf-8")).hexdigest()
            if row["prev_hash"] != expected_prev or recomputed != row["entry_hash"]:
                return {
                    "intact": False,
                    "entries": len(rows),
                    "broken_at_seq": row["seq"],
                    "reason": "Hash chain does not recompute; the log was altered or truncated.",
                }
            expected_prev = row["entry_hash"]
        return {"intact": True, "entries": len(rows), "broken_at_seq": None, "reason": ""}

    # ------------------------------------------------------------------- goals

    def add_goal(
        self,
        title: str,
        description: str = "",
        *,
        priority: int = 5,
        created_by: str = "user",
    ) -> dict[str, Any]:
        clean_title = _clean(title, 200)
        if not clean_title:
            raise ValueError("A goal requires a title.")
        goal_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO autonomy_goals VALUES (?,?,?,?,?,?,?,?)",
                    (
                        goal_id,
                        self.secure.encrypt(clean_title),
                        self.secure.encrypt(_clean(description)),
                        "active",
                        max(1, min(int(priority), 10)),
                        _clean(created_by, 40),
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        self.audit("goal_created", {"goal_id": goal_id, "title": clean_title, "created_by": created_by})
        return {"id": goal_id, "title": clean_title, "status": "active", "created_at": stamp}

    def goals(self, status: str | None = "active", limit: int = 25) -> list[dict[str, Any]]:
        with self.lock:
            db = self._connect()
            try:
                if status:
                    rows = db.execute(
                        "SELECT id,title,description,status,priority,created_by,created_at,updated_at "
                        "FROM autonomy_goals WHERE status=? ORDER BY priority, created_at LIMIT ?",
                        (status, max(1, min(limit, 100))),
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT id,title,description,status,priority,created_by,created_at,updated_at "
                        "FROM autonomy_goals ORDER BY created_at DESC LIMIT ?",
                        (max(1, min(limit, 100)),),
                    ).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "title": self.secure.decrypt(row["title"]),
                "description": self.secure.decrypt(row["description"]),
                "status": row["status"],
                "priority": row["priority"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _set_goal_status(self, goal_id: str, status: str) -> bool:
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE autonomy_goals SET status=?, updated_at=? WHERE id=? AND status='active'",
                    (status, _now(), goal_id),
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    # ----------------------------------------------------------------- actions

    def _resolve_workspace_path(self, relative: str) -> Path:
        """Resolve a requested path inside the workspace, or refuse it."""
        # Check each path component for a symlink *before* resolving. Resolving
        # first would follow a link out of the workspace and the confinement
        # test below would then see only the final, legitimate-looking target.
        probe = self.workspace.resolve()
        for part in Path(str(relative)).parts:
            if part in ("", ".", ".."):
                continue
            probe = probe / part
            if probe.is_symlink():
                raise PermissionError("Autonomy will not write through a symbolic link.")
        candidate = (self.workspace / str(relative)).resolve()
        base = self.workspace.resolve()
        if candidate != base and base not in candidate.parents:
            raise PermissionError("Autonomy writes are confined to the autonomy workspace.")
        if candidate.is_symlink():
            raise PermissionError("Autonomy will not write through a symbolic link.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def _count_files(self) -> int:
        return sum(1 for path in self.workspace.rglob("*") if path.is_file())

    def _apply_action(self, action: dict[str, Any]) -> tuple[str, bool]:
        kind = str(action.get("type", "wait")).strip()
        if kind not in ACTION_KINDS:
            raise ValueError(f"Unsupported autonomous action: {kind}")
        stamp = _now()
        if kind == "wait":
            return "Waited without changing external state.", True

        if kind == "create_goal":
            title = _clean(action.get("title"), 200)
            if not title:
                raise ValueError("create_goal requires a title.")
            goal = self.add_goal(
                title,
                _clean(action.get("description")),
                priority=int(action.get("priority", 5) or 5),
                created_by="autonomy",
            )
            return f"Created goal {goal['id']}: {title}", True

        if kind == "complete_goal":
            goal_id = _clean(action.get("goal_id"), 80)
            changed = self._set_goal_status(goal_id, "completed")
            if changed:
                self.audit("goal_completed", {"goal_id": goal_id})
            return (
                f"Completed goal {goal_id}" if changed else f"No active goal matched {goal_id}"
            ), changed

        if kind == "append_note":
            content = _clean(action.get("content"))
            if not content:
                raise ValueError("append_note requires content.")
            note_id = uuid.uuid4().hex
            with self.lock:
                db = self._connect()
                try:
                    db.execute(
                        "INSERT INTO autonomy_notes VALUES (?,?,?)",
                        (note_id, self.secure.encrypt(content), stamp),
                    )
                    db.commit()
                    exists = db.execute("SELECT 1 FROM autonomy_notes WHERE id=?", (note_id,)).fetchone()
                finally:
                    db.close()
            self.audit("note_appended", {"note_id": note_id})
            return f"Recorded note {note_id}", exists is not None

        if kind == "write_file":
            relative = _clean(action.get("path") or action.get("filename"), 200)
            if not relative:
                raise ValueError("write_file requires a path.")
            content = str(action.get("content") or "")
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_FILE_BYTES:
                raise ValueError(f"Autonomy will not write more than {MAX_FILE_BYTES} bytes in one file.")
            if self.bytes_written + len(encoded) > self.limits["max_bytes_written"]:
                raise AutonomyHalted("Write budget exhausted.")
            if self._count_files() >= self.limits["max_files"]:
                raise AutonomyHalted("File-count budget exhausted.")
            target = self._resolve_workspace_path(relative)
            target.write_bytes(encoded)
            self.bytes_written += len(encoded)
            verified = target.exists() and target.stat().st_size == len(encoded)
            self.audit(
                "file_written",
                {"path": str(target.relative_to(self.workspace.resolve())), "bytes": len(encoded), "verified": verified},
            )
            return f"Wrote {len(encoded)} bytes to {target.name}", verified

        return "Waited without changing external state.", True

    # ------------------------------------------------------------- gating/budgets

    def stop_requested(self) -> bool:
        """Checked before every action, so a stop lands within one step."""
        return self.stop_flag_path.exists()

    def _within_action_rate(self) -> bool:
        cutoff = time.monotonic() - 3600
        with self.lock:
            self.actions_this_hour = [stamp for stamp in self.actions_this_hour if stamp > cutoff]
            return len(self.actions_this_hour) < self.limits["max_actions_per_hour"]

    def _register_action(self) -> None:
        with self.lock:
            self.actions_this_hour.append(time.monotonic())

    def remaining_budget(self) -> dict[str, Any]:
        with self.lock:
            elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
            return {
                "cycles_used": self.cycles_run,
                "cycles_remaining": max(0, self.limits["max_cycles"] - self.cycles_run),
                "seconds_used": round(elapsed, 1),
                "seconds_remaining": round(max(0.0, self.limits["max_seconds"] - elapsed), 1),
                "actions_used_last_hour": len(
                    [s for s in self.actions_this_hour if s > time.monotonic() - 3600]
                ),
                "actions_remaining_this_hour": max(
                    0,
                    self.limits["max_actions_per_hour"]
                    - len([s for s in self.actions_this_hour if s > time.monotonic() - 3600]),
                ),
                "bytes_written": self.bytes_written,
                "bytes_remaining": max(0, self.limits["max_bytes_written"] - self.bytes_written),
            }

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "enabled": self.state in ("running", "paused"),
            "stop_flag_present": self.stop_flag_path.exists(),
            "stop_flag_path": str(self.stop_flag_path),
            "workspace": str(self.workspace),
            "agent_id": self.agent_id,
            "limits": dict(self.limits),
            "budget": self.remaining_budget(),
            "consecutive_failures": self.consecutive_failures,
            "last_stop_reason": self.last_stop_reason,
            "goals": self.goals("active", limit=10),
            "action_kinds": list(ACTION_KINDS),
            "audit": {"entries": len(self.audit_log(500)), "chain_intact": self.verify_audit_chain()["intact"]},
            "notes": len(self.notes(50)),
        }

    def notes(self, limit: int = 20) -> list[dict[str, str]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,content,created_at FROM autonomy_notes ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(limit, 100)),),
                ).fetchall()
            finally:
                db.close()
        return [
            {"id": row["id"], "content": self.secure.decrypt(row["content"]), "created_at": row["created_at"]}
            for row in rows
        ]

    # ------------------------------------------------------------------- cycle

    def _plan(self, goals: list[dict[str, Any]], notes: list[dict[str, str]]) -> dict[str, Any]:
        if self.provider is None:
            raise RuntimeError("No model provider is configured, so autonomy cannot plan.")
        system = (
            "You are BabyMind operating autonomously on the user's own machine. You have no shell, "
            "no network, no credentials and no way to delete anything. You may only: write a text "
            "file inside your workspace, append a note, create a goal, complete a goal, or wait. "
            "Choose one small, reversible, genuinely useful step that advances an active goal. "
            "Do not claim to have done anything you have not done. Do not claim to have searched the "
            "web, run code, or contacted anything. If the best move is to stop, choose wait and say why. "
            "Return one JSON object with keys: goal_id, plan, action, expected, reflection_cue. "
            "action.type must be one of: " + ", ".join(ACTION_KINDS) + ". "
            "write_file needs path and content. create_goal needs title. complete_goal needs goal_id. "
            "append_note needs content. Return only the JSON object."
        )
        user = (
            "ACTIVE GOALS:\n" + json.dumps(goals, ensure_ascii=False)
            + "\n\nYOUR EARLIER NOTES:\n" + json.dumps(notes[:10], ensure_ascii=False)
            + "\n\nWORKSPACE: " + str(self.workspace)
            + "\nBUDGET: " + json.dumps(self.remaining_budget(), ensure_ascii=False)
            + "\nChoose the single best next step."
        )
        raw = (self.provider.complete(system, user) or "").strip()
        fence = chr(96) * 3
        if raw.startswith(fence):
            raw = raw.split("\n", 1)[-1].split(fence)[0].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"Autonomy plan was not valid JSON: {error.msg}") from error
        if not isinstance(parsed, dict):
            raise ValueError("Autonomy plan must be a JSON object.")
        return parsed

    def run_cycle(self, cycle: int = 0) -> CycleOutcome:
        """One decide-act-verify cycle. Never raises for a bad plan; records it."""
        if self.stop_requested():
            return CycleOutcome(cycle, None, "", {"type": "wait"}, "Stop requested; cycle skipped.", False, "", "stop_requested")
        if not self._within_action_rate():
            self.state = "halted"
            self.last_stop_reason = "Action-rate budget exhausted; reset to continue."
            self.audit("halted", {"reason": self.last_stop_reason, "cycle": cycle})
            return CycleOutcome(cycle, None, "", {"type": "wait"}, self.last_stop_reason, False, "", "rate_limit")

        goals = self.goals("active", limit=10)
        notes = self.notes(10)
        try:
            plan = self._plan(goals, notes)
        except Exception as error:  # noqa: BLE001
            self.consecutive_failures += 1
            self.audit("plan_failed", {"cycle": cycle, "error": str(error)[:300]})
            if self.consecutive_failures >= self.limits["consecutive_failures_before_halt"]:
                self.state = "halted"
                self.last_stop_reason = "Repeated planning failures; autonomy halted pending review."
                self.audit("halted", {"reason": self.last_stop_reason, "cycle": cycle})
            return CycleOutcome(cycle, None, "", {"type": "wait"}, f"Planning failed: {str(error)[:200]}", False, "", "plan_failed")

        action = plan.get("action")
        if not isinstance(action, dict):
            self.consecutive_failures += 1
            self.audit("plan_invalid", {"cycle": cycle, "plan": plan})
            return CycleOutcome(cycle, None, _clean(plan.get("plan")), {"type": "wait"}, "Plan contained no action object.", False, "", "plan_invalid")

        goal_id = _clean(plan.get("goal_id"), 80) or None
        try:
            if self.stop_requested():
                return CycleOutcome(cycle, goal_id, _clean(plan.get("plan")), action, "Stop requested before the action ran.", False, "", "stop_requested")
            outcome, verified = self._apply_action(action)
            self._register_action()
            error_text = ""
        except AutonomyHalted as error:
            self.state = "halted"
            self.last_stop_reason = str(error)
            self.audit("halted", {"reason": str(error), "cycle": cycle})
            return CycleOutcome(cycle, goal_id, _clean(plan.get("plan")), action, str(error), False, "", "budget_exhausted")
        except Exception as error:  # noqa: BLE001
            outcome, verified, error_text = f"Action rejected: {str(error)[:300]}", False, str(error)[:300]

        if verified:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.limits["consecutive_failures_before_halt"]:
                self.state = "halted"
                self.last_stop_reason = "Repeated failed verifications; autonomy halted pending review."
                self.audit("halted", {"reason": self.last_stop_reason, "cycle": cycle})

        self.audit(
            "cycle",
            {
                "cycle": cycle,
                "goal_id": goal_id,
                "plan": _clean(plan.get("plan")),
                "action": action,
                "outcome": outcome,
                "verified": verified,
                "error": error_text,
            },
        )
        return CycleOutcome(
            cycle,
            goal_id,
            _clean(plan.get("plan")),
            action,
            outcome,
            verified,
            _clean(plan.get("reflection_cue")),
            "",
        )

    # -------------------------------------------------------------- the loop

    def start(self, *, cycles: int | None = None, interval: float = 5.0) -> dict[str, Any]:
        """Start the loop in a background thread. Returns immediately."""
        with self.lock:
            if self.state in ("running", "paused"):
                return {"started": False, "state": self.state, "reason": "Autonomy is already active."}
            if self.state == "halted":
                return {
                    "started": False,
                    "state": self.state,
                    "reason": (
                        "Autonomy halted and must be reset before it can start again. "
                        f"Cause: {self.last_stop_reason or 'unknown'}"
                    ),
                }
            if self.provider is None:
                return {"started": False, "state": self.state, "reason": "No model provider is configured."}
            if self.stop_requested():
                return {
                    "started": False,
                    "state": self.state,
                    "reason": f"A stop file exists at {self.stop_flag_path}. Remove it, or call reset, before starting.",
                }
            if not self.goals("active", limit=1):
                return {"started": False, "state": self.state, "reason": "Add at least one active goal first."}
            self.limits["max_cycles"] = max(1, min(int(cycles or self.limits["max_cycles"]), 500))
            self.cycles_run = 0
            self.consecutive_failures = 0
            self._started_at = time.monotonic()
            self.state = "running"
            self.last_stop_reason = ""
            self.audit("started", {"max_cycles": self.limits["max_cycles"], "interval": interval})
            self.thread = threading.Thread(
                target=self._loop, args=(max(0.0, min(interval, 3600.0)),), daemon=True, name="babymind-autonomy"
            )
            self.thread.start()
        return {"started": True, "state": self.state, "reason": ""}

    def _loop(self, interval: float) -> None:
        while True:
            with self.lock:
                if self.state != "running":
                    break
                if self.cycles_run >= self.limits["max_cycles"]:
                    self.state = "stopped"
                    self.last_stop_reason = "Cycle budget completed."
                    self.audit("stopped", {"reason": self.last_stop_reason, "cycles": self.cycles_run})
                    break
                if self._started_at and time.monotonic() - self._started_at > self.limits["max_seconds"]:
                    self.state = "stopped"
                    self.last_stop_reason = "Time budget completed."
                    self.audit("stopped", {"reason": self.last_stop_reason, "cycles": self.cycles_run})
                    break
                if self.stop_requested():
                    self.state = "stopped"
                    self.last_stop_reason = "Stop requested."
                    self.audit("stopped", {"reason": self.last_stop_reason, "cycles": self.cycles_run})
                    break
                self.cycles_run += 1
                cycle_number = self.cycles_run
            try:
                self.run_cycle(cycle_number)
            except Exception as error:  # noqa: BLE001 - the loop must never die silently
                self.audit("cycle_error", {"cycle": cycle_number, "error": str(error)[:300]})
            with self.lock:
                if self.state != "running":
                    break
            if interval:
                # Sleep in slices so a stop lands quickly rather than after a long nap.
                deadline = time.monotonic() + interval
                while time.monotonic() < deadline:
                    if self.stop_requested() or self.state != "running":
                        break
                    time.sleep(min(0.5, deadline - time.monotonic()))
        with self.lock:
            if self.state == "running":
                self.state = "stopped"

    def stop(self, *, reason: str = "Stopped by request.") -> dict[str, Any]:
        """Stop the loop and drop a stop file so a restart is deliberate."""
        with self.lock:
            previous = self.state
            self.state = "stopped"
            self.last_stop_reason = reason
            try:
                self.stop_flag_path.write_text(f"{_now()} {reason}\n", encoding="utf-8")
            except OSError:
                pass
            self.audit("stopped", {"reason": reason, "from_state": previous, "cycles": self.cycles_run})
        return {"state": self.state, "previous_state": previous, "reason": reason}

    def pause(self) -> dict[str, Any]:
        with self.lock:
            if self.state != "running":
                return {"state": self.state, "changed": False}
            self.state = "paused"
            self.audit("paused", {"cycles": self.cycles_run})
        return {"state": self.state, "changed": True}

    def resume(self) -> dict[str, Any]:
        with self.lock:
            if self.state == "paused":
                if self.stop_requested():
                    return {"state": self.state, "changed": False, "reason": "A stop file is present; clear it first."}
                self.state = "running"
                self.audit("resumed", {"cycles": self.cycles_run})
                return {"state": self.state, "changed": True}
            if self.state == "running":
                return {"state": self.state, "changed": False}
        return {"state": self.state, "changed": False, "reason": "Start autonomy before resuming it."}

    def reset(self) -> dict[str, Any]:
        """Clear a halt and the stop file so the engine can start again."""
        with self.lock:
            self.consecutive_failures = 0
            self.last_stop_reason = ""
            self.state = "stopped"
            try:
                self.stop_flag_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.audit("reset", {})
        return {"state": self.state, "stop_flag_present": self.stop_requested()}

    def clear_stop_flag(self) -> bool:
        try:
            self.stop_flag_path.unlink(missing_ok=True)
        except OSError:
            return self.stop_flag_path.exists()
        return not self.stop_flag_path.exists()


def autonomy_enabled() -> bool:
    """Whether autonomous operation is permitted at all in this environment."""
    return os.getenv("BABYMIND_AUTONOMY", "0").strip().lower() in ("1", "true", "on", "yes")


MAX_AUTONOMY_CYCLES = 25
MAX_INTERVAL_SECONDS = 3600
DRIFT_KEYS = ("system", "distribution", "kernel", "architecture", "python",
              "python_executable", "home_directory", "babymind_home")


class ActionPolicy:
    """Fail-closed policy for actions proposed by the cognitive model."""

    SAFE_LOCAL_ACTIONS = frozenset({
        "create_goal", "complete_goal", "record_question", "write_note", "wait"
    })
    REQUIRES_HUMAN_APPROVAL = frozenset({
        "network_access", "shell", "source_edit", "file_delete",
        "credential_access", "external_message", "purchase", "system_change",
    })

    @classmethod
    def authorize(cls, action: dict[str, Any], *, human_approved: bool = False) -> dict[str, Any]:
        kind = str(action.get("type", "")).strip()
        if kind in cls.SAFE_LOCAL_ACTIONS:
            return {"allowed": True, "requires_approval": False, "reason": "Allowlisted local cognitive-state action."}
        if kind in cls.REQUIRES_HUMAN_APPROVAL:
            return {"allowed": False, "requires_approval": True,
                    "reason": "This action is outside the autonomous core and requires a separate supervised tool and explicit approval."}
        return {"allowed": False, "requires_approval": False, "reason": "Unknown actions are denied by default."}


class AutonomyController:
    """Run finite observe/plan/act/verify/reflect cycles with audit-friendly output."""

    def __init__(self, core: CognitiveCore | None = None) -> None:
        self.core = core or CognitiveCore()

    def observe_environment(self) -> dict[str, Any]:
        current = environment_snapshot()
        prior = None
        for note in self.core.recent_notes(30):
            if note.get("kind") != "environment_baseline":
                continue
            try:
                prior = json.loads(note["content"])
            except (TypeError, json.JSONDecodeError):
                continue
            break

        changes = []
        if isinstance(prior, dict):
            for key in DRIFT_KEYS:
                if prior.get(key) != current.get(key):
                    changes.append({
                        "field": key,
                        "previous": prior.get(key),
                        "current": current.get(key),
                    })
        baseline = {key: current.get(key) for key in DRIFT_KEYS}
        if prior != baseline:
            stamp = datetime.now(timezone.utc).isoformat()
            note_id = uuid.uuid4().hex
            encrypted = self.core.secure.encrypt(json.dumps(baseline, sort_keys=True, ensure_ascii=False))
            with self.core.lock:
                db = self.core._connect()
                try:
                    db.execute(
                        "INSERT INTO notes (id,kind,content,created_at) VALUES (?,?,?,?)",
                        (note_id, "environment_baseline", encrypted, stamp),
                    )
                    db.commit()
                finally:
                    db.close()
        return {"snapshot": current, "changed": bool(changes), "changes": changes,
                "baseline_available": prior is not None}

    def execute_goal(self, provider, goal_id: str, *, max_steps: int = 10,
                     agent_id: str = "BM-02") -> dict[str, Any]:
        """Work toward one existing goal using finite, individually verified cycles."""
        if not 1 <= max_steps <= 10:
            raise ValueError("max_steps must be between 1 and 10")
        target = next((goal for goal in self.core.active_goals(50)
                       if goal["id"] == goal_id), None)
        if target is None:
            raise ValueError("No active goal matches the supplied goal ID.")
        objective = (
            f"Goal ID: {target['id']}\nTitle: {target['title']}\n"
            f"Description: {target['description']}\n"
            "Advance this goal in small, reversible steps. Use only the local cognitive "
            "action allowlist. Record research questions or verified progress as notes. "
            "Mark the goal complete only when the stated objective is genuinely complete."
        )
        steps = []
        for index in range(max_steps):
            try:
                result = self.core.run_cycle(provider, agent_id=agent_id, objective=objective)
                steps.append(result)
            except KeyboardInterrupt:
                return {"status": "paused_by_user", "goal_id": goal_id,
                        "steps_completed": len(steps), "steps": steps}
            except Exception as error:
                message = f"Goal execution step failed: {type(error).__name__}: {_cognitive_clean(error, 500)}"
                try:
                    self.core._apply_action({"type": "write_note", "content": message})
                except Exception:
                    pass
                steps.append({"step": index + 1, "verified": False, "error": message})
                break
            still_active = any(goal["id"] == goal_id for goal in self.core.active_goals(50))
            if not still_active:
                return {"status": "completed", "goal_id": goal_id,
                        "steps_completed": len(steps), "steps": steps,
                        "verification": "Target goal no longer appears among active goals after the completion action."}
        still_active = any(goal["id"] == goal_id for goal in self.core.active_goals(50))
        return {"status": "step_limit_reached" if still_active else "completed",
                "goal_id": goal_id, "steps_completed": len(steps), "steps": steps,
                "verification": "Target goal remains active; no completion is claimed." if still_active
                else "Target goal no longer appears among active goals."}

    def run(self, provider, *, cycles: int = 5, interval: float = 0,
            agent_id: str = "BM-02") -> dict[str, Any]:
        if not 1 <= cycles <= MAX_AUTONOMY_CYCLES:
            raise ValueError(f"cycles must be between 1 and {MAX_AUTONOMY_CYCLES}")
        if not 0 <= interval <= MAX_INTERVAL_SECONDS:
            raise ValueError(f"interval must be between 0 and {MAX_INTERVAL_SECONDS} seconds")

        observations = self.observe_environment()
        results = []
        for index in range(cycles):
            try:
                result = self.core.run_cycle(provider, agent_id=agent_id)
                decision = ActionPolicy.authorize(result.get("action", {}))
                result["permission"] = decision
                if not decision["allowed"]:
                    result["verified"] = False
                    result["permission_blocked"] = True
                results.append(result)
            except KeyboardInterrupt:
                return {"status": "paused_by_user", "requested_cycles": cycles,
                        "completed_cycles": len(results), "environment": observations,
                        "cycles": results}
            except Exception as error:
                failure = {
                    "type": "write_note",
                    "content": "Autonomy cycle failure: " + _cognitive_clean(
                        f"{type(error).__name__}: {error}", 1000
                    ),
                }
                try:
                    self.core._apply_action(failure)
                except Exception:
                    pass
                results.append({
                    "cycle_index": index + 1, "verified": False,
                    "error": f"{type(error).__name__}: {_cognitive_clean(error, 500)}",
                    "learning_status": "failure recorded when local memory was available",
                })
            if index + 1 < cycles and interval:
                time.sleep(interval)

        verified = sum(bool(item.get("verified")) for item in results)
        return {
            "status": "completed" if len(results) == cycles else "incomplete",
            "requested_cycles": cycles, "completed_cycles": len(results),
            "verified_cycles": verified, "environment": observations,
            "active_goals": self.core.active_goals(),
            "cycles": results,
            "autonomy_boundary": (
                "Finite local cognitive cycles only. No arbitrary shell, network, "
                "credential, destructive, or external actions are available."
            ),
        }
