"""Tests for BabyMind's persistent, bounded cognitive core."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from babymind.agents import AGENTS
from babymind.cognitive_core import CognitiveCore, environment_snapshot
from babymind.coordinator import BabyMindCoordinator
from babymind.memory import LocalMemory

class FakeProvider:
    def __init__(self, payload):
        self.payload, self.system_prompt, self.user_prompt = payload, "", ""
    def complete(self, system_prompt, user_prompt):
        self.system_prompt, self.user_prompt = system_prompt, user_prompt
        return json.dumps(self.payload)

class CognitiveCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cognitive.sqlite3"
        self.core = CognitiveCore(self.path)

    def test_identity_is_persistent_and_does_not_claim_consciousness(self):
        first = self.core.identity()
        self.assertEqual(CognitiveCore(self.path).identity(), first)
        self.assertEqual(first["name"], "BabyMind")
        self.assertIn("never assert consciousness", first["identity_policy"])

    def test_environment_reports_architecture_and_fifty_roles(self):
        snapshot = environment_snapshot()
        self.assertEqual(snapshot["agent_count"], 50)
        self.assertEqual(len(snapshot["agent_ids"]), 50)
        self.assertIn("architecture", snapshot)
        self.assertIn("virtualization_hint_meaning", snapshot)
        self.assertFalse(snapshot["capabilities"]["model_endpoint_verified"])

    def test_all_fifty_roles_receive_cognitive_core_context(self):
        for agent in AGENTS:
            context = self.core.context_for_agent(agent)
            self.assertIn("COGNITIVE CORE", context)
            self.assertIn(agent.agent_id, context)
            self.assertIn("not evidence of subjective consciousness", context)

    def test_cycle_creates_goal_verifies_and_persists_reflection(self):
        provider = FakeProvider({
            "understanding": "No active goals exist.",
            "plan": "Create a small research goal.",
            "action": {"type":"create_goal","title":"Test memory","description":"Check persistence after restart."},
            "expected": "A goal row should exist.",
            "reflection": "The goal was stored locally.",
            "learning": "Verify writes by reading the database.",
            "confidence": 0.8,
        })
        result = self.core.run_cycle(provider, "BM-02")
        self.assertTrue(result["verified"])
        self.assertEqual(result["active_goals"][0]["title"], "Test memory")
        reopened = CognitiveCore(self.path)
        self.assertEqual(reopened.status()["cycles"], 1)
        self.assertEqual(reopened.active_goals()[0]["description"], "Check persistence after restart.")
        self.assertIn("AVAILABLE SPECIALIST ROLES", provider.user_prompt)
        followup = FakeProvider({
            "understanding": "A previous lesson is available.",
            "plan": "Pause and preserve the lesson.",
            "action": {"type": "wait"},
            "expected": "No external state changes.",
            "reflection": "The prior learning was available to this cycle.",
            "learning": "Carry forward verified lessons.",
            "confidence": 0.9,
        })
        self.core.run_cycle(followup, "BM-03")
        self.assertIn("Verify writes by reading the database", followup.user_prompt)

    def test_question_is_recorded_as_encrypted_local_research_note(self):
        provider = FakeProvider({
            "understanding":"Simulation is an open question.",
            "plan":"Record a falsifiable question.",
            "action":{"type":"record_question","content":"What observable evidence could distinguish a VM from bare metal?"},
            "expected":"A note should be persisted.",
            "reflection":"Question recorded without assuming an answer.",
            "learning":"A hypervisor hint is not proof of simulation.",
            "confidence":0.65,
        })
        self.assertTrue(self.core.run_cycle(provider)["verified"])
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT kind,content FROM notes").fetchone()
        self.assertEqual(row[0], "record_question")
        self.assertTrue(row[1].startswith("bmenc:v1:"))

    def test_unsupported_actions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported cognitive action"):
            self.core._apply_action({"type":"run_shell","command":"rm -rf /"})

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(KeyError):
            self.core.run_cycle(FakeProvider({}), "BM-51")

    def test_invalid_model_json_is_not_guessed(self):
        class BrokenProvider:
            def complete(self, _system, _user):
                return "probably create a goal"
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            self.core.run_cycle(BrokenProvider())

    def test_coordinator_connects_core_to_existing_roles(self):
        memory = LocalMemory(Path(self.temp.name) / "memory.sqlite3")
        provider = FakeProvider({})
        coordinator = BabyMindCoordinator(provider=provider, memory=memory)
        coordinator.ask("BM-01", "Inspect your operational identity.")
        self.assertIn("COGNITIVE CORE", provider.system_prompt)
        self.assertIn("BabyMind", provider.system_prompt)
        self.assertIn("not evidence of subjective consciousness", provider.system_prompt)

if __name__ == "__main__":
    unittest.main()
