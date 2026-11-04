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

## Fail-closed broker executable and IPC isolation smoke test

`babymind_workspace_broker.exe` is a separate process host. It refuses to run unless its process token is a capability-free Windows AppContainer token (no declared network capabilities), reads one bounded frame from standard input with a five-second deadline, validates it with the strict parser, and then denies the request. The broker statically compiles its native path-validation implementation so the AppContainer process does not need to load a workspace DLL from the developer's directory.

The Windows smoke launcher now:
- Creates or reuses a dedicated AppContainer profile and launches the broker suspended with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`.
- Uses `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` to inherit only the request pipe and two NUL output handles.
- Sends exactly one bounded root-list request through the private anonymous pipe, then closes the parent writer to signal EOF.
- Runs a second negative smoke case with a deliberate trailing byte and requires the broker to reject it as malformed/chained IPC.
- Places the child in a kill-on-close Job Object with a one-process and 256 MiB process-memory limit.
- Requires the broker to parse the valid frame and return the deliberate “operation not implemented” denial exit code.

This is an end-to-end isolation/IPC smoke test, not a production launcher or authorization path. It does not grant workspace ACLs, show a native approval dialog, or dispatch file operations.

## IPC frame parser

`broker_protocol.cpp` implements a bounded, versioned little-endian parser for the proposed operation codes. It checks exact frame lengths, operation-specific payload rules, UTF-16 validity, relative paths and the 32 KiB create payload limit. Tests cover truncation, trailing bytes, unknown operations/versions, traversal and invalid payload combinations. Parsing does not authorize filesystem access or user approval.

## Approval and process isolation

See [NATIVE_WORKSPACE_BROKER_PROTOCOL.md](../../docs/NATIVE_WORKSPACE_BROKER_PROTOCOL.md) for the required broker-owned confirmation, one-use approval, AppContainer isolation, IPC framing, and enablement gates. The process/IPC smoke launcher covers only a subset of the design contract.

## Security limits — do not enable

This is an initial implementation, not a completed security review. The ctypes adapter is experimental and is not an approval dispatcher. It does not yet include native approval-token binding, workspace ACL provisioning and revocation, deterministic concurrent rename stress tests, a hostile same-user isolation boundary, production package/signature verification, or independent review.

The read and create functions are native primitives only. The private ctypes adapter can load the DLL for controlled development tests, but no application route invokes it. Keep `WORKSPACE_FILE_ACTIONS_ENABLED = False` and project test execution disabled. Never fall back to Python open(), Path.resolve(), or path-based file operations.

A process running as the same Windows user may have equivalent filesystem permissions. Handle-relative opens and a capability-free AppContainer token do not by themselves grant or confine access to a selected workspace. A separate, narrowly scoped ACL grant/revoke flow and independent review are required before claiming that threat is covered.

The first release remains limited to non-recursive directory listing, bounded text reads, and exclusive creation. Editing, deletion, recursive search, and command execution remain out of scope.
