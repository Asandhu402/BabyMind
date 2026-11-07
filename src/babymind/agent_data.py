"""Inspect and delete stored agent, role, mission and review records.

BabyMind now has exactly one identity (BM-01), and the 50-role catalogue, the
mission orchestrator and the development-review feature have been removed. This
module lets an installation clear the data those features left behind, and
reports what is actually present instead of assuming any of it exists.

Scope and safety
----------------
- Only the tables named in :data:`PURGE_TABLES` are touched, and only rows are
  deleted: no schema is dropped, so an older version can still open the
  database.
- Deletion requires an explicit ``confirm``. ``dry_run`` lists counts and
  deletes nothing.
- Backups (``.bmbak`` archives) are **not** touched. A backup is a copy of an
  earlier state; removing rows from the live database does not rewrite it, and
  this module never claims otherwise.
- Conversation history is **not** touched. Those messages are the user's own
  records, not agent data, even though each row carries an ``agent_id`` column.
- Nothing here is reversible. There is no undo.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

# Tables that exist only to record the removed multi-role features. Ordered so a
# child table is emptied before its parent.
PURGE_TABLES = (
    "development_review_attempts",
    "development_review_roles",
    "development_reviews",
    "agent_runs",
    "missions",
)

# Never touched, listed so the report can say so explicitly.
PRESERVED = (
    "conversations",
    "messages",
    "tasks",
    "execution_proposals",
    "memories",
)


def _data_home(home: str | Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    configured = os.getenv("BABYMIND_HOME", "").strip()
    return Path(configured) if configured else Path.home() / ".babymind"


def _database_paths(home: Path) -> list[Path]:
    """Every database a BabyMind installation may keep agent data in."""
    candidates = [
        home / "app.sqlite3",
        home / "memory.sqlite3",
        home / "independence.sqlite3",
    ]
    return [path for path in candidates if path.is_file()]


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def agent_data_report(home: str | Path | None = None) -> dict[str, Any]:
    """Report which removable tables exist and how many rows each holds."""
    home_path = _data_home(home)
    database_reports: list[dict[str, Any]] = []
    total = 0
    for path in _database_paths(home_path):
        entry: dict[str, Any] = {"database": path.name, "tables": {}, "present": []}
        try:
            connection = sqlite3.connect(path, timeout=15)
            try:
                available = _tables(connection)
                for table in PURGE_TABLES:
                    if table not in available:
                        continue
                    count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    entry["tables"][table] = count
                    entry["present"].append(table)
                    total += count
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            entry["error"] = f"Could not read this database: {error}"
        database_reports.append(entry)
    return {
        "home": str(home_path),
        "identity": "BM-01 only; the 50-role catalogue was removed",
        "databases": database_reports,
        "removable_rows": total,
        "purgeable_tables": list(PURGE_TABLES),
        "preserved_tables": list(PRESERVED),
        "notes": [
            "Nothing is deleted by this report.",
            "Backups (.bmbak) and conversation history are never touched by purge.",
            "Rows are deleted; tables and schema are left in place.",
        ],
    }


def purge_agent_data(
    *, confirm: bool = False, dry_run: bool = False, home: str | Path | None = None
) -> dict[str, Any]:
    """Delete stored agent/role/mission/review rows from the live databases.

    ``dry_run`` takes precedence over ``confirm`` and deletes nothing. Otherwise
    ``confirm`` must be true or nothing happens.
    """
    home_path = _data_home(home)
    if dry_run:
        report = agent_data_report(home_path)
        return {
            "dry_run": True,
            "deleted_total": 0,
            "would_delete": report["removable_rows"],
            "databases": report["databases"],
            "note": "Dry run: nothing was deleted.",
        }
    if not confirm:
        raise PermissionError(
            "Refusing to delete records without explicit confirmation. "
            "Pass confirm=True (CLI: --confirm)."
        )

    deleted: dict[str, dict[str, int]] = {}
    total = 0
    failures: list[str] = []
    for path in _database_paths(home_path):
        counts: dict[str, int] = {}
        try:
            connection = sqlite3.connect(path, timeout=15)
            try:
                available = _tables(connection)
                for table in PURGE_TABLES:
                    if table not in available:
                        continue
                    cursor = connection.execute(f"DELETE FROM {table}")
                    counts[table] = cursor.rowcount if cursor.rowcount > 0 else 0
                connection.commit()
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            failures.append(f"{path.name}: {error}")
        if counts:
            deleted[path.name] = counts
            total += sum(counts.values())

    return {
        "dry_run": False,
        "deleted_total": total,
        "deleted": deleted,
        "failures": failures,
        "preserved": list(PRESERVED),
        "backups_untouched": True,
        "note": (
            "Deleted rows only; tables and schema remain. Backups (.bmbak) and "
            "conversation history were not modified. This cannot be undone."
        ),
    }
