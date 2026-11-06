# BabyMind

> **Status: experimental / development software — NOT production-ready.**
> The autonomous-development features are partially implemented and not
> independently verified; see
> [production readiness programme](docs/PRODUCTION_READINESS.md) for the
> open gates.

BabyMind is a local-first AI workspace for **Linux x86-64** with a desktop
window and a bundled CPU llama.cpp runtime. Its 50 specialist roles are prompts
over one model, not independent people or independently trained agents.

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
bash -c 'if command -v curl >/dev/null 2>&1; then curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; elif command -v wget >/dev/null 2>&1; then wget -qO- https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; else if command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y curl ca-certificates; elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y curl ca-certificates; elif command -v pacman >/dev/null 2>&1; then sudo pacman -Sy --noconfirm curl ca-certificates; elif command -v zypper >/dev/null 2>&1; then sudo zypper --non-interactive install curl ca-certificates; else printf "Install curl or wget first.\n" >&2; exit 1; fi; curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/bootstrap-linux.sh; fi' | BABYMIND_LAUNCH_AFTER_INSTALL=1 bash
```

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
   and adds the application-menu entry.

Review the scripts before running them. It needs internet, a graphical desktop,
time to compile, and disk space (at least 4.5 GB for the model plus several GB
for dependencies; 10 GB free recommended), and it may ask for your sudo
password. When it finishes, BabyMind starts on its own; afterwards open it from
Applications or run `~/.local/bin/babymind`. Set
`BABYMIND_LAUNCH_AFTER_INSTALL=0` instead of `=1` in that command to install
without starting.

Preview without changing anything, or stop after preparing the machine:

```bash
bash bootstrap-linux.sh --dry-run        # print the plan (package manager, packages, Python)
bash bootstrap-linux.sh --prepare-only   # install prerequisites + newest Python, nothing else
```

Run either of them from a checkout to install that checkout instead of
downloading the newest source. `install-and-run-linux.sh` does the same work and
then starts BabyMind.

The apt path is exercised on real Ubuntu runners in CI (bootstrap preparation,
Qt build, packaged app, installer shell tests). Debian and Ubuntu derivatives are the only supported distribution family; the first-run
GUI with the production model remains unverified on a clean desktop. See
[verification](docs/LINUX_VERIFICATION.md) and
[known limitations](docs/KNOWN_LIMITATIONS.md).

## Continuous testing

The model is BabyMind's brain, so the real-model acceptance job runs on **every
push and every pull request** - it is not a manual, opt-in dispatch. On a fresh
Ubuntu VM it runs the actual `install-linux.sh` (package installation, the
2.71 GB model download and its SHA-256 check, the local build), starts the
installed desktop under Xvfb and drives it through the **full** extended
question set with the real model, then runs the real model through source-mode
chat questions, a coding task, a sandboxed self-edit and a 50-role mission on a
disposable copy of this source.

There are no manual variants of this workflow. Every trigger - push, pull
request or manual dispatch - runs the same complete set of jobs, and no job is
gated by a condition; `tests/test_real_model_ci.py` fails the build if a gate
or a job-selecting switch is ever added back.

A passing run shows the installer, the pinned model and CPU inference still work
together on the tested questions. It is not proof of role competence, of
correct advice, of behavior on a real Ubuntu Desktop session, or of packaged
self-upgrade. It is also slow: the job allows 180 minutes for the download, the
build, the GUI question set and a 50-role CPU mission, and it fails when the
model cannot answer the tested questions or produce a valid edit.

## Portable desktop

The target is a graphical Debian-based x86-64 desktop with glibc 2.39 or newer (Ubuntu 24.04+,
because Qt 6.12 requires glibc 2.34 or newer and the release is built on 24.04)
and standard Qt WebEngine system libraries. Extract the complete
Linux portable archive and run `./BabyMind` (or open the executable in your file
manager). On first launch BabyMind asks to download a roughly 2.71 GB model,
verifies its SHA-256, and saves it under `~/.babymind/models`. The download
requires internet and at least 4.5 GB free. Subsequent launches use the local
model. There is no API key, paid service, LM Studio or auto-updater.
CPU inference may be slow and needs substantial memory.

The Linux package and first-run GUI have **not yet been validated end to end**
on a normal Ubuntu desktop with the production model. See
[Linux portable instructions](docs/LINUX_PORTABLE.md) for compatibility,
building from source, and current limitations. Linux is the sole supported
desktop target.

## Safety and capabilities

Current capability status (honest, matches the code):

1. **Build digital applications** — *partially supported*: the opt-in app
   builder plans, writes, and sandboxed-runs one generated app, then runs an
   automatic behavior check on the result. Packaged builds cannot execute
   generated code (fail closed).
2. **Automatically fix errors** — *limited*: `/api/verify/fix` verifies
   (compile + tests + sandboxed behavior + sandbox boundary), then runs a
   bounded propose→verify→rollback repair loop. Fixes are only kept when all
   checks pass.
3. **Research internet and GitHub** — *limited*: web search/page-read and
   read-only GitHub metadata research exist; page content is treated as
   untrusted. No autonomous browsing or repo cloning.
4. **Fully autonomous development** — *incomplete*: missions (sequential or
   phase-parallel graph mode), checkpointed self-edits with rollback, and
   independent verification exist, but there is no typed task-graph state,
   worktree isolation, or signed/auto-updating release — not yet an
   autonomous platform. See [autonomous platform audit](docs/AUTONOMOUS_PLATFORM_AUDIT.md).

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
- Downloads, third-party dependencies and the model have their own licenses;
  assess them before redistribution. This repository currently has no top-level
  license file. No license to redistribute the project is implied.

See [security policy](SECURITY.md) and [known limitations](docs/KNOWN_LIMITATIONS.md). Research answers follow the [source-quality and citation policy](docs/RESEARCH_SOURCE_POLICY.md).
