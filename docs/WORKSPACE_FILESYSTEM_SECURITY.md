# Linux workspace filesystem security

**Status: design gate only. Workspace file actions must remain disabled.** This document defines requirements for a future Linux-native workspace broker; it is not evidence that a secure backend has been implemented.

## Threat model

The workspace root is selected by the user. Relative paths and directory entries may be attacker-controlled. A concurrent process may rename, replace, or create path components while BabyMind is operating. The backend must never escape the authorized workspace through traversal, symbolic links, bind mounts, mount points, or path replacement races.

A descriptor-relative API does not automatically isolate file contents from a malicious process running as the same user. The product must define whether same-user concurrent writers are in scope. Advisory locks and a second path check are not sufficient isolation.

## Required architecture

Use a small Linux-native broker with a narrow typed interface. Python must not perform privileged path resolution or file I/O for brokered operations.

- Admit the selected root by opening it as a directory and retaining the directory file descriptor.
- Resolve every child relative to a pinned parent descriptor.
- Use `openat2` with restrictive resolution flags where available (including `RESOLVE_BENEATH`, `RESOLVE_NO_SYMLINKS`, and an explicitly chosen mount-crossing policy).
- Provide a reviewed descriptor-relative fallback only when its guarantees are equivalent for the supported kernel; otherwise fail closed.
- Reject symlinks, magic links, unexpected mount transitions, non-regular files, and invalid path components.
- Use `O_NOFOLLOW`, `O_CLOEXEC`, and exclusive creation where appropriate.
- Verify opened object type and identity through the file descriptor, not by reopening a path.
- Keep parent descriptors alive for the entire operation.
- Bound directory entries, file sizes, content sizes, and operation time.
- Bind one-use approvals to the exact operation, root identity, relative path, content digest, size limit, and expiry.
- Record every decision and operation in the audit trail without logging file contents or secrets.

## Initial operation scope

The first reviewed release may support only:
1. Non-recursive listing of one selected directory.
2. Bounded UTF-8 text reads.
3. Exclusive creation of a new text file.

Editing, deletion, recursive search, arbitrary command execution, and project test execution require separate threat reviews and must remain disabled until approved.

## OS isolation

A broker process running under the same unrestricted user identity is not, by itself, a security boundary against hostile same-user software. If the threat model includes that attacker, use an independently provisioned restricted identity and narrowly scoped filesystem permissions, or another reviewed Linux isolation design. Never call a path-checking subprocess a sandbox.

## Verification requirements

- Test traversal, absolute paths, empty components, dot components, symlinks, magic links, bind mounts, mount crossings, hard links, and path replacement races.
- Test concurrent rename and replacement attempts during root admission and every operation.
- Test crash, cancellation, timeout, descriptor cleanup, and partial-write behavior.
- Test the declared kernel and distribution matrix.
- Verify the broker fails closed when required kernel features or isolation controls are unavailable.
- Obtain an independent security review before enabling any workspace API or UI operation.

Until all required evidence exists, workspace operations stay disabled.
