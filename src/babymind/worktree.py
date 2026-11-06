"""Disposable git-worktree isolation for self-development edits.

With ``BABYMIND_SELF_EDIT_WORKTREE=true`` and a git checkout, ``apply_edits``
first applies and verifies the change in a throwaway ``git worktree`` of HEAD.
The user's primary checkout is only touched after the worktree copy passes
compile and tests, so a broken patch never lands in the working tree even
before the checkpoint rollback runs.
"""
from __future__ import annotations

import os
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


def create_worktree(root: Path, *, include_working_tree: bool = False) -> Path:
    """Create a disposable worktree, optionally mirroring tracked and untracked edits.

    Pre-verification must test the exact checkout the user is editing, not only
    HEAD. Ignored files (for example virtual environments and caches) remain
    excluded; symlinked untracked files are rejected rather than followed.
    """
    if not is_git_repo(root):
        raise WorktreeError(f"{root} is not a git work tree.")
    target = Path(tempfile.mkdtemp(prefix="babymind-worktree-"))
    result = _git(root, "worktree", "add", "--detach", str(target), "HEAD")
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise WorktreeError("git worktree add failed: " + result.stderr.strip()[:300])
    try:
        if include_working_tree:
            diff = _git(root, "diff", "--binary", "HEAD")
            if diff.returncode != 0:
                raise WorktreeError("Could not snapshot tracked working-tree changes: "
                                    + diff.stderr.strip()[:300])
            if diff.stdout:
                applied = subprocess.run(["git", "apply", "--binary", "-"], cwd=str(target),
                                          input=diff.stdout, capture_output=True, text=True,
                                          timeout=120)
                if applied.returncode != 0:
                    raise WorktreeError("Could not reproduce tracked working-tree changes: "
                                        + applied.stderr.strip()[:300])
            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=str(root), capture_output=True, timeout=30,
            )
            if untracked.returncode != 0:
                raise WorktreeError("Could not enumerate untracked working-tree files.")
            root_resolved = root.resolve()
            for raw_path in untracked.stdout.split(b"\0"):
                if not raw_path:
                    continue
                relative = Path(os.fsdecode(raw_path))
                source = root / relative
                if source.is_symlink():
                    raise WorktreeError(f"Refusing to copy untracked symlink into pre-verification: {relative}")
                resolved = source.resolve(strict=True)
                if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
                    raise WorktreeError(f"Refusing non-regular untracked path in pre-verification: {relative}")
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        return target
    except Exception:
        _git(root, "worktree", "remove", "--force", str(target))
        shutil.rmtree(target, ignore_errors=True)
        raise


def discard_worktree(root: Path, worktree: Path) -> None:
    """Remove a disposable worktree, discarding all changes in it."""
    _git(root, "worktree", "remove", "--force", str(worktree))
    shutil.rmtree(worktree, ignore_errors=True)


def worktree_enabled() -> bool:
    import os
    return os.getenv("BABYMIND_SELF_EDIT_WORKTREE", "").strip().lower() in {"1", "true", "yes", "on"}
