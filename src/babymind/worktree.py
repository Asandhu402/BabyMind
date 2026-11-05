"""Disposable git-worktree isolation for self-development edits.

With ``BABYMIND_SELF_EDIT_WORKTREE=true`` and a git checkout, ``apply_edits``
first applies and verifies the change in a throwaway ``git worktree`` of HEAD.
The user's primary checkout is only touched after the worktree copy passes
compile and tests, so a broken patch never lands in the working tree even
before the checkpoint rollback runs.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class WorktreeError(RuntimeError):
    pass


def _git(root: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, timeout=timeout)


def is_git_repo(root: Path) -> bool:
    if shutil.which("git") is None:
        return False
    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def create_worktree(root: Path) -> Path:
    """Create a disposable worktree of HEAD and return its path."""
    if not is_git_repo(root):
        raise WorktreeError(f"{root} is not a git work tree.")
    target = Path(tempfile.mkdtemp(prefix="babymind-worktree-"))
    result = _git(root, "worktree", "add", "--detach", str(target), "HEAD")
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise WorktreeError("git worktree add failed: " + result.stderr.strip()[:300])
    return target


def discard_worktree(root: Path, worktree: Path) -> None:
    """Remove a disposable worktree, discarding all changes in it."""
    _git(root, "worktree", "remove", "--force", str(worktree))
    shutil.rmtree(worktree, ignore_errors=True)


def worktree_enabled() -> bool:
    import os
    return os.getenv("BABYMIND_SELF_EDIT_WORKTREE", "").strip().lower() in {"1", "true", "yes", "on"}
