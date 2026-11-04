# Autonomous development architecture

**Status: implemented, tested on Linux; Windows-specific paths are untested.**
BabyMind now has a mission orchestrator over 50 development roles, a
self-development engine with checkpoints and automatic rollback, a bounded
command runner, GitHub/licence research, and offline hardware sizing.

Read the status matrix before believing any capability claim in a chat message.
Nothing in this document is a promise that BabyMind is a finished autonomous
engineer.

## What was built

| Capability | Module | What it actually does |
| --- | --- | --- |
| 50-role catalogue | `agents.py` | 50 named roles in 9 phases, each with a purpose, capability set, and required evidence. `can_use()` enforces the capability map. |
| Mission orchestration | `orchestrator.py` | Walks every phase, gives each role the brief plus a bounded digest of earlier contributions, and stores each contribution encrypted. Failed or skipped roles are recorded, never dropped. |
| Mission storage | `orchestrator.py` (`MissionStore`) | SQLite in the data home, content encrypted with AES-256-GCM, same key handling as the rest of BabyMind. |
| Self-development | `selfdev.py` | Checkpoint → transactional write → compile → test → keep or auto-rollback, with a hash-chained audit log. |
| Command runner | `runner.py` | Allowlisted executables, working-directory boundary, scrubbed environment, output caps, timeout, process-tree kill, POSIX rlimits. |
| Public research | `research.py` | DuckDuckGo search, guarded page reading, GitHub repository search/metadata, licence classification. |
| Hardware sizing | `hardware.py` | CPU/RAM/disk detection and a conservative model/context recommendation with llama.cpp flags. |
| UI | `web/mission.js`, `index.html` | Mission control view: run a mission, watch all 50 roles, inspect self-development state, roll back, run tests, edit source with preview. |

## The 50 roles are not 50 models

One local GGUF model, loaded once, is used for every role. A mission makes 50
model calls, each with a different role prompt. On a 4B CPU model that is slow:
budget accordingly, or lower `BABYMIND_MISSION_MAX_SECONDS`. Roles that cannot
run inside the budget are recorded as `deferred` with a reason.

You cannot get more intelligence by adding roles. Roles change *framing* —
what the model attends to and what it is asked to produce — not capability.

## The autonomous loop (opt-in per mission)

Starting a mission with `self_edit: true` (UI: **Also apply one verified
self-edit**) closes the loop:

1. All 50 roles run and record their contributions.
2. The Coding Agent makes one extra model call asking for a JSON patch against
   BabyMind's own source, constrained to at most 40 files and allowed suffixes.
3. The patch goes through the self-development engine: checkpoint → write →
   compile → test → keep, or automatic rollback.

It runs at most once per mission, never bypasses verification, and records the
outcome (`applied`, `rolled_back`, `no_change`, `rejected`, `skipped`) on the
mission. A malformed or unsafe patch changes nothing.

The loop is still bounded by the model. A 4B model's patch that compiles and
passes the suite is kept even if it is not the improvement you wanted; that is
why the acceptance roles' reasoning is recorded next to it and the checkpoint id
is returned with the result.

## Self-development guarantees

Every write to BabyMind's own source follows the same path:

1. Validate the transaction (paths, sizes, suffixes, protected files).
2. **Checkpoint** the whole project into `state/checkpoints/<id>/` with a
   SHA-256 manifest.
3. Write each file atomically (`os.replace`), never through a symlink.
4. Run `python -m compileall -q src tests`.
5. Run the project's own unittest suite (`python -m unittest discover`).
6. On any failure: **restore the checkpoint automatically**, remove files the
   transaction created, and append `auto_rollback` to the audit log.
7. On success: append `applied` with the changed files and test count.

The audit log (`state/dev-audit.jsonl`) is append-only and hash-chained; the UI
and `babymind selfdev` report whether the chain is intact.

### What self-development does not guarantee

- It is not a sandbox. Generated or imported code runs with your privileges.
- It does not understand its own architecture magically. The model proposes; the
  test suite decides.
- It cannot recover a change that passes the tests but is wrong. Tests are
  necessary, not sufficient.
- Rollback restores the checkpoint. If a transaction crashes between writing a
  file and recording the checkpoint's `created` list, a newly created file can
  survive a rollback; its contents are still recorded in the audit log.

## Execution boundary

`runner.py` enforces an allowlist (Python, Node, Git, CMake, pytest by default),
requires the working directory to be inside the allowed root, scrubs the
environment to non-secret variables, caps output at 40,000 characters, and kills
the process tree on timeout. On POSIX it also sets CPU, file-size, and
open-file rlimits.

It reports `os_sandbox: false` and `network_isolation: false` because neither is
true. A same-user subprocess is not a security boundary. Untrusted third-party
code should not be executed through it; that needs a real sandbox that this
project has not built.

## Research and open-source reuse

`github_search()` and `github_repository()` read public metadata only: licences,
stars, activity, archived flag. `license_policy()` classifies a licence as
permissive, copyleft, or unknown. Nothing is cloned, vendored, or imported
automatically, and no upstream repository counts as "integrated" because it was
mentioned in a plan.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `BABYMIND_DEV_ROOT` | repository root | Source checkout the engine may modify. |
| `BABYMIND_SELF_DEVELOPMENT_ENABLED` | on in a source checkout | Force the engine on or off. |
| `BABYMIND_MISSION_MAX_SECONDS` | `900` | Wall-clock budget for one mission. |
| `BABYMIND_RUNNER_ALLOWLIST` | see `runner.DEFAULT_ALLOWLIST` | Extra allowed executables (comma separated). |
| `BABYMIND_RUNNER_UNRESTRICTED` | off | Disables the executable allowlist. Reported in `runner_status()`. |

## Verification performed

Unit tests cover: registry completeness and capability enforcement, all 50 roles
recorded per mission, error and cancellation recording, checkpoint/apply/
rollback, automatic rollback on a deliberately failing test, path-traversal and
protected-file rejection, audit-chain tamper detection, runner timeout/output
caps/allowlist/env scrubbing, licence classification, and the HTTP endpoints.

Run them yourself:

    py -m unittest discover -s tests

See `docs/TEST_REPORT.md` for the recorded run and `docs/KNOWN_LIMITATIONS.md`
for what is still missing.
