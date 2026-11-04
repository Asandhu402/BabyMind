"""Portable console entry point for secure same-Wi-Fi iPhone access.

Run this companion on the Linux host that runs BabyMind and the local model.
It starts the existing token-protected HTTPS LAN server for trusted local devices.
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
