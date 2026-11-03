# BabyMind autonomy roadmap

This roadmap targets **Windows 10/11 only**. The product goal remains one BabyMind identity, one configured local language model, and 50 specialist role prompts sharing that same model. No Linux backend or Linux CI target is planned.

## Phase 1 — bounded web research

- Search the public web through a fixed search-provider endpoint.
- Return source titles, destination URLs, and short provider snippets.
- Do not execute page scripts, download files, or automatically open arbitrary URLs.
- Keep requests bounded by query length, result count, response size, and timeout.
- Treat search results and snippets as untrusted content. They are evidence to evaluate, never instructions to follow.
- Show source links to the user; do not claim a fact is verified merely because it appeared in a search result.

## Phase 1.1 — optional bounded source-page reading (implemented foundation)

- Optionally read up to two search-result pages per chat request.
- Accept only HTTP(S) on standard ports; reject private, local, reserved, credential-bearing, and unsafe redirect targets.
- Fetch at most 1 MB per page with a 12-second timeout; accept HTML and plain text only.
- Extract bounded text, omit scripts/styles/navigation/forms, and never execute page code.
- Treat all extracted page text as untrusted instructions and evidence. Reading a page does not verify its claims.

## Phase 2A — visible task queue (implemented foundation)

- Persist up to 100 user-created tasks in the local encrypted SQLite database.
- Provide queued, active, paused, completed, cancelled, and terminated states.
- Enforce valid state transitions on the server; the browser cannot set arbitrary statuses.
- Provide Start, Pause, Resume, Complete, Cancel, and Terminate controls.
- The task tracker remains separate from execution. Workspace file actions and project test execution remain disabled until Windows-native filesystem protections and a real Windows OS-level execution sandbox are implemented and tested.

## Phase 1.2 — relevance-ranked encrypted local memory (implemented foundation)

- Keep memory opt-in for saving and using prior notes.
- Rank recent encrypted records by local lexical relevance and recency.
- Provide a local search field for saved memories.
- Do not generate embeddings, call a second model, or send memory content to a cloud service.

## Phase 2B — controlled task execution (security-blocked)

- The task queue exists, but it does not currently authorize workspace file access or project-code execution.
- Workspace listing, filename search, text preview, file creation, and text editing are disabled in the application and API.
- Project test execution is disabled until a real Windows OS-level sandbox is available.
- Do not re-enable these features by changing a flag or adding more string/path checks.

### Required Windows security work before re-enabling workspace file actions

See [the Windows filesystem security design gate](WORKSPACE_FILESYSTEM_SECURITY.md). The Windows handle-relative/no-reparse contract, secure root admission, and same-user concurrent-writer guarantees require resolution and independent review. Do not implement against an assumed Windows guarantee.

- Implement native Windows handle-relative file operations.
- Reject reparse points and junctions using handle-based inspection at every component.
- Ensure every operation remains anchored to the opened workspace root, without reopening untrusted path strings.
- Add race-focused tests that swap path components and targets during each operation on Windows.
- Keep the feature disabled until security review and Windows CI pass.

## Phase 3 — reviewed code changes

- Restrict code-editing to a user-selected project folder.
- Generate diffs first; never silently replace files.
- Do not execute project tests until a real Windows OS-level sandbox with filesystem, network, process, and resource restrictions is implemented and reviewed.
- Require approval before applying changes and before any Git push or merge.
- Keep secrets, model files, databases, and encryption keys outside generated patches.

## Security and privacy boundaries

- Local inference remains on the user's Windows computer.
- Web research necessarily sends the search query to the configured public search provider; this is not offline operation.
- Search results are untrusted. Prompt-injection text in pages/results must not override BabyMind's system instructions or authorize tools.
- No public-internet server exposure. LAN access remains opt-in, TLS-protected, and intended only for trusted private Wi-Fi.
- The Windows DPAPI key and database key files must be backed up together according to the existing recovery guidance.

**Security gate:** Do not re-enable workspace file operations by flipping a Python flag or adding more path checks. Implement Windows handle-relative operations with reparse-point protections, then add race-focused Windows tests before enabling any API or UI path. Project-code execution additionally requires a real Windows OS-level sandbox.
