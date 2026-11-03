"""Tests for optional integration adapters without third-party dependencies."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.integrations.browser import run_browser_task
from babymind.integrations.catalog import integration_status
from babymind.integrations.documents import IntegrationUnavailable, convert_document
from babymind.integrations.open_interpreter import launch_workspace_session
from babymind.integrations.speech import transcribe_audio


class IntegrationTests(unittest.TestCase):
    def test_catalog_reports_all_four_optional_integrations(self):
        statuses = integration_status()
        self.assertEqual(
            {item["integration_id"] for item in statuses},
            {"docling", "faster-whisper", "browser-use", "open-interpreter"},
        )

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

    def test_open_interpreter_requires_approval_before_launch(self):
        with self.assertRaises(PermissionError):
            launch_workspace_session(".")

    def test_open_interpreter_is_forced_to_local_provider_and_workspace_write_sandbox(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as folder:
            process = MagicMock()
            process.pid = 4321
            with patch("shutil.which", return_value="interpreter"), patch(
                "subprocess.Popen", return_value=process
            ) as popen:
                result = launch_workspace_session(
                    folder, model="local-model", base_url="http://127.0.0.1:1234/v1",
                    user_approved=True,
                )
            self.assertEqual(result.pid, 4321)
            command = popen.call_args.args[0]
            self.assertIn("--oss", command)
            self.assertIn("--local-provider", command)
            self.assertIn("lmstudio", command)
            self.assertIn("local-model", command)
            self.assertIn("--sandbox", command)
            self.assertIn("workspace-write", command)
            self.assertIn("--ask-for-approval", command)
            self.assertIn("on-request", command)
            self.assertIn("--cd", command)
            self.assertIn(str(Path(folder).resolve()), command)
            self.assertIn("sandbox_workspace_write.network_access=false", command)
            self.assertEqual(
                popen.call_args.kwargs["env"]["CODEX_OSS_BASE_URL"],
                "http://127.0.0.1:1234/v1",
            )
            self.assertFalse(popen.call_args.kwargs["shell"])
            import subprocess
            self.assertEqual(
                popen.call_args.kwargs["creationflags"],
                getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0,
            )

    def test_open_interpreter_rejects_nonlocal_model_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                launch_workspace_session(
                    folder, model="remote", base_url="https://api.example.com/v1",
                    user_approved=True,
                )

    def test_missing_optional_docling_is_reported_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note.txt"
            path.write_text("hello", encoding="utf-8")
            with patch.dict("sys.modules", {"docling": None}):
                with self.assertRaises(IntegrationUnavailable):
                    convert_document(path)


if __name__ == "__main__":
    unittest.main()
