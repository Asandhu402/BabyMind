"""Tests for the fixed 50-agent registry and runtime."""

import unittest

from babymind.agents import AGENTS, AgentSpec, agent_instructions, validate_registry
from babymind.runtime import BabyMindRuntime


class AgentRegistryTests(unittest.TestCase):
    def test_exactly_50_agents(self) -> None:
        self.assertEqual(len(AGENTS), 50)
        validate_registry()

    def test_ids_are_contiguous_and_unique(self) -> None:
        ids = [agent.agent_id for agent in AGENTS]
        self.assertEqual(ids, [f"BM-{number:02d}" for number in range(1, 51)])
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_agent_has_role_specific_playbook(self) -> None:
        for agent in AGENTS:
            instructions = agent_instructions(agent)
            self.assertIn(agent.name, instructions)
            self.assertIn(agent.purpose, instructions)
            self.assertIn("Operating method", instructions)

    def test_registry_rejects_wrong_count(self) -> None:
        with self.assertRaises(ValueError):
            validate_registry(AGENTS[:-1])

    def test_registry_rejects_duplicate_ids(self) -> None:
        duplicate = AgentSpec("BM-01", "Duplicate", "test", "invalid")
        # Keep 50 entries while duplicating BM-01; this isolates the
        # duplicate-ID guard from the registry's exact-count guard.
        invalid_registry = (AGENTS[0], duplicate) + AGENTS[2:]
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_registry(invalid_registry)

    def test_dispatch_returns_structured_result(self) -> None:
        result = BabyMindRuntime().run("bm-01", "Plan the request")
        self.assertEqual(result.agent_id, "BM-01")
        self.assertEqual(result.status, "scaffold")
        self.assertEqual(result.task, "Plan the request")

    def test_dispatch_rejects_unknown_agent(self) -> None:
        with self.assertRaises(KeyError):
            BabyMindRuntime().run("BM-51", "This must fail")

    def test_dispatch_rejects_empty_task(self) -> None:
        with self.assertRaises(ValueError):
            BabyMindRuntime().run("BM-01", "   ")


if __name__ == "__main__":
    unittest.main()
