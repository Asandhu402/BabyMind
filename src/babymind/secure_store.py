"""Authenticated encryption for BabyMind's local text fields.

The data-encryption key is stored as a separate, owner-only file in the
Linux user's BabyMind data directory. This protects database contents at
rest; it does not protect data while BabyMind is running or against malware
running as the same user.
"""
from __future__ import annotations

import base64
import os
import secrets
import stat
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "bmenc:v1:"


class SecureTextStore:
    """Encrypt and decrypt text with an authenticated per-installation key."""

    def __init__(self, key_path: str | Path) -> None:
        self.key_path = Path(key_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.key_path.parent, 0o700)
        except OSError:
            pass
        self._key = self._load_or_create_key()
        self._cipher = AESGCM(self._key)

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            info = self.key_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError("BabyMind's encryption key must be a regular file owned by the current user.")
            if info.st_mode & 0o077:
                raise RuntimeError("BabyMind's encryption key permissions are too broad; set them to 0600.")
            stored = self.key_path.read_bytes()
            if len(stored) != 32:
                raise RuntimeError("BabyMind's local encryption key is invalid or uses an unsupported legacy format.")
            return stored

        key = secrets.token_bytes(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            return self._load_or_create_key()
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            self.key_path.unlink(missing_ok=True)
            raise
        os.chmod(self.key_path, 0o600)
        return key

    def encrypt(self, value: str) -> str:
        if value.startswith(_PREFIX):
            return value
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), b"BabyMind:text:v1")
        return _PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value.startswith(_PREFIX):
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
