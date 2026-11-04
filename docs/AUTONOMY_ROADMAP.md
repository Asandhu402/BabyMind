# BabyMind autonomy roadmap

**Platform target: Linux only.** Build, CI, packaging, runtime, and release work must target Linux. The 50 roles are configurations over one shared local model.

## Phase 1 — bounded web research

- Search the public web through a fixed search-provider endpoint.
- Return source titles, destination URLs, and short provider snippets.
- Do not execute page scripts, download files, or automatically open arbitrary URLs.
- Bound query length, result count, response size, and timeout.
- Treat search results and snippets as untrusted content, never as instructions.
- Show source links; do not claim a fact is verified merely because it appeared in a search result.

## Phase 1.1 — bounded source-page reading

- Optionally read up to two search-result pages per chat request.
- Accept only HTTP(S) on standard ports; reject private, local, reserved, credential-bearing, and unsafe redirect targets.
- Fetch at most 1 MB per page with a 12-second timeout; accept HTML and plain text only.
- Extract bounded text, omit scripts/styles/navigation/forms, and never execute page code.

## Phase 1.2 — encrypted local memory

- Keep memory opt-in for saving and using prior notes.
- Rank recent encrypted records by local lexical relevance and recency.
- Provide local search for saved memories.
- Do not send memory content to a cloud service.
- Store encryption keys separately with Linux owner-only file permissions.

## Phase 2A — visible task queue

- Persist up to 100 user-created tasks in the local encrypted SQLite database.
- Provide queued, active, paused, completed, cancelled, and terminated states.
- Enforce valid state transitions on the server.
- Keep task tracking separate from execution authorization.

## Phase 2B — Linux-native controlled workspace access (security-blocked)

- Workspace listing, filename search, text preview, file creation, and text editing remain disabled until a Linux-native broker is implemented, tested, and independently reviewed.
- Use descriptor-relative filesystem operations and defend against symlink traversal, mount-boundary escapes, path replacement races, and unsafe concurrent writes.
- Bind narrowly scoped, single-use approvals to the exact operation, selected workspace, and target.
- Do not re-enable file actions through a feature flag or additional path-string checks.

## Phase 2C — Linux OS-enforced project execution (security-blocked)

- Project commands and tests remain disabled until a real Linux sandbox is implemented and independently reviewed.
- Enforce filesystem, network, process, and resource restrictions using an appropriate Linux isolation design.
- Include process-tree termination, timeouts, output limits, environment scrubbing, and explicit workspace boundaries.
- Verify sandbox behavior with adversarial tests; do not describe a subprocess, container, or path check alone as a security sandbox.

## Phase 3 — reviewed code changes and self-development

- Restrict code editing to a user-selected project folder or a separately protected BabyMind source workspace.
- Generate reviewable diffs before applying changes; preserve checkpoints and support automatic rollback.
- Keep secrets, model files, databases, and encryption keys outside generated patches.
- Require clear approval for consequential changes, Git pushes, merges, releases, and external side effects.
- Record changes and tool activity in a tamper-evident audit trail.
- Self-modification must not be able to disable its own security gates or erase its audit history.

## Phase 4 — optional local capability adapters

- Keep document parsing, speech transcription, local speech synthesis, browser automation, and knowledge retrieval optional and lazy-loaded.
- Use local engines where practical; clearly disclose network requests.
- Browser automation remains visible, supervised, and explicitly approved.
- Treat converted documents, transcripts, browser content, and retrieved knowledge as untrusted data.
- Do not claim an adapter is wired into the chat UI or independently sandboxed unless integration and security tests prove it.

## Security and privacy boundaries

- Local inference and conversation storage remain on the user's Linux computer by default.
- Web research sends the search query to the configured public search provider; this is not offline operation.
- Search results and page contents are untrusted. Prompt-injection text must not override system instructions or authorize tools.
- LAN access remains opt-in, authenticated, TLS-protected, and intended only for trusted private networks.
- Linux file permissions and key-storage behavior must be documented accurately.
- Preserve existing user data and provide a tested backup/restore procedure.

**Do not enable workspace writes or project execution until their Linux-native security boundaries and tests pass.**
