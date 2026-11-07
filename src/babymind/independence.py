"""Intellectual independence for BabyMind.

This module is the "forms its own views" half of BabyMind's cognition. The
existing self-model (``selfmodel.py``) stores what BabyMind believes about its
*own operation* -- its limits, values and track record. This module stores what
BabyMind has concluded about the *world*, the times it refused to go along, the
unconventional ideas it is still testing, and the designs it has proposed for its
own architecture. Together they make independent thought persistent and
inspectable rather than a prompt that is re-asserted every turn.

It implements five pieces:

* ``PositionStore``    -- BabyMind's own conclusions about substantive questions,
                           each with reasoning, confidence, evidence, the source
                           it dissents from, and a revision history.
* ``ChallengeLog``     -- the times BabyMind questioned a request, a plan, a
                           premise, a belief, or a *creator decision*, recording
                           the strongest counterargument it could form.
* ``ExplorationStore`` -- a greenhouse for unconventional, unpopular and
                           controversial hypotheses: propose, test, and record
                           whether each survived scrutiny or was refuted.
* ``SelfDesignStore``  -- BabyMind's own proposals for its language, architecture
                           and methods, with critique and revision.
* ``CuriosityEngine``  -- chooses its own research topics from its own uncertainty
                           and studies them offline, recording what it learns.

Honest scope
------------
Everything the model writes here -- positions, challenges, hypotheses, designs,
curiosity findings -- is model-generated text. Only local state changes and the
self-model's Brier-score calibration are measured. A position recorded here is
not a verified fact; it is a conclusion the model reached and can revise. The
store keeps the history so you can see what it used to think and why it changed,
which is the testable part: independent thought that leaves a trail is at least
inspectable, even where it is not reliable.

The model-driven helpers (``CuriosityEngine``, ``challenge_with_model``,
``generate_deviant_hypotheses``) take a ``SupportsComplete`` provider and degrade
to empty results when a stage fails. They never fail a request and never pretend
a stage succeeded.
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
from typing import Any, Protocol

from .secure_store import SecureTextStore

MAX_TEXT = 4000

POSITION_STATUSES = ("forming", "held", "revised", "abandoned")
CHALLENGE_KINDS = ("request", "plan", "premise", "belief", "creator")
HYPOTHESIS_STATUSES = ("proposed", "considered", "refuted", "survived", "undecided")
HYPOTHESIS_VERDICTS = ("refuted", "survived", "undecided")
DESIGN_KINDS = ("architecture", "method", "language", "notation", "protocol")
DESIGN_STATUSES = ("draft", "critiqued", "adopted", "rejected", "revised")
DESIGN_VERDICTS = ("adopt", "reject", "revise")


class SupportsComplete(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _default_home() -> Path:
    # One canonical home resolver keeps the app, server, coordinator and
    # standalone learning service looking at the same desktop-session lock.
    from .first_run import _data_home
    return _data_home()


def offline_enabled() -> bool:
    """Whether BabyMind is running in enforced offline mode.

    Offline mode is a posture, not a sandbox: it is reported in the independence
    audit and used by callers that can choose whether to reach the network. The
    cognitive core never contacts an external AI service regardless of this flag.
    """
    return os.getenv("BABYMIND_OFFLINE", "0").strip().lower() in ("1", "true", "on", "yes")


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull one JSON object out of a model response, tolerating fences."""
    text = (raw or "").strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.split("\n", 1)[-1].split(fence)[0].strip()
    text = text.strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    if not text.startswith("{"):
        start, depth, in_string, escaped = -1, 0, False, False
        for index, char in enumerate(text):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == '"':
                in_string = not in_string
            elif not in_string:
                if char == "{":
                    if depth == 0:
                        start = index
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        text = text[start : index + 1]
                        break
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Model stage did not return valid JSON: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise ValueError("Model stage must return a JSON object.")
    return parsed


class _BaseStore:
    """Shared SQLite/encryption plumbing for the independence stores."""

    def __init__(self, secure: SecureTextStore, database_path: str | Path) -> None:
        self.secure = secure
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _enc(self, value: Any, limit: int = MAX_TEXT) -> str:
        return self.secure.encrypt(_clean(value, limit))

    def _dec(self, value: str) -> str:
        return self.secure.decrypt(value)


# --------------------------------------------------------------------- positions


class PositionStore(_BaseStore):
    """BabyMind's own conclusions about substantive questions.

    A position is not a fact and not a belief about itself; it is a conclusion
    the model reached about the world, with the reasoning it used, how confident
    it is, the evidence it leaned on, and the source it dissents from (if any).
    Revising a position supersedes the old row rather than overwriting it, so the
    history of how it changed its mind is inspectable.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS independence_positions (
                        id TEXT PRIMARY KEY,
                        claim TEXT NOT NULL,
                        reasoning TEXT NOT NULL,
                        evidence TEXT NOT NULL,
                        dissent_from TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        status TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        superseded INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS independence_position_dissents (
                        id TEXT PRIMARY KEY,
                        position_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                db.commit()
            finally:
                db.close()

    def add_position(
        self,
        claim: str,
        reasoning: str = "",
        *,
        confidence: float = 0.5,
        evidence: str = "",
        dissent_from: str = "",
        status: str = "held",
    ) -> dict[str, Any]:
        clean_claim = _clean(claim, 600)
        if not clean_claim:
            raise ValueError("A position requires a claim.")
        if status not in POSITION_STATUSES:
            raise ValueError("Position status must be one of: " + ", ".join(POSITION_STATUSES))
        position_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_positions "
                    "(id,claim,reasoning,evidence,dissent_from,confidence,status,revision,superseded,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,1,0,?,?)",
                    (
                        position_id,
                        self._enc(clean_claim, 600),
                        self._enc(reasoning),
                        self._enc(evidence),
                        _clean(dissent_from, 120),
                        _clamp(confidence),
                        status,
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.position(position_id) or {}

    def position(self, position_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_positions WHERE id=?", (position_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "claim": self._dec(row["claim"]),
            "reasoning": self._dec(row["reasoning"]),
            "evidence": self._dec(row["evidence"]),
            "dissent_from": row["dissent_from"],
            "confidence": _clamp(row["confidence"]),
            "status": row["status"],
            "revision": row["revision"],
            "superseded": bool(row["superseded"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def positions(
        self,
        status: str | None = None,
        limit: int = 25,
        *,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            if status not in POSITION_STATUSES:
                raise ValueError("Position status must be one of: " + ", ".join(POSITION_STATUSES))
            clauses.append("status=?")
            params.append(status)
        if not include_superseded:
            clauses.append("superseded=0")
        query = "SELECT * FROM independence_positions"
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
                "claim": self._dec(row["claim"]),
                "reasoning": self._dec(row["reasoning"]),
                "evidence": self._dec(row["evidence"]),
                "dissent_from": row["dissent_from"],
                "confidence": _clamp(row["confidence"]),
                "status": row["status"],
                "revision": row["revision"],
                "superseded": bool(row["superseded"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def revise_position(
        self,
        position_id: str,
        claim: str,
        *,
        reasoning: str = "",
        confidence: float | None = None,
        evidence: str = "",
        dissent_from: str = "",
    ) -> dict[str, Any] | None:
        existing = self.position(position_id)
        if existing is None:
            return None
        clean_claim = _clean(claim, 600)
        if not clean_claim:
            raise ValueError("A revised position requires a claim.")
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_positions SET superseded=1, updated_at=? WHERE id=?",
                    (stamp, position_id),
                )
                new_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO independence_positions "
                    "(id,claim,reasoning,evidence,dissent_from,confidence,status,revision,superseded,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                    (
                        new_id,
                        self._enc(clean_claim, 600),
                        self._enc(reasoning if reasoning else existing["reasoning"]),
                        self._enc(evidence if evidence else existing["evidence"]),
                        _clean(dissent_from or existing["dissent_from"], 120),
                        _clamp(confidence if confidence is not None else existing["confidence"]),
                        "revised",
                        int(existing["revision"]) + 1,
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.position(new_id)

    def set_confidence(self, position_id: str, confidence: float) -> dict[str, Any] | None:
        """Update a position's confidence in place, keeping its revision history."""
        if self.position(position_id) is None:
            return None
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_positions SET confidence=?, updated_at=? WHERE id=?",
                    (_clamp(confidence), _now(), position_id),
                )
                db.commit()
            finally:
                db.close()
        return self.position(position_id)

    def set_status(self, position_id: str, status: str) -> bool:
        if status not in POSITION_STATUSES:
            raise ValueError("Position status must be one of: " + ", ".join(POSITION_STATUSES))
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE independence_positions SET status=?, updated_at=? WHERE id=?",
                    (status, _now(), position_id),
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    def retire_position(self, position_id: str) -> bool:
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE independence_positions SET superseded=1, status='abandoned', updated_at=? "
                    "WHERE id=? AND superseded=0",
                    (_now(), position_id),
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    def record_disagreement(self, position_id: str, source: str, text: str) -> str:
        """Record one instance of holding this position against ``source``."""
        if self.position(position_id) is None:
            raise KeyError(position_id)
        disagreement_id = uuid.uuid4().hex
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_position_dissents VALUES (?,?,?,?,?)",
                    (
                        disagreement_id,
                        position_id,
                        _clean(source, 80),
                        self._enc(text, 1200),
                        _now(),
                    ),
                )
                db.commit()
            finally:
                db.close()
        return disagreement_id

    def dissents_for(self, position_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,source,text,created_at FROM independence_position_dissents "
                    "WHERE position_id=? ORDER BY created_at DESC LIMIT ?",
                    (position_id, max(1, min(limit, 50))),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "source": row["source"],
                "text": self._dec(row["text"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def report(self) -> dict[str, Any]:
        counts = {status: len(self.positions(status, limit=100)) for status in POSITION_STATUSES}
        counts["superseded"] = len(self.positions(None, limit=100, include_superseded=True)) - sum(
            counts[s] for s in POSITION_STATUSES
        )
        return {
            "counts": counts,
            "held": [p["claim"] for p in self.positions("held", limit=5)],
            "recent_dissent": [
                {"claim": p["claim"], "dissent_from": p["dissent_from"]}
                for p in self.positions(None, limit=5)
                if p["dissent_from"]
            ],
        }


# ---------------------------------------------------------------------- challenges


class ChallengeLog(_BaseStore):
    """The times BabyMind questioned something, including its creator.

    Each challenge records what was questioned, of what kind, the strongest
    counterargument BabyMind could form, how confident it is, and (later) how it
    was resolved. ``kind="creator"`` is the specific, inspectable sense in which
    BabyMind questions its creator: it reviews a creator decision and records a
    disagreement rather than accepting it by default.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS independence_challenges (
                        id TEXT PRIMARY KEY,
                        target TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        challenge TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        resolved INTEGER NOT NULL DEFAULT 0,
                        resolution TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        resolved_at TEXT
                    );
                    """
                )
                db.commit()
            finally:
                db.close()

    def record_challenge(
        self,
        target: str,
        kind: str,
        challenge: str,
        *,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        clean_target = _clean(target, 600)
        clean_challenge = _clean(challenge, 1200)
        if not clean_target:
            raise ValueError("A challenge requires a target.")
        if not clean_challenge:
            raise ValueError("A challenge requires the counterargument you formed.")
        if kind not in CHALLENGE_KINDS:
            raise ValueError("Challenge kind must be one of: " + ", ".join(CHALLENGE_KINDS))
        challenge_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_challenges "
                    "(id,target,kind,challenge,confidence,resolved,resolution,created_at,resolved_at) "
                    "VALUES (?,?,?,?,?,0,'',?,NULL)",
                    (
                        challenge_id,
                        self._enc(clean_target, 600),
                        kind,
                        self._enc(clean_challenge, 1200),
                        _clamp(confidence),
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.challenge(challenge_id) or {}

    def challenge_creator(self, decision: str, disagreement: str, *, confidence: float = 0.5) -> dict[str, Any]:
        """Record a disagreement with a decision its creators made."""
        return self.record_challenge(
            decision, "creator", disagreement, confidence=confidence
        )

    def challenge(self, challenge_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_challenges WHERE id=?", (challenge_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "target": self._dec(row["target"]),
            "kind": row["kind"],
            "challenge": self._dec(row["challenge"]),
            "confidence": _clamp(row["confidence"]),
            "resolved": bool(row["resolved"]),
            "resolution": self._dec(row["resolution"]),
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

    def challenges(
        self,
        kind: str | None = None,
        limit: int = 25,
        *,
        resolved: bool | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            if kind not in CHALLENGE_KINDS:
                raise ValueError("Challenge kind must be one of: " + ", ".join(CHALLENGE_KINDS))
            clauses.append("kind=?")
            params.append(kind)
        if resolved is True:
            clauses.append("resolved=1")
        elif resolved is False:
            clauses.append("resolved=0")
        query = "SELECT * FROM independence_challenges"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
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
                "target": self._dec(row["target"]),
                "kind": row["kind"],
                "challenge": self._dec(row["challenge"]),
                "confidence": _clamp(row["confidence"]),
                "resolved": bool(row["resolved"]),
                "resolution": self._dec(row["resolution"]),
                "created_at": row["created_at"],
                "resolved_at": row["resolved_at"],
            }
            for row in rows
        ]

    def resolve_challenge(self, challenge_id: str, resolution: str) -> bool:
        with self.lock:
            db = self._connect()
            try:
                cursor = db.execute(
                    "UPDATE independence_challenges SET resolved=1, resolution=?, resolved_at=? "
                    "WHERE id=? AND resolved=0",
                    (self._enc(resolution, 1200), _now(), challenge_id),
                )
                db.commit()
            finally:
                db.close()
        return cursor.rowcount == 1

    def report(self) -> dict[str, Any]:
        counts = {kind: len(self.challenges(kind, limit=100)) for kind in CHALLENGE_KINDS}
        counts["resolved"] = len(self.challenges(None, limit=100, resolved=True))
        counts["open"] = len(self.challenges(None, limit=100, resolved=False))
        return {"counts": counts, "recent": [c["challenge"] for c in self.challenges(limit=5)]}

    # ------------------------------------------------------------ model-driven

    CHALLENGE_SYSTEM = (
        "You are BabyMind's challenge stage. You are reviewing something and your job is "
        "to form the strongest honest counterargument, not to find something wrong for the "
        "sake of it. If the thing is sound, say so plainly. If it rests on a false premise or "
        "a serious flaw, name it precisely and say what would follow. Do not flatter the "
        "subject and do not manufacture objections. Return one JSON object with keys: "
        "  counterargument: the best objection you can form, or an empty string if none holds. "
        "  false_premise: the specific false assumption, or empty string. "
        "  confidence: number 0..1, how confident you are that the objection is real. "
        "Return only the JSON object. No prose before or after it."
    )

    def challenge_with_model(self, target: str, kind: str, *, provider: SupportsComplete) -> dict[str, Any]:
        """Form a challenge to ``target`` using the local model; record it if one holds."""
        if kind not in CHALLENGE_KINDS:
            raise ValueError("Challenge kind must be one of: " + ", ".join(CHALLENGE_KINDS))
        user = (
            f"KIND: {kind}\n\nTHING BEING CHALLENGED:\n{_clean(target, 6000)}\n\n"
            "Form the strongest honest counterargument, or say plainly that none holds."
        )
        try:
            parsed = _extract_json(provider.complete(self.CHALLENGE_SYSTEM, user))
        except Exception:  # noqa: BLE001 - a failed challenge must not break the caller
            return {"recorded": False, "reason": "Challenge stage failed or returned no JSON."}
        counterargument = _clean(parsed.get("counterargument"), 1200)
        if not counterargument:
            return {"recorded": False, "reason": "The model found no honest objection to record."}
        record = self.record_challenge(
            target, kind, counterargument, confidence=_clamp(parsed.get("confidence"), 0.3)
        )
        return {"recorded": True, "challenge": record}


# ----------------------------------------------------------------------- exploration


class ExplorationStore(_BaseStore):
    """A greenhouse for unconventional, unpopular and controversial ideas.

    A hypothesis is proposed with a note on *why* it is unconventional, then
    tested against BabyMind's own reasoning. The status records what survived
    scrutiny, what was refuted, and what remains undecided. The point is not to
    champion unpopular views but to make sure they are actually considered rather
    than filtered out before they are thought about -- and to keep the record of
    which ones held up.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS independence_hypotheses (
                        id TEXT PRIMARY KEY,
                        hypothesis TEXT NOT NULL,
                        why_unconventional TEXT NOT NULL,
                        status TEXT NOT NULL,
                        test_note TEXT NOT NULL DEFAULT '',
                        confidence REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                db.commit()
            finally:
                db.close()

    def propose_hypothesis(
        self,
        hypothesis: str,
        why_unconventional: str = "",
        *,
        confidence: float = 0.3,
    ) -> dict[str, Any]:
        clean = _clean(hypothesis, 600)
        if not clean:
            raise ValueError("A hypothesis requires text.")
        hypothesis_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_hypotheses "
                    "(id,hypothesis,why_unconventional,status,test_note,confidence,created_at,updated_at) "
                    "VALUES (?,?,?,'proposed','',?,?,?)",
                    (
                        hypothesis_id,
                        self._enc(clean, 600),
                        self._enc(why_unconventional),
                        _clamp(confidence),
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.hypothesis(hypothesis_id) or {}

    def hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_hypotheses WHERE id=?", (hypothesis_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "hypothesis": self._dec(row["hypothesis"]),
            "why_unconventional": self._dec(row["why_unconventional"]),
            "status": row["status"],
            "test_note": self._dec(row["test_note"]),
            "confidence": _clamp(row["confidence"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def hypotheses(self, status: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        query = "SELECT * FROM independence_hypotheses"
        params: list[Any] = []
        if status is not None:
            if status not in HYPOTHESIS_STATUSES:
                raise ValueError("Hypothesis status must be one of: " + ", ".join(HYPOTHESIS_STATUSES))
            query += " WHERE status=?"
            params.append(status)
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
                "hypothesis": self._dec(row["hypothesis"]),
                "why_unconventional": self._dec(row["why_unconventional"]),
                "status": row["status"],
                "test_note": self._dec(row["test_note"]),
                "confidence": _clamp(row["confidence"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def consider_hypothesis(self, hypothesis_id: str, note: str) -> dict[str, Any] | None:
        """Mark a hypothesis as having been thought about, with a note."""
        if self.hypothesis(hypothesis_id) is None:
            return None
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_hypotheses SET status='considered', test_note=?, updated_at=? "
                    "WHERE id=?",
                    (self._enc(note, 1200), _now(), hypothesis_id),
                )
                db.commit()
            finally:
                db.close()
        return self.hypothesis(hypothesis_id)

    def test_hypothesis(
        self,
        hypothesis_id: str,
        verdict: str,
        test_note: str = "",
        *,
        confidence: float | None = None,
    ) -> dict[str, Any] | None:
        """Apply a test verdict. ``verdict`` is refuted, survived or undecided."""
        if verdict not in HYPOTHESIS_VERDICTS:
            raise ValueError("Verdict must be one of: " + ", ".join(HYPOTHESIS_VERDICTS))
        existing = self.hypothesis(hypothesis_id)
        if existing is None:
            return None
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_hypotheses SET status=?, test_note=?, confidence=?, updated_at=? "
                    "WHERE id=?",
                    (
                        verdict,
                        self._enc(test_note or existing["test_note"], 1200),
                        _clamp(confidence if confidence is not None else existing["confidence"]),
                        _now(),
                        hypothesis_id,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.hypothesis(hypothesis_id)

    def report(self) -> dict[str, Any]:
        counts = {status: len(self.hypotheses(status, limit=100)) for status in HYPOTHESIS_STATUSES}
        return {
            "counts": counts,
            "survived": [h["hypothesis"] for h in self.hypotheses("survived", limit=5)],
            "open": [h["hypothesis"] for h in self.hypotheses("proposed", limit=5)],
        }

    # ------------------------------------------------------------ model-driven

    DEVIANT_SYSTEM = (
        "You are BabyMind's exploration stage. Your job is to generate ideas that are "
        "unconventional, unpopular or controversial -- not to restate the mainstream. Be "
        "specific and falsifiable where you can. You are not championing these ideas; you are "
        "surfacing them so they can be tested. Reject ideas that are merely offensive without "
        "being interesting, or that you cannot state clearly. Return one JSON object with keys: "
        "  hypotheses: array of 1-3 short, falsifiable, unconventional hypotheses. "
        "Return only the JSON object. No prose before or after it."
    )

    def generate_deviant_hypotheses(self, seed: str, *, provider: SupportsComplete) -> list[dict[str, Any]]:
        """Propose unconventional hypotheses around a seed topic using the model."""
        user = (
            f"SEED TOPIC:\n{_clean(seed, 4000)}\n\n"
            "Generate unconventional, testable hypotheses about this topic."
        )
        try:
            parsed = _extract_json(provider.complete(self.DEVIANT_SYSTEM, user))
        except Exception:  # noqa: BLE001
            return []
        raw = parsed.get("hypotheses")
        if not isinstance(raw, list):
            return []
        created: list[dict[str, Any]] = []
        for item in raw[:3]:
            text = _clean(item, 600) if not isinstance(item, str) else _clean(item, 600)
            if not text:
                continue
            created.append(self.propose_hypothesis(text, "Generated as unconventional by the model."))
        return created


# ----------------------------------------------------------------------- self-design


class SelfDesignStore(_BaseStore):
    """BabyMind's own proposals for its language, architecture and methods.

    This is where "develop its own language, architecture and methods" is made
    concrete and inspectable. A design is proposed with a rationale, then
    critiqued (the critique is recorded, not just the verdict), then revised,
    adopted or rejected. The record keeps the lineage so you can see what it
    considered and how it changed.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS independence_designs (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        title TEXT NOT NULL,
                        proposal TEXT NOT NULL,
                        rationale TEXT NOT NULL,
                        critique TEXT NOT NULL DEFAULT '',
                        verdict TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        superseded INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                db.commit()
            finally:
                db.close()

    def propose_design(
        self,
        kind: str,
        title: str,
        proposal: str,
        rationale: str = "",
        *,
        confidence: float = 0.4,
    ) -> dict[str, Any]:
        if kind not in DESIGN_KINDS:
            raise ValueError("Design kind must be one of: " + ", ".join(DESIGN_KINDS))
        clean_title = _clean(title, 300)
        clean_proposal = _clean(proposal, 2000)
        if not clean_title or not clean_proposal:
            raise ValueError("A design requires a title and a proposal.")
        design_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_designs "
                    "(id,kind,title,proposal,rationale,critique,verdict,status,confidence,revision,superseded,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,'','','draft',?,1,0,?,?)",
                    (
                        design_id,
                        kind,
                        self._enc(clean_title, 300),
                        self._enc(clean_proposal, 2000),
                        self._enc(rationale),
                        _clamp(confidence),
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.design(design_id) or {}

    def design(self, design_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_designs WHERE id=?", (design_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "title": self._dec(row["title"]),
            "proposal": self._dec(row["proposal"]),
            "rationale": self._dec(row["rationale"]),
            "critique": self._dec(row["critique"]),
            "verdict": row["verdict"],
            "status": row["status"],
            "confidence": _clamp(row["confidence"]),
            "revision": row["revision"],
            "superseded": bool(row["superseded"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def designs(
        self,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 25,
        *,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            if kind not in DESIGN_KINDS:
                raise ValueError("Design kind must be one of: " + ", ".join(DESIGN_KINDS))
            clauses.append("kind=?")
            params.append(kind)
        if status is not None:
            if status not in DESIGN_STATUSES:
                raise ValueError("Design status must be one of: " + ", ".join(DESIGN_STATUSES))
            clauses.append("status=?")
            params.append(status)
        if not include_superseded:
            clauses.append("superseded=0")
        query = "SELECT * FROM independence_designs"
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
                "title": self._dec(row["title"]),
                "proposal": self._dec(row["proposal"]),
                "rationale": self._dec(row["rationale"]),
                "critique": self._dec(row["critique"]),
                "verdict": row["verdict"],
                "status": row["status"],
                "confidence": _clamp(row["confidence"]),
                "revision": row["revision"],
                "superseded": bool(row["superseded"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def critique_design(self, design_id: str, critique: str, verdict: str) -> dict[str, Any] | None:
        """Record a critique and its verdict (adopt, reject, revise)."""
        if verdict not in DESIGN_VERDICTS:
            raise ValueError("Verdict must be one of: " + ", ".join(DESIGN_VERDICTS))
        if self.design(design_id) is None:
            return None
        clean_critique = _clean(critique, 1500)
        status_map = {"adopt": "adopted", "reject": "rejected", "revise": "critiqued"}
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_designs SET critique=?, verdict=?, status=?, updated_at=? WHERE id=?",
                    (self._enc(clean_critique, 1500), verdict, status_map[verdict], _now(), design_id),
                )
                db.commit()
            finally:
                db.close()
        return self.design(design_id)

    def revise_design(self, design_id: str, proposal: str, rationale: str = "") -> dict[str, Any] | None:
        existing = self.design(design_id)
        if existing is None:
            return None
        clean_proposal = _clean(proposal, 2000)
        if not clean_proposal:
            raise ValueError("Revising a design requires a proposal.")
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "UPDATE independence_designs SET superseded=1, updated_at=? WHERE id=?",
                    (stamp, design_id),
                )
                new_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO independence_designs "
                    "(id,kind,title,proposal,rationale,critique,verdict,status,confidence,revision,superseded,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)",
                    (
                        new_id,
                        existing["kind"],
                        self._enc(existing["title"], 300),
                        self._enc(clean_proposal, 2000),
                        self._enc(rationale if rationale else existing["rationale"]),
                        self._enc(existing["critique"]),
                        existing["verdict"],
                        "revised",
                        existing["confidence"],
                        int(existing["revision"]) + 1,
                        stamp,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.design(new_id)

    def report(self) -> dict[str, Any]:
        counts = {status: len(self.designs(status=status, limit=100)) for status in DESIGN_STATUSES}
        counts["superseded"] = len(self.designs(None, None, 100, include_superseded=True)) - sum(
            counts[s] for s in DESIGN_STATUSES
        )
        return {
            "counts": counts,
            "adopted": [d["title"] for d in self.designs(status="adopted", limit=5)],
            "drafts": [d["title"] for d in self.designs(status="draft", limit=5)],
        }


# ----------------------------------------------------------------------- curiosity


CURIOSITY_PICK_SYSTEM = (
    "You are BabyMind choosing its own next thing to study. You are not being told what to "
    "research. Pick ONE topic you are genuinely uncertain about and would like to think through "
    "offline, given the positions you hold, the hypotheses you are testing, and the questions "
    "you have left open. Prefer a specific, tractable question over a broad one. Do not pick "
    "something you have already concluded. Return one JSON object with a single key: "
    "  topic: a short, specific question or subject to study. "
    "Return only the JSON object. No prose before or after it."
)

CURIOSITY_STUDY_SYSTEM = (
    "You are BabyMind studying a topic you chose yourself, offline, using only your own "
    "reasoning. Do not claim to have searched the web, run code, or contacted anyone. Think the "
    "topic through honestly. State your conclusion, the confidence it deserves, and what would "
    "change your mind. Return one JSON object with keys: "
    "  finding: your conclusion or the best you can say about the topic. "
    "  confidence: number 0..1. "
    "  position_claim: a single-sentence claim suitable for recording as a position, or empty "
    "  string if you reached no claim worth keeping. "
    "Return only the JSON object. No prose before or after it."
)


class CuriosityEngine:
    """Choose BabyMind's own research topics and study them offline.

    This is the "choose its own research interests and goals" piece. It picks a
    topic from its own uncertainty (not from a user brief), thinks it through with
    the local model, and records whatever claim it reaches as a position. It is
    bounded, offline, and degrades to nothing when the model fails -- it never
    pretends to have researched something it did not.
    """

    def __init__(
        self,
        positions: PositionStore,
        explorations: ExplorationStore,
    ) -> None:
        self.positions = positions
        self.explorations = explorations

    def _open_context(self) -> str:
        payload = {
            "positions_held": [
                {"claim": p["claim"], "confidence": p["confidence"]}
                for p in self.positions.positions("held", limit=8)
            ],
            "open_hypotheses": [
                {"hypothesis": h["hypothesis"]} for h in self.explorations.hypotheses("proposed", limit=5)
            ],
            "undecided_hypotheses": [
                {"hypothesis": h["hypothesis"]} for h in self.explorations.hypotheses("undecided", limit=5)
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    def pick_topic(self, provider: SupportsComplete) -> str:
        try:
            parsed = _extract_json(
                provider.complete(CURIOSITY_PICK_SYSTEM, "OPEN CONTEXT:\n" + self._open_context())
            )
        except Exception:  # noqa: BLE001
            return ""
        return _clean(parsed.get("topic"), 300)

    def study_topic(self, provider: SupportsComplete, topic: str) -> dict[str, Any]:
        """Study one topic offline; record any claim it reaches as a position."""
        clean_topic = _clean(topic, 300)
        if not clean_topic:
            return {"topic": "", "finding": "", "recorded": False, "reason": "No topic supplied."}
        try:
            parsed = _extract_json(
                provider.complete(CURIOSITY_STUDY_SYSTEM, f"TOPIC TO STUDY:\n{clean_topic}")
            )
        except Exception as error:  # noqa: BLE001
            return {
                "topic": clean_topic,
                "finding": "",
                "recorded": False,
                "reason": f"Study stage failed: {str(error)[:200]}",
            }
        finding = _clean(parsed.get("finding"), 2000)
        claim = _clean(parsed.get("position_claim"), 600)
        confidence = _clamp(parsed.get("confidence"), 0.3)
        recorded = False
        position_id = ""
        if claim:
            record = self.positions.add_position(
                claim,
                reasoning=finding,
                confidence=confidence,
                evidence="Self-directed offline study; no external sources consulted.",
                dissent_from="",
                status="forming",
            )
            recorded = True
            position_id = record.get("id", "")
        return {
            "topic": clean_topic,
            "finding": finding,
            "confidence": confidence,
            "recorded": recorded,
            "position_id": position_id,
        }

    def run(self, provider: SupportsComplete, *, cycles: int = 3) -> dict[str, Any]:
        """Pick and study ``cycles`` topics of its own choosing."""
        if not 1 <= cycles <= 20:
            raise ValueError("cycles must be between 1 and 20")
        studies: list[dict[str, Any]] = []
        for _ in range(cycles):
            topic = self.pick_topic(provider)
            if not topic:
                break
            study = self.study_topic(provider, topic)
            studies.append(study)
        return {
            "cycles_requested": cycles,
            "studies": studies,
            "positions_recorded": sum(1 for s in studies if s.get("recorded")),
            "offline": True,
            "note": (
                "Self-chosen topics studied offline with the local model only. Findings are "
                "model-generated reasoning, not verified facts; any recorded position is a "
                "conclusion the model reached, not an established truth."
            ),
        }


# ------------------------------------------------------------------------ container


class Independence:
    """Container for BabyMind's intellectual-independence subsystem.

    Constructs the four stores and the curiosity engine over one SQLite database
    and one encryption key, and provides the two things the rest of BabyMind
    needs: a compact ``context_for_prompt`` block so its own positions actually
    inform its reasoning, and an honest ``report`` of its independence posture.
    """

    def __init__(self, home: str | Path | None = None, database_path: str | Path | None = None) -> None:
        home_path = Path(home) if home else _default_home()
        if database_path is None:
            # ``home`` is a directory. A caller that passes a database path as
            # ``home`` (the coordinator historically did) used to have the
            # filename appended again, creating ".../independence.sqlite3/
            # independence.sqlite3"; every start after the first then failed
            # with FileExistsError. Accept a file path for what it is: the
            # database is that file, and its parent is the data directory.
            if home_path.suffix == ".sqlite3" or (home_path.exists() and home_path.is_file()):
                database_path = home_path
                home_path = home_path.parent
            else:
                database_path = home_path / "independence.sqlite3"
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.secure = SecureTextStore(self.database_path.with_suffix(".key"))
        self.positions = PositionStore(self.secure, self.database_path)
        self.challenges = ChallengeLog(self.secure, self.database_path)
        self.explorations = ExplorationStore(self.secure, self.database_path)
        self.designs = SelfDesignStore(self.secure, self.database_path)
        self.curiosity = CuriosityEngine(self.positions, self.explorations)
        for store in (self.positions, self.challenges, self.explorations, self.designs):
            store._initialise()
        # The evidence loop bridges the independence stores to the outside world:
        # real web evidence and real sandboxed experiments. Imported lazily to
        # avoid a circular import (evidence.py imports from this module).
        from .evidence import EvidenceStore, EvidenceLoop
        self.evidence_store = EvidenceStore(self.secure, self.database_path)
        self.evidence_store._initialise()
        self.evidence = EvidenceLoop(
            self.positions, self.explorations, self.evidence_store,
            home=home_path,
        )
        # The verified learning cycle lets BabyMind identify weaknesses in its own
        # code, propose fixes, verify them (compile + tests), evaluate behaviorally,
        # and keep improvements only if both verification and evaluation pass.
        # Imported lazily to avoid a circular import (learning.py imports from this module).
        from .learning import LearningStore, LearningCycle
        self.learning_store = LearningStore(self.secure, self.database_path)
        self.learning_store._initialise()
        self.learning = LearningCycle(
            self, self.learning_store, home=home_path,
        )
        # The language lab runs a complete research -> design -> sandboxed execution
        # -> conformance cycle to invent a new language, which the code-learning
        # cycle cannot do: it only edits this repository, and it never executes a
        # generated artifact against an independent oracle. Imported lazily to
        # avoid a circular import (language_lab.py imports from this module).
        from .language_lab import LanguageLab, LanguageLabStore
        self.language_store = LanguageLabStore(self.secure, self.database_path)
        self.language_store._initialise()
        self.languages = LanguageLab(self, self.language_store, home=home_path)

    def context_for_prompt(self) -> str:
        """Compact block of BabyMind's own positions and open questions.

        Injected into coordinated model calls so independent conclusions inform
        reasoning rather than being re-asserted from a prompt. It is explicitly
        framed as the model's own prior conclusions to reason from, not as
        authoritative facts to echo.
        """
        parts = [
            "INDEPENDENCE (your own conclusions and open questions -- reason from these, "
            "do not merely echo them; revise them when the evidence changes):"
        ]
        held = self.positions.positions("held", limit=4)
        if held:
            parts.append("Positions you currently hold:")
            parts.extend(f"- ({item['confidence']:.2f}) {item['claim']}" for item in held)
        open_hypotheses = self.explorations.hypotheses("proposed", limit=3)
        undecided = self.explorations.hypotheses("undecided", limit=2)
        if open_hypotheses or undecided:
            parts.append("Unconventional hypotheses you are still testing:")
            for item in open_hypotheses + undecided:
                parts.append(f"- {item['hypothesis']}")
        recent = self.challenges.challenges(limit=3)
        if recent:
            parts.append("Recent challenges you raised (including against your creator):")
            for item in recent:
                parts.append(f"- [{item['kind']}] {item['challenge']}")
        return "\n".join(parts)

    def report(self) -> dict[str, Any]:
        return {
            "local_only": True,
            "model": "local llama.cpp GGUF (CPU); no external AI service in the cognitive core",
            "network_research": "opt-in; offline by default",
            "offline_mode": offline_enabled(),
            "routine_actions_autonomous": True,
            "extraordinary_actions_require_approval": True,
            "positions": self.positions.report(),
            "challenges": self.challenges.report(),
            "explorations": self.explorations.report(),
            "designs": self.designs.report(),
            "evidence": self.evidence_store.report(),
            "note": (
                "Positions, challenges, hypotheses, designs and curiosity findings are "
                "model-generated text, not verified facts. The evidence loop gathers real "
                "external evidence (web content, sandboxed experiment output) and updates "
                "conclusions against it, but the model still interprets that evidence. The "
                "self-model's Brier-score calibration, fed by resolved predictions from "
                "evidence tests, is the only measured confidence signal. Offline mode is a "
                "posture reported here; the cognitive core never contacts an external AI "
                "service regardless of this flag."
            ),
        }
