"""Expose Qt smoke-test failure details in a GitHub check annotation.

The Actions log storage can be inaccessible even while the check API works.
Annotations are deliberately bounded and are only emitted on test failure.
"""
import re
import sys
from pathlib import Path


INTERESTING = re.compile(
    r"error|fail|fatal|abort|traceback|exception|signal|cannot|could not|not found|segmentation",
    re.IGNORECASE,
)


def annotation(log: str, status: str) -> str:
    lines = log.splitlines()
    matches = [line for line in lines if INTERESTING.search(line)]
    details = "\n".join(matches[-60:] if matches else lines[-60:])[-24000:]
    message = f"Qt GUI smoke test exited {status}. Diagnostic lines:\n{details or '(log was empty)'}"
    # GitHub workflow-command escaping prevents injected workflow commands.
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=Qt GUI smoke test::{escaped}"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: ci_gui_diagnostics.py LOG EXIT_CODE")
    try:
        log = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        log = f"Could not read the GUI log: {error}"
    print(annotation(log, sys.argv[2]))


if __name__ == "__main__":
    main()
