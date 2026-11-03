"""Opt-in local SQLite memory for BabyMind, encrypted at rest."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .secure_store import SecureTextStore


class LocalMemory:
    """Store explicitly requested task/response memories encrypted on this device."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            home = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind"))
            home.mkdir(parents=True, exist_ok=True)
            database_path = home / "memory.sqlite3"
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.secure = SecureTextStore(self.database_path.with_suffix(".key"))
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
            # Upgrade older plaintext rows without changing their IDs or order.
            rows = connection.execute(
                "SELECT id, task, response FROM memories"
            ).fetchall()
            for memory_id, task, response in rows:
                encrypted_task = self.secure.encrypt(task)
                encrypted_response = self.secure.encrypt(response)
                if encrypted_task != task or encrypted_response != response:
                    connection.execute(
                        "UPDATE memories SET task=?, response=? WHERE id=?",
                        (encrypted_task, encrypted_response, memory_id),
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def remember(self, agent_id: str, task: str, response: str) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (created_at, agent_id, task, response) VALUES (?, ?, ?, ?)",
                (created_at, agent_id, self.secure.encrypt(task), self.secure.encrypt(response)),
            )

    def recent(self, limit: int = 5) -> list[dict[str, str]]:
        if limit < 1:
            raise ValueError("Memory limit must be at least 1.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT created_at, agent_id, task, response FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "created_at": row[0],
                "agent_id": row[1],
                "task": self.secure.decrypt(row[2]),
                "response": self.secure.decrypt(row[3]),
            }
            for row in rows
        ]

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories")
            return int(cursor.rowcount)
