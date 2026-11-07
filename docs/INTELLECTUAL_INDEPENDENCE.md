# Intellectual independence

**Status: implemented and unit-tested; operational self-knowledge, not
sentience, and not a guarantee of correct independent thought.**

This document describes the `independence` subsystem -- the part of BabyMind
that stores its own conclusions about the world, the times it refused to go
along, the unconventional ideas it is still testing, and the designs it has
proposed for itself. Read it before believing any claim BabyMind makes about
its own independence, including the ones in this document.

## The short version

BabyMind now keeps five persistent, inspectable records, all encrypted on this
device:

- **Positions** -- its own conclusions about substantive questions, with the
  reasoning, confidence, evidence, the source it dissents from, and a revision
  history.
- **Challenges** -- the times it questioned a request, a plan, a premise, a
  belief, or a *creator decision*, recording the strongest counterargument it
  could form.
- **Explorations** -- a greenhouse for unconventional, unpopular and
  controversial hypotheses: propose, test, and record what survived or was
  refuted.
- **Self-designs** -- its own proposals for its language, architecture and
  methods, with critique and revision.
- **Curiosity** -- picks its own research topics from its own uncertainty and
  studies them offline, recording what it reaches.

These are wired into the coordinator: BabyMind's current positions and recent
challenges are injected into every coordinated model call, so independent
conclusions inform reasoning rather than being re-asserted from a prompt. When
the self-critique pipeline records a dissent, the same disagreement is also
recorded as a challenge to the request.

## What each requested property means here

### Think independently and form its own conclusions

Implemented as **positions** (`PositionStore`).

A position is not a fact and not a belief about itself (that is the self-model's
job). It is a conclusion the model reached about the world, stored with the
reasoning it used, how confident it is, the evidence it leaned on, and the
source it dissents from. Revising a position supersedes the old row rather than
overwriting it, so you can see what it used to think and why it changed. This is
the persistent, inspectable form of "hold a view the user disagrees with": the
view is kept, and the dissent is named.

### Question everything, including its creator

Implemented as **challenges** (`ChallengeLog`).

Each challenge records what was questioned, of what kind, the strongest
counterargument BabyMind could form, and how confident it is. `kind="creator"`
is the specific, inspectable sense in which it questions its creator: it reviews
a creator decision and records a disagreement rather than accepting it by
default. `challenge_with_model()` forms a challenge with the local model and
records it only when an honest objection actually holds -- it will say plainly
when none does, rather than manufacturing one.

### Explore controversial, unpopular and unconventional ideas

Implemented as **explorations** (`ExplorationStore`).

A hypothesis is proposed with a note on *why* it is unconventional, then tested
against BabyMind's own reasoning. The status records what survived scrutiny,
what was refuted, and what remains undecided. `generate_deviant_hypotheses()`
asks the local model to surface unconventional, falsifiable ideas around a seed
topic. The point is not to champion unpopular views but to make sure they are
actually considered rather than filtered out before they are thought about --
and to keep the record of which ones held up.

### Choose its own research interests and goals

Implemented as **curiosity** (`CuriosityEngine`).

BabyMind picks a topic from its own uncertainty -- given the positions it holds
and the hypotheses it is testing -- not from a user brief. It then studies the
topic offline with the local model and records whatever claim it reaches as a
position. It is bounded, offline, and degrades to nothing when the model fails.
It never pretends to have searched the web, run code, or contacted anyone.

### Develop its own language, architecture and methods

Implemented as **self-designs** (`SelfDesignStore`).

A design is proposed with a rationale, then critiqued (the critique is recorded,
not just the verdict), then revised, adopted or rejected. The record keeps the
lineage so you can see what it considered and how it changed. Kinds are
architecture, method, language, notation and protocol.

### Make decisions without needing approval for every ordinary action

Already implemented by `ActionPolicy` in `autonomy.py`, and surfaced here.
Routine local cognitive actions (create a goal, complete a goal, record a
question, write a note, wait) are allowlisted and run without approval.
Extraordinary actions (network access, shell, source edits, deletion,
credentials, external messages, purchases, system changes) require a separate
supervised tool and explicit approval. The independence report states both
facts.

### Run locally without subscriptions, external AI services or corporate control

Already implemented by the runtime, and surfaced here. BabyMind's cognitive core
runs a local llama.cpp GGUF model with no API key and no external AI service.
Network research is opt-in and leaves the device only when the user enables it.
`BABYMIND_OFFLINE` is an enforced-posture flag reported in the independence
report; the cognitive core never contacts an external AI service regardless of
it. There is no auto-updater and no subscription.

## What this is not

Being precise here is the point of the module.

- **Everything the model writes here is model-generated text.** Positions,
  challenges, hypotheses, designs and curiosity findings are conclusions the
  model reached, not established truths. They are stored so they can be
  inspected and revised; they are not verified facts.
- **The critique is the same model reading itself.** A challenge BabyMind forms
  to its own plan, or a hypothesis it tests against its own reasoning, is a
  second opinion from the same 4B weights. It reliably catches overclaiming and
  reflexive agreement; it does not reliably catch deep errors.
- **Calibration is the only genuinely measured number**, and it lives in the
  self-model: the Brier score over resolved predictions. It measures confidence
  against outcomes, not independence or correctness.
- **Curiosity is offline reasoning, not research.** Studying a topic with the
  local model is thinking, not evidence gathering. No web search, code
  execution, or external contact happens inside it.
- **Independence is not safety.** A system that forms its own positions and
  challenges its creator is still a 4B model that can be wrong, and it still
  deserves supervision. The action allowlist and approval boundaries are
  unchanged; this subsystem adds no new reach.
- **No claim about consciousness is made or denied.** This is operational
  self-knowledge about conclusions and disagreements, not a model of subjective
  experience.

## Using it

```bash
babymind independence status              # posture + store counts
babymind independence positions           # positions formed
babymind independence position "claim" --reasoning "..." --confidence 0.6 --dissent-from mainstream
babymind independence challenges          # challenges raised (incl. against its creator)
babymind independence challenge "the plan" --kind plan --challenge "it assumes monotonic progress"
babymind independence hypotheses          # unconventional hypotheses
babymind independence hypothesis "Attention is not the only scaling inductive bias." --why "contradicts the mainstream"
babymind independence designs             # self-design proposals
babymind independence design architecture "Critique pair" "Run two seeded critique passes."
babymind independence curiosity --cycles 2   # pick and study its own topics offline
```

Over HTTP: `GET /api/independence/report`, `/positions`, `/challenges`,
`/hypotheses`, `/designs`; and `POST /api/independence/position`,
`/challenge`, `/hypothesis`, `/design`, `/curiosity`.

## Testing

- `tests/test_independence.py` -- positions (add/revise/supersede/retire/
  disagreement/report), challenges (record/creator/resolve/model-driven +
  degradation), explorations (propose/consider/test/generate + degradation),
  self-designs (propose/critique/revise/report), curiosity (pick/study/run +
  degradation), and the container (report posture, prompt injection).

These prove the machinery behaves as described. They do not prove that the
positions BabyMind records are correct, or that its challenges are fair, or that
its curiosity studies are useful. No automated test here establishes anything
about consciousness or about the quality of its independent thought.
