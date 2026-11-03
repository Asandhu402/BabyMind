# BabyMind autonomy roadmap

This roadmap adds capabilities incrementally while preserving the core invariant: **one BabyMind identity, one configured local language model, and 50 specialist role prompts sharing that same model.** No second model, cloud inference fallback, or LM Studio dependency is introduced.

## Phase 1 — bounded web research

- Search the public web through a fixed search-provider endpoint.
- Return source titles, destination URLs, and short provider snippets.
- Do not execute page scripts, download files, or automatically open arbitrary URLs.
- Keep requests bounded by query length, result count, response size, and timeout.
- Treat search results and snippets as untrusted content. They are evidence to evaluate, never instructions to follow.
- Show source links to the user; do not claim a fact is verified merely because it appeared in a search result.

## Phase 2A — visible task queue (implemented foundation)

- Persist up to 100 user-created tasks in the local encrypted SQLite database.
- Provide queued, active, paused, completed, cancelled, and terminated states.
- Enforce valid state transitions on the server; the browser cannot set arbitrary statuses.
- Provide Start, Pause, Resume, Complete, Cancel, and Terminate controls.
- The task tracker remains separate from execution. Phase 2B now supports an approval-gated, read-only directory listing inside a configured workspace; it does not read file contents, write files, run commands, browse pages, or perform external side effects.

## Phase 2B — controlled task execution (not yet implemented)

- Add a visible task queue with explicit user approval before external side effects.
- Start with reversible, local actions (read files in a user-selected workspace, create draft files, run tests).
- Require confirmation before overwriting/deleting files, installing software, sending messages, spending money, or changing accounts.
- Provide pause, resume, cancel, and terminate controls; log each action and its result.

### Phase 2B.1 — approval-gated read-only listing (implemented foundation)\n\n- Set `BABYMIND_WORKSPACE_ROOT` to an existing folder on the BabyMind computer.\n- Start a task, request a `list_directory` proposal for a relative subfolder, review its target and SHA-256 proposal fingerprint, then explicitly approve that exact fingerprint.\n- The server revalidates the path at execution time, rejects absolute paths and parent traversal, and lists at most 200 entry names/types. It never opens file contents or follows symlinks.\n- This is a narrow API foundation; it is not a general-purpose executor and does not yet provide a complete graphical proposal/approval experience.\n\n### Phase 2B.2 — approval-gated new text files (implemented foundation)

- Create a new allowlisted UTF-8 text file up to 32 KB inside an existing workspace folder.
- Keep proposed content encrypted in the local proposal store until approval.
- Require approval of the exact SHA-256 proposal. Revalidate the target and use exclusive file creation so a file added after review is never overwritten.
- No edits, deletes, shell commands, or arbitrary file types are supported.

### Phase 2B.3 — approval-gated text edits (implemented foundation)

- Edit only an existing allowlisted UTF-8 text file up to 32 KB.
- Show the complete before/after contents and target path before approval.
- Bind the proposal to the original file SHA-256 and exact proposed content.
- At approval, verify the original file is unchanged and replace it atomically; stale proposals are refused.
- This does not support binary files, arbitrary paths, or silent edits.

## Phase 3 — reviewed code changes

- Restrict code-editing to a user-selected project folder.
- Generate diffs first; never silently replace files.
- Run tests in a bounded subprocess with timeout and captured output.
- Require approval before applying changes and before any Git push or merge.
- Keep secrets, model files, databases, and encryption keys outside generated patches.

## Security and privacy boundaries

- Local inference remains on the user's computer.
- Web research necessarily sends the search query to the configured public search provider; this is not offline operation.
- Search results are untrusted. Prompt-injection text in pages/results must not override BabyMind's system instructions or authorize tools.
- No public-internet server exposure. LAN access remains opt-in, TLS-protected, and intended only for trusted private Wi-Fi.
- The Windows DPAPI key and database key files must be backed up together according to the existing recovery guidance.
