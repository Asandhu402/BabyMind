"""Source staging workspace and Python helper for the frozen Linux desktop.

Edits affect a managed source copy only. The running frozen executable is not
rebuilt, replaced, or activated by this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
from pathlib import Path

_MARKER = ".babymind-development-workspace.json"
_LOCK = threading.Lock()


class PackagedDevelopmentError(RuntimeError):
    pass


def app_directory() -> Path:
    return Path(sys.executable).resolve().parent


def python_path() -> Path:
    runtime = app_directory() / "dev-python"
    python = runtime / "bin" / "python3"
    if runtime.is_symlink() or python.is_symlink() or not python.is_file() or not os.access(python, os.X_OK):
        raise PackagedDevelopmentError("The bundled development Python is missing or invalid.")
    return python


def python_environment() -> dict[str, str]:
    runtime = python_path().parents[1]
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return {"PYTHONHOME": str(runtime), "PYTHONNOUSERSITE": "1", "LD_LIBRARY_PATH": str(runtime / "lib"),
            "PYTHONPATH": str(runtime / "lib" / version / "site-packages")}


def _seed_fingerprint(seed: Path) -> str:
    if seed.is_symlink() or not (seed / "src" / "babymind").is_dir() or not (seed / "tests").is_dir():
        raise PackagedDevelopmentError("The bundled source seed is missing or invalid.")
    digest = hashlib.sha256()
    for directory, subdirectories, files in os.walk(seed, followlinks=False):
        subdirectories.sort()
        for name in sorted(subdirectories + files):
            if (Path(directory) / name).is_symlink():
                raise PackagedDevelopmentError("The bundled source seed contains a symbolic link.")
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(seed).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big")); digest.update(relative)
            file_hash = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    file_hash.update(chunk)
            digest.update(file_hash.digest())
    return digest.hexdigest()


def verify_packaged_staging() -> None:
    """Exercise a staged edit with the bundled helper, without a model or GUI."""
    import tempfile
    from . import runner, sandbox, selfdev

    if not getattr(sys, "frozen", False):
        raise PackagedDevelopmentError("This check must run from the packaged executable.")
    backend = sandbox.backend()
    if not backend.available:
        message = f"SKIPPED packaged source edit: OS sandbox unavailable: {backend.detail}"
        print(message)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            safe = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::warning title=Packaged staging skipped::{safe}")
        return
    with tempfile.TemporaryDirectory(prefix="babymind-packaged-check-") as home:
        old_home = os.environ.get("BABYMIND_HOME")
        old_flag = os.environ.get("BABYMIND_SELF_DEVELOPMENT_ENABLED")
        os.environ["BABYMIND_HOME"] = home
        os.environ["BABYMIND_SELF_DEVELOPMENT_ENABLED"] = "true"
        try:
            root = workspace()
            target = root / "src" / "babymind" / "__init__.py"
            original = target.read_text(encoding="utf-8")
            seed_original = (app_directory() / "dev-source-seed/src/babymind/__init__.py").read_text(encoding="utf-8")
            content = original + "\ndef _packaged_test_value():\n    return 42\n"
            result = selfdev.apply_edits([{"path": "src/babymind/__init__.py", "content": content}],
                                         reason="disposable packaged staging check")
            if (result.get("status") != "applied" or not result.get("sandboxed")
                    or result.get("source_scope") != "staged-copy"
                    or not (result.get("tests") or {}).get("summary", {}).get("passed")):
                raise PackagedDevelopmentError(f"Staged self-edit did not pass: {result.get('status')} {result.get('reason', '')}")
            from . import broker
            check = broker.execute(
                [runner.venv_python(), "-c", "from babymind import _packaged_test_value; assert _packaged_test_value() == 42"],
                cwd=root, allowed_root=root, timeout=60, env={"PYTHONPATH": str(root / "src")}, sandbox_mode="require")
            if not check["ok"] or not check["sandboxed"]:
                raise PackagedDevelopmentError("Independent sandboxed staged-source behavior check failed: " + check.get("stderr", "")[-1000:])
            if (app_directory() / "dev-source-seed/src/babymind/__init__.py").read_text(encoding="utf-8") != seed_original:
                raise PackagedDevelopmentError("The packaged source seed was unexpectedly modified.")
            print("Packaged source staging passed its sandboxed edit and independent behavior test. The running app was not updated.")
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print("::notice title=Packaged staging::Sandboxed staged-source edit and independent behavior test passed; running app unchanged.")
        finally:
            for name, value in (("BABYMIND_HOME", old_home), ("BABYMIND_SELF_DEVELOPMENT_ENABLED", old_flag)):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def workspace() -> Path:
    """Create once; never replace an existing unrecognised folder or user edits."""
    seed = app_directory() / "dev-source-seed"
    python_path()
    seed_fingerprint = _seed_fingerprint(seed)
    home = Path(os.environ.get("BABYMIND_HOME") or (Path.home() / ".babymind")).expanduser()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if home.is_symlink():
        raise PackagedDevelopmentError("The BabyMind data directory cannot be a symbolic link for source staging.")
    dest = home / "development-source"
    with _LOCK:
        if not dest.exists() and not dest.is_symlink():
            try:
                dest.mkdir(mode=0o700)
            except FileExistsError:
                pass
            else:
                # An interrupted copy remains unmarked and is never overwritten.
                shutil.copytree(seed, dest, dirs_exist_ok=True, symlinks=True)
                (dest / _MARKER).write_text(json.dumps({"kind": "babymind-staged-source", "version": 1,
                                                        "seed_sha256": seed_fingerprint}), encoding="utf-8")
        marker = dest / _MARKER
        if dest.is_symlink() or not dest.is_dir() or marker.is_symlink() or not marker.is_file():
            raise PackagedDevelopmentError("Existing development-source is not a recognised workspace; it was not changed.")
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PackagedDevelopmentError("Development workspace marker is invalid; it was not changed.") from error
        if (not isinstance(info, dict) or info.get("kind") != "babymind-staged-source"
                or info.get("version") != 1 or not (dest / "src" / "babymind").is_dir()):
            raise PackagedDevelopmentError("Development workspace is incomplete or unrecognised; it was not changed.")
        if info.get("seed_sha256") != seed_fingerprint:
            raise PackagedDevelopmentError("The staged workspace is from a different package version; it was not changed.")
        return dest.resolve()
