"""Constrained launcher for the external Open Interpreter CLI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def launch_read_only_session(
    workspace: str | Path,
    *,
    user_approved: bool = False,
) -> subprocess.Popen:
    """Launch Open Interpreter in read-only mode in a selected workspace.

    This deliberately does not expose write access, project execution, shell
    escalation, or approval-bypass flags. The installed CLI must enforce its
    own native sandbox; if it cannot, the user should cancel the session.
    """
    if not user_approved:
        raise PermissionError("Launching a coding-agent session requires approval.")
    executable = shutil.which("interpreter")
    if not executable:
        raise FileNotFoundError(
            "Open Interpreter CLI not found. Install it from "
            "https://github.com/openinterpreter/openinterpreter"
        )
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")
    return subprocess.Popen(
        [executable, "--sandbox", "read-only"],
        cwd=str(root),
        shell=False,
        stdin=None,
        stdout=None,
        stderr=None,
    )
