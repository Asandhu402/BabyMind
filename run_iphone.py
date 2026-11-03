"""Portable console entry point for secure same-Wi-Fi iPhone access.

The portable Windows package includes its own Python runtime and llama.cpp.
Prepare the same verified local model as the desktop app, then start the
existing token-protected HTTPS LAN server.
"""
from __future__ import annotations

import sys


def main() -> None:
    from babymind.first_run import prepare_local_engine

    prepare_local_engine()

    # Force authenticated HTTPS LAN mode; preserve optional user arguments
    # such as --port while preventing accidental loopback-only startup.
    sys.argv = [sys.argv[0], "--lan", *sys.argv[1:]]

    from babymind.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
