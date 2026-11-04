"""First-launch setup for the bundled BabyMind Linux desktop app.

The llama.cpp server is installed locally. The model is
downloaded once to the user's local BabyMind data directory and verified
against the publisher's SHA-256 checksum before it can be used.
"""
from __future__ import annotations

import hashlib
import os
import queue
import shutil
import sys
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
    partial = destination.with_suffix(destination.suffix + ".part")
    if shutil.disk_usage(destination.parent).free < 4_500_000_000:
        raise RuntimeError(
            "BabyMind needs at least 4.5 GB of free disk space for the first model download."
        )

    request = urllib.request.Request(
        MODEL_URL,
        headers={"User-Agent": "BabyMind-Desktop/0.3", "Accept": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            digest = hashlib.sha256()
            with partial.open("wb") as output:
                while True:
                    if cancelled and cancelled.is_set():
                        raise InterruptedError("Model download cancelled.")
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
        actual_hash = digest.hexdigest()
        if actual_hash.lower() != MODEL_SHA256:
            raise RuntimeError(
                "The downloaded model failed its SHA-256 integrity check. "
                "The incomplete file has been discarded; please try again."
            )
        partial.replace(destination)
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            MODEL_SHA256, encoding="ascii"
        )
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _ensure_model(model_path: Path) -> None:
    from tkinter import Tk, messagebox, ttk

    marker = model_path.with_suffix(model_path.suffix + ".sha256")
    # Never trust a sidecar marker as proof of the model's contents. Re-hash
    # the actual GGUF on every startup before allowing it to reach llama.cpp.
    if model_path.is_file():
        try:
            actual_hash = _sha256(model_path).lower()
        except OSError:
            actual_hash = ""
        if actual_hash == MODEL_SHA256:
            marker.write_text(MODEL_SHA256, encoding="ascii")
            return
        model_path.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)

    root = Tk()
    root.withdraw()
    accepted = messagebox.askyesno(
        "Set up BabyMind's local AI",
        "BabyMind needs to download its first local AI model "
        f"({MODEL_SIZE_LABEL}).\n\n"
        "This is a one-time download. The model will be saved on this computer "
        "and used locally. No external model account or API key is required.\n\n"
        "Download now?",
        parent=root,
    )
    if not accepted:
        root.destroy()
        raise RuntimeError(
            "First-time model setup was cancelled. Reopen BabyMind when you are ready."
        )

    root.deiconify()
    root.title("BabyMind — Downloading local AI")
    root.geometry("500x155")
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", lambda: cancel.set())
    status = ttk.Label(root, text="Connecting to the model host…", wraplength=460)
    status.pack(padx=18, pady=(18, 8), anchor="w")
    bar = ttk.Progressbar(root, length=460, mode="determinate", maximum=100)
    bar.pack(padx=18, pady=8)
    detail = ttk.Label(root, text="The first download is approximately 2.71 GB.")
    detail.pack(padx=18, pady=(0, 12), anchor="w")

    updates: queue.Queue[tuple] = queue.Queue()
    cancel = threading.Event()
    outcome: dict[str, Exception | bool] = {}

    def worker() -> None:
        try:
            _download_model(
                model_path,
                progress=lambda done, total: updates.put(("progress", done, total)),
                cancelled=cancel,
            )
            outcome["ok"] = True
        except Exception as error:
            outcome["error"] = error
        updates.put(("finished",))

    threading.Thread(target=worker, name="BabyMindModelDownload", daemon=True).start()

    def poll() -> None:
        try:
            while True:
                item = updates.get_nowait()
                if item[0] == "progress":
                    done, total = item[1], item[2]
                    if total:
                        percent = min(100, done * 100 / total)
                        bar.configure(value=percent)
                        status.configure(text=f"Downloading model… {percent:.1f}%")
                        detail.configure(
                            text=f"{done / 1_000_000_000:.2f} / {total / 1_000_000_000:.2f} GB"
                        )
                    else:
                        status.configure(text=f"Downloaded {done / 1_000_000_000:.2f} GB…")
                elif item[0] == "finished":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        if cancel.is_set():
            status.configure(text="Cancelling download safely…")
        root.after(150, poll)

    root.after(150, poll)
    root.mainloop()
    if "error" in outcome:
        raise RuntimeError(f"BabyMind could not download its local model: {outcome['error']}")
    if not outcome.get("ok"):
        raise RuntimeError("The model download did not complete.")


def prepare_local_engine() -> None:
    """Configure the bundled CPU engine and ensure its verified model exists."""
    selected = os.getenv("BABYMIND_ENGINE", "").strip().lower()
    if selected and selected not in {"llama.cpp", "llamacpp", "llama-cpp"}:
        raise RuntimeError(f"Unknown BABYMIND_ENGINE setting: {selected}")

    app_dir = _app_directory()
    server = _find_llama_server(app_dir)
    if server is None:
        raise RuntimeError(
            "The llama.cpp runtime is missing. Set BABYMIND_LLAMA_SERVER to a valid "
            "llama-server executable or install the Linux llama.cpp runtime."
        )

    # BabyMind always uses the single bundled, SHA-256-pinned model.
    # The environment variable may relocate that exact file for packaging/tests,
    # but _ensure_model verifies its contents and replaces mismatches safely.
    configured_path = os.getenv("BABYMIND_GGUF_MODEL", "").strip()
    model_path = (
        Path(configured_path).expanduser()
        if configured_path
        else _data_home() / "models" / MODEL_FILENAME
    )
    _ensure_model(model_path)

    os.environ["BABYMIND_ENGINE"] = "llama.cpp"
    os.environ["BABYMIND_LLAMA_SERVER"] = str(server)
    os.environ["BABYMIND_GGUF_MODEL"] = str(model_path)
    os.environ.setdefault("BABYMIND_CONTEXT_SIZE", "4096")
