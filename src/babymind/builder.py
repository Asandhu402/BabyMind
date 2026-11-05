"""Opt-in local app builder: plan a small app, write it, run it once.

BabyMind's own model turns a short brief into a set of text files. The files are
written into one dedicated folder and the generated Python entry point is run
once so the user can see whether the app actually starts.

Generated code is treated as untrusted and only executes through the shared
sandboxed runner (``runner.run_command`` with ``sandbox="require"``): Linux
user/mount/PID/network namespaces, a chrooted root with only the app folder
writable, no network, and CPU/file-size/memory/process resource limits. If no
OS sandbox backend is available, running generated code is refused outright.
What this module additionally enforces:

* Disabled unless ``BABYMIND_APP_BUILDER_ENABLED=true``.
* Writes only inside ``<root>/apps/<slug>/``; traversal, absolute paths,
  hidden paths, links, and overwriting an existing file are all refused.
* Executes only the entry point from the reviewed plan, with no shell, a
  scrubbed environment, a bounded timeout, and captured output.
* Requires the SHA-256 of the exact plan the user reviewed, so the files that
  get written are the files that were shown.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_PLAN_FILES = 40
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 512 * 1024
MAX_BRIEF_CHARS = 2_000
MAX_PATH_CHARS = 120
MAX_OUTPUT_CHARS = 20_000
BUILD_TIMEOUT_SECONDS = 60
MAX_PLAN_AGE_SECONDS = 1_800

ALLOWED_SUFFIXES = {
    ".py", ".txt", ".md", ".json", ".csv", ".html", ".css", ".js",
    ".toml", ".ini", ".cfg", ".yaml", ".yml", ".svg",
}

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_SAFE_ENV_KEYS = {
    "PATH", "TMPDIR", "HOME", "LANG", "LC_ALL", "PYTHONIOENCODING",
    "PYTHONUTF8", "NUMBER_OF_PROCESSORS",
}


class BuilderError(ValueError):
    """Raised when the app builder is disabled, misconfigured, or rejects a plan."""


@dataclass(frozen=True, slots=True)
class PlannedFile:
    path: str
    content: str

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def builder_enabled() -> bool:
    return _flag("BABYMIND_APP_BUILDER_ENABLED")


def builder_root() -> Path:
    """Return the configured, existing root that generated apps live under."""
    configured = (
        os.getenv("BABYMIND_BUILDER_ROOT", "").strip()
        or os.getenv("BABYMIND_WORKSPACE_ROOT", "").strip()
    )
    if not configured:
        raise BuilderError(
            "Set BABYMIND_BUILDER_ROOT (or BABYMIND_WORKSPACE_ROOT) to an existing folder "
            "before using the app builder."
        )
    try:
        root = Path(configured).expanduser().resolve(strict=True)
    except OSError as error:
        raise BuilderError("BABYMIND_BUILDER_ROOT must point to an existing folder.") from error
    if not root.is_dir():
        raise BuilderError("BABYMIND_BUILDER_ROOT must point to an existing folder.")
    return root


def builder_status() -> dict:
    """Report the builder's real state without creating anything on disk."""
    enabled = builder_enabled()
    root: Path | None = None
    root_error = ""
    try:
        root = builder_root()
    except BuilderError as error:
        root_error = str(error)
    apps = root / "apps" if root else None
    existing = []
    if apps and apps.is_dir():
        existing = sorted(
            item.name for item in apps.iterdir() if item.is_dir() and not item.is_symlink()
        )[:20]
    return {
        "enabled": enabled,
        "ready": enabled and root is not None,
        "root": str(root) if root else None,
        "apps_folder": str(apps) if apps else None,
        "existing_apps": existing,
        "can_write_files": enabled and root is not None,
        "can_run_generated_python": enabled and root is not None,
        "can_run_shell_commands": False,
        "sandboxed": _sandbox_available(),
        "requires_sandbox": True,
        "limits": {
            "max_files": MAX_PLAN_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
            "run_timeout_seconds": BUILD_TIMEOUT_SECONDS,
        },
        "setup": (
            "Set BABYMIND_APP_BUILDER_ENABLED=true and BABYMIND_BUILDER_ROOT to an existing "
            "folder, then restart BabyMind."
        ),
        "problem": root_error,
        "notice": (
            "Generated code is untrusted: it only runs inside the OS sandbox (namespaces, "
            "no network, resource limits) and is refused entirely when no sandbox backend is "
            "available. Files are confined to the apps folder and nothing is written before "
            "you approve the exact reviewed plan."
        ),
    }


def _sandbox_available() -> bool:
    try:
        from . import sandbox as sandboxing
        return sandboxing.available()
    except Exception:
        return False


def _require_ready() -> Path:
    if not builder_enabled():
        raise BuilderError(
            "The app builder is off. Set BABYMIND_APP_BUILDER_ENABLED=true and restart BabyMind."
        )
    return builder_root()


def slugify(name: str, fallback: str = "app") -> str:
    slug = _SLUG_PATTERN.sub("-", (name or "").strip().lower()).strip("-")
    return (slug[:40] or fallback).strip("-") or fallback


def _validate_path(raw: object) -> str:
    if not isinstance(raw, str):
        raise BuilderError("Every generated file needs a text path.")
    path = raw.strip().replace("\\", "/")
    if not path or len(path) > MAX_PATH_CHARS or "\x00" in path:
        raise BuilderError("A generated file path is empty, too long, or contains a NUL byte.")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or candidate.drive or re.match(r"^[A-Za-z]:", path):
        raise BuilderError(f"Generated paths must be relative: {path}")
    if any(":" in part for part in candidate.parts):
        raise BuilderError(f"Generated paths cannot contain drive letters or streams: {path}")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise BuilderError(f"Generated paths cannot contain '.', '..', or empty segments: {path}")
    if any(part.startswith(".") for part in candidate.parts):
        raise BuilderError(f"Generated paths cannot target hidden files or folders: {path}")
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise BuilderError(
            f"Generated file type is not allowed: {path}. "
            f"Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}"
        )
    return candidate.as_posix()


def _plan_digest(name: str, target: str, entry: str, files: list[PlannedFile]) -> str:
    canonical = json.dumps(
        {
            "name": name,
            "target": target,
            "entry": entry,
            "files": [[item.path, hashlib.sha256(item.content.encode("utf-8")).hexdigest()] for item in files],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_plan(name: str, entry: object, files: list[dict] | list[PlannedFile], *,
               summary: str = "", root: Path | None = None) -> dict:
    """Validate a model-proposed app and return the exact plan the user reviews."""
    root = root or _require_ready()
    clean_name = " ".join(str(name or "").split())[:80] or "BabyMind app"
    if not isinstance(files, list) or not files:
        raise BuilderError("The model did not propose any files.")
    if len(files) > MAX_PLAN_FILES:
        raise BuilderError(f"A generated app is limited to {MAX_PLAN_FILES} files.")

    planned: list[PlannedFile] = []
    seen: set[str] = set()
    total = 0
    for item in files:
        if isinstance(item, PlannedFile):
            raw_path, content = item.path, item.content
        elif isinstance(item, dict):
            raw_path, content = item.get("path"), item.get("content")
        else:
            raise BuilderError("Every generated file needs a path and content.")
        path = _validate_path(raw_path)
        if path in seen:
            raise BuilderError(f"The plan lists the same path twice: {path}")
        if not isinstance(content, str):
            raise BuilderError(f"File content must be text: {path}")
        if "\x00" in content:
            raise BuilderError(f"File content contains a NUL byte: {path}")
        size = len(content.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise BuilderError(f"{path} is larger than the {MAX_FILE_BYTES // 1024} KB per-file limit.")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise BuilderError(f"The plan is larger than the {MAX_TOTAL_BYTES // 1024} KB total limit.")
        seen.add(path)
        planned.append(PlannedFile(path=path, content=content))

    if entry is not None and not isinstance(entry, str):
        raise BuilderError("The entry point must be a file path or null.")
    entry_path = _validate_path(entry) if entry else ""
    if entry_path and entry_path not in seen:
        raise BuilderError("The entry point must be one of the generated files.")
    if entry_path and not entry_path.endswith(".py"):
        raise BuilderError("BabyMind only runs a generated Python entry point; choose a .py file or null.")

    slug = slugify(clean_name)
    target = f"apps/{slug}"
    app_dir = root / "apps" / slug
    if app_dir.exists():
        raise BuilderError(f"{target} already exists. Name the app something else so nothing is overwritten.")

    digest = _plan_digest(clean_name, target, entry_path, planned)
    previews = [
        {
            "path": item.path,
            "bytes": item.size,
            "lines": item.content.count("\n") + (0 if item.content.endswith("\n") else 1),
            "preview": item.content[:400] + ("…" if len(item.content) > 400 else ""),
        }
        for item in planned
    ]
    return {
        "name": clean_name,
        "summary": " ".join(str(summary or "").split())[:500],
        "slug": slug,
        "target": target,
        "app_dir": str(app_dir),
        "entry": entry_path,
        "will_run": bool(entry_path),
        "files": [{"path": item.path, "content": item.content} for item in planned],
        "file_summary": previews,
        "total_bytes": total,
        "plan_hash": digest,
    }


def verify_plan(plan: dict, approved_hash: str) -> None:
    """Refuse to act unless the approved hash matches the plan exactly."""
    if not isinstance(approved_hash, str) or not approved_hash:
        raise BuilderError("Approve the exact plan before BabyMind writes anything.")
    files = [PlannedFile(path=item["path"], content=item["content"]) for item in plan.get("files", [])]
    expected = _plan_digest(str(plan.get("name", "")), str(plan.get("target", "")),
                            str(plan.get("entry", "")), files)
    if not hmac.compare_digest(expected, str(plan.get("plan_hash", ""))):
        raise BuilderError("This plan changed after it was shown. Request a new plan.")
    if not hmac.compare_digest(expected, approved_hash):
        raise BuilderError("Approval does not match the exact plan that was shown.")


def _write_files(app_dir: Path, files: list[dict]) -> list[dict]:
    """Create the app folder and write each file, never overwriting anything."""
    root = app_dir.parent.parent
    if not app_dir.resolve().is_relative_to(root):
        raise BuilderError("Resolved app folder escaped the builder root.")
    created: list[Path] = []
    written: list[dict] = []
    try:
        for item in files:
            relative = PurePosixPath(item["path"])
            destination = app_dir / Path(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = destination.parent.resolve()
            if not resolved_parent.is_relative_to(root):
                raise BuilderError(f"{item['path']} resolves outside the builder root.")
            encoded = item["content"].encode("utf-8")
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as error:
                raise BuilderError(f"{item['path']} already exists; nothing was overwritten.") from error
            created.append(destination)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            written.append({"path": item["path"], "bytes": len(encoded)})
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return written


def _scrubbed_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in _SAFE_ENV_KEYS}


def _run_entry(app_dir: Path, entry: str) -> dict:
    """Run the generated Python entry point once through the sandboxed runner.

    Generated code is untrusted. It only ever runs via ``runner.run_command``
    with ``sandbox="require"``: if no OS sandbox backend is available, the run
    is refused (fail closed) instead of executing with the user's privileges.
    """
    if getattr(sys, "frozen", False):
        return {"ran": False, "reason": "Running generated code is unavailable in the portable app; a frozen executable is not a Python interpreter."}
    if not entry.endswith(".py"):
        return {"ran": False, "reason": "No Python entry point in this plan."}
    from . import runner
    from . import sandbox as sandboxing

    shown = f"{Path(sys.executable).name} -u {entry}"
    try:
        result = runner.run_command(
            [sys.executable, "-u", entry],
            cwd=app_dir,
            allowed_root=app_dir,
            timeout=BUILD_TIMEOUT_SECONDS,
            env=_scrubbed_environment(),
            sandbox="require",
        )
    except runner.CommandRejected as error:
        return {
            "ran": False,
            "command": shown,
            "reason": f"Refused to run generated code without an OS sandbox: {error}",
            "sandboxed": False,
        }
    return {
        "ran": True,
        "command": shown,
        "timed_out": result["timed_out"],
        "exit_code": result["exit_code"],
        "seconds": result["seconds"],
        "stdout": result["stdout"][-MAX_OUTPUT_CHARS:],
        "stderr": result["stderr"][-MAX_OUTPUT_CHARS:],
        "sandboxed": result["sandboxed"],
        "note": "Ran inside the OS sandbox (namespaces + resource limits)."
        if result["sandboxed"] else "Sandbox unavailable; run was refused.",
    }


def apply_plan(plan: dict, approved_hash: str) -> dict:
    """Write an approved plan and run its entry point once."""
    root = _require_ready()
    verify_plan(plan, approved_hash)
    app_dir = (root / plan["target"]).resolve()
    if not app_dir.is_relative_to(root.resolve()):
        raise BuilderError("The plan target is outside the builder root.")
    written = _write_files(app_dir, plan["files"])
    run = _run_entry(app_dir, plan["entry"]) if plan.get("entry") else {
        "ran": False,
        "reason": "This plan contains no Python entry point, so nothing was executed.",
    }
    return {
        "name": plan["name"],
        "target": plan["target"],
        "app_dir": str(app_dir),
        "files": written,
        "entry": plan.get("entry") or None,
        "run": run,
        "plan_hash": plan["plan_hash"],
        "notice": (
            "Files were created inside the apps folder and the entry point ran once. "
            "Generated code ran inside the OS sandbox only; review it before running it again."
        ),
    }


PLAN_SYSTEM_PROMPT = (
    "You are BabyMind's local app builder. Turn the user's brief into one small, complete, "
    "runnable application written with the Python standard library or plain HTML/CSS/JS.\n"
    "Return ONLY a single JSON object, no prose and no code fences, with this shape:\n"
    '{"name": "Short App Name", "summary": "one sentence", '
    '"entry": "app.py", "files": [{"path": "app.py", "content": "..."}]}\n'
    "Rules: 1 to 12 files; relative paths only; no '..', no hidden files, no absolute paths; "
    "allowed extensions are " + ", ".join(sorted(ALLOWED_SUFFIXES)) + "; each file under 64 KB; "
    "entry must be one of the .py files, or null for a static site. "
    "The app must run without installing anything and must not require network access. "
    "Keep the code short, readable, and working on the first try. "
    "Escape newlines inside the JSON string values correctly."
)


def parse_plan_response(raw: str) -> dict:
    """Extract the JSON object from a model response, tolerating code fences."""
    if not isinstance(raw, str) or not raw.strip():
        raise BuilderError("The local model returned an empty plan.")
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise BuilderError("The local model did not return a JSON plan. Try a more specific brief.")
    try:
        plan = json.loads(text[start:end + 1])
    except json.JSONDecodeError as error:
        raise BuilderError(
            "The local model's plan was not valid JSON. Try a shorter brief and plan again."
        ) from error
    if not isinstance(plan, dict):
        raise BuilderError("The local model did not return a JSON object.")
    return plan


def create_plan(brief: str, provider, *, name_hint: str = "") -> dict:
    """Ask BabyMind's own local model for an app plan, then validate it."""
    root = _require_ready()
    clean_brief = " ".join(str(brief or "").split())
    if len(clean_brief) < 3:
        raise BuilderError("Describe the app you want in at least a few words.")
    if len(clean_brief) > MAX_BRIEF_CHARS:
        raise BuilderError(f"The brief must be {MAX_BRIEF_CHARS:,} characters or fewer.")
    prompt = "APP BRIEF:\n" + clean_brief
    if name_hint.strip():
        prompt += "\n\nUse this app name: " + " ".join(name_hint.split())[:80]
    response = provider.complete(PLAN_SYSTEM_PROMPT, prompt)
    proposal = parse_plan_response(response)
    return build_plan(
        str(proposal.get("name") or name_hint or "BabyMind app"),
        proposal.get("entry"),
        proposal.get("files") or [],
        summary=str(proposal.get("summary") or ""),
        root=root,
    )
