# Testing on Ubuntu 26.04 LTS

BabyMind is **Debian-based Linux for x86-64 only**, and its
testing platform is **Ubuntu 26.04 LTS** (x86-64, glibc 2.43, ships Python
3.14). This page is the single place that explains how that testing is wired
and what is required before support can be called verified.

> **History.** On 2026-11-06 BabyMind was briefly configured for the interim
> Ubuntu 26.10 (released 2026-10-15, short support window). GitHub does not
> publish a hosted `ubuntu-26.10` label and no self-hosted runner was ever
> registered, so nothing ran on 26.10. The same day the workflows moved to the
> **Ubuntu 26.04 LTS** baseline, for which GitHub *does* publish a hosted
> runner. Ubuntu 26.10 support was never claimed and no 26.10 run occurred;
> the 26.10 configuration and what would have been required of it are recorded
> in [LINUX_VERIFICATION.md](LINUX_VERIFICATION.md). This document was renamed
> from `UBUNTU_26_10_TESTING.md`.

## What CI expects

| Job / file | Runner | Purpose |
| --- | --- | --- |
| `linux` matrix (Python 3.13, 3.14, 3.15) — `.github/workflows/tests.yml` | `ubuntu-26.04` | Portable build, full unit suite, llama.cpp fixture, packaged-app checks |
| `source-latest` | `ubuntu-26.04` | Source-only suite with Python 3.15 |
| `bootstrap` | `ubuntu-26.04` | `bootstrap-linux.sh --prepare-only` end to end |
| `bootstrap-plan` | `ubuntu-24.04` | A too-old distribution (Python 3.12) must plan the python.org source build; cannot run on 26.04 (Python 3.14 is supported) |
| `real-model-installer` | `ubuntu-26.04` | Real installer, real ~2.71 GB pinned model, full GUI question set under Xvfb, coding task, disposable self-edit, 50-role mission |
| `release` — `.github/workflows/release.yml` | `ubuntu-26.04` | Release archive build |
| `ui-diagnostics` | `ubuntu-24.04` | Headless jsdom functional test of the Diagnostics view |

`tests/test_real_model_ci.py` enforces that the real-model job stays
permanent (no job-level `if:`, no dispatch switches), so this table is
expectation, not opt-out.

GitHub publishes a hosted `ubuntu-26.04` runner, so unlike the 26.10 period no
self-hosted machine is required. Whether every job passes is unknown until the
workflow executes; no 26.04 run has been recorded as of 2026-11-06.

## Quick readiness check (optional, for a local or self-hosted machine)

```bash
bash scripts/check-ubuntu-26.04-ready.sh
```

Read-only: it verifies the OS release, architecture, glibc ≥ 2.43, apt-get,
passwordless sudo, toolchain, Python 3.13-3.15, network reachability of GitHub,
PyPI, Hugging Face, the Ubuntu archive and python.org, disk (≥ 10 GB), RAM
(≥ 4 GB, 8 GB recommended), the unprivileged-user-namespace AppArmor state and
Xvfb. It prints `READY` or lists every gap. Hosted runners run the workflow
directly; this check is for your own machine before trusting it with a manual
verification run.

## CI model cache

The `real-model-installer` job restores the pinned ~2.71 GB GGUF from the
GitHub dependency cache (`actions/cache`, key
`babymind-gguf-<MODEL_SHA256>`) before the installer runs, and drops a cached
file that fails SHA-256 so the installer re-downloads it. A cache miss behaves
exactly as before. The key must stay in sync with `MODEL_SHA256` in
`babymind/first_run.py`. The cache cannot be validated until the job executes;
treat the first run after this change as the test of the cache, not of the
installer itself.

## Optional: running the jobs on your own machine

If you want the jobs on real hardware (for example an Ubuntu 26.04 desktop,
not just CI VMs), use a **dedicated, disposable machine** running Ubuntu
26.04 x86-64. Do not register a machine that holds anything you care about:
this is a **public** repository, and its workflows run on every push and pull
request.

1. Harden first (see "Public-repository safety" below).
2. In the repository on GitHub: **Settings → Actions → Runners → New
   self-hosted runner → Linux → x64**, follow the instructions shown there,
   configure it with the label the workflows use (`ubuntu-26.04`), install and
   start the service, and confirm it shows online in **Settings → Actions →
   Runners**.
3. Trigger a run (push to `main`, open a PR, or re-run a queued workflow).
   `real-model-installer` downloads ~2.71 GB, builds llama.cpp and can take
   well over an hour — its timeout is 180 minutes.

### Public-repository safety

- In **Settings → Actions → General → Fork pull request workflows**, require
  approval for first-time and outside collaborators, so a random fork PR
  cannot execute arbitrary code on the runner.
- The runner user needs passwordless sudo (the workflow installs packages and
  applies the AppArmor sysctl for unprivileged user namespaces). Scope that
  sudo narrowly if your policy allows, or accept it on a disposable VM.
- Never put personal credentials, SSH keys, cloud tokens or the user's
  `~/.babymind` on the runner. The workflow uses none of them.
- Prefer an ephemeral, reprovisioned VM image. An ordinary always-on machine
  accumulates state (build caches, `~/.babymind`, logs) that makes runs
  non-reproducible and can leak between runs.

## Acceptance criteria — what "tested on Ubuntu 26.04 LTS" means

Ubuntu 26.04 support is claimed only when all of the following have completed
on Ubuntu 26.04 runners and the results are recorded in
[LINUX_VERIFICATION.md](LINUX_VERIFICATION.md):

1. `linux` matrix green for Python 3.13, 3.14 and 3.15 (portable build, unit
   suite, llama.cpp fixture, packaged-app checks).
2. `source-latest` green (Python 3.15).
3. `bootstrap` green (`--prepare-only` on a bare 26.04 machine).
4. `real-model-installer` green: real installer run, ~2.71 GB model
   download/restore with SHA-256 verification, installed desktop launched
   under Xvfb, full extended GUI question set, coding task, sandboxed
   self-edit on a disposable source copy, and the 50-role mission.

Until then, Ubuntu 26.04 is the configured testing target, not a verified
platform. Xvfb is not an Ubuntu Desktop session; a clean desktop run with the
production model remains unverified separately.

## Bootstrap-plan is the deliberate exception

`bootstrap-plan` asserts that a distribution whose Python is below the 3.13
floor plans a python.org source build instead of stopping. Ubuntu 26.04's
Python is supported (3.14), so the job runs on `ubuntu-24.04` (Python 3.12).
It must stay on a too-old distribution; never move it to a release whose
Python satisfies the floor.

## Ubuntu 26.10, for the record

Ubuntu 26.10 was the configured testing target from 2026-11-06 (morning) and
was never executed: GitHub publishes no hosted `ubuntu-26.10` label and no
self-hosted runner was registered. It was replaced by the 26.04 LTS baseline
later the same day because the hosted `ubuntu-26.04` label exists and 26.10 is
a short-lived interim release. No claim that BabyMind ran, or passes, on
Ubuntu 26.10 was ever made; see
[LINUX_VERIFICATION.md](LINUX_VERIFICATION.md) for the recorded history.
