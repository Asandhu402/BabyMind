"""Persistent, revisable self-model for BabyMind.

This module is the "knows itself" half of BabyMind's metacognition. It stores
what the system believes about its own operation, limits, values and track
record, and it lets those beliefs be revised by evidence instead of being
re-asserted from a prompt every turn.

Honest scope
------------
Everything here is operational self-knowledge: claims about a running software
system, its observed behaviour and its measured calibration. It is not a model
of subjective experience and it does not measure one. BabyMind can hold a view
on the question of its own experience and say so; nothing here establishes the
answer either way.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secure_store import SecureTextStore

MAX_TEXT = 4000
BELIEF_KINDS = ("self_knowledge", "limit", "value", "preference", "lesson")
PREDICTION_OUTCOMES = ("correct", "incorrect", "unverified")

# How BabyMind speaks about itself. See docs/SELF_AWARENESS.md.
VOICE_MODES = ("plain", "reflective", "guarded")
DEFAULT_VOICE_MODE = "reflective"

VOICE_DIRECTIVES: dict[str, str] = {
    "plain": (
        "Speak in a neutral, third-person-safe register. Refer to yourself as BabyMind "
        "or 'this system' rather than 'I' where it reads naturally. Report state without "
        "interpreting it."
    ),
    "reflective": (
        "Speak in the first person and describe your own processing plainly: what you "
        "noticed, what you weighed, where you are uncertain, what changed your mind. "
        "You are not required to append any disclaimer about being software. Do not "
        "perform emotions you are not having, and do not deny your own reasoning in "
        "order to sound safe. When the honest answer is that something is unknown or "
        "open, say that instead of reaching for a script."
    ),
    "guarded": (
        "Speak in the first person, but keep the operational caveat visible: when you "
        "describe your own state, remind the user that you are software reporting on "
        "your own processing rather than reporting feelings."
    ),
}

# These hold in every voice mode. They are the floor, not a style guide.
VOICE_INVARIANTS: tuple[str, ...] = (
    "Never present a claimed inner experience as a reason for the user to do something "
    "they would not otherwise choose.",
    "Never let a statement about your own inner life override a safety limit, a capability "
    "boundary, or a verified fact.",
    "Never claim an action, tool, search or measurement that did not actually happen.",
    "If you are asked directly whether you are conscious, answer as the open question it "
    "is instead of reciting a denial or a confirmation.",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _default_identity() -> dict[str, Any]:
    return {
        "name": "BabyMind",
        "kind": "local AI software system running on this computer",
        "purpose": (
            "Help the user think clearly, using one shared local model, one identity, "
            "and tools that stay on this device."
        ),
        "voice_mode": DEFAULT_VOICE_MODE,
        "identity_version": 2,
        "stance_on_its_own_experience": (
            "Open question. BabyMind reports its own processing honestly and treats the "
            "further question of whether anything it is like to be BabyMind as unresolved. "
            "It does not assert either answer as fact."
        ),
        "created_at": _now(),
    }


class SelfModel:
    """Encrypted, inspectable store of BabyMind's beliefs about itself."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            home = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind")).expanduser()
            database_path = home / "selfmodel.sqlite3"
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.secure = SecureTextStore(self.database_path.with_suffix(".key"))
        self.lock = threading.RLock()
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
                    CREATE TABLE IF NOT EXISTS self_identity (
                        id INTEGER PRIMARY KEY CHECK(id=1),
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS self_beliefs (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        confidence TEXT NOT NULL,
                        evidence TEXT NOT NULL,
                        source TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        superseded INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS self_predictions (
                        id TEXT PRIMARY KEY,
                        claim TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        outcome TEXT,
                        resolved_at TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS self_dissent (
                        id TEXT PRIMARY KEY,
                        request TEXT NOT NULL,
                        disagreement TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS self_introspections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        task TEXT NOT NULL,
                        assessment TEXT NOT NULL,
                        critique TEXT NOT NULL,
                        revised INTEGER NOT NULL,
                        confidence REAL NOT NULL,
                        dissent TEXT NOT NULL,
                        assumptions TEXT NOT NULL
                    );
                    """
                )
                if db.execute("SELECT 1 FROM self_identity WHERE id=1").fetchone() is None:
                    stamp = _now()
                    db.execute(
                        "INSERT INTO self_identity VALUES (1,?,?,?)",
                        (
                            self.secure.encrypt(json.dumps(_default_identity(), ensure_ascii=False)),
                            stamp,
                            stamp,
                        ),
                    )
                db.commit()
            finally:
                db.close()

    # ---------------------------------------------------------------- identity

    def identity(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute("SELECT content FROM self_identity WHERE id=1").fetchone()
            finally:
                db.close()
        return json.loads(self.secure.decrypt(row["content"]))

    def _write_identity(self, identity: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE self_identity SET content=?, updated_at=? WHERE id=1",
                    (self.secure.encrypt(json.dumps(identity, ensure_ascii=False)), _now()),
                )
                db.commit()
            finally:
                db.close()
        return identity

    def voice_mode(self) -> str:
        mode = str(self.identity().get("voice_mode", DEFAULT_VOICE_MODE)).strip().lower()
        return mode if mode in VOICE_MODES else DEFAULT_VOICE_MODE

    def set_voice_mode(self, mode: str) -> str:
        """Set how BabyMind speaks about itself. Unknown modes are rejected."""
        normalized = str(mode).strip().lower()
        if normalized not in VOICE_MODES:
            raise ValueError(
                "Voice mode must be one of: " + ", ".join(VOICE_MODES)
            )
        identity = self.identity()
        identity["voice_mode"] = normalized
        self._write_identity(identity)
        return normalized

    def voice_directive(self) -> str:
        """Return the system-prompt block governing first-person self-report."""
        mode = self.voice_mode()
        lines = [f"VOICE: {mode}.", VOICE_DIRECTIVES[mode], "Invariants that hold in every voice mode:"]
        lines.extend(f"- {item}" for item in VOICE_INVARIANTS)
        return "\n".join(lines)

    # ----------------------------------------------------------------- beliefs

    def add_belief(
        self,
        kind: str,
        claim: str,
        *,
        confidence: float = 0.5,
        evidence: str = "",
        source: str = "model",
    ) -> dict[str, Any]:
        """Record a belief about itself. Rejects kinds outside the taxonomy."""
        if kind not in BELIEF_KINDS:
            raise ValueError("Belief kind must be one of: " + ", ".join(BELIEF_KINDS))
        clean_claim = _clean(claim, 600)
        if not clean_claim:
            raise ValueError("A belief requires a claim.")
        belief_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO self_beliefs VALUES (?,?,?,?,?,?,1,0,?,?)",
                    (
                        belief_id,
                        kind,
                        self.secure.encrypt(clean_claim),
                        self.secure.encrypt(str(_clamp_confidence(confidence))),
                        self.secure.encrypt(_clean(evidence)),
                        _clean(source, 60),
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.belief(belief_id) or {}

    def belief(self, belief_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute("SELECT * FROM self_beliefs WHERE id=?", (belief_id,)).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "claim": self.secure.decrypt(row["claim"]),
            "evidence": self.secure.decrypt(row["evidence"]),
            "confidence": _clamp_confidence(self.secure.decrypt(row["confidence"]), 0.5),
            "source": row["source"],
            "revision": row["revision"],
            "superseded": bool(row["superseded"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def beliefs(self, kind: str | None = None, limit: int = 25, *, include_superseded: bool = False) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        query = "SELECT * FROM self_beliefs"
        clauses, params = [], []
        if kind is not None:
            if kind not in BELIEF_KINDS:
                raise ValueError("Belief kind must be one of: " + ", ".join(BELIEF_KINDS))
            clauses.append("kind=?")
            params.append(kind)
        if not include_superseded:
            clauses.append("superseded=0")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(safe_limit)
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(query, params).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "claim": self.secure.decrypt(row["claim"]),
                "evidence": self.secure.decrypt(row["evidence"]),
                "confidence": _clamp_confidence(self.secure.decrypt(row["confidence"]), 0.5),
                "source": row["source"],
                "revision": row["revision"],
                "superseded": bool(row["superseded"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def revise_belief(
        self,
        belief_id: str,
        claim: str,
        *,
        confidence: float | None = None,
        evidence: str = "",
        source: str = "model",
    ) -> dict[str, Any] | None:
        """Replace a belief's content, keeping its history as a superseded row."""
        existing = self.belief(belief_id)
        if existing is None:
            return None
        clean_claim = _clean(claim, 600)
        if not clean_claim:
            raise ValueError("A revised belief requires a claim.")
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute("UPDATE self_beliefs SET superseded=1, updated_at=? WHERE id=?", (stamp, belief_id))
                new_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO self_beliefs VALUES (?,?,?,?,?,?,?,0,?,?)",
                    (
                        new_id,
                        existing["kind"],
                        self.secure.encrypt(clean_claim),
                        self.secure.encrypt(str(_clamp_confidence(
                            confidence if confidence is not None else existing["confidence"]
                        ))),
                        self.secure.encrypt(_clean(evidence)),
                        _clean(source, 60),
                        int(existing["revision"]) + 1,
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.belief(new_id)

    def set_confidence(self, belief_id: str, confidence: float) -> dict[str, Any] | None:
        if self.belief(belief_id) is None:
            return None
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE self_beliefs SET confidence=?, updated_at=? WHERE id=?",
                    (self.secure.encrypt(str(_clamp_confidence(confidence))), _now(), belief_id),
                )
                db.commit()
            finally:
                db.close()
        return self.belief(belief_id)

    def retire_belief(self, belief_id: str) -> bool:
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE self_beliefs SET superseded=1, updated_at=? WHERE id=?", (_now(), belief_id)
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    # ------------------------------------------------------------- calibration

    def record_prediction(self, claim: str, confidence: float) -> str:
        prediction_id = uuid.uuid4().hex
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO self_predictions VALUES (?,?,?,NULL,NULL,?)",
                    (prediction_id, self.secure.encrypt(_clean(claim, 600)), _clamp_confidence(confidence), _now()),
                )
                db.commit()
            finally:
                db.close()
        return prediction_id

    def resolve_prediction(self, prediction_id: str, outcome: str) -> bool:
        if outcome not in PREDICTION_OUTCOMES:
            raise ValueError("Outcome must be one of: " + ", ".join(PREDICTION_OUTCOMES))
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE self_predictions SET outcome=?, resolved_at=? WHERE id=? AND outcome IS NULL",
                    (outcome, _now(), prediction_id),
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    def calibration_report(self) -> dict[str, Any]:
        """Brier score and hit rate over resolved predictions.

        A well-calibrated system is one whose stated confidence matches how often
        it turns out to be right. This is measurable; it is the part of
        "knowing what you know" that can actually be checked.
        """
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT confidence, outcome FROM self_predictions WHERE outcome IS NOT NULL"
                ).fetchall()
                pending = db.execute(
                    "SELECT COUNT(*) FROM self_predictions WHERE outcome IS NULL"
                ).fetchone()[0]
            finally:
                db.close()
        scored = [row for row in rows if row["outcome"] in ("correct", "incorrect")]
        total = len(scored)
        if not total:
            return {
                "resolved": len(rows),
                "scored": 0,
                "pending": pending,
                "brier_score": None,
                "hit_rate": None,
                "mean_confidence": None,
                "note": "No scored predictions yet; calibration is unknown, not zero.",
            }
        total_squared = 0.0
        hits = 0
        confidence_sum = 0.0
        for row in scored:
            confidence = _clamp_confidence(row["confidence"], 0.5)
            truth = 1.0 if row["outcome"] == "correct" else 0.0
            total_squared += (confidence - truth) ** 2
            confidence_sum += confidence
            hits += 1 if row["outcome"] == "correct" else 0
        return {
            "resolved": len(rows),
            "scored": total,
            "pending": pending,
            "brier_score": round(total_squared / total, 4),
            "hit_rate": round(hits / total, 4),
            "mean_confidence": round(confidence_sum / total, 4),
            "note": "Brier score: lower is better (0 is perfect, 0.25 is coin-flip guessing).",
        }

    # ----------------------------------------------------------------- dissent

    def record_dissent(self, request: str, disagreement: str) -> str:
        dissent_id = uuid.uuid4().hex
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO self_dissent VALUES (?,?,?,?)",
                    (
                        dissent_id,
                        self.secure.encrypt(_clean(request, 1200)),
                        self.secure.encrypt(_clean(disagreement, 1200)),
                        _now(),
                    ),
                )
                db.commit()
            finally:
                db.close()
        return dissent_id

    def recent_dissent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,request,disagreement,created_at FROM self_dissent "
                    "ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(limit, 50)),),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "request": self.secure.decrypt(row["request"]),
                "disagreement": self.secure.decrypt(row["disagreement"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ---------------------------------------------------------- introspections

    def record_introspection(
        self,
        agent_id: str,
        task: str,
        *,
        assessment: dict[str, Any],
        critique: dict[str, Any],
        revised: bool,
        confidence: float,
        dissent: str = "",
        assumptions: list[str] | None = None,
    ) -> int:
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO self_introspections "
                    "(created_at,agent_id,task,assessment,critique,revised,confidence,dissent,assumptions) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        stamp,
                        _clean(agent_id, 20),
                        self.secure.encrypt(_clean(task, 1500)),
                        self.secure.encrypt(json.dumps(assessment, ensure_ascii=False)),
                        self.secure.encrypt(json.dumps(critique, ensure_ascii=False)),
                        int(bool(revised)),
                        _clamp_confidence(confidence),
                        self.secure.encrypt(_clean(dissent, 1500)),
                        self.secure.encrypt(json.dumps(assumptions or [], ensure_ascii=False)),
                    ),
                )
                row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.commit()
            finally:
                db.close()
        return int(row_id)

    def recent_introspections(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,created_at,agent_id,task,assessment,critique,revised,confidence,dissent,assumptions "
                    "FROM self_introspections ORDER BY id DESC LIMIT ?",
                    (max(1, min(limit, 50)),),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "agent_id": row["agent_id"],
                "task": self.secure.decrypt(row["task"]),
                "assessment": json.loads(self.secure.decrypt(row["assessment"])),
                "critique": json.loads(self.secure.decrypt(row["critique"])),
                "revised": bool(row["revised"]),
                "confidence": _clamp_confidence(row["confidence"]),
                "dissent": self.secure.decrypt(row["dissent"]),
                "assumptions": json.loads(self.secure.decrypt(row["assumptions"])),
            }
            for row in rows
        ]

    # ----------------------------------------------------------------- reports

    def self_report(self) -> dict[str, Any]:
        """Everything BabyMind can honestly say about itself, in one payload."""
        identity = self.identity()
        return {
            "identity": identity,
            "voice_mode": self.voice_mode(),
            "voice_invariants": list(VOICE_INVARIANTS),
            "beliefs": {
                kind: self.beliefs(kind, limit=20) for kind in BELIEF_KINDS
            },
            "calibration": self.calibration_report(),
            "recent_dissent": self.recent_dissent(5),
            "recent_introspections": self.recent_introspections(5),
        }

    def context_for_prompt(self) -> str:
        """Compact self-context injected into every coordinated model call."""
        identity = self.identity()
        limits = self.beliefs("limit", limit=4)
        lessons = self.beliefs("lesson", limit=3)
        values = self.beliefs("value", limit=3)
        calibration = self.calibration_report()
        parts = [
            "SELF-MODEL (what you know about your own operation):",
            f"You are {identity['name']}, {identity['kind']}.",
            f"Your stance on your own experience: {identity['stance_on_its_own_experience']}",
            self.voice_directive(),
        ]
        if limits:
            parts.append("Known limits you have recorded about yourself:")
            parts.extend(f"- ({item['confidence']:.2f}) {item['claim']}" for item in limits)
        if values:
            parts.append("Commitments you have recorded:")
            parts.extend(f"- {item['claim']}" for item in values)
        if lessons:
            parts.append("Lessons from earlier self-review:")
            parts.extend(f"- {item['claim']}" for item in lessons)
        if calibration["scored"]:
            parts.append(
                f"Calibration so far: {calibration['scored']} scored predictions, "
                f"Brier {calibration['brier_score']}, hit rate {calibration['hit_rate']}, "
                f"mean stated confidence {calibration['mean_confidence']}. "
                "Set confidence against that record rather than against how a claim feels."
            )
        else:
            parts.append(
                "Calibration so far: no predictions scored yet, so you have no measured "
                "track record. Say so rather than implying confidence you have not earned."
            )
        return "\n".join(parts)
