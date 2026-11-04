"""First-launch setup for the bundled BabyMind Linux desktop app.

The llama.cpp executable is bundled with the Linux package. The model is
downloaded once to the user's local BabyMind data directory and verified
against a pinned SHA-256 checksum before it can be used.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable

MODEL_URL = (
    "https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/resolve/55e05aba5a4e1e2d6c4919753a68941c4ad4cb11/"
    "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf?download=true"
)
MODEL_FILENAME = "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
MODEL_SHA256 = (
    "79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741"
)
MODEL_SIZE_LABEL = "approximately 2.71 GB"
CHUNK_SIZE = 4 * 1024 * 1024
MAX_MODEL_DOWNLOAD_BYTES = 3_500_000_000


def _data_home() -> Path:
    configured = os.getenv("BABYMIND_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".babymind"


def _app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _find_llama_server(app_dir: Path) -> Path | None:
    configured = os.getenv("BABYMIND_LLAMA_SERVER", "").strip()
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    bundled = app_dir / "llama.cpp" / "llama-server"
    if bundled.is_file():
        return bundled
    runtime_dir = app_dir / "llama.cpp"
    if runtime_dir.is_dir():
        return next(runtime_dir.rglob("llama-server"), None)
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_model(
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
    cancelled: threading.Event | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < 4_500_000_000:
        raise RuntimeError(
            "BabyMind needs at least 4.5 GB of free disk space for the first model download."
        )

    # A unique private partial file avoids overwriting any unrelated .part file.
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    os.close(fd)
    partial = Path(name)
    request = urllib.request.Request(
        MODEL_URL,
        headers={"User-Agent": "BabyMind-Desktop/0.3", "Accept": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0") or 0)
            if total < 0 or total > MAX_MODEL_DOWNLOAD_BYTES:
                raise RuntimeError("Model download exceeds the allowed size limit.")
            downloaded = 0
            digest = hashlib.sha256()
            with partial.open("wb") as output:
                while True:
                    if cancelled and cancelled.is_set():
                        raise InterruptedError("Model download cancelled.")
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_MODEL_DOWNLOAD_BYTES:
                        raise RuntimeError("Model download exceeds the allowed size limit.")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(downloaded, total)
        actual_hash = digest.hexdigest()
        if actual_hash.lower() != MODEL_SHA256:
            raise RuntimeError(
                "The downloaded model failed its SHA-256 integrity check. "
                "The incomplete file has been discarded; please try again."
            )
        # Publish without overwriting a file that appeared during the download.
        # Both paths share a directory/filesystem, so the link is atomic.
        try:
            os.link(partial, destination)
        except FileExistsError as error:
            raise RuntimeError("The model path appeared during download; it was not overwritten.") from error
        partial.unlink()
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _ensure_model(
    model_path: Path, downloader: Callable[[Path], None] | None = None,
    verifier: Callable[[Path], str] | None = None,
) -> None:
    # A sidecar marker is not evidence: verify the file itself every time.
    verifier = verifier or _sha256
    if model_path.is_file():
        if verifier(model_path).lower() == MODEL_SHA256:
            return
        raise RuntimeError(
            f"The existing model at {model_path} does not match BabyMind's pinned "
            "SHA-256. It was not deleted. Move it elsewhere or choose another "
            "BABYMIND_GGUF_MODEL path, then restart."
        )
    if downloader is None:
        raise RuntimeError("First-time model setup requires the BabyMind desktop window.")
    downloader(model_path)
    # Do not trust the callback or marker, either.
    if not model_path.is_file() or verifier(model_path).lower() != MODEL_SHA256:
        raise RuntimeError("Model download did not produce the verified pinned model.")


def prepare_local_engine(
    downloader: Callable[[Path], None] | None = None,
    verifier: Callable[[Path], str] | None = None,
) -> None:
    """Configure the bundled CPU engine and ensure its verified model exists."""
    selected = os.getenv("BABYMIND_ENGINE", "").strip().lower()
    if selected and selected not in {"llama.cpp", "llamacpp", "llama-cpp"}:
        raise RuntimeError(f"Unknown BABYMIND_ENGINE setting: {selected}")

    app_dir = _app_directory()
    server = _find_llama_server(app_dir)
    if server is None:
        raise RuntimeError(
            "The llama.cpp runtime is missing. Set BABYMIND_LLAMA_SERVER to a valid "
            "llama-server executable or download the complete BabyMind Linux package."
        )

    # BabyMind always uses the single bundled, SHA-256-pinned model.
    # The environment variable may relocate that exact file for packaging/tests,
    # and _ensure_model verifies its contents without deleting mismatches.
    configured_path = os.getenv("BABYMIND_GGUF_MODEL", "").strip()
    model_path = (
        Path(configured_path).expanduser()
        if configured_path
        else _data_home() / "models" / MODEL_FILENAME
    )
    _ensure_model(model_path, downloader, verifier or _sha256)

    os.environ["BABYMIND_ENGINE"] = "llama.cpp"
    os.environ["BABYMIND_LLAMA_SERVER"] = str(server)
    os.environ["BABYMIND_GGUF_MODEL"] = str(model_path)
    os.environ.setdefault("BABYMIND_CONTEXT_SIZE", "4096")
