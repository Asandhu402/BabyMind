# Native Windows workspace broker prototype

This is an experimental MSVC/CMake native component with a versioned C ABI and a private ctypes adapter. The adapter is not connected to HTTP routes and does not enable workspace access in the application.

## Implemented in this prototype

- Strict lexical validation for relative Windows path components.
- Root admission for a fixed local NTFS drive, walking each path component relative to the previous directory handle.
- Handle-relative intermediate and final opens using NtCreateFile with OBJECT_ATTRIBUTES.RootDirectory.
- Reparse-point inspection on opened handles; reparse components are rejected.
- Handle-based, non-recursive directory listing (maximum 200 entries; reparse points are identified but never followed).
- Bounded reads from the opened file handle (maximum 16 MiB).
- Exclusive new-file creation (maximum 1 MiB); existing names are not overwritten.
- Native tests for traversal, create/read behavior, duplicate creation, buffer limits, and directory and file symlink escape rejection, read-size enforcement, and concurrent exclusive-create behavior.
- Windows CI build and CTest steps.

## Approval and process isolation

See [NATIVE_WORKSPACE_BROKER_PROTOCOL.md](../../docs/NATIVE_WORKSPACE_BROKER_PROTOCOL.md) for the required broker-owned confirmation, one-use approval, AppContainer isolation, IPC framing, and enablement gates. This is a design contract, not implemented functionality.

## Security limits — do not enable

This is an initial implementation, not a completed security review. The ctypes adapter is experimental and is not an approval dispatcher. It does not yet include native approval-token binding, a broker process boundary, deterministic concurrent rename stress tests, a hostile same-user isolation boundary, or independent review.

The read and create functions are native primitives only. The private ctypes adapter can load the DLL for controlled development tests, but no application route invokes it. Keep WORKSPACE_FILE_ACTIONS_ENABLED = False and project test execution disabled. Never fall back to Python open(), Path.resolve(), or path-based file operations.

A process running as the same Windows user may have equivalent filesystem permissions. Handle-relative opens do not by themselves protect against a hostile same-user process. A separate restricted identity/ACL boundary is required before claiming that threat is covered.

The first release remains limited to non-recursive directory listing, bounded text reads, and exclusive creation. Editing, deletion, recursive search, and command execution remain out of scope.
