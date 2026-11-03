# Windows workspace filesystem security

**Status: design gate only. Workspace file actions must remain disabled. BabyMind currently targets Windows 10/11 only.** This document records the Windows implementation requirements and unresolved guarantees. It is not evidence that a secure backend has been implemented.

## Threat model

The workspace root is selected by the user. Relative paths and directory entries may be attacker-controlled. A concurrent process may rename, replace, or create path components while BabyMind is operating. The backend must never escape the originally authorized workspace directory through traversal, symbolic links, junctions, mount points, or other reparse points.

A handle-relative API does not automatically provide a snapshot of directory names or protect a file's contents from a same-user process that can independently open and modify that file. The product must define whether same-user concurrent writers are in scope. If they are, a stronger OS-enforced isolation boundary is required; advisory locks and a second hash check are not sufficient.

## Windows implementation direction and unresolved contract

Windows needs directory handles and child opens relative to those handles, while refusing reparse points at every component. `NtCreateFile` documents a `RootDirectory` handle for relative names and `FILE_OPEN_REPARSE_POINT` behavior. `OBJ_DONT_REPARSE` is the relevant fail-on-reparse object attribute in the general `OBJECT_ATTRIBUTES` documentation; it is distinct from `FILE_OPEN_REPARSE_POINT`, which opens the reparse point itself rather than refusing traversal.

### Research evidence (November 3, 2026)

A Microsoft Q&A thread reports a successful test on Windows 11 build 26200, local NTFS, using a directory handle as `RootDirectory`, a single relative component, and `OBJ_DONT_REPARSE | OBJ_CASE_INSENSITIVE`. The test reports `STATUS_REPARSE_POINT_ENCOUNTERED` for a junction. This is useful experimental evidence and suggests a viable implementation direction.

However, the Q&A distinguishes that measured behavior from the published contract: the user-mode `NtCreateFile` page narrows its `Attributes` description to zero or `OBJ_CASE_INSENSITIVE`, while the general `OBJECT_ATTRIBUTES` page defines `OBJ_DONT_REPARSE`. The cited docs do not unambiguously resolve acceptance of this exact combination across supported Windows versions and filesystems.

The available research also does not establish namespace stability during concurrent rename, replacement, or reparse-point changes. Initial acquisition of the trusted root handle is a separate problem: a descendant open cannot retroactively prove that the absolute root path and its ancestors were admitted without following an untrusted reparse point.

Therefore, this is not enough to enable workspace operations. A Windows prototype must validate the tested combination on a declared Windows/filesystem matrix, securely establish the root handle, verify the opened object through its handle, and separately define/mitigate concurrent namespace changes. Do not claim race-free behavior from the flag alone.

References:
- https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile
- https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile
- https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes
- https://learn.microsoft.com/en-us/answers/questions/6052628/documented-user-mode-ntcreatefile-contract-for-fil
- https://learn.microsoft.com/en-us/answers/questions/6059091/is-ntcreatefile-with-rootdirectory-race-safe-again

## Required operations and invariants

Before any workspace action can be enabled, the Windows backend must provide and test:

1. Secure admission of the configured workspace root, including every ancestor component; reject roots that are reparse points or whose ancestry cannot be established safely.
2. Directory-relative resolution of each component from a pinned root/parent handle, with no path-based reopen after validation.
3. Type verification from the opened handle (directory vs regular file), not from a separate path lookup.
4. Bounded reads from the opened file handle, with size and file-type checks on that handle.
5. New-file creation that is exclusive and relative to a pinned parent directory handle.
6. Edits that have a defensible concurrency model. A hash check followed by a path-based replace is not sufficient. If the backend cannot guarantee that the reviewed object is the object being changed under the stated threat model, editing must remain unavailable.
7. Cleanup that uses the same trusted parent handle and cannot unlink a substituted path.
8. Explicit refusal on unsupported Windows versions, filesystems, API behavior, or fallback paths.

## Windows security test matrix

Run on supported Windows CI runners and repeat race tests many times:

- Symlink, junction, and other reparse points at the root, each intermediate component, and the final component.
- Replace an intermediate directory with a junction/reparse point during resolution.
- Rename or replace the final file between proposal and approval.
- Replace a directory entry during enumeration and file creation.
- Attempt `..`, absolute paths, alternate separators, drive paths, UNC paths, device paths, and case/Unicode edge cases.
- Concurrent same-user modification of the reviewed file; verify the chosen threat model and behavior explicitly.
- Verify all failures leave no outside-workspace reads, writes, or cleanup deletions.

## Enablement rule

Keep `WORKSPACE_FILE_ACTIONS_ENABLED = False` and keep the API/UI disabled until the Windows implementation has code review, a documented supported Windows/filesystem matrix, adversarial race tests, and passing Windows CI. Project test execution is a separate feature and still requires a real Windows OS-level sandbox for process, network, filesystem, and resource isolation.
