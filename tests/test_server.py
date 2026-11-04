"""Integration checks for BabyMind's local web application."""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from babymind import server


class BabyMindWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.original_db = server.DB_PATH
        self.original_home = server.DATA_HOME
        self.original_memory = server.COORDINATOR.memory
        server.DATA_HOME = Path(self.temp.name) / "data"
        server.DATA_HOME.mkdir(parents=True, exist_ok=True)
        server.DB_PATH = server.DATA_HOME / "app.sqlite3"
        server.init_db()
        from babymind import approval
        self.original_workspace_actions_enabled = approval.WORKSPACE_FILE_ACTIONS_ENABLED
        approval.WORKSPACE_FILE_ACTIONS_ENABLED = True  # Legacy helper coverage only inside tests.
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.auth_token = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH = self.original_db
        server.DATA_HOME = self.original_home
        server.COORDINATOR.memory = self.original_memory
        from babymind import approval
        approval.WORKSPACE_FILE_ACTIONS_ENABLED = self.original_workspace_actions_enabled
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None, token: str | None = None,
                extra_headers: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-BabyMind-Token"] = token
        headers.update(extra_headers or {})
        request = Request(self.base + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                body = response.read()
                return response.status, response.headers.get("Content-Type"), body
        except HTTPError as error:
            return error.code, error.headers.get("Content-Type"), error.read()

    def test_encrypted_backup_export_api(self) -> None:
        destination = Path(self.temp.name) / "BabyMind.bmbak"
        status, _, body = self.request("/api/backup/export", {
            "path": str(destination), "password": "test-backup-password-2026",
        })
        self.assertEqual(status, 201, body)
        payload = json.loads(body)
        self.assertTrue(destination.is_file())
        self.assertIn("app.sqlite3", payload["files"])
        self.assertIn("encrypted", payload["notice"].lower())

    def test_encrypted_backup_restore_api_restores_conversation(self) -> None:
        status, _, body = self.request("/api/conversations", {"title": "Backup test"})
        self.assertEqual(status, 201)
        conversation_id = json.loads(body)["id"]
        server.persist_integration_exchange(conversation_id, "hello backup", "saved response")
        destination = Path(self.temp.name) / "BabyMind.bmbak"
        status, _, body = self.request("/api/backup/export", {
            "path": str(destination), "password": "test-backup-password-2026",
        })
        self.assertEqual(status, 201, body)
        status, _, _ = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        request = Request(self.base + "/api/conversations/" + conversation_id, method="DELETE")
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
        status, _, _ = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.request("/api/conversations/" + conversation_id)[2]), [])
        status, _, body = self.request("/api/backup/restore", {
            "path": str(destination), "password": "test-backup-password-2026",
            "confirmation": "RESTORE BABYMIND",
        })
        self.assertEqual(status, 200, body)
        status, _, body = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        self.assertEqual([item["role"] for item in json.loads(body)], ["user", "assistant"])
        self.assertEqual(json.loads(body)[1]["content"], "saved response")

    def test_integrations_api_lists_optional_tools(self) -> None:
        status, _, body = self.request("/api/integrations")
        self.assertEqual(status, 200)
        self.assertEqual(
            {item["integration_id"] for item in json.loads(body)},
            {"docling", "faster-whisper", "browser-use", "coding-assistant", "cognee", "voicebox", "promptfoo"},
        )

    def test_document_integration_uses_core_coordinator(self) -> None:
        fake = SimpleNamespace(
            response="Document summary", agent_id="BM-02", agent_name="Researcher",
            memories_used=0, remembered=False,
        )
        with patch.object(server.COORDINATOR, "process_document", return_value=(fake, 123)) as process:
            status, _, body = self.request("/api/integrations/document", {
                "path": "C:/Users/test/report.pdf", "agent_id": "BM-02",
            })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["response"], "Document summary")
        self.assertEqual(json.loads(body)["extracted_characters"], 123)
        process.assert_called_once()

    def test_audio_integration_uses_core_coordinator(self) -> None:
        fake = SimpleNamespace(
            response="Audio summary", agent_id="BM-01", agent_name="Coordinator",
            memories_used=0, remembered=False,
        )
        transcript = {"text": "Hello there", "language": "en"}
        with patch.object(server.COORDINATOR, "process_audio", return_value=(fake, transcript)) as process:
            status, _, body = self.request("/api/integrations/audio", {
                "path": "C:/Users/test/voice.wav",
            })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["transcript"]["text"], "Hello there")
        process.assert_called_once()

    def test_voicebox_speech_route_uses_core_coordinator(self) -> None:
        with patch.object(server.COORDINATOR, "synthesize_speech", return_value=b"RIFFaudio") as speak:
            status, _, body = self.request("/api/integrations/voicebox/speech", {"text": "Hello"})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["mime_type"], "audio/wav")
        self.assertEqual(payload["audio_base64"], "UklGRmF1ZGlv")
        speak.assert_called_once_with("Hello", voice=None, speed=1.0)

    def test_voicebox_transcription_route_uses_core_coordinator(self) -> None:
        fake = SimpleNamespace(
            response="Audio summary", agent_id="BM-01", agent_name="Coordinator",
            memories_used=0, remembered=False,
        )
        transcript = {"text": "Local speech", "language": "en"}
        with patch.object(server.COORDINATOR, "process_voicebox_audio", return_value=(fake, transcript)) as process:
            status, _, body = self.request("/api/integrations/voicebox/transcribe", {"path": "C:/voice.wav"})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["response"], "Audio summary")
        self.assertEqual(payload["transcript"]["text"], "Local speech")
        process.assert_called_once()

    def test_cognee_index_route_uses_approved_core_coordinator(self) -> None:
        with patch.object(server.COORDINATOR, "index_knowledge_note", return_value="babymind-approved") as index:
            status, _, body = self.request("/api/integrations/cognee/index", {
                "text": "An approved note", "user_approved": True,
            })
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["dataset"], "babymind-approved")
        index.assert_called_once_with("An approved note", user_approved=True)

    def test_cognee_search_route_uses_shared_coordinator_and_persists_answer(self) -> None:
        fake = SimpleNamespace(
            response="The note says hello.", agent_id="BM-02", agent_name="Researcher",
            memories_used=1, remembered=False,
        )
        with patch.object(server.COORDINATOR, "ask_with_knowledge", return_value=(fake, ["Hello note"])) as ask:
            status, _, body = self.request("/api/integrations/cognee/search", {
                "query": "What does my note say?", "agent_id": "BM-02", "use_memory": True,
            })
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["response"], "The note says hello.")
        self.assertEqual(payload["results"], ["Hello note"])
        self.assertTrue(payload["conversation_id"])
        ask.assert_called_once_with(
            "BM-02", "What does my note say?", use_memory=True, remember=False,
        )

    def test_coding_assistant_requires_explicit_approval(self) -> None:
        status, _, body = self.request("/api/integrations/coding", {"task": "Explain this function"})
        self.assertEqual(status, 400)
        self.assertIn(b"Confirm the coding request", body)

    def test_coding_assistant_uses_shared_local_coordinator_and_persists_result(self) -> None:
        with patch.object(server.COORDINATOR, "coding_assist", return_value="Here is a safe patch plan.") as assist:
            status, _, body = self.request("/api/integrations/coding", {
                "task": "Fix this Python bug", "context": "def f(): return None",
                "user_approved": True,
            })
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["response"], "Here is a safe patch plan.")
        self.assertIn("No files or commands were accessed", payload["notice"])
        self.assertTrue(payload["conversation_id"])
        assist.assert_called_once_with("Fix this Python bug", context="def f(): return None")

    def test_integration_exchanges_are_saved_in_encrypted_conversation_history(self) -> None:
        conversation_id = server.persist_integration_exchange(
            "", "Analyze local document: report.pdf", "This is the summary."
        )
        status, _, body = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        messages = json.loads(body)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["content"], "This is the summary.")
        with server.db() as connection:
            rows = connection.execute(
                "SELECT content FROM messages WHERE conversation_id=?", (conversation_id,)
            ).fetchall()
        self.assertTrue(all(row["content"].startswith("bmenc:v1:") for row in rows))

    def test_task_queue_create_and_lifecycle(self) -> None:
        status, _, body = self.request("/api/tasks", {
            "title": "Prepare project plan", "details": "Draft steps only"
        })
        self.assertEqual(status, 201)
        task = json.loads(body)
        self.assertEqual(task["status"], "queued")
        task_id = task["id"]
        for action, expected in [
            ("start", "active"), ("pause", "paused"),
            ("resume", "active"), ("complete", "completed")
        ]:
            status, _, body = self.request(
                f"/api/tasks/{task_id}/action", {"action": action}
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], expected)
        status, _, body = self.request("/api/tasks")
        self.assertEqual(status, 200)
        tasks = json.loads(body)
        self.assertEqual(tasks[0]["title"], "Prepare project plan")
        self.assertEqual(tasks[0]["details"], "Draft steps only")

    def test_task_queue_rejects_invalid_state_transition(self) -> None:
        status, _, body = self.request("/api/tasks", {"title": "Task"})
        task_id = json.loads(body)["id"]
        status, _, body = self.request(
            f"/api/tasks/{task_id}/action", {"action": "resume"}
        )
        self.assertEqual(status, 400)
        self.assertIn(b"Cannot resume", body)

    def test_approval_gated_readonly_directory_listing(self) -> None:
        with TemporaryDirectory() as workspace:
            Path(workspace, "note.txt").write_text("private contents", encoding="utf-8")
            with patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
                status, _, body = self.request("/api/tasks", {"title": "Inspect workspace"})
                task_id = json.loads(body)["id"]
                self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
                status, _, body = self.request(f"/api/tasks/{task_id}/propose", {"relative_path": "."})
                self.assertEqual(status, 201)
                proposal = json.loads(body)
                self.assertEqual(proposal["status"], "awaiting_approval")
                self.assertEqual(proposal["action"], "list_directory")
                status, _, body = self.request(f"/api/proposals/{proposal['id']}/approve", {
                    "proposal_hash": "wrong"
                })
                self.assertEqual(status, 400)
                status, _, body = self.request(f"/api/proposals/{proposal['id']}/approve", {
                    "proposal_hash": proposal["proposal_hash"]
                })
                self.assertEqual(status, 200)
                result = json.loads(body)["result"]
                self.assertEqual(result["entries"], [{"name": "note.txt", "type": "file"}])
                self.assertNotIn("private contents", body.decode("utf-8"))
                self.assertEqual(Path(workspace, "note.txt").read_text(encoding="utf-8"), "private contents")

    def test_approval_rejects_parent_traversal(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            with self.assertRaises(ValueError):
                from babymind.approval import build_readonly_proposal
                build_readonly_proposal("../")

    def test_task_queue_stores_text_encrypted(self) -> None:
        self.request("/api/tasks", {"title": "Secret title", "details": "Secret details"})
        with server.db() as connection:
            row = connection.execute("SELECT title, details FROM tasks").fetchone()
        self.assertTrue(row["title"].startswith("bmenc:v1:"))
        self.assertTrue(row["details"].startswith("bmenc:v1:"))

    def test_agent_api_returns_exactly_fifty_roles(self) -> None:
        status, _, body = self.request("/api/agents")
        self.assertEqual(status, 200)
        agents = json.loads(body)
        self.assertEqual(len(agents), 50)
        self.assertEqual(agents[0]["id"], "BM-01")
        self.assertEqual(agents[-1]["id"], "BM-50")

    def test_web_assets_are_served_from_package(self) -> None:
        status, content_type, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type or "")
        self.assertIn(b"BabyMind", body)
        status, content_type, _ = self.request("/assets/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type or "")

    def test_lan_mode_requires_access_token(self) -> None:
        self.httpd.auth_token = "test-local-token"
        status, _, _ = self.request("/api/agents")
        self.assertEqual(status, 401)
        status, _, body = self.request("/api/agents", token="test-local-token")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)), 50)

    def test_cross_site_mutation_is_rejected(self) -> None:
        status, _, body = self.request(
            "/api/memory/clear", {},
            extra_headers={"Origin": "http://attacker.example"},
        )
        self.assertEqual(status, 403)
        self.assertIn(b"origin", body.lower())

    def test_non_json_mutation_is_rejected(self) -> None:
        request = Request(
            self.base + "/api/memory/clear",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        self.assertEqual(status, 400)

    def test_chat_is_rejected_while_an_inference_is_active(self) -> None:
        self.assertTrue(server.INFERENCE_SEMAPHORE.acquire(blocking=False))
        try:
            status, _, body = self.request("/api/chat", {
                "message": "Hello", "agent_id": "BM-01"
            })
        finally:
            server.INFERENCE_SEMAPHORE.release()
        self.assertEqual(status, 429)
        self.assertIn(b"busy", body.lower())

    def test_chat_persists_only_successful_conversation(self) -> None:
        fake_result = SimpleNamespace(response="Hello from BabyMind")
        with patch.object(server.COORDINATOR, "ask", return_value=fake_result):
            status, _, body = self.request("/api/chat", {
                "message": "Hello", "agent_id": "BM-01"
            })
        self.assertEqual(status, 200)
        result = json.loads(body)
        conversation_id = result["conversation_id"]
        status, _, body = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        messages = json.loads(body)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["content"], "Hello from BabyMind")

    def test_chat_treats_null_conversation_id_as_new_conversation(self) -> None:
        fake_result = SimpleNamespace(response="Fresh conversation response")
        with patch.object(server.COORDINATOR, "ask", return_value=fake_result):
            status, _, body = self.request("/api/chat", {
                "message": "Start a fresh chat", "agent_id": "BM-01",
                "conversation_id": None,
            })
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertTrue(result["conversation_id"])
        status, _, body = self.request("/api/conversations/" + result["conversation_id"])
        self.assertEqual(status, 200)
        self.assertEqual(
            [item["role"] for item in json.loads(body)], ["user", "assistant"]
        )

    def test_conversation_text_is_encrypted_in_sqlite(self) -> None:
        fake_result = SimpleNamespace(response="Confidential answer")
        with patch.object(server.COORDINATOR, "ask", return_value=fake_result):
            status, _, body = self.request("/api/chat", {
                "message": "Confidential question", "agent_id": "BM-01"
            })
        self.assertEqual(status, 200)
        with server.db() as connection:
            stored = connection.execute(
                "SELECT content FROM messages ORDER BY id"
            ).fetchall()
        self.assertTrue(all(row["content"].startswith("bmenc:v1:") for row in stored))
        self.assertNotIn("Confidential question", [row["content"] for row in stored])
        self.assertNotIn("Confidential answer", [row["content"] for row in stored])

    def test_conversation_can_be_deleted_with_its_messages(self) -> None:
        fake_result = SimpleNamespace(response="Temporary answer")
        with patch.object(server.COORDINATOR, "ask", return_value=fake_result):
            status, _, body = self.request("/api/chat", {
                "message": "Delete me", "agent_id": "BM-01"
            })
        self.assertEqual(status, 200)
        conversation_id = json.loads(body)["conversation_id"]
        request = Request(self.base + "/api/conversations/" + conversation_id, method="DELETE")
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
        self.assertEqual(result["deleted"], 1)
        status, _, body = self.request("/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])

    def test_collaboration_uses_specialist_reviewer_and_coordinator(self) -> None:
        fake_result = SimpleNamespace(response="Draft answer")
        with patch.object(server.COORDINATOR, "ask", return_value=fake_result) as ask:
            status, _, body = self.request("/api/chat", {
                "message": "Review my plan", "agent_id": "BM-02", "collaborate": True
            })
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["agents_involved"], ["BM-02", "BM-49", "BM-01"])
        self.assertEqual([call.args[0] for call in ask.call_args_list], ["BM-02", "BM-49", "BM-01"])


    def test_proposals_api_lists_pending_and_completed_results(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, "readme.txt").write_text("must stay private", encoding="utf-8")
            status, _, body = self.request("/api/tasks", {"title": "Review files"})
            self.assertEqual(status, 201)
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(f"/api/tasks/{task_id}/propose", {"relative_path": "."})
            self.assertEqual(status, 201)
            proposal = json.loads(body)

            status, _, body = self.request("/api/proposals")
            self.assertEqual(status, 200)
            pending = json.loads(body)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["id"], proposal["id"])
            self.assertEqual(pending[0]["status"], "awaiting_approval")
            self.assertEqual(pending[0]["payload"], {"relative_path": "."})
            self.assertEqual(pending[0]["result"], "")

            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)

            status, _, body = self.request("/api/proposals")
            self.assertEqual(status, 200)
            completed = json.loads(body)[0]
            self.assertEqual(completed["status"], "completed")
            result = json.loads(completed["result"])
            self.assertEqual(result["entries"], [{"name": "readme.txt", "type": "file"}])
            self.assertNotIn("must stay private", body.decode("utf-8"))

    def test_proposal_requires_active_task(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            status, _, body = self.request("/api/tasks", {"title": "Not started"})
            task_id = json.loads(body)["id"]
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose", {"relative_path": "."}
            )
            self.assertEqual(status, 400)
            self.assertIn(b"Start the task", body)

    def test_approval_workspace_assets_are_served(self) -> None:
        status, content_type, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b'data-view="approvals"', body)
        self.assertIn(b'/assets/approvals.js', body)
        for asset in ("approvals.js", "approvals.css"):
            status, content_type, body = self.request(f"/assets/{asset}")
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertTrue(content_type)


    def test_approved_text_file_preview_reads_only_after_matching_approval(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, "notes.txt").write_text("hello from the workspace", encoding="utf-8")
            status, _, body = self.request("/api/tasks", {"title": "Preview a note"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": "notes.txt", "action": "read_text_file"},
            )
            self.assertEqual(status, 201)
            proposal = json.loads(body)
            self.assertEqual(proposal["action"], "read_text_file")
            self.assertNotIn("hello from the workspace", body.decode("utf-8"))

            status, _, body = self.request("/api/proposals")
            self.assertEqual(status, 200)
            pending = json.loads(body)[0]
            self.assertEqual(pending["status"], "awaiting_approval")
            self.assertEqual(pending["result"], "")
            self.assertNotIn("hello from the workspace", body.decode("utf-8"))

            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)
            result = json.loads(body)["result"]
            self.assertEqual(result["content"], "hello from the workspace")
            self.assertEqual(result["bytes"], len("hello from the workspace".encode("utf-8")))
            self.assertEqual(Path(workspace, "notes.txt").read_text(encoding="utf-8"), "hello from the workspace")

    def test_text_file_preview_rejects_unsupported_hidden_and_oversized_files(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, ".env").write_text("SECRET=value", encoding="utf-8")
            Path(workspace, "large.txt").write_text("x" * (32 * 1024 + 1), encoding="utf-8")
            Path(workspace, "image.png").write_bytes(b"not text")
            from babymind.approval import build_readonly_proposal
            for name in (".env", "large.txt", "image.png"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    build_readonly_proposal(name, action="read_text_file")

    def test_text_file_preview_rejects_parent_traversal_and_symlinks(self) -> None:
        with TemporaryDirectory() as workspace, TemporaryDirectory() as outside, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(outside, "secret.txt").write_text("outside", encoding="utf-8")
            try:
                Path(workspace, "linked.txt").symlink_to(Path(outside, "secret.txt"))
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable on this platform.")
            from babymind.approval import build_readonly_proposal
            with self.assertRaises(ValueError):
                build_readonly_proposal("../secret.txt", action="read_text_file")
            with self.assertRaises(ValueError):
                build_readonly_proposal("linked.txt", action="read_text_file")


    def test_filename_search_lists_candidates_without_reading_contents(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, "invoice-2026.txt").write_text("private invoice body", encoding="utf-8")
            Path(workspace, "notes.md").write_text("private notes body", encoding="utf-8")
            Path(workspace, ".hidden-invoice.txt").write_text("hidden", encoding="utf-8")
            Path(workspace, "invoice.png").write_bytes(b"binary")
            Path(workspace, "nested").mkdir()
            Path(workspace, "nested", "old-invoice.csv").write_text("private csv body", encoding="utf-8")
            status, _, body = self.request("/api/tasks", {"title": "Find invoices"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": ".", "action": "find_files", "name_contains": "invoice"},
            )
            self.assertEqual(status, 201)
            proposal = json.loads(body)
            self.assertEqual(proposal["action"], "find_files")
            self.assertNotIn("private invoice body", body.decode("utf-8"))
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)
            result = json.loads(body)["result"]
            paths = {item["relative_path"] for item in result["files"]}
            self.assertEqual(paths, {"invoice-2026.txt", "nested/old-invoice.csv"})
            self.assertNotIn("private invoice body", body.decode("utf-8"))
            self.assertNotIn("private csv body", body.decode("utf-8"))

    def test_each_found_file_requires_its_own_preview_proposal_and_approval(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, "one.txt").write_text("one private body", encoding="utf-8")
            Path(workspace, "two.txt").write_text("two private body", encoding="utf-8")
            status, _, body = self.request("/api/tasks", {"title": "Review notes"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": ".", "action": "find_files", "name_contains": ".txt"},
            )
            search_proposal = json.loads(body)
            status, _, body = self.request(
                f"/api/proposals/{search_proposal['id']}/approve",
                {"proposal_hash": search_proposal["proposal_hash"]},
            )
            found = json.loads(body)["result"]["files"]
            first_path = found[0]["relative_path"]
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": first_path, "action": "read_text_file"},
            )
            self.assertEqual(status, 201)
            read_proposal = json.loads(body)
            self.assertEqual(read_proposal["status"], "awaiting_approval")
            status, _, body = self.request("/api/proposals")
            self.assertEqual(status, 200)
            self.assertNotIn("one private body", body.decode("utf-8"))
            self.assertNotIn("two private body", body.decode("utf-8"))
            status, _, body = self.request(
                f"/api/proposals/{read_proposal['id']}/approve",
                {"proposal_hash": read_proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)
            self.assertIn(json.loads(body)["result"]["content"], {"one private body", "two private body"})

    def test_filename_search_rejects_empty_query(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            from babymind.approval import build_readonly_proposal
            with self.assertRaises(ValueError):
                build_readonly_proposal(".", action="find_files", name_contains="  ")


    def test_new_text_file_requires_exact_approval_and_never_overwrites(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            status, _, body = self.request("/api/tasks", {"title": "Create a draft"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            Path(workspace, "drafts").mkdir()
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": "drafts/hello.txt", "action": "create_text_file", "content": "Hello BabyMind"},
            )
            self.assertEqual(status, 201)
            proposal = json.loads(body)
            self.assertEqual(proposal["action"], "create_text_file")
            self.assertFalse(Path(workspace, "drafts", "hello.txt").exists())
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve", {"proposal_hash": "wrong"}
            )
            self.assertEqual(status, 400)
            self.assertFalse(Path(workspace, "drafts", "hello.txt").exists())
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)
            self.assertEqual(Path(workspace, "drafts", "hello.txt").read_text(encoding="utf-8"), "Hello BabyMind")
            self.assertTrue(json.loads(body)["result"]["created"])

    def test_new_text_file_rejects_existing_target_and_unsafe_input(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            from babymind.approval import build_readonly_proposal
            Path(workspace, "exists.txt").write_text("keep me", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "never overwrite"):
                build_readonly_proposal("exists.txt", action="create_text_file", content="replace")
            with self.assertRaises(ValueError):
                build_readonly_proposal("../escape.txt", action="create_text_file", content="no")
            with self.assertRaises(ValueError):
                build_readonly_proposal("bad.exe", action="create_text_file", content="no")
            with self.assertRaises(ValueError):
                build_readonly_proposal("new.txt", action="create_text_file", content="\x00")


    def test_new_text_file_does_not_overwrite_target_added_after_proposal(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            status, _, body = self.request("/api/tasks", {"title": "Create a draft safely"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": "late.txt", "action": "create_text_file", "content": "new content"},
            )
            proposal = json.loads(body)
            target = Path(workspace, "late.txt")
            target.write_text("existing content", encoding="utf-8")
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 400)
            self.assertEqual(target.read_text(encoding="utf-8"), "existing content")


    def test_text_file_edit_requires_exact_approval_and_original_hash(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            target = Path(workspace, "draft.md")
            target.write_text("# Draft\\nold text\\n", encoding="utf-8")
            status, _, body = self.request("/api/tasks", {"title": "Revise draft"})
            task_id = json.loads(body)["id"]
            self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
            status, _, body = self.request(
                f"/api/tasks/{task_id}/propose",
                {"relative_path": "draft.md", "action": "edit_text_file", "content": "# Draft\\nnew text\\n"},
            )
            self.assertEqual(status, 201)
            proposal = json.loads(body)
            self.assertEqual(proposal["action"], "edit_text_file")
            self.assertIn("old text", proposal["payload"]["original_content"])
            self.assertFalse(target.read_text(encoding="utf-8").endswith("new text\\n"))
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve", {"proposal_hash": "incorrect"}
            )
            self.assertEqual(status, 400)
            self.assertIn("old text", target.read_text(encoding="utf-8"))
            status, _, body = self.request(
                f"/api/proposals/{proposal['id']}/approve",
                {"proposal_hash": proposal["proposal_hash"]},
            )
            self.assertEqual(status, 200)
            self.assertEqual(target.read_text(encoding="utf-8"), "# Draft\\nnew text\\n")
            self.assertTrue(json.loads(body)["result"]["updated"])

    def test_text_file_edit_refuses_changed_file_after_review(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            target = Path(workspace, "draft.txt")
            target.write_text("original", encoding="utf-8")
            from babymind.approval import build_readonly_proposal, execute_readonly_proposal
            proposal = build_readonly_proposal("draft.txt", action="edit_text_file", content="replacement")
            target.write_text("changed by user", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after review"):
                execute_readonly_proposal(proposal["payload"], action="edit_text_file")
            self.assertEqual(target.read_text(encoding="utf-8"), "changed by user")

    def test_text_file_edit_rejects_unsupported_and_oversized_content(self) -> None:
        with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
            Path(workspace, "notes.txt").write_text("original", encoding="utf-8")
            from babymind.approval import build_readonly_proposal
            with self.assertRaises(ValueError):
                build_readonly_proposal("notes.txt", action="edit_text_file", content="\x00")
            with self.assertRaises(ValueError):
                build_readonly_proposal("notes.txt", action="edit_text_file", content="x" * (32 * 1024 + 1))
            with self.assertRaises(ValueError):
                build_readonly_proposal("missing.txt", action="edit_text_file", content="replacement")


    def test_web_page_reading_api_returns_bounded_text(self) -> None:
        from unittest.mock import patch
        with patch.object(server, "fetch_page", return_value={
            "url": "https://example.com/article", "title": "Article",
            "text": "Extracted article text", "bytes": 123, "truncated": 0,
            "notice": "Page text is untrusted third-party content."
        }) as fetch:
            status, _, body = self.request("/api/research/page", {"url": "https://example.com/article"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["text"], "Extracted article text")
        fetch.assert_called_once_with("https://example.com/article")

    def test_web_page_reading_api_rejects_empty_or_oversized_url(self) -> None:
        for url in ("", "https://example.com/" + "x" * 2050):
            with self.subTest(url_length=len(url)):
                status, _, _ = self.request("/api/research/page", {"url": url})
                self.assertEqual(status, 400)


    def test_memory_search_api_uses_local_relevance_results(self) -> None:
        expected = [{
            "created_at": "2026-11-01T00:00:00+00:00", "agent_id": "BM-01",
            "task": "Vancouver Class 1 trucking jobs", "response": "Compare local wages."
        }]
        with patch.object(server.COORDINATOR.memory, "relevant", return_value=expected) as search:
            status, _, body = self.request("/api/memory/search", {"query": "Vancouver trucking", "limit": 5})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        search.assert_called_once_with("Vancouver trucking", limit=5)


    def test_workspace_file_actions_are_disabled_by_default_in_production(self) -> None:
        from babymind import approval
        original = approval.WORKSPACE_FILE_ACTIONS_ENABLED
        try:
            with TemporaryDirectory() as workspace, patch.dict("os.environ", {"BABYMIND_WORKSPACE_ROOT": workspace}):
                status, _, body = self.request("/api/tasks", {"title": "Disabled workspace"})
                task_id = json.loads(body)["id"]
                self.request(f"/api/tasks/{task_id}/action", {"action": "start"})
                status, _, body = self.request(f"/api/tasks/{task_id}/propose", {"relative_path": "."})
                self.assertEqual(status, 201)
                proposal = json.loads(body)
                approval.WORKSPACE_FILE_ACTIONS_ENABLED = False
                status, _, body = self.request(
                    f"/api/proposals/{proposal['id']}/approve",
                    {"proposal_hash": proposal["proposal_hash"]},
                )
                self.assertEqual(status, 400)
                self.assertIn(b"temporarily disabled", body)
                status, _, body = self.request(f"/api/tasks/{task_id}/propose", {"relative_path": "."})
                self.assertEqual(status, 400)
                self.assertIn(b"temporarily disabled", body)
        finally:
            approval.WORKSPACE_FILE_ACTIONS_ENABLED = original

    def test_project_test_execution_is_disabled_until_sandboxed(self) -> None:
        from babymind.approval import build_readonly_proposal, execute_readonly_proposal
        with self.assertRaisesRegex(ValueError, "Unsupported workspace action"):
            build_readonly_proposal(".", action="run_tests")
        with self.assertRaisesRegex(ValueError, "disabled until a real sandbox"):
            execute_readonly_proposal({"relative_path": "."}, action="run_tests")


    def test_workspace_readiness_api_reports_closed_security_gates(self) -> None:
        status, _, body = self.request("/api/workspace/readiness")
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(report["model_engine"], "llama.cpp")
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["native_workspace"]["file_actions_enabled"])
        self.assertFalse(report["project_execution"]["sandbox_available"])
        self.assertIn("read-only readiness report", report["notice"])


if __name__ == "__main__":
    unittest.main()
