"""Record the real BabyMind local web UI against a local llama.cpp model.

The recorder owns the web-server subprocess so startup failures are captured and
reported instead of being hidden by a detached PowerShell Start-Process.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts"
OUT.mkdir(exist_ok=True)
BASE_URL = "http://127.0.0.1:8765"


def wait_for_server(process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 90
    last_error = "server has not answered yet"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError(
                f"BabyMind web server exited with code {process.returncode}. "
                f"Server log:\\n{detail[-12000:]}"
            )
        try:
            with urlopen(f"{BASE_URL}/api/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError) as error:
            last_error = str(error)
        time.sleep(1)
    detail = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise RuntimeError(
        f"BabyMind web server did not become ready: {last_error}. "
        f"Server log:\\n{detail[-12000:]}"
    )


def main() -> None:
    env = os.environ.copy()
    env.update({
        "BABYMIND_ENGINE": "llama.cpp",
        "BABYMIND_LLAMA_SERVER": env["BABYMIND_DEMO_LLAMA"],
        "BABYMIND_GGUF_MODEL": env["BABYMIND_DEMO_MODEL"],
        "BABYMIND_CONTEXT_SIZE": "2048",
        "BABYMIND_HOME": str(Path(os.environ["RUNNER_TEMP"]) / "babymind-demo-data"),
        "PYTHONUNBUFFERED": "1",
    })
    log_path = Path(os.environ["RUNNER_TEMP"]) / "babymind-ui-server.log"
    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "babymind.server", "--host", "127.0.0.1", "--port", "8765", "--no-browser"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_server(server, log_path)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 960},
                    device_scale_factor=1,
                    record_video_dir=str(OUT),
                    record_video_size={"width": 1440, "height": 960},
                )
                page = context.new_page()
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.screenshot(path=str(OUT / "01-chat-home.png"), full_page=True)

                # Show the searchable specialist directory.
                page.locator('[data-view="agents"]').click()
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / "02-agent-directory.png"), full_page=True)

                # Ask the running local model a real question through the UI.
                page.locator('[data-view="chat"]').click()
                page.locator("#messageInput").fill(
                    "For this interface demo, reply in two short sentences: introduce yourself as BabyMind and explain that you have specialist roles."
                )
                page.locator("#sendButton").click()
                page.locator("#typingIndicator").wait_for(state="visible", timeout=15000)
                page.locator("#typingIndicator").wait_for(state="hidden", timeout=240000)
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / "03-live-model-chat.png"), full_page=True)

                # Show memory and settings areas.
                page.locator('[data-view="memory"]').click()
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / "04-memory.png"), full_page=True)
                page.locator("#settingsButton").click()
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / "05-settings.png"), full_page=True)

                context.close()
                video_path = page.video.path()
                browser.close()
                if not Path(video_path).is_file() or Path(video_path).stat().st_size < 100_000:
                    raise RuntimeError(f"Browser recording is missing or unexpectedly small: {video_path}")
                shutil.copy2(video_path, OUT / "BabyMind-UI-Demo.webm")
                print(f"Recorded actual BabyMind UI video ({Path(video_path).stat().st_size} bytes).")
        except PlaywrightTimeoutError as error:
            raise RuntimeError(f"Browser UI timed out: {error}") from error
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
