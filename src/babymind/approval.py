"""Approval-gated, read-only local workspace actions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

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
    target = candidate.resolve(strict=True)
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


def build_readonly_proposal(
    relative_path: str, action: str = "list_directory", name_contains: str = ""
) -> dict:
    if action == "list_directory":
        root, target = _safe_directory(relative_path.strip())
        relative = target.relative_to(root).as_posix() or "."
        payload = {"relative_path": relative}
    elif action == "read_text_file":
        root, target = _safe_text_file(relative_path.strip())
        relative = target.relative_to(root).as_posix()
        payload = {"relative_path": relative}
    elif action == "find_files":
        root, target = _safe_directory(relative_path.strip())
        query = name_contains.strip()
        if not query or len(query) > 80 or any(ord(char) < 32 for char in query):
            raise ValueError("Enter a filename search of 1 to 80 printable characters.")
        relative = target.relative_to(root).as_posix() or "."
        payload = {"relative_path": relative, "name_contains": query}
    else:
        raise ValueError("Unsupported read-only action.")
    canonical = json.dumps({"action": action, "payload": payload}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "action": action,
        "payload": payload,
        "proposal_hash": digest,
        "display_target": relative,
        "max_bytes": MAX_TEXT_FILE_BYTES if action == "read_text_file" else None,
    }


def execute_readonly_proposal(payload: dict, action: str = "list_directory") -> dict:
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
