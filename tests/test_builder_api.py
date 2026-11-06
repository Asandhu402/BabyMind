"""API tests for the opt-in app builder and the loopback Host check."""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from babymind import sandbox, server


class FakeProvider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(self.payload)


PLAN = {
    "name": "Greeting App",
    "summary": "Prints a greeting.",
    "entry": "app.py",
    "files": [{"path": "app.py", "content": 'print("built by babymind")\n'}],
}


class BuilderApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.original_db = server.DB_PATH
        self.original_home = server.DATA_HOME
        self.original_provider = server.COORDINATOR.provider
        server.DATA_HOME = Path(self.temp.name) / "data"
        server.DATA_HOME.mkdir(parents=True, exist_ok=True)
        server.DB_PATH = server.DATA_HOME / "app.sqlite3"
        server.init_db()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.env = patch.dict(os.environ, {
            "BABYMIND_APP_BUILDER_ENABLED": "true",
            "BABYMIND_BUILDER_ROOT": str(self.root),
        })
        self.env.start()
        server.COORDINATOR.provider = FakeProvider(PLAN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.auth_token = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.COORDINATOR.provider = self.original_provider
        server.DB_PATH = self.original_db
        server.DATA_HOME = self.original_home
        server.BUILDER_PLANS.clear()
        self.env.stop()
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None, headers: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        merged = {"Content-Type": "application/json"} if data is not None else {}
        merged.update(headers or {})
        try:
            with urlopen(Request(self.base + path, data=data, headers=merged), timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_status_endpoint_reports_the_gate(self) -> None:
        status, body = self.request("/api/builder/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["ready"])
        self.assertTrue(body["can_write_files"])
        self.assertFalse(body["can_run_shell_commands"])

    def test_status_is_not_ready_when_disabled(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_APP_BUILDER_ENABLED": "false"}):
            status, body = self.request("/api/builder/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["ready"])

    def test_plan_then_build_creates_the_app(self) -> None:
        if not sandbox.available():
            self.skipTest("generated code execution requires an available OS sandbox")
        status, plan = self.request("/api/builder/plan", {"brief": "a greeting app"})
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["target"], "apps/greeting-app")
        self.assertEqual(plan["files"][0]["path"], "app.py")
        self.assertFalse((self.root / "apps").exists(), "planning must not write anything")

        status, result = self.request("/api/builder/build", {
            "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
        })
        self.assertEqual(status, 201, result)
        created = self.root / "apps" / "greeting-app" / "app.py"
        self.assertTrue(created.is_file())
        self.assertEqual(result["run"]["exit_code"], 0)
        self.assertIn("built by babymind", result["run"]["stdout"])

    def test_build_requires_the_reviewed_hash(self) -> None:
        _, plan = self.request("/api/builder/plan", {"brief": "a greeting app"})
        status, body = self.request("/api/builder/build", {
            "plan_id": plan["plan_id"], "plan_hash": "0" * 64,
        })
        self.assertEqual(status, 400)
        self.assertIn("match", body["error"].lower())
        self.assertFalse((self.root / "apps" / "greeting-app").exists())

    def test_plans_are_single_use(self) -> None:
        _, plan = self.request("/api/builder/plan", {"brief": "a greeting app"})
        first, _ = self.request("/api/builder/build", {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]})
        second, body = self.request("/api/builder/build", {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]})
        self.assertEqual(first, 201)
        self.assertEqual(second, 400)
        self.assertIn("no longer available", body["error"].lower())

    def test_builder_requires_the_environment_gate(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_APP_BUILDER_ENABLED": ""}):
            status, body = self.request("/api/builder/plan", {"brief": "a greeting app"})
        self.assertEqual(status, 400)
        self.assertIn("off", body["error"].lower())

    def test_foreign_host_header_is_rejected(self) -> None:
        status, body = self.request("/api/conversations", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)
        self.assertIn("host", body["error"].lower())

    def test_loopback_host_header_is_accepted(self) -> None:
        status, _ = self.request("/api/conversations", headers={
            "Host": f"127.0.0.1:{self.httpd.server_port}",
        })
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
