# Autonomous platform audit

Audit of repository baseline `50291f753b5f1ed34274a12ef141dbf0d426cc68` and the changes in this working branch. This is an engineering status report, **not a release acceptance report**. The autonomous Windows platform requested in the mission is not complete.

## Current implementation and gaps

| Area | Repository evidence | Status against mission |
| --- | --- | --- |
| Desktop and UI | `desktop.py`, `server.py`, `web/`, `build-windows.ps1` | Existing desktop/web assistant and portable build script. The requested end-to-end autonomous development workspace is not present. A Windows package was not built or run in this environment. |
| Agents | `agents.py`, `coordinator.py`, `development_review.py` | The general-purpose catalogue remains separate. The development-review view now makes a model call for each of the requested 50 development roles, sequentially, and records reports and attempts. These are advisory reviews of supplied text: they have no development tools, verified completion, independent verification, parallel scheduling, or autonomous task execution. |
| Coding | `integrations/coding.py`, `integrations/coding_agent.py` | Coding assistance drafts responses. The bounded agent loop supports injected handlers but provides no real workspace or shell handlers. This is not an autonomous coding engine. |
| Workspace | `approval.py`, `workspace_readiness.py`, `native/windows_workspace/` | Workspace actions remain disabled. The Windows C++ component is a prototype; its broker executable deliberately denies requests. It lacks production ACL provisioning, a working authorization/dispatch path, editing and deletion, and independent security review. |
| Sandboxed execution | `workspace_readiness.py`, native broker documentation | Project execution is disabled. There is no verified general-purpose Windows execution sandbox, including the requested isolation, network, resource and cleanup guarantees. Do not substitute a same-user subprocess. |
| Self-upgrade/recovery | `backup.py`, `build-windows.ps1` | Password-protected local database backup/restore exists. Source checkpoints, transactional source patches, tested rollback, and a separate installation update supervisor do not. Database backup is not a source-code rollback. |
| Local inference | `providers.py`, `first_run.py` | llama.cpp provider, CPU packaging path and pinned default model with SHA-256 verification exist. Hardware-aware model selection, management of multiple models, and proven real-world performance on the target laptop are not established. |
| Memory | `memory.py`, `backup.py` | Opt-in encrypted SQLite task/response memory and lexical retrieval exist. The required comprehensive development history, versioned project memory, and automatic recovery are not complete. |
| Research and integration | `research.py`, `github_research.py`, `integrations/upstream_components.py`, `.gitmodules` | Bounded web search/page reading and anonymous, read-only GitHub repository/commit/file inspection are available. There is no autonomous license/security-reviewed component integration pipeline. Submodule references alone are not integrations. |
| Testing and delivery | `tests/`, `.github/workflows/tests.yml` | Existing Python tests and a Windows native test/build workflow exist. Neither a Windows release installation nor the required real-model coding/self-modification acceptance scenarios were run here. |

## Changes made during this audit

- Fixed new user text beginning with `bmenc:v1:` being mistaken for already encrypted data. New values are now always encrypted; only the explicitly named legacy migration path treats the old marker as evidence of an existing encrypted record. Added unit and database-restart regression tests for memory and conversations.
- Existing legacy records that already begin with the marker are intrinsically ambiguous: the old format has no separate flag to distinguish marker-prefixed plaintext from damaged ciphertext. Migration preserves them rather than silently treating damaged encrypted data as plaintext. Do not delete the key or database if such a record cannot be read; preserve a backup for investigation.
- Deferred the Tk import for already-verified models, so checking an existing model does not unnecessarily require the GUI toolkit.
- Added a separate development-review screen and backend. Each of the requested 50 roles receives a shared-model inference call; reports and attempt statuses are encrypted and saved. The review is resumable and supports cancellation between calls. It does not execute development tasks or verify claims. The existing general-purpose catalogue is unchanged.
- Added a GitHub research screen and backend. Anonymous queries go to the fixed GitHub API host. Public files are read at a pinned commit and checked against the reported Git blob ID; tree and response limits apply. Users can add an excerpt to review context. This does not install code, validate licenses, verify safety, or integrate external components.

## Verification performed in this environment

- Linux x86-64, Python 3.11.2; isolated environment with `cryptography` 50.0.2.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q`: **175 tests passed** on this branch. These are repository unit/integration tests, many with fakes; the 50-role review was tested with fake providers and a local HTTP test server, not a real local model. They do not prove real-model autonomy or Windows isolation.
- Tested an isolated archive of GitHub `main` at `f3a51e8871de0b088e2f2527fb13a2eea6c4ca1e` with this branch's `first_run.py` and its regression tests overlaid: **262 tests passed** on Linux (exit code 0). This was a compatibility check only; these changes were not merged into `main`.
- Real GitHub API smoke test: searched for `octocat/Hello-World`, inspected commit `7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`, and read its `README` through the pinned tree/blob integrity path. This does not verify arbitrary upstream content or the desktop UI.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `node --check` on `app.js`, `development.js`, `github-research.js` and `approvals.js`: passed.
- `git diff --check`: passed.
- No GitHub Actions were triggered. Windows 11, MSVC, the target hardware, a configured llama.cpp server/GGUF model, and a Windows desktop session were not available here. Windows native tests, Windows packaging/install/startup, model inference, sandbox escape tests, real coding tasks, self-upgrades, and upgrade rollback/restart remain **not run**.

## Critical path to the requested acceptance

1. Design, implement and independently review a broker with scoped ACL provisioning, handle-relative reads and transactional changes, crash-safe checkpoints, auditable operations and Windows race/escape tests. Keep the current gate closed until verified.
2. Implement a separately isolated Windows execution service with enforceable filesystem/network restrictions, resource limits, cancellation and cleanup; test adversarial code and protected-data access on Windows 11 Home. No untrusted project execution until this gate passes.
3. Build an evidence-based development orchestrator: the exact 50 requested roles, persisted assignments and results, resource-aware scheduling, failure/retry handling, tool permissions and a verifier that records actual build/test evidence. Shared-model role outputs are not independent models or proof of completed work.
4. Connect planning, research, workspace transactions, sandboxed build/test/debug cycles, durable project memory, diff/history controls and recovery into the desktop UI. Add a separate recoverable updater before attempting self-updates.
5. Run the mission's acceptance scenarios with a real local model on the target Windows hardware, including clean install, crash/restart, malicious project isolation, and failed-upgrade rollback. Record commands, outcomes, artifacts and remaining limitations without substituting unit tests for those scenarios.

These dependencies are substantial engineering and validation work; this audit and its fixes do not complete them.
