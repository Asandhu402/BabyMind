# Verified Learning Cycle

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

## How to use it

### CLI

```bash
# Show the learning cycle status (weaknesses, cycles, audit chain)
python -m babymind.cli independence learning

# Run one verified learning cycle
python -m babymind.cli independence run-learning --cycles 1

# Run up to three cycles
python -m babymind.cli independence run-learning --cycles 3
```

### Server API

```bash
# Get learning cycle status
curl /api/independence/learning

# Run a learning cycle
curl -X POST /api/independence/run-learning \
  -H "Content-Type: application/json" \
  -d '{"cycles": 1}'
```

### Python

```python
from babymind.independence import Independence
from babymind.coordinator import BabyMindCoordinator

ind = Independence(home="~/.babymind")
coordinator = BabyMindCoordinator()
ind.learning.selfmodel = coordinator.selfmodel

report = ind.learning.run(coordinator.provider, cycles=3)
for cycle in report["cycles"]:
    print(cycle["decision"], cycle["weakness"][:80])
```

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
- It does not run in a loop automatically. Cycles are bounded and opt-in.
