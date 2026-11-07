"""Tests for the permanent, supervised autonomous learning service.

The model and the OS sandbox are never invoked here: the verified cycle is
replaced with a deterministic report and timing is controlled by a fake clock.
What is tested is the supervisor itself: default-on state, durable scheduling,
gates, stop/reset, circuit breaking, locking, API/CLI wiring, the headless
launcher and the systemd unit installer.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from babymind import selfdev
from babymind.cli import build_parser
from babymind.learning_service import (
    DEFAULT_INTERVAL_SECONDS,
    ENV_ENABLED,
    ENV_INTERVAL,
    MAX_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    LearningService,
    _default_home,
    _parse_stamp,
    _release_lock,
    _try_exclusive_lock,
    build_service,
    control_service,
    desktop_session_active,
    enabled_by_environment,
    hold_desktop_session,
    interval_from_environment,
)

ROOT = Path(__file__).resolve().parents[1]


class DummyProvider:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return "{}"


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class LearningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.clock = FakeClock()
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.advance(seconds)

    def _service(self, **overrides) -> LearningService:
        kwargs = dict(
            home=self.home,
            interval=60,
            startup_delay=0,
            max_errors=2,
            provider_factory=lambda: DummyProvider(),
            gate_checker=lambda: {"ready": True, "reasons": [], "checks": {}},
            clock=self.clock,
            sleep=self.sleep,
        )
        kwargs.update(overrides)
        return build_service(**kwargs)

    def test_learning_is_default_on_with_an_environment_kill_switch(self) -> None:
        with patch.dict(os.environ, {ENV_ENABLED: "1"}):
            self.assertTrue(enabled_by_environment())
        for value in ("0", "false", "no", "off", "OFF"):
            with self.subTest(value=value), patch.dict(os.environ, {ENV_ENABLED: value}):
                self.assertFalse(enabled_by_environment())

    def test_interval_is_bounded(self) -> None:
        with patch.dict(os.environ, {ENV_INTERVAL: "1"}):
            self.assertEqual(interval_from_environment(), MIN_INTERVAL_SECONDS)
        with patch.dict(os.environ, {ENV_INTERVAL: "999999"}):
            self.assertEqual(interval_from_environment(), MAX_INTERVAL_SECONDS)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(interval_from_environment(), DEFAULT_INTERVAL_SECONDS)
        service = self._service()
        self.assertEqual(service.set_interval(1)["interval_seconds"], MIN_INTERVAL_SECONDS)
        self.assertEqual(service.set_interval(999999)["interval_seconds"], MAX_INTERVAL_SECONDS)
        self.assertTrue(service.runs()["audit"]["intact"])

    def test_durable_state_survives_supervisor_restart(self) -> None:
        service = self._service()
        service.pause()
        service.set_interval(300)
        service.stop(reason="Persist me.")
        self.assertEqual(service.status()["state"], "stopped")
        # A real restart does not pass an explicit interval; it must inherit the
        # operator-set value from the durable daemon state.
        restarted = self._service(interval=None)
        self.assertEqual(restarted.status()["state"], "stopped")
        self.assertEqual(restarted.status()["interval_seconds"], 300)
        self.assertTrue(restarted.stop_flag_present())
        self.assertTrue(restarted.runs()["audit"]["intact"])

    def test_start_and_foreground_service_preserve_durable_stop_states(self) -> None:
        for state_name in ("paused", "halted", "stopped"):
            with self.subTest(state=state_name):
                home = self.home / f"durable-{state_name}"
                service = self._service(home=home)
                if state_name == "paused":
                    service.pause()
                else:
                    service.store.set_daemon_state(state=state_name, last_skip_reason="durable")
                with patch("babymind.learning_service.threading.Thread") as thread:
                    started = service.start()
                self.assertTrue(started["started"])
                self.assertEqual(started["state"], state_name)
                self.assertEqual(service.store.daemon_state()["state"], state_name)
                thread.assert_called_once()
                service.request_stop()

                foreground = self._service(home=home, supervisor=True)
                foreground.gate_checker = lambda svc=foreground: {
                    "ready": svc.store.daemon_state().get("state") == "idle",
                    "reasons": ["durable stop state"], "checks": {},
                }
                with patch.object(foreground.learning, "run_autonomous_cycle") as cycle:
                    report = foreground.run_forever(max_cycles=1)
                self.assertEqual(report["cycles"], 1)
                cycle.assert_not_called()
                self.assertEqual(foreground.store.daemon_state()["state"], state_name)
                self.assertTrue(foreground.runs()["audit"]["intact"])

    def test_default_gates_fail_closed_when_any_prerequisite_is_missing(self) -> None:
        service = self._service(gate_checker=None)
        service.store.set_daemon_state(state="stopped")
        with patch.dict(os.environ, {ENV_ENABLED: "0", "BABYMIND_SANDBOX": "off"}), \
             patch("babymind.learning_service.selfdev.dev_root", return_value=ROOT), \
             patch("babymind.learning_service.selfdev.selfdev_enabled", return_value=True), \
             patch("babymind.sandbox.backend", return_value=SimpleNamespace(available=True, detail="ok")):
            gates = service._default_gates()
        self.assertFalse(gates["ready"])
        self.assertTrue(any("disables the autonomous supervisor" in reason for reason in gates["reasons"]))
        self.assertTrue(any("must be 'require'" in reason for reason in gates["reasons"]))
        self.assertTrue(any("stopped pending an operator reset" in reason for reason in gates["reasons"]))
        self.assertFalse(gates["checks"]["enabled_by_environment"])
        self.assertEqual(gates["checks"]["sandbox_policy"], "off")

    def test_stop_flag_blocks_cycles_until_reset(self) -> None:
        stop_path = self.home / "learning" / "STOP"

        def checker():
            if stop_path.exists():
                return {"ready": False, "reasons": ["A stop file is present."], "checks": {}}
            return {"ready": True, "reasons": [], "checks": {}}

        service = self._service(gate_checker=checker)
        report = {"decision": "kept", "cycle_id": "c1", "weakness_id": "w1", "reason": "verified"}
        with patch.object(service.learning, "run_autonomous_cycle", return_value=report) as cycle:
            service.stop(reason="Stop from test.")
            blocked = service.run_once(force=True)
            self.assertEqual(blocked["decision"], "skipped")
            cycle.assert_not_called()
            self.assertTrue(service.runs()["runs"])
            reset = service.reset()
            self.assertFalse(reset["stop_flag_present"])
            allowed = service.run_once(force=True)
            self.assertEqual(allowed["decision"], "kept")
            cycle.assert_called_once()
        self.assertFalse(stop_path.exists())
        self.assertEqual(service.store.daemon_state()["consecutive_errors"], 0)

    def test_consecutive_errors_halt_with_backoff_and_reset_clears_the_halt(self) -> None:
        service = self._service(max_errors=2)
        with patch.object(service.learning, "run_autonomous_cycle", side_effect=RuntimeError("boom")):
            first = service.run_once(force=True)
            second = service.run_once(force=True)
        self.assertEqual(first["consecutive_errors"], 1)
        self.assertFalse(first["halted"])
        self.assertTrue(second["halted"])
        state = service.store.daemon_state()
        self.assertEqual(state["state"], "halted")
        self.assertEqual(state["consecutive_errors"], 2)
        self.assertGreaterEqual(_parse_stamp(state["next_due_at"]) - self.clock.now, 239)
        service.reset()
        with patch.object(service.learning, "run_autonomous_cycle", return_value={"decision": "kept"}):
            recovered = service.run_once(force=True)
        self.assertEqual(recovered["decision"], "kept")
        self.assertEqual(service.store.daemon_state()["consecutive_errors"], 0)
        self.assertTrue(service.runs()["audit"]["intact"])

    def test_cycle_lock_prevents_overlapping_edits(self) -> None:
        first = self._service()
        second = self._service()
        with first.cycle_lock() as acquired:
            self.assertTrue(acquired)
            with second.cycle_lock() as blocked:
                self.assertFalse(blocked)
        with second.cycle_lock() as acquired_again:
            self.assertTrue(acquired_again)

    def test_supervisor_lock_parks_a_duplicate_service_in_standby(self) -> None:
        service = self._service(supervisor=True)
        handle = _try_exclusive_lock(service.supervisor_lock_path)
        self.assertIsNotNone(handle)
        service._wait_seconds = lambda seconds: service.request_stop()
        try:
            report = service.run_forever(max_cycles=1)
        finally:
            _release_lock(handle)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["state"], "standby")
        self.assertEqual(service.store.daemon_state()["state"], "standby")
        self.assertTrue(service.runs()["audit"]["intact"])

    def test_run_forever_schedules_and_records_verified_cycles(self) -> None:
        service = self._service()
        with patch.object(service.learning, "run_autonomous_cycle",
                          return_value={"decision": "kept", "cycle_id": "c1", "reason": "verified"}) as cycle:
            report = service.run_forever(max_cycles=2)
        self.assertEqual(report["cycles"], 2)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(service.store.daemon_state()["total_cycles"], 2)
        self.assertEqual(len(service.runs()["runs"]), 2)
        self.assertTrue(service.runs()["audit"]["intact"])
        self.assertGreater(len(self.waits), 0)

    def test_run_supervised_uses_the_shared_cycle_lock_and_verification_gate(self) -> None:
        service = self._service()
        with patch.object(service.learning, "run", return_value={"cycles": []}) as run, \
             patch.object(service, "_verification_ready", return_value=(True, "")):
            report = service.run_supervised(3)
        self.assertEqual(report, {"cycles": []})
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["cycles"], 3)
        with service.cycle_lock():
            with self.assertRaisesRegex(RuntimeError, "already running"):
                service.run_supervised(1)
        with patch.object(service, "_verification_ready", return_value=(False, "Verification gates are closed.")):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                service.run_supervised(1)

    def test_control_service_commands_need_no_model(self) -> None:
        with patch("babymind.model_router.ModelRouter", side_effect=AssertionError("model constructed")), \
             patch("babymind.providers.create_provider", side_effect=AssertionError("provider constructed")):
            service = control_service(home=self.home)
            self.assertEqual(service.pause()["state"], "paused")
            self.assertEqual(control_service(home=self.home).resume()["state"], "idle")
            self.assertFalse(control_service(home=self.home).disable()["enabled"])
            self.assertTrue(control_service(home=self.home).enable()["enabled"])
            self.assertTrue(control_service(home=self.home).stop()["stop_flag_present"])
            self.assertFalse(control_service(home=self.home).reset()["stop_flag_present"])

    def test_status_reports_autonomy_gates_and_durable_ledger(self) -> None:
        service = self._service()
        status = service.status()
        self.assertTrue(status["autonomous"])
        self.assertTrue(status["default_enabled"])
        self.assertTrue(status["gates"]["ready"])
        self.assertIn("recent_runs", status)
        self.assertIn("learning", status)
        self.assertTrue(status["learning"]["audit_chain_intact"])

    def test_all_entry_points_resolve_the_same_data_home(self) -> None:
        from babymind import first_run, independence, server

        with patch.dict(os.environ, {"BABYMIND_HOME": "~/babymind-home-parity"}):
            expected = Path.home() / "babymind-home-parity"
            self.assertEqual(first_run._data_home(), expected)
            self.assertEqual(independence._default_home(), expected)
            self.assertEqual(server._data_home(), expected)
            self.assertEqual(_default_home(), expected)
        custom = self.home / "custom-home"
        with patch.dict(os.environ, {"BABYMIND_HOME": str(custom)}):
            self.assertEqual(server._data_home(), custom)
            handle = hold_desktop_session()
            try:
                self.assertIsNotNone(handle)
                self.assertTrue(desktop_session_active())
                self.assertEqual(server._data_home(), _default_home())
            finally:
                _release_lock(handle)

    def test_cli_exposes_the_permanent_learning_controls(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["learning", "status"])
        self.assertEqual((args.command, args.learning_action), ("learning", "status"))
        args = parser.parse_args(["learning", "interval", "300"])
        self.assertEqual(args.seconds, 300.0)
        args = parser.parse_args(["learning", "service", "--interval", "120", "--max-cycles", "2"])
        self.assertEqual((args.interval, args.max_cycles), (120.0, 2))
        args = parser.parse_args(["learning", "stop", "--reason", "maintenance"])
        self.assertEqual(args.reason, "maintenance")
        for action in ("runs", "run-once", "pause", "resume", "enable", "disable", "reset"):
            with self.subTest(action=action):
                self.assertEqual(parser.parse_args(["learning", action]).learning_action, action)

    def test_desktop_launcher_has_a_headless_service_mode(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "run_desktop.py"), "--learning-service", "--help"],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--learning-service", result.stdout)
        self.assertIn("--max-cycles", result.stdout)
        self.assertIn("--interval", result.stdout)
        env = {**os.environ, "BABYMIND_HOME": str(self.home),
               "BABYMIND_SANDBOX": "require"}
        cli = subprocess.run(
            [sys.executable, str(ROOT / "run_desktop.py"), "learning", "status"],
            text=True, capture_output=True, timeout=20, env=env,
        )
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertIn('"autonomous": true', cli.stdout)
        self.assertIn('"default_enabled": true', cli.stdout)


class LearningServiceInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.script = ROOT / "scripts" / "install-learning-service.sh"

    def test_script_passes_bash_syntax_check(self) -> None:
        result = subprocess.run(["bash", "-n", str(self.script)], text=True,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_renders_a_fail_closed_restarting_unit(self) -> None:
        result = subprocess.run(
            ["bash", str(self.script), "--dry-run", "--launcher", "/opt/BabyMind App/babymind",
             "--model-filename", "Fixture 100%.gguf", "--if-available"],
            text=True, capture_output=True, timeout=20, env={**os.environ, "HOME": str(self.home)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ExecStart="/opt/BabyMind App/babymind" --learning-service', result.stdout)
        self.assertIn("Restart=always", result.stdout)
        self.assertIn("RestartSec=30", result.stdout)
        self.assertIn("KillSignal=SIGTERM", result.stdout)
        self.assertIn('Environment="BABYMIND_SANDBOX=require"', result.stdout)
        self.assertIn('Environment="BABYMIND_GGUF_MODEL=%h/.babymind/models/Fixture 100%%.gguf"', result.stdout)
        self.assertIn("EnvironmentFile=-%h/.config/babymind/models.env", result.stdout)
        self.assertIn("WantedBy=default.target", result.stdout)

    def test_if_available_skips_when_no_systemd_user_session_exists(self) -> None:
        unit = self.home / "babymind-learning.service"
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        systemctl = bin_dir / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 1\n")
        systemctl.chmod(0o755)
        env = {**os.environ, "HOME": str(self.home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        result = subprocess.run(
            ["bash", str(self.script), "--if-available", "--unit-path", str(unit)],
            text=True, capture_output=True, timeout=20, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no running systemd user session", result.stderr)
        self.assertFalse(unit.exists())

    def test_install_writes_the_unit_and_enables_the_service(self) -> None:
        launcher_dir = self.home / "launch dir"
        launcher_dir.mkdir()
        launcher = launcher_dir / "babymind"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o755)
        unit = self.home / ".config/systemd/user/babymind-learning.service"
        log = self.home / "systemctl.log"
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$LEARNING_SYSTEMCTL_LOG\"\nexit 0\n"
        )
        systemctl.chmod(0o755)
        env = {**os.environ, "HOME": str(self.home),
               "PATH": f"{bin_dir}:{os.environ['PATH']}", "LEARNING_SYSTEMCTL_LOG": str(log)}
        result = subprocess.run(
            ["bash", str(self.script), "--launcher", str(launcher), "--unit-path", str(unit)],
            text=True, capture_output=True, timeout=20, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("installed and enabled", result.stdout)
        self.assertIn(f'ExecStart="{launcher}" --learning-service', unit.read_text())
        self.assertEqual(unit.stat().st_mode & 0o777, 0o644)
        env_file = self.home / ".config/babymind/models.env"
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
        commands = log.read_text()
        self.assertIn("--user show-environment", commands)
        self.assertIn("--user daemon-reload", commands)
        self.assertIn("--user enable --now babymind-learning.service", commands)


if __name__ == "__main__":
    unittest.main()
