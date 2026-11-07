# Known limitations

This file exists so no capability is over-claimed. Each item names what is
missing, not what is planned.

## Platform and packaging

- The requested acceptance-testing target is Ubuntu 26.10 x86-64. The present
  checkout was tested only on Debian 12/Python 3.11, and the existing hosted CI
  jobs use Ubuntu 26.04; neither establishes Ubuntu 26.10 acceptance.

- The supported portable target is Debian-based Linux on x86-64 with glibc 2.43+ (Ubuntu 26.04 LTS; the release is built and tested on Ubuntu 26.04 LTS). Debian 13 ships glibc 2.41 and is below the portable-archive floor, though source builds with Python 3.13+ remain supported there. Python 3.13+ is required for source builds, along with a graphical desktop. Historically, a hosted Ubuntu 22.04 VM with Xvfb passed the installer, real model download and one GUI chat response while BabyMind still supported Python 3.10/3.11; that combination is no longer supported. A clean Ubuntu Desktop session and broader capabilities remain unverified.
- The one-command installer is exercised in CI on GitHub-hosted
  **Ubuntu 26.04 LTS** (bootstrap preparation, Qt build and packaged app).
  Debian and Ubuntu derivatives are the only supported distribution family.
  GitHub publishes a hosted `ubuntu-26.04` label, so no self-hosted machine is
  required — but **no CI run has been recorded yet** (configured 2026-11-06);
  until one completes and its results are recorded in
  [verification](LINUX_VERIFICATION.md), a fresh-machine run with the
  production model remains unverified. See
  [testing on Ubuntu 26.04](UBUNTU_26_04_TESTING.md).
- There is no auto-updater or code signing. A default-on learning supervisor
  exists, but it reuses bounded verified cycles, cannot update the running
  packaged executable, and is not a general self-repair or release manager.
- Linux x86-64 is the sole supported desktop target.
- The portable executable is not itself a Python interpreter. A bundled Python helper supports sandboxed staged-source tests; generated Python app execution is still unavailable.

## Sandboxing and execution

- **The OS sandbox is Linux-only today.** `sandbox.py` builds a user, mount,
  pid and network namespace, chroots into a tmpfs root, mounts the system
  read-only, mounts only the project writable, and drops the network to
  loopback. `self_test()` proves each of those four claims against the live
  kernel, and the sandboxed suite runs the same green result as an unsandboxed
  one.
- The frozen app uses a bundled interpreter for the namespace helper. Packaged
  self-development requires a successful boundary probe and fails closed when
  unavailable. In source mode, `auto` now **fails closed** (treated as
  `require`) unless `BABYMIND_ALLOW_UNSANDBOXED_AUTO=true` is set explicitly;
  never set that for untrusted code.
- **Ubuntu 24.04 and newer restrict unprivileged user namespaces** through
  AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`). On such hosts
  `sandbox.backend()` reports `none` and every sandboxed path - packaged
  self-edits, generated apps and the sandboxed test suite - fails closed.
  BabyMind does not change kernel settings for you; CI re-enables them with
  `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` on a
  disposable runner, and a desktop user who wants those features must decide
  that for their own machine.
- Memory is capped by RLIMIT_AS/RLIMIT_DATA (virtual address space/heap) and,
  when cgroup v2 delegation is available, an additional best-effort
  `memory.max` cgroup cap (reported as `CGROUP_MEM_SET`/`CGROUP_MEM_UNAVAILABLE`
  on stderr). Physical-RAM cgroup limits are not guaranteed on every kernel.
- **Nested sandboxes are detected but still single-layer.** Running BabyMind
  inside a container/VM is reported by `sandbox.status()` and
  `/api/broker/status` (`nested_sandbox_detected`), but user namespaces inside
  a user namespace add no second layer of isolation. Because of that, a handful
  of tests that need their own OS sandbox (generated-app execution and the app
  verifier) cannot run while the project's suite is itself executing inside
  BabyMind's sandbox. The packaged staging check therefore reports them as
  pre-existing problems - the same tolerance `apply_edits` applies - and only
  refuses a staged edit that regresses the suite, runs nothing, or is not
  sandboxed. Those tests still run normally in a source checkout and in CI.
- **Limits are rlimits, not cgroups.** CPU time, file size, open files, process
  count, and address space/heap (RLIMIT_AS + RLIMIT_DATA, 2 GiB by default,
  `BABYMIND_SANDBOX_MEM_BYTES`) are capped, and refused limits are reported as
  `LIMIT_FAILED`. Physical RAM is still not capped, because cgroup delegation
  is unavailable here; a runaway allocation is bounded by virtual-memory
  failure plus the parent's monitor and timeout, not by a cgroup memory cap.
- **Only the project root is writable, and that includes `state/`.** The sandbox
  protects your home directory, keys and the network, not the project's own
  files: a model-authored patch can still damage the checkout it is editing,
  which is what checkpoints and rollback are for.

## Autonomy

- **50 roles are 50 prompts over one model**, executed sequentially by default.
  There is no multi-model parallelism or learned routing. Opt-in team chat can
  route 2–4 text-only roles through a validated dependency graph, but does not
  give them tools or independent execution. See [team chat](TEAMWORK.md).
- A mission only edits source when started with `self_edit: true`. The frozen
  desktop edits a staged copy; it does not rebuild or activate those edits in the
  running application. The loop attempts a patch proposed by the Coding Agent,
  verified by compile and tests. After a failed
  verification it can request one repair and retry; malformed or unsafe proposals
  can stop the loop earlier. This is not an unrestricted iterative engineer.
- The patch comes from a 4B-class local model. Expect small, local changes, not
  architectural rewrites.
- Missions stop scheduling at the time budget; model calls already running may
  continue until their provider returns or times out. Unrun roles are recorded
  as `deferred`; they are not retried automatically.
- The model is a 4B-class local GGUF. Long briefs and deep architectural
  reasoning will exceed it. Quality depends on the model you install.

## Self-development

- Verification is `compileall` plus the repository's unittest suite. A change
  that passes both but is semantically wrong is kept.
- Checkpoints copy project files; they do not snapshot the Git index, untracked
  binaries, databases, keys, or the model. They are not backups of user data.
- The engine refuses protected paths (`.git`, keys, databases, binaries) but it
  edits with your user's privileges; it is not protection against a compromised
  process.
- `BABYMIND_RUNNER_UNRESTRICTED` exists, is off by default, and removes the
  executable allowlist. Leaving it on is equivalent to giving the engine a shell.

## Inventing a language

- The **language lab** (`docs/LANGUAGE_LAB.md`) runs a complete
  research → design → sandboxed execution → conformance cycle and can produce a
  working interpreter for a new language whose behaviour is measured, not
  narrated. What it proves is narrow: that this model-authored interpreter, on
  this machine, produced the digits an independent decimal oracle computed, on
  the cases and held-out probes that ran. It does **not** show that the language
  is coherent, complete, useful or well designed, that anything except decimal
  rounding is correct, that research findings were applied, or that the
  interpreter is robust against a hostile program.
- The lab is **off by default** and **fails closed** without an OS sandbox
  backend. Research is a separate per-cycle opt-in. There is no UI; it is
  reachable through `babymind language`, `/api/language/*` and Python.
- **Only Python is compiled or executed.** A design's files are text, but the
  entry point must be a `.py` interpreter. BabyMind cannot build or run a
  C, Rust, Go or JavaScript toolchain, and it does not install dependencies.
- No cycle has been run against a **real local model** in this environment;
  every test uses a scripted provider. A real-model acceptance run and desktop
  UI coverage remain open, and running generated code is unavailable in the
  frozen packaged app.

## Applications BabyMind can build

- The app builder produces Python/HTML/CSS/JS applications inside a folder. It
  does not compile C#/Java/Rust/Go projects, produce packages for other
  operating systems or CPU architectures, or submit anything to an app store.
- Nothing is installed system-wide; generated apps run from their folder.
- Dependency installation for generated projects is not automated.

## Data and model

- No model is bundled in the repository. Installation downloads ~2.7 GB; the
  installer, download and checksum verification run automatically on every
  CI push and pull request on the hosted Ubuntu 26.04 LTS runner (the model is
  restored from the dependency cache, verified against its pinned SHA-256 on
  every run), but no CI run has been recorded yet, and other networks and a
  normal desktop session remain untested.
- The real-model acceptance job is permanent CI, not an opt-in dispatch, so a
  model that cannot answer its tested questions or emit a valid edit turns the
  build red. Its checks cover a fixed GUI question set, three source-mode chat
  questions, one coding task and two self-edits; they are not a measure of role
  competence or advice quality.
- Conversations, missions, and memory are encrypted at rest with a local key file on Linux. It is readable by the same user and does not protect against a compromised account.
- Knowledge-graph and voice integrations remain optional and unverified here.
- The interaction diagnostics log (`~/.babymind/interactions.jsonl`) records every local
  API call plus every failed page/asset request. It is metadata-only
  (route, status, timing, error text) and unencrypted; error messages may embed local
  paths. It is capped at 500 entries/256 KB, can be cleared from the Diagnostics window,
  and its markdown report is generated on demand — but anything you paste elsewhere is
  no longer under BabyMind's control. Successful static-file serves are deliberately
  not logged (they would flood the 500-entry log); failures anywhere are.

## Interface

- The mission and self-development views were syntax-checked and served by the
  test server, but were not driven through a real browser in this environment.
  The diagnostics window passes syntax checks, `node --check`, a permanent
  jsdom functional test (`tests/test_diagnostics_ui.js` / CI `ui-diagnostics`
  job) that drives the real DOM logic, and server-route tests — but it has not
  been exercised in a real browser here; rendering, layout and real clipboard
  behavior remain unverified.
- There is no diff viewer beyond the text `diff` field, no terminal emulator, and
  no project explorer tree in the UI yet (the API exposes `/api/dev/tree`).

## Source context selection

Self-edit and repair select a limited, lexical subset of the configured BabyMind
source root; they do not index or understand an entire arbitrary project. Large
files are often excerpts only. The instruction not to replace an incompletely
shown file is not enforced by the edit engine, and test success cannot establish
that a patch is correct. Filename exclusions are not a guarantee against secrets
embedded in source; selected content is sent to the configured provider.

The opt-in `babymind develop` loop can search, read windows, and submit
hash-checked search/replace edits only in BabyMind's own configured development
checkout. It is not a general project workspace or a shell-equipped OpenHands or
Aider replacement. Verification uses the same baseline/rollback and sandbox
limitations described above, including potentially pre-existing failures; an
applied result does not prove the task was fulfilled. Its filesystem checks are
not race-resistant and the model sees selected source and failure output.

## Self-model, self-critique and autonomy

- **The self-critique is the same model reading itself.** The draft, the critique
  and the revision all come from one 4B local model. This is a second opinion from
  the same weights, not an independent check. It reliably catches overclaiming,
  reflexive agreement and missed parts of a question; it does not reliably catch
  deep factual or reasoning errors, and it can be confidently wrong about its own
  correctness. A verdict of `sound` is not a guarantee.
- **Self-reports are model-generated text.** Reflection, understanding, lessons and
  confidence values are things the model says about itself. The runtime verifies
  only local state changes and observable host facts. A recorded "learning" is not
  evidence of a change in capability.
- **Calibration is measured, and only measures confidence.** The Brier score
  compares stated confidence against resolved outcomes. It says nothing about
  intelligence or correctness beyond that. With few scored predictions it is noisy;
  with none it is reported as unknown rather than zero.
- **No claim about consciousness is made or denied.** Nothing here establishes that
  BabyMind has subjective experience, and nothing here establishes that it does
  not. The question is left open in the stored identity and in the voice
  invariants. Fluent first-person self-report is not evidence either way, and the
  reflective voice mode is explicitly told not to deny its own reasoning in order
  to sound safe.
- **Voice invariants are a configurable floor.** Four invariants hold in every
  voice mode (no claimed inner experience used to persuade, no claimed inner life
  overriding a safety limit, no claimed actions that did not happen, and honest
  openness on the consciousness question). They live in `VOICE_INVARIANTS` in
  `src/babymind/selfmodel.py` and can be edited; they are written down so that
  changing them is a decision rather than an accident.
- **Autonomy is bounded, not thereby safe.** The allowlist is five actions, all
  confined to one workspace, with no shell, network or deletion. A system that can
  write files unattended still deserves supervision. Budgets bound how long it runs,
  not the quality or desirability of what it writes.
- **The audit log is tamper-evident, not tamper-proof.** The SHA-256 chain detects
  removal or editing of an entry; it does not prevent them. Someone with write
  access to the database can recompute the entire chain, so it is a record against
  accident and casual alteration, not against a determined adversary with the same
  privileges BabyMind runs as.
- **Autonomy has not been exercised against a real model.** Every test uses
  scripted providers. Real-model behaviour of the goal loop — including whether a
  4B CPU model produces useful plans rather than repetitive ones — is unverified.
- **The permanent learning supervisor is not proof of improvement.** It is
  default-on, durable, stoppable and uses real compile/test/rollback verification,
  but weakness identification, patches, behavioral evaluation and lessons are
  model-generated. Its path guard refuses supervisor, verification, isolation,
  UI, test and model-boundary files; that is a policy check, not a formal security
  boundary. If the audit chain is broken, self-development is unavailable, or
  `BABYMIND_SANDBOX=require` cannot be satisfied, cycles are skipped rather than
  downgraded. Five consecutive errors halt the supervisor pending reset.
- **The learning supervisor has not completed real-model or desktop acceptance.**
  Scheduler, locks, gates, controls, persistence, guard and installer machinery
  are covered by scripted tests. Whether a real 4B model finds useful weaknesses
  or writes useful patches, long-running service behavior, packaged staged-source
  edits, and Ubuntu 26.10 acceptance remain unverified. See
  [permanent autonomous learning](AUTONOMOUS_LEARNING.md).
- **The learning service is not an auto-updater.** In source checkouts it can keep
  narrowly guarded verified edits; in the packaged app it edits a managed staged
  source copy only. It never rebuilds, replaces, activates or updates the running
  executable.
- **Introspection roughly triples model calls per answer** (draft, assess,
  critique, and a revision plus re-critique when needed). On CPU inference this is
  a significant latency cost.

## Research and context card

Deep research uses one shared model, bounded parallel searches, and only short
page excerpts; citation-number validation is not fact-checking. Public search
queries leave the device. The user-edited context card is opt-in at inference,
not autonomous learning, and the source-learning supervisor never updates it.
Real-model, public search, desktop, and Ubuntu 26.10 acceptance have not been
completed for this feature. See
[research and context card](RESEARCH_ENGINE.md).

Research document mode accepts only one small text attachment, sends selected
excerpts to the configured model, and performs no web search. It is not PDF or
multi-document research; citation checks do not verify claims. Independent
research agents remain unimplemented. Autonomous learning **is implemented** as
a default-on verified source-improvement supervisor, but it is not autonomous
research, does not update chat memory or the context card, and does not make the
model's conclusions true. See [permanent autonomous learning](AUTONOMOUS_LEARNING.md)
and [research and context card](RESEARCH_ENGINE.md).
