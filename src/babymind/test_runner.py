"""Fixed-command test runner bundled for approval-gated project checks."""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a project's Python unittest suite.")
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve(strict=True)
    tests_dir = root / "tests"
    if tests_dir.is_symlink() or not tests_dir.is_dir():
        print("The selected project must contain an existing, non-symlink tests folder.", file=sys.stderr)
        return 2
    if not tests_dir.resolve(strict=True).is_relative_to(root):
        print("The tests folder must remain inside the selected project.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(tests_dir),
        pattern="test*.py",
        top_level_dir=str(root),
    )
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
