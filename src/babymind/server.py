"""Local web application server for BabyMind.

The server binds to localhost by default. LAN access is opt-in via --host 0.0.0.0.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sqlite3
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agents import AGENTS
from .coordinator import BabyMindCoordinator
from .providers import LMStudioProvider, ProviderError

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web"
DATA_HOME = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind"))
DATA_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_HOME / "app.sqlite3"
DB_LOCK = threading.Lock()
COORDINATOR = BabyMindCoordinator()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with DB_LOCK, db() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, agent_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("PRAGMA foreign_keys = ON")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Handler(BaseHTTPRequestHandler):
    server_version = "BabyMind/0.2"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[BabyMind] {self.address_string()} - {fmt % args}")

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                raise ValueError("Request body is too large.")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object.")
            return value
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Invalid JSON request.") from error

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            provider = LMStudioProvider()
            try:
                model_data = provider._request_json(f"{provider.base_url}/models")
                models = model_data.get("data", [])
                model_ready = bool(models)
                model_name = str(models[0].get("id", "Loaded model")) if models else None
            except ProviderError:
                model_ready = False
                model_name = None
            self.send_json({
                "application": "BabyMind",
                "status": "ready" if model_ready else "waiting_for_model",
                "agent_count": len(AGENTS), "model_server": provider.base_url,
                "model_available": model_ready, "model_name": model_name,
                "privacy": "Local server; conversation data stays on this device."
            })
        elif path == "/api/agents":
            self.send_json([{
                "id": agent.agent_id, "name": agent.name,
                "domain": agent.domain, "purpose": agent.purpose
            } for agent in AGENTS])
        elif path == "/api/conversations":
            with db() as connection:
                rows = connection.execute(
                    "SELECT id, title, created_at, updated_at FROM conversations "
                    "ORDER BY updated_at DESC LIMIT 100"
                ).fetchall()
            self.send_json([dict(row) for row in rows])
        elif path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            with db() as connection:
                rows = connection.execute(
                    "SELECT id, role, content, agent_id, created_at FROM messages "
                    "WHERE conversation_id=? ORDER BY id", (conversation_id,)
                ).fetchall()
            self.send_json([dict(row) for row in rows])
        elif path == "/api/memory":
            self.send_json(COORDINATOR.memory.recent(limit=100))
        elif path == "/":
            self.serve_file("index.html")
        elif path.startswith("/assets/"):
            self.serve_file(path.removeprefix("/assets/"))
        else:
            self.send_json({"error": "Not found"}, 404)

    def serve_file(self, relative: str) -> None:
        candidate = (WEB / relative).resolve()
        if WEB.resolve() not in candidate.parents and candidate != WEB.resolve():
            self.send_json({"error": "Invalid path"}, 400)
            return
        if not candidate.is_file():
            self.send_json({"error": "Not found"}, 404)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/conversations":
                conversation_id = secrets.token_urlsafe(12)
                timestamp = now()
                title = str(payload.get("title") or "New conversation")[:100]
                with db() as connection:
                    connection.execute(
                        "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                        (conversation_id, title, timestamp, timestamp)
                    )
                self.send_json({"id": conversation_id, "title": title}, 201)
            elif path == "/api/chat":
                self.handle_chat(payload)
            elif path == "/api/memory/clear":
                deleted = COORDINATOR.memory.clear()
                self.send_json({"deleted": deleted})
            else:
                self.send_json({"error": "Not found"}, 404)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except ProviderError as error:
            self.send_json({"error": str(error), "kind": "model_unavailable"}, 503)
        except Exception as error:
            self.send_json({"error": f"BabyMind could not complete the request: {error}"}, 500)

    def handle_chat(self, payload: dict) -> None:
        task = str(payload.get("message", "")).strip()
        agent_id = str(payload.get("agent_id", "BM-01")).strip().upper()
        conversation_id = str(payload.get("conversation_id", "")).strip()
        if not task:
            raise ValueError("Please enter a message.")
        if len(task) > 20000:
            raise ValueError("Messages must be 20,000 characters or fewer.")
        agent = next((item for item in AGENTS if item.agent_id == agent_id), None)
        if agent is None:
            raise ValueError("Choose one of the 50 registered agents.")
        if not conversation_id:
            conversation_id = secrets.token_urlsafe(12)
            timestamp = now()
            with db() as connection:
                connection.execute(
                    "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                    (conversation_id, task[:54] + ("…" if len(task) > 54 else ""), timestamp, timestamp)
                )
        with db() as connection:
            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not exists:
                raise ValueError("Conversation not found. Start a new conversation.")
            history = connection.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? "
                "ORDER BY id DESC LIMIT 12", (conversation_id,)
            ).fetchall()
            history = list(reversed(history))
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
                "VALUES (?, 'user', ?, ?, ?)",
                (conversation_id, task, agent_id, now())
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now(), conversation_id)
            )
        context = "\n".join(
            f"{'User' if item['role'] == 'user' else 'BabyMind'}: {item['content']}"
            for item in history
        )
        prompt = f"Recent conversation context (oldest first):\n{context}\n\nCurrent user message:\n{task}" if context else task
        if payload.get("collaborate"):
            first = COORDINATOR.ask(agent_id, prompt, use_memory=bool(payload.get("use_memory")))
            reviewer = COORDINATOR.ask("BM-49", (
                "Review this draft for correctness, gaps, clarity, and safety. "
                "Return concise actionable improvements. Do not rewrite the user's request.\n\n"
                + first.response
            ))
            final = COORDINATOR.ask("BM-01", (
                "Produce one coherent final answer using the specialist draft and reviewer notes. "
                "Resolve contradictions, do not mention hidden process, and do not invent facts.\n\n"
                "SPECIALIST DRAFT:\n" + first.response
                + "\n\nREVIEW NOTES:\n" + reviewer.response
            ), remember=bool(payload.get("remember")))
            response = final.response
            used_agents = [agent_id, "BM-49", "BM-01"]
        else:
            result = COORDINATOR.ask(
                agent_id, prompt,
                use_memory=bool(payload.get("use_memory")),
                remember=bool(payload.get("remember"))
            )
            response = result.response
            used_agents = [agent_id]
        with db() as connection:
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
                "VALUES (?, 'assistant', ?, ?, ?)",
                (conversation_id, response, agent_id, now())
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now(), conversation_id)
            )
        self.send_json({
            "conversation_id": conversation_id, "response": response,
            "agent_id": agent_id, "agent_name": agent.name,
            "agents_involved": used_agents,
            "remembered": bool(payload.get("remember"))
        })

def main() -> None:
    parser = argparse.ArgumentParser(description="Start the BabyMind local web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Use 127.0.0.1 for this PC only.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print("BabyMind web app")
    print(f"Open {url}")
    print("Data is stored locally in", DATA_HOME)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: LAN binding exposes this unauthenticated app to your local network.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down BabyMind.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
