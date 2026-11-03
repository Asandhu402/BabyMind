"""Constrained launcher for the external Open Interpreter CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def launch_read_only_session(
    workspace: str | Path,
    *,
    model: str = "",
    base_url: str = "",
    user_approved: bool = False,
) -> subprocess.Popen:
    """Launch Open Interpreter against a local OpenAI-compatible model in read-only mode.

    The documented OSS provider path is forced explicitly. Hosted provider
    selection is never inherited from the user's Open Interpreter config.
    The CLI's own sandbox must enforce read-only access; this wrapper is not
    an independent OS-level security boundary.
    """
    if not user_approved:
        raise PermissionError("Launching a coding-agent session requires approval.")
    clean_model = model.strip()
    if not clean_model or len(clean_model) > 300:
        raise ValueError("A valid local model ID is required.")
    if not (
        base_url.startswith("http://127.0.0.1:")
        or base_url.startswith("http://localhost:")
    ):
        raise ValueError("Open Interpreter must use a local model endpoint.")
    executable = shutil.which("interpreter")
    if not executable:
        raise FileNotFoundError(
            "Open Interpreter CLI not found. Install it from "
            "https://github.com/openinterpreter/openinterpreter"
        )
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")

    # Current Open Interpreter CLI local-model configuration. --oss plus the
    # explicit local provider prevents a cloud provider saved in user config
    # from becoming the default. CODEX_OSS_BASE_URL selects BabyMind's local
    # model server; -c overrides the sandbox for this invocation only.
    environment = os.environ.copy()
    environment["CODEX_OSS_BASE_URL"] = base_url.rstrip("/")
    command = [
        executable,
        "--oss",
        "--local-provider",
        "lmstudio",
        "-m",
        clean_model,
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        'approval_policy="untrusted"',
    ]
    return subprocess.Popen(
        command,
        cwd=str(root),
        env=environment,
        shell=False,
        stdin=None,
        stdout=None,
        stderr=None,
    )
