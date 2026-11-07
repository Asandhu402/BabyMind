"""Permanent, supervised autonomous learning service for BabyMind.

The verified learning cycle in :mod:`babymind.learning` is one unit of work.
This module is the **supervisor**: it is started by the desktop/server entry
points without an operator request, persists its schedule and ledger across
restarts, and can also run as an enabled Linux systemd user service. It does
not grant new permissions. Every cycle still goes through the coding engine's
path guard, self-development checkpoints, fail-closed sandbox policy, compile
and full test suite, behavioral evaluation, automatic rollback and the
hash-chained learning audit.

The loop is "permanent" in the software sense: enabled by default, restarted
with the installation, durable across crashes, and never requiring a person to
press Run. It is not permanent inference or an unbounded agent. A stop file,
API/CLI controls, a circuit breaker, a per-cycle process lock, an idle
backoff, a protected-path policy and an intact-audit-chain requirement can all
stop it. Weakness identification and behavioral evaluation remain
model-generated; only compilation, tests, rollback and local state changes are
measured.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:  # Linux is the only supported desktop target; keep imports testable.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX development only
    fcntl = None  # type: ignore[assignment]

from . import selfdev
from .independence import Independence, _clean, _default_home, _now

MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86_400
DEFAULT_INTERVAL_SECONDS = 1_800
DEFAULT_STARTUP_DELAY_SECONDS = 300
MAX_BACKOFF_SECONDS = 21_600
SKIP_RETRY_SECONDS = 60
DEFAULT_MAX_CONSECUTIVE_ERRORS = 5

ENV_ENABLED = "BABYMIND_LEARNING_AUTONOMOUS"
ENV_INTERVAL = "BABYMIND_LEARNING_INTERVAL_SECONDS"
ENV_STARTUP_DELAY = "BABYMIND_LEARNING_STARTUP_DELAY_SECONDS"
ENV_MAX_ERRORS = "BABYMIND_LEARNING_MAX_CONSECUTIVE_ERRORS"

DISABLED_VALUES = {"0", "false", "no", "off"}
# An operator pause, a circuit-breaker halt and the durable kill switch must all
# survive a process restart. Startup may clear only transient states.
DURABLE_STOP_STATES = frozenset({"paused", "halted", "stopped"})


def enabled_by_environment() -> bool:
    """Autonomous learning is on unless the operator explicitly disables it."""
    return os.getenv(ENV_ENABLED, "1").strip().lower() not in DISABLED_VALUES


def interval_from_environment(default: float = DEFAULT_INTERVAL_SECONDS) -> float:
    try:
        value = float(os.getenv(ENV_INTERVAL, str(default)) or default)
    except (TypeError, ValueError):
        return default
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, value))


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(float(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _parse_stamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _lock_path(home: Path, name: str) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    return home / name


def _try_exclusive_lock(path: Path):
    """Return an open, exclusively locked handle, or ``None`` if unavailable."""
    if fcntl is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def _release_lock(handle) -> None:
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def hold_desktop_session(home: str | Path | None = None):
    """Hold a shared session lock for a running desktop/server process.

    The standalone learning service uses this to stay idle while the app is
    open: the in-process supervisor already owns learning and shares the model.
    Returns an open handle that the caller must keep alive, or ``None`` when
    another process already holds an exclusive-compatible lock.
    """
    home_path = Path(home) if home else _default_home()
    path = _lock_path(home_path, "desktop-session.lock")
    if fcntl is None:
        return None
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def desktop_session_active(home: str | Path | None = None) -> bool:
    """True when a desktop/server process holds the shared session lock."""
    home_path = Path(home) if home else _default_home()
    path = _lock_path(home_path, "desktop-session.lock")
    if fcntl is None:
        return False
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


class _SerializedProvider:
    """Serialize model calls with ordinary chat requests in the same process."""

    def __init__(self, provider: Any, semaphore: Any) -> None:
        self.provider = provider
        self.semaphore = semaphore

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        with self.semaphore:
            return self.provider.complete(system_prompt, user_prompt)


class SpecialistProvider:
    """Lazily create the coding specialist's routed model provider.

    Provider construction can start a multi-gigabyte local model. A status or
    control command must not do that; only an actual cycle calls ``complete``.
    """

    def __init__(self, agent_id: str = "BM-03", fallback_factory: Callable[[], Any] | None = None) -> None:
        self.agent_id = agent_id
        self._fallback_factory = fallback_factory
        self._router = None

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self._router is None:
            from .model_router import ModelRouter
            if self._fallback_factory is None:
                from .providers import create_provider
                fallback = create_provider()
            else:
                fallback = self._fallback_factory()
            self._router = ModelRouter(fallback=fallback)
        return self._router.complete_for(self.agent_id, system_prompt, user_prompt)


class LearningService:
    """Durable autonomous supervisor around verified learning cycles."""

    def __init__(
        self,
        independence: Independence,
        *,
        home: str | Path | None = None,
        provider_factory: Callable[[], Any] | None = None,
        interval: float | None = None,
        startup_delay: float | None = None,
        max_errors: int | None = None,
        standalone: bool = False,
        supervisor: bool = False,
        semaphore: Any | None = None,
        desktop_active: Callable[[], bool] | None = None,
        gate_checker: Callable[[], Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.independence = independence
        self.learning = independence.learning
        self.store = independence.learning_store
        self.home = Path(home) if home else _default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.stop_flag_path = self.home / "learning" / "STOP"
        self.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.cycle_lock_path = self.home / "learning-cycle.lock"
        self.supervisor_lock_path = self.home / "learning-service.lock"
        # A durable operator-set interval must survive a service restart. Only
        # an explicit command-line/API override may replace it; otherwise the
        # environment default is just the initial seed for a new installation.
        explicit_interval = interval is not None
        self.interval = self._clamp_interval(
            interval if interval is not None else interval_from_environment()
        )
        self.startup_delay = max(
            0.0,
            min(
                float(startup_delay if startup_delay is not None
                      else _env_int(ENV_STARTUP_DELAY, DEFAULT_STARTUP_DELAY_SECONDS, 0, MAX_INTERVAL_SECONDS)),
                MAX_INTERVAL_SECONDS,
            ),
        )
        self.max_errors = max(
            1,
            int(max_errors if max_errors is not None
                else _env_int(ENV_MAX_ERRORS, DEFAULT_MAX_CONSECUTIVE_ERRORS, 1, 20)),
        )
        self.standalone = bool(standalone)
        self.supervisor = bool(supervisor)
        self.semaphore = semaphore
        self.desktop_active = desktop_active or (
            (lambda: desktop_session_active(self.home)) if self.standalone else (lambda: False)
        )
        self.gate_checker = gate_checker or self._default_gates
        self.provider_factory = provider_factory or (lambda: SpecialistProvider())
        self._clock = clock or time.time
        self._sleep = sleep or time.sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._foreground = False
        self.lock = threading.RLock()
        self.learning.daemon = self
        self._recover()
        state = self.store.daemon_state()
        persisted_interval = int(state.get("interval_seconds") or 0)
        if not explicit_interval and persisted_interval > 0:
            self.interval = self._clamp_interval(persisted_interval)
        if not state.get("next_due_at"):
            self.store.set_daemon_state(
                interval_seconds=int(self.interval),
                next_due_at=_stamp(self._clock() + self.startup_delay),
            )
        elif int(state.get("interval_seconds", self.interval)) != int(self.interval):
            self.store.set_daemon_state(interval_seconds=int(self.interval))

    # ------------------------------------------------------------- configuration

    @staticmethod
    def _clamp_interval(value: float) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = DEFAULT_INTERVAL_SECONDS
        return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds))

    def set_interval(self, seconds: float) -> dict[str, Any]:
        value = self._clamp_interval(seconds)
        self.interval = value
        self.store.set_daemon_state(
            interval_seconds=int(value),
            next_due_at=_stamp(self._clock() + value),
        )
        self.store.audit("daemon_interval", {"interval_seconds": int(value)})
        return self.status()

    def environment_enabled(self) -> bool:
        return enabled_by_environment()

    def stop_flag_present(self) -> bool:
        return self.stop_flag_path.exists()

    def clear_stop_flag(self) -> bool:
        try:
            self.stop_flag_path.unlink(missing_ok=True)
        except OSError:
            return self.stop_flag_present()
        return not self.stop_flag_present()

    # ------------------------------------------------------------------- gates

    def _default_gates(self) -> dict[str, Any]:
        state = self.store.daemon_state()
        reasons: list[str] = []
        if not enabled_by_environment():
            reasons.append(f"{ENV_ENABLED}=0 disables the autonomous supervisor.")
        if not state.get("enabled", True):
            reasons.append("Autonomous learning was disabled from its controls.")
        if self.stop_flag_present():
            reasons.append(f"A stop file is present at {self.stop_flag_path}.")
        if state.get("state") == "paused":
            reasons.append("The supervisor is paused.")
        if state.get("state") == "halted":
            reasons.append("The supervisor is halted pending an operator reset.")
        if state.get("state") == "stopped":
            reasons.append("The supervisor is stopped pending an operator reset.")
        audit = self.store.verify_audit_chain()
        if not audit["intact"]:
            reasons.append("The learning audit chain is not intact; refusing to edit source.")
        try:
            selfdev.dev_root()
            dev_available = True
        except Exception as error:  # noqa: BLE001
            dev_available = False
            reasons.append(f"No developable source checkout: {str(error)[:160]}")
        if dev_available and not selfdev.selfdev_enabled():
            reasons.append("Self-development is disabled for this checkout.")
        policy = os.getenv("BABYMIND_SANDBOX", "require").strip().lower()
        if policy != "require":
            reasons.append("BABYMIND_SANDBOX must be 'require' for autonomous edits.")
        from . import sandbox
        backend = sandbox.backend()
        if not backend.available:
            reasons.append(f"OS sandbox unavailable: {backend.detail}")
        if self.standalone and self.desktop_active():
            reasons.append("A desktop session is active; the in-app supervisor owns learning.")
        return {
            "ready": not reasons,
            "reasons": reasons,
            "checks": {
                "enabled_by_environment": enabled_by_environment(),
                "enabled_in_store": bool(state.get("enabled", True)),
                "stop_flag_present": self.stop_flag_present(),
                "state": state.get("state", "idle"),
                "audit_chain_intact": audit["intact"],
                "dev_available": dev_available,
                "selfdev_enabled": selfdev.selfdev_enabled() if dev_available else False,
                "sandbox_policy": policy,
                "sandbox_backend_available": backend.available,
                "desktop_session_active": bool(self.desktop_active()) if self.standalone else False,
            },
        }

    def _gates(self) -> dict[str, Any]:
        result = self.gate_checker()
        if isinstance(result, dict):
            return {
                "ready": bool(result.get("ready", not result.get("reasons"))),
                "reasons": list(result.get("reasons") or []),
                "checks": dict(result.get("checks") or {}),
            }
        reason = str(result or "")
        return {"ready": not reason, "reasons": [reason] if reason else [], "checks": {}}

    def _verification_ready(self) -> tuple[bool, str]:
        if not self.store.verify_audit_chain()["intact"]:
            return False, "The learning audit chain is not intact."
        if not selfdev.selfdev_enabled():
            return False, "Self-development is disabled or the source checkout is unavailable."
        if os.getenv("BABYMIND_SANDBOX", "require").strip().lower() != "require":
            return False, "BABYMIND_SANDBOX must be 'require'."
        from . import sandbox
        backend = sandbox.backend()
        if not backend.available:
            return False, f"OS sandbox unavailable: {backend.detail}"
        return True, ""

    # -------------------------------------------------------------- process locks

    @contextlib.contextmanager
    def cycle_lock(self):
        """Yield True only when this process owns the cross-process cycle lock."""
        handle = _try_exclusive_lock(self.cycle_lock_path)
        if handle is None:
            yield False
            return
        try:
            yield True
        finally:
            _release_lock(handle)

    def _recover(self) -> None:
        """Clear a cycle left 'running' by a crash and record the interruption."""
        state = self.store.daemon_state()
        if not state.get("running_since") or state.get("state") in DURABLE_STOP_STATES:
            return
        self.store.audit("daemon_interrupted", {
            "running_since": state["running_since"],
            "running_pid": state.get("running_pid", 0),
        })
        self.store.set_daemon_state(
            state="idle", running_since="", running_pid=0,
            last_error="A previous learning cycle was interrupted before completion.",
            next_due_at=_stamp(self._clock() + SKIP_RETRY_SECONDS),
        )

    # ------------------------------------------------------------------ controls

    def start(self) -> dict[str, Any]:
        """Start the supervisor thread. Idempotent and model-free."""
        with self.lock:
            if self._thread is not None and self._thread.is_alive():
                return {"started": False, "state": self.store.daemon_state()["state"],
                        "reason": "The learning supervisor is already running."}
            self._stop.clear()
            self._recover()
            current = self.store.daemon_state().get("state", "idle")
            if current not in DURABLE_STOP_STATES:
                self.store.set_daemon_state(state="idle", last_skip_reason="")
                current = "idle"
            self.store.audit("service_started", {
                "pid": os.getpid(), "in_process": not self.standalone,
                "interval_seconds": int(self.interval),
            })
            self._thread = threading.Thread(
                target=self._run_loop, name="babymind-learning-supervisor", daemon=True,
            )
            self._thread.start()
            return {"started": True, "state": current}

    def request_stop(self, *_: object) -> None:
        """Stop the loop in response to SIGTERM/SIGINT; the kill switch is separate."""
        self._stop.set()

    def pause(self) -> dict[str, Any]:
        state = self.store.daemon_state()
        if state.get("state") == "halted":
            return {"state": "halted", "changed": False,
                    "reason": "Reset the halted supervisor before pausing it."}
        self.store.set_daemon_state(state="paused", last_skip_reason="Paused by the operator.")
        self.store.audit("daemon_paused", {})
        return {"state": "paused", "changed": True}

    def resume(self) -> dict[str, Any]:
        if self.stop_flag_present():
            return {"state": self.store.daemon_state()["state"], "changed": False,
                    "reason": "A stop file is present; reset the supervisor first."}
        state = self.store.daemon_state()
        if state.get("state") == "halted":
            return {"state": "halted", "changed": False,
                    "reason": "The supervisor is halted; reset it first."}
        self.store.set_daemon_state(state="idle", last_skip_reason="")
        self.store.audit("daemon_resumed", {})
        return {"state": "idle", "changed": True}

    def stop(self, *, reason: str = "Stopped from the BabyMind interface.") -> dict[str, Any]:
        """Drop a durable kill switch. A reset is required to run again."""
        clean = _clean(reason, 300)
        previous = self.store.daemon_state().get("state", "idle")
        try:
            self.stop_flag_path.write_text(f"{_now()} {clean}\n", encoding="utf-8")
        except OSError:
            pass
        self.store.set_daemon_state(state="stopped", last_skip_reason=clean)
        self.store.audit("daemon_stopped", {"reason": clean, "from_state": previous})
        return {"state": "stopped", "previous_state": previous,
                "stop_flag_present": self.stop_flag_present(), "reason": clean}

    def reset(self) -> dict[str, Any]:
        """Clear the kill switch, halt and error backoff, and re-enable."""
        self.clear_stop_flag()
        self.store.set_daemon_state(
            enabled=1, state="idle", consecutive_errors=0,
            halted_reason="", last_error="", last_skip_reason="",
            running_since="", running_pid=0,
            next_due_at=_stamp(self._clock()),
        )
        self.store.audit("daemon_reset", {})
        return {"state": "idle", "stop_flag_present": self.stop_flag_present(),
                "enabled": True}

    def disable(self) -> dict[str, Any]:
        self.store.set_daemon_state(enabled=0, state="stopped",
                                   last_skip_reason="Disabled from the learning controls.")
        self.store.audit("daemon_disabled", {})
        return {"state": "stopped", "enabled": False}

    def enable(self) -> dict[str, Any]:
        self.store.set_daemon_state(enabled=1, state="idle", last_skip_reason="")
        self.store.audit("daemon_enabled", {})
        return {"state": "idle", "enabled": True,
                "stop_flag_present": self.stop_flag_present()}

    # -------------------------------------------------------------------- cycles

    def _provider(self):
        provider = self.provider_factory()
        if self.semaphore is not None:
            provider = _SerializedProvider(provider, self.semaphore)
        return provider

    def _skip(self, reason: str, *, kind: str = "autonomous",
              due_delay: float = SKIP_RETRY_SECONDS) -> dict[str, Any]:
        state = self.store.daemon_state()
        clean = _clean(reason, 800)
        next_state = state.get("state", "idle")
        if "desktop session is active" in clean.lower():
            next_state = "standby"
        elif "stop file" in clean.lower() or "disabled" in clean.lower():
            next_state = "stopped"
        self.store.set_daemon_state(
            state=next_state,
            last_skip_reason=clean,
            cycles_skipped=int(state.get("cycles_skipped", 0)) + 1,
            next_due_at=_stamp(self._clock() + max(1.0, due_delay)),
        )
        if state.get("last_skip_reason") != clean:
            self.store.audit("daemon_skipped", {"reason": clean})
        self.store.record_daemon_run(kind="skipped", decision="skipped", reason=clean)
        return {"decision": "skipped", "skipped": True, "reason": clean,
                "cycle_id": "", "weakness": ""}

    def _record_success(self, result: dict[str, Any], *, kind: str,
                        state: dict[str, Any], started: float) -> dict[str, Any]:
        decision = str(result.get("decision") or "failed")
        count_field = {
            "kept": "cycles_kept", "rolled_back": "cycles_rolled_back",
            "no_change": "cycles_no_change", "failed": "cycles_failed",
        }.get(decision)
        updates: dict[str, Any] = {
            "state": "idle", "last_finished_at": _now(),
            "last_decision": decision, "last_error": "", "last_skip_reason": "",
            "consecutive_errors": 0, "total_cycles": int(state.get("total_cycles", 0)) + 1,
            "running_since": "", "running_pid": 0,
            "next_due_at": _stamp(self._clock() + float(state.get("interval_seconds", self.interval))),
        }
        if count_field:
            updates[count_field] = int(state.get(count_field, 0)) + 1
        self.store.set_daemon_state(**updates)
        duration = max(0.0, self._clock() - started)
        self.store.record_daemon_run(
            kind=kind, decision=decision,
            reason=str(result.get("reason") or result.get("lesson") or "")[:1000],
            cycle_id=str(result.get("cycle_id") or ""),
            weakness_id=str(result.get("weakness_id") or ""),
            duration_seconds=duration,
        )
        self.store.audit("daemon_cycle_completed", {
            "decision": decision, "cycle_id": result.get("cycle_id", ""),
            "weakness_id": result.get("weakness_id", ""),
            "kind": kind,
        })
        result["supervisor"] = {
            "kind": kind, "duration_seconds": duration,
            "next_due_at": updates["next_due_at"], "state": "idle",
        }
        return result

    def _record_failure(self, error: str, *, kind: str,
                        state: dict[str, Any], started: float) -> dict[str, Any]:
        clean = _clean(error, 1000)
        errors = int(state.get("consecutive_errors", 0)) + 1
        halted = errors >= self.max_errors
        backoff = min(
            max(float(state.get("interval_seconds", self.interval)) * (2 ** errors),
                SKIP_RETRY_SECONDS),
            MAX_BACKOFF_SECONDS,
        )
        reason = "Repeated learning cycle errors; supervisor halted pending reset." if halted else clean
        self.store.set_daemon_state(
            state="halted" if halted else "idle",
            last_finished_at=_now(), last_decision="failed", last_error=clean,
            last_skip_reason="", consecutive_errors=errors,
            total_cycles=int(state.get("total_cycles", 0)) + 1,
            cycles_failed=int(state.get("cycles_failed", 0)) + 1,
            halted_reason=reason if halted else "",
            running_since="", running_pid=0,
            next_due_at=_stamp(self._clock() + backoff),
        )
        duration = max(0.0, self._clock() - started)
        self.store.record_daemon_run(
            kind=kind, decision="failed", reason=clean, error=clean,
            duration_seconds=duration,
        )
        self.store.audit("daemon_cycle_failed", {
            "error": clean, "consecutive_errors": errors, "kind": kind,
        })
        if halted:
            self.store.audit("daemon_halted", {"reason": reason, "errors": errors})
        return {
            "decision": "failed", "reason": clean, "cycle_id": "", "weakness": "",
            "consecutive_errors": errors, "halted": halted,
            "supervisor": {
                "kind": kind, "duration_seconds": duration,
                "state": "halted" if halted else "idle",
            },
        }

    def run_once(self, *, force: bool = False, kind: str = "autonomous") -> dict[str, Any]:
        """Run at most one verified cycle under all supervisor gates."""
        state = self.store.daemon_state()
        if not force:
            due = _parse_stamp(state.get("next_due_at"))
            if due > self._clock():
                return {"decision": "skipped", "skipped": True,
                        "reason": "The next cycle is not due yet.",
                        "next_due_at": state.get("next_due_at", ""), "cycle_id": ""}
        with self.cycle_lock() as acquired:
            if not acquired:
                return self._skip("Another BabyMind process is already running a learning cycle.")
            gates = self._gates()
            if not gates["ready"]:
                return self._skip("; ".join(gates["reasons"]), kind=kind)
            state = self.store.daemon_state()
            started = self._clock()
            self.store.set_daemon_state(
                state="running", last_started_at=_now(), last_finished_at="",
                last_error="", last_skip_reason="", running_since=_now(),
                running_pid=os.getpid(),
                next_due_at=_stamp(started + float(state.get("interval_seconds", self.interval))),
            )
            self.store.audit("daemon_cycle_started", {
                "kind": kind, "pid": os.getpid(),
                "next_due_at": _stamp(started + float(state.get("interval_seconds", self.interval))),
            })
            try:
                result = self.learning.run_autonomous_cycle(self._provider())
                if not isinstance(result, dict):
                    raise TypeError("The learning cycle did not return a report.")
            except Exception as error:  # noqa: BLE001 - one failure must not kill the service
                return self._record_failure(
                    f"{type(error).__name__}: {error}", kind=kind, state=state, started=started,
                )
            if result.get("decision") == "failed":
                return self._record_failure(
                    str(result.get("reason") or "The learning cycle reported a failure."),
                    kind=kind, state=state, started=started,
                )
            return self._record_success(result, kind=kind, state=state, started=started)

    def run_supervised(self, cycles: int = 1) -> dict[str, Any]:
        """Run a bounded operator-requested batch without overlapping the loop.

        This is still verification-gated and path-guarded. It deliberately does
        not bypass the audit-chain, sandbox or self-development checks; only the
        autonomous schedule and kill switch are irrelevant to an explicit run.
        """
        with self.cycle_lock() as acquired:
            if not acquired:
                raise RuntimeError("Another BabyMind learning cycle is already running.")
            ready, reason = self._verification_ready()
            if not ready:
                raise RuntimeError(reason)
            report = self.learning.run(self._provider(), cycles=cycles)
            self.store.record_daemon_run(
                kind="manual", decision="batch",
                reason=f"Operator-requested batch of {cycles} cycle(s).",
            )
            self.store.audit("daemon_manual_batch", {"cycles": cycles})
            return report

    # ------------------------------------------------------------------ the loop

    def _wait_seconds(self, seconds: float) -> None:
        deadline = self._clock() + max(0.0, seconds)
        while not self._stop.is_set() and self._clock() < deadline:
            self._sleep(min(1.0, max(0.0, deadline - self._clock())))

    def _wait_until_due(self) -> None:
        while not self._stop.is_set():
            state = self.store.daemon_state()
            due = _parse_stamp(state.get("next_due_at")) or self._clock()
            delay = due - self._clock()
            if delay <= 0:
                return
            self._sleep(min(1.0, delay))

    def _run_loop(self, max_cycles: int | None = None) -> dict[str, Any]:
        completed = 0
        self._foreground = True
        try:
            while not self._stop.is_set() and (max_cycles is None or completed < max_cycles):
                self._wait_until_due()
                if self._stop.is_set():
                    break
                result = self.run_once(force=True)
                completed += 1
                if self.standalone:
                    print(
                        "[BabyMind learning] "
                        + json.dumps({
                            "decision": result.get("decision"),
                            "reason": str(result.get("reason") or result.get("lesson") or "")[:200],
                            "cycle_id": result.get("cycle_id", ""),
                            "next_due_at": self.store.daemon_state().get("next_due_at", ""),
                        }, ensure_ascii=False),
                        flush=True,
                    )
            return {"status": "stopped" if self._stop.is_set() else "completed",
                    "cycles": completed, "state": self.store.daemon_state().get("state", "idle")}
        finally:
            self._foreground = False
            self.store.audit("service_stopped", {
                "pid": os.getpid(), "cycles": completed,
                "reason": "signal" if self._stop.is_set() else "budget",
            })
            # Do not erase a durable halt, pause or kill-switch state just
            # because this particular process is exiting.
            current = self.store.daemon_state().get("state", "idle")
            if current not in DURABLE_STOP_STATES:
                self.store.set_daemon_state(
                    state="idle",
                    last_skip_reason="Supervisor process stopped; a new process resumes the durable schedule.",
                )

    def run_forever(self, *, max_cycles: int | None = None) -> dict[str, Any]:
        """Blocking service entry point; used by the CLI/systemd process."""
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive.")
        if not self.supervisor:
            return self._run_loop(max_cycles)
        handle = _try_exclusive_lock(self.supervisor_lock_path)
        while handle is None and not self._stop.is_set():
            if self.store.daemon_state().get("state", "idle") not in DURABLE_STOP_STATES:
                self.store.set_daemon_state(
                    state="standby",
                    last_skip_reason="Another BabyMind learning service owns the supervisor lock.",
                )
            self.store.audit("service_standby", {"pid": os.getpid()})
            self._wait_seconds(60)
            handle = _try_exclusive_lock(self.supervisor_lock_path)
        if handle is None:
            return {"status": "stopped", "cycles": 0,
                    "state": self.store.daemon_state().get("state", "standby")}
        try:
            if self.store.daemon_state().get("state", "idle") not in DURABLE_STOP_STATES:
                self.store.set_daemon_state(state="idle", last_skip_reason="")
            return self._run_loop(max_cycles)
        finally:
            _release_lock(handle)

    # ------------------------------------------------------------------- status

    def runs(self, limit: int = 25) -> dict[str, Any]:
        return {
            "runs": self.store.daemon_runs(limit),
            "audit": self.store.verify_audit_chain(),
        }

    def status(self) -> dict[str, Any]:
        state = self.store.daemon_state()
        gates = self._gates()
        report = self.store.report()
        due = _parse_stamp(state.get("next_due_at"))
        thread_alive = bool(self._thread is not None and self._thread.is_alive())
        return {
            "autonomous": True,
            "default_enabled": True,
            "enabled_by_environment": enabled_by_environment(),
            "enabled": bool(state.get("enabled", True)),
            "state": state.get("state", "idle"),
            "mode": "standalone service" if self.standalone else "in-process supervisor",
            "process_running": self._foreground or thread_alive,
            "thread_alive": thread_alive,
            "stop_flag_path": str(self.stop_flag_path),
            "stop_flag_present": self.stop_flag_present(),
            "interval_seconds": state.get("interval_seconds", int(self.interval)),
            "startup_delay_seconds": self.startup_delay,
            "max_consecutive_errors": self.max_errors,
            "next_due_at": state.get("next_due_at", ""),
            "next_due_in_seconds": max(0.0, due - self._clock()) if due else 0.0,
            "last_started_at": state.get("last_started_at", ""),
            "last_finished_at": state.get("last_finished_at", ""),
            "last_decision": state.get("last_decision", ""),
            "last_error": state.get("last_error", ""),
            "last_skip_reason": state.get("last_skip_reason", ""),
            "halted_reason": state.get("halted_reason", ""),
            "consecutive_errors": state.get("consecutive_errors", 0),
            "total_cycles": state.get("total_cycles", 0),
            "decisions": {
                "kept": state.get("cycles_kept", 0),
                "rolled_back": state.get("cycles_rolled_back", 0),
                "no_change": state.get("cycles_no_change", 0),
                "failed": state.get("cycles_failed", 0),
                "skipped": state.get("cycles_skipped", 0),
            },
            "gates": gates,
            "gate_reason": "; ".join(gates["reasons"]),
            "recent_runs": self.store.daemon_runs(10),
            "learning": report,
            "note": (
                "Enabled by default and persistent across restarts, but bounded: "
                "one verified cycle at a time, a durable schedule, an operator "
                "kill switch, a circuit breaker, a protected-path policy, "
                "fail-closed sandboxing and a hash-chained audit. Weakness "
                "identification and behavioral evaluation are model-generated; "
                "compile/test results, rollback and local state changes are measured."
            ),
        }


# Convenience alias used by documentation and older callers.
LearningDaemon = LearningService


def build_service(
    independence: Independence | None = None,
    *,
    home: str | Path | None = None,
    standalone: bool = False,
    supervisor: bool = False,
    provider_factory: Callable[[], Any] | None = None,
    semaphore: Any | None = None,
    desktop_active: Callable[[], bool] | None = None,
    interval: float | None = None,
    startup_delay: float | None = None,
    max_errors: int | None = None,
    gate_checker: Callable[[], Any] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> LearningService:
    """Construct a supervisor without starting a model or a thread."""
    home_path = Path(home) if home else _default_home()
    ind = independence or Independence(home=home_path)
    if ind.learning.selfmodel is None:
        from .selfmodel import SelfModel
        ind.learning.selfmodel = SelfModel(home_path / "selfmodel.sqlite3")
    if provider_factory is None:
        cached = SpecialistProvider()
        provider_factory = lambda: cached
    return LearningService(
        ind,
        home=home_path,
        provider_factory=provider_factory,
        interval=interval,
        startup_delay=startup_delay,
        max_errors=max_errors,
        standalone=standalone,
        supervisor=supervisor,
        semaphore=semaphore,
        desktop_active=desktop_active,
        gate_checker=gate_checker,
        clock=clock,
        sleep=sleep,
    )


def in_process_service(coordinator: Any, *, home: str | Path, semaphore: Any) -> LearningService:
    """Attach the supervisor to a running server/desktop coordinator."""
    return build_service(
        coordinator.independence,
        home=home,
        standalone=False,
        supervisor=False,
        provider_factory=coordinator.routed_provider,
        semaphore=semaphore,
        desktop_active=lambda: False,
    )


def control_service(
    independence: Independence | None = None,
    home: str | Path | None = None,
) -> LearningService:
    """Model-free supervisor for CLI/API status and control commands.

    Passing an existing ``Independence`` attaches the supervisor to that exact
    instance, so ``independence.learning.status()`` reports the live service.
    """
    if home is None and independence is not None:
        home = independence.database_path.parent
    return build_service(
        independence, home=home, standalone=False, supervisor=False,
    )


def run_standalone(*, interval: float | None = None, max_cycles: int | None = None) -> dict[str, Any]:
    """Run the enabled Linux user service in the foreground."""
    # A separate service must never silently downgrade to unsandboxed tests.
    os.environ.setdefault("BABYMIND_SANDBOX", "require")
    service = build_service(
        home=_default_home(), standalone=True, supervisor=True,
        interval=interval,
    )
    previous: dict[int, Any] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, service.request_stop)
    try:
        print(json.dumps({"event": "learning_service_started",
                          "status": service.status()}, ensure_ascii=False, default=str), flush=True)
        report = service.run_forever(max_cycles=max_cycles)
        print(json.dumps({"event": "learning_service_stopped", "report": report},
                         ensure_ascii=False, default=str), flush=True)
        return report
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
