"""Private ctypes binding for the experimental native Windows workspace DLL.

Importing this module never loads a DLL or enables workspace access. The
application feature flag remains false until a separately reviewed broker
process and native approval protocol are complete.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path


_EXPECTED_ABI = 1
_MAX_LIST_ENTRIES = 200
_MAX_READ_BYTES = 16 * 1024 * 1024
_MAX_CREATE_BYTES = 1024 * 1024


class _DirectoryEntry(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar * 256), ("type", ctypes.c_uint32)]


class NativeWorkspaceError(RuntimeError):
    """A native workspace operation failed closed."""


class _NativeWorkspaceRoot:
    """Owns one opaque native root handle; deliberately not wired into HTTP routes."""

    def __init__(self, library, handle):
        self._library = library
        self._handle = ctypes.c_void_p(handle)

    def close(self) -> None:
        if self._handle and self._handle.value:
            self._library.bm_ws_close_workspace_root(self._handle)
            self._handle = ctypes.c_void_p()

    def __enter__(self):
        if not self._handle or not self._handle.value:
            raise NativeWorkspaceError("Workspace root handle is closed.")
        return self

    def __exit__(self, *_exc):
        self.close()

    def _require_open(self):
        if not self._handle or not self._handle.value:
            raise NativeWorkspaceError("Workspace root handle is closed.")

    def list_directory(self, relative_path: str = "", *, capacity: int = 200) -> dict:
        self._require_open()
        if not isinstance(relative_path, str) or "\x00" in relative_path:
            raise ValueError("Relative workspace path must be a NUL-free string.")
        if not isinstance(capacity, int) or isinstance(capacity, bool) or not 1 <= capacity <= _MAX_LIST_ENTRIES:
            raise ValueError(f"Directory listing capacity must be between 1 and {_MAX_LIST_ENTRIES}.")
        entries = (_DirectoryEntry * capacity)()
        written = ctypes.c_size_t()
        truncated = ctypes.c_int()
        status = self._library.bm_ws_list_directory(
            self._handle, relative_path, entries, capacity,
            ctypes.byref(written), ctypes.byref(truncated),
        )
        _check_status(status, "list directory")
        return {
            "entries": [
                {"name": entries[index].name, "type": ("file", "directory", "reparse_point")[entries[index].type]}
                for index in range(written.value)
                if entries[index].type in (0, 1, 2)
            ],
            "truncated": bool(truncated.value),
        }

    def read_text(self, relative_path: str, *, max_bytes: int = 32 * 1024) -> str:
        self._require_open()
        if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
            raise ValueError("A NUL-free relative file path is required.")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= _MAX_READ_BYTES:
            raise ValueError(f"Read limit must be between 1 and {_MAX_READ_BYTES} bytes.")
        output = (ctypes.c_uint8 * (max_bytes + 1))()
        received = ctypes.c_size_t()
        status = self._library.bm_ws_read_text(
            self._handle, relative_path, max_bytes, output, max_bytes + 1,
            ctypes.byref(received),
        )
        _check_status(status, "read text")
        try:
            raw = bytes(output[:received.value])
            if b"\x00" in raw:
                raise NativeWorkspaceError("The selected file is not plain UTF-8 text.")
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise NativeWorkspaceError("The selected file is not valid UTF-8.") from error

    def create_new_text(self, relative_path: str, content: str, *, max_bytes: int = 32 * 1024) -> dict:
        self._require_open()
        if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
            raise ValueError("A NUL-free relative file path is required.")
        if not isinstance(content, str) or "\x00" in content:
            raise ValueError("New file content must be NUL-free text.")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= _MAX_CREATE_BYTES:
            raise ValueError(f"Create limit must be between 1 and {_MAX_CREATE_BYTES} bytes.")
        try:
            encoded = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("New file content must be valid UTF-8.") from error
        if len(encoded) > max_bytes:
            raise ValueError("New file content exceeds the requested byte limit.")
        data = (ctypes.c_uint8 * len(encoded)).from_buffer_copy(encoded) if encoded else None
        status = self._library.bm_ws_create_new_text(
            self._handle, relative_path, data, len(encoded), max_bytes,
        )
        _check_status(status, "create new text file")
        return {"created": True, "bytes": len(encoded)}


def _check_status(status: int, operation: str) -> None:
    if status == 0:
        return
    messages = {
        1: "Invalid native API argument.",
        2: "Invalid relative workspace path.",
        4: "Native filesystem operation failed.",
        5: "Reparse points are not allowed.",
        6: "The selected object is not a directory.",
        7: "The requested operation exceeded its byte limit.",
        8: "The native output buffer is too small.",
    }
    raise NativeWorkspaceError(f"Could not {operation}: {messages.get(status, f'native status {status}')}") 


def load_native_workspace_library(dll_path: str | os.PathLike | None = None):
    """Load an explicitly configured DLL; never searches PATH or auto-enables access."""
    if os.name != "nt":
        raise OSError("The native workspace broker is available only on Windows.")
    configured = dll_path if dll_path is not None else os.getenv("BABYMIND_WORKSPACE_BROKER_DLL", "")
    if not configured:
        raise NativeWorkspaceError("Set BABYMIND_WORKSPACE_BROKER_DLL to the packaged native broker DLL.")
    path = Path(configured)
    if not path.is_absolute():
        raise NativeWorkspaceError("The native broker DLL path must be absolute.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise NativeWorkspaceError("The configured native broker DLL does not exist.") from error
    if not resolved.is_file():
        raise NativeWorkspaceError("The configured native broker path is not a file.")

    library = ctypes.WinDLL(str(resolved))
    library.bm_ws_abi_version.argtypes = []
    library.bm_ws_abi_version.restype = ctypes.c_uint32
    if library.bm_ws_abi_version() != _EXPECTED_ABI:
        raise NativeWorkspaceError("The native workspace broker ABI version is unsupported.")

    library.bm_ws_open_workspace_root.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    library.bm_ws_open_workspace_root.restype = ctypes.c_int
    library.bm_ws_close_workspace_root.argtypes = [ctypes.c_void_p]
    library.bm_ws_close_workspace_root.restype = None
    library.bm_ws_list_directory.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(_DirectoryEntry),
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int),
    ]
    library.bm_ws_list_directory.restype = ctypes.c_int
    library.bm_ws_read_text.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ]
    library.bm_ws_read_text.restype = ctypes.c_int
    library.bm_ws_create_new_text.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t, ctypes.c_size_t,
    ]
    library.bm_ws_create_new_text.restype = ctypes.c_int

    class _LoadedNativeWorkspace:
        def open_root(self, absolute_path: str) -> _NativeWorkspaceRoot:
            if not isinstance(absolute_path, str) or not absolute_path or "\x00" in absolute_path:
                raise ValueError("An absolute workspace directory path is required.")
            if len(absolute_path) > 500:
                raise ValueError("Workspace root path is too long.")
            handle = ctypes.c_void_p()
            status = library.bm_ws_open_workspace_root(absolute_path, ctypes.byref(handle))
            _check_status(status, "open workspace root")
            if not handle.value:
                raise NativeWorkspaceError("Native broker returned an empty workspace handle.")
            return _NativeWorkspaceRoot(library, handle.value)

    return _LoadedNativeWorkspace()
