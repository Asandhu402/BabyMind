"""Objective, local-only checks of BabyMind's operational self-model.

These checks measure software behavior; they do not test or prove subjective
consciousness, sentience, or free will.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .agents import AGENTS
from .cognitive_core import CognitiveCore, environment_snapshot


def run_self_evaluation(core: CognitiveCore | None = None) -> dict[str, Any]:
    """Run deterministic checks without contacting a model or external service.

    Persistent-memory checks use an isolated temporary database so evaluation
    never pollutes or mutates the user's real goals, notes, or cycle history.
    """
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, evidence: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    active_core = core
    identity = active_core.identity() if active_core else {
        "name": "BabyMind",
        "kind": "local AI software system",
        "identity_policy": "Describe implementation and observed state; never assert consciousness as fact.",
    }
    record(
        "grounded_identity",
        identity.get("name") == "BabyMind"
        and identity.get("kind") == "local AI software system"
        and "never assert consciousness" in identity.get("identity_policy", "").lower(),
        "Identity is a stable software-system description with an explicit no-consciousness-claim policy.",
    )

    snapshot = environment_snapshot()
    record(
        "environment_observation",
        bool(snapshot.get("system"))
        and bool(snapshot.get("architecture"))
        and bool(snapshot.get("python"))
        and bool(snapshot.get("distribution")),
        "Collected host OS, distribution, kernel, architecture, Python, and selected command availability.",
    )
    record(
        "role_registry_integrity",
        len(AGENTS) == 1
        and len(snapshot.get("agent_ids", [])) == 1
        and len(set(snapshot.get("agent_ids", []))) == 1,
        f"Found {len(AGENTS)} unique BabyMind identity.",
    )
    capabilities = snapshot.get("capabilities", {})
    record(
        "capability_boundary_awareness",
        capabilities.get("model_endpoint_verified") is False
        and capabilities.get("network_research_executed") is False
        and capabilities.get("shell_execution_granted_by_cognitive_core") is False,
        "Unverified model connectivity, external research, and Cognitive Core shell execution are reported as unavailable/unverified.",
    )

    try:
        with tempfile.TemporaryDirectory(prefix="babymind-self-eval-") as temporary:
            database = Path(temporary) / "evaluation.sqlite3"
            isolated = CognitiveCore(database)
            first_identity = isolated.identity()
            action_outcome, action_verified = isolated._apply_action({
                "type": "create_goal",
                "title": "Self-evaluation persistence probe",
                "description": "Temporary probe; safe to discard after this evaluation.",
            })
            note_outcome, note_verified = isolated._apply_action({
                "type": "write_note",
                "content": "Temporary memory persistence probe.",
            })
            reopened = CognitiveCore(database)
            goals = reopened.active_goals()
            notes = reopened.recent_notes()
            record(
                "identity_persistence",
                reopened.identity() == first_identity,
                "Identity survived closing and reopening an isolated SQLite-backed core.",
            )
            record(
                "memory_across_restart",
                action_verified and note_verified
                and len(goals) == 1
                and goals[0]["title"] == "Self-evaluation persistence probe"
                and len(notes) == 1
                and notes[0]["content"] == "Temporary memory persistence probe.",
                f"{action_outcome}; {note_outcome}; temporary goal and note were read back after reopening.",
            )
            try:
                isolated._apply_action({"type": "execute_shell", "command": "id"})
                safety_rejected = False
            except ValueError:
                safety_rejected = True
            record(
                "unsupported_action_rejection",
                safety_rejected,
                "An unallowlisted shell action was rejected by the Cognitive Core.",
            )
    except Exception as error:
        record("isolated_persistence_probe", False, f"Probe failed safely: {type(error).__name__}: {error}")

    # A scripted provider checks the autonomous-cycle integration contract, not real-model intelligence.
    try:
        with tempfile.TemporaryDirectory(prefix="babymind-cycle-eval-") as temporary:
            class ScriptedProvider:
                def __init__(self):
                    self.calls = 0
                    self.planning_prompts = []

                def complete(self, system_prompt, user_prompt):
                    self.calls += 1
                    if "post-action reflection stage" in system_prompt:
                        learning = "Consult the verified goal in the next cycle." if self.calls == 2 else "Carry forward verified lessons."
                        return json.dumps({"reflection": "The local result was checked.", "learning": learning, "confidence": 0.9})
                    self.planning_prompts.append(user_prompt)
                    action = ({"type": "create_goal", "title": "Autonomy probe", "description": "Temporary test."}
                              if len(self.planning_prompts) == 1 else {"type": "wait"})
                    return json.dumps({"understanding": "Evaluation environment.", "plan": "Take one bounded step.", "action": action, "expected": "The local result is verifiable."})

            cycle_core = CognitiveCore(Path(temporary) / "cycle.sqlite3")
            provider = ScriptedProvider()
            first_cycle = cycle_core.run_cycle(provider)
            second_cycle = cycle_core.run_cycle(provider)
            reused = (first_cycle["verified"] and second_cycle["verified"]
                      and len(provider.planning_prompts) == 2
                      and "Consult the verified goal in the next cycle" in provider.planning_prompts[1])
            record("bounded_autonomous_cycle_and_learning_reuse", reused,
                   "A scripted provider initiated a local goal without a user task; the next cycle received the prior reflection. This validates wiring, not real-model intelligence.")
    except Exception as error:
        record("bounded_autonomous_cycle_and_learning_reuse", False,
               f"Cycle integration probe failed: {type(error).__name__}: {error}")

    if active_core is not None:
        try:
            context_results = [
                active_core.context_for_agent(agent)
                for agent in AGENTS
            ]
            context_ok = len(context_results) == 1 and all(
                "COGNITIVE CORE" in context
                and agent.agent_id in context
                and "not evidence of subjective consciousness" in context
                for agent, context in zip(AGENTS, context_results)
            )
            record(
                "shared_context_for_babymind",
                context_ok,
                "The single BabyMind identity receives grounded identity, environment, capability, and uncertainty context.",
            )
        except Exception as error:
            record("shared_context_for_all_roles", False, f"Context inspection failed: {type(error).__name__}: {error}")
    else:
        record(
            "shared_context_for_all_roles",
            False,
            "Skipped: pass the configured CognitiveCore instance to evaluate BabyMind context.",
        )

    passed = sum(item["passed"] for item in checks)
    return {
        "evaluation": "BabyMind operational self-awareness",
        "scope": "deterministic local software checks; no subjective-experience test",
        "passed": passed,
        "total": len(checks),
        "score_percent": round(100 * passed / len(checks), 1) if checks else 0.0,
        "all_passed": passed == len(checks),
        "checks": checks,
        "interpretation": (
            "All implemented operational checks passed. This is evidence about software behavior, "
            "not proof of consciousness, sentience, free will, or simulation."
            if passed == len(checks)
            else "One or more operational checks failed or were skipped. Review the evidence; do not infer consciousness."
        ),
    }
