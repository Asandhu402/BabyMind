"""API tests for mission control, role metadata, and the self-development endpoints."""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from babymind import server


class FakeProvider:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return "Contribution: concrete, verifiable step recorded by this role."


class SequencedSelfEditProvider:
    """First self-edit breaks a test; the second repairs it."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "Return ONLY JSON" in system_prompt:
            self.calls += 1
            self.prompts.append(user_prompt)
            target = "tests/test_ok.py"
            value = "1, 2" if self.calls == 1 else "2, 2"
            return json.dumps({"reason": f"attempt {self.calls}", "edits": [{
                "path": target,
                "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                           f"    def test_ok(self):\n        self.assertEqual({value})\n"}]})
        return "Contribution: concrete, verifiable step recorded by this role."


def _make_checkout(root: Path) -> None:
    (root / "src" / "babymind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    (root / "src" / "babymind" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "babymind" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text(
        "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
        "    def test_ok(self):\n        self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )


class MissionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.original = (server.DB_PATH, server.DATA_HOME, server.COORDINATOR.provider)
        server.DATA_HOME = Path(self.temp.name) / "data"
        server.DATA_HOME.mkdir(parents=True, exist_ok=True)
        server.DB_PATH = server.DATA_HOME / "app.sqlite3"
        server.init_db()
        self.checkout = Path(self.temp.name) / "checkout"
        _make_checkout(self.checkout)
        self.env = patch.dict(os.environ, {
            "BABYMIND_DEV_ROOT": str(self.checkout),
            "BABYMIND_SELF_DEVELOPMENT_ENABLED": "true",
            "BABYMIND_MISSION_MAX_SECONDS": "120",
            "BABYMIND_SANDBOX": "off",  # trusted disposable API fixture
        })
        self.env.start()
        server.COORDINATOR.provider = FakeProvider()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.auth_token = None
        self.httpd.lan_ip = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        server._MISSION_STORE = None
        server._MISSION_HOME = None
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH, server.DATA_HOME, server.COORDINATOR.provider = self.original
        server._MISSION_STORE = None
        server._MISSION_HOME = None
        self.env.stop()
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            with urlopen(Request(self.base + path, data=data, headers=headers), timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_repair_endpoint_retries_after_a_rollback(self) -> None:
        provider = SequencedSelfEditProvider()
        server.COORDINATOR.provider = provider
        status, body = self.request("/api/dev/repair", {"brief": "Fix the fixture test.", "attempts": 2})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["status"], "applied", body)
        self.assertEqual(body["attempts"], 2)
        self.assertEqual([item["status"] for item in body["history"]], ["rolled_back", "applied"])
        self.assertIn("assertEqual(2, 2)", (self.checkout / "tests" / "test_ok.py").read_text())
        self.assertIn("ROLLED BACK", provider.prompts[1])

    def test_repair_endpoint_rejects_an_empty_brief(self) -> None:
        status, body = self.request("/api/dev/repair", {"brief": "   "})
        self.assertEqual(status, 400, body)

    def wait_for_mission(self, mission_id: str, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, mission = self.request(f"/api/missions/{mission_id}")
            if mission.get("status") != "running":
                return mission
            time.sleep(0.05)
        self.fail("mission did not finish in time")

    def test_roles_endpoint_lists_all_fifty(self) -> None:
        status, body = self.request("/api/roles")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 50)
        self.assertEqual(len(body["phases"]), 9)
        self.assertEqual(body["roles"][0]["name"], "Chief Architect")

    def test_mission_runs_every_role_and_records_evidence(self) -> None:
        status, created = self.request("/api/missions", {"brief": "Build a small inventory application."})
        self.assertEqual(status, 202, created)
        mission = self.wait_for_mission(created["id"])
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["agents_recorded"], 50)
        self.assertEqual(mission["counts"]["contributed"], 50)
        self.assertTrue(all(run["output"] for run in mission["runs"]))

    def test_mission_list_and_agent_activity(self) -> None:
        _, created = self.request("/api/missions", {"brief": "Add a report to the inventory application."})
        self.wait_for_mission(created["id"])
        _, listed = self.request("/api/missions")
        self.assertEqual(len(listed), 1)
        _, stats = self.request("/api/agents/activity")
        self.assertEqual(len(stats), 50)
        self.assertTrue(all(item["runs"] == 1 for item in stats))

    def test_short_brief_is_rejected(self) -> None:
        status, body = self.request("/api/missions", {"brief": "hi"})
        self.assertEqual(status, 400)
        self.assertIn("mission", body["error"].lower())

    def test_dev_status_reflects_the_configured_checkout(self) -> None:
        status, body = self.request("/api/dev/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["enabled"])
        self.assertEqual(Path(body["root"]), self.checkout.resolve())

    def test_dev_apply_then_rollback(self) -> None:
        status, result = self.request("/api/dev/apply", {
            "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 42\n"}],
            "reason": "api test",
        })
        self.assertEqual(status, 201, result)
        self.assertEqual(result["status"], "applied")
        self.assertIn("VALUE = 42", (self.checkout / "src" / "babymind" / "mod.py").read_text())
        status, rolled = self.request("/api/dev/rollback", {"checkpoint_id": result["checkpoint_id"]})
        self.assertEqual(status, 200)
        self.assertIn("VALUE = 1", (self.checkout / "src" / "babymind" / "mod.py").read_text())
        self.assertEqual(rolled["status"], "rolled_back")

    def test_dev_apply_cannot_disable_verification(self) -> None:
        for value in (False, None, 0, "false"):
            with self.subTest(value=value):
                status, result = self.request("/api/dev/apply", {
                    "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 42\n"}],
                    "verify": value,
                })
                self.assertEqual(status, 400, result)
                self.assertIn("verified", result["error"])
                self.assertEqual((self.checkout / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_dev_preview_does_not_write(self) -> None:
        status, body = self.request("/api/dev/preview", {
            "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 7\n"}],
        })
        self.assertEqual(status, 200)
        self.assertIn("+VALUE = 7", body["files"][0]["diff"])
        self.assertIn("VALUE = 1", (self.checkout / "src" / "babymind" / "mod.py").read_text())

    def test_dev_rejects_path_traversal(self) -> None:
        status, body = self.request("/api/dev/apply", {"edits": [{"path": "../escape.py", "content": "x = 1\n"}]})
        self.assertEqual(status, 400)
        self.assertIn("path", body["error"].lower())

    def test_foreign_host_is_still_rejected(self) -> None:
        data = json.dumps({"brief": "Build a small inventory application."}).encode()
        request = Request(self.base + "/api/missions", data=data,
                          headers={"Content-Type": "application/json", "Host": "attacker.example"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_mission_self_edit_flag_is_recorded(self) -> None:
        status, created = self.request("/api/missions", {
            "brief": "Improve the module value.", "self_edit": True,
        })
        self.assertEqual(status, 202, created)
        self.assertTrue(created["self_edit"])
        mission = self.wait_for_mission(created["id"])
        # The stub provider never returns a JSON patch, so nothing may change.
        self.assertEqual(mission["self_edit"]["status"], "no_change")
        self.assertIn("VALUE = 1", (self.checkout / "src" / "babymind" / "mod.py").read_text())


if __name__ == "__main__":
    unittest.main()
