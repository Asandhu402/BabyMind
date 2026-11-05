"""Preview window and upgrade helpers for the self-development window.

A preview window runs a second, isolated BabyMind server instance from the
developable (possibly patched) source tree on a random localhost port, with
its own data folder, so upgraded features can be tried without touching the
running app. An upgrade copies verified staged source into the downloaded
package's source seed so the next launch of the installed app includes the
changes. The running executable is never modified or restarted by this module.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import selfdev

UPGRADE_CONFIRMATION = "UPGRADE BABYMIND"
_PREVIEW_LOCK = threading.Lock()
_preview: dict | None = None


class UpgradeError(ValueError):
    """Raised when a preview or upgrade action is rejected."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _preview_home(root: Path) -> Path:
    home = root / selfdev.STATE_DIRNAME / "preview-data"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    return home


def start_preview() -> dict:
    """Launch an isolated preview server from the developable source tree."""
    global _preview
    with _PREVIEW_LOCK:
        if _preview and _preview["process"].poll() is None:
            return {"url": _preview["url"], "port": _preview["port"], "pid": _preview["process"].pid,
                    "already_running": True}
        root = selfdev.dev_root()
        port = _free_port()
        env = dict(os.environ)
        env["BABYMIND_DEV_ROOT"] = str(root)
        env["BABYMIND_HOME"] = str(_preview_home(root))
        env["BABYMIND_SELF_DEVELOPMENT_ENABLED"] = "true"
        if getattr(sys, "frozen", False):
            from . import packaged_dev
            interpreter = str(packaged_dev.python_path())
            env.update(packaged_dev.python_environment())
            env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), env.get("PYTHONPATH", "")])
        else:
            interpreter = sys.executable
            env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), env.get("PYTHONPATH", "")])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.Popen(
            [interpreter, "-m", "babymind.server", "--host", "127.0.0.1",
             "--port", str(port), "--no-browser"],
            env=env, cwd=str(root),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        url = f"http://127.0.0.1:{port}/"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise UpgradeError("The preview window failed to start; it exited immediately.")
            try:
                with urllib.request.urlopen(url + "api/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            process.terminate()
            raise UpgradeError("The preview window did not become ready within 30 seconds.")
        _preview = {"process": process, "port": port, "url": url}
        return {"url": url, "port": port, "pid": process.pid, "root": str(root)}


def stop_preview() -> dict:
    """Stop the preview server if one is running."""
    global _preview
    with _PREVIEW_LOCK:
        if not _preview:
            return {"stopped": False, "notice": "No preview window is running."}
        process = _preview["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        _preview = None
        return {"stopped": True, "notice": "Preview window stopped. The running app was not affected."}


def preview_state() -> dict:
    with _PREVIEW_LOCK:
        if not _preview:
            return {"running": False}
        return {"running": _preview["process"].poll() is None,
                "url": _preview["url"], "port": _preview["port"], "pid": _preview["process"].pid}


def _copy_tree(source: Path, target: Path, *, skip_names: set[str]) -> int:
    copied = 0
    for directory, subdirectories, files in os.walk(source, followlinks=False):
        subdirectories[:] = sorted(d for d in subdirectories if d not in skip_names and d != "__pycache__")
        if Path(directory).is_symlink():
            raise UpgradeError("The staged source contains a symbolic link; refusing to upgrade.")
        relative = Path(directory).relative_to(source)
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            if name in skip_names or name.endswith(".pyc"):
                continue
            origin = Path(directory) / name
            if origin.is_symlink():
                raise UpgradeError("The staged source contains a symbolic link; refusing to upgrade.")
            shutil.copy2(origin, destination / name)
            copied += 1
    return copied


def upgrade(confirmation: str) -> dict:
    """Copy the verified staged source into the downloaded package's source seed.

    Only meaningful for the packaged (downloaded) app. The running executable
    is never touched; the next launch of the installed app uses the upgraded
    source seed. A timestamped backup of the original seed is kept first.
    """
    if confirmation != UPGRADE_CONFIRMATION:
        raise UpgradeError(f'Type {UPGRADE_CONFIRMATION} to confirm the upgrade.')
    if not getattr(sys, "frozen", False):
        return {
            "upgraded": False,
            "notice": ("BabyMind is already running from this source checkout, so there is no "
                       "downloaded copy to upgrade. Edits here are live immediately after tests pass."),
        }
    from . import packaged_dev
    staged = packaged_dev.workspace()  # validates marker and seed fingerprint; never overwrites user edits
    seed = packaged_dev.app_directory() / "dev-source-seed"
    if seed.is_symlink() or not (seed / "src" / "babymind").is_dir():
        raise UpgradeError("The downloaded source seed is missing or invalid; nothing was changed.")
    backup = packaged_dev.app_directory() / f"dev-source-seed.backup-{selfdev.now().replace(':', '-')}"
    if backup.exists():
        raise UpgradeError("An upgrade backup already exists from this minute; try again shortly.")
    shutil.copytree(seed, backup, symlinks=False)
    try:
        copied = _copy_tree(
            staged, seed,
            skip_names={selfdev.STATE_DIRNAME, ".babymind-development-workspace.json", "apps", "dist", "build"},
        )
    except Exception:
        shutil.rmtree(seed, ignore_errors=True)
        shutil.move(str(backup), str(seed))
        raise
    selfdev.purge_bytecode(seed)
    return {
        "upgraded": True,
        "files": copied,
        "backup": str(backup),
        "notice": ("Staged source copied into the downloaded package's source seed. "
                   "Restart BabyMind to run the upgraded build. The running app was not modified."),
    }
