# BabyMind: one-day completion scope and integration decisions

**Target:** deliver the most complete usable Windows 11 release candidate possible in one focused day.
**Release promise:** working features only; no security claims based on an unreviewed prototype.
**Current base:** `approval-gated-project-test-runner`, commit `39f996e40eeb187fb1af8c1ac3848f46dba1fe8f`.

This document is the product contract for the accelerated build. It deliberately distinguishes implemented features, same-day work, and capabilities that must remain disabled until their security requirements are met.

## 1. Product definition

BabyMind is one local-first personal assistant with one identity, one conversation history, one memory system, and one user interface. The 50 BM roles are specialist modes selected by the coordinator; they are not 50 separate models or autonomous processes.

Primary device: Windows 11 laptop. Secondary device: iPhone on the same trusted private network. Default inference and storage remain local. Public web research and any explicitly connected third-party service are disclosed as network operations.

## 2. Features required for a complete personal assistant

| Feature | Current state | Release requirement |
|---|---|---|
| Unified identity and 50 specialist roles | Implemented foundation | Keep one personality; roles are expertise profiles |
| Local model support | llama.cpp-only local inference | Fixed runtime, connection test, context/model settings, clear errors |
| Chat and conversation history | Implemented foundation | Search, rename, delete, export, resume |
| Encrypted local memory | Implemented foundation; lexical retrieval | User-controlled remember/use switches, inspect/search/delete/export, memory backup |
| Task queue | Implemented foundation | Task details, status, pause/resume/cancel, durable run history |
| Web research | Implemented bounded search and page reading | Source list, dates where available, source text marked untrusted, user-controlled toggle |
| File/project understanding | Disabled pending native security | Read-only access only after broker review; no Python path fallback |
| Code generation | Model can generate code in chat | Show patch/diff; never silently apply |
| Code editing | Disabled | Approval-bound diff and rollback after secure broker is reviewed |
| Test execution | Disabled | OS sandbox with filesystem, network, process and resource restrictions |
| Browser automation | Not integrated | Optional Browser Use adapter; visible browser, per-action approval, no saved-password or payment actions without explicit approval |
| Voice input/output | Not integrated | Optional local speech-to-text and text-to-speech; microphone permission explicit |
| Image/file understanding | Small text attachments only | Add bounded PDF, image and document extraction with clear size limits; do not execute attachments |
| Knowledge base / RAG | Not integrated | Local-only document index, source citations, delete/rebuild controls |
| Automation / reminders | Not integrated | User-created schedules, visible next run, pause/disable, audit trail |
| Self-improvement | Not implemented | Suggest changes, create branch and tests, show diff; user approves merge/release |
| Backups and restore | Not complete | Encrypted export, backup verification, restore test, documented key recovery |
| iPhone access | Trusted LAN HTTPS foundation | Pairing/revoke controls, no public exposure, responsive UI |
| Diagnostics | Basic health endpoint | One-click diagnostics with redacted logs and model/runtime/DB/port checks |
| Updates | Portable build foundation | Version display, signed release preferred, checksum verification and rollback instructions |
| Accessibility and usability | Existing web UI | Keyboard support, readable status/errors, reduced-motion and mobile layout |

## 3. Reuse decisions: integrate selectively, do not assemble a fragile pile

### A. Coding and computer actions: disabled pending a llama.cpp-native adapter

Repository: https://github.com/openinterpreter/openinterpreter  
License: Apache-2.0 (verify the exact pinned release before redistribution).

The current external CLI adapter is disabled because its local-provider integration does not provide a verified direct connection to BabyMind's llama.cpp server. Do not launch it through another runtime. A future coding subsystem must connect directly to llama.cpp, enforce a reviewed OS-level workspace boundary, and preserve BabyMind's approval records before it can be enabled.

**Current decision:** keep coding execution disabled. Revisit only after a llama.cpp-native adapter and independently enforced Windows sandbox have been reviewed and tested.

References:
- https://github.com/openinterpreter/openinterpreter/blob/main/docs/windows.md
- https://github.com/openinterpreter/openinterpreter/blob/main/docs/sandbox.md

### B. Browser automation: Browser Use

Repository: https://github.com/browser-use/browser-use  
License: MIT.

Keep as an optional adapter, not a required dependency for the core application. It can connect to a local browser and local model. Require a visible session, domain allowlists where practical, and approval before submissions, account changes, purchases, messages, or other external side effects. Treat page content as untrusted prompt-injection-capable data.

Reference: https://github.com/browser-use/browser-use

### C. Long-term memory: keep BabyMind's encrypted SQLite memory for this release

Mem0 (Apache-2.0) and Letta (Apache-2.0) are credible projects, but adding either today would duplicate the existing local encrypted memory layer and expand dependency, migration, and privacy risk. Keep the existing memory for the same-day release. Design a provider interface so a future optional semantic-memory backend can be evaluated without replacing the user's records.

References:
- https://github.com/mem0ai/mem0
- https://github.com/letta-ai/letta

### D. Agent orchestration: do not embed all of OpenHands today

OpenHands Agent Canvas is a mature self-hosted coding-agent control center, but its documented deployment choices introduce Node.js, agent-server services and/or Docker. That is a large second application stack for this Windows laptop and duplicates BabyMind's interface and task queue. Reuse its architectural ideas (backend adapters, isolated workspaces, automation dispatch) rather than importing the full product today.

Reference: https://github.com/OpenHands/OpenHands

## 4. Architecture to implement

1. **BabyMind UI and identity:** existing app remains the only user-facing home.
2. **Coordinator:** routes a request to one of the 50 roles using the one configured model.
3. **Model adapter:** llama.cpp only; no alternate runtime or hidden cloud fallback.
4. **Memory service:** existing encrypted SQLite store; explicit remember/use/delete controls.
5. **Tool registry:** each tool declares input schema, risk class, required permissions, timeout, network access and audit fields.
6. **Policy/approval gateway:** validates exact action, target, content hash, scope, expiry and one-time approval. Approval is not inferred from conversation text or model output.
7. **Execution adapters:** browser, files and coding tools are separate adapters. Each fails closed if its security boundary is unavailable.
8. **Audit and recovery:** append-only action events, redacted logs, backups, rollback instructions and clear error reporting.

No plugin, tool, model, webpage, attachment or memory may grant itself new permissions. Retrieved content is evidence/data, never policy.

## 5. Same-day implementation order

### P0 — usable assistant
- Confirm clean Windows install/build and current CI.
- Confirm local model connection and model discovery.
- Verify chat, history, 50 roles, task queue and memory end-to-end.
- Add a diagnostics page/command that checks model endpoint, storage, encryption key availability, server bind address and feature flags.
- Add memory export/import with encryption and a restore verification test.
- Ensure settings clearly show local vs network operations and all feature flags.

### P1 — practical productivity
- Improve conversation search, rename, delete and Markdown export.
- Improve task queue history and task details.
- Add a project workspace registry that only stores user-selected roots; it must not enable filesystem access.
- Add patch proposal display and approval records without applying patches.
- Add tool registry schemas and structured audit events.
- Add browser adapter interface, with execution disabled until per-action approval and sandbox checks pass.

### P2 — guarded coding capability
- Implement and review a direct llama.cpp-native coding adapter and its Windows sandbox before enabling execution.
- Run any future coding session only as an explicit, separately visible user-approved session.
- Confirm its configured workspace and command permissions before any command.
- Do not claim protection against hostile same-user processes unless an independent security boundary exists.
- Never fall back to raw Python path-based file operations.

### P3 — release hardening
- Run all Python tests, native C++ tests, Windows desktop build, dependency audit and smoke tests on the final commit.
- Verify portable artifact, checksum, clean-machine launch and uninstall/rollback instructions.
- Verify LAN pairing/revocation and ensure no public-interface bind by default.
- Document known limitations and exact enabled capabilities.

## 6. Security gates that cannot be waived to meet a deadline

- The native C++ Windows workspace broker in `native/windows_workspace/` is an experimental prototype, not yet connected to Python or the application and not independently security-reviewed.
- Keep `WORKSPACE_FILE_ACTIONS_ENABLED = False` until the broker is reviewed, Python uses only the native ABI, race-focused tests pass, approval tokens bind to exact operations, and packaging/ABI failures fail closed.
- Project-code execution remains disabled until a real OS-level sandbox is implemented and reviewed for filesystem, network, process and resource isolation.
- A normal child process launched under the same Windows user is not, by itself, a security boundary against hostile same-user software.
- Do not add automatic installs, shell execution, file edits, deletes, Git pushes, merges, messages, purchases or account changes without explicit approval.
- Do not disable dependency audits or tests to obtain a green build.

## 7. Acceptance criteria for calling today's build usable

- A fresh Windows 11 setup can launch BabyMind and connect to a local model using documented steps.
- All 50 roles route through the same assistant identity and configured model.
- Conversation history and opt-in encrypted memory survive restart.
- User can inspect, search, export and clear memory.
- Web research is opt-in and shows sources; page content cannot override tool policy.
- Task state and action proposals are visible; unapproved actions do not execute.
- Workspace file actions and code execution remain visibly disabled unless their respective security gates are actually passed.
- CI passes on the exact release commit; portable artifact starts on a clean Windows user profile.
- The README accurately describes what works and what remains disabled.

## 8. Explicit non-goals for a one-day release

A one-day build cannot honestly guarantee a fully autonomous self-modifying AI, hostile same-user isolation, production-grade browser automation across arbitrary websites, robust voice UX, semantic RAG over every file type, or a security-reviewed general-purpose Windows execution sandbox. These remain future capabilities, not fake checkboxes.

**Release rule:** ship the maximum useful, tested capability today; do not label blocked capabilities as complete. The target is a dependable BabyMind release candidate, not an unsafe demo marketed as a finished autonomous agent.
