# The language lab: a complete online development cycle

**Status: implemented and unit-tested with real sandboxed execution. Not a
general-purpose language, not a compiler, and not proof of engineering ability.**

This document describes `src/babymind/language_lab.py`, which closes a specific
gap. Until now BabyMind's improvement loop could only edit *its own Python
source*, and its self-assessment was model narration. The lab runs a different
cycle end to end: research the public web, design a **new** language, validate
the specification, **execute** the generated interpreter in the OS sandbox, and
measure whether its behaviour matches an oracle the harness computes itself.

The difference that matters: the learning cycle asks the model whether its patch
was good. The language lab asks the kernel to run the artefact and compares the
bytes with independent arithmetic. The first is interpretation; the second is
measurement.

## What one cycle does

| Stage | What happens | Who decides |
| --- | --- | --- |
| **research** | Optional. Search the public web and read actual pages for design evidence. Snippets are discarded; only page text read is passed on. | Opt-in per cycle |
| **design** | The model returns a full specification: name, purpose, keywords, syntax rules, decimal semantics, conformance cases, and every interpreter file. | Model |
| **validate** | A fixed contract checks the specification before anything runs or is written: paths, sizes, keyword uniqueness, case counts, entry point, rounding mode. | Harness |
| **execute** | The interpreter is written to a fresh folder and run in the OS sandbox (user/mount/PID/network namespaces, no network, resource limits). | Kernel |
| **conformance** | Measured output is compared with the harness oracle, repeated for determinism, and probed with **held-out numbers the model never saw**. | Harness |
| **record** | The run is stored encrypted with the hash of the exact specification that ran, its sources, every check, and a hash-chained audit entry. An accepted language is also registered as a `language` self-design. | Harness |

## Why the held-out probe matters

The obvious way to fake this is an "interpreter" that prints the answers listed
in its own conformance cases. Nothing about asking the model, or checking that
the declared digits match the declared rounding rule, catches that.

So after running the declared cases the harness **derives its own numbers** from
the ones the model used: it rotates digits, offsets by a fixed amount, and
constructs an exact half at the last place (where `half_up` and `half_even`
disagree). It recomputes the expected digits with `decimal`, substitutes them
into the same program, and runs again. An interpreter that memorised answers
fails; one that implements the rule passes.

`tests/test_language_lab.py` proves both directions against real execution:
a genuine interpreter is `verified`, and a hardcoded one that reproduces every
declared expectation exactly is `rejected` on the held-out probes.

## What is measured, and what is not

**Measured** (real evidence about a real artefact):

- the interpreter ran as a separate process inside the namespace sandbox;
- its exit code was zero on valid programs;
- its stdout agreed with digits computed by `oracle_round`, not supplied by the model;
- two runs of the same program produced identical bytes;
- an unparseable program was refused with a clean error, when the specification claims to reject invalid programs;
- the recorded specification hash is the specification that ran.

**Not measured**:

- whether the language is **coherent, complete, elegant, or useful**. Read the spec. A language that rounds decimals and prints a unit word is a genuine complete cycle, not a usable programming language.
- **non-numeric semantics.** The oracle encodes decimal rounding only. A `literal` conformance case is self-consistent: it shows the interpreter printed what the model said it would, not that the expectation was interesting.
- whether **research findings were applied.** Pages are untrusted input; a model may ignore them entirely, and nothing verifies citation.
- **robustness against a hostile program.** The sandbox bounds the blast radius; it does not make an interpreter correct or safe to trust.
- anything about **general capability.** One small invented language, verified once, is not evidence of engineering skill, sentience, or autonomy in any broad sense.

An accepted language is a real, executed artifact with a real, measured
behaviour on a small set of inputs. Everything beyond that sentence is model
output.

## Gates and safety

Three independent gates must all hold, or the cycle refuses before writing a
byte:

1. **`BABYMIND_LANGUAGE_LAB_ENABLED=true`.** Off by default.
2. **`BABYMIND_LANGUAGE_LAB_ROOT`** (or `BABYMIND_WORKSPACE_ROOT`) naming an
   existing folder. Nothing is created inside a folder that does not exist.
3. **An available OS sandbox backend.** With none, the cycle fails closed with
   an explanation rather than running generated code with the user's privileges.

Network access is a *fourth, per-cycle* gate: `allow_research` is `False` unless
the caller asks for it, and `BABYMIND_OFFLINE=1` refuses it even then.

Specifications are confined the way the app builder confines generated apps:
relative paths only, no `..`, no hidden files, no protected or secret-looking
names, allowed suffixes only (`.py`, `.md`, `.txt`, `.json`), 20 files,
64 KB each, 256 KB total. Each cycle writes into a new
`languages/<slug>-<id>` folder and never overwrites an existing one. The
interpreter executes with a scrubbed environment, a bounded timeout, and no
network namespace.

This is a bounded choke point, not a formally verified security boundary. The
generated interpreter is model-authored code, and review before reuse is your
responsibility.

## Using it

```bash
# What the lab can actually do, and its durable history
babymind language status
babymind language runs --limit 10

# One complete cycle with no network access
babymind language run-once

# Authorise public research for this cycle only, with one retry on rejection
babymind language run-once --research --attempts 2
```

Server API:

```bash
curl /api/language/status
curl /api/language/runs?limit=25

# Research stays off unless the body says allow_research: true
curl -X POST /api/language/run-once \
  -H "Content-Type: application/json" -d '{"allow_research": false}'
```

Python:

```python
from babymind.coordinator import BabyMindCoordinator

coordinator = BabyMindCoordinator()
report = coordinator.independence.languages.run(
    coordinator.provider, allow_research=False, max_attempts=1,
)
print(report["status"], report["conformance"]["summary"])
for check in report["conformance"]["checks"]:
    print(check["case"], check["passed"], check.get("detail", ""))
```

The report's `status` is `verified`, `rejected`, or `failed`; `reason` carries
the harness's own failure text, such as an interpreter exiting non-zero or
disagreeing with the oracle on an unseen number.

## Relationship to the other loops

- The **[verified learning cycle](LEARNING_CYCLE.md)** edits BabyMind's own
  Python and verifies with compile + tests. It cannot produce an artefact in a
  different language, and its effectiveness verdict is model-generated.
- The **[evidence loop](EVIDENCE_LOOP.md)** tests BabyMind's *conclusions*
  against external evidence. The lab tests an *artefact* against an oracle.
- **Self-designs** (`independence.designs`) record proposals for BabyMind's
  language, architecture and methods. The lab is the part that actually builds
  and runs one; an accepted language is registered there as `kind="language"`.
- **[Research](RESEARCH_ENGINE.md)** is shared, with the same untrusted-data
  posture and the same bounded reader.

## Verification and honest limits of this document

Tested here on **Debian 12 x86-64 with Python 3.11**, which is outside
BabyMind's supported range (3.13+). Execution tests skip cleanly when no
sandbox backend exists. The full suite's pre-existing failures are unchanged by
this work; `tests/test_language_lab.py` (35 tests) and the new server route test
pass.

Not done: no real 4B-class local model was available, so no cycle was run
against real model output; every test uses a scripted provider. A real-model
acceptance run, and one on Ubuntu 26.04/26.10 with the packaged build, remain
open. The lab has not been exercised from the desktop UI; it is exposed through
the CLI, the HTTP API and Python only. Running a generated interpreter is
unavailable in the frozen packaged app, matching the app builder.
