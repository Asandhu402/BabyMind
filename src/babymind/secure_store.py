"""Authenticated encryption for BabyMind's local text fields.

On Linux, the random AES-256 key is stored in a user-only file (mode 0600).
This protects database contents at rest; it does not protect data while BabyMind
is running or against malware running as the same user.
"""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "bmenc:v1:"
_MAGIC = b"BMK1"




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
            # Do not overwrite or silently reinterpret a legacy platform-bound key.
            if stored.startswith(_MAGIC) and len(stored) != 32:
                raise RuntimeError(
                    "This legacy platform-protected BabyMind key cannot be opened on Linux. "
                    "Keep the original key and databases; do not delete or replace them."
                )
            key = stored
            if len(key) != 32:
                raise RuntimeError("BabyMind's local encryption key is invalid.")
            return key

        key = secrets.token_bytes(32)
        stored = key
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
        """Encrypt new plaintext, even when it resembles a ciphertext marker."""
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), b"BabyMind:text:v1")
        return _PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def encrypt_legacy(self, value: str) -> str:
        """Migrate a stored legacy value; never use this for new user input.

        The old format has no separate encrypted-column marker, so a legacy
        plaintext value beginning with the marker is ambiguous. Preserve it
        rather than silently converting a damaged ciphertext into plaintext.
        """
        return value if value.startswith(_PREFIX) else self.encrypt(value)

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
