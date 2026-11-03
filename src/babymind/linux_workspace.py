"""Linux-only, fail-closed workspace primitives built on openat2(2).

This module is intentionally not wired into approval.py and does not enable
workspace actions. It provides a narrow primitive layer for independent tests.
Only x86_64 and aarch64 Linux are supported; other platforms fail closed.
"""
from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat

# openat2 is syscall 437 on x86_64 and 56 on arm64/aarch64.
_MACHINE_SYSCALL = {"x86_64": 437, "amd64": 437, "aarch64": 56, "arm64": 56}
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_REQUIRED_RESOLVE = (
    _RESOLVE_BENEATH | _RESOLVE_NO_SYMLINKS | _RESOLVE_NO_MAGICLINKS
)
_AT_FDCWD = -100


class WorkspaceSecurityError(ValueError):
    """A workspace path could not be resolved under the required policy."""


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


def _syscall_number() -> int:
    if not sys_is_linux():
        raise WorkspaceSecurityError("The openat2 backend is Linux-only.")
    try:
        return _MACHINE_SYSCALL[platform.machine().lower()]
    except KeyError as error:
        raise WorkspaceSecurityError(
            "openat2 syscall number is not validated for this CPU architecture."
        ) from error


def sys_is_linux() -> bool:
    return os.name == "posix" and platform.system() == "Linux"


def _openat2(dir_fd: int, path: str, flags: int, mode: int = 0) -> int:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise WorkspaceSecurityError("Invalid empty or NUL-containing path.")
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    how = _OpenHow(flags, mode, _REQUIRED_RESOLVE)
    result = syscall(
        ctypes.c_long(_syscall_number()),
        ctypes.c_int(dir_fd),
        ctypes.c_char_p(os.fsencode(path)),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        code = ctypes.get_errno()
        if code in (errno.ENOSYS, errno.EINVAL, errno.E2BIG):
            raise WorkspaceSecurityError(
                "This kernel does not support the required openat2 security flags."
            )
        raise OSError(code, os.strerror(code), path)
    return int(result)


def _parts(relative_path: str) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 500:
        raise WorkspaceSecurityError("Workspace path is invalid or too long.")
    if relative_path.startswith("/") or "\x00" in relative_path:
        raise WorkspaceSecurityError("Workspace paths must be relative.")
    parts = tuple(relative_path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise WorkspaceSecurityError("Empty, dot, and parent path components are not allowed.")
    if any(part.startswith(".") for part in parts):
        raise WorkspaceSecurityError("Hidden workspace paths are not supported.")
    return parts


class LinuxWorkspace:
    """Pinned workspace root and handle-relative operations.

    The caller owns this object and must close it. No path-based reopen is used
    for descendants. File edits are deliberately not implemented here.
    """

    def __init__(self, root_path: str):
        if not sys_is_linux():
            raise WorkspaceSecurityError("The openat2 backend is Linux-only.")
        if not isinstance(root_path, str) or not os.path.isabs(root_path):
            raise WorkspaceSecurityError("Workspace root must be an absolute path.")
        raw_parts = root_path.split("/")
        if any(part == ".." for part in raw_parts):
            raise WorkspaceSecurityError("Workspace root cannot contain parent traversal.")
        # Admit every root ancestor one component at a time from the pinned / fd.
        current = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for component in (part for part in raw_parts if part not in ("", ".")):
                next_fd = _openat2(
                    current,
                    component,
                    os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC,
                )
                os.close(current)
                current = next_fd
            self._root_fd = current
            current = -1
        except Exception:
            raise
        finally:
            if current >= 0:
                os.close(current)

    def close(self) -> None:
        fd = getattr(self, "_root_fd", -1)
        if fd >= 0:
            os.close(fd)
            self._root_fd = -1

    def __enter__(self) -> "LinuxWorkspace":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _directory_fd(self, parts: tuple[str, ...]) -> int:
        current = os.dup(self._root_fd)
        try:
            for component in parts:
                next_fd = _openat2(
                    current,
                    component,
                    os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC,
                )
                os.close(current)
                current = next_fd
            return current
        except Exception:
            os.close(current)
            raise

    def list_directory(self, relative_path: str = ".") -> list[dict]:
        if relative_path == ".":
            parts: tuple[str, ...] = ()
        else:
            parts = _parts(relative_path)
        directory_fd = self._directory_fd(parts)
        try:
            entries = []
            # Bound enumeration work; the UI can request another view later.
            with os.scandir(directory_fd) as iterator:
                names = []
                for entry in iterator:
                    if entry.name.startswith("."):
                        continue
                    names.append(entry.name)
                    if len(names) >= 201:
                        break
            for name in sorted(names[:200], key=str.casefold):
                try:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    # A concurrently removed name is simply not reported.
                    continue
                if stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                elif stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                elif stat.S_ISREG(info.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries.append({"name": name[:255], "type": kind})
            return entries
        finally:
            os.close(directory_fd)

    def read_file(self, relative_path: str, max_bytes: int = 32768) -> bytes:
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
            raise WorkspaceSecurityError("Read limit must be a non-negative integer.")
        parts = _parts(relative_path)
        parent_fd = self._directory_fd(parts[:-1])
        try:
            fd = _openat2(
                parent_fd,
                parts[-1],
                os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK,
            )
        finally:
            os.close(parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceSecurityError("Only regular files can be read.")
            if info.st_size > max_bytes:
                raise WorkspaceSecurityError("File exceeds the configured read limit.")
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 8192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > max_bytes:
                raise WorkspaceSecurityError("File exceeds the configured read limit.")
            return data
        finally:
            os.close(fd)

    def create_file(self, relative_path: str, content: bytes) -> int:
        parts = _parts(relative_path)
        if not isinstance(content, bytes):
            raise WorkspaceSecurityError("File content must be bytes.")
        parent_fd = self._directory_fd(parts[:-1])
        try:
            fd = _openat2(
                parent_fd,
                parts[-1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
        finally:
            os.close(parent_fd)
        try:
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            return len(content)
        except Exception:
            os.close(fd)
            # Do not unlink by path: cleanup must not risk deleting a substitute.
            raise
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
