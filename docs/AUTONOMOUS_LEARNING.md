# Permanent autonomous learning

**Status: implemented, enabled by default, supervised, and honest about its
limits.** BabyMind no longer waits for a person to invoke its verified learning
cycle. A durable supervisor starts with the application and, on supported Linux
installations, with an enabled systemd user service. It repeatedly selects one
bounded piece of work, runs the existing verified cycle, records the result,
and schedules the next attempt. This is "permanent" in the software sense:
default-on, persistent across restarts, crash-recoverable, and automatically
restarted by the installation. It is **not** permanent inference, an unbounded
agent, an auto-updater, or a claim of sentience.

For the unit of work itself, see [verified learning cycle](LEARNING_CYCLE.md).
For the broader release gates, see [production readiness](PRODUCTION_READINESS.md)
and [known limitations](KNOWN_LIMITATIONS.md).

## What changed

Previously the cycle was a bounded, opt-in command. The cycle still exists and
is still bounded, but it is now driven by `learning_service.LearningService`:

- The desktop and server start an in-process supervisor without an operator
  request. The Self-improvement view exposes its state and controls.
- `install-linux.sh` installs `babymind-learning.service` when a systemd user
  session is available. The unit runs the frozen launcher in headless
  `--learning-service` mode with `Restart=always`, `BABYMIND_SANDBOX=require`
  and the pinned local model environment. `--if-available` skips cleanly on
  hosts without a user session; the in-app supervisor remains active there.
- A durable SQLite state, schedule, run ledger and hash-chained audit survive
  process restarts. Crash-interrupted cycles are detected and retried after a
  short backoff. An operator pause, a circuit-breaker halt and the kill switch
  are also durable: a new process does not silently clear them.
- A cross-process cycle lock prevents two BabyMind processes from editing
  source at once. A supervisor lock parks duplicate standalone services in
  standby. A desktop-session lock keeps the standalone service idle while the
  desktop app owns the in-process supervisor.

## What one autonomous cycle does

1. **Selects durable work.** The cycle first retries an unresolved weakness,
   then asks the configured local specialist for a new weakness. Duplicate or
   retired weaknesses are skipped, repeated failures retire a weakness after
   three attempts, and recent lessons are included in the next task.
2. **Proposes a narrow patch.** `coding_engine.develop` receives
   `learning_edit_guard`. The guard refuses paths belonging to the supervisor,
   coding/verification/isolation machinery, model boundaries, UI, tests and
   other protected locations before any write. A refusal is a proposal error,
   not a silent downgrade.
3. **Verifies in the existing transaction.** `selfdev` checkpoints the files,
   applies hash-checked edits, compiles, runs the full test suite in the OS
   sandbox, and rolls back automatically on failure.
4. **Evaluates behaviorally.** The model reads the changed files and judges
   whether the named weakness was addressed. This is model interpretation,
   not measurement. An ineffective fix is rolled back even when tests pass.
5. **Records and learns from the outcome.** The decision, lesson, prediction,
   attempt count, cycle id, run duration and next due time are persisted. The
   cycle audit and supervisor audit are hash-chained; a broken chain closes the
   gate. Kept improvements are recorded as positions; predictions feed Brier
   calibration.

Weakness identification, proposed edits, behavioral evaluation and lessons are
model-generated. Compilation, tests, rollback, file changes and local state
transitions are real. Passing tests and a positive model evaluation do not
prove semantic correctness or an increase in capability.

## Gates and kill switches

A cycle is refused unless **all** of these are true:

| Gate | Why it exists |
| --- | --- |
| `BABYMIND_LEARNING_AUTONOMOUS` is not `0/false/no/off` | Environment-level default-off switch. The default is on. |
| The durable operator setting is enabled | `disable`/`enable` controls survive restarts. |
| `~/.babymind/learning/STOP` is absent | Durable kill switch; `stop` writes it and `reset` removes it. |
| State is not paused, halted or stopped | Explicit pause, circuit breaker and stop are respected. |
| The learning audit chain is intact | A tampered or truncated audit must not authorize source edits. |
| A developable checkout exists and self-development is enabled | No source writes without the configured dev root. |
| `BABYMIND_SANDBOX=require` and the OS sandbox backend is available | No silent downgrade to an unsandboxed test run. |
| No desktop session owns the in-app supervisor (standalone only) | Avoids duplicate model use and overlapping edits. |
| The cycle lock and, for standalone services, the supervisor lock are free | Serializes edits and duplicate service processes. |

Interval bounds are 60–86,400 seconds (default 1,800). Startup delay defaults
to 300 seconds, consecutive errors halt the supervisor after five failures,
error backoff is capped at 21,600 seconds, and skipped gates retry after at
least 60 seconds. These are runtime limits, not quality guarantees.

## Controls

### CLI

```bash
babymind learning status               # supervisor, gates, ledger and schedule
babymind learning runs                 # recent autonomous outcomes and audit chain
babymind learning run-once             # one verified cycle now, under the gates
babymind learning pause                 # keep the schedule, stop cycles
babymind learning resume                # resume after a pause
babymind learning stop --reason "..."   # durable kill switch
babymind learning reset                 # clear stop/halt/backoff and re-enable
babymind learning disable               # persistent operator disable
babymind learning enable                # persistent operator enable
babymind learning interval 900          # set the durable cycle interval
babymind learning service --interval 120 --max-cycles 2  # foreground service
```

The frozen desktop launcher dispatches these CLI commands directly, so an
installed user does not need a source checkout. The older `independence
learning` and bounded `independence run-learning` commands remain. The latter
now routes through `run_supervised`, using the same shared cycle lock and
verification gates; it is not a way to bypass them.

### HTTP

```text
GET  /api/learning/service
GET  /api/learning/runs?limit=25
POST /api/learning/service/run-once
POST /api/learning/service/pause
POST /api/learning/service/resume
POST /api/learning/service/stop       {"reason": "..."}
POST /api/learning/service/reset
POST /api/learning/service/enable
POST /api/learning/service/disable
POST /api/learning/service/interval   {"seconds": 900}
POST /api/independence/run-learning   {"cycles": 1}   # legacy supervised batch
```

### Desktop

The **Self-improvement** view shows the state, next cycle, interval, stop
switch, safety gates, outcome counters, recent lessons and run ledger. It
provides the same pause/resume/run-once/stop/reset/enable/disable/interval
controls and reports audit-chain integrity.

### Linux service

```bash
systemctl --user status babymind-learning.service
systemctl --user disable --now babymind-learning.service
babymind learning stop          # durable kill switch, even while the unit runs
babymind learning reset         # clear it and resume the durable schedule
```

`scripts/install-learning-service.sh --dry-run` prints the exact unit without
installing it. `--if-available` skips on hosts without a systemd user session.
The service does not open a Qt window and does not update the running binary.

## Honest scope

- **It is not an auto-updater.** In source checkouts, verified edits can change
  ordinary source modules. In the packaged desktop, edits affect a managed
  staged source copy only; they do not rebuild, replace, activate or update the
  running executable.
- **It cannot escalate its own authority.** The path guard refuses the
  supervisor, verification and sandbox modules, model/provider boundaries, UI,
  tests and protected paths. It grants no shell, network access, credentials,
  deletion outside the transaction, or arbitrary project writes.
- **It is not an independent auditor.** Weakness discovery and effectiveness
  judgments come from the same local model family. A green test suite is real;
  a claim that the weakness was fixed is model text.
- **It is not continuous inference.** One bounded cycle runs when due. The
  service is idle between cycles, skips closed gates, backs off on errors and
  halts after repeated failures.
- **It is not sentience or a capability claim.** A recorded lesson is text and a
  local database row, not evidence of understanding, subjective experience or
  improved intelligence. Brier calibration measures stated confidence against
  resolved verification outcomes, not the quality of the fixes.
- **It is not production-accepted yet.** Automated tests cover the scheduler,
  gates, locks, persistence, guard, CLI/API/UI controls and installer unit.
  Real-model quality, long-running desktop behavior, packaged-app staging and
  Ubuntu 26.10 acceptance remain open gates.

## Testing

- `tests/test_learning.py` — durable daemon state, weakness retry/dedup/retire,
  guard policy, autonomous work selection, inner `result.files` evaluation,
  prediction confidence and supervisor status.
- `tests/test_learning_service.py` — default-on flag, interval bounds, durable
  restarts, fail-closed gates, kill switch/reset, error halt/backoff, cycle and
  supervisor locks, scheduling, supervised batches, CLI parsing, headless
  launcher and systemd unit rendering/installation.
- `tests/test_coding_engine.py` — guard refusals never reach the write path.
- `tests/test_server.py` — service status, run ledger, startup and all HTTP
  controls.
- `tests/test_learning_ui.js` — jsdom checks for the Self-improvement view,
  status/gate/ledger rendering, controls, interval validation and escaping.
- `tests/test_installer.py` and `tests/test_background.py` — installer wiring
  and unit invariants.

These are machinery tests with scripted providers. They do not prove that a real
4B model finds useful weaknesses, writes useful patches, or improves BabyMind.
