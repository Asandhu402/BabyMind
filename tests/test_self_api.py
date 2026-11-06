"""API tests for the self-model, introspection and autonomy endpoints."""
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

from babymind import server


class FakeProvider:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return "A plain answer."


class SelfApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.original = (server.DB_PATH, server.DATA_HOME, server.COORDINATOR.provider)
        server.DATA_HOME = Path(self.temp.name) / "data"
        server.DATA_HOME.mkdir(parents=True, exist_ok=True)
        server.DB_PATH = server.DATA_HOME / "app.sqlite3"
        server.init_db()
        server.COORDINATOR.provider = FakeProvider()
        # Give the coordinator an isolated self-model and autonomy engine.
        self.selfmodel = server.COORDINATOR.selfmodel
        self.env = patch.dict(os.environ, {"BABYMIND_AUTONOMY": "0"})
        self.env.start()
        server._AUTONOMY = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.auth_token = None
        self.httpd.lan_ip = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH, server.DATA_HOME, server.COORDINATOR.provider = self.original
        server._AUTONOMY = None
        self.env.stop()
        self.temp.cleanup()

    def request(self, path: str, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            with urlopen(Request(self.base + path, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET")), timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    # ------------------------------------------------------------ self-model

    def test_self_status_reports_identity_voice_and_calibration(self):
        status, body = self.request("/api/self/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["identity"]["name"], "BabyMind")
        self.assertIn(body["voice_mode"], ("plain", "reflective", "guarded"))
        self.assertEqual(len(body["voice_invariants"]), 4)
        self.assertIn("calibration", body)
        self.assertIn("beliefs", body)

    def test_voice_mode_can_be_set_and_is_persisted(self):
        status, body = self.request("/api/self/voice", {"mode": "guarded"})
        self.assertEqual(status, 200)
        self.assertEqual(body["voice_mode"], "guarded")
        _, again = self.request("/api/self/status")
        self.assertEqual(again["voice_mode"], "guarded")

    def test_invalid_voice_mode_is_rejected(self):
        status, body = self.request("/api/self/voice", {"mode": "sentient"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_belief_can_be_added_listed_and_retired(self):
        status, belief = self.request("/api/self/belief", {
            "kind": "limit", "claim": "I cannot reach the network from a cycle.",
            "confidence": 0.85, "evidence": "No network tool is wired in.", "source": "user",
        })
        self.assertEqual(status, 201)
        _, report = self.request("/api/self/status")
        self.assertIn("I cannot reach the network from a cycle.",
                      [item["claim"] for item in report["beliefs"]["limit"]])

        status, _ = self.request(f"/api/self/belief/{belief['id']}", method="DELETE")
        self.assertEqual(status, 200)
        _, report = self.request("/api/self/status")
        self.assertNotIn("I cannot reach the network from a cycle.",
                         [item["claim"] for item in report["beliefs"]["limit"]])

    def test_empty_belief_claim_is_rejected(self):
        status, _ = self.request("/api/self/belief", {"kind": "limit", "claim": "  "})
        self.assertEqual(status, 400)

    def test_unknown_belief_delete_returns_404(self):
        status, _ = self.request("/api/self/belief/does-not-exist", method="DELETE")
        self.assertEqual(status, 404)

    def test_belief_can_be_revised(self):
        _, belief = self.request("/api/self/belief", {"kind": "lesson", "claim": "Old lesson."})
        status, revised = self.request("/api/self/belief/revise", {
            "id": belief["id"], "claim": "New lesson.", "confidence": 0.9,
        })
        self.assertEqual(status, 200)
        self.assertEqual(revised["claim"], "New lesson.")
        self.assertEqual(revised["revision"], 2)

    def test_revising_a_missing_belief_returns_404(self):
        status, _ = self.request("/api/self/belief/revise", {"id": "nope", "claim": "x"})
        self.assertEqual(status, 404)

    def test_dissent_and_introspection_endpoints_are_readable(self):
        _, _ = self.request("/api/self/dissent")
        status, body = self.request("/api/self/introspections")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    # ------------------------------------------------------------- autonomy

    def test_autonomy_starts_stopped_and_reports_its_bounds(self):
        status, body = self.request("/api/autonomy/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "stopped")
        self.assertIn("write_file", body["action_kinds"])
        self.assertTrue(body["audit"]["chain_intact"])
        self.assertIn("max_cycles", body["limits"])

    def test_autonomy_start_is_refused_without_arming(self):
        status, body = self.request("/api/autonomy/start", {"cycles": 1})
        self.assertEqual(status, 403)
        self.assertFalse(body["started"])
        self.assertIn("armed", body["reason"])

    def test_goal_can_be_added_and_listed(self):
        status, goal = self.request("/api/autonomy/goal", {"title": "Keep a learning journal"})
        self.assertEqual(status, 201)
        _, goals = self.request("/api/autonomy/goals")
        self.assertIn("Keep a learning journal", [item["title"] for item in goals])

    def test_empty_goal_is_rejected(self):
        status, _ = self.request("/api/autonomy/goal", {"title": "   "})
        self.assertEqual(status, 400)

    def test_start_without_any_goal_is_refused(self):
        status, body = self.request("/api/autonomy/start", {"cycles": 1, "confirm": True})
        self.assertEqual(status, 200)
        self.assertFalse(body["started"])
        self.assertIn("goal", body["reason"])

    def test_autonomy_runs_and_stops_with_an_intact_audit_chain(self):
        self.request("/api/autonomy/goal", {"title": "Take one note"})
        status, body = self.request("/api/autonomy/start", {"cycles": 1, "interval": 0, "confirm": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["started"], body)

        deadline = 10.0
        engine = server.autonomy_engine()
        while engine.state == "running" and deadline > 0:
            import time
            time.sleep(0.05)
            deadline -= 0.05

        status, body = self.request("/api/autonomy/stop", {"reason": "API test finished."})
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "stopped")

        _, audit = self.request("/api/autonomy/audit")
        self.assertTrue(audit["chain"]["intact"])
        kinds = [entry["kind"] for entry in audit["entries"]]
        self.assertIn("started", kinds)
        self.assertIn("stopped", kinds)

    def test_stop_is_idempotent_and_drops_a_stop_file(self):
        self.request("/api/autonomy/stop", {"reason": "First stop."})
        status, body = self.request("/api/autonomy/stop", {"reason": "Second stop."})
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "stopped")
        _, status_body = self.request("/api/autonomy/status")
        self.assertTrue(status_body["stop_flag_present"])

    def test_reset_clears_the_stop_flag(self):
        self.request("/api/autonomy/stop", {"reason": "Stopped."})
        status, _ = self.request("/api/autonomy/reset", {})
        self.assertEqual(status, 200)
        _, status_body = self.request("/api/autonomy/status")
        self.assertFalse(status_body["stop_flag_present"])

    def test_pause_and_resume_round_trip(self):
        self.request("/api/autonomy/goal", {"title": "A goal"})
        self.request("/api/autonomy/start", {"cycles": 50, "interval": 5, "confirm": True})
        status, body = self.request("/api/autonomy/pause", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["changed"])
        status, body = self.request("/api/autonomy/resume", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["changed"])
        self.request("/api/autonomy/stop", {"reason": "Done."})

    def test_stepping_a_cycle_while_stopped_is_conflict(self):
        status, _ = self.request("/api/autonomy/cycle", {})
        self.assertEqual(status, 409)

    def test_audit_chain_detects_a_removed_entry(self):
        self.request("/api/autonomy/goal", {"title": "One"})
        self.request("/api/autonomy/goal", {"title": "Two"})
        self.request("/api/autonomy/goal", {"title": "Three"})
        import sqlite3
        with sqlite3.connect(server.autonomy_engine().database_path) as connection:
            connection.execute("DELETE FROM autonomy_audit WHERE seq = 2")
        _, audit = self.request("/api/autonomy/audit")
        self.assertFalse(audit["chain"]["intact"])
        self.assertEqual(audit["chain"]["broken_at_seq"], 3)


if __name__ == "__main__":
    unittest.main()
