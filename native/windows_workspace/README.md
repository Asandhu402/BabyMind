# Native Windows workspace broker prototype

This is an experimental MSVC/CMake native component. It is **not connected to BabyMind's Python API** and does not enable workspace access in the application.

## Implemented in this prototype

- Strict lexical validation for relative Windows path components.
- Root admission for a fixed local NTFS drive, walking each path component relative to the previous directory handle.
- Handle-relative intermediate and final opens using NtCreateFile with OBJECT_ATTRIBUTES.RootDirectory.
- Reparse-point inspection on opened handles; reparse components are rejected.
- Bounded reads from the opened file handle (maximum 16 MiB).
- Exclusive new-file creation (maximum 1 MiB); existing names are not overwritten.
- Native tests for traversal, create/read behavior, duplicate creation, buffer limits, and directory and file symlink escape rejection, and read-size enforcement.
- Windows CI build and CTest steps.

## Security limits — do not enable

This is an initial implementation, not a completed security review. It does not yet include directory enumeration, approval-token binding, Python FFI, a broker process boundary, deterministic concurrent rename stress tests, a hostile same-user isolation boundary, or independent review.

The read and create functions are native primitives only. They are not exposed to the UI or Python. Keep WORKSPACE_FILE_ACTIONS_ENABLED = False and project test execution disabled. Never fall back to Python open(), Path.resolve(), or path-based file operations.

A process running as the same Windows user may have equivalent filesystem permissions. Handle-relative opens do not by themselves protect against a hostile same-user process. A separate restricted identity/ACL boundary is required before claiming that threat is covered.

The first release remains limited to listing, bounded text reads, and exclusive creation. Editing, deletion, recursive search, and command execution remain out of scope.
