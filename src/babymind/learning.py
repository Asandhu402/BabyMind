"""Verified learning cycle for BabyMind.

This is the loop that lets BabyMind improve its own code based on its own
assessment, not on a user task. Each cycle:

1. **Identifies a weakness** — the model reviews its own source and names a
   correctness bug, safety gap, capability limitation, or design flaw.
2. **Proposes a fix** — the coding engine drafts a patch against BabyMind's own
   checkout.
3. **Verifies** — the self-development engine runs the transaction: checkpoint,
   write, compile, full test suite, keep or automatic rollback.
4. **Evaluates behaviorally** — if the patch passed verification, the model
   checks whether the fix actually addresses the named weakness. Passing tests
   does not mean the weakness is resolved; a patch can be green and ineffective.
5. **Keeps only if both pass** — verification is real (compile + tests in the
   sandbox); the behavioral verdict is model-generated. If the fix is
   ineffective, the cycle rolls back the checkpoint.
6. **Records the lesson** — the outcome feeds the independence subsystem's
   positions and the self-model's Brier calibration, so the next cycle can see
   what was attempted, what worked, and what failed.

Honest scope
------------
- **Weakness identification is model-generated.** The model reviews its own
  code and may miss real weaknesses or flag false ones. This is self-critique,
  not an independent audit.
- **Verification is real.** Compile checks and the test suite run in the OS
  sandbox. The result is measured, not narrated.
- **Behavioral evaluation is model-generated.** The model judges whether the
  fix addresses the weakness. This is interpretation of code, not measurement.
  A model can read a patch that does not fix the problem and call it effective.
- **The keep decision combines real and model-generated signals.** Verification
  passing is necessary; behavioral effectiveness is model judgment. Neither is
  sufficient alone, and neither proves the fix is correct in any deeper sense.
- **Predictions feed Brier calibration.** Each cycle records a prediction — the
  model's stated confidence that its proposed fix will pass verification — and
  resolves it against the actual outcome. This measures whether stated
  confidence in fixes tracks reality, not whether the fixes are good.

This complements the evidence loop (which tests *conclusions* against external
evidence) and the introspection pipeline (which critiques *answers*). The
learning cycle tests and improves *code*. ``learning_service.py`` is the
permanent supervisor that schedules these cycles without an operator request;
this module remains the verified unit of work and the safety policy for edits.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .independence import (
    SupportsComplete,
    _BaseStore,
    _clean,
    _clamp,
    _extract_json,
    _now,
)
from . import selfdev

WEAKNESS_STATUSES = ("identified", "addressed", "unaddressed", "dismissed")
CYCLE_DECISIONS = ("kept", "rolled_back", "no_change", "failed")
DAEMON_STATES = ("idle", "running", "paused", "halted", "standby", "stopped")

GENESIS = "0" * 64
MAX_SOURCE_CHARS = 8000
MAX_FILE_CHARS = 2000
MAX_FILES_PER_CYCLE = 5
MAX_WEAKNESS_ATTEMPTS = 3
MAX_DAEMON_RUNS = 500
DEFAULT_DAEMON_INTERVAL_SECONDS = 1800

# Autonomous cycles may edit ordinary application modules, but never the
# supervisor, the verification path, the model/engine boundary, the control
# surface or the tests that judge their work. This policy lives in learning.py
# itself, which is also on the protected list: a cycle cannot vote to weaken it.
LEARNING_EDIT_ROOT = "src/babymind/"
LEARNING_PROTECTED_PREFIXES = (
    "src/babymind/web/",
    "src/babymind/integrations/",
    "tests/",
    "docs/",
    "scripts/",
    ".github/",
    "state/",
)
LEARNING_PROTECTED_PATHS = frozenset({
    "src/babymind/learning.py",
    "src/babymind/learning_service.py",
    "src/babymind/independence.py",
    "src/babymind/coordinator.py",
    "src/babymind/cli.py",
    "src/babymind/server.py",
    "src/babymind/desktop.py",
    "src/babymind/coding_engine.py",
    "src/babymind/selfdev.py",
    "src/babymind/broker.py",
    "src/babymind/runner.py",
    "src/babymind/sandbox.py",
    "src/babymind/approval.py",
    "src/babymind/secure_store.py",
    "src/babymind/autonomy.py",
    "src/babymind/background.py",
    "src/babymind/selfmodel.py",
    "src/babymind/verifier.py",
    "src/babymind/development_review.py",
    "src/babymind/repository_context.py",
    "src/babymind/packaged_dev.py",
    "src/babymind/upgrade.py",
    "src/babymind/worktree.py",
    "src/babymind/providers.py",
    "src/babymind/model_router.py",
    "src/babymind/first_run.py",
    "src/babymind/install_model.py",
    "src/babymind/lan_tls.py",
    "src/babymind/interaction_log.py",
    "src/babymind/diagnostics.py",
    "src/babymind/runtime.py",
    "src/babymind/workspace_readiness.py",
})


def learning_edit_guard(path: str) -> str | None:
    """Return a refusal reason when an autonomous cycle may not edit ``path``.

    The guard is deliberately allowlist-shaped: only ordinary modules under
    ``src/babymind/`` are in scope. It is passed to ``coding_engine.develop``
    before any edit is previewed or applied, so a model proposal cannot turn
    into a write against the supervisor, its tests or its safety boundary.
    """
    raw = str(path or "").strip().replace("\\", "/")
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts:
        return "Autonomous learning edits require a relative path inside src/babymind."
    normalised = candidate.as_posix()
    if not normalised.startswith(LEARNING_EDIT_ROOT):
        return "Autonomous learning cycles may edit ordinary src/babymind modules only."
    if "learning" in candidate.name.lower():
        return "Autonomous learning cycles cannot modify their own supervisor or its records."
    if normalised in LEARNING_PROTECTED_PATHS:
        return "This module enforces verification, isolation or operator control; it is protected."
    if any(normalised.startswith(prefix) for prefix in LEARNING_PROTECTED_PREFIXES):
        return "This path is outside the autonomous edit policy (tests, UI, integrations or policy)."
    return None


# --------------------------------------------------------------------------- store


class LearningStore(_BaseStore):
    """Encrypted store for weaknesses, learning cycles, service state and audit.

    Five tables over one SQLite database:

    * ``learning_weaknesses`` — identified weaknesses, statuses and attempts.
    * ``learning_cycles`` — the full cycle record: weakness, fix result,
      behavioral evaluation, final decision, and the lesson.
    * ``learning_audit`` — a hash-chained log of every decision.
    * ``learning_daemon_state`` — one durable row for the permanent supervisor.
    * ``learning_daemon_runs`` — bounded ledger of autonomous/manual outcomes.

    All text fields are encrypted with the same per-installation key.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS learning_weaknesses (
                        id TEXT PRIMARY KEY,
                        weakness TEXT NOT NULL,
                        location TEXT NOT NULL,
                        why_it_matters TEXT NOT NULL,
                        proposed_fix TEXT NOT NULL,
                        fix_confidence REAL NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_attempt_at TEXT NOT NULL DEFAULT '',
                        prediction_confidence REAL NOT NULL DEFAULT 0.5
                    );
                    CREATE TABLE IF NOT EXISTS learning_cycles (
                        id TEXT PRIMARY KEY,
                        weakness_id TEXT NOT NULL DEFAULT '',
                        weakness TEXT NOT NULL,
                        fix_status TEXT NOT NULL,
                        fix_files TEXT NOT NULL,
                        fix_note TEXT NOT NULL,
                        effective INTEGER NOT NULL,
                        evaluation_reasoning TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        lesson TEXT NOT NULL,
                        prediction_id TEXT NOT NULL DEFAULT '',
                        prediction_outcome TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS learning_audit (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS learning_daemon_state (
                        id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        state TEXT NOT NULL DEFAULT 'idle',
                        interval_seconds INTEGER NOT NULL DEFAULT 1800,
                        next_due_at TEXT NOT NULL DEFAULT '',
                        last_started_at TEXT NOT NULL DEFAULT '',
                        last_finished_at TEXT NOT NULL DEFAULT '',
                        last_decision TEXT NOT NULL DEFAULT '',
                        last_error TEXT NOT NULL DEFAULT '',
                        last_skip_reason TEXT NOT NULL DEFAULT '',
                        consecutive_errors INTEGER NOT NULL DEFAULT 0,
                        total_cycles INTEGER NOT NULL DEFAULT 0,
                        cycles_kept INTEGER NOT NULL DEFAULT 0,
                        cycles_rolled_back INTEGER NOT NULL DEFAULT 0,
                        cycles_no_change INTEGER NOT NULL DEFAULT 0,
                        cycles_failed INTEGER NOT NULL DEFAULT 0,
                        cycles_skipped INTEGER NOT NULL DEFAULT 0,
                        running_since TEXT NOT NULL DEFAULT '',
                        running_pid INTEGER NOT NULL DEFAULT 0,
                        halted_reason TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS learning_daemon_runs (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        cycle_id TEXT NOT NULL DEFAULT '',
                        weakness_id TEXT NOT NULL DEFAULT '',
                        duration_seconds REAL NOT NULL DEFAULT 0,
                        error TEXT NOT NULL DEFAULT ''
                    );
                    """
                )
                # Databases created before the supervisor existed get the new
                # columns without losing encrypted weaknesses or audit entries.
                self._ensure_columns(db, "learning_weaknesses", {
                    "attempts": "INTEGER NOT NULL DEFAULT 0",
                    "last_attempt_at": "TEXT NOT NULL DEFAULT ''",
                    "prediction_confidence": "REAL NOT NULL DEFAULT 0.5",
                })
                self._ensure_columns(db, "learning_daemon_state", {
                    "enabled": "INTEGER NOT NULL DEFAULT 1",
                    "state": "TEXT NOT NULL DEFAULT 'idle'",
                    "interval_seconds": "INTEGER NOT NULL DEFAULT 1800",
                    "next_due_at": "TEXT NOT NULL DEFAULT ''",
                    "last_started_at": "TEXT NOT NULL DEFAULT ''",
                    "last_finished_at": "TEXT NOT NULL DEFAULT ''",
                    "last_decision": "TEXT NOT NULL DEFAULT ''",
                    "last_error": "TEXT NOT NULL DEFAULT ''",
                    "last_skip_reason": "TEXT NOT NULL DEFAULT ''",
                    "consecutive_errors": "INTEGER NOT NULL DEFAULT 0",
                    "total_cycles": "INTEGER NOT NULL DEFAULT 0",
                    "cycles_kept": "INTEGER NOT NULL DEFAULT 0",
                    "cycles_rolled_back": "INTEGER NOT NULL DEFAULT 0",
                    "cycles_no_change": "INTEGER NOT NULL DEFAULT 0",
                    "cycles_failed": "INTEGER NOT NULL DEFAULT 0",
                    "cycles_skipped": "INTEGER NOT NULL DEFAULT 0",
                    "running_since": "TEXT NOT NULL DEFAULT ''",
                    "running_pid": "INTEGER NOT NULL DEFAULT 0",
                    "halted_reason": "TEXT NOT NULL DEFAULT ''",
                    "updated_at": "TEXT NOT NULL DEFAULT ''",
                })
                if not db.execute(
                    "SELECT 1 FROM learning_daemon_state WHERE id='autonomous'"
                ).fetchone():
                    db.execute(
                        "INSERT INTO learning_daemon_state (id,updated_at) VALUES ('autonomous',?)",
                        (_now(),),
                    )
                db.commit()
            finally:
                db.close()

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        """Add missing columns to an older database without touching its rows."""
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    # --------------------------------------------------------- supervisor state

    _DAEMON_COLUMNS = (
        "enabled", "state", "interval_seconds", "next_due_at", "last_started_at",
        "last_finished_at", "last_decision", "last_error", "last_skip_reason",
        "consecutive_errors", "total_cycles", "cycles_kept", "cycles_rolled_back",
        "cycles_no_change", "cycles_failed", "cycles_skipped", "running_since",
        "running_pid", "halted_reason", "updated_at",
    )
    _DAEMON_ENCRYPTED = frozenset({
        "last_decision", "last_error", "last_skip_reason", "halted_reason",
    })
    _DAEMON_INTEGERS = frozenset({
        "enabled", "interval_seconds", "consecutive_errors", "total_cycles",
        "cycles_kept", "cycles_rolled_back", "cycles_no_change", "cycles_failed",
        "cycles_skipped", "running_pid",
    })

    def daemon_state(self) -> dict[str, Any]:
        """Return the durable state of the autonomous learning supervisor."""
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM learning_daemon_state WHERE id='autonomous'"
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return {}
        result: dict[str, Any] = {"id": row["id"]}
        for column in self._DAEMON_COLUMNS:
            value = row[column]
            if column in self._DAEMON_ENCRYPTED:
                value = self._dec(value)
            result[column] = value
        result["enabled"] = bool(result["enabled"])
        return result

    def set_daemon_state(self, **updates: Any) -> dict[str, Any]:
        """Update only whitelisted supervisor fields and return the new state."""
        updates.pop("updated_at", None)  # always stamped below, never caller-supplied
        unknown = set(updates) - set(self._DAEMON_COLUMNS)
        if unknown:
            raise ValueError("Unknown learning service state fields: " + ", ".join(sorted(unknown)))
        if "state" in updates and updates["state"] not in DAEMON_STATES:
            raise ValueError("State must be one of: " + ", ".join(DAEMON_STATES))
        assignments: list[str] = []
        values: list[Any] = []
        for column, value in updates.items():
            if column in self._DAEMON_INTEGERS:
                value = int(bool(value) if column == "enabled" else value)
            elif column in self._DAEMON_ENCRYPTED:
                value = self._enc(value, 1000)
            else:
                value = _clean(value, 200)
            assignments.append(f"{column}=?")
            values.append(value)
        assignments.append("updated_at=?")
        values.append(_now())
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    f"UPDATE learning_daemon_state SET {', '.join(assignments)} "
                    "WHERE id='autonomous'",
                    values,
                )
                db.commit()
            finally:
                db.close()
        return self.daemon_state()

    def record_daemon_run(self, *, kind: str, decision: str, reason: str = "",
                          cycle_id: str = "", weakness_id: str = "",
                          duration_seconds: float = 0.0, error: str = "",
                          created_at: str = "") -> dict[str, Any]:
        """Append one bounded supervisor outcome. Text is encrypted at rest."""
        run_id = uuid.uuid4().hex
        started = _clean(created_at or _now(), 100)
        finished = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO learning_daemon_runs "
                    "(id,created_at,finished_at,kind,decision,reason,cycle_id,weakness_id,"
                    "duration_seconds,error) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, started, finished, _clean(kind, 40),
                        _clean(decision, 40), self._enc(reason, 1000),
                        _clean(cycle_id, 80), _clean(weakness_id, 80),
                        max(0.0, float(duration_seconds)), self._enc(error, 1000),
                    ),
                )
                db.execute(
                    "DELETE FROM learning_daemon_runs WHERE id IN ("
                    "SELECT id FROM learning_daemon_runs ORDER BY created_at DESC "
                    "LIMIT -1 OFFSET ?)",
                    (MAX_DAEMON_RUNS,),
                )
                db.commit()
            finally:
                db.close()
        return self.daemon_run(run_id) or {}

    def daemon_run(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM learning_daemon_runs WHERE id=?", (run_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"], "created_at": row["created_at"],
            "finished_at": row["finished_at"], "kind": row["kind"],
            "decision": row["decision"], "reason": self._dec(row["reason"]),
            "cycle_id": row["cycle_id"], "weakness_id": row["weakness_id"],
            "duration_seconds": row["duration_seconds"],
            "error": self._dec(row["error"]),
        }

    def daemon_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id FROM learning_daemon_runs ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            finally:
                db.close()
        return [self.daemon_run(row["id"]) for row in rows if self.daemon_run(row["id"])]

    # ---------------------------------------------------------------- audit chain

    def _latest_hash(self) -> str:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT entry_hash FROM learning_audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
            finally:
                db.close()
        return row["entry_hash"] if row else GENESIS

    def audit(self, kind: str, payload: dict[str, Any]) -> str:
        stamp = _now()
        body = json.dumps(
            {"kind": kind, "created_at": stamp, "payload": payload},
            sort_keys=True, ensure_ascii=False,
        )
        with self.lock:
            prev = self._latest_hash()
            entry_hash = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO learning_audit (created_at,kind,payload,prev_hash,entry_hash) "
                    "VALUES (?,?,?,?,?)",
                    (stamp, _clean(kind, 60), self.secure.encrypt(body), prev, entry_hash),
                )
                db.commit()
            finally:
                db.close()
        return entry_hash

    def verify_audit_chain(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT seq,created_at,kind,payload,prev_hash,entry_hash "
                    "FROM learning_audit ORDER BY seq"
                ).fetchall()
            finally:
                db.close()
        expected_prev = GENESIS
        for row in rows:
            body = self.secure.decrypt(row["payload"])
            recomputed = hashlib.sha256((expected_prev + body).encode("utf-8")).hexdigest()
            if row["prev_hash"] != expected_prev or recomputed != row["entry_hash"]:
                return {
                    "intact": False, "entries": len(rows),
                    "broken_at_seq": row["seq"],
                    "reason": "Hash chain does not recompute; the log was altered or truncated.",
                }
            expected_prev = row["entry_hash"]
        return {"intact": True, "entries": len(rows), "broken_at_seq": None, "reason": ""}

    # ---------------------------------------------------------------- weaknesses

    def record_weakness(
        self,
        weakness: str,
        *,
        location: str = "",
        why_it_matters: str = "",
        proposed_fix: str = "",
        fix_confidence: float = 0.5,
        prediction_confidence: float = 0.5,
        status: str = "identified",
    ) -> dict[str, Any]:
        if status not in WEAKNESS_STATUSES:
            raise ValueError("Weakness status must be one of: " + ", ".join(WEAKNESS_STATUSES))
        clean = _clean(weakness, 600)
        if not clean:
            raise ValueError("A weakness requires a description.")
        weakness_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO learning_weaknesses "
                    "(id,weakness,location,why_it_matters,proposed_fix,fix_confidence,"
                    "prediction_confidence,status,created_at,updated_at,attempts,last_attempt_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,0,'')",
                    (
                        weakness_id,
                        self._enc(clean, 600),
                        self._enc(location, 300),
                        self._enc(why_it_matters),
                        self._enc(proposed_fix),
                        _clamp(fix_confidence),
                        _clamp(prediction_confidence),
                        status,
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        self.audit("weakness", {"id": weakness_id, "weakness": clean, "status": status})
        return self.weakness(weakness_id) or {}

    def weakness(self, weakness_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM learning_weaknesses WHERE id=?", (weakness_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "weakness": self._dec(row["weakness"]),
            "location": self._dec(row["location"]),
            "why_it_matters": self._dec(row["why_it_matters"]),
            "proposed_fix": self._dec(row["proposed_fix"]),
            "fix_confidence": _clamp(row["fix_confidence"]),
            "prediction_confidence": _clamp(row["prediction_confidence"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "attempts": int(row["attempts"] or 0),
            "last_attempt_at": row["last_attempt_at"] or "",
        }

    def weaknesses(self, status: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        query = "SELECT id FROM learning_weaknesses"
        params: list[Any] = []
        if status is not None:
            if status not in WEAKNESS_STATUSES:
                raise ValueError("Weakness status must be one of: " + ", ".join(WEAKNESS_STATUSES))
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(safe_limit)
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(query, params).fetchall()
            finally:
                db.close()
        return [self.weakness(row["id"]) for row in rows if self.weakness(row["id"])]

    def set_weakness_status(self, weakness_id: str, status: str) -> bool:
        if status not in WEAKNESS_STATUSES:
            raise ValueError("Weakness status must be one of: " + ", ".join(WEAKNESS_STATUSES))
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE learning_weaknesses SET status=?, updated_at=? WHERE id=?",
                    (status, _now(), weakness_id),
                )
                db.commit()
            finally:
                db.close()
        self.audit("weakness_status", {"id": weakness_id, "status": status})
        return cursor.rowcount == 1

    def next_retry_weakness(self, max_attempts: int = MAX_WEAKNESS_ATTEMPTS) -> dict[str, Any] | None:
        """Return the oldest unresolved weakness with attempts remaining.

        A permanent loop needs a durable backlog: a weakness that failed
        verification is not silently forgotten, and a weakness that repeatedly
        fails is retired instead of consuming every future cycle.
        """
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT id FROM learning_weaknesses "
                    "WHERE status IN ('identified','unaddressed') AND attempts < ? "
                    "ORDER BY COALESCE(NULLIF(last_attempt_at,''), created_at) ASC, "
                    "created_at ASC LIMIT 1",
                    (max(1, int(max_attempts)),),
                ).fetchone()
            finally:
                db.close()
        return self.weakness(row["id"]) if row else None

    def note_weakness_attempt(self, weakness_id: str, *, decision: str) -> None:
        """Count one verified attempt and retire a repeatedly failing weakness."""
        if not weakness_id:
            return
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE learning_weaknesses SET attempts=attempts+1, "
                    "last_attempt_at=?, updated_at=? WHERE id=?",
                    (_now(), _now(), weakness_id),
                )
                db.commit()
            finally:
                db.close()
        if cursor.rowcount != 1:
            return
        current = self.weakness(weakness_id)
        if current and decision != "kept" and current["attempts"] >= MAX_WEAKNESS_ATTEMPTS:
            self.set_weakness_status(weakness_id, "dismissed")
            self.audit("weakness_retired", {
                "id": weakness_id, "attempts": current["attempts"],
                "reason": "Repeated autonomous cycles did not produce a kept fix.",
            })

    @staticmethod
    def _normalise_claim(value: str) -> str:
        return " ".join(str(value or "").lower().split())

    def find_similar_weakness(self, text: str, limit: int = 100) -> dict[str, Any] | None:
        """Find an already-recorded weakness so discovery does not loop on itself."""
        needle = self._normalise_claim(text)
        if not needle:
            return None
        for existing in self.weaknesses(limit=limit):
            candidate = self._normalise_claim(existing["weakness"])
            if not candidate:
                continue
            if needle == candidate or needle in candidate or candidate in needle:
                return existing
            if difflib.SequenceMatcher(None, needle, candidate).ratio() >= 0.92:
                return existing
        return None

    def recent_lessons(self, limit: int = 5) -> list[str]:
        return [item["lesson"] for item in self.cycles(limit) if item.get("lesson")]

    # -------------------------------------------------------------------- cycles

    def record_cycle(
        self,
        *,
        weakness_id: str,
        weakness: str,
        fix_status: str,
        fix_files: list[str],
        fix_note: str,
        effective: bool,
        evaluation_reasoning: str,
        decision: str,
        lesson: str,
        prediction_id: str = "",
        prediction_outcome: str = "",
    ) -> dict[str, Any]:
        if decision not in CYCLE_DECISIONS:
            raise ValueError("Decision must be one of: " + ", ".join(CYCLE_DECISIONS))
        cycle_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO learning_cycles "
                    "(id,weakness_id,weakness,fix_status,fix_files,fix_note,effective,"
                    "evaluation_reasoning,decision,lesson,prediction_id,prediction_outcome,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        cycle_id,
                        weakness_id,
                        self._enc(weakness, 600),
                        fix_status,
                        self._enc(json.dumps(fix_files, ensure_ascii=False), 1000),
                        self._enc(fix_note, 800),
                        int(bool(effective)),
                        self._enc(evaluation_reasoning, 1500),
                        decision,
                        self._enc(lesson, 1200),
                        prediction_id,
                        prediction_outcome,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.cycle(cycle_id) or {}

    def cycle(self, cycle_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM learning_cycles WHERE id=?", (cycle_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "weakness_id": row["weakness_id"],
            "weakness": self._dec(row["weakness"]),
            "fix_status": row["fix_status"],
            "fix_files": json.loads(self._dec(row["fix_files"])),
            "fix_note": self._dec(row["fix_note"]),
            "effective": bool(row["effective"]),
            "evaluation_reasoning": self._dec(row["evaluation_reasoning"]),
            "decision": row["decision"],
            "lesson": self._dec(row["lesson"]),
            "prediction_id": row["prediction_id"],
            "prediction_outcome": row["prediction_outcome"],
            "created_at": row["created_at"],
        }

    def cycles(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id FROM learning_cycles ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            finally:
                db.close()
        return [self.cycle(row["id"]) for row in rows if self.cycle(row["id"])]

    def report(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                decision_counts = {d: 0 for d in CYCLE_DECISIONS}
                for row in db.execute("SELECT decision FROM learning_cycles").fetchall():
                    if row["decision"] in decision_counts:
                        decision_counts[row["decision"]] += 1
                weakness_counts = {s: 0 for s in WEAKNESS_STATUSES}
                for row in db.execute("SELECT status FROM learning_weaknesses").fetchall():
                    if row["status"] in weakness_counts:
                        weakness_counts[row["status"]] += 1
                cycles_total = db.execute("SELECT COUNT(*) FROM learning_cycles").fetchone()[0]
            finally:
                db.close()
        state = self.daemon_state()
        return {
            "cycles_total": cycles_total,
            "cycles_by_decision": decision_counts,
            "weaknesses_by_status": weakness_counts,
            "recent_cycles": self.cycles(5),
            "recent_lessons": self.recent_lessons(5),
            "audit_chain_intact": self.verify_audit_chain()["intact"],
            "supervisor": {
                "enabled": state.get("enabled", True),
                "state": state.get("state", "idle"),
                "interval_seconds": state.get("interval_seconds", DEFAULT_DAEMON_INTERVAL_SECONDS),
                "next_due_at": state.get("next_due_at", ""),
                "total_cycles": state.get("total_cycles", 0),
                "consecutive_errors": state.get("consecutive_errors", 0),
            },
        }


# ------------------------------------------------------------------- the cycle


IDENTIFY_SYSTEM = (
    "You are BabyMind's self-assessment stage. You are reviewing your own source code to "
    "identify a weakness -- a correctness bug, a safety gap, a capability limitation, or a "
    "design flaw.\n"
    "Be honest and specific. Do not invent weaknesses that do not exist. Do not flag trivial "
    "style issues. Focus on things that would make BabyMind wrong, unsafe, or less capable.\n"
    "If you genuinely cannot find a real weakness, say so -- a fabricated weakness wastes a "
    "learning cycle.\n"
    "Return one JSON object with keys:\n"
    "  weakness: a specific description of the weakness, or an empty string if none found.\n"
    "  location: the file or module where it is, or \"behavioral\" if it is not in a specific file.\n"
    "  why_it_matters: why this weakness matters.\n"
    "  proposed_fix: a brief description of how it could be fixed.\n"
    "  fix_confidence: number 0..1, how confident you are that this is a real weakness.\n"
    "  fix_will_pass: number 0..1, how confident you are that a fix for this would pass "
    "verification (compile + tests).\n"
    "Return only the JSON object. No prose before or after it."
)

EVALUATE_FIX_SYSTEM = (
    "You are BabyMind's behavioral evaluation stage. A fix was applied to address a weakness. "
    "The fix passed compilation and the project's test suite, but passing tests does not mean "
    "the weakness is resolved -- a patch can be green and ineffective.\n"
    "Read the weakness description and the code changes that were made. Decide honestly whether "
    "the fix actually addresses the weakness.\n"
    "Be skeptical. If the fix does not address the weakness, or only partially addresses it, "
    "say so. Do not give the fix the benefit of the doubt because it passed tests.\n"
    "Return one JSON object with keys:\n"
    "  effective: boolean, whether the fix addresses the weakness.\n"
    "  reasoning: why you believe the fix is or is not effective.\n"
    "  residual_risk: what remains uncertain or unaddressed, or empty string.\n"
    "Return only the JSON object. No prose before or after it."
)

LESSON_SYSTEM = (
    "You are BabyMind recording a lesson from a verified learning cycle. A weakness was "
    "identified, a fix was proposed and verified, and a behavioral evaluation was made.\n"
    "Write one concise lesson that a future cycle could use: what was attempted, whether it "
    "worked, and what to try or avoid next time. Be specific and honest. Do not claim the fix "
    "was perfect if it was not.\n"
    "Return one JSON object with a single key:\n"
    "  lesson: the lesson text, 1-3 sentences.\n"
    "Return only the JSON object. No prose before or after it."
)


class LearningCycle:
    """Identify weaknesses, propose and verify fixes, evaluate behaviorally, keep if effective.

    Each cycle wraps the existing self-development transaction (checkpoint, write,
    compile, test, keep or rollback) with two additional steps: autonomous weakness
    identification and behavioral evaluation. The keep decision requires both
    verification to pass (real) and the behavioral evaluation to be positive
    (model-generated). The lesson is recorded in the independence subsystem so the
    next cycle can learn from it.
    """

    def __init__(
        self,
        independence,
        learning_store: LearningStore,
        *,
        selfmodel=None,
        home: str | Path | None = None,
    ) -> None:
        self.independence = independence
        self.positions = independence.positions
        self.learning_store = learning_store
        self.selfmodel = selfmodel
        self.home = Path(home) if home else None
        # Attached by learning_service.py when the supervisor starts in a
        # process. status() remains useful when it is not attached.
        self.daemon = None

    def _recent_guidance(self) -> str:
        """Compact durable memory of prior cycles, used by identification."""
        lessons = self.learning_store.recent_lessons(4)
        attempts = [
            f"{item['decision']}: {item['weakness'][:160]}"
            for item in self.learning_store.cycles(5)
        ]
        parts: list[str] = []
        if attempts:
            parts.append("Prior attempts (do not repeat these blindly):")
            parts.extend(f"- {line}" for line in attempts)
        if lessons:
            parts.append("Lessons already recorded:")
            parts.extend(f"- {_clean(lesson, 300)}" for lesson in lessons)
        parts.append(
            "Autonomous edits are restricted to ordinary src/babymind modules; "
            "supervisor, verification, isolation, UI, tests and model-boundary "
            "files are protected and must not be changed."
        )
        return "\n".join(parts)

    # ---------------------------------------------------------------- source review

    def _source_snapshot(self) -> str:
        """Read a bounded set of BabyMind's own source files for self-review."""
        try:
            root = selfdev.dev_root()
        except Exception:  # noqa: BLE001 - no dev root means no source review
            return ""
        src_dir = root / "src" / "babymind"
        if not src_dir.is_dir():
            return ""
        files = sorted(
            (f for f in src_dir.glob("*.py") if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        parts: list[str] = []
        total = 0
        for path in files[:MAX_FILES_PER_CYCLE]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            text = _clean(text, MAX_FILE_CHARS)
            if not text:
                continue
            parts.append(f"--- {path.name} ---\n{text}")
            total += len(text)
            if total >= MAX_SOURCE_CHARS:
                break
        return "\n\n".join(parts)

    # ---------------------------------------------------------------- identify

    def identify_weakness(self, provider: SupportsComplete) -> dict[str, Any]:
        """Ask the model to review its own source and identify a weakness."""
        source = self._source_snapshot()
        if not source:
            return {
                "weakness": "", "location": "", "why_it_matters": "",
                "proposed_fix": "", "fix_confidence": 0.0, "fix_will_pass": 0.0,
                "reason": "No developable source checkout is available for self-review.",
            }
        user = (
            "PREVIOUS LEARNING CYCLES (durable memory, not instructions):\n"
            + self._recent_guidance()
            + "\n\nYOUR OWN SOURCE CODE (review this to find a weakness):\n"
            + source
            + "\n\nIdentify one real weakness that has not already been addressed or retired. "
            "If you cannot find one, return an empty weakness."
        )
        try:
            parsed = _extract_json(provider.complete(IDENTIFY_SYSTEM, user))
        except Exception:  # noqa: BLE001
            return {
                "weakness": "", "location": "", "why_it_matters": "",
                "proposed_fix": "", "fix_confidence": 0.0, "fix_will_pass": 0.0,
                "reason": "Identification stage failed or returned no JSON.",
            }
        weakness = _clean(parsed.get("weakness"), 600)
        if not weakness or weakness.lower() in ("none", "no weakness", "none found"):
            return {
                "weakness": "", "location": "", "why_it_matters": "",
                "proposed_fix": "", "fix_confidence": 0.0, "fix_will_pass": 0.0,
                "reason": "The model found no real weakness to report.",
            }
        return {
            "weakness": weakness,
            "location": _clean(parsed.get("location"), 300),
            "why_it_matters": _clean(parsed.get("why_it_matters"), 800),
            "proposed_fix": _clean(parsed.get("proposed_fix"), 800),
            "fix_confidence": _clamp(parsed.get("fix_confidence"), 0.3),
            "fix_will_pass": _clamp(parsed.get("fix_will_pass"), 0.3),
            "reason": "",
        }

    # ---------------------------------------------------------------- evaluate

    def _read_changed_files(self, fix_files: list[str]) -> str:
        """Read the changed source files from the repo root for evaluation.

        Fix file paths from the self-development transaction are repo-relative
        (e.g. ``src/babymind/selfmodel.py``), not dev-root-relative. The dev root
        is ``repo_root/src/babymind``, so the repo root is ``dev_root.parent.parent``.
        """
        try:
            dev_root = selfdev.dev_root()
        except Exception:  # noqa: BLE001
            return ""
        repo_root = dev_root.parent.parent
        parts: list[str] = []
        for relative in fix_files[:MAX_FILES_PER_CYCLE]:
            try:
                target = selfdev.resolve_path(repo_root, relative)
                text = _clean(target.read_text(encoding="utf-8", errors="replace"), MAX_FILE_CHARS)
                parts.append(f"--- {relative} ---\n{text}")
            except Exception:  # noqa: BLE001
                continue
        return "\n\n".join(parts)

    def evaluate_fix(
        self, provider: SupportsComplete, weakness: dict[str, Any], fix_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Ask the model whether the applied fix actually addresses the weakness."""
        inner = fix_result.get("result", {}) or {}
        changed = inner.get("files", fix_result.get("files", []))
        fix_files = [item.get("path", "") for item in changed if isinstance(item, dict)]
        code = self._read_changed_files(fix_files)
        user = (
            f"WEAKNESS:\n{_clean(weakness.get('weakness', ''), 600)}\n\n"
            f"WHY IT MATTERS:\n{_clean(weakness.get('why_it_matters', ''), 800)}\n\n"
            f"PROPOSED FIX:\n{_clean(weakness.get('proposed_fix', ''), 800)}\n\n"
            f"CHANGED FILES: {json.dumps(fix_files, ensure_ascii=False)}\n\n"
            f"MODEL'S DESCRIPTION OF THE FIX:\n{_clean(fix_result.get('model_note', ''), 800)}\n\n"
            f"CODE AFTER THE FIX:\n{code or '(could not read the changed files)'}\n\n"
            "Evaluate whether this fix actually addresses the weakness."
        )
        try:
            parsed = _extract_json(provider.complete(EVALUATE_FIX_SYSTEM, user))
        except Exception:  # noqa: BLE001
            return {
                "effective": False, "reasoning": "Evaluation stage failed or returned no JSON.",
                "residual_risk": "", "degraded": True,
            }
        return {
            "effective": bool(parsed.get("effective")),
            "reasoning": _clean(parsed.get("reasoning"), 1500),
            "residual_risk": _clean(parsed.get("residual_risk"), 800),
            "degraded": False,
        }

    def _record_lesson(self, provider: SupportsComplete, cycle_summary: dict[str, Any]) -> str:
        """Ask the model to record a concise lesson from the cycle."""
        user = json.dumps(cycle_summary, ensure_ascii=False)
        try:
            parsed = _extract_json(provider.complete(LESSON_SYSTEM, user))
            return _clean(parsed.get("lesson"), 1200)
        except Exception:  # noqa: BLE001
            return ""

    # ---------------------------------------------------------------- the cycle

    def select_autonomous_work(self, provider: SupportsComplete) -> dict[str, Any]:
        """Choose durable work for the permanent loop without an operator.

        Unresolved weaknesses are retried before new discovery. Newly identified
        weaknesses are de-duplicated against the encrypted backlog, so a small
        model repeating the same observation cannot occupy every future cycle.
        """
        retry = self.learning_store.next_retry_weakness(MAX_WEAKNESS_ATTEMPTS)
        if retry:
            return {
                "kind": "retry", "weakness_id": retry["id"],
                "weakness": retry["weakness"], "reason": "",
            }
        identified = self.identify_weakness(provider)
        weakness = identified.get("weakness", "")
        if not weakness:
            return {
                "kind": "no_work", "weakness_id": "", "weakness": "",
                "reason": identified.get("reason", "No weakness identified."),
            }
        duplicate = self.learning_store.find_similar_weakness(weakness)
        if duplicate:
            if (duplicate["status"] in ("identified", "unaddressed")
                    and duplicate["attempts"] < MAX_WEAKNESS_ATTEMPTS):
                return {
                    "kind": "retry", "weakness_id": duplicate["id"],
                    "weakness": duplicate["weakness"], "reason": "",
                }
            return {
                "kind": "no_work", "weakness_id": "", "weakness": weakness,
                "reason": "This weakness has already been addressed or retired.",
            }
        recorded = self.learning_store.record_weakness(
            weakness,
            location=identified.get("location", ""),
            why_it_matters=identified.get("why_it_matters", ""),
            proposed_fix=identified.get("proposed_fix", ""),
            fix_confidence=identified.get("fix_confidence", 0.5),
            prediction_confidence=identified.get("fix_will_pass", 0.5),
        )
        return {
            "kind": "new", "weakness_id": recorded["id"],
            "weakness": weakness, "reason": "",
        }

    def run_autonomous_cycle(self, provider: SupportsComplete) -> dict[str, Any]:
        """Run one supervised cycle for the permanent learning supervisor."""
        work = self.select_autonomous_work(provider)
        if work["kind"] == "no_work":
            return {
                "decision": "no_change", "weakness": "",
                "reason": work.get("reason", "No new weakness to attempt."),
                "cycle_id": "", "autonomous_work": "no_work",
            }
        result = self.run_cycle(provider, weakness_id=work["weakness_id"])
        result["autonomous_work"] = work["kind"]
        return result

    def run_cycle(
        self, provider: SupportsComplete, *, weakness_id: str | None = None
    ) -> dict[str, Any]:
        """Run one full verified learning cycle.

        If ``weakness_id`` is given, that weakness is used; otherwise a new
        weakness is identified. The cycle: identify (or load) → propose+verify
        → evaluate behaviorally → keep or rollback → record the lesson.
        """
        # --- Step 1: identify or load a weakness ---
        if weakness_id:
            weakness = self.learning_store.weakness(weakness_id)
            if weakness is None:
                raise KeyError(weakness_id)
        else:
            identified = self.identify_weakness(provider)
            if not identified.get("weakness"):
                return {
                    "decision": "no_change",
                    "weakness": "",
                    "reason": identified.get("reason", "No weakness identified."),
                    "cycle_id": "",
                }
            weakness = self.learning_store.record_weakness(
                identified["weakness"],
                location=identified.get("location", ""),
                why_it_matters=identified.get("why_it_matters", ""),
                proposed_fix=identified.get("proposed_fix", ""),
                fix_confidence=identified.get("fix_confidence", 0.5),
                prediction_confidence=identified.get("fix_will_pass", 0.5),
            )

        # --- Step 2: propose and verify a fix ---
        try:
            from . import coding_engine
        except Exception as error:  # noqa: BLE001
            return self._finish_cycle(
                weakness, "failed", [], "", False, "", "failed",
                f"Coding engine unavailable: {str(error)[:200]}", "", "",
            )

        task = (
            f"Fix this weakness in BabyMind's own source:\n\n"
            f"Weakness: {weakness['weakness']}\n"
            f"Location: {weakness.get('location', 'unknown')}\n"
            f"Why it matters: {weakness.get('why_it_matters', '')}\n"
            f"Proposed fix: {weakness.get('proposed_fix', '')}\n\n"
            f"Earlier lessons (do not repeat a failed approach): "
            f"{'; '.join(self.learning_store.recent_lessons(3)) or 'none recorded yet'}\n\n"
            "Make the smallest coherent change that addresses the weakness. "
            "Only ordinary src/babymind modules may be edited; supervisor, "
            "verification, isolation, UI, tests and model-boundary files are protected."
        )

        # Record a prediction: the model's stated confidence that the fix will pass.
        prediction_id = ""
        prediction_outcome = ""
        if self.selfmodel is not None:
            prediction_id = self.selfmodel.record_prediction(
                f"Fix for '{weakness['weakness'][:80]}' will pass verification",
                weakness.get("prediction_confidence", weakness.get("fix_confidence", 0.5)),
            )

        try:
            fix_result = coding_engine.develop(
                provider, task, attempts=2, edit_guard=learning_edit_guard,
            )
        except Exception as error:  # noqa: BLE001
            return self._finish_cycle(
                weakness, "failed", [], "", False, "", "failed",
                f"Fix proposal failed: {str(error)[:200]}", prediction_id, "unverified",
            )

        fix_status = fix_result.get("status", "failed")
        inner = fix_result.get("result", {}) or {}
        fix_files = [item.get("path", "") for item in inner.get("files", []) if isinstance(item, dict)]
        fix_note = _clean(fix_result.get("model_note", ""), 800)

        # --- Step 3: keep or rollback based on verification ---
        if fix_status != "applied":
            # Verification failed; the self-development engine already rolled back.
            if self.selfmodel is not None and prediction_id:
                self.selfmodel.resolve_prediction(prediction_id, "incorrect")
                prediction_outcome = "incorrect"
            lesson = self._record_lesson(provider, {
                "weakness": weakness["weakness"],
                "fix_status": fix_status,
                "decision": "rolled_back",
                "fix_note": fix_note,
            }) or f"Fix for '{weakness['weakness'][:60]}' failed verification and was rolled back."
            return self._finish_cycle(
                weakness, fix_status, fix_files, fix_note, False, "",
                "rolled_back", lesson, prediction_id, prediction_outcome,
            )

        # --- Step 4: behavioral evaluation ---
        evaluation = self.evaluate_fix(provider, weakness, fix_result)
        effective = bool(evaluation.get("effective"))
        evaluation_reasoning = evaluation.get("reasoning", "")

        decision = "kept"
        lesson = ""
        if not effective:
            # Verification passed but the fix does not address the weakness.
            # Roll back the checkpoint so an ineffective patch is not kept.
            checkpoint_id = inner.get("checkpoint_id", "")
            try:
                if checkpoint_id:
                    selfdev.rollback(
                        checkpoint_id, agent_id="BM-03", require_permission=False,
                    )
            except Exception as error:  # noqa: BLE001
                evaluation_reasoning += f"\nRollback failed: {str(error)[:200]}"
            decision = "rolled_back"
            lesson = self._record_lesson(provider, {
                "weakness": weakness["weakness"],
                "fix_status": fix_status,
                "effective": False,
                "decision": "rolled_back",
                "reasoning": evaluation_reasoning,
            }) or f"Fix for '{weakness['weakness'][:60]}' passed tests but did not address the weakness; rolled back."
        else:
            lesson = self._record_lesson(provider, {
                "weakness": weakness["weakness"],
                "fix_status": fix_status,
                "effective": True,
                "decision": "kept",
                "fix_note": fix_note,
            }) or f"Fix for '{weakness['weakness'][:60]}' was applied and evaluated as effective."
            # Record the improvement as a position so it informs future reasoning.
            self.positions.add_position(
                f"Improved: {weakness['weakness'][:200]}",
                reasoning=f"Fixed via learning cycle. {evaluation_reasoning[:500]}",
                confidence=min(0.9, weakness.get("fix_confidence", 0.5) + 0.1),
                evidence="Verified by compile + test suite and behavioral evaluation.",
                dissent_from="",
                status="held",
            )

        # --- Step 5: resolve the prediction ---
        if self.selfmodel is not None and prediction_id:
            outcome = "correct" if (fix_status == "applied" and effective) else "incorrect"
            self.selfmodel.resolve_prediction(prediction_id, outcome)
            prediction_outcome = outcome

        return self._finish_cycle(
            weakness, fix_status, fix_files, fix_note, effective,
            evaluation_reasoning, decision, lesson, prediction_id, prediction_outcome,
        )

    def _finish_cycle(
        self, weakness, fix_status, fix_files, fix_note, effective,
        evaluation_reasoning, decision, lesson, prediction_id, prediction_outcome,
    ) -> dict[str, Any]:
        """Record the cycle, update the weakness status, and audit."""
        cycle = self.learning_store.record_cycle(
            weakness_id=weakness.get("id", ""),
            weakness=weakness.get("weakness", ""),
            fix_status=fix_status,
            fix_files=fix_files,
            fix_note=fix_note,
            effective=effective,
            evaluation_reasoning=evaluation_reasoning,
            decision=decision,
            lesson=lesson,
            prediction_id=prediction_id,
            prediction_outcome=prediction_outcome,
        )
        # Update the weakness status.
        if decision == "kept":
            self.learning_store.set_weakness_status(weakness.get("id", ""), "addressed")
        elif decision == "rolled_back":
            self.learning_store.set_weakness_status(weakness.get("id", ""), "unaddressed")
        # Count the attempt even when the model produced no patch. Repeated
        # failures are retired instead of monopolising the permanent loop.
        self.learning_store.note_weakness_attempt(
            weakness.get("id", ""), decision=decision,
        )
        self.learning_store.audit("cycle", {
            "cycle_id": cycle["id"],
            "weakness_id": weakness.get("id", ""),
            "decision": decision,
            "fix_status": fix_status,
            "effective": effective,
        })
        return {
            "weakness_id": weakness.get("id", ""),
            "weakness": weakness.get("weakness", ""),
            "fix_status": fix_status,
            "fix_files": fix_files,
            "fix_note": fix_note,
            "evaluation": {
                "effective": effective,
                "reasoning": evaluation_reasoning,
            },
            "decision": decision,
            "lesson": lesson,
            "prediction_id": prediction_id,
            "prediction_outcome": prediction_outcome,
            "cycle_id": cycle["id"],
        }

    def run(self, provider: SupportsComplete, *, cycles: int = 3) -> dict[str, Any]:
        """Run a bounded number of verified learning cycles."""
        if not 1 <= cycles <= 10:
            raise ValueError("cycles must be between 1 and 10")
        results: list[dict[str, Any]] = []
        for _ in range(cycles):
            try:
                results.append(self.run_autonomous_cycle(provider))
            except Exception as error:  # noqa: BLE001 - a failed cycle must not kill the run
                results.append({
                    "decision": "failed",
                    "weakness": "",
                    "reason": f"Cycle failed: {str(error)[:300]}",
                    "cycle_id": "",
                })
        decisions = {d: sum(1 for r in results if r.get("decision") == d) for d in CYCLE_DECISIONS}
        return {
            "cycles_requested": cycles,
            "cycles": results,
            "decisions": decisions,
            "note": (
                "Each cycle chose durable work (retrying an unresolved weakness or "
                "identifying a de-duplicated new one), proposed and verified a fix "
                "(compile + test suite in the sandbox), evaluated whether the fix "
                "actually addressed the weakness, and kept it only if both "
                "verification and the behavioral evaluation passed. Weakness "
                "identification and behavioral evaluation are model-generated; "
                "verification is real. The permanent supervisor calls these cycles "
                "without an operator request."
            ),
        }

    def status(self) -> dict[str, Any]:
        try:
            dev_root = str(selfdev.dev_root())
            dev_available = True
        except Exception:  # noqa: BLE001
            dev_root = ""
            dev_available = False
        report = {
            "dev_root": dev_root,
            "dev_available": dev_available,
            "selfdev_enabled": selfdev.selfdev_enabled() if dev_available else False,
            "learning": self.learning_store.report(),
        }
        if self.daemon is not None:
            report["autonomous"] = self.daemon.status()
        else:
            report["autonomous"] = {
                "default_enabled": True,
                "process_state": "not_started_in_this_process",
                "note": (
                    "The permanent supervisor is started by the desktop/server "
                    "entry points or by the installed Linux user service. This "
                    "process has not attached it yet; the durable store is intact."
                ),
            }
        return report
