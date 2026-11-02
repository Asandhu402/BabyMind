"""Integration checks for BabyMind's local web application."""
from __future__ import annotations

import json
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
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
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
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None, token: str | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-BabyMind-Token"] = token
        request = Request(self.base + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                body = response.read()
                return response.status, response.headers.get("Content-Type"), body
        except HTTPError as error:
            return error.code, error.headers.get("Content-Type"), error.read()

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


if __name__ == "__main__":
    unittest.main()
