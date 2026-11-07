"""Tests for BabyMind's single-identity runtime."""
import unittest
from babymind.agents import AGENTS, AgentSpec, agent_instructions, validate_registry
from babymind.runtime import BabyMindRuntime


class AgentRegistryTests(unittest.TestCase):
    def test_only_one_babymind_identity_exists(self):
        self.assertEqual(len(AGENTS), 1)
        self.assertEqual(AGENTS[0].agent_id, "BM-01")
        self.assertEqual(AGENTS[0].name, "BabyMind")
        validate_registry()

    def test_identity_has_grounded_instructions(self):
        instructions = agent_instructions(AGENTS[0])
        self.assertIn("BabyMind", instructions)
        self.assertIn("one unified AI system", instructions)

    def test_registry_rejects_multiple_identities(self):
        with self.assertRaises(ValueError):
            validate_registry(AGENTS + (AgentSpec("BM-02", "Extra", "test", "invalid"),))

    def test_dispatch_returns_structured_result(self):
        result = BabyMindRuntime().run("bm-01", "Plan the request")
        self.assertEqual(result.agent_id, "BM-01")
        self.assertEqual(result.status, "scaffold")
        self.assertEqual(result.task, "Plan the request")

    def test_dispatch_rejects_unknown_identity(self):
        with self.assertRaises(KeyError):
            BabyMindRuntime().run("BM-02", "This must fail")

    def test_dispatch_rejects_empty_task(self):
        with self.assertRaises(ValueError):
            BabyMindRuntime().run("BM-01", "   ")


if __name__ == "__main__":
    unittest.main()
