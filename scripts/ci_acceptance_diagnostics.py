#!/usr/bin/env python3
"""Expose the tail of an opt-in CI acceptance step as a check annotation."""
import sys
from pathlib import Path


def annotation(path: Path, label: str, status: str) -> str:
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace", newline="") as log:
            text = log.read()[-8000:]
    else:
        text = "Log unavailable."
    # GitHub workflow-command data must escape these three characters.
    data = f"{label} failed with status {status}.\n{text}"
    data = data.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=Ubuntu acceptance test::{data}"


if __name__ == "__main__":
    print(annotation(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
