"""Opt-in local SQLite memory for BabyMind, encrypted at rest."""
import math
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .secure_store import SecureTextStore


MEMORY_LOCK = threading.RLock()


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

    @contextmanager
    def _connect(self):
        """Yield a serialized SQLite connection and always close its file handle.

        sqlite3.Connection's context manager commits/rolls back but does not
        close the connection; explicit close keeps temporary database handles from leaking.
        """
        with MEMORY_LOCK:
            connection = sqlite3.connect(self.database_path)
            try:
                connection.execute("PRAGMA secure_delete = ON")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

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


    def relevant(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """Return recent memories ranked by local lexical relevance, without a model call."""
        clean = " ".join(str(query).split())
        if not clean or len(clean) > 20000:
            raise ValueError("Memory search query must contain 1–20,000 characters.")
        if not 1 <= int(limit) <= 20:
            raise ValueError("Memory result limit must be between 1 and 20.")
        stop_words = {
            "about", "after", "again", "also", "and", "are", "can", "could",
            "does", "for", "from", "have", "help", "how", "into", "just",
            "more", "most", "not", "our", "please", "should", "that", "the",
            "their", "them", "then", "there", "these", "this", "those",
            "through", "was", "what", "when", "where", "which", "with", "would",
            "you", "your"
        }
        terms = {token for token in re.findall(r"[\w]{2,}", clean.casefold()) if token not in stop_words}
        if not terms:
            return self.recent(limit)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT created_at, agent_id, task, response FROM memories ORDER BY id DESC LIMIT 1000"
            ).fetchall()
        documents = [
            {
                "created_at": row[0], "agent_id": row[1],
                "task": self.secure.decrypt(row[2]), "response": self.secure.decrypt(row[3])
            }
            for row in rows
        ]
        token_sets = [
            set(re.findall(r"[\w]{2,}", (item["task"] + " " + item["response"]).casefold()))
            for item in documents
        ]
        document_frequency = {
            term: sum(1 for tokens in token_sets if term in tokens) for term in terms
        }
        ranked = []
        total = max(1, len(documents))
        for index, (item, tokens) in enumerate(zip(documents, token_sets)):
            matched = terms.intersection(tokens)
            if not matched:
                continue
            score = sum(math.log((total + 1) / (document_frequency[term] + 1)) + 1 for term in matched)
            ranked.append((score, -index, item))
        if not ranked:
            return documents[:limit]
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [entry[2] for entry in ranked[:limit]]

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories")
            return int(cursor.rowcount)
