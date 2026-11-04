"""Bounded local command execution for BabyMind's development engine.

This is a controlled subprocess runner, not an operating-system sandbox. It
enforces an executable allowlist, a working-directory boundary, a scrubbed
environment, output caps, a timeout, and process-tree termination. It cannot
guarantee that the child is contained if the child itself escapes, and it does
not restrict network access. ``isolation_report()`` says exactly that.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

MAX_ARGUMENTS = 64
MAX_ARGUMENT_CHARS = 500
MAX_OUTPUT_CHARS = 40_000
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900
MIN_TIMEOUT = 1

# Callers may extend this list explicitly; see runner_status() for the truth.
DEFAULT_ALLOWLIST = {
    "python", "python3", "python.exe", "python3.exe", "py", "py.exe",
    "node", "node.exe", "npm", "npm.cmd", "npx",
    "git", "git.exe", "cmake", "cmake.exe", "ctest", "ctest.exe",
    "pytest", "pytest.exe",
}

_ENV_PASSTHROUGH = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LANG", "LC_ALL", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
    "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PYTHONIOENCODING",
    "PYTHONUTF8", "VIRTUAL_ENV", "SYSTEMDRIVE",
}


class CommandRejected(ValueError):
    """Raised when a command is outside the runner's policy."""


def allowlist() -> set[str]:
    extra = os.getenv("BABYMIND_RUNNER_ALLOWLIST", "").replace(";", ",").split(",")
    return DEFAULT_ALLOWLIST | {item.strip().lower() for item in extra if item.strip()}


def unrestricted() -> bool:
    return os.getenv("BABYMIND_RUNNER_UNRESTRICTED", "").strip().lower() in {"1", "true", "yes"}


def runner_status() -> dict:
    return {
        "executable_allowlist": sorted(allowlist()),
        "unrestricted": unrestricted(),
        "timeout_seconds": {"default": DEFAULT_TIMEOUT, "max": MAX_TIMEOUT},
        "max_output_chars": MAX_OUTPUT_CHARS,
        "environment": "scrubbed to a fixed allowlist of non-secret variables",
        "working_directory": "must be inside the caller's allowed root",
        "isolation": isolation_report(),
    }


def isolation_report() -> dict:
    """Describe the containment that is actually enforced on this platform."""
    windows = sys.platform == "win32"
    return {
        "os_sandbox": False,
        "filesystem_containment": "none at OS level; the working directory is validated before launch",
        "network_isolation": False,
        "cpu_memory_limits": "posix rlimits (CPU, file size, open files)" if not windows
        else "not available without a Job Object; reported as unenforced",
        "process_tree_kill": "process group" if not windows else "taskkill /T",
        "environment_scrubbed": True,
        "note": (
            "A same-user subprocess is not a security boundary. Untrusted or generated code that "
            "must be contained needs an OS sandbox, which this project has not implemented."
        ),
    }


def _validate_arguments(argv: list[str]) -> list[str]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise CommandRejected("A command must be a non-empty argument list.")
    if len(argv) > MAX_ARGUMENTS:
        raise CommandRejected(f"Commands are limited to {MAX_ARGUMENTS} arguments.")
    clean: list[str] = []
    for item in argv:
        if not isinstance(item, str) or "\x00" in item:
            raise CommandRejected("Command arguments must be plain strings.")
        if len(item) > MAX_ARGUMENT_CHARS:
            raise CommandRejected(f"Command arguments are limited to {MAX_ARGUMENT_CHARS} characters.")
        clean.append(item)
    return clean


def _resolve_executable(argv: list[str]) -> str:
    program = argv[0]
    name = Path(program).name.lower()
    if not unrestricted() and name not in allowlist():
        raise CommandRejected(
            f"'{Path(program).name}' is not in the executable allowlist. "
            "Add it to BABYMIND_RUNNER_ALLOWLIST if this is intentional."
        )
    resolved = shutil.which(program)
    if resolved is None and os.path.isfile(program):
        resolved = os.path.abspath(program)
    if resolved is None:
        raise CommandRejected(f"Executable not found: {program}")
    return resolved


def _resolve_cwd(cwd: str | Path | None, allowed_root: str | Path | None) -> Path:
    working = Path(cwd).expanduser() if cwd else Path.cwd()
    try:
        working = working.resolve(strict=True)
    except OSError as error:
        raise CommandRejected(f"Working directory does not exist: {working}") from error
    if not working.is_dir():
        raise CommandRejected(f"Working directory is not a directory: {working}")
    if allowed_root is not None:
        root = Path(allowed_root).expanduser().resolve()
        if not working.is_relative_to(root):
            raise CommandRejected("The working directory must stay inside the allowed root.")
    return working


def _scrubbed_environment(extra: dict[str, str] | None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _ENV_PASSTHROUGH}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUTF8"] = "1"
    for key, value in (extra or {}).items():
        if any(token in key.upper() for token in ("TOKEN", "SECRET", "PASSWORD", "KEY", "API")):
            continue
        env[str(key)] = str(value)
    return env


def _limits() -> None:
    """Best-effort POSIX limits for the child process."""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return
    for limit, value in (
        (getattr(resource, "RLIMIT_CPU", None), 300),
        (getattr(resource, "RLIMIT_FSIZE", None), 64 * 1024 * 1024),
        (getattr(resource, "RLIMIT_NOFILE", None), 256),
    ):
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            process.kill()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def run_command(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    allowed_root: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict:
    """Run one allowlisted command and return a structured result."""
    try:
        seconds = int(timeout)
    except (TypeError, ValueError) as error:
        raise CommandRejected("Timeout must be an integer number of seconds.") from error
    if not MIN_TIMEOUT <= seconds <= MAX_TIMEOUT:
        raise CommandRejected(f"Timeout must be between {MIN_TIMEOUT} and {MAX_TIMEOUT} seconds.")

    clean = _validate_arguments(list(argv))
    executable = _resolve_executable(clean)
    working = _resolve_cwd(cwd, allowed_root)
    command = [executable, *clean[1:]]

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(working),
        env=_scrubbed_environment(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=sys.platform != "win32",
        preexec_fn=_limits if sys.platform != "win32" else None,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ) if sys.platform == "win32" else 0,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            stdout, stderr = "", ""
    duration = round(time.monotonic() - started, 2)
    return {
        "argv": clean,
        "cwd": str(working),
        "exit_code": None if timed_out else process.returncode,
        "timed_out": timed_out,
        "seconds": duration,
        "timeout_seconds": seconds,
        "stdout": (stdout or "")[-MAX_OUTPUT_CHARS:],
        "stderr": (stderr or "")[-MAX_OUTPUT_CHARS:],
        "truncated": len(stdout or "") > MAX_OUTPUT_CHARS or len(stderr or "") > MAX_OUTPUT_CHARS,
        "ok": (not timed_out) and process.returncode == 0,
    }


def venv_python() -> str:
    """Interpreter used for BabyMind's own test and compile commands."""
    return sys.executable


def run_unit_tests(root: str | Path, *, timeout: int = 300) -> dict:
    """Run the repository's unittest suite from a source checkout."""
    root = Path(root).resolve()
    # unittest requires the discovery start directory to be importable when the
    # top-level directory is its parent; otherwise it must be made the top level.
    top = "." if (root / "tests" / "__init__.py").is_file() else "tests"
    result = run_command(
        [venv_python(), "-m", "unittest", "discover", "-s", "tests", "-t", top],
        cwd=root,
        allowed_root=root,
        timeout=timeout,
        env={"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    result["summary"] = _summarise_unittest(result)
    return result


def run_compile_check(root: str | Path, *, timeout: int = 120) -> dict:
    root = Path(root).resolve()
    return run_command(
        [venv_python(), "-m", "compileall", "-q", "src", "tests"],
        cwd=root, allowed_root=root, timeout=timeout,
    )


def _summarise_unittest(result: dict) -> dict:
    import re

    text = (result.get("stderr") or "") + (result.get("stdout") or "")
    ran = failures = errors = skipped = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Ran ") and " test" in stripped:
            match = re.search(r"Ran (\d+) tests?", stripped)
            if match:
                ran = int(match.group(1))
        for name, value in re.findall(r"(failures|errors|skipped)=(\d+)", stripped):
            if name == "failures":
                failures = int(value)
            elif name == "errors":
                errors = int(value)
            else:
                skipped = int(value)
    problems = failures + errors
    return {
        "ran": ran,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "problems": problems,
        # A suite that ran nothing but failed is an import or startup failure.
        "passed": problems == 0 and bool(result.get("ok")),
    }
