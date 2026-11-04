"""Tests for optional integration adapters without third-party dependencies."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.integrations.browser import run_browser_task
from babymind.integrations.catalog import integration_status
from babymind.integrations.documents import IntegrationUnavailable, convert_document
from babymind.integrations.speech import transcribe_audio


class IntegrationTests(unittest.TestCase):
    def test_catalog_reports_all_seven_optional_integrations(self):
        statuses = integration_status()
        self.assertEqual(
            {item["integration_id"] for item in statuses},
            {"docling", "faster-whisper", "browser-use", "coding-assistant", "cognee", "voicebox", "promptfoo"},
        )
        coding = next(item for item in statuses if item["integration_id"] == "coding-assistant")
        self.assertTrue(coding["available"])
        self.assertIn("llama.cpp", coding["purpose"])
        self.assertIn("No automatic workspace", coding["safety"])

    def test_voicebox_rejects_non_loopback_endpoint(self):
        from babymind.integrations.voicebox import _base_url
        with patch.dict(os.environ, {"BABYMIND_VOICEBOX_URL": "https://example.com"}):
            with self.assertRaises(ValueError):
                _base_url()

    def test_cognee_is_disabled_by_default(self):
        from babymind.integrations.cognee_memory import index_approved_note
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                index_approved_note("This must not be indexed.")

    def test_cognee_rejects_hosted_api_credentials(self):
        from babymind.integrations.cognee_memory import index_approved_note
        with patch.dict(os.environ, {"BABYMIND_COGNEE_ENABLED": "true", "OPENAI_API_KEY": "not-a-real-key"}):
            with self.assertRaises(PermissionError):
                index_approved_note("This must not be indexed.")

    def test_document_import_requires_existing_local_file(self):
        with self.assertRaises(FileNotFoundError):
            convert_document("missing-local-document.pdf")

    def test_document_import_rejects_large_files_before_loading_docling(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.pdf"
            path.write_bytes(b"x")
            with patch("pathlib.Path.stat") as stat_mock:
                import os
                import stat
                stat_mock.return_value = os.stat_result(
                    (stat.S_IFREG, 0, 0, 0, 0, 0, 101 * 1024 * 1024, 0, 0, 0)
                )
                with self.assertRaises(ValueError):
                    convert_document(path)

    def test_speech_requires_existing_local_file(self):
        with self.assertRaises(FileNotFoundError):
            transcribe_audio("missing-audio.wav")

    def test_browser_requires_approval_before_import_or_network(self):
        async def run():
            with self.assertRaises(PermissionError):
                await run_browser_task("read this page", model="local-model")
        import asyncio
        asyncio.run(run())

    def test_browser_is_enabled_by_default_after_explicit_task_approval(self):
        import asyncio
        import sys
        import types

        class FakeBrowser:
            closed = False
            async def close(self):
                self.closed = True

        browser = FakeBrowser()

        class FakeAgent:
            async def run(self):
                return types.SimpleNamespace(final_result=lambda: "Page summary")

        fake = types.ModuleType("browser_use")
        fake.Agent = lambda **kwargs: FakeAgent()
        fake.Browser = lambda: browser
        fake.ChatOpenAI = lambda **kwargs: object()
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"browser_use": fake}):
            result = asyncio.run(run_browser_task(
                "Read the current page and summarize it",
                model="local-model",
                user_approved=True,
            ))
        self.assertEqual(result, "Page summary")
        self.assertTrue(browser.closed)

    def test_browser_can_still_be_disabled_explicitly(self):
        import asyncio
        with patch.dict(os.environ, {"BABYMIND_BROWSER_AUTOMATION_ENABLED": "false"}):
            with self.assertRaises(PermissionError):
                asyncio.run(run_browser_task(
                    "Read this page", model="local-model", user_approved=True
                ))

    def test_missing_optional_docling_is_reported_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note.txt"
            path.write_text("hello", encoding="utf-8")
            with patch.dict("sys.modules", {"docling": None}):
                with self.assertRaises(IntegrationUnavailable):
                    convert_document(path)


    def test_coding_assistant_uses_provider_and_marks_context_untrusted(self):
        from babymind.integrations.coding import assist_with_code
        class Provider:
            def complete(self, system, user):
                self.system, self.user = system, user
                return "Proposed implementation."
        provider = Provider()
        result = assist_with_code(provider, "Fix the parser", context="ValueError at line 4")
        self.assertEqual(result, "Proposed implementation.")
        self.assertIn("no filesystem or command tools", provider.system)
        self.assertIn("untrusted data", provider.user)

    def test_coding_assistant_rejects_empty_and_oversized_requests(self):
        from babymind.integrations.coding import assist_with_code
        class Provider:
            def complete(self, system, user):
                raise AssertionError("Provider must not be called for invalid input.")
        for task in ("", " "):
            with self.assertRaises(ValueError):
                assist_with_code(Provider(), task)
        with self.assertRaises(ValueError):
            assist_with_code(Provider(), "x" * 12001)
        with self.assertRaises(ValueError):
            assist_with_code(Provider(), "valid", context="x" * 24001)




if __name__ == "__main__":
    unittest.main()
