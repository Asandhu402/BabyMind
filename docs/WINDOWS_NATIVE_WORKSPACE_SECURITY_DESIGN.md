# Windows Native Workspace Security Design

**Status: experimental native primitives implemented — root admission, handle-relative bounded reads, and exclusive new-file creation exist; not independently reviewed or approved for enablement.**

This document defines a conservative Windows-only design for BabyMind's future workspace file broker. The existing Python workspace implementation is not a security boundary. Keep `WORKSPACE_FILE_ACTIONS_ENABLED = False` and keep project test execution disabled until the implementation and adversarial tests have been independently reviewed.

## 1. Security goals and non-goals

The first release should provide only narrowly scoped, approval-gated workspace operations:

- Enumerate one explicitly selected directory (names and basic types only).
- Read one explicitly selected, bounded UTF-8 text file.
- Create one new text file without overwriting an existing name, if the directory and file identity checks can be made race-resistant.

Do **not** implement editing, deleting, recursive search, arbitrary command execution, process launching, or project test execution in the first native release. Add capabilities only after a separate threat review and test suite.

The broker must prevent path traversal, reparse-point escapes, stale approval replay, and namespace races from redirecting an operation outside the admitted workspace. It must enforce byte limits and return structured errors without leaking file contents in logs.

## 2. Threat model

Assume the model, UI, Python process, proposal payload, and relative path are untrusted. An attacker may submit malformed paths and may cause ordinary files/directories inside the workspace to be renamed or replaced while an operation is in progress.

A process running as the **same Windows user** can often exercise the same filesystem permissions as BabyMind. Handle-relative opens reduce namespace substitution risks, but do not by themselves isolate file contents from a malicious same-user process. The first release must explicitly state whether it protects only against accidental/concurrent workspace changes or also against a hostile same-user process.

If hostile same-user interference is in scope, run the broker in a separate restricted security context with a dedicated workspace ACL boundary (for example, a separately provisioned service identity or suitably constrained AppContainer design). Do not claim protection from a same-user attacker until that boundary is implemented and tested. A normal child process under the same token is not a security boundary.

## 3. Architecture

Use a small native C++ library/broker with a narrow, versioned C ABI. Python calls it through a thin binding layer; Python must not perform the protected filesystem operations itself.

Suggested components:

1. **Python policy/API layer** — validates request shape, approval state, user-facing limits, and audit metadata. It never resolves or opens a workspace path for an approved operation.
2. **Native broker** — admits the workspace root, holds directory/file handles, resolves each child relative to a pinned parent handle, rejects reparse points, checks object types and identities, and performs bounded I/O.
3. **Approval record** — binds the action, canonical relative components, admitted workspace identity, target identity where applicable, content hash where applicable, size limit, and expiry to a cryptographic digest. Approval is single-use and action-specific.
4. **OS isolation boundary** — required if protection against hostile same-user processes is claimed.

The native API should expose typed operations, not a generic "open arbitrary path" function. Example conceptual calls:

- `bm_workspace_open_root(configured_path) -> root_handle, root_identity`
- `bm_workspace_list_directory(root_handle, relative_components, limits)`
- `bm_workspace_read_text(root_handle, relative_components, max_bytes)`
- `bm_workspace_create_new_text(root_handle, parent_components, leaf_name, bytes, max_bytes)`

Opaque handles must not be forgeable from Python integers or reused after close. Validate ABI version, buffer lengths, component counts, and all integer conversions.

## 4. Windows handle and path rules

### Root admission

- Accept a user-selected absolute directory only during explicit setup.
- Open and retain a directory handle; do not rely on a string path as the ongoing authority.
- Inspect the opened object using handle-based metadata (including file attributes, reparse tag, volume identity, and file ID).
- Reject a root that is itself a reparse point. Define and test the policy for reparse points in every ancestor of the configured root; do not assume checking only the final component is sufficient.
- Record volume serial/identity and file ID for the admitted root. Revalidate the held handle before each operation.
- Treat unsupported filesystems and remote/network paths as unsupported in the initial version unless separately reviewed.

### Child resolution

- Resolve one path component at a time relative to an already-open directory handle.
- Use a reviewed native Windows handle-relative open strategy. If using `NtCreateFile` with `OBJECT_ATTRIBUTES.RootDirectory`, isolate it behind one small implementation, document the exact supported Windows versions, and review the native declarations and status handling. Do not treat undocumented or version-sensitive flags as a universal guarantee.
- Open objects in a way that permits inspection of the reparse point itself; reject any reparse point rather than following it.
- Verify the opened handle's type and identity after opening. Never perform a separate path check and then reopen by path for the actual operation.
- Keep parent handles alive for the complete operation. Do not concatenate a previously validated absolute path and pass it to a later Win32 file API.
- Reject absolute paths, drive prefixes, UNC paths, device paths, alternate data stream syntax, empty components, dot/dot-dot components, trailing-dot/space aliases, reserved device names, and unexpected separators. Normalize input once under a documented Windows filename policy.

### Operation-specific rules

**Directory listing**
- Enumerate through the already-open directory handle.
- Return only bounded names and coarse entry types.
- Do not recurse in the first release.
- Never follow a reparse-point entry.

**Text read**
- Open the final component relative to its pinned parent.
- Reject directories, reparse points, unsupported types, and files larger than the configured maximum.
- Read from that same handle; enforce the byte limit while reading, not only from pre-read metadata.
- Decode UTF-8 strictly. Do not return partial file content after an error.

**New-file creation**
- Initially permit only creation in an existing admitted directory.
- Create the final component with an exclusive create disposition relative to the pinned parent; fail if any object already occupies the name.
- Never use a check-then-create sequence.
- Write only bounded UTF-8 bytes, flush the file, and remove incomplete output using the retained parent handle if the write fails.
- Do not replace, rename over, or truncate an existing file.

**Editing/deletion**
- Not in the first release. A hash comparison followed by path-based replacement is insufficient. Design a separate transaction protocol with pinned identities and atomicity analysis before considering these operations.

## 5. Approval protocol

An approval must bind at least:

- Protocol and ABI version.
- Workspace root volume identity and file ID.
- Exact operation and normalized relative component sequence.
- Target identity for reads of existing files.
- Expected content hash where the operation depends on a reviewed version.
- Exact content hash and byte count for create operations.
- Maximum bytes, creation time, expiry, and one-time nonce.

The server must atomically transition a proposal from pending to running exactly once. Re-check task state and proposal digest immediately before dispatch. The native broker must independently enforce its operation allowlist and limits; Python approval is not a substitute for native validation.

Do not put file contents in ordinary logs. Encrypt stored proposal payloads as the current application does, and avoid returning file contents until after approval.

## 6. Build and packaging

- Build with the repository's supported MSVC toolchain and Windows SDK in CI.
- Pin and document the compiler/SDK matrix.
- Export only the narrow C ABI; keep Windows types and NT structures out of Python-facing interfaces.
- Enable compiler warnings at a high level and treat relevant warnings as errors.
- Add static analysis and dependency scanning for the native component.
- Package the native binary with integrity verification; fail closed if it is missing, mismatched, or has an unsupported ABI version.
- Do not silently fall back to Python path-based filesystem operations.

## 7. Required adversarial test plan

Run on supported Windows versions and filesystems. Use deterministic synchronization barriers where possible rather than timing-only stress tests.

1. Root is a junction, symlink, mount point, or other reparse point.
2. An ancestor of the configured root is replaced or is a reparse point.
3. Intermediate directory is swapped for a junction between component resolution steps.
4. Final file is swapped for a reparse point immediately before open.
5. Directory is renamed/replaced during enumeration.
6. File is renamed/replaced while a read is pending; verify the read uses only the opened object and does not escape.
7. Two simultaneous create requests target the same name; exactly one succeeds and neither overwrites.
8. Parent directory is renamed/replaced during create and cleanup.
9. Malformed paths: drive-relative, UNC, device namespace, ADS, mixed separators, dot/dot-dot, trailing dot/space, reserved device names, Unicode normalization edge cases, and very long components.
10. File grows beyond the byte limit during read; the broker stops at the limit.
11. Broker handle reuse, invalid ABI values, oversized buffers, integer overflow, cancellation, and process interruption.
12. Stale, expired, altered, duplicated, or replayed approvals.
13. Unsupported filesystem and network share behavior.
14. If same-user attacker protection is claimed: attempt access from a second process under the same user and from the broker's restricted identity; verify ACL and token boundaries rather than assuming process separation is sufficient.

Every failure test must assert no access outside the admitted workspace and no unintended create, overwrite, truncate, rename, or delete side effect.

## 8. Enablement gates

Do not set `WORKSPACE_FILE_ACTIONS_ENABLED = True` until all of the following are true:

- Native broker implemented; no Python path-based fallback.
- Threat model and supported platform matrix documented.
- Independent security review completed.
- All adversarial tests pass on Windows CI.
- Approval replay and concurrency tests pass.
- Packaging and ABI failure modes fail closed.
- User-facing capability description matches the exact tested operations.

Project code execution remains a separate project. It requires an OS-level sandbox with explicit filesystem, network, process, and resource controls; this file design does not provide one.

## 9. Approval and process isolation protocol

The required broker-owned confirmation, one-use approval state, AppContainer isolation, restricted IPC, and test gates are specified in [NATIVE_WORKSPACE_BROKER_PROTOCOL.md](NATIVE_WORKSPACE_BROKER_PROTOCOL.md). That document is design only; none of those mechanisms is implemented or enabled.

## 10. Current status

A Windows-only C++ prototype now exists under native/windows_workspace/. It provides:
- An MSVC/CMake DLL target and native unit-test executable.
- Strict lexical validation for relative Windows path components.
- Fixed-local-NTFS root admission by walking from the volume root through pinned directory handles.
- Handle-relative child opens using NtCreateFile and OBJECT_ATTRIBUTES.RootDirectory.
- Handle-based reparse-point/type checks.
- Bounded reads (16 MiB cap) and exclusive new-file creation (1 MiB cap).
- Tests for ordinary traversal, create/read, duplicate creation, and directory-symlink escape rejection.
- CI build and CTest steps in both Windows workflows.

These are experimental primitives, not a reviewed security boundary. Directory listing is implemented as a bounded native primitive. Native approval-token binding, a broker process boundary, deterministic concurrent rename tests, a restricted broker identity, and independent security review are not implemented. A private ctypes adapter now defines the versioned C ABI boundary, but it is not invoked by the application or HTTP routes. No approved workspace action reaches the DLL. The existing Python helper remains unsafe to enable; the global feature flag remains false.
