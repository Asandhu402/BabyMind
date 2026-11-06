"""Bounded local command execution for BabyMind's development engine.

This is a controlled subprocess runner, not an operating-system sandbox. It
enforces an executable allowlist, a working-directory boundary, a scrubbed
environment, output caps, a timeout, and process-tree termination. It cannot
guarantee that the child is contained if the child itself escapes, and it does
not restrict network access. ``isolation_report()`` says exactly that.
"""
from __future__ import annotations

import json
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

# Discovery is driven by a generated helper rather than "-m unittest" so that the
# set of failing tests is captured as data. The console tail is capped above and
# kept from the end, so on a suite with many failures the earliest FAIL:/ERROR:
# headings are lost -- which made "did this suite actually run?" undecidable.
_DRIVER_NAME = ".babymind-unittest-driver.py"
_REPORT_NAME = ".babymind-unittest-report.json"

_UNITTEST_DRIVER = '''"""Run unittest discovery and record failing test ids as data.

Written into the checkout by runner.run_unit_tests and removed afterwards. The
console output is unchanged; the report exists so callers never have to
reconstruct the failing set from a truncated tail.
"""
import json
import os
import sys
import unittest


class _RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.problem_ids = []

    def _record(self, test):
        # getDescription() is exactly what unittest prints after "FAIL:"/"ERROR:",
        # so recorded ids stay comparable with ids scraped from older output.
        self.problem_ids.append(self.getDescription(test))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test)

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test)


def main() -> int:
    top = sys.argv[1] if len(sys.argv) > 1 else "tests"
    suite = unittest.defaultTestLoader.discover(start_dir="tests", top_level_dir=top)
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1, resultclass=_RecordingResult)
    result = runner.run(suite)
    target = os.environ.get("BABYMIND_TEST_REPORT") or ""
    if target:
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(sorted(result.problem_ids), handle)
    return 0 if result.wasSuccessful() else 1


raise SystemExit(main())
'''

# Callers may extend this list explicitly; see runner_status() for the truth.
DEFAULT_ALLOWLIST = {"python", "python3", "node", "npm", "npx", "git", "cmake", "ctest", "pytest"}

_ENV_PASSTHROUGH = {
    "PATH", "TMPDIR", "HOME", "LANG", "LC_ALL", "PYTHONIOENCODING",
    "PYTHONUTF8", "VIRTUAL_ENV",
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
        "os_sandbox": __import__("babymind.sandbox", fromlist=["status"]).status(),
    }


def isolation_report() -> dict:
    """Describe the containment that is actually enforced on this platform."""
    return {
        "os_sandbox": False,
        "filesystem_containment": "none at OS level; the working directory is validated before launch",
        "network_isolation": False,
        "cpu_memory_limits": "posix rlimits (CPU, file size, open files)",
        "process_tree_kill": "process group",
        "environment_scrubbed": True,
        "note": (
            "A same-user subprocess is not a security boundary. Untrusted or generated code that "
            "must be contained needs an OS sandbox, which must be explicitly required and independently verified."
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
    resolved = shutil.which(program)
    if resolved is None and os.path.isfile(program):
        resolved = os.path.abspath(program)
    if not unrestricted() and name not in allowlist():
        # Some Ubuntu/Python builds expose the active interpreter as
        # python3.10, python3.12, etc. Allow only the actual running interpreter,
        # not arbitrary executables that merely have a versioned Python name.
        same_interpreter = False
        if resolved and not getattr(sys, "frozen", False):
            try:
                same_interpreter = os.path.samefile(resolved, sys.executable)
            except OSError:
                pass
        if not same_interpreter:
            raise CommandRejected(
                f"'{Path(program).name}' is not in the executable allowlist. "
                "Add it to BABYMIND_RUNNER_ALLOWLIST if this is intentional."
            )
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
    except ImportError:  # pragma: no cover
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
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def _sandbox_mode(value: bool | str) -> str:
    if isinstance(value, bool):
        return "require" if value else "off"
    text = str(value or "off").strip().lower()
    if text not in {"off", "auto", "require"}:
        return "off"
    if text == "auto" and not _unsandboxed_auto_allowed():
        # "auto" must never silently downgrade untrusted execution to a
        # same-user subprocess; without an explicit opt-in it fails closed.
        return "require"
    return text


def _unsandboxed_auto_allowed() -> bool:
    return os.getenv("BABYMIND_ALLOW_UNSANDBOXED_AUTO", "").strip().lower() in {"1", "true", "yes", "on"}


def run_command(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    allowed_root: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
    sandbox: bool | str = False,
) -> dict:
    """Run one allowlisted command and return a structured result.

    ``sandbox`` is ``off``, ``auto`` (use an OS sandbox when one is available),
    or ``require`` (fail when it is not). The sandbox wraps the same command; it
    does not bypass the allowlist, the working-directory boundary, or the timeout.
    """
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
    child_env = _scrubbed_environment(env)
    if getattr(sys, "frozen", False):
        from . import packaged_dev
        if Path(executable).resolve() == packaged_dev.python_path().resolve():
            runtime_env = packaged_dev.python_environment()
            project_pythonpath = child_env.get("PYTHONPATH")
            child_env.update(runtime_env)
            if project_pythonpath:
                child_env["PYTHONPATH"] = project_pythonpath + os.pathsep + runtime_env["PYTHONPATH"]

    mode = _sandbox_mode(sandbox)
    sandboxed = False
    sandbox_cleanup: dict | None = None
    if mode != "off":
        from . import sandbox as sandboxing

        if sandboxing.available():
            command, outer_env = sandboxing.wrap(
                command, root=allowed_root or working, cwd=working, env=child_env,
            )
            child_env = outer_env
            sandbox_cleanup = outer_env
            sandboxed = True
        elif mode == "require":
            raise CommandRejected(
                "An OS sandbox is required for this command but no backend is available: "
                + sandboxing.backend().detail
            )
        else:
            mode = "unavailable"

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(working),
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
        preexec_fn=_limits,
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
    finally:
        if sandbox_cleanup is not None:
            from . import sandbox as sandboxing
            sandboxing.cleanup(command, sandbox_cleanup)
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
        "sandbox": mode,
        "sandboxed": sandboxed,
    }


def venv_python() -> str:
    """Interpreter used for BabyMind's own test and compile commands."""
    if getattr(sys, "frozen", False):
        from . import packaged_dev
        return str(packaged_dev.python_path())
    return sys.executable


def run_unit_tests(root: str | Path, *, timeout: int = 300, sandbox: bool | str = False) -> dict:
    """Run the repository's unittest suite from a source checkout."""
    root = Path(root).resolve()
    # unittest requires the discovery start directory to be importable when the
    # top-level directory is its parent; otherwise it must be made the top level.
    top = "." if (root / "tests" / "__init__.py").is_file() else "tests"
    driver = root / _DRIVER_NAME
    report = root / _REPORT_NAME
    try:
        driver.write_text(_UNITTEST_DRIVER, encoding="utf-8")
        result = run_command(
            [venv_python(), _DRIVER_NAME, top],
            cwd=root,
            allowed_root=root,
            timeout=timeout,
            env={
                "PYTHONPATH": str(root / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "BABYMIND_TEST_REPORT": _REPORT_NAME,
            },
            sandbox=sandbox,
        )
    finally:
        recorded = None
        try:
            if report.is_file():
                loaded = json.loads(report.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    recorded = [str(item) for item in loaded]
        except (OSError, ValueError):
            recorded = None  # fall back to scraping the console output
        for stray in (driver, report):
            stray.unlink(missing_ok=True)
    result["summary"] = _summarise_unittest(result)
    if recorded is not None:
        result["problem_ids"] = recorded
    return result


def run_compile_check(root: str | Path, *, timeout: int = 120, sandbox: bool | str = False) -> dict:
    root = Path(root).resolve()
    return run_command(
        [venv_python(), "-m", "compileall", "-q", "src", "tests"],
        cwd=root, allowed_root=root, timeout=timeout, sandbox=sandbox,
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
