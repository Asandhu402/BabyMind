"""Local web application server for BabyMind.

The server binds to localhost by default. LAN access is opt-in via --lan.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import sqlite3
import threading
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agents import AGENTS
from .coordinator import BabyMindCoordinator
from .providers import ProviderError
from .secure_store import SecureTextStore

WEB = Path(__file__).resolve().parent / "web"
DATA_HOME = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind"))
DATA_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_HOME / "app.sqlite3"
DB_LOCK = threading.Lock()
# The local model is CPU/RAM intensive. Start with one inference at a time.
INFERENCE_SEMAPHORE = threading.BoundedSemaphore(1)
COORDINATOR = BabyMindCoordinator()


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA secure_delete = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def text_store() -> SecureTextStore:
    return SecureTextStore(DB_PATH.with_suffix(".key"))


def init_db() -> None:
    secure = text_store()
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
        # Encrypt legacy plaintext values in place; the prefix makes this
        # migration idempotent and safe to retry after an interrupted upgrade.
        for row in connection.execute("SELECT id, title FROM conversations").fetchall():
            encrypted = secure.encrypt(row["title"])
            if encrypted != row["title"]:
                connection.execute("UPDATE conversations SET title=? WHERE id=?", (encrypted, row["id"]))
        for row in connection.execute("SELECT id, content FROM messages").fetchall():
            encrypted = secure.encrypt(row["content"])
            if encrypted != row["content"]:
                connection.execute("UPDATE messages SET content=? WHERE id=?", (encrypted, row["id"]))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_loopback_host(host: str) -> bool:
    """Return whether a bind host is a loopback address or localhost."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "BabyMind/0.3"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[BabyMind] {self.address_string()} - {fmt % args}")

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Content-Type must be application/json.")
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

    def authorize(self, path: str) -> bool:
        token = getattr(self.server, "auth_token", None)
        if token and path.startswith("/api/") and secrets.compare_digest(
            self.headers.get("X-BabyMind-Token", ""), token
        ):
            return True
        if token and path.startswith("/api/"):
            self.send_json({"error": "This BabyMind server requires its local access token."}, 401)
            return False
        return True

    def validate_browser_origin(self) -> bool:
        """Reject cross-site browser mutations while allowing non-browser local clients."""
        fetch_site = self.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site in {"cross-site"}:
            self.send_json({"error": "Cross-site requests are not allowed."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            request_host = self.headers.get("Host", "").lower()
            if not parsed.netloc or parsed.netloc.lower() != request_host:
                self.send_json({"error": "Request origin does not match this BabyMind server."}, 403)
                return False
        return True

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self.authorize(path):
            return
        if path == "/api/health":
            provider = COORDINATOR.provider
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
                "model_engine": "llama.cpp" if provider.__class__.__name__ == "LlamaCppProvider" else "LM Studio",
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
            self.send_json([{**dict(row), "title": text_store().decrypt(row["title"])} for row in rows])
        elif path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            with db() as connection:
                rows = connection.execute(
                    "SELECT id, role, content, agent_id, created_at FROM messages "
                    "WHERE conversation_id=? ORDER BY id", (conversation_id,)
                ).fetchall()
            self.send_json([{**dict(row), "content": text_store().decrypt(row["content"])} for row in rows])
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
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self.authorize(path):
            return
        if not self.validate_browser_origin():
            return
        try:
            payload = self.read_json()
            if path == "/api/conversations":
                conversation_id = secrets.token_urlsafe(12)
                timestamp = now()
                title = str(payload.get("title") or "New conversation")[:100]
                with db() as connection:
                    connection.execute(
                        "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                        (conversation_id, text_store().encrypt(title), timestamp, timestamp)
                    )
                self.send_json({"id": conversation_id, "title": title}, 201)
            elif path == "/api/chat":
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request. Please try again shortly."}, 429)
                    return
                try:
                    self.handle_chat(payload)
                finally:
                    INFERENCE_SEMAPHORE.release()
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

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not self.authorize(path):
            return
        if not self.validate_browser_origin():
            return
        if path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            with db() as connection:
                cursor = connection.execute(
                    "DELETE FROM conversations WHERE id=?", (conversation_id,)
                )
                deleted = cursor.rowcount
            self.send_json({"deleted": deleted})
        else:
            self.send_json({"error": "Not found"}, 404)

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
        is_new_conversation = not conversation_id
        if is_new_conversation:
            conversation_id = secrets.token_urlsafe(12)
            conversation_title = task[:54] + ("…" if len(task) > 54 else "")
        with db() as connection:
            if not is_new_conversation:
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
            else:
                history = []
        context = "\n".join(
            f"{'User' if item['role'] == 'user' else 'BabyMind'}: {text_store().decrypt(item['content'])}"
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
            timestamp = now()
            if is_new_conversation:
                connection.execute(
                    "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                    (conversation_id, text_store().encrypt(conversation_title), timestamp, timestamp)
                )
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
                "VALUES (?, 'user', ?, ?, ?)",
                (conversation_id, text_store().encrypt(task), agent_id, timestamp)
            )
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
                "VALUES (?, 'assistant', ?, ?, ?)",
                (conversation_id, text_store().encrypt(response), agent_id, timestamp)
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (timestamp, conversation_id)
            )
        self.send_json({
            "conversation_id": conversation_id, "response": response,
            "agent_id": agent_id, "agent_name": agent.name,
            "agents_involved": used_agents,
            "remembered": bool(payload.get("remember"))
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the BabyMind local web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; non-loopback requires --lan.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lan", action="store_true", help="Allow trusted devices on your Wi-Fi using a one-time access token.")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.lan and not is_loopback_host(args.host):
        parser.error("Non-loopback binding requires --lan, which enables access-token protection.")
    init_db()
    host = "0.0.0.0" if args.lan else args.host
    auth_token = secrets.token_urlsafe(24) if args.lan else None
    server = ThreadingHTTPServer((host, args.port), Handler)
    server.auth_token = auth_token
    url = f"http://127.0.0.1:{args.port}"
    print("BabyMind web app")
    print(f"Open on this computer: {url}")
    print("Data is stored locally in", DATA_HOME)
    if args.lan:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 80))
            lan_ip = probe.getsockname()[0]
        except OSError:
            lan_ip = "YOUR-PC-IP"
        finally:
            probe.close()
        print(f"Open on a trusted Wi-Fi device: http://{lan_ip}:{args.port}")
        print(f"One-time BabyMind access token: {auth_token}")
        print("WARNING: LAN mode uses HTTP. Use only on a trusted private Wi-Fi network; do not use on public Wi-Fi.")
        print("Keep this token private.")
    if not args.no_browser and not args.lan:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down BabyMind.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
