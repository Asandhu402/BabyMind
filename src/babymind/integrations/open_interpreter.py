"""Workspace-scoped launcher for a future llama.cpp-native coding adapter."""
from __future__ import annotations

from pathlib import Path


def launch_workspace_session(
    workspace: str | Path, *, model: str = "", base_url: str = "",
    user_approved: bool = False,
):
    """Fail closed until the coding CLI supports BabyMind's llama.cpp endpoint."""
    if not user_approved:
        raise PermissionError("Launching a coding-agent session requires approval.")
    if not model.strip():
        raise ValueError("A valid llama.cpp model ID is required.")
    if not (
        base_url.startswith("http://127.0.0.1:")
        or base_url.startswith("http://localhost:")
    ):
        raise ValueError("The coding assistant must use BabyMind's local llama.cpp endpoint.")
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")
    raise RuntimeError(
        "The external coding CLI does not provide a verified llama.cpp-native "
        "provider path. BabyMind has disabled this adapter rather than launching "
        "a different model runtime."
    )
