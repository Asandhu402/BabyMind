"""Authenticated encryption for BabyMind's local text fields.

On Windows, the random AES-256 key is protected with the current user's DPAPI.
On other platforms, the key is stored in a user-only file (0600 where supported).
This protects database contents at rest; it does not protect data while BabyMind
is running or against malware running as the same user.
"""
from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "bmenc:v1:"
_MAGIC = b"BMK1"


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Protect/unprotect bytes using Windows Data Protection API."""
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is unavailable on this platform.")

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_ptr = ctypes.POINTER(DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [
        blob_ptr, wintypes.LPCWSTR, blob_ptr, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, blob_ptr,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_ptr, ctypes.POINTER(wintypes.LPWSTR), blob_ptr, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_ptr,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source_buffer = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "BabyMind local encryption key", None, None, None, 0,
            ctypes.byref(target),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class SecureTextStore:
    """Encrypt and decrypt text with an authenticated per-installation key."""

    def __init__(self, key_path: str | Path) -> None:
        self.key_path = Path(key_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key = self._load_or_create_key()
        self._cipher = AESGCM(self._key)

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            stored = self.key_path.read_bytes()
            if stored.startswith(_MAGIC):
                if sys.platform != "win32":
                    raise RuntimeError(
                        "This BabyMind encryption key was protected by Windows DPAPI "
                        "and cannot be opened on this platform."
                    )
                key = _dpapi(stored[len(_MAGIC):], protect=False)
            else:
                key = stored
            if len(key) != 32:
                raise RuntimeError("BabyMind's local encryption key is invalid.")
            return key

        key = secrets.token_bytes(32)
        stored = _MAGIC + _dpapi(key, protect=True) if sys.platform == "win32" else key
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            return self._load_or_create_key()
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(stored)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            self.key_path.unlink(missing_ok=True)
            raise
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def encrypt(self, value: str) -> str:
        if value.startswith(_PREFIX):
            return value
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), b"BabyMind:text:v1")
        return _PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value.startswith(_PREFIX):
            # Existing databases are migrated in place and remain readable if
            # an interrupted migration left an older plaintext row behind.
            return value
        try:
            payload = base64.urlsafe_b64decode(value[len(_PREFIX):].encode("ascii"))
            nonce, ciphertext = payload[:12], payload[12:]
            return self._cipher.decrypt(nonce, ciphertext, b"BabyMind:text:v1").decode("utf-8")
        except Exception as error:
            raise RuntimeError(
                "BabyMind could not decrypt local data. The encryption key may be "
                "missing, replaced, or inaccessible; do not delete the key file."
            ) from error
