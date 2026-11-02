"""First-launch setup for the bundled BabyMind Windows desktop app.

The llama.cpp executable is bundled with the Windows package. The model is
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
from tkinter import Tk, messagebox, ttk

MODEL_URL = (
    "https://huggingface.co/SoAIHQ/Qwen3.5-4B-GGUF/resolve/main/"
    "Qwen3.5-4B-Q4_K_M.gguf?download=true"
)
MODEL_FILENAME = "Qwen3.5-4B-Q4_K_M.gguf"
MODEL_SHA256 = (
    "2ebe6eb67cb92adeffc7073c48dd4e3baf79465ac650793dc751cad2b29cf219"
)
MODEL_SIZE_LABEL = "approximately 2.8 GB"
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
    bundled = app_dir / "llama.cpp" / "llama-server.exe"
    if bundled.is_file():
        return bundled
    runtime_dir = app_dir / "llama.cpp"
    if runtime_dir.is_dir():
        return next(runtime_dir.rglob("llama-server.exe"), None)
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_model(
    destination: Path,
    progress: callable | None = None,
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
    marker = model_path.with_suffix(model_path.suffix + ".sha256")
    if model_path.is_file() and marker.is_file():
        if marker.read_text(encoding="ascii").strip() == MODEL_SHA256:
            return
    if model_path.is_file():
        if _sha256(model_path).lower() == MODEL_SHA256:
            marker.write_text(MODEL_SHA256, encoding="ascii")
            return
        model_path.unlink()
        marker.unlink(missing_ok=True)

    root = Tk()
    root.withdraw()
    accepted = messagebox.askyesno(
        "Set up BabyMind's local AI",
        "BabyMind needs to download its first local AI model "
        f"({MODEL_SIZE_LABEL}).\n\n"
        "This is a one-time download. The model will be saved on this computer "
        "and used locally. No LM Studio account or API key is required.\n\n"
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
    detail = ttk.Label(root, text="The first download is approximately 2.8 GB.")
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
    if selected in {"lm-studio", "lmstudio"}:
        return

    app_dir = _app_directory()
    server = _find_llama_server(app_dir)
    if server is None:
        raise RuntimeError(
            "The bundled llama.cpp runtime is missing. Download the complete "
            "BabyMind Windows package again; do not move only BabyMind.exe."
        )

    model_path = Path(os.getenv("BABYMIND_GGUF_MODEL", "")).expanduser()
    if not str(model_path):
        model_path = _data_home() / "models" / MODEL_FILENAME
    _ensure_model(model_path)

    os.environ["BABYMIND_ENGINE"] = "llama.cpp"
    os.environ["BABYMIND_LLAMA_SERVER"] = str(server)
    os.environ["BABYMIND_GGUF_MODEL"] = str(model_path)
    os.environ.setdefault("BABYMIND_CONTEXT_SIZE", "4096")
