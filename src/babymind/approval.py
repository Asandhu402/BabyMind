"""Approval-gated, read-only local workspace actions.

Only directory listings are supported in this first execution increment.
No shell, file reads, writes, deletes, network access, or arbitrary commands.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _workspace_root() -> Path:
    configured = os.getenv("BABYMIND_WORKSPACE_ROOT", "").strip()
    if not configured:
        raise ValueError("Set BABYMIND_WORKSPACE_ROOT to a workspace folder before proposing local actions.")
    root = Path(configured).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("BABYMIND_WORKSPACE_ROOT must point to an existing directory.")
    return root


def _safe_target(relative_path: str) -> tuple[Path, Path]:
    if len(relative_path) > 500 or "\x00" in relative_path:
        raise ValueError("Workspace path is invalid or too long.")
    candidate_part = Path(relative_path or ".")
    if candidate_part.is_absolute() or any(part == ".." for part in candidate_part.parts):
        raise ValueError("Use a relative path inside the selected workspace; parent traversal is not allowed.")
    root = _workspace_root()
    target = (root / candidate_part).resolve(strict=True)
    if not target.is_dir() or not target.is_relative_to(root):
        raise ValueError("The selected path must be an existing directory inside the workspace.")
    return root, target


def build_readonly_proposal(relative_path: str) -> dict:
    root, target = _safe_target(relative_path.strip())
    payload = {"relative_path": target.relative_to(root).as_posix() or "."}
    canonical = json.dumps({"action": "list_directory", "payload": payload}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "action": "list_directory",
        "payload": payload,
        "proposal_hash": digest,
        "display_target": payload["relative_path"]
    }


def execute_readonly_proposal(payload: dict) -> dict:
    if set(payload) != {"relative_path"} or not isinstance(payload["relative_path"], str):
        raise ValueError("Unsupported or malformed approved action.")
    root, target = _safe_target(payload["relative_path"])
    entries = []
    for item in sorted(target.iterdir(), key=lambda entry: entry.name.casefold())[:200]:
        # Names and basic types only; do not follow symlinks or read file contents.
        entries.append({
            "name": item.name[:255],
            "type": "directory" if item.is_dir() and not item.is_symlink() else
                    "symlink" if item.is_symlink() else "file"
        })
    return {
        "relative_path": target.relative_to(root).as_posix() or ".",
        "entries": entries,
        "truncated": len(list(target.iterdir())) > 200
    }
