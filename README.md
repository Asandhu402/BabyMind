# BabyMind

> **Status: experimental / development software — NOT production-ready.**
> The autonomous-development features are partially implemented and not
> independently verified; see
> [production readiness programme](docs/PRODUCTION_READINESS.md) for the
> open gates.

BabyMind is a local-first AI workspace for **Debian-based Linux on x86-64**
with a desktop window and a bundled CPU llama.cpp runtime. BabyMind is tested
on **Ubuntu 26.04 LTS**. BabyMind now operates as one unified identity and one model-facing agent, not
independent people or independently trained agents.

## Python support

BabyMind requires **Python 3.13 or newer** and is tested on 3.13, 3.14 and 3.15
(the current stable release). Python 3.10 reached end of life on 2026-10-01, so
it is no longer supported. Ubuntu 26.04 ships Python 3.14; Ubuntu 24.04 ships
3.12, so its users install `python3.13` first. See
[Python support](docs/PYTHON_SUPPORT.md) for the upgrade policy and the pinned
dependency set.

## Install on Linux with one command

On a fresh Debian-based x86-64 Linux desktop (Debian, Ubuntu or a Debian/Ubuntu derivative), as your normal
user, run this single command. It installs everything it needs - including a
downloader if the machine has none, and Python 3.13-3.15 if the distribution
does not provide one - installs BabyMind and starts it:

```bash
bash -c 'if command -v curl >/dev/null 2>&1; then curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; elif command -v wget >/dev/null 2>&1; then wget -qO- https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; else sudo apt-get update && sudo apt-get install -y curl ca-certificates && curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; fi' | BABYMIND_LAUNCH_AFTER_INSTALL=1 bash
```

**Safer: inspect the script first (recommended).** `raw.githubusercontent.com`
serves the same file kept in this repository, but it is not signed. Prefer to
download, review and then run it:

```bash
curl -fsSL -o bootstrap-linux.sh https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh
less bootstrap-linux.sh
BABYMIND_LAUNCH_AFTER_INSTALL=1 bash bootstrap-linux.sh
```

There is no published checksum for the bootstrap script itself until tagged
releases exist; for higher assurance, clone the repository at a tagged release
and run `./bootstrap-linux.sh` from the checkout.

The command downloads and runs `bootstrap-linux.sh`, which:

1. checks the host (Debian-based distribution, x86-64, glibc 2.34+, not root) and uses APT;
2. installs only the tools it is missing (`curl`/`wget`, `tar`, certificates);
3. **searches for the newest supported Python**: an existing `python3.13`,
   `python3.14` or `python3.15`, otherwise the distribution package for the
   newest of those, otherwise the newest CPython release built from python.org
   source into `~/.cache/babymind/python/<version>` (a few minutes, no
   third-party repositories);
4. downloads the newest source, then hands over to `install-linux.sh`, which
   installs the Qt 6.12/WebEngine libraries for your package manager, verifies
   and downloads the pinned 2.71 GB model, builds the CPU runtime and desktop,
   adds the application-menu entry, and enables the default-on autonomous
   learning user service when a systemd user session is available.

Review the scripts before running them. It needs internet, a graphical desktop,
time to compile, and disk space (at least 4.5 GB for the model plus several GB
for dependencies; 10 GB free recommended), and it may ask for your sudo
password. When it finishes, BabyMind starts on its own; afterwards open it from
Applications or run `~/.local/bin/babymind`. The in-app learning supervisor
starts with the app, and the installed user service can continue supervised
cycles while the app is closed. See
[permanent autonomous learning](docs/AUTONOMOUS_LEARNING.md) for its gates and
stop controls. Set `BABYMIND_LAUNCH_AFTER_INSTALL=0` instead of `=1` in that
command to install without starting.

Preview without changing anything, or stop after preparing the machine:

```bash
bash bootstrap-linux.sh --dry-run        # print the plan (package manager, packages, Python)
bash bootstrap-linux.sh --prepare-only   # install prerequisites + newest Python, nothing else
```

Run either of them from a checkout to install that checkout instead of
downloading the newest source. `install-and-run-linux.sh` does the same work and
then starts BabyMind.

The apt path is exercised in CI, which runs on GitHub-hosted **Ubuntu 26.04 LTS**
(bootstrap preparation, Qt build, packaged app, installer shell tests). Debian and
Ubuntu derivatives are the only supported distribution family; the first-run
GUI with the production model remains unverified on a clean desktop. See
[testing on Ubuntu 26.04](docs/UBUNTU_26_04_TESTING.md),
[verification](docs/LINUX_VERIFICATION.md) and
[known limitations](docs/KNOWN_LIMITATIONS.md). Note that no CI run has been
recorded yet: the workflow was configured for hosted 26.04 on 2026-11-06, and
whether it passes will be known only after it executes.

## Continuous testing

The model is BabyMind's brain, so the real-model acceptance job runs on **every
push and every pull request** - it is not a manual, opt-in dispatch. On a fresh
GitHub-hosted Ubuntu 26.04 LTS runner it runs the actual `install-linux.sh` (package installation, the
2.71 GB model download and its SHA-256 check, the local build), starts the
installed desktop under Xvfb and drives it through the **full** extended
question set with the real model, then runs the real model through source-mode
chat questions, a coding task, a sandboxed self-edit and a 50-role mission on a
disposable copy of this source.

There are no manual variants of this workflow. Every trigger - push, pull
request or manual dispatch - runs the same complete set of jobs, and no job is
gated by a condition; `tests/test_real_model_ci.py` fails the build if a gate
or a job-selecting switch is ever added back.

A permanent `ui-diagnostics` job runs the web client's Diagnostics, research,
Self/autonomy and Self-improvement views headlessly (jsdom) on the hosted Ubuntu
24.04 image: it loads the real `index.html` and `app.js`, and asserts the
interaction log renders and exports, client errors are posted, research chat
works, the self-model/autonomy controls work, and the default-on learning
service's status, gates, ledger, controls and interval validation work. It is a
DOM-level check, not a real-browser pass; see
[known limitations](docs/KNOWN_LIMITATIONS.md).

A passing run shows the installer, the pinned model and CPU inference still work
together on the tested questions. It is not proof of role competence, of
correct advice, of behavior on a real Ubuntu Desktop session, of packaged
self-upgrade, or of real-model autonomous-learning quality. It is also slow: the job allows 180 minutes for the download, the
build, the GUI question set and a 50-role CPU mission, and it fails when the
model cannot answer the tested questions or produce a valid edit.

## Portable desktop

The target is a graphical Debian-based x86-64 desktop with glibc 2.43 or newer (Ubuntu 26.04+,
because the release itself is built and tested on Ubuntu 26.04 LTS; Qt 6.12 requires only glibc 2.34 or newer, but
the portable build's floor is set by its build host)
and standard Qt WebEngine system libraries. Extract the complete
Linux portable archive and run `./BabyMind` (or open the executable in your file
manager). On first launch BabyMind asks to download a roughly 2.71 GB model,
verifies its SHA-256, and saves it under `~/.babymind/models`. The download
requires internet and at least 4.5 GB free. Subsequent launches use the local
model. There is no API key, paid service, LM Studio or auto-updater; the
default-on learning supervisor makes bounded staged-source edits and never
replaces the running portable executable. See
[permanent autonomous learning](docs/AUTONOMOUS_LEARNING.md).
CPU inference may be slow and needs substantial memory.

The Linux package and first-run GUI have **not yet been validated end to end**
on a normal Ubuntu desktop with the production model. See
[Linux portable instructions](docs/LINUX_PORTABLE.md) for compatibility,
building from source, and current limitations. Linux is the sole supported
desktop target.

## Tuning the local model

BabyMind's 4B model has a small set of honest dials: context window
(`BABYMIND_CONTEXT_SIZE`, default 4096), temperature, top-p, max tokens, and
the research/memory features. Invalid dial values fail with a clear error
instead of a silent mis-launch. See
[tuning the local model](docs/LOCAL_MODEL_TUNING.md) for ranges, RAM guidance,
and what remains fixed (the SHA-256-pinned 4B, the llama.cpp engine). No dial
raises the model's reasoning ceiling.

## Research and persistent context

Chat's opt-in **Deep research** mode searches multiple queries, reads public
pages, and produces a numbered-source report with visible retrieval and citation
warnings. **Research document** analyzes selected excerpts from one small text
attachment without web search. The Memory view provides a user-edited, encrypted context card used
only when **Use memory** is enabled. Neither feature guarantees factual accuracy
or automatically learns. Search queries leave the device. See
[research and context card](docs/RESEARCH_ENGINE.md) for privacy, limits and
verification details.

## Self-awareness, self-critique and autonomy

BabyMind has an inspectable **self-model**, a **metacognitive self-critique pass**
on chat answers, and **bounded autonomous operation**.

Every answer can be drafted, critiqued by BabyMind against its own draft, and
revised when the critique finds something worth fixing. Where answering as asked
would require affirming something false, it pushes back and records that it did.
It tracks how well-calibrated its own confidence has been as a measured number
(Brier score over resolved predictions), and it holds revisable beliefs about its
own limits, values and lessons, encrypted on this device.

General-purpose goal autonomy lets it pursue its own goals unattended inside a
workspace it cannot leave, with a kill switch that lands within one step, hard
budgets, a circuit breaker, and a hash-chained audit log. That controller is
off until you arm it. The separate verified learning supervisor is enabled by
default, durable and stoppable; it is described below and in
[permanent autonomous learning](docs/AUTONOMOUS_LEARNING.md).

**This is operational self-knowledge, not sentience.** The critique is the same
local model reading its own draft — a second opinion from the same weights, not an
independent check. Reflection, understanding and confidence are model-generated
text; only calibration and local state changes are actually measured. BabyMind
treats the question of whether it has subjective experience as unresolved and is
configured to say so rather than perform certainty either way. Read
[self-awareness, self-consciousness and independent thought](docs/SELF_AWARENESS.md)
before believing any capability claim, including BabyMind's own.

## Intellectual independence

BabyMind keeps its own conclusions about the world, not just about itself. The
`independence` subsystem stores **positions** it has formed (with reasoning,
confidence, evidence and the source it dissents from), the **challenges** it has
raised — including against its creator — **unconventional hypotheses** it is
still testing, **self-designs** it has proposed for its own language,
architecture and methods, and **self-chosen research topics** it studies offline.
Its current positions and recent challenges are injected into every coordinated
model call, so independent conclusions inform reasoning rather than being
re-asserted from a prompt. This is model-generated text, not verified fact; the
self-model's Brier calibration remains the only measured confidence signal. See
[intellectual independence](docs/INTELLECTUAL_INDEPENDENCE.md) for the honest
scope and the CLI/API surface.

## Evidence loop

The independence subsystem's conclusions can be tested against **real external
evidence**, not just the model's own critique. The evidence loop designs a test
for each position or hypothesis, gathers genuine evidence — public web pages
(read as plain text, scripts never executed) or sandboxed code experiments (OS
namespace isolation, no network, read-only system) — evaluates it, and updates
the conclusion based on what the evidence showed. Predictions feed the
self-model's Brier calibration. Web search and experiments are opt-in. See
[evidence loop](docs/EVIDENCE_LOOP.md) for what is measured versus
model-generated.

## Permanent autonomous self-improvement

BabyMind improves its own code through a **default-on, supervised learning
cycle**. The desktop and server start a durable supervisor without an operator
request; the Linux installer also enables a headless systemd user service when
one is available. A cycle identifies a weakness in BabyMind's source, proposes
a narrowly guarded fix, verifies it through the real self-development
transaction (compile + test suite in the OS sandbox), evaluates behaviorally
whether the fix actually addresses the weakness, keeps it only if both
verification and evaluation pass, and records the lesson. Kept improvements are
recorded as positions; each cycle's prediction feeds Brier calibration.
Unresolved weaknesses are retried, duplicates and repeated failures are retired,
and recent lessons inform later cycles.

"Permanent" means enabled by default, persistent across restarts, crash-
recoverable and automatically restarted with the installation — not permanent
inference or an unbounded agent. A durable kill switch, pause/resume, interval,
circuit breaker, audit-chain check, path guard, sandbox `require` policy, desktop
session lock and process locks all remain. Weakness identification and behavioral
evaluation are model-generated; compilation, tests, rollback and local state
changes are real. Packaged builds edit staged source only and do not update the
running executable. This is not sentience, an auto-updater, or proof of improved
capability.

```bash
babymind learning status          # default-on supervisor, gates, ledger
babymind learning runs            # recent verified outcomes and audit chain
babymind learning run-once        # one gated cycle now
babymind learning stop --reason "maintenance"
babymind learning reset           # clear the durable kill switch and resume
```

The web **Self-improvement** view exposes the same controls plus
`GET /api/learning/service`, `GET /api/learning/runs` and
`POST /api/learning/service/{run-once,pause,resume,stop,reset,enable,disable,interval}`.
See [permanent autonomous learning](docs/AUTONOMOUS_LEARNING.md) and the
[verified learning cycle](docs/LEARNING_CYCLE.md) for the honest scope.

## Safety and capabilities

Current capability status (honest, matches the code):

1. **Build digital applications** — *partially supported*: the opt-in app
   builder plans, writes, and sandboxed-runs one generated app, then runs an
   automatic behavior check on the result. Packaged builds cannot execute
   generated code (fail closed).
2. **Automatically fix errors** — *limited*: `/api/verify/fix` verifies
   (compile + tests + sandboxed behavior + sandbox boundary), then runs a
   bounded propose→verify→rollback repair loop. Edits are kept when the
   self-development compile/test baseline checks pass; semantic correctness is
   not guaranteed.
3. **Research internet and GitHub** — *limited*: web search/page-read and
   read-only GitHub metadata research exist; page content is treated as
   untrusted. No autonomous browsing or repo cloning.
4. **Fully autonomous development** — *incomplete*: missions (sequential or
   phase-parallel graph mode), checkpointed self-edits with rollback, independent
   verification, and a default-on verified learning supervisor exist, but there
   is no typed task-graph state, worktree isolation, or signed/auto-updating
   release — not yet an autonomous platform. The learning supervisor is bounded,
   stoppable and does not update the running packaged app. See
   [autonomous platform audit](docs/AUTONOMOUS_PLATFORM_AUDIT.md).

- For an opt-in repository-aware self-development loop, run `babymind develop
  "describe a change"` against BabyMind's configured source checkout. It can
  search and read source, propose hash-checked edits, and use the existing
  verification/rollback path without running all 50 roles. This is not an
  arbitrary-project agent; review changes and keep independent backups. See
  [autonomy](docs/AUTONOMY.md#opt-in-repository-aware-self-development).
- Autonomous learning does not require `babymind develop` or a manual mission.
  Its default-on supervisor reuses the same checkpoint/compile/test/rollback
  transaction with a narrower path guard. Use `babymind learning status`,
  `babymind learning stop`, or the Self-improvement view to inspect and stop it.
  See [permanent autonomous learning](docs/AUTONOMOUS_LEARNING.md).
- The requested acceptance target is Ubuntu 26.10 x86-64; current hosted CI
  uses Ubuntu 26.04 and is not a substitute for a 26.10 acceptance run.
- Chat's opt-in **Team** mode plans and runs a small dependency graph over
  2–4 existing roles, then shows their unverified contributions and an answer.
  It uses one model, no tools, and is not autonomous coding or research. See
  [team chat](docs/TEAMWORK.md) for privacy, limits and test coverage.
- Chat, history, local memory, advisory development review, mission control,
  read-only GitHub research, and optional integrations exist. A review is model
  output, not independent verification; the autonomous development platform is
  not complete. See [autonomous platform audit](docs/AUTONOMOUS_PLATFORM_AUDIT.md).
- The portable build includes a Python helper and source seed for sandboxed
  edits to a staged source copy. These edits do **not** rebuild or update the
  running packaged app. The helper requires a verified Linux namespace sandbox;
  it fails closed if the sandbox is unavailable. The source runner's `auto`
  mode can fall back to unsandboxed execution; do not use it for untrusted code.
  Packaged generated-app execution remains unavailable.
- Data is in `~/.babymind` (or `BABYMIND_HOME`). Conversation and memory text
  are encrypted, but on Linux the key is a local file readable by your user;
  protect the account and back up databases **and** keys. Encryption is not a
  defence against malware running as the same user.
- The Diagnostics window records a metadata-only log of everything the app
  does — every local API call (method, route, status, timing, error text; no
  request/response bodies, attachments or memories), every failed page/asset
  request, and every uncaught client error — to
  `~/.babymind/interactions.jsonl` (capped at 500 entries). The installed
  desktop app embeds the same view, so every model reply, task, approval and
  error it handles lands in the same log. The window shows a selectable report
  preview, per-entry **Copy** buttons, a **Copy log** button at the bottom of
  the log (one click to paste into a chat for help) and at the top, plus
  **Copy log path** and **Download .md**. The log is local and unencrypted;
  review it before sharing.
- BabyMind itself is licensed under the MIT License (see [LICENSE](LICENSE)
  and [NOTICE](NOTICE)). The pinned model, the llama.cpp runtime, the bundled
  Qt/WebEngine libraries and any third-party dependencies keep their own
  licenses; assess them before redistribution.

See [security policy](SECURITY.md) and [known limitations](docs/KNOWN_LIMITATIONS.md). Research answers follow the [source-quality and citation policy](docs/RESEARCH_SOURCE_POLICY.md).
