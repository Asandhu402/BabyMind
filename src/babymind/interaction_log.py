"""Interaction log: every /api/ call and uncaught client error, with outcome.

BabyMind records **metadata only**: method, path (query string stripped),
HTTP status, wall-clock duration, and the error text the server produced.
Request and response bodies are never recorded, so chat messages, attachments
and saved memories are not copied into this log.

Entries are appended to ``<data home>/interactions.jsonl`` (one JSON object per
line) so the log survives a crash of the app itself, and mirrored in memory
when the module is used through the server. ``export_report`` renders the log
as a paste-able markdown report for support: BabyMind version, platform,
Python, the data-home path, and the newest entries with their error details.

The log is local, unencrypted, and readable by the user's account. Treat it
like any other local diagnostic file: review it before pasting it anywhere.
"""
from __future__ import annotations

import json
import os
import platform
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_ENTRIES = 500
MAX_FILE_BYTES = 256 * 1024
MAX_REPORT_ENTRIES = 100
MAX_ERROR_CHARS = 500

_LOCK = threading.RLock()


def log_path(home: Path) -> Path:
    return Path(home) / "interactions.jsonl"


def _clean_error(text: object) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    if not collapsed:
        return None
    return collapsed[:MAX_ERROR_CHARS]


def _iter_entries(home: Path) -> list[dict]:
    """Return every parsed entry in the log (uncapped)."""
    path = log_path(home)
    entries = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except FileNotFoundError:
        return []
    return entries


def _read_entries(home: Path) -> list[dict]:
    return _iter_entries(home)[-MAX_FILE_ENTRIES:]


def _trim(path: Path, entries: list[dict]) -> None:
    keep = entries[-MAX_FILE_ENTRIES:]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for entry in keep:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def record(home: Path, *, kind: str, method: str, path: str, status: int,
           duration_ms: float | None = None, error: object = None,
           detail: object = None, ok: bool | None = None) -> dict:
    """Append one interaction to the log and return the stored entry."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    clean_error = _clean_error(error)
    if ok is None:
        ok = int(status) < 400 and clean_error is None
    entry = {
        "id": secrets.token_urlsafe(8),
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        "method": (method or "?").upper()[:10],
        "path": (path or "").split("?", 1)[0][:300],
        "status": int(status),
        "ok": bool(ok),
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "error": clean_error,
        "detail": _clean_error(detail),
    }
    path_out = log_path(home)
    with _LOCK:
        with path_out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            over_bytes = path_out.stat().st_size > MAX_FILE_BYTES
        except OSError:
            over_bytes = False
        entries = _iter_entries(home)
        if over_bytes or len(entries) > MAX_FILE_ENTRIES:
            try:
                _trim(path_out, entries)
            except OSError:
                pass
    return entry


def recent(home: Path, limit: int = 100) -> list[dict]:
    """Return up to ``limit`` newest entries, oldest first."""
    home = Path(home)
    try:
        limit = max(1, min(int(limit), MAX_FILE_ENTRIES))
    except (TypeError, ValueError):
        limit = 100
    with _LOCK:
        entries = _read_entries(home)
    return entries[-limit:]


def clear(home: Path) -> int:
    """Delete the log; return how many entries were removed."""
    home = Path(home)
    with _LOCK:
        entries = _iter_entries(home)
        try:
            log_path(home).unlink()
        except FileNotFoundError:
            pass
    return len(entries)


def export_report(home: Path, *, version: str, limit: int = MAX_REPORT_ENTRIES) -> str:
    """Render a ready-to-paste markdown diagnostics report."""
    home = Path(home)
    entries = recent(home, limit)
    errors = sum(1 for entry in entries if not entry.get("ok"))
    lines = [
        "## BabyMind diagnostics report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- BabyMind: {version}",
        f"- Platform: {platform.platform()}",
        f"- Python: {platform.python_version()} ({platform.machine()})",
        f"- Data home: {home}",
        f"- Entries: {len(entries)} ({errors} with errors, newest last)",
        "",
        "Error text is included verbatim from the server; no chat content or",
        "request/response bodies are recorded in this log.",
        "",
        "### Interactions",
        "",
    ]
    if not entries:
        lines.append("(no interactions recorded yet)")
    for entry in entries:
        duration = entry.get("duration_ms")
        duration_text = f" · {duration} ms" if duration is not None else ""
        outcome = "ok" if entry.get("ok") else f"ERROR {entry.get('status')}"
        lines.append(
            f"- {entry.get('time', '?')} `{entry.get('method', '?')} {entry.get('path', '?')}` → {outcome}{duration_text}"
        )
        if entry.get("error"):
            lines.append(f"  - error: {entry['error']}")
        if entry.get("detail"):
            lines.append(f"  - detail: {entry['detail']}")
    lines.append("")
    return "\n".join(lines)
