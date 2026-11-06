#!/usr/bin/env python3
"""Expose the tail of a CI acceptance step as a check annotation."""
import re
import sys
from pathlib import Path


def annotation(path: Path, label: str, status: str) -> str:
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace", newline="") as log:
            content = log.read()
            text = content[-2400:]
            if label == "Source tests":
                failures = re.findall(r"(?ms)^={10,}\n(?:FAIL|ERROR):.*?(?=^={10,}\n|^-{10,}\nRan \d+ test)", content)
                if failures:
                    text = "\n".join(failures)[-4500:]
                else:
                    # Concurrent test output can interrupt separator lines.
                    # Preserve the traceback even when it is not at line start.
                    positions = [match.start() for match in re.finditer(r"(?:FAIL|ERROR): ", content)]
                    if positions:
                        start = positions[-1]
                        text = content[start:start + 4500]
    else:
        text = "Log unavailable."
    # GitHub workflow-command data must escape these three characters.
    data = f"{label} failed with status {status}.\n{text}"
    data = data.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=Ubuntu acceptance test::{data}"


if __name__ == "__main__":
    print(annotation(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
