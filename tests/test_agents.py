"""Tests for the fixed 50-agent registry and runtime."""

import unittest

from babymind.agents import AGENTS, AgentSpec, validate_registry
from babymind.runtime import BabyMindRuntime


class AgentRegistryTests(unittest.TestCase):
    def test_exactly_50_agents(self) -> None:
        self.assertEqual(len(AGENTS), 50)
        validate_registry()

    def test_ids_are_contiguous_and_unique(self) -> None:
        ids = [agent.agent_id for agent in AGENTS]
        self.assertEqual(ids, [f"BM-{number:02d}" for number in range(1, 51)])
        self.assertEqual(len(ids), len(set(ids)))

    def test_registry_rejects_wrong_count(self) -> None:
        with self.assertRaises(ValueError):
            validate_registry(AGENTS[:-1])

    def test_registry_rejects_duplicate_ids(self) -> None:
        duplicate = AgentSpec("BM-01", "Duplicate", "test", "invalid")
        with self.assertRaises(ValueError):
            validate_registry((duplicate,) + AGENTS[1:])

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
