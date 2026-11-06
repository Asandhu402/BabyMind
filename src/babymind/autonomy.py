"""Bounded autonomous operation with drift detection and explicit action policy.

This controller deliberately delegates reasoning to BabyMind's configured
provider and delegates local state changes to CognitiveCore's strict allowlist.
It never runs arbitrary shell commands, edits source code, browses the network,
or performs external side effects.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .cognitive_core import CognitiveCore, _clean, environment_snapshot

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
            self.core._apply_action({
                "type": "write_note",
                "content": json.dumps(baseline, sort_keys=True, ensure_ascii=False),
                "kind": "environment_baseline",
            })
            # _apply_action classifies write_note; mark the newest matching note
            # as a baseline using the existing notes table's kind field.
            with self.core.lock:
                db = self.core._connect()
                try:
                    row = db.execute(
                        "SELECT id FROM notes WHERE kind='write_note' ORDER BY created_at DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        db.execute("UPDATE notes SET kind='environment_baseline' WHERE id=?", (row["id"],))
                        db.commit()
                finally:
                    db.close()
        return {"snapshot": current, "changed": bool(changes), "changes": changes,
                "baseline_available": prior is not None}

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
                    "content": "Autonomy cycle failure: " + _clean(
                        f"{type(error).__name__}: {error}", 1000
                    ),
                }
                try:
                    self.core._apply_action(failure)
                except Exception:
                    pass
                results.append({
                    "cycle_index": index + 1, "verified": False,
                    "error": f"{type(error).__name__}: {_clean(error, 500)}",
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
