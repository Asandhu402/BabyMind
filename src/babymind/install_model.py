"""Install the desktop's pinned model from a terminal, without Qt."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .first_run import MODEL_FILENAME, MODEL_SIZE_LABEL, _data_home, _download_model, _ensure_model


def main() -> int:
    configured = os.getenv("BABYMIND_GGUF_MODEL", "").strip()
    path = Path(configured).expanduser() if configured else _data_home() / "models" / MODEL_FILENAME
    print(f"Model location: {path}", flush=True)
    print(f"Checking local model (download size {MODEL_SIZE_LABEL} if missing)...", flush=True)

    def download(destination: Path) -> None:
        last_report = -1

        def progress(done: int, total: int) -> None:
            nonlocal last_report
            # Do not flood terminals and logs with every chunk.
            report = done // (128 * 1024 * 1024)
            if report != last_report or (total and done == total):
                last_report = report
                suffix = f" / {total / 1e9:.2f} GB" if total else ""
                print(f"Downloaded {done / 1e9:.2f}{suffix}", flush=True)

        _download_model(destination, progress=progress)

    try:
        _ensure_model(path, downloader=download)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Model setup failed: {error}", file=sys.stderr)
        return 1
    print("Model SHA-256 verified.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
