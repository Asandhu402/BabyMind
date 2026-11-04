"""Password-protected backups for BabyMind's encrypted local databases.

The archive is encrypted with scrypt + AES-256-GCM. It contains the existing
encrypted SQLite databases and their key files; it never exports plaintext
conversation or memory text. Preserve both the archive and its password;
backups do not contain source checkout snapshots.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_MAGIC = b"BMBK1"
_SALT_BYTES = 16
_NONCE_BYTES = 12
_MAX_ARCHIVE = 512 * 1024 * 1024
_MAX_PASSWORD = 1024
_DATABASES = ("app.sqlite3", "memory.sqlite3")
_KEY_FILES = ("app.key", "memory.key")
_ALLOWED = frozenset((*_DATABASES, *_KEY_FILES, "manifest.json"))


def _derive(password: str, salt: bytes) -> bytes:
    clean = password.encode("utf-8")
    if len(clean) < 12 or len(clean) > _MAX_PASSWORD:
        raise ValueError("Backup password must be 12–1,024 UTF-8 bytes.")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(clean)


def _snapshot_database(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(str(source), timeout=15)
    target_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(target_connection)
        result = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed for {source.name}.")
    finally:
        target_connection.close()
        source_connection.close()


def _read_existing(home: Path, work: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in _DATABASES:
        source = home / name
        if source.is_file():
            snapshot = work / name
            _snapshot_database(source, snapshot)
            files[name] = snapshot.read_bytes()
            key_name = "app.key" if name == "app.sqlite3" else "memory.key"
            key_path = home / key_name
            if not key_path.is_file():
                raise RuntimeError(f"{name} exists but {key_name} is missing; refusing to create an incomplete backup.")
            files[key_name] = key_path.read_bytes()
    if not files:
        raise RuntimeError("There is no BabyMind database to back up yet.")
    return files


def create_backup(home: str | Path, destination: str | Path, password: str) -> dict[str, object]:
    """Create an authenticated, password-protected backup without plaintext export."""
    root = Path(home).expanduser().resolve()
    target = Path(destination).expanduser()
    if not target.name or target.suffix.lower() not in {".bmbak", ".bak"}:
        raise ValueError("Choose a backup filename ending in .bmbak.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve() == root or root in target.resolve().parents:
        raise ValueError("Store the backup outside BabyMind's live data directory.")
    if target.exists() and target.is_dir():
        raise ValueError("Backup destination must be a file.")
    with tempfile.TemporaryDirectory(prefix="babymind-backup-") as temporary:
        work = Path(temporary)
        files = _read_existing(root, work)
        manifest = {
            "format": 1,
            "application": "BabyMind",
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        }
        files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode("utf-8")
        archive_path = work / "backup.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        plaintext = archive_path.read_bytes()
        if len(plaintext) > _MAX_ARCHIVE:
            raise ValueError("Backup exceeds the 512 MB safety limit.")
        salt, nonce = secrets.token_bytes(_SALT_BYTES), secrets.token_bytes(_NONCE_BYTES)
        encrypted = AESGCM(_derive(password, salt)).encrypt(nonce, plaintext, _MAGIC)
        temporary_target = target.with_name(target.name + ".tmp")
        try:
            with temporary_target.open("xb") as stream:
                stream.write(_MAGIC + salt + nonce + encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_target, target)
        finally:
            temporary_target.unlink(missing_ok=True)
    return {"path": str(target.resolve()), "bytes": target.stat().st_size, "files": sorted(files)}


def _decrypt_backup(source: Path, password: str, work: Path) -> dict[str, bytes]:
    if not source.is_file():
        raise FileNotFoundError(f"Backup file not found: {source}")
    if source.stat().st_size > _MAX_ARCHIVE + 1024:
        raise ValueError("Backup file exceeds the 512 MB safety limit.")
    payload = source.read_bytes()
    header_size = len(_MAGIC) + _SALT_BYTES + _NONCE_BYTES
    if len(payload) <= header_size or not payload.startswith(_MAGIC):
        raise ValueError("This is not a valid BabyMind backup file.")
    offset = len(_MAGIC)
    salt = payload[offset:offset + _SALT_BYTES]
    nonce = payload[offset + _SALT_BYTES:header_size]
    try:
        plaintext = AESGCM(_derive(password, salt)).decrypt(nonce, payload[header_size:], _MAGIC)
    except Exception as error:
        raise ValueError("Backup password is incorrect or the backup has been damaged.") from error
    if len(plaintext) > _MAX_ARCHIVE:
        raise ValueError("Decrypted backup exceeds the safety limit.")
    archive_path = work / "backup.zip"
    archive_path.write_bytes(plaintext)
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) > len(_ALLOWED) or set(names) - _ALLOWED or len(names) != len(set(names)):
            raise ValueError("Backup contains unexpected or duplicate file paths.")
        total_size = 0
        for info in archive.infolist():
            total_size += info.file_size
            if info.is_dir() or info.file_size > _MAX_ARCHIVE or total_size > _MAX_ARCHIVE:
                raise ValueError("Backup contains an invalid or oversized file entry.")
            files[info.filename] = archive.read(info)
    manifest_raw = files.pop("manifest.json", None)
    if manifest_raw is None:
        raise ValueError("Backup manifest is missing.")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except Exception as error:
        raise ValueError("Backup manifest is invalid.") from error
    if manifest.get("format") != 1 or manifest.get("application") != "BabyMind":
        raise ValueError("Unsupported BabyMind backup format.")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or set(expected) != set(files):
        raise ValueError("Backup manifest does not match its contents.")
    for name, data in files.items():
        if hashlib.sha256(data).hexdigest() != expected[name]:
            raise ValueError(f"Backup integrity check failed for {name}.")
    for database, key in (("app.sqlite3", "app.key"), ("memory.sqlite3", "memory.key")):
        if (database in files) != (key in files):
            raise ValueError(f"Backup is incomplete: {database} and {key} must be present together.")
    if not files:
        raise ValueError("Backup contains no BabyMind data.")
    return files


def _validate_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"Database integrity check failed for {path.name}.")
    finally:
        connection.close()


def _validate_encrypted_data(work: Path, files: dict[str, bytes]) -> None:
    """Confirm each included key can decrypt the encrypted fields in its DB."""
    from .secure_store import SecureTextStore

    checks = {
        "app.sqlite3": {
            "conversations": ("title",),
            "messages": ("content",),
            "tasks": ("title", "details"),
            "execution_proposals": ("payload", "result"),
            "development_reviews": ("task", "context"),
            "development_review_roles": ("response",),
            "development_review_attempts": ("error", "response"),
        },
        "memory.sqlite3": {"memories": ("task", "response")},
    }
    for database, tables in checks.items():
        if database not in files:
            continue
        key_name = "app.key" if database == "app.sqlite3" else "memory.key"
        key_path = work / key_name
        key_path.write_bytes(files[key_name])
        store = SecureTextStore(key_path)
        connection = sqlite3.connect(str(work / database))
        try:
            available = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            for table, columns in tables.items():
                if table not in available:
                    continue
                existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                for column in columns:
                    if column not in existing:
                        continue
                    for (value,) in connection.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"):
                        if isinstance(value, str) and value.startswith("bmenc:v1:"):
                            store.decrypt(value)
        finally:
            connection.close()


def restore_backup(
    home: str | Path,
    source: str | Path,
    password: str,
    *,
    confirmation: str,
) -> dict[str, object]:
    """Validate a backup fully, then atomically replace the local DB/key set."""
    if confirmation != "RESTORE BABYMIND":
        raise PermissionError("Type RESTORE BABYMIND to confirm replacing local BabyMind data.")
    root = Path(home).expanduser().resolve()
    backup = Path(source).expanduser().resolve()
    if backup == root or root in backup.parents:
        raise ValueError("Restore source must be outside BabyMind's live data directory.")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="babymind-restore-", dir=root.parent) as temporary:
        work = Path(temporary)
        files = _decrypt_backup(backup, password, work)
        for name, data in files.items():
            staged = work / name
            staged.write_bytes(data)
            if name.endswith(".sqlite3"):
                _validate_database(staged)
        _validate_encrypted_data(work, files)
        # Keep a rollback copy until all replacements have completed.
        rollback = work / "rollback"
        rollback.mkdir()
        changed: list[Path] = []
        previous: dict[str, bytes | None] = {}
        try:
            # Replace the complete known database/key set, including removing
            # stores that did not exist when this backup was created.
            for name in (*_DATABASES, *_KEY_FILES):
                destination = root / name
                previous[name] = destination.read_bytes() if destination.is_file() else None
                if name not in files:
                    destination.unlink(missing_ok=True)
                else:
                    staged = work / name
                    staged_target = root / (name + ".restore-tmp")
                    shutil.copyfile(staged, staged_target)
                    os.replace(staged_target, destination)
                changed.append(destination)
        except Exception:
            for destination in reversed(changed):
                old = previous[destination.name]
                if old is None:
                    destination.unlink(missing_ok=True)
                else:
                    rollback_file = rollback / destination.name
                    rollback_file.write_bytes(old)
                    os.replace(rollback_file, destination)
            raise
    return {"restored": sorted(files), "path": str(root)}
