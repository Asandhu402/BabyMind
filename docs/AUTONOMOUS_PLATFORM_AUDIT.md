# Autonomous platform audit

Status of the branch after incorporating GitHub `main` at `f3a51e8871de0b088e2f2527fb13a2eea6c4ca1e` (PR #43) and this branch's changes. **This is not a release acceptance report.** BabyMind is not yet the complete autonomous Windows platform described in the mission.

| Area | Evidence | Current scope and limitations |
| --- | --- | --- |
| Agents | `agents.py`, `orchestrator.py` | The mission orchestrator schedules 50 development roles over one shared model and records outcomes, including errors and deferred roles. Roles are sequential; model text alone is not independent verification. |
| Development reviews | `development_review.py`, `web/development.js` | A separate advisory workflow calls 50 role prompts sequentially on supplied text, persists reports and attempts encrypted, and supports cancel/retry. It does not read projects, apply changes or verify tests. It and mission control are distinct workflows with separate scheduling. |
| Self-development | `selfdev.py`, `runner.py` | A source-checkout engine implements checkpoints, edits, compile/test verification, rollback and a bounded repair loop. It is not an independently secured workspace broker and can run verification without an OS sandbox in `auto` mode. Crash recovery and acceptance are not complete. |
| Workspace broker | `native/windows_workspace/`, `workspace_readiness.py` | Experimental Windows primitives and an AppContainer IPC smoke test exist. The broker deliberately denies requests and is not a production, reviewed authorization and dispatch path. |
| Sandboxed execution | `sandbox.py`, `runner.py` | A Linux namespace backend is implemented. Windows and macOS backends are not. `BABYMIND_SANDBOX=auto` can execute without isolation if no backend is available; `require` refuses instead. Do not treat a same-user subprocess as a security sandbox. |
| Application builder | `builder.py` | Opt-in generation of small Python/HTML/CSS/JS applications under its configured apps directory. Not general multi-platform delivery; see `docs/KNOWN_LIMITATIONS.md`. |
| Local inference | `providers.py`, `first_run.py`, `hardware.py` | llama.cpp support, a pinned default model with SHA-256 verification, and hardware recommendations exist. Neither real model inference nor target-hardware performance was tested in this environment. |
| Memory and recovery | `memory.py`, `backup.py` | Encrypted opt-in task/response memory and password-protected database backup/restore exist. These backups are not source-code or installation rollback, nor a complete versioned project memory. |
| Research | `research.py`, `github_research.py` | Web and GitHub metadata research, plus anonymous commit-pinned inspection of public source files. License metadata and matching Git blob IDs do not establish safety or compatibility. No automatic reviewed integration pipeline exists. |
| Windows delivery | `desktop.py`, `build-windows.ps1` | Desktop launcher and portable-build script exist. Windows package build, install, startup, recovery, native isolation and end-to-end coding acceptance have not been tested here. There is no separate installation-recovery supervisor. |

For more detail on the main-branch implementation, including its own prior test results and limitations, see `docs/AUTONOMY.md`, `docs/KNOWN_LIMITATIONS.md`, and `docs/TEST_REPORT.md`. Those documents describe their original test runs, not this branch's test run below.

## Changes from this branch

- New user text beginning with `bmenc:v1:` is always encrypted instead of being mistaken for ciphertext. Only the explicitly named legacy migration path preserves the old marker. Legacy marker-prefixed plaintext is intrinsically ambiguous; preserve backups and keys if such data cannot be read.
- First-run setup verifies an existing model without importing Tkinter. If a model download is needed but Tkinter is missing, the error explains the requirement. The dialog still requires Tkinter.
- The separate development-review workflow records 50 shared-model advisory reports and their attempts. It does not replace or verify mission execution.
- The GitHub research view searches public repositories, lists a pinned commit's regular files, and reads bounded UTF-8 blobs with an integrity check. It does not clone, execute, install, license-clear or integrate upstream code.

## Verification on the combined branch

- Linux x86-64, Python 3.11.2, isolated environment with `cryptography` 50.0.2.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q`: **282 tests passed**. Many use fakes; these results do not demonstrate real-model autonomy or Windows isolation.
- Python compilation and `node --check` on the web JavaScript files passed.
- The GitHub research backend was also smoke-tested against the public `octocat/Hello-World` repository at commit `7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`. This is not a desktop UI or supply-chain security test.
- No Windows runtime, MSVC, target hardware, real GGUF model, or browser-driven UI test was available. No Windows installation, native sandbox escape test, model-authored coding task, installation upgrade or rollback was executed. Do not mark those acceptance requirements as passed.

## Remaining release gates

A reviewed Windows broker and OS-enforced execution sandbox, secure update supervisor, evidence-driven development and repair workflow, real-model tests, and Windows 11 installation/upgrade/recovery acceptance remain necessary. This branch does not claim those are finished.
