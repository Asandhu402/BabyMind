"""Opt-in local SQLite memory for BabyMind."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class LocalMemory:
    """Store only explicitly requested task/response memories on this device."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            home = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind"))
            home.mkdir(parents=True, exist_ok=True)
            database_path = home / "memory.sqlite3"
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    response TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def remember(self, agent_id: str, task: str, response: str) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (created_at, agent_id, task, response) "
                "VALUES (?, ?, ?, ?)",
                (created_at, agent_id, task, response),
            )

    def recent(self, limit: int = 5) -> list[dict[str, str]]:
        if limit < 1:
            raise ValueError("Memory limit must be at least 1.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT created_at, agent_id, task, response "
                "FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "created_at": row[0],
                "agent_id": row[1],
                "task": row[2],
                "response": row[3],
            }
            for row in rows
        ]

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories")
            return int(cursor.rowcount)
