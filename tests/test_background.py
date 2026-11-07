"""Tests for the Linux cognitive background service."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from babymind.background import BackgroundService
from babymind.cognitive_core import CognitiveCore


class BackgroundServiceTests(unittest.TestCase):
    def test_interval_is_bounded(self):
        with self.assertRaises(ValueError):
            BackgroundService(interval=1, coordinator=MagicMock(), core=MagicMock())
        with self.assertRaises(ValueError):
            BackgroundService(interval=3601, coordinator=MagicMock(), core=MagicMock())

    def test_finite_test_run_executes_cycles_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            core = CognitiveCore(Path(folder) / "cognitive.sqlite3")
            coordinator = MagicMock()
            coordinator.provider = MagicMock()
            service = BackgroundService(interval=5, core=core, coordinator=coordinator)
            service.controller.run = MagicMock(return_value={
                "status": "completed", "completed_cycles": 1, "verified_cycles": 1
            })
            report = service.run(max_cycles=2)
            self.assertEqual(report["cycles"], 2)
            self.assertEqual(report["verified_cycles"], 2)
            self.assertEqual(service.controller.run.call_count, 2)

    def test_duplicate_service_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            core = CognitiveCore(Path(folder) / "cognitive.sqlite3")
            service1 = BackgroundService(interval=5, core=core, coordinator=MagicMock())
            service2 = BackgroundService(interval=5, core=core, coordinator=MagicMock())
            with patch("babymind.background.signal.signal"):
                with service1.core.database_path.with_name("background-service.lock").open("a+") as f:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(RuntimeError):
                        service2.run(max_cycles=1)

    def test_install_script_is_present_and_linux_scoped(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "install-cognitive-service.sh"
        self.assertIn("systemd", path.read_text(encoding="utf-8"))
        self.assertIn("x86_64", path.read_text(encoding="utf-8"))

    def test_learning_service_install_script_is_headless_and_fail_closed(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "install-learning-service.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("--learning-service", text)
        self.assertIn("Restart=always", text)
        self.assertIn("KillSignal=SIGTERM", text)
        self.assertIn("BABYMIND_SANDBOX=require", text)
        self.assertIn("EnvironmentFile=-%h/.config/babymind/models.env", text)
        self.assertIn("enable --now babymind-learning.service", text)


if __name__ == "__main__":
    unittest.main()
