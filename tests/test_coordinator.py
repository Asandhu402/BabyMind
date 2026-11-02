"""Tests for the unified coordinator, local memory, and provider errors."""

import tempfile
import unittest
from pathlib import Path

from babymind.coordinator import BabyMindCoordinator
from babymind.memory import LocalMemory
from babymind.providers import LMStudioProvider, ProviderError


class FakeProvider:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""
        self.system_prompts = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.system_prompts.append(system_prompt)
        return "A tested response."


class CoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.memory = LocalMemory(Path(self.temp_dir.name) / "memory.sqlite3")
        self.provider = FakeProvider()
        self.coordinator = BabyMindCoordinator(
            provider=self.provider, memory=self.memory
        )

    def test_one_provider_serves_different_agent_roles(self) -> None:
        first = self.coordinator.ask("BM-01", "Coordinate this")
        first_prompt = self.provider.system_prompt
        second = self.coordinator.ask("BM-02", "Research this")
        second_prompt = self.provider.system_prompt
        self.assertEqual(first.response, "A tested response.")
        self.assertIn("Coordinator", first_prompt)
        self.assertEqual(second.agent_id, "BM-02")
        self.assertIn("Researcher", second_prompt)

    def test_memory_is_opt_in_for_writing_and_reading(self) -> None:
        self.coordinator.ask("BM-01", "Private task", remember=True)
        self.assertEqual(len(self.memory.recent()), 1)
        result = self.coordinator.ask("BM-02", "Follow-up", use_memory=True)
        self.assertEqual(result.memories_used, 1)
        self.assertIn("Private task", self.provider.system_prompt)

    def test_memory_is_not_used_by_default(self) -> None:
        self.memory.remember("BM-01", "Old task", "Old response")
        result = self.coordinator.ask("BM-02", "New task")
        self.assertEqual(result.memories_used, 0)
        self.assertNotIn("Old task", self.provider.system_prompt)

    def test_memory_can_be_cleared(self) -> None:
        self.memory.remember("BM-01", "Task", "Response")
        self.assertEqual(self.memory.clear(), 1)
        self.assertEqual(self.memory.recent(), [])

    def test_provider_requires_loaded_model_when_model_not_set(self) -> None:
        provider = LMStudioProvider(base_url="http://127.0.0.1:1/v1", timeout=1)
        with self.assertRaises(ProviderError):
            provider.complete("system", "task")


if __name__ == "__main__":
    unittest.main()
