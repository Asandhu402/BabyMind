# Native Windows workspace broker prototype

This is the first MSVC-buildable stage of BabyMind's native workspace work.

## Current capability

- Strict lexical validation for relative Windows workspace path components.
- Windows-only CMake target and native unit-test executable.
- Reserved API entry points for future workspace operations.

## Deliberate limitations

**No filesystem operation is implemented.** Root admission, handle-relative child opening, reparse-point rejection, bounded reads, and exclusive file creation all return `BM_WS_NOT_IMPLEMENTED`.

Lexical validation is not a filesystem security boundary. It does not prove that a path is inside a workspace and must never be used as a reason to call Python `open()`, `Path.resolve()`, or another path-based API. The Python feature gate remains disabled.

The next implementation stage must establish a pinned root directory handle and resolve every child relative to pinned parent handles using a reviewed Windows-native strategy. It must then add adversarial junction/reparse-point and concurrent rename tests before any filesystem API is enabled.

Protection against a hostile process running as the same Windows user requires a separate OS security boundary; a normal child process is not sufficient.
