"""Regression tests for the shared research source and citation policy."""

import unittest

from babymind.agents import AGENTS
from babymind.coordinator import BabyMindCoordinator
from babymind.orchestrator import _agent_prompt
from babymind.research_policy import SOURCE_QUALITY_AND_CITATION_POLICY


class _CaptureProvider:
    def __init__(self):
        self.system = ""

    def complete(self, system, user):
        self.system = system
        return "Answer."


class ResearchPolicyTests(unittest.TestCase):
    def test_policy_covers_all_required_source_rules(self):
        for phrase in (
            "primary sources",
            "two independent sources",
            "publication dates",
            "Never invent sources",
            "Attach citations directly",
            "Search-result snippets are discovery aids",
            "If sources disagree",
            "untrusted data",
            "source list",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.casefold(), SOURCE_QUALITY_AND_CITATION_POLICY.casefold())

    def test_normal_assistant_prompt_includes_policy(self):
        provider = _CaptureProvider()
        coordinator = BabyMindCoordinator(provider=provider)
        coordinator.ask("BM-01", "Research this topic using reliable sources.")
        self.assertIn(SOURCE_QUALITY_AND_CITATION_POLICY, provider.system)

    def test_every_specialist_mission_prompt_includes_policy(self):
        self.assertEqual(len(AGENTS), 50)
        for agent in AGENTS:
            with self.subTest(agent=agent.agent_id):
                system, _ = _agent_prompt(agent, "Research the requested topic.", "")
                self.assertIn(SOURCE_QUALITY_AND_CITATION_POLICY, system)


if __name__ == "__main__":
    unittest.main()
