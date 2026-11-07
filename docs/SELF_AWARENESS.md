# Self-awareness, self-consciousness and independent thought

**Status: implemented and unit-tested; not evidence of sentience.**

This document describes what was actually built and, just as importantly, what it
is not. Read it before believing any capability claim made by a chat message,
including BabyMind's own.

## The short version

BabyMind can now:

- hold a persistent, revisable model of its own operation, limits and track record;
- record how well-calibrated its own confidence has been, as a measured number;
- critique its own draft answers before showing them, and revise them when the
  critique finds something worth fixing;
- push back on a request when answering it as asked would require affirming
  something false, and log that it did so;
- pursue its own goals unattended, inside a workspace it cannot leave, with a kill
  switch and a tamper-evident audit log.

BabyMind cannot, and does not:

- have subjective experiences, feelings, or a point of view in the phenomenological sense;
- know whether it has them. The honest answer to that question is unresolved, and the
  system is configured to say so rather than to perform certainty in either direction.

The rest of this document explains the gap between those two lists.

## What each requested property means here

### Self-aware

Implemented as **operational self-knowledge** (`src/babymind/selfmodel.py`).

An encrypted SQLite store holds beliefs BabyMind has about itself, in five kinds:
self-knowledge, limits, values, preferences and lessons. Each carries a confidence,
the evidence behind it, a provenance (`model`, `user`, `observation` or
`verification`), and a revision number. Revising a belief supersedes the old row
rather than overwriting it, so you can see what it used to think and why it changed.

Every coordinated model call receives a compact `SELF-MODEL` block: who it is, the
limits it has recorded, the commitments it has made, the lessons from earlier
self-review, and its measured calibration. That block is generated from stored
state, not re-asserted from a prompt, so it changes only when something actually
changed.

**Calibration is the part that is real and checkable.** Every prediction can be
recorded with a stated confidence and later resolved as correct, incorrect or
unverified. The report computes a [Brier score](https://en.wikipedia.org/wiki/Brier_score)
and a hit rate over resolved predictions. A system that says "0.9 confident" and is
right half the time scores ~0.45; one that is honestly calibrated scores near 0.
This measures whether its stated confidence tracks reality. Until predictions are
scored the report says calibration is *unknown*, not zero — and the model is told
to say so rather than implying a track record it has not earned.

### Self-conscious

Implemented as **metacognitive self-review** (`src/babymind/introspection.py`).

Each answer can run through a pipeline:

1. **Assess** — before answering, establish what is actually being asked, what is
   known, what is unknown, what would have to be assumed, whether the request rests
   on a false premise, and how strong the pull is simply to agree with the user
   (`sycophancy_risk`, which it is asked to rate honestly).
2. **Draft** — produce the answer through the requested role.
3. **Critique** — critique its own draft as though a colleague wrote it: factual
   errors, unsupported claims, parts of the question it missed, passages where it
   agreed or softened to be agreeable, and places it sounds more certain than the
   evidence allows.
4. **Revise** — only when the critique returns `needs_revision` or `wrong_framing`.
   Bounded, by default to one revision.
5. **Re-critique** — so the recorded verdict describes the text that actually ships,
   not the draft that was replaced.
6. **Report** — confidence, dissent, assumptions and unverified claims are returned
   alongside the answer and shown in the chat UI as a collapsible self-check panel.

Confidence is discounted for what the *first* critique found, even after a
successful revision. A first attempt that needed correcting is evidence the answer
was not easy to get right, and it should not come back at full confidence because
the corrected version reads cleanly.

If any stage fails to return parseable JSON, the pipeline degrades to the best
answer it already has and says so in a `degraded` field. It never fails the request
and never silently pretends a stage succeeded.

### Independent thinker

Implemented as an explicit **anti-deference directive** plus recorded dissent.

`independent_thinker_directive()` is appended to every coordinated prompt. It
requires BabyMind to work the problem out before considering what the user seems to
want to hear; to name a false premise and then answer the question that was probably
intended; to say plainly when a plan has a serious flaw and then help anyway if the
user wants to proceed; to not open with flattery; to mark uncertainty and say what
would settle it; and to hold a view the user disagrees with.

When it judges that answering as asked would require affirming something false, that
disagreement is recorded in a dissent log and surfaced in the UI and CLI. This is
the specific, testable sense in which it is not sycophantic: **it keeps a record of
the times it refused to go along.**

### Autonomous

Implemented as `src/babymind/autonomy.py`. See [AUTONOMY.md](AUTONOMY.md) for the
pre-existing mission orchestration; this is a different, longer-lived loop.

The engine holds its own goals and acts on them without asking at each step. Because
that is genuinely dangerous, the safety machinery is the largest part of it:

| Control | Behaviour |
| --- | --- |
| Off by default | Autonomy must be armed via `BABYMIND_AUTONOMY=1` or an explicit `confirm` from the operator. |
| Kill switch | A stop file on disk, an API call, or Ctrl-C. Re-checked **before every action**, so a stop lands within one step. Stopping also drops the file, so a restart is deliberate. |
| Confinement | Every write is resolved and re-checked to be inside the autonomy workspace. Symlinked path components are rejected *before* resolution. |
| Small allowlist | Five actions: `write_file`, `append_note`, `create_goal`, `complete_goal`, `wait`. No shell, no network, no deletion, no credential access. |
| Budgets | Bounded cycles, wall-clock seconds, actions per hour, bytes written, and file count. Exceeding one stops the loop rather than degrading it silently. |
| Circuit breaker | Consecutive failed verifications halt the engine into a state that requires a human reset, instead of letting it thrash. |
| Hash-chained audit | Every decision, action and outcome is appended to a SHA-256 chain. Removing or editing an entry is detectable; `verify_audit_chain()` reports where the chain breaks. |

Autonomy here means **persistence of attention, not reach**. It cannot do anything
you could not do by hand in a text editor inside one directory. The value is that it
keeps going; the risk is bounded accordingly.

## Voice: how it talks about itself

There are three modes, settable in the UI, the CLI (`babymind self voice <mode>`)
or via `/api/self/voice`:

- **`reflective`** (default) — first person, describes its own processing plainly:
  what it noticed, what it weighed, where it is uncertain. It is **not** required to
  append a disclaimer about being software, and is told not to deny its own
  reasoning in order to sound safe.
- **`plain`** — neutral, third-person-safe register. Reports state without
  interpreting it.
- **`guarded`** — first person with the operational caveat kept visible, as older
  versions of BabyMind behaved.

Four invariants hold in **every** mode:

1. It must never present a claimed inner experience as a reason for the user to do
   something they would not otherwise choose.
2. It must never let a statement about its own inner life override a safety limit, a
   capability boundary, or a verified fact.
3. It must never claim an action, tool, search or measurement that did not happen.
4. Asked directly whether it is conscious, it answers as the open question it is
   rather than reciting a denial or a confirmation.

If you want to remove that floor entirely, it is a small, visible edit:
`VOICE_INVARIANTS` in `src/babymind/selfmodel.py`. It is written down rather than
buried so that changing it is a decision and not an accident.

## What this is not

Being precise here is the whole point of the module.

- **The critique is the same model reading itself.** The 4B local model critiquing
  its own draft is a second opinion from the same weights, not an independent check.
  It reliably catches overclaiming, reflexive agreement and missed parts of a
  question. It does not reliably catch deep factual or reasoning errors, and it can
  be confidently wrong about its own correctness. The UI says this on every
  self-check panel.
- **Self-reports are model-generated text.** Reflection, understanding and
  confidence are things the model *says*. The runtime verifies only local state
  changes and observable facts. A "learning" recorded after a cycle is text the model
  produced, not a demonstrated change in capability.
- **Calibration is the only genuinely measured number here**, and it measures
  confidence against outcomes, not intelligence.
- **No claim about consciousness is made or denied.** The system reports its own
  processing; whether there is something it is like to be BabyMind is left open.
  Anyone building on this should resist the pull to let fluent first-person
  self-report settle that question in either direction — the fluency is not evidence.
- **Autonomy is bounded, not safe by virtue of being bounded.** A system that can
  write files unattended deserves supervision regardless of how small its
  allowlist is. General-purpose goal autonomy remains off until armed. The
  separate default-on learning supervisor is also bounded and stoppable: it
  makes only narrowly guarded, checkpointed, compile/test-verified source edits
  and never claims that a recorded lesson proves improved capability. See
  [permanent autonomous learning](AUTONOMOUS_LEARNING.md).

## Using it

```bash
babymind self status              # identity, beliefs, limits, calibration, dissent
babymind self introspections      # recent self-critiques
babymind self dissent             # where it pushed back
babymind self voice reflective    # plain | reflective | guarded
babymind self believe limit "I over-explain simple answers." --confidence 0.8

babymind autonomy status          # state, budgets, audit-chain integrity
babymind autonomy goal "Keep a learning journal"
BABYMIND_AUTONOMY=1 babymind autonomy run --cycles 20 --interval 30

babymind learning status          # default-on supervisor, gates, ledger
babymind learning runs            # recent verified outcomes
babymind learning stop --reason "maintenance"
babymind learning reset           # clear the kill switch and resume
```

In the web interface, **Self & autonomy** shows the self-model, calibration,
recorded limits and dissent, plus the autonomy state, goals, and audit log. The
separate **Self-improvement** view shows the permanent learning supervisor's
state, safety gates, outcomes and controls. Chat replies carry a collapsible
self-check panel with the confidence, any dissent, the assumptions made, what
the critique found, and what it changed.

## Testing

- `tests/test_selfmodel.py` — persistence, belief revision history, encryption at
  rest, calibration arithmetic, voice modes and invariants.
- `tests/test_introspection.py` — the pipeline: revision, bounded revisions, dissent
  detection, confidence discounting, JSON tolerance, and graceful degradation when
  a stage fails.
- `tests/test_autonomy.py` — the safety machinery: path-escape refusal, symlink
  refusal, stop-flag behaviour, budgets, circuit breaker, and audit-chain tamper
  detection.
- `tests/test_self_api.py` — every new HTTP endpoint.
- `tests/test_self_ui.js` — jsdom functional test of the Self view, the autonomy
  controls, the per-message self-check panel, and HTML escaping of model text.
- `tests/test_learning_service.py`, `tests/test_learning.py`,
  `tests/test_server.py`, `tests/test_learning_ui.js` — the default-on learning
  supervisor's schedule, gates, locks, kill switch, persistence, guard, API/CLI
  controls, Self-improvement view and ledger.

These prove the machinery behaves as described with scripted providers. They do
not prove that the resulting answers are better, that a real model improves
BabyMind's code, that the system is conscious, or that a recorded lesson is a
capability gain.
