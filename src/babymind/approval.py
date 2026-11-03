"""Approval-gated local workspace file actions."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

WORKSPACE_FILE_ACTIONS_ENABLED = False  # Fail closed pending native handle-based path protection.
MAX_TEXT_FILE_BYTES = 32 * 1024
MAX_SEARCH_DIRECTORIES = 250
MAX_SEARCH_FILES = 2000
MAX_SEARCH_RESULTS = 50
MAX_SEARCH_DEPTH = 3
ALLOWED_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".py", ".js",
    ".ts", ".html", ".css", ".sql", ".sh", ".ps1"
}


def _workspace_root() -> Path:
    configured = os.getenv("BABYMIND_WORKSPACE_ROOT", "").strip()
    if not configured:
        raise ValueError("Set BABYMIND_WORKSPACE_ROOT to a workspace folder before proposing local actions.")
    root = Path(configured).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("BABYMIND_WORKSPACE_ROOT must point to an existing directory.")
    return root


def _relative_path(relative_path: str) -> tuple[Path, Path, Path]:
    if not isinstance(relative_path, str) or len(relative_path) > 500 or "\x00" in relative_path:
        raise ValueError("Workspace path is invalid or too long.")
    part = Path(relative_path or ".")
    if part.is_absolute() or any(piece == ".." for piece in part.parts):
        raise ValueError("Use a relative path inside the selected workspace; parent traversal is not allowed.")
    root = _workspace_root()
    candidate = root / part
    current = root
    for piece in part.parts:
        if piece in {"", "."}:
            continue
        if piece.startswith("."):
            raise ValueError("Hidden workspace paths are not supported.")
        current = current / piece
        if current.is_symlink():
            raise ValueError("Symbolic links are not supported in approved workspace actions.")
    try:
        target = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("The selected path must already exist inside the configured workspace.") from error
    if not target.is_relative_to(root):
        raise ValueError("The selected path must remain inside the configured workspace.")
    return root, candidate, target


def _safe_directory(relative_path: str) -> tuple[Path, Path]:
    root, _, target = _relative_path(relative_path)
    if not target.is_dir():
        raise ValueError("The selected path must be an existing directory inside the workspace.")
    return root, target


def _safe_text_file(relative_path: str) -> tuple[Path, Path]:
    root, _, target = _relative_path(relative_path)
    if not target.is_file():
        raise ValueError("Choose an existing regular text file inside the workspace.")
    if target.suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise ValueError("This file type is not supported for preview.")
    if target.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise ValueError("Text-file previews are limited to 32 KB.")
    return root, target



def _safe_new_text_file(relative_path: str, content: str) -> tuple[Path, Path, str]:
    """Validate a new text file target without following links or overwriting."""
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 500 or "\x00" in relative_path:
        raise ValueError("Workspace file path is invalid or too long.")
    part = Path(relative_path)
    if part.is_absolute() or any(piece in {"..", ""} for piece in part.parts):
        raise ValueError("Use a new relative file path inside the selected workspace.")
    if any(piece.startswith(".") for piece in part.parts):
        raise ValueError("Hidden workspace paths are not supported.")
    if part.suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise ValueError("This file type is not supported for creation.")
    if not isinstance(content, str) or "\x00" in content:
        raise ValueError("New file content must be plain UTF-8 text.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TEXT_FILE_BYTES:
        raise ValueError("New text files are limited to 32 KB.")
    root = _workspace_root()
    parent = root / part.parent
    current = root
    for piece in part.parent.parts:
        if piece in {"", "."}:
            continue
        current = current / piece
        if current.is_symlink():
            raise ValueError("Symbolic links are not supported in approved workspace actions.")
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as error:
        raise ValueError("The parent folder must already exist inside the configured workspace.") from error
    if not resolved_parent.is_dir() or not resolved_parent.is_relative_to(root):
        raise ValueError("The parent folder must exist inside the configured workspace.")
    target = resolved_parent / part.name
    if target.exists() or target.is_symlink():
        raise ValueError("The target file already exists. BabyMind will never overwrite an existing file.")
    return root, target, content



def build_readonly_proposal(
    relative_path: str, action: str = "list_directory", name_contains: str = "",
    content: str = ""
) -> dict:
    if not WORKSPACE_FILE_ACTIONS_ENABLED:
        raise ValueError("Workspace file actions are disabled until native race-resistant filesystem protection is available.")
    if action == "create_text_file":
        root, target, clean_content = _safe_new_text_file(relative_path.strip(), content)
        relative = target.relative_to(root).as_posix()
        payload = {"relative_path": relative, "content": clean_content}
    elif action == "list_directory":
        root, target = _safe_directory(relative_path.strip())
        relative = target.relative_to(root).as_posix() or "."
        payload = {"relative_path": relative}
    elif action == "read_text_file":
        root, target = _safe_text_file(relative_path.strip())
        relative = target.relative_to(root).as_posix()
        payload = {"relative_path": relative}
    elif action == "edit_text_file":
        root, target = _safe_text_file(relative_path.strip())
        with target.open("rb") as handle:
            original = handle.read(MAX_TEXT_FILE_BYTES + 1)
        if len(original) > MAX_TEXT_FILE_BYTES or b"\x00" in original:
            raise ValueError("Only UTF-8 text files up to 32 KB can be edited.")
        try:
            original_text = original.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Only valid UTF-8 text files can be edited.") from error
        if not isinstance(content, str) or "\x00" in content or len(content.encode("utf-8")) > MAX_TEXT_FILE_BYTES:
            raise ValueError("Edited text must be plain UTF-8 and no larger than 32 KB.")
        relative = target.relative_to(root).as_posix()
        payload = {
            "relative_path": relative,
            "expected_sha256": hashlib.sha256(original).hexdigest(),
            "original_content": original_text,
            "content": content,
        }

    elif action == "find_files":
        root, target = _safe_directory(relative_path.strip())
        query = name_contains.strip()
        if not query or len(query) > 80 or any(ord(char) < 32 for char in query):
            raise ValueError("Enter a filename search of 1 to 80 printable characters.")
        relative = target.relative_to(root).as_posix() or "."
        payload = {"relative_path": relative, "name_contains": query}
    else:
        raise ValueError("Unsupported workspace action.")
    canonical = json.dumps({"action": action, "payload": payload}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "action": action,
        "payload": payload,
        "proposal_hash": digest,
        "display_target": relative,
        "max_bytes": MAX_TEXT_FILE_BYTES if action in {"read_text_file", "create_text_file", "edit_text_file"} else None,
    }


def execute_readonly_proposal(payload: dict, action: str = "list_directory") -> dict:
    if not WORKSPACE_FILE_ACTIONS_ENABLED:
        raise ValueError("Workspace file actions are disabled until native race-resistant filesystem protection is available.")
    if action == "edit_text_file":
        required = {"relative_path", "expected_sha256", "original_content", "content"}
        if not isinstance(payload, dict) or set(payload) != required or any(not isinstance(payload[key], str) for key in required):
            raise ValueError("Unsupported or malformed approved action.")
        root, target = _safe_text_file(payload["relative_path"])
        try:
            new_content = payload["content"].encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("Edited text must be valid UTF-8.") from error
        if len(new_content) > MAX_TEXT_FILE_BYTES or b"\x00" in new_content:
            raise ValueError("Edited text must be plain UTF-8 and no larger than 32 KB.")
        with target.open("rb") as handle:
            current = handle.read(MAX_TEXT_FILE_BYTES + 1)
        if hashlib.sha256(current).hexdigest() != payload["expected_sha256"]:
            raise ValueError("The file changed after review. No changes were applied; create a new proposal.")
        try:
            current_text = current.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("The current file is no longer valid UTF-8. No changes were applied.") from error
        if current_text != payload["original_content"]:
            raise ValueError("The file content no longer matches the reviewed version. No changes were applied.")
        descriptor = -1
        temporary_path = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(prefix=".babymind-edit-", suffix=".tmp", dir=target.parent)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(new_content)
                handle.flush()
                os.fsync(handle.fileno())
            # Recheck immediately before atomic replacement to avoid applying a stale proposal.
            with target.open("rb") as handle:
                latest = handle.read(MAX_TEXT_FILE_BYTES + 1)
            if hashlib.sha256(latest).hexdigest() != payload["expected_sha256"]:
                raise ValueError("The file changed during approval. No changes were applied.")
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
        return {"relative_path": target.relative_to(root).as_posix(), "updated": True,
                "old_sha256": payload["expected_sha256"],
                "new_sha256": hashlib.sha256(new_content).hexdigest(),
                "bytes": len(new_content)}
    if action == "run_tests":
        raise ValueError("Project test execution is disabled until a real sandbox is available.")

    if action == "create_text_file":
        if (not isinstance(payload, dict) or set(payload) != {"relative_path", "content"}
                or not isinstance(payload["relative_path"], str)
                or not isinstance(payload["content"], str)):
            raise ValueError("Unsupported or malformed approved action.")
        root, target, content = _safe_new_text_file(payload["relative_path"], payload["content"])
        encoded = content.encode("utf-8")
        try:
            # O_EXCL prevents overwriting a file created after proposal review.
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ValueError("The target file now exists. No file was overwritten.") from error
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"relative_path": target.relative_to(root).as_posix(), "created": True,
                "bytes": len(encoded), "notice": "New UTF-8 text file created; existing files are never overwritten."}
    if action == "find_files":
        if (not isinstance(payload, dict) or set(payload) != {"relative_path", "name_contains"}
                or not isinstance(payload["relative_path"], str)
                or not isinstance(payload["name_contains"], str)):
            raise ValueError("Unsupported or malformed approved action.")
        root, target = _safe_directory(payload["relative_path"])
        query = payload["name_contains"].casefold()
        found = []
        visited_dirs = 0
        visited_files = 0
        truncated = False
        stack = [(target, 0)]
        while stack:
            current, depth = stack.pop()
            visited_dirs += 1
            if visited_dirs > MAX_SEARCH_DIRECTORIES:
                truncated = True
                break
            try:
                children = sorted(current.iterdir(), key=lambda entry: entry.name.casefold())
            except OSError:
                continue
            directories = []
            for child in children:
                if child.name.startswith(".") or child.is_symlink():
                    continue
                if child.is_dir():
                    if depth < MAX_SEARCH_DEPTH:
                        directories.append(child)
                    continue
                if not child.is_file():
                    continue
                visited_files += 1
                if visited_files > MAX_SEARCH_FILES:
                    truncated = True
                    break
                if child.suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
                    continue
                if query in child.name.casefold():
                    found.append({
                        "relative_path": child.relative_to(root).as_posix(),
                        "name": child.name[:255],
                        "type": "text_file"
                    })
                    if len(found) >= MAX_SEARCH_RESULTS:
                        truncated = True
                        break
            if truncated:
                break
            stack.extend((directory, depth + 1) for directory in reversed(directories))
        return {
            "relative_path": target.relative_to(root).as_posix() or ".",
            "name_contains": payload["name_contains"],
            "files": found,
            "count": len(found),
            "truncated": truncated,
            "note": "Filename search only. File contents were not opened."
        }
    if not isinstance(payload, dict) or set(payload) != {"relative_path"} or not isinstance(payload["relative_path"], str):
        raise ValueError("Unsupported or malformed approved action.")
    if action == "read_text_file":
        root, target = _safe_text_file(payload["relative_path"])
        with target.open("rb") as handle:
            raw = handle.read(MAX_TEXT_FILE_BYTES + 1)
        if len(raw) > MAX_TEXT_FILE_BYTES:
            raise ValueError("Text-file previews are limited to 32 KB.")
        if b"\x00" in raw:
            raise ValueError("The selected file does not appear to be plain text.")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Only valid UTF-8 text files can be previewed.") from error
        return {
            "relative_path": target.relative_to(root).as_posix(),
            "content": content,
            "bytes": len(raw),
        }
    if action != "list_directory":
        raise ValueError("Unsupported or malformed approved action.")
    root, target = _safe_directory(payload["relative_path"])
    items = sorted(target.iterdir(), key=lambda entry: entry.name.casefold())
    entries = []
    for item in items[:200]:
        entries.append({
            "name": item.name[:255],
            "type": "directory" if item.is_dir() and not item.is_symlink() else
                    "symlink" if item.is_symlink() else "file"
        })
    return {
        "relative_path": target.relative_to(root).as_posix() or ".",
        "entries": entries,
        "truncated": len(items) > 200
    }
