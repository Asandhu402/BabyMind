# Verified Learning Cycle

**Status: implemented as the unit of work inside a default-on autonomous
supervisor.** See [permanent autonomous learning](AUTONOMOUS_LEARNING.md) for
the scheduler, durable state, gates, kill switches, CLI/API/UI controls and the
Linux service. The manual commands below remain verification-gated, but a
person no longer has to start each cycle.

The verified learning cycle is BabyMind's capability to improve its own code
based on its own assessment. Each cycle identifies a weakness in BabyMind's
source, proposes a fix, verifies it through the real self-development
transaction (compile + test suite in the sandbox), evaluates behaviorally
whether the fix actually addresses the weakness, keeps it only if both
verification and evaluation pass, and records the lesson.

## What a cycle does

1. **Identifies a weakness.** The model reviews its own source and names a
   correctness bug, safety gap, capability limitation, or design flaw. If no
   real weakness is found, the cycle exits with `no_change`.

2. **Proposes a fix.** The coding engine (`coding_engine.develop`) drafts a
   patch against BabyMind's own checkout, using the same repository-aware
   search/read/edit/submit loop used for user-driven development tasks.

3. **Verifies.** The self-development engine runs the transaction: checkpoint
   the files being changed, write the patch, compile-check, run the full test
   suite in the OS sandbox, keep or auto-rollback. This is real verification
   -- not model narration.

4. **Evaluates behaviorally.** If the patch passed verification, the model
   reads the changed files and judges whether the fix actually addresses the
   named weakness. Passing tests does not mean the weakness is resolved: a
   patch can be green and ineffective.

5. **Keeps only if both pass.** If verification passed AND the behavioral
   evaluation is positive, the patch is kept. If verification passed but the
   behavioral evaluation is negative, the checkpoint is rolled back. If
   verification failed, the self-development engine already rolled back.

6. **Records the lesson.** The outcome is recorded as a cycle with the
   decision, the fix status, the evaluation reasoning, and a concise lesson.
   Kept improvements are also recorded as positions in the independence
   subsystem. Each cycle records a prediction (the model's stated confidence
   that its fix will pass verification) and resolves it against the actual
   outcome, feeding the self-model's Brier calibration.

## Honest scope

- **Weakness identification is model-generated.** The model reviews its own
  code and may miss real weaknesses or flag false ones. This is self-critique,
  not an independent audit.

- **Verification is real.** Compile checks and the test suite run in the OS
  sandbox. The result is measured, not narrated.

- **Behavioral evaluation is model-generated.** The model judges whether the
  fix addresses the weakness. This is interpretation of code, not measurement.
  A model can read a patch that does not fix the problem and call it effective.

- **The keep decision combines real and model-generated signals.** Verification
  passing is necessary; behavioral effectiveness is model judgment. Neither is
  sufficient alone, and neither proves the fix is correct in any deeper sense.

- **Predictions feed Brier calibration.** Each cycle records a prediction --
  the model's stated confidence that its proposed fix will pass verification --
  and resolves it against the actual outcome. This measures whether stated
  confidence in fixes tracks reality, not whether the fixes are good.

## How it runs

The supervisor is enabled by default when the desktop or server starts. It
persists the next due time, retries unresolved weaknesses, skips duplicates and
retired work, and records each autonomous outcome in a durable ledger. On Linux
installations with a systemd user session, the installer also enables a
headless user service; `--if-available` skips that unit on hosts without one.
The in-app supervisor remains active either way. See
[permanent autonomous learning](AUTONOMOUS_LEARNING.md).

```bash
# Inspect the default-on supervisor, gates and ledger
babymind learning status
babymind learning runs

# One verified cycle now, or change the durable schedule
babymind learning run-once
babymind learning interval 900

# Explicit controls
babymind learning pause
babymind learning resume
babymind learning stop --reason "maintenance"
babymind learning reset
```

### Legacy CLI

```bash
# Show the learning cycle status (weaknesses, cycles, audit chain)
python -m babymind.cli independence learning

# Run one verified learning cycle; now routed through the supervised batch
python -m babymind.cli independence run-learning --cycles 1

# Run up to three cycles
python -m babymind.cli independence run-learning --cycles 3
```

### Server API

```bash
# Default-on service status and recent outcomes
curl /api/learning/service
curl /api/learning/runs?limit=25

# One cycle now, under the shared lock and verification gates
curl -X POST /api/learning/service/run-once \
  -H "Content-Type: application/json" -d '{}'

# Legacy cycle status and bounded supervised batch
curl /api/independence/learning
curl -X POST /api/independence/run-learning \
  -H "Content-Type: application/json" \
  -d '{"cycles": 1}'
```

### Python

```python
from babymind.independence import Independence
from babymind.coordinator import BabyMindCoordinator
from babymind.learning_service import build_service

ind = Independence(home="~/.babymind")
coordinator = BabyMindCoordinator()
ind.learning.selfmodel = coordinator.selfmodel
service = build_service(ind, home="~/.babymind",
                        provider_factory=coordinator.routed_provider)

# Use the supervisor for shared locking and verification gates.
report = service.run_supervised(cycles=3)
for cycle in report["cycles"]:
    print(cycle["decision"], cycle["weakness"][:80])
```

Calling `ind.learning.run(...)` directly remains available for tests and custom
integrations, but it does not acquire the supervisor's cross-process cycle
lock. Prefer `run_supervised` when a normal BabyMind process may be running.

## What this complements

- The **evidence loop** tests BabyMind's *conclusions* against external evidence.
- The **introspection pipeline** critiques BabyMind's *answers* for quality.
- The **self-model** tracks BabyMind's *beliefs* about itself and their calibration.
- The **learning cycle** tests and improves BabyMind's *code* -- its own source.

## What this does not do

- It does not prove that identified weaknesses are real. The model may
  fabricate weaknesses or miss genuine ones.
- It does not prove that behavioral evaluations are accurate. The model may
  call an ineffective fix effective.
- It does not make arbitrary generated code safe. The self-development
  engine keeps BabyMind recoverable; it does not sandbox arbitrary code.
- It does not update the running packaged executable. Verified edits in a
  packaged build affect a managed staged source copy only, with no rebuild,
  replacement or activation.
- It is no longer opt-in. The default-on supervisor schedules bounded cycles,
  but that is not permanent inference, an unbounded agent, an auto-updater, a
  claim of sentience, or proof that BabyMind's capability improved. See
  [permanent autonomous learning](AUTONOMOUS_LEARNING.md) for the gates,
  kill switches and open acceptance work.
