"""Long-running, supervised cognitive service for Linux systemd.

The loop is intentionally conservative: one verified cognitive cycle at a time,
a minimum interval, a process lock, bounded consecutive-error backoff, and clean
SIGTERM/SIGINT handling. It does not grant new action permissions.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from .autonomy import AutonomyController
from .coordinator import BabyMindCoordinator
from .cognitive_core import CognitiveCore

MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 3600
MAX_CONSECUTIVE_ERRORS = 5


class BackgroundService:
    def __init__(self, *, interval: float = 60, agent_id: str = "BM-01",
                 core: CognitiveCore | None = None, coordinator: BabyMindCoordinator | None = None):
        if not MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
            raise ValueError(f"Interval must be between {MIN_INTERVAL_SECONDS} and {MAX_INTERVAL_SECONDS} seconds.")
        self.interval = float(interval)
        self.agent_id = agent_id.strip().upper()
        self.core = core or CognitiveCore()
        self.coordinator = coordinator or BabyMindCoordinator()
        self.controller = AutonomyController(self.core)
        self._stop = False

    def request_stop(self, *_: object) -> None:
        self._stop = True

    def run(self, *, max_cycles: int | None = None) -> dict[str, Any]:
        """Run until signalled or max_cycles is reached; max_cycles is for tests."""
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive.")
        lock_path = self.core.database_path.with_name("background-service.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another BabyMind cognitive background service is already running.") from error
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(str(os.getpid()))
            lock_file.flush()

            previous = {}
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.getsignal(sig)
                signal.signal(sig, self.request_stop)
            cycles = 0
            verified = 0
            errors = 0
            last_result: dict[str, Any] | None = None
            try:
                while not self._stop and (max_cycles is None or cycles < max_cycles):
                    try:
                        report = self.controller.run(
                            self.coordinator.model_router, cycles=1, interval=0,
                            agent_id=self.agent_id,
                        )
                        last_result = report
                        cycles += int(report.get("completed_cycles", 0))
                        verified += int(report.get("verified_cycles", 0))
                        if report.get("status") != "completed" or report.get("verified_cycles") != 1:
                            raise RuntimeError("Cognitive cycle did not complete successfully.")
                        errors = 0
                        delay = self.interval
                    except Exception as error:
                        errors += 1
                        note = f"Background cycle error {errors}: {type(error).__name__}: {error}"[:1000]
                        try:
                            self.core._apply_action({"type": "write_note", "content": note})
                        except Exception:
                            pass
                        if errors >= MAX_CONSECUTIVE_ERRORS:
                            return {"status": "stopped_after_errors", "cycles": cycles,
                                    "verified_cycles": verified, "consecutive_errors": errors,
                                    "last_error": note, "last_result": last_result}
                        delay = min(self.interval * (2 ** errors), MAX_INTERVAL_SECONDS)
                    if self._stop or (max_cycles is not None and cycles >= max_cycles):
                        break
                    # Sleep in short slices so systemd stop requests are responsive.
                    deadline = time.monotonic() + delay
                    while not self._stop and time.monotonic() < deadline:
                        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.flush()
            return {"status": "stopped" if self._stop else "completed",
                    "cycles": cycles, "verified_cycles": verified,
                    "consecutive_errors": errors, "last_result": last_result}
