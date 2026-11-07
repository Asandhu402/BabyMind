# Evidence loop

**Status: implemented and unit-tested; gathers real external evidence, but the
model still interprets it.**

This document describes the evidence-gathering and experimental learning loop —
the part of BabyMind that tests its own conclusions against external evidence
and actual experiments instead of only asking the same model to critique itself.
Read it before believing any claim about how independent BabyMind's thinking is.

## The problem this solves

The introspection pipeline asks the model to critique its own draft. That is a
second opinion from the same 4B weights. It catches overclaiming and reflexive
agreement, but it cannot catch a conclusion that is wrong in the same way the
model is wrong. A model critiquing its own conclusion about, say, whether a
particular algorithm converges will tend to find the errors it is predisposed to
make and miss the ones it is predisposed to miss.

The evidence loop changes what "critique" means. Instead of the model reading
its own draft, it reads **real external evidence**: web pages written by other
people, and the actual stdout of code running in a sandbox. The evidence is
outside the model. The model still interprets it, but the interpretation is
against data rather than against itself.

## The loop

For each position or hypothesis, the `EvidenceLoop` (`src/babymind/evidence.py`)
runs five steps:

1. **Record a prediction.** The position's claim and confidence are recorded in
   the self-model. When the test completes, the prediction is resolved against
   the verdict. This feeds the Brier calibration — the only genuinely measured
   confidence signal in the system.

2. **Design a test.** The model is asked to design the strongest test that could
   prove the claim wrong. It proposes one of two kinds:
   - `web_search`: a search query to find external evidence.
   - `code_experiment`: a self-contained Python program (standard library only,
     no network, no file writes outside the workspace) to test the claim
     computationally.

3. **Gather the evidence.**
   - For `web_search`: the research module searches the public web and reads
     pages as plain text. Scripts are never executed. Each search snippet and
     each fetched page becomes an evidence record.
   - For `code_experiment`: the command runs through the broker in the OS
     sandbox — separate network namespace (loopback only), read-only system
     bind mounts, a private `/tmp`, rlimits on CPU, memory, file size, and
     process count. The actual stdout and stderr are captured as evidence.

4. **Evaluate the evidence.** The model reads the real external data and returns
   a verdict: `supported`, `refuted`, `unclear`, or `inconclusive`, with a
   confidence and reasoning.

5. **Update the conclusion.**
   - `supported`: the position's confidence is raised modestly (+0.1, capped at
     0.95); the hypothesis is marked `survived`.
   - `refuted`: the position is revised with lower confidence (−0.3, floored at
     0.05) and a new revision row recording what the evidence showed; the
     hypothesis is marked `refuted`.
   - `unclear` or `inconclusive`: no confidence change; the hypothesis is marked
     `undecided`.

Every test is recorded in the evidence store with its raw evidence, design,
verdict, and what changed. The audit log is hash-chained: removing or editing a
test record is detectable.

## What is genuinely measured

- **Code experiment output is real.** The sandbox runs the code and captures
  the actual output. If the experiment prints `(3, 11)`, that is the real
  Python version of the sandbox interpreter, not a model claim.
- **Web page text is real.** The research module fetches and extracts text from
  real web pages. The content is third-party, but it exists outside the model.
- **Brier calibration is measured.** When a position is tested, its prediction
  is resolved: `supported` → `correct`, `refuted` → `incorrect`,
  `unclear`/`inconclusive` → `unverified`. The Brier score over resolved
  predictions measures whether BabyMind's stated confidence tracks whether its
  conclusions hold up against real evidence.

## What is still model-generated

- **The test design is model-generated.** The model chooses what to search for
  or what code to run. It may design a bad test — one that cannot fail, or one
  that tests the wrong thing. The sandbox makes the experiment safe to run; it
  does not make it a good experiment.
- **The verdict is model-generated.** The model reads the evidence and decides
  whether it supports or refutes the claim. This is interpretation, not
  measurement. A model can misread evidence, or read contradictory evidence as
  supportive.
- **Web content is untrusted.** The research module reads pages as plain text
  and never executes scripts, but the source may be wrong, biased, outdated, or
  adversarial. The model reads it; it does not verify it. The source-quality
  policy in the coordinator's prompt governs how web content is used, but it is
  a prompt, not an enforced guarantee.
- **The update is model-interpreted.** The confidence delta (+0.1, −0.3) is a
  heuristic, not a measured response. It is designed to be conservative, but it
  is not derived from the evidence itself.

## Opt-in evidence kinds

Web search and code experiments are each opt-in. By default the loop gathers no
external evidence and records an inconclusive test with a `local_reasoning`
evidence record explaining that the kind was not enabled. The loop never
pretends to have gathered evidence it did not. The permanent learning supervisor
is separate: it has no web or experiment capability and does not override these
flags. See [permanent autonomous learning](AUTONOMOUS_LEARNING.md).

- `BABYMIND_OFFLINE=1` reports offline posture in the independence report, but
  does not automatically disable the evidence loop. The loop's own
  `allow_web` / `allow_experiments` flags control what it does.
- Web search leaves the device. Code experiments run locally in the sandbox and
  never touch the network.

## Using it

```bash
# Test one position against a sandboxed code experiment
babymind independence test <position-id> --experiments

# Test one hypothesis against web evidence
babymind independence test <hypothesis-id> --kind hypothesis --web

# Test several conclusions against real evidence
babymind independence run-evidence --cycles 3 --experiments --web

# Show evidence tests and their verdicts
babymind independence evidence
```

Over HTTP: `GET /api/independence/evidence`, `GET /api/independence/tests`;
and `POST /api/independence/test`, `POST /api/independence/run-evidence`.

## What this is not

- **Not a replacement for self-critique.** The introspection pipeline still
  runs on every coordinated answer. The evidence loop tests *conclusions*
  (positions and hypotheses), not *answers*. They are complementary:
  self-critique catches overclaiming in a draft; the evidence loop tests whether
  a held conclusion survives contact with the outside world.
- **Not a general research agent.** The loop designs one test per conclusion,
  gathers evidence for that test, and updates. It does not browse autonomously,
  clone repositories, or run arbitrary project code. The code experiment runs
  in the namespace sandbox with no network and read-only system paths.
- **Not a proof of correctness.** A `supported` verdict means the evidence
  supports the claim, not that the claim is true. A `refuted` verdict means the
  evidence contradicts the claim, not that the claim is false. The evidence may
  be wrong, incomplete, or misinterpreted.
- **Not a security boundary for experiments.** The sandbox is real kernel
  isolation, but it is not a defense against a malicious *model* that designs a
  test to exfiltrate data. The sandbox blocks network and host access; it does
  not evaluate the intent of the code.

## Testing

- `tests/test_evidence.py` — evidence records (add/read/report), test records
  (add/read/report), hash-chained audit tamper detection, design_test
  (web_search/code_experiment/invalid/degradation), evaluate
  (supported/refuted/invalid/no-evidence/degradation), test_position
  (supported/refuted/inconclusive/prediction-feeds-calibration), test_hypothesis
  (supported/refuted/inconclusive), run (bounded, requires evidence kind), and
  container integration.

These prove the machinery behaves as described. They do not prove that the
verdicts are correct, that the tests are well-designed, or that the evidence is
accurate. No automated test here establishes anything about the quality of
BabyMind's independent thought.
