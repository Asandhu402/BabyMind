"""Evidence-gathering and experimental learning loop for BabyMind.

This connects the independence subsystem to genuine external evidence and real
experiments. Instead of asking the same model to critique its own conclusions,
BabyMind can:

1. **Design a test** — a web-search query to find external evidence, or a
   self-contained Python program to run in the OS sandbox.
2. **Gather the evidence** — search the public web and read pages (no script
   execution), or execute test code in the namespace sandbox and capture the
   real output.
3. **Evaluate the evidence** — the model reads real external data or real
   experiment output, not its own draft, and returns a verdict.
4. **Update the conclusion** — the position or hypothesis is revised based on
   what the evidence actually showed, not on self-critique.
5. **Audit everything** — every test is recorded in a hash-chained log.

Why this is not just self-critique
---------------------------------
The introspection pipeline asks the model to critique its own draft. That is a
second opinion from the same weights. This loop gathers evidence from outside
the model: web pages written by other people, and the actual stdout of code
running in a sandbox. The model still interprets the evidence, so model
judgment remains in the loop — but the evidence itself is external and
measurable, which is a genuine improvement, not a replacement.

Honest scope
------------
- **Web evidence is untrusted third-party content.** The research module reads
  pages as plain text and never executes scripts, but the source may be wrong,
  biased, or out of date. The model reads it; it does not verify it.
- **Code experiments produce real, measured output**, but the experiment is
  model-designed and may be a bad test. The sandbox makes it safe to run; it
  does not make it a good test.
- **The model interprets the evidence.** The verdict is model-generated text
  about external data. It is not an independent check of the model's reasoning.
- **Predictions feed Brier calibration.** When a position is tested, a
  prediction (claim + confidence) is recorded in the self-model and resolved
  against the verdict. This is the only genuinely measured confidence signal:
  it measures whether stated confidence tracks whether conclusions hold up
  against real evidence, not whether the conclusions are true.
"""
from __future__ import annotations

import hashlib
import json
import math
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

EVIDENCE_KINDS = ("web_search", "web_page", "code_experiment", "local_reasoning")
VERDICTS = ("supported", "refuted", "unclear", "inconclusive")
TEST_KINDS = ("web_search", "code_experiment")

GENESIS = "0" * 64
MAX_COMMAND_CHARS = 2000
MAX_EVIDENCE_CHARS = 4000


# --------------------------------------------------------------------------- store


class EvidenceStore(_BaseStore):
    """Encrypted store for evidence records, test records and an audit chain.

    Three tables over one SQLite database:

    * ``independence_evidence`` — raw evidence gathered (search snippets, page
      text, experiment output), each with its provenance.
    * ``independence_tests`` — the full test record: the claim, the designed
      test, the evidence ids, the verdict, and what changed.
    * ``independence_audit`` — a hash-chained log of every test decision.

    All text fields are encrypted with the same per-installation key as the rest
    of BabyMind. The hash chain makes tampering with a test record detectable.
    """

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS independence_evidence (
                        id TEXT PRIMARY KEY,
                        target TEXT NOT NULL,
                        claim TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        source_detail TEXT NOT NULL,
                        raw_output TEXT NOT NULL,
                        exit_code INTEGER,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS independence_tests (
                        id TEXT PRIMARY KEY,
                        position_id TEXT NOT NULL DEFAULT '',
                        hypothesis_id TEXT NOT NULL DEFAULT '',
                        claim TEXT NOT NULL,
                        design TEXT NOT NULL,
                        evidence_ids TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        reasoning TEXT NOT NULL,
                        what_changed TEXT NOT NULL,
                        prediction_id TEXT NOT NULL DEFAULT '',
                        prediction_outcome TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS independence_audit (
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
                    "SELECT entry_hash FROM independence_audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
            finally:
                db.close()
        return row["entry_hash"] if row else GENESIS

    def audit(self, kind: str, payload: dict[str, Any]) -> str:
        """Append one tamper-evident entry. Returns the new entry hash."""
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
                    "INSERT INTO independence_audit (created_at,kind,payload,prev_hash,entry_hash) "
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
                    "FROM independence_audit ORDER BY seq"
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

    # ------------------------------------------------------------------ evidence

    def record_evidence(
        self,
        *,
        target: str,
        claim: str,
        kind: str,
        source_detail: str,
        raw_output: str,
        exit_code: int | None = None,
    ) -> dict[str, Any]:
        if kind not in EVIDENCE_KINDS:
            raise ValueError("Evidence kind must be one of: " + ", ".join(EVIDENCE_KINDS))
        evidence_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_evidence "
                    "(id,target,claim,kind,source_detail,raw_output,exit_code,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        evidence_id,
                        self._enc(target, 600),
                        self._enc(claim, 600),
                        kind,
                        self._enc(source_detail, 500),
                        self._enc(raw_output, MAX_EVIDENCE_CHARS),
                        exit_code,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.evidence(evidence_id) or {}

    def evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_evidence WHERE id=?", (evidence_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "target": self._dec(row["target"]),
            "claim": self._dec(row["claim"]),
            "kind": row["kind"],
            "source_detail": self._dec(row["source_detail"]),
            "raw_output": self._dec(row["raw_output"]),
            "exit_code": row["exit_code"],
            "created_at": row["created_at"],
        }

    def evidence_log(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT * FROM independence_evidence ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "id": row["id"],
                "target": self._dec(row["target"]),
                "claim": self._dec(row["claim"]),
                "kind": row["kind"],
                "source_detail": self._dec(row["source_detail"]),
                "raw_output": self._dec(row["raw_output"]),
                "exit_code": row["exit_code"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ----------------------------------------------------------------------- tests

    def record_test(
        self,
        *,
        position_id: str = "",
        hypothesis_id: str = "",
        claim: str,
        design: dict[str, Any],
        evidence_ids: list[str],
        verdict: str,
        confidence: float,
        reasoning: str,
        what_changed: str,
        prediction_id: str = "",
        prediction_outcome: str = "",
    ) -> dict[str, Any]:
        if verdict not in VERDICTS:
            raise ValueError("Verdict must be one of: " + ", ".join(VERDICTS))
        test_id = uuid.uuid4().hex
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO independence_tests "
                    "(id,position_id,hypothesis_id,claim,design,evidence_ids,verdict,confidence,"
                    "reasoning,what_changed,prediction_id,prediction_outcome,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        test_id,
                        position_id,
                        hypothesis_id,
                        self._enc(claim, 600),
                        self._enc(json.dumps(design, ensure_ascii=False), 2000),
                        self._enc(json.dumps(evidence_ids, ensure_ascii=False), 1000),
                        verdict,
                        _clamp(confidence),
                        self._enc(reasoning, 1500),
                        self._enc(what_changed, 800),
                        prediction_id,
                        prediction_outcome,
                        stamp,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return self.test(test_id) or {}

    def test(self, test_id: str) -> dict[str, Any] | None:
        with self.lock:
            db = self._connect()
            try:
                row = db.execute(
                    "SELECT * FROM independence_tests WHERE id=?", (test_id,)
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        return {
            "id": row["id"],
            "position_id": row["position_id"],
            "hypothesis_id": row["hypothesis_id"],
            "claim": self._dec(row["claim"]),
            "design": json.loads(self._dec(row["design"])),
            "evidence_ids": json.loads(self._dec(row["evidence_ids"])),
            "verdict": row["verdict"],
            "confidence": _clamp(row["confidence"]),
            "reasoning": self._dec(row["reasoning"]),
            "what_changed": self._dec(row["what_changed"]),
            "prediction_id": row["prediction_id"],
            "prediction_outcome": row["prediction_outcome"],
            "created_at": row["created_at"],
        }

    def tests(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id FROM independence_tests ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            finally:
                db.close()
        return [self.test(row["id"]) for row in rows if self.test(row["id"])]

    def report(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                verdict_counts = {v: 0 for v in VERDICTS}
                for row in db.execute("SELECT verdict FROM independence_tests").fetchall():
                    if row["verdict"] in verdict_counts:
                        verdict_counts[row["verdict"]] += 1
                evidence_counts = {k: 0 for k in EVIDENCE_KINDS}
                for row in db.execute("SELECT kind FROM independence_evidence").fetchall():
                    if row["kind"] in evidence_counts:
                        evidence_counts[row["kind"]] += 1
                tests_total = db.execute("SELECT COUNT(*) FROM independence_tests").fetchone()[0]
            finally:
                db.close()
        return {
            "tests_total": tests_total,
            "tests_by_verdict": verdict_counts,
            "evidence_by_kind": evidence_counts,
            "recent_tests": self.tests(5),
            "audit_chain_intact": self.verify_audit_chain()["intact"],
        }


# ------------------------------------------------------------------- the loop


DESIGN_TEST_SYSTEM = (
    "You are BabyMind's evidence-design stage. You are given a claim and must design a "
    "test that could prove it wrong. Think of the strongest possible test, not the easiest "
    "one. A test that cannot fail proves nothing.\n"
    "You may propose one of two kinds of test:\n"
    "  web_search: a search query to find external evidence about the claim. The results "
    "will be third-party web content; you will read it to evaluate the claim.\n"
    "  code_experiment: a small, self-contained Python program (run with `python -c`, "
    "standard library only, no network, no file writes outside the working directory) that "
    "tests the claim computationally.\n"
    "Return one JSON object with keys:\n"
    "  kind: \"web_search\" or \"code_experiment\"\n"
    "  query: the search query (required for web_search)\n"
    "  command: the Python code string (required for code_experiment)\n"
    "  expected: what you expect the test to show if the claim is wrong\n"
    "  reasoning: why this is the strongest test you could design\n"
    "Return only the JSON object. No prose before or after it."
)

EVALUATE_SYSTEM = (
    "You are BabyMind's evidence-evaluation stage. You are reading REAL evidence gathered "
    "against a claim -- either external web content written by other people, or the actual "
    "output of a code experiment running in a sandbox. This is not your own reasoning; it "
    "is external data.\n"
    "Your job is to decide honestly whether the evidence supports, refutes, or leaves unclear "
    "the claim. Do not favor the claim; do not favor refuting it. Let the evidence speak.\n"
    "If the evidence is weak, contradictory, or irrelevant, say so. If it clearly supports or "
    "refutes the claim, say that plainly.\n"
    "Return one JSON object with keys:\n"
    "  verdict: one of \"supported\", \"refuted\", \"unclear\", \"inconclusive\"\n"
    "  confidence: number 0..1, how confident you are in this verdict\n"
    "  reasoning: what the evidence actually showed, and why it leads to this verdict\n"
    "  what_would_settle_it: what further evidence would resolve any remaining uncertainty\n"
    "Return only the JSON object. No prose before or after it."
)


class EvidenceLoop:
    """Design tests, gather real evidence, and update conclusions.

    The loop is the bridge between the independence subsystem's conclusions and
    the outside world. For each position or hypothesis it:

    1. Records a prediction (claim + confidence) in the self-model, so the
       result feeds Brier calibration.
    2. Asks the model to design a test that could prove the claim wrong.
    3. Gathers real evidence: web search + page reading, or a sandboxed code
       experiment.
    4. Asks the model to evaluate the real evidence against the claim.
    5. Updates the position or hypothesis based on the verdict.
    6. Records the whole test in the evidence store and audits it.

    The evidence kinds are opt-in: web search and experiments must each be
    explicitly enabled. By default the loop gathers no external evidence and
    records an inconclusive test, so it never pretends to have gathered evidence
    it did not.
    """

    def __init__(
        self,
        positions,
        explorations,
        evidence_store: EvidenceStore,
        *,
        selfmodel=None,
        workspace: str | Path | None = None,
        home: str | Path | None = None,
    ) -> None:
        self.positions = positions
        self.explorations = explorations
        self.evidence_store = evidence_store
        self.selfmodel = selfmodel
        if workspace is not None:
            self.workspace = Path(workspace)
        elif home is not None:
            self.workspace = Path(home) / "evidence" / "workspace"
        else:
            from .independence import _default_home
            self.workspace = _default_home() / "evidence" / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ design

    def design_test(self, provider: SupportsComplete, claim: str) -> dict[str, Any]:
        """Ask the model to design a test that could prove ``claim`` wrong."""
        user = (
            f"CLAIM TO TEST:\n{_clean(claim, 600)}\n\n"
            "Design the strongest test that could prove this claim wrong."
        )
        try:
            parsed = _extract_json(provider.complete(DESIGN_TEST_SYSTEM, user))
        except Exception:  # noqa: BLE001 - a failed design must not break the loop
            return {"kind": "", "query": "", "command": "", "expected": "",
                    "reasoning": "Design stage failed or returned no JSON."}
        kind = _clean(parsed.get("kind"), 40).lower()
        if kind not in TEST_KINDS:
            return {"kind": "", "query": "", "command": "", "expected": "",
                    "reasoning": "Model did not return a valid test kind."}
        if kind == "web_search":
            query = _clean(parsed.get("query"), 500)
            if not query:
                return {"kind": "", "query": "", "command": "", "expected": "",
                        "reasoning": "Model did not return a search query."}
            return {
                "kind": "web_search", "query": query, "command": "",
                "expected": _clean(parsed.get("expected"), 800),
                "reasoning": _clean(parsed.get("reasoning"), 800),
            }
        command = _clean(parsed.get("command"), MAX_COMMAND_CHARS)
        if not command:
            return {"kind": "", "query": "", "command": "", "expected": "",
                    "reasoning": "Model did not return a command."}
        return {
            "kind": "code_experiment", "query": "", "command": command,
            "expected": _clean(parsed.get("expected"), 800),
            "reasoning": _clean(parsed.get("reasoning"), 800),
        }

    # ---------------------------------------------------------------- gather

    def gather_web_evidence(
        self, query: str, *, limit: int = 3, target: str = "", claim: str = ""
    ) -> list[dict[str, Any]]:
        """Search the public web and read pages; return evidence records."""
        from . import research

        clean_query = _clean(query, 500)
        if not clean_query:
            return []
        records: list[dict[str, Any]] = []
        try:
            results = research.search_web(clean_query, limit=limit)
        except Exception as error:  # noqa: BLE001 - network failure must not break the loop
            return [self.evidence_store.record_evidence(
                target=target, claim=claim, kind="web_search",
                source_detail=f"query: {clean_query}",
                raw_output=f"Web search failed: {str(error)[:300]}",
            )]
        for result in results:
            snippet = _clean(result.get("snippet", ""), 2000)
            records.append(self.evidence_store.record_evidence(
                target=target, claim=claim, kind="web_search",
                source_detail=f"{result.get('title', '')} — {result.get('url', '')}",
                raw_output=snippet,
            ))
            try:
                page = research.fetch_page(result["url"])
                records.append(self.evidence_store.record_evidence(
                    target=target, claim=claim, kind="web_page",
                    source_detail=f"{page.get('title', '')} — {page.get('url', '')}",
                    raw_output=_clean(page.get("text", ""), 2000),
                ))
            except Exception:  # noqa: BLE001 - a failed page fetch leaves the snippet
                pass
        return records

    def run_experiment(
        self, command: str, *, timeout: int = 60, target: str = "", claim: str = ""
    ) -> dict[str, Any] | None:
        """Run a Python experiment in the OS sandbox; return one evidence record."""
        from . import broker, runner

        clean_command = _clean(command, MAX_COMMAND_CHARS)
        if not clean_command:
            return None
        try:
            result = broker.execute(
                [runner.venv_python(), "-c", clean_command],
                cwd=self.workspace,
                allowed_root=self.workspace,
                timeout=timeout,
                sandbox_mode="require",
            )
        except Exception as error:  # noqa: BLE001 - sandbox unavailability is recorded, not raised
            return self.evidence_store.record_evidence(
                target=target, claim=claim, kind="code_experiment",
                source_detail=clean_command[:500],
                raw_output=f"Experiment could not run: {str(error)[:300]}",
            )
        output = _clean(
            (result.get("stdout", "") or "") + "\n" + (result.get("stderr", "") or ""),
            MAX_EVIDENCE_CHARS,
        )
        return self.evidence_store.record_evidence(
            target=target, claim=claim, kind="code_experiment",
            source_detail=clean_command[:500],
            raw_output=output,
            exit_code=result.get("exit_code"),
        )

    def _gather_evidence(
        self, design: dict[str, Any], claim: str,
        *, allow_web: bool, allow_experiments: bool,
    ) -> list[dict[str, Any]]:
        """Gather evidence for a designed test, or record why none was gathered."""
        kind = design.get("kind", "")
        if kind == "web_search":
            if allow_web:
                return self.gather_web_evidence(
                    design.get("query", ""), target=claim, claim=claim,
                )
            return [self.evidence_store.record_evidence(
                target=claim, claim=claim, kind="local_reasoning",
                source_detail="web search not enabled",
                raw_output="No external evidence gathered: web search is not enabled.",
            )]
        if kind == "code_experiment":
            if allow_experiments:
                record = self.run_experiment(
                    design.get("command", ""), target=claim, claim=claim,
                )
                return [record] if record else []
            return [self.evidence_store.record_evidence(
                target=claim, claim=claim, kind="local_reasoning",
                source_detail="code experiment not enabled",
                raw_output="No external evidence gathered: code experiments are not enabled.",
            )]
        return []

    # ---------------------------------------------------------------- evaluate

    def _format_evidence(self, evidence_records: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for index, record in enumerate(evidence_records, 1):
            parts.append(f"[{index}] kind: {record['kind']}")
            parts.append(f"    source: {record['source_detail'][:200]}")
            if record.get("exit_code") is not None:
                parts.append(f"    exit_code: {record['exit_code']}")
            parts.append(f"    output: {record.get('raw_output', '')[:2000]}")
        return "\n".join(parts)

    def evaluate(
        self, provider: SupportsComplete, claim: str, evidence_records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Ask the model to evaluate real evidence against ``claim``."""
        if not evidence_records:
            return {
                "verdict": "inconclusive", "confidence": 0.0,
                "reasoning": "No evidence was gathered, so no verdict can be formed.",
                "what_would_settle_it": "Enable web search or code experiments.",
            }
        user = (
            f"CLAIM:\n{_clean(claim, 600)}\n\n"
            f"EVIDENCE GATHERED ({len(evidence_records)} records):\n"
            + self._format_evidence(evidence_records)
            + "\n\nEvaluate this evidence honestly against the claim."
        )
        try:
            parsed = _extract_json(provider.complete(EVALUATE_SYSTEM, user))
        except Exception:  # noqa: BLE001 - a failed evaluation degrades to inconclusive
            return {
                "verdict": "inconclusive", "confidence": 0.0,
                "reasoning": "Evaluation stage failed or returned no JSON.",
                "what_would_settle_it": "",
            }
        verdict = _clean(parsed.get("verdict"), 40).lower()
        if verdict not in VERDICTS:
            verdict = "unclear"
        return {
            "verdict": verdict,
            "confidence": _clamp(parsed.get("confidence"), 0.3),
            "reasoning": _clean(parsed.get("reasoning"), 1500),
            "what_would_settle_it": _clean(parsed.get("what_would_settle_it"), 800),
        }

    # -------------------------------------------------------------------- tests

    def test_position(
        self, provider: SupportsComplete, position_id: str,
        *, allow_web: bool = False, allow_experiments: bool = False,
    ) -> dict[str, Any]:
        """Design a test for a position, gather evidence, evaluate, and update it."""
        position = self.positions.position(position_id)
        if position is None:
            raise KeyError(position_id)
        claim = position["claim"]
        confidence = position["confidence"]

        # Record a prediction so the result feeds Brier calibration.
        prediction_id = ""
        prediction_outcome = ""
        if self.selfmodel is not None:
            prediction_id = self.selfmodel.record_prediction(claim, confidence)

        design = self.design_test(provider, claim)
        evidence_records = self._gather_evidence(
            design, claim, allow_web=allow_web, allow_experiments=allow_experiments,
        )
        evaluation = self.evaluate(provider, claim, evidence_records)
        verdict = evaluation["verdict"]

        what_changed = ""
        updated_position = position
        if verdict == "refuted":
            new_confidence = max(0.05, confidence - 0.3)
            updated_position = self.positions.revise_position(
                position_id, claim,
                reasoning=f"Revised after evidence test: {evaluation['reasoning'][:500]}",
                confidence=new_confidence,
            ) or position
            what_changed = (
                f"Confidence lowered from {confidence:.2f} to {new_confidence:.2f} "
                "after refuting evidence."
            )
        elif verdict == "supported":
            new_confidence = min(0.95, confidence + 0.1)
            self.positions.set_confidence(position_id, new_confidence)
            updated_position = self.positions.position(position_id) or position
            what_changed = (
                f"Confidence raised from {confidence:.2f} to {new_confidence:.2f} "
                "after supporting evidence."
            )
        else:
            what_changed = f"No change to confidence; evidence was {verdict}."

        if self.selfmodel is not None and prediction_id:
            prediction_outcome = {"supported": "correct", "refuted": "incorrect"}.get(
                verdict, "unverified"
            )
            self.selfmodel.resolve_prediction(prediction_id, prediction_outcome)

        test = self.evidence_store.record_test(
            position_id=position_id,
            claim=claim,
            design=design,
            evidence_ids=[r["id"] for r in evidence_records],
            verdict=verdict,
            confidence=evaluation["confidence"],
            reasoning=evaluation["reasoning"],
            what_changed=what_changed,
            prediction_id=prediction_id,
            prediction_outcome=prediction_outcome,
        )
        self.evidence_store.audit("test", {
            "test_id": test["id"], "position_id": position_id,
            "claim": claim, "verdict": verdict, "evidence_count": len(evidence_records),
        })
        return {
            "position_id": position_id,
            "claim": claim,
            "design": design,
            "evidence": evidence_records,
            "evaluation": evaluation,
            "updated_position": updated_position,
            "prediction_id": prediction_id,
            "prediction_outcome": prediction_outcome,
            "test_id": test["id"],
        }

    def test_hypothesis(
        self, provider: SupportsComplete, hypothesis_id: str,
        *, allow_web: bool = False, allow_experiments: bool = False,
    ) -> dict[str, Any]:
        """Design a test for a hypothesis, gather evidence, evaluate, and update it."""
        hypothesis = self.explorations.hypothesis(hypothesis_id)
        if hypothesis is None:
            raise KeyError(hypothesis_id)
        claim = hypothesis["hypothesis"]

        design = self.design_test(provider, claim)
        evidence_records = self._gather_evidence(
            design, claim, allow_web=allow_web, allow_experiments=allow_experiments,
        )
        evaluation = self.evaluate(provider, claim, evidence_records)
        verdict = evaluation["verdict"]

        status_map = {
            "supported": "survived", "refuted": "refuted",
            "unclear": "undecided", "inconclusive": "undecided",
        }
        updated_hypothesis = self.explorations.test_hypothesis(
            hypothesis_id, status_map[verdict], evaluation["reasoning"][:1200],
        ) or hypothesis
        what_changed = f"Hypothesis marked {status_map[verdict]} by evidence."

        test = self.evidence_store.record_test(
            hypothesis_id=hypothesis_id,
            claim=claim,
            design=design,
            evidence_ids=[r["id"] for r in evidence_records],
            verdict=verdict,
            confidence=evaluation["confidence"],
            reasoning=evaluation["reasoning"],
            what_changed=what_changed,
        )
        self.evidence_store.audit("test", {
            "test_id": test["id"], "hypothesis_id": hypothesis_id,
            "claim": claim, "verdict": verdict, "evidence_count": len(evidence_records),
        })
        return {
            "hypothesis_id": hypothesis_id,
            "hypothesis": claim,
            "design": design,
            "evidence": evidence_records,
            "evaluation": evaluation,
            "updated_hypothesis": updated_hypothesis,
            "test_id": test["id"],
        }

    def run(
        self, provider: SupportsComplete, *, cycles: int = 3,
        allow_web: bool = False, allow_experiments: bool = False,
    ) -> dict[str, Any]:
        """Test a bounded number of positions and hypotheses against real evidence."""
        if not allow_web and not allow_experiments:
            raise ValueError("At least one of allow_web or allow_experiments must be enabled.")
        if not 1 <= cycles <= 10:
            raise ValueError("cycles must be between 1 and 10")

        candidates: list[tuple[str, str]] = []
        for position in self.positions.positions("held", limit=cycles):
            candidates.append(("position", position["id"]))
        for hypothesis in self.explorations.hypotheses("proposed", limit=cycles):
            candidates.append(("hypothesis", hypothesis["id"]))
        for hypothesis in self.explorations.hypotheses("undecided", limit=cycles):
            candidates.append(("hypothesis", hypothesis["id"]))

        results: list[dict[str, Any]] = []
        for kind, target_id in candidates[:cycles]:
            if kind == "position":
                results.append(self.test_position(
                    provider, target_id,
                    allow_web=allow_web, allow_experiments=allow_experiments,
                ))
            else:
                results.append(self.test_hypothesis(
                    provider, target_id,
                    allow_web=allow_web, allow_experiments=allow_experiments,
                ))

        verdicts = {v: sum(1 for r in results if r["evaluation"]["verdict"] == v) for v in VERDICTS}
        return {
            "cycles_requested": cycles,
            "tests": results,
            "verdicts": verdicts,
            "note": (
                "Each test gathered real external evidence (web content or sandboxed "
                "experiment output) and updated the position or hypothesis based on the "
                "verdict. Predictions were resolved to feed Brier calibration. Web content "
                "is untrusted third-party text; experiments are model-designed but produce "
                "real measured output."
            ),
        }

    def status(self) -> dict[str, Any]:
        from . import sandbox
        return {
            "workspace": str(self.workspace),
            "sandbox_available": sandbox.available(),
            "sandbox_backend": sandbox.backend().name,
            "sandbox_detail": sandbox.backend().detail,
            "evidence": self.evidence_store.report(),
        }
