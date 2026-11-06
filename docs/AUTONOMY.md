# Autonomous development architecture

**Status: implemented in part; Linux is the supported platform.**
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
A role recorded as `contributed` merely returned non-empty model text. A mission
marked `completed` means all calls returned text; neither status verifies that
its output is correct, useful, or that requested work was actually performed.

## The autonomous loop (opt-in per mission)

Starting a mission with `self_edit: true` (UI: **Also apply one verified
self-edit**) closes the loop:

1. All 50 roles run and record their contributions.
2. The Coding Agent requests a JSON patch against BabyMind's own source,
   constrained by the engine's file-count and suffix limits.
3. The patch goes through the self-development engine: checkpoint → write →
   compile → test → keep, or automatic rollback. After a failed verification,
   the model can receive the failure and propose one repair attempt.

If a role errors, the time budget expires, or the mission is cancelled before
self-edit begins, the self-edit is skipped and recorded; it is not attempted
with a partial set of role responses. A complete set is still unverified model
text, not proof of competent independent review. Cancellation after a patch
transaction has begun does not guarantee interruption of that transaction.

The loop attempts at most two patches per mission, never bypasses verification,
and records the outcome (`applied`, `rolled_back`, `no_change`, `rejected`,
`skipped`). A malformed or unsafe patch changes nothing. In the frozen desktop,
the feature operates only on a managed staged source copy. It does not rebuild,
replace, activate, or update the running application.

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
5. Run the project's own unittest suite (`python -m unittest discover`). The
   pre-edit and post-edit runs must complete with runnable tests; fewer tests,
   fewer non-skipped tests, or a newly failing test is a regression. Existing
   failures are compared using unittest's reported failure headings.
6. On any failure: **restore the checkpoint automatically**, remove files the
   transaction created, and append `auto_rollback` to the audit log.
7. On success: append `applied` with the changed files and test count.

The audit log (`state/dev-audit.jsonl`) is append-only and hash-chained; the UI
and `babymind selfdev` report whether the chain is intact.

### Repair attempts

A single failed patch used to end the loop. It now gets a bounded second chance.
`selfdev.apply_with_repair()` keeps calling the proposer with the tail of the
failed verification output, up to `MAX_SELF_EDIT_ATTEMPTS` (2) attempts. Each
attempt is a full transaction: checkpoint, write, compile, test, keep or roll
back. Two failed attempts leave the tree byte-identical and the audit log records
`repair_unresolved`. The mission's `self_edit` report carries the per-attempt
trail (`rolled_back`, then `applied`), so a repaired patch is visible as a
repair rather than as a first-time success.

The same loop is exposed over HTTP as `POST /api/dev/repair` with
`{"brief": "...", "attempts": 2}`, and it drives the mission's closing
self-edit. The proposer is always the shared local model; no attempt is applied
without passing verification.

### What self-development does not guarantee

- Verification runs inside the OS sandbox described below, so a failed patch
  cannot reach your keys, the network, or system files while it is being tested.
  The sandbox is still not a defence against a malicious *model*, only against
  the code it writes.
- It does not understand its own architecture magically. The model proposes; the
  test suite decides.
- It cannot recover a change that passes the tests but is wrong. Test counts
  do not prove that assertions or test identities were preserved, and model
  output is not independent verification. Tests are necessary, not sufficient.
- Tests run with write access to the designated project root. A hostile test
  can change other files there; rollback of an edit does not restore unrelated
  changes. Use a disposable checkout and keep independent backups.
- Rollback restores the checkpoint. If a transaction crashes between writing a
  file and recording the checkpoint's `created` list, a newly created file can
  survive a rollback; its contents are still recorded in the audit log.

## Execution boundary

`runner.py` enforces an allowlist (Python, Node, Git, CMake, pytest by default),
requires the working directory to be inside the allowed root, scrubs the
environment to non-secret variables, caps output at 40,000 characters, and kills
the process tree on timeout. On POSIX it also sets CPU, file-size, open-file,
address-space (RLIMIT_AS), heap (RLIMIT_DATA) and process-count (RLIMIT_NPROC)
rlimits.

Self-development compile and test runs default to `BABYMIND_SANDBOX=require`
and fail if the OS sandbox is unavailable. Explicitly setting `auto` allows
an unsandboxed fallback, and `off` disables it; neither is safe for untrusted
code. Other command-runner callers choose their own policy. On Linux the
backend uses:

- `unshare --user --map-root-user --mount --pid --fork --kill-child --net`, a
  generated launcher, then `chroot` into a fresh tmpfs root.
- `/usr`, `/lib`, `/lib64`, `/bin`, `/sbin`, `/etc` and the interpreter prefix are
  bind-mounted **read-only**; only the project root is writable.
- A private network namespace with nothing but loopback, so DNS and outbound
  connections fail with `OSError`.
- `/proc` is a fresh procfs; `/dev` holds `null`, `zero`, `random`, `urandom`;
  `/tmp` is an empty tmpfs.
- RLIMIT_CPU (300 s), RLIMIT_FSIZE (128 MB), RLIMIT_NOFILE (512), RLIMIT_AS and
  RLIMIT_DATA (2 GiB address-space/heap cap by default, overridable with
  `BABYMIND_SANDBOX_MEM_BYTES`) and RLIMIT_NPROC (256) are set; each soft cap is
  clamped to the inherited hard limit and any limit the kernel refuses is
  reported on stderr as `LIMIT_FAILED`. The pid namespace kills leftover
  children, and the launcher file is removed in a `finally` block.

`GET /api/sandbox` reports the backend and mechanisms; `POST
/api/sandbox/self-test` runs four live probes (network, host secret, system
write, workspace write) and returns the raw output. The portable build uses its
bundled Python helper for the namespace launcher; packaged self-edits require
the probes to pass and fail closed if they cannot.

Two honest limits. Nested sandbox operation (BabyMind running inside a
container/VM) is now detected and reported by `sandbox.status()` and
`/api/broker/status`, but nested user namespaces still provide no second layer
of isolation — an inner sandbox remains weaker than a non-nested one. And the
limits are rlimits, not cgroups: RLIMIT_AS/RLIMIT_DATA cap virtual address space
and heap, not physical RAM, which would require cgroup memory delegation.

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

## Source context for self-edit and repair

Mission self-edits, `/api/dev/repair`, and `/api/verify/fix` now select a
small amount of source context from the configured BabyMind development root
for each attempt. A deterministic lexical search ranks task and failure terms
and explicit paths; a retry searches again using the failure output after the
previous transaction has rolled back. The selection is bounded to 1,200 files,
400 directories, 3 MiB of source reads, six entries and 6,000 serialized
characters. Large files may have a short, line-numbered excerpt or only a path;
`complete: true` means the entire file is present. This is not a whole-repository
index: lexical matching, scan limits and the model's context window can miss
important dependencies. No new file or shell tools have been enabled.

Repository text and test output are untrusted data. The model is instructed not
to replace existing files without their full contents, but this is a prompt,
not an enforced guarantee: review every diff and maintain independent backups.
The selection excludes symlinks, hidden and protected directories, and common
secret filenames, but **is not a secret scanner**; source files can still contain
credentials. Selected content is sent to the configured model provider. Only
use a provider you trust with that source. Verification and rollback retain their
existing limits and do not establish semantic correctness. `/api/verify/fix`
now refuses a verification root other than the configured development root,
because repairs always target that root.

The repository-context tests were run on Debian 12 x86-64 with Python 3.11 in
the development sandbox (outside the supported Python range); Ubuntu 26.10 and
real-model behavior were not available for this change and remain unverified.

## Opt-in repository-aware self-development

`babymind develop "describe a change"` runs a separate bounded coding loop
against **BabyMind's configured development checkout**, without waiting for all
50 roles. It lets the configured provider search selected source and read
bounded line windows, then submit exact search/replace edits for existing files
or full contents for new files. Existing-file edits require the SHA-256 from a
read, an exact unique match, and a matching checkpoint before any write. They
still use the existing checkpoint, compile, test, audit and rollback transaction;
failed verification is fed back for a bounded retry (default two attempts).
The command returns a JSON report, and exits nonzero if no change was applied.

Use a disposable checkout and independent backup. The configured provider sees
the task, selected files and test failures; source can contain secrets despite
filename exclusions. Project text and output are untrusted. Filename and
symlink checks are not a race-resistant filesystem security boundary, and the
model can still misinterpret data as instructions. Commands and network tools
are not exposed to the model. Verification uses the existing sandbox policy
(default `require`); sandbox unavailability refuses the edit. Tests have write
access to the checkout and are not a proof of correct behavior. The engine can
make multiple file edits but cannot edit arbitrary external projects, install
dependencies, or deliver a generally autonomous development agent. Inspection
is bounded, the model can run out of steps or context, and real local-model
performance has not yet been validated. An existing whole-file edit API remains
available and does not acquire the search-edit hash guard automatically.
