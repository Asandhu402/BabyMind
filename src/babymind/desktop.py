"""Native-window launcher for BabyMind on Windows.

The local HTTP server stays bound to loopback. pywebview supplies the desktop
window; all chat/model work remains in the existing BabyMind runtime.
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from http.server import ThreadingHTTPServer

import webview

from .server import DATA_HOME, Handler, init_db


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    """Start BabyMind in a standalone desktop window."""
    init_db()
    port = _available_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="BabyMindLocalServer",
        daemon=True,
    )
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    # Wait briefly for the local server before creating the desktop window.
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=0.25):
                break
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)

    print("BabyMind desktop is running.")
    print(f"Local data folder: {DATA_HOME}")
    print("The server is bound to this computer only.")

    try:
        webview.create_window(
            "BabyMind",
            url,
            width=1280,
            height=820,
            min_size=(900, 620),
            text_select=True,
        )
        webview.start()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
