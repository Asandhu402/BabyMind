# BabyMind autonomy roadmap

**Platform target: Linux only.** Windows and macOS are unsupported and are not future build, CI, packaging, or release targets. See [the Linux-only platform mission](PLATFORM_MISSION.md) for migration phases and acceptance criteria.

The product goal remains one BabyMind identity, one configured local language model, and 50 specialist role configurations sharing that model. The 50 roles are not 50 independent models.

## Phase 1 — bounded web research

- Search the public web through a fixed search-provider endpoint.
- Return source titles, destination URLs, and short provider snippets.
- Do not execute page scripts, download files, or automatically open arbitrary URLs.
- Keep requests bounded by query length, result count, response size, and timeout.
- Treat search results and snippets as untrusted content. They are evidence to evaluate, never instructions to follow.
- Show source links to the user; do not claim a fact is verified merely because it appeared in a search result.

## Phase 1.1 — optional bounded source-page reading

- Optionally read up to two search-result pages per chat request.
- Accept only HTTP(S) on standard ports; reject private, local, reserved, credential-bearing, and unsafe redirect targets.
- Fetch at most 1 MB per page with a 12-second timeout; accept HTML and plain text only.
- Extract bounded text, omit scripts/styles/navigation/forms, and never execute page code.
- Treat all extracted page text as untrusted instructions and evidence. Reading a page does not verify its claims.

## Phase 1.2 — relevance-ranked encrypted local memory

- Keep memory opt-in for saving and using prior notes.
- Rank recent encrypted records by local lexical relevance and recency.
- Provide a local search field for saved memories.
- Do not generate embeddings, call a second model, or send memory content to a cloud service.
- Linux key protection must follow the Linux-only platform mission. Do not rely on Windows DPAPI for new installations.

## Phase 2A — visible task queue

- Persist up to 100 user-created tasks in the local encrypted SQLite database.
- Provide queued, active, paused, completed, cancelled, and terminated states.
- Enforce valid state transitions on the server; the browser cannot set arbitrary statuses.
- Provide Start, Pause, Resume, Complete, Cancel, and Terminate controls.
- Keep task tracking separate from execution authorization.

## Phase 2B — Linux-native controlled workspace access (security-blocked)

- Workspace listing, filename search, text preview, file creation, and text editing must remain disabled until the Linux-native broker is implemented, tested, and independently reviewed.
- Use descriptor-relative filesystem operations and defend against symlink traversal, mount-boundary escapes, path replacement races, and unsafe concurrent writes.
- Bind narrowly scoped, single-use approvals to the exact operation, selected workspace, and target.
- Do not re-enable file actions through a feature flag or additional path-string checks.
- Start with bounded listing, bounded reads, and exclusive new-file creation. Expand capabilities only after security evidence supports them.

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
- Use local engines where practical; clearly disclose any network requests.
- Browser automation remains visible, supervised, and explicitly approved.
- Treat converted documents, transcripts, browser content, and retrieved knowledge as untrusted data, never system instructions.
- Do not claim an adapter is wired into the chat UI or independently sandboxed unless integration and security tests prove it.

## Security and privacy boundaries

- Local inference and conversation storage remain on the user's Linux computer by default.
- Web research necessarily sends the search query to the configured public search provider; this is not offline operation.
- Search results and page contents are untrusted. Prompt-injection text must not override system instructions or authorize tools.
- LAN access remains opt-in, authenticated, TLS-protected, and intended only for trusted private networks. Do not expose the service to the public internet by default.
- Linux file permissions and key-storage behavior must be documented accurately. Do not claim encrypted storage is protected from malware running as the same user or from data access while the app is running.
- Preserve existing user data and provide a tested migration path for data created by legacy Windows builds.

## Platform migration gate

The repository currently contains Windows-specific documentation, workflows, packaging, desktop assumptions, and DPAPI handling. These are legacy implementation details and must be migrated or retired. A documentation change alone does not make the application Linux-ready.

**Do not enable workspace writes or project execution until their Linux-native security boundaries and tests pass.** Follow [PLATFORM_MISSION.md](PLATFORM_MISSION.md) and its acceptance criteria.
