# Testing on Ubuntu 26.10

BabyMind is **Debian-based Linux for x86-64 only**, and its testing platform is
**Ubuntu 26.10** ("Stonking Stingray", released 2026-10-15, Python 3.14.7,
glibc 2.43). This page is the single place that explains how that testing is
wired and what is required to make it actually run.

## What CI expects

| Job / file | Runner | Purpose |
| --- | --- | --- |
| `linux` matrix (Python 3.13, 3.14, 3.15) — `.github/workflows/tests.yml` | `ubuntu-26.10` | Portable build, full unit suite, llama.cpp fixture, packaged-app checks |
| `source-latest` | `ubuntu-26.10` | Source-only suite with Python 3.15 |
| `bootstrap` | `ubuntu-26.10` | `bootstrap-linux.sh --prepare-only` end to end |
| `bootstrap-plan` | `ubuntu-24.04` | A too-old distribution (Python 3.12) must plan the python.org source build; cannot run on 26.10 |
| `real-model-installer` | `ubuntu-26.10` | Real installer, real ~2.71 GB pinned model, full GUI question set under Xvfb, coding task, disposable self-edit, 50-role mission |
| `release` — `.github/workflows/release.yml` | `ubuntu-26.10` | Release archive build |

`tests/test_real_model_ci.py` enforces that the real-model job stays
permanent (no job-level `if:`, no dispatch switches), so this table is
expectation, not opt-out.

## Quick readiness check (run this on the 26.10 machine first)

```bash
bash scripts/check-ubuntu-26.10-ready.sh
```

Read-only: it verifies the OS release, architecture, glibc ≥ 2.43, apt-get,
passwordless sudo, toolchain, Python 3.13-3.15, network reachability of GitHub,
PyPI, Hugging Face, the Ubuntu archive and python.org, disk (≥ 10 GB), RAM
(≥ 4 GB, 8 GB recommended), the unprivileged-user-namespace AppArmor state and
Xvfb. It prints `READY` or lists every gap; fix those before registering the
runner.

## The blocker: there is no hosted `ubuntu-26.10` label

GitHub-hosted runners currently offer `ubuntu-22.04`, `ubuntu-24.04`,
`ubuntu-26.04` (plus `-arm` variants and `ubuntu-slim`), but **not**
`ubuntu-26.10` — GitHub does not publish interim (non-LTS) releases. Every
`ubuntu-26.10` job above therefore stays `QUEUED` until a self-hosted runner
with the label `ubuntu-26.10` is registered, or GitHub adds the label.

The workflows intentionally keep `ubuntu-26.10` rather than silently falling
back to an LTS runner: testing on anything else is not what this project
claims.

## Registering a self-hosted Ubuntu 26.10 runner

Use a **dedicated, disposable VM or machine** running Ubuntu 26.10 x86-64.
Do not register a machine that holds anything you care about: this is a
**public** repository, and its workflows run on every push and pull request.

1. Harden first (see "Public-repository safety" below).
2. Install the prerequisites the runner and workflow need:

   ```bash
   sudo apt-get update
   sudo apt-get install -y curl ca-certificates sudo xvfb xauth libnss3 libgl1 libegl1 libgbm1 libdrm2 \
     dbus-x11 libxkbcommon0 libfontconfig1
   ```

   The workflow installs the remaining Qt/WebEngine libraries itself via apt.

3. In the repository on GitHub: **Settings → Actions → Runners → New
   self-hosted runner → Linux → x64**. Follow the download and checksum
   instructions shown there for the current runner release, then configure it
   with the exact label the workflows use:

   ```bash
   ./config.sh --url https://github.com/Asandhu402/BabyMind \
     --token <registration-token> --labels ubuntu-26.10
   sudo ./svc.sh install && sudo ./svc.sh start
   ```

   Confirm it appears online in **Settings → Actions → Runners** (a green
   dot). Listing runners from the API requires admin:
   `gh api repos/Asandhu402/BabyMind/actions/runners`.

4. Trigger a run (push to `main`, open a PR, or "Re-run all jobs" on a queued
   workflow). The `linux` jobs should start immediately; the
   `real-model-installer` job will download ~2.71 GB, build llama.cpp and can
   take well over an hour — its timeout is 180 minutes.

### Public-repository safety

- In **Settings → Actions → General → Fork pull request workflows**, require
  approval for first-time and outside collaborators, so a random fork PR
  cannot execute arbitrary code on the runner.
- The runner user needs passwordless sudo (the workflow installs packages and
  applies the AppArmor sysctl for unprivileged user namespaces). Scope that
  sudo narrowly if your policy allows, or accept it on a disposable VM.
- Never put personal credentials, SSH keys, cloud tokens or the user's
  `~/.babymind` on the runner. The workflow uses none of them; if you add
  secrets, that is a different trust decision than this project makes by
  default.
- Prefer an ephemeral, reprovisioned VM image. An ordinary always-on machine
  accumulates state (build caches, `~/.babymind`, logs) that makes runs
  non-reproducible and can leak between runs.

## Acceptance criteria — what "tested on Ubuntu 26.10" means

Ubuntu 26.10 support is claimed only when all of the following have completed
on a 26.10 runner and the results are recorded in
[LINUX_VERIFICATION.md](LINUX_VERIFICATION.md):

1. `linux` matrix green for Python 3.13, 3.14 and 3.15 (portable build, unit
   suite, llama.cpp fixture, packaged-app checks).
2. `source-latest` green (Python 3.15).
3. `bootstrap` green (`--prepare-only` on a bare 26.10 machine).
4. `real-model-installer` green: real installer run, ~2.71 GB model download
   with SHA-256 verification, installed desktop launched under Xvfb, full
   extended GUI question set, coding task, sandboxed self-edit on a disposable
   source copy, and the 50-role mission.

Until then, 26.10 is the configured testing target, not a verified platform.
Xvfb is not an Ubuntu Desktop session; a clean desktop run with the production
model remains unverified separately.

## Bootstrap-plan is the deliberate exception

`bootstrap-plan` asserts that a distribution whose Python is below the 3.13
floor plans a python.org source build instead of stopping. Ubuntu 26.10's
Python is supported, so the job runs on `ubuntu-24.04` (Python 3.12). If GitHub
ever publishes the 26.10 label, revisit this job — it must stay on a too-old
distribution or move to an older Debian-based release, never to 26.10.

## If GitHub ships `ubuntu-26.10` hosted runners later

No repository change is needed: every job already targets `ubuntu-26.10`.
Delete or repurpose the self-hosted runner, and remove the "requires a
self-hosted runner" notes from README.md, KNOWN_LIMITATIONS.md,
LINUX_PORTABLE.md, PYTHON_SUPPORT.md and `.github/workflows/tests.yml`, and
record the first hosted run in LINUX_VERIFICATION.md.
