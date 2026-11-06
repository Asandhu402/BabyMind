"""Tests for BabyMind's bounded autonomous operation.

These focus on the safety machinery: that the engine can be stopped, that it
stays inside its workspace, that budgets are honoured, and that its audit log
can detect tampering.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from babymind.autonomy import DEFAULT_LIMITS, AutonomyEngine


class ScriptedProvider:
    def __init__(self, action):
        self.action = action
        self.calls = 0

    def complete(self, system_prompt, user_prompt):
        self.calls += 1
        return json.dumps({
            "goal_id": "", "plan": "do the thing",
            "action": self.action, "expected": "it works", "reflection_cue": "noted",
        })


def plan(action):
    return ScriptedProvider(action)


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = AutonomyEngine(
            plan({"type": "wait"}),
            database_path=self.root / "autonomy.sqlite3",
            workspace=self.root / "ws",
        )

    # ------------------------------------------------------------- lifecycle

    def test_starts_stopped_and_off(self):
        self.assertEqual(self.engine.state, "stopped")
        self.assertFalse(self.engine.status()["enabled"])

    def test_adding_a_goal_is_audited(self):
        goal = self.engine.add_goal("Keep a learning journal", "Write one note per cycle.")
        self.assertEqual(goal["status"], "active")
        self.assertEqual(self.engine.goals("active")[0]["title"], "Keep a learning journal")
        self.assertIn("goal_created", [entry["kind"] for entry in self.engine.audit_log()])

    def test_empty_goal_title_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.add_goal("   ")

    def test_start_requires_a_goal(self):
        result = self.engine.start()
        self.assertFalse(result["started"])
        self.assertIn("goal", result["reason"])

    def test_start_requires_a_provider(self):
        self.engine.add_goal("Something")
        self.engine.provider = None
        result = self.engine.start()
        self.assertFalse(result["started"])
        self.assertIn("provider", result["reason"])

    def test_start_is_refused_while_a_stop_file_is_present(self):
        self.engine.add_goal("Something")
        self.engine.stop(reason="Testing the stop file.")
        result = self.engine.start()
        self.assertFalse(result["started"])
        self.assertIn("stop file", result["reason"])

    def test_reset_clears_the_stop_file_and_a_halt(self):
        self.engine.state = "halted"
        self.engine.stop()
        self.engine.reset()
        self.assertFalse(self.engine.stop_requested())
        self.assertEqual(self.engine.state, "stopped")
        self.assertEqual(self.engine.consecutive_failures, 0)

    # --------------------------------------------------------------- stopping

    def test_stop_sets_a_stop_file_that_survives_restart(self):
        self.engine.stop(reason="Operator stopped it.")
        self.assertTrue(self.engine.stop_requested())
        self.assertEqual(AutonomyEngine(
            plan({"type": "wait"}),
            database_path=self.root / "autonomy.sqlite3",
            workspace=self.root / "ws",
        ).stop_requested(), True)

    def test_clear_stop_flag_allows_a_start_again(self):
        self.engine.add_goal("Something")
        self.engine.stop()
        self.engine.clear_stop_flag()
        self.addCleanup(self.engine.stop)
        result = self.engine.start(cycles=1, interval=0)
        self.assertTrue(result["started"], result.get("reason"))
        # Let the loop finish naturally, then assert on the reason it gave.
        self.wait_for_exit(self.engine)
        self.assertEqual(self.engine.cycles_run, 1)
        self.assertIn("Cycle budget", self.engine.last_stop_reason)

    def wait_for_exit(self, engine, timeout=15.0):
        """Wait for the loop to reach a terminal state on its own."""
        deadline = time.monotonic() + timeout
        while engine.state == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        if engine.thread is not None:
            engine.thread.join(timeout=timeout)
        return engine.state

    def settle(self, engine, timeout=15.0):
        """Force-stop the engine and join its thread, so no test leaves a
        background thread writing to a deleted temporary directory."""
        self.addCleanup(engine.stop)
        engine.stop(reason="Test finished.")
        return self.wait_for_exit(engine, timeout)

    def test_stop_flag_is_checked_before_the_action_runs(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "note.txt", "content": "should not be written"}),
            database_path=self.root / "a2.sqlite3",
            workspace=self.root / "ws2",
        )
        engine.add_goal("Write something")
        engine.stop_flag_path.write_text("stop\n")
        outcome = engine.run_cycle(1)
        self.assertIn("Stop requested", outcome.outcome)
        self.assertFalse(outcome.verified)
        self.assertFalse((self.root / "ws2" / "note.txt").exists())

    def test_pause_and_resume_round_trip(self):
        self.engine.state = "running"
        self.assertTrue(self.engine.pause()["changed"])
        self.assertEqual(self.engine.state, "paused")
        self.assertTrue(self.engine.resume()["changed"])
        self.assertEqual(self.engine.state, "running")

    def test_resume_is_refused_while_a_stop_file_is_present(self):
        self.engine.state = "paused"
        self.engine.stop_flag_path.write_text("stop\n")
        result = self.engine.resume()
        self.assertFalse(result["changed"])
        self.assertEqual(self.engine.state, "paused")

    # ------------------------------------------------------------ confinement

    def test_path_escape_is_refused(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "../../escaped.txt", "content": "pwned"}),
            database_path=self.root / "a3.sqlite3",
            workspace=self.root / "ws3",
        )
        engine.add_goal("Escape")
        outcome = engine.run_cycle(1)
        self.assertIn("confined", outcome.outcome)
        self.assertFalse(outcome.verified)
        self.assertFalse((self.root.parent / "escaped.txt").exists())

    def test_symbolic_link_writes_are_refused(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "link.txt", "content": "x"}),
            database_path=self.root / "a4.sqlite3",
            workspace=self.root / "ws4",
        )
        target = self.root / "outside-target.txt"
        (self.root / "ws4").mkdir(parents=True, exist_ok=True)
        (self.root / "ws4" / "link.txt").symlink_to(target)
        engine.add_goal("Write through a link")
        outcome = engine.run_cycle(1)
        self.assertIn("symbolic link", outcome.outcome)
        self.assertFalse(target.exists())

    def test_legitimate_write_is_verified_by_read_back(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "notes/today.md", "content": "# Learned today"}),
            database_path=self.root / "a5.sqlite3",
            workspace=self.root / "ws5",
        )
        engine.add_goal("Journal")
        outcome = engine.run_cycle(1)
        self.assertTrue(outcome.verified)
        self.assertEqual((self.root / "ws5" / "notes" / "today.md").read_text(), "# Learned today")

    def test_unsupported_action_kinds_are_refused(self):
        engine = AutonomyEngine(
            plan({"type": "run_shell", "command": "rm -rf /"}),
            database_path=self.root / "a6.sqlite3",
            workspace=self.root / "ws6",
        )
        engine.add_goal("Do something dangerous")
        outcome = engine.run_cycle(1)
        self.assertIn("Unsupported autonomous action", outcome.outcome)
        self.assertFalse(outcome.verified)

    def test_oversized_writes_are_refused(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "huge.txt", "content": "x" * (256 * 1024 + 1)}),
            database_path=self.root / "a7.sqlite3",
            workspace=self.root / "ws7",
        )
        engine.add_goal("Write a huge file")
        self.assertIn("will not write more than", engine.run_cycle(1).outcome)

    # --------------------------------------------------------------- budgets

    def test_write_budget_halts_the_engine(self):
        engine = AutonomyEngine(
            plan({"type": "write_file", "path": "a.txt", "content": "x" * 1000}),
            database_path=self.root / "a8.sqlite3",
            workspace=self.root / "ws8",
            limits={"max_bytes_written": 500},
        )
        engine.add_goal("Write")
        outcome = engine.run_cycle(1)
        self.assertIn("budget", outcome.outcome)
        self.assertEqual(engine.state, "halted")

    def test_halted_engine_cannot_be_restarted_without_a_reset(self):
        self.engine.state = "halted"
        self.engine.last_stop_reason = "Repeated failures."
        result = self.engine.start()
        self.assertFalse(result["started"])
        self.assertIn("must be reset", result["reason"])

    def test_action_rate_limit_is_enforced(self):
        engine = AutonomyEngine(
            plan({"type": "append_note", "content": "a note"}),
            database_path=self.root / "a9.sqlite3",
            workspace=self.root / "ws9",
            limits={"max_actions_per_hour": 2},
        )
        engine.add_goal("Take notes")
        self.assertTrue(engine.run_cycle(1).verified)
        self.assertTrue(engine.run_cycle(2).verified)
        third = engine.run_cycle(3)
        self.assertEqual(engine.state, "halted")
        self.assertIn("rate", third.stopped_reason)

    # ------------------------------------------------------- circuit breaker

    def test_repeated_failures_halt_the_engine(self):
        engine = AutonomyEngine(
            ScriptedProvider({"type": "run_shell"}),
            database_path=self.root / "a10.sqlite3",
            workspace=self.root / "ws10",
            limits={"consecutive_failures_before_halt": 2},
        )
        engine.add_goal("Fail repeatedly")
        engine.run_cycle(1)
        engine.run_cycle(2)
        self.assertEqual(engine.state, "halted")
        self.assertIn("halted", [entry["kind"] for entry in engine.audit_log()])

    def test_a_success_resets_the_failure_counter(self):
        engine = AutonomyEngine(
            ScriptedProvider({"type": "append_note", "content": "ok"}),
            database_path=self.root / "a11.sqlite3",
            workspace=self.root / "ws11",
            limits={"consecutive_failures_before_halt": 2},
        )
        engine.add_goal("Succeed")
        engine.run_cycle(1)
        engine.run_cycle(2)
        self.assertEqual(engine.consecutive_failures, 0)
        self.assertNotEqual(engine.state, "halted")

    def test_unparseable_plan_does_not_raise_and_is_recorded(self):
        class Broken:
            def complete(self, system_prompt, user_prompt):
                return "this is not json"

        engine = AutonomyEngine(Broken(), database_path=self.root / "a12.sqlite3",
                                workspace=self.root / "ws12")
        engine.add_goal("Something")
        outcome = engine.run_cycle(1)
        self.assertIn("Planning failed", outcome.outcome)
        self.assertIn("plan_failed", [entry["kind"] for entry in engine.audit_log()])

    def test_plan_without_an_action_object_is_recorded(self):
        class NoAction:
            def complete(self, system_prompt, user_prompt):
                return json.dumps({"plan": "thinking about it"})

        engine = AutonomyEngine(NoAction(), database_path=self.root / "a13.sqlite3",
                                workspace=self.root / "ws13")
        engine.add_goal("Something")
        outcome = engine.run_cycle(1)
        self.assertIn("no action object", outcome.outcome)

    # ------------------------------------------------------------ audit chain

    def test_audit_chain_verifies_as_intact(self):
        self.engine.add_goal("Goal one")
        self.engine.add_goal("Goal two")
        chain = self.engine.verify_audit_chain()
        self.assertTrue(chain["intact"])
        self.assertGreaterEqual(chain["entries"], 2)

    def test_removing_a_middle_entry_breaks_the_chain(self):
        # Deleting the newest entry leaves a shorter but valid chain; removing
        # one from the middle leaves the next entry pointing at a hash that is
        # no longer the one before it, which is the detectable case.
        self.engine.add_goal("Goal one")
        self.engine.add_goal("Goal two")
        self.engine.add_goal("Goal three")
        import sqlite3
        with sqlite3.connect(self.engine.database_path) as connection:
            connection.execute("DELETE FROM autonomy_audit WHERE seq = 2")
        chain = self.engine.verify_audit_chain()
        self.assertFalse(chain["intact"])
        self.assertEqual(chain["broken_at_seq"], 3)
        self.assertIn("altered", chain["reason"])

    def test_rewriting_an_entry_breaks_the_chain(self):
        self.engine.add_goal("Goal one")
        self.engine.add_goal("Goal two")
        import sqlite3
        with sqlite3.connect(self.engine.database_path) as connection:
            connection.execute(
                "UPDATE autonomy_audit SET entry_hash = ? WHERE seq = 1",
                ("f" * 64,),
            )
        self.assertFalse(self.engine.verify_audit_chain()["intact"])

    def test_audit_payload_is_encrypted_at_rest(self):
        self.engine.add_goal("A private goal title")
        import sqlite3
        with sqlite3.connect(self.engine.database_path) as connection:
            stored = connection.execute("SELECT payload FROM autonomy_audit").fetchone()[0]
        self.assertNotIn("private goal title", stored)
        self.assertTrue(stored.startswith("bmenc:v1:"))

    def test_audit_entries_are_linked_to_the_previous_hash(self):
        self.engine.add_goal("One")
        self.engine.add_goal("Two")
        entries = sorted(self.engine.audit_log(50), key=lambda item: item["seq"])
        self.assertEqual(entries[0]["prev_hash"], "0" * 64)
        self.assertEqual(entries[1]["prev_hash"], entries[0]["entry_hash"])

    # ----------------------------------------------------------------- status

    def test_status_reports_state_budgets_and_workspace(self):
        status = self.engine.status()
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(Path(status["workspace"]), self.root / "ws")
        self.assertIn("cycles_used", status["budget"])
        self.assertTrue(status["audit"]["chain_intact"])
        for kind in ("write_file", "append_note", "create_goal", "complete_goal", "wait"):
            self.assertIn(kind, status["action_kinds"])

    def test_default_limits_are_finite_and_bounded(self):
        for key, value in DEFAULT_LIMITS.items():
            self.assertIsInstance(value, int)
            self.assertGreater(value, 0)

    # ---------------------------------------------------------- the real loop

    def test_background_loop_stops_on_request_within_one_step(self):
        engine = AutonomyEngine(
            plan({"type": "append_note", "content": "tick"}),
            database_path=self.root / "a14.sqlite3",
            workspace=self.root / "ws14",
            limits={"max_cycles": 100, "max_seconds": 60, "max_actions_per_hour": 100},
        )
        engine.add_goal("Tick")
        self.assertTrue(engine.start(cycles=100, interval=0.2)["started"])
        deadline = time.monotonic() + 10
        while engine.cycles_run < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.settle(engine), "stopped")
        self.assertGreater(engine.cycles_run, 0)
        self.assertLess(engine.cycles_run, 100)
        self.assertTrue(engine.verify_audit_chain()["intact"])

    def test_loop_respects_the_cycle_budget(self):
        engine = AutonomyEngine(
            plan({"type": "wait"}),
            database_path=self.root / "a15.sqlite3",
            workspace=self.root / "ws15",
            limits={"max_actions_per_hour": 100},
        )
        engine.add_goal("Wait a lot")
        self.addCleanup(engine.stop)
        self.assertTrue(engine.start(cycles=3, interval=0)["started"])
        self.wait_for_exit(engine)
        self.assertEqual(engine.cycles_run, 3)
        self.assertIn("Cycle budget", engine.last_stop_reason)


if __name__ == "__main__":
    unittest.main()
