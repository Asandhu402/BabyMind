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
learning cycle tests and improves *code*.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

GENESIS = "0" * 64
MAX_SOURCE_CHARS = 8000
MAX_FILE_CHARS = 2000
MAX_FILES_PER_CYCLE = 5


# --------------------------------------------------------------------------- store


class LearningStore(_BaseStore):
    """Encrypted store for weaknesses, learning cycles and an audit chain.

    Three tables over one SQLite database:

    * ``learning_weaknesses`` — identified weaknesses with their status.
    * ``learning_cycles`` — the full cycle record: weakness, fix result,
      behavioral evaluation, final decision, and the lesson.
    * ``learning_audit`` — a hash-chained log of every decision.

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
                        updated_at TEXT NOT NULL
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
                    """
                )
                db.commit()
            finally:
                db.close()

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
                    "(id,weakness,location,why_it_matters,proposed_fix,fix_confidence,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        weakness_id,
                        self._enc(clean, 600),
                        self._enc(location, 300),
                        self._enc(why_it_matters),
                        self._enc(proposed_fix),
                        _clamp(fix_confidence),
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
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
        return {
            "cycles_total": cycles_total,
            "cycles_by_decision": decision_counts,
            "weaknesses_by_status": weakness_counts,
            "recent_cycles": self.cycles(5),
            "audit_chain_intact": self.verify_audit_chain()["intact"],
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
            "YOUR OWN SOURCE CODE (review this to find a weakness):\n"
            + source
            + "\n\nIdentify one real weakness. If you cannot find one, return an empty weakness."
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
        changed = fix_result.get("files", [])
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
            )

        # --- Step 2: propose and verify a fix ---
        try:
            from . import coding_engine
        except Exception as error:  # noqa: BLE001
            return self._finish_cycle(
                weakness, "failed", [], "", False, "", "kept",
                f"Coding engine unavailable: {str(error)[:200]}", "", "",
            )

        task = (
            f"Fix this weakness in BabyMind's own source:\n\n"
            f"Weakness: {weakness['weakness']}\n"
            f"Location: {weakness.get('location', 'unknown')}\n"
            f"Why it matters: {weakness.get('why_it_matters', '')}\n"
            f"Proposed fix: {weakness.get('proposed_fix', '')}\n\n"
            "Make the smallest coherent change that addresses the weakness."
        )

        # Record a prediction: the model's stated confidence that the fix will pass.
        prediction_id = ""
        prediction_outcome = ""
        if self.selfmodel is not None:
            prediction_id = self.selfmodel.record_prediction(
                f"Fix for '{weakness['weakness'][:80]}' will pass verification",
                weakness.get("fix_confidence", 0.5),
            )

        try:
            fix_result = coding_engine.develop(provider, task, attempts=2)
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
                results.append(self.run_cycle(provider))
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
                "Each cycle identified a weakness, proposed and verified a fix (compile + "
                "test suite in the sandbox), evaluated whether the fix actually addressed "
                "the weakness, and kept it only if both verification and the behavioral "
                "evaluation passed. Weakness identification and behavioral evaluation are "
                "model-generated; verification is real."
            ),
        }

    def status(self) -> dict[str, Any]:
        try:
            dev_root = str(selfdev.dev_root())
            dev_available = True
        except Exception:  # noqa: BLE001
            dev_root = ""
            dev_available = False
        return {
            "dev_root": dev_root,
            "dev_available": dev_available,
            "selfdev_enabled": selfdev.selfdev_enabled() if dev_available else False,
            "learning": self.learning_store.report(),
        }
