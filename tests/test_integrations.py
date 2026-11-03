"""Tests for optional integration adapters without third-party dependencies."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.integrations.browser import run_browser_task
from babymind.integrations.catalog import integration_status
from babymind.integrations.documents import IntegrationUnavailable, convert_document
from babymind.integrations.open_interpreter import launch_read_only_session
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

    def test_open_interpreter_requires_approval_before_launch(self):
        with self.assertRaises(PermissionError):
            launch_read_only_session(".")

    def test_open_interpreter_is_forced_to_local_provider_and_read_only_sandbox(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as folder:
            process = MagicMock()
            process.pid = 4321
            with patch("shutil.which", return_value="interpreter"), patch(
                "subprocess.Popen", return_value=process
            ) as popen:
                result = launch_read_only_session(
                    folder, model="local-model", base_url="http://127.0.0.1:1234/v1",
                    user_approved=True,
                )
            self.assertEqual(result.pid, 4321)
            command = popen.call_args.args[0]
            self.assertIn("--oss", command)
            self.assertIn("--local-provider", command)
            self.assertIn("lmstudio", command)
            self.assertIn("local-model", command)
            self.assertIn('sandbox_mode="read-only"', command)
            self.assertIn('approval_policy="untrusted"', command)
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
                launch_read_only_session(
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
