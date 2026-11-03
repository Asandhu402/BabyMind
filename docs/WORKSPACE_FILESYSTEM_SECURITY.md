# Workspace filesystem security backend

**Status: design gate only. Workspace file actions must remain disabled.** This document records implementation requirements and unresolved platform guarantees. It is not evidence that a secure backend has been implemented.

## Threat model

The workspace root is selected by the user. Relative paths and directory entries may be attacker-controlled. A concurrent process may rename, replace, or create path components while BabyMind is operating. The backend must never escape the originally authorized workspace directory through path traversal, symbolic links, Windows junctions, mount points, or reparse points.

A handle-relative API reduces path-resolution races, but it does not automatically provide a snapshot of directory names or protect a file's contents from a same-user process that can independently open and modify that file. The product must define whether same-user concurrent writers are in scope. If they are, a stronger OS-enforced isolation boundary is required; advisory locks and a second hash check are not sufficient.

## Linux direction

Use Linux openat2(2) relative to a pinned workspace-root directory descriptor, with at least:

- RESOLVE_BENEATH
- RESOLVE_NO_SYMLINKS
- RESOLVE_NO_MAGICLINKS
- Consider RESOLVE_NO_XDEV if crossing mount points is not allowed by product policy.
- Fail closed if openat2 is unavailable or returns an unsupported/unsafe result. Do not silently fall back to ordinary path-based open() or Path.resolve().

The kernel interface is available since Linux 5.6. The system call is invoked through syscall(2) on glibc systems without a libc wrapper. Keep the workspace root descriptor open and perform all descendant operations relative to trusted directory descriptors. Use descriptor-relative operations for enumeration, create, and rename; do not reconstruct absolute paths for later filesystem calls.

Reference: https://man7.org/linux/man-pages/man2/openat2.2.html

## Windows direction and unresolved contract

Windows needs directory handles and child opens relative to those handles, while refusing reparse points at every component. NtCreateFile documents a RootDirectory handle for relative names and documents FILE_OPEN_REPARSE_POINT behavior. However, the published user-mode contract for the exact combination of relative opens, no-reparse enforcement, ancestor admission, and concurrent namespace changes is not sufficiently clear to claim the required security guarantee.

A recent Microsoft Q&A response explicitly notes that the cited references do not settle the exact support contract or guarantee behavior during concurrent renames/reparse-point changes. This is not a suitable basis for enabling a security-sensitive implementation.

References:
- https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile
- https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile
- https://learn.microsoft.com/en-us/answers/questions/6052628/documented-user-mode-ntcreatefile-contract-for-fil

Do not treat a successful test on one Windows build as proof of a supported contract. Obtain a documented, supported approach or an independently reviewed native implementation with an explicit Windows/filesystem support matrix. Until then, Windows workspace actions remain disabled.

## Required operations and invariants

Before any action can be enabled, the backend must provide and test:

1. Secure admission of the configured workspace root, including every ancestor component; reject roots that are reparse points/symlinks or whose ancestry cannot be established safely.
2. Directory-relative resolution of each component from a pinned root/parent handle, with no path-based reopen after validation.
3. Type verification from the opened handle (directory vs regular file), not from a separate path lookup.
4. Bounded reads from the opened file handle, with size and file-type checks on that handle.
5. New-file creation that is exclusive and relative to a pinned parent directory handle.
6. Edits that have a defensible concurrency model. A hash check followed by a path-based replace is not sufficient. If the backend cannot guarantee that the reviewed object is the object being changed under the stated threat model, editing must remain unavailable.
7. Cleanup that uses the same trusted parent handle and cannot unlink a substituted path.
8. Explicit refusal on unsupported filesystems, API versions, flags, or fallback paths.

## Security test matrix

Run on supported Windows and Linux CI runners, and repeat race tests many times:

- Symlink/junction/reparse point at the root, each intermediate component, and the final component.
- Replace an intermediate directory with a symlink/junction during resolution.
- Rename or replace the final file between proposal and approval.
- Replace a directory entry during enumeration and file creation.
- Attempt .., absolute paths, alternate separators, drive paths, UNC paths, device paths, and case/Unicode edge cases on Windows.
- Mount-point crossing and Linux magic-link attempts.
- Concurrent same-user modification of the reviewed file; verify the chosen threat model and behavior explicitly.
- Verify all failures leave no outside-workspace reads, writes, or cleanup deletions.

## Enablement rule

Keep WORKSPACE_FILE_ACTIONS_ENABLED = False and keep the API/UI disabled until both platform implementations have code review, a documented supported-platform matrix, adversarial race tests, and passing CI. Project test execution is a separate feature and still requires an OS-level sandbox for process, network, filesystem, and resource isolation.