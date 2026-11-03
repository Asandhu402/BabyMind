"""Workspace-scoped launcher for the external Open Interpreter coding CLI."""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path

def launch_workspace_session(workspace: str | Path, *, model: str = "", base_url: str = "", user_approved: bool = False) -> subprocess.Popen:
    """Launch with write access limited to the selected workspace.

    The CLI/OS sandbox must enforce the workspace boundary for commands and
    child processes. Network access is disabled. If enforcement is unavailable,
    the CLI must fail closed; this wrapper never falls back to unsandboxed mode.
    """
    if not user_approved:
        raise PermissionError("Launching a coding-agent session requires approval.")
    clean_model = model.strip()
    if not clean_model or len(clean_model) > 300:
        raise ValueError("A valid local model ID is required.")
    if not (base_url.startswith("http://127.0.0.1:") or base_url.startswith("http://localhost:")):
        raise ValueError("The coding assistant must use a local model endpoint.")
    executable = shutil.which("interpreter")
    if not executable:
        raise FileNotFoundError("Open Interpreter CLI not found. Install it from https://github.com/openinterpreter/openinterpreter")
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")
    environment = os.environ.copy()
    environment["CODEX_OSS_BASE_URL"] = base_url.rstrip("/")
    command = [
        executable, "--oss", "--local-provider", "lmstudio", "-m", clean_model,
        "--cd", str(root), "--sandbox", "workspace-write",
        "--ask-for-approval", "on-request", "-c",
        "sandbox_workspace_write.network_access=false",
    ]
    return subprocess.Popen(
        command, cwd=str(root), env=environment, shell=False,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0,
        stdin=None, stdout=None, stderr=None,
    )
