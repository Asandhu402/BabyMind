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
        self.assertIn("QUALITY STANDARD", first_prompt)
        self.assertIn("Verify arithmetic", first_prompt)
        self.assertEqual(second.agent_id, "BM-02")
        self.assertIn("Researcher", second_prompt)
        self.assertIn("QUALITY STANDARD", second_prompt)

    def test_document_pipeline_routes_extracted_text_through_shared_coordinator(self) -> None:
        from unittest.mock import patch
        with patch("babymind.integrations.documents.convert_document", return_value="# Local report\\nRevenue increased.") as convert:
            result, extracted_chars = self.coordinator.process_document(
                "BM-02", "report.pdf", "Analyze the report"
            )
        convert.assert_called_once()
        self.assertEqual(result.response, "A tested response.")
        self.assertEqual(extracted_chars, len("# Local report\\nRevenue increased."))
        self.assertIn("Local report", self.provider.user_prompt)
        self.assertIn("untrusted source data", self.provider.user_prompt)

    def test_audio_pipeline_transcribes_then_uses_the_same_model(self) -> None:
        from unittest.mock import patch
        transcript = {"text": "Meeting starts at nine.", "language": "en"}
        with patch("babymind.integrations.speech.transcribe_audio", return_value=transcript):
            result, metadata = self.coordinator.process_audio(
                "BM-01", "meeting.wav", "Extract action items"
            )
        self.assertEqual(result.response, "A tested response.")
        self.assertEqual(metadata, transcript)
        self.assertIn("Meeting starts at nine.", self.provider.user_prompt)

    def test_audio_pipeline_rejects_empty_transcript(self) -> None:
        from unittest.mock import patch
        with patch("babymind.integrations.speech.transcribe_audio", return_value={"text": " "}):
            with self.assertRaises(ValueError):
                self.coordinator.process_audio("BM-01", "silent.wav")

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

    def test_memory_database_stores_ciphertext_and_migrates_plaintext(self) -> None:
        self.memory.remember("BM-01", "Private task", "Private response")
        import sqlite3
        connection = sqlite3.connect(self.memory.database_path)
        try:
            task, response = connection.execute(
                "SELECT task, response FROM memories"
            ).fetchone()
        finally:
            connection.close()
        self.assertNotIn("Private task", task)
        self.assertNotIn("Private response", response)
        self.assertTrue(task.startswith("bmenc:v1:"))
        self.assertEqual(self.memory.recent()[0]["task"], "Private task")

    def test_memory_can_be_cleared(self) -> None:
        self.memory.remember("BM-01", "Task", "Response")
        self.assertEqual(self.memory.clear(), 1)
        self.assertEqual(self.memory.recent(), [])

    def test_provider_requires_loaded_model_when_model_not_set(self) -> None:
        provider = LMStudioProvider(base_url="http://127.0.0.1:1/v1", timeout=1)
        with self.assertRaises(ProviderError):
            provider.complete("system", "task")


    def test_relevant_memory_search_ranks_matching_topics_over_newer_unrelated_notes(self) -> None:
        self.memory.remember("BM-01", "Vancouver Class 1 trucking jobs", "Compare local truck driver wages.")
        self.memory.remember("BM-02", "Punjabi song recording", "Practice vocal takes.")
        results = self.memory.relevant("Find Vancouver Class 1 truck driving work", limit=2)
        self.assertEqual(results[0]["task"], "Vancouver Class 1 trucking jobs")

    def test_relevant_memory_search_falls_back_to_recent_when_no_terms_match(self) -> None:
        self.memory.remember("BM-01", "Earlier private note", "First response.")
        self.memory.remember("BM-02", "Another note", "Second response.")
        results = self.memory.relevant("follow up on that", limit=2)
        self.assertEqual(results[0]["task"], "Another note")

    def test_relevant_memory_search_validates_query_and_limit(self) -> None:
        with self.assertRaises(ValueError):
            self.memory.relevant("")
        with self.assertRaises(ValueError):
            self.memory.relevant("valid query", limit=21)


    def test_voicebox_audio_pipeline_uses_shared_coordinator_and_memory(self) -> None:
        from unittest.mock import patch
        transcript = {"text": "The meeting starts at ten.", "language": "en"}
        with patch("babymind.integrations.voicebox.transcribe_with_voicebox", return_value=transcript):
            result, metadata = self.coordinator.process_voicebox_audio(
                "BM-01", "meeting.wav", "Extract action items", use_memory=True
            )
        self.assertEqual(result.response, "A tested response.")
        self.assertEqual(metadata, transcript)
        self.assertIn("The meeting starts at ten.", self.provider.user_prompt)
        self.assertEqual(result.agent_id, "BM-01")

    def test_knowledge_indexing_requires_explicit_user_approval(self) -> None:
        from unittest.mock import patch
        with patch("babymind.integrations.cognee_memory.index_approved_note") as index:
            with self.assertRaises(PermissionError):
                self.coordinator.index_knowledge_note("private note")
            index.assert_not_called()
            self.coordinator.index_knowledge_note("approved note", user_approved=True)
            index.assert_called_once_with("approved note")

    def test_knowledge_retrieval_is_answered_by_the_shared_babymind_model(self) -> None:
        from unittest.mock import patch
        snippets = ["A grounded local note."]
        with patch("babymind.integrations.cognee_memory.search_approved_notes", return_value=snippets) as search:
            result, retrieved = self.coordinator.ask_with_knowledge(
                "BM-02", "What did the note say?", use_memory=True
            )
        search.assert_called_once_with("What did the note say?")
        self.assertEqual(retrieved, snippets)
        self.assertEqual(result.response, "A tested response.")
        self.assertIn("A grounded local note.", self.provider.user_prompt)
        self.assertIn("untrusted reference material", self.provider.user_prompt)
        self.assertIn("Researcher", self.provider.system_prompt)

    def test_knowledge_search_without_results_still_uses_shared_coordinator(self) -> None:
        from unittest.mock import patch
        with patch("babymind.integrations.cognee_memory.search_approved_notes", return_value=[]):
            result, retrieved = self.coordinator.ask_with_knowledge("BM-01", "Search my notes")
        self.assertEqual(retrieved, [])
        self.assertEqual(result.response, "A tested response.")
        self.assertEqual(self.provider.user_prompt, "Search my notes")

    def test_speech_synthesis_is_exposed_through_core_coordinator(self) -> None:
        from unittest.mock import patch
        with patch("babymind.integrations.voicebox.synthesize_speech", return_value=b"RIFFaudio") as speak:
            result = self.coordinator.synthesize_speech("Hello BabyMind")
        self.assertEqual(result, b"RIFFaudio")
        speak.assert_called_once_with("Hello BabyMind", voice=None, speed=1.0)


if __name__ == "__main__":
    unittest.main()
