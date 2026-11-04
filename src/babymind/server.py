"""Local web application server for BabyMind.

The server binds to localhost by default. LAN access is opt-in via --lan.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import sqlite3
import threading
import time
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agents import AGENTS
from .coordinator import BabyMindCoordinator
from .providers import ProviderError
from .secure_store import SecureTextStore
from .lan_tls import create_lan_tls_context
from .research import fetch_page, search_web

WEB = Path(__file__).resolve().parent / "web"
DATA_HOME = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind"))
DATA_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_HOME / "app.sqlite3"
DB_LOCK = threading.RLock()
# The local model is CPU/RAM intensive. Start with one inference at a time.
INFERENCE_SEMAPHORE = threading.BoundedSemaphore(1)
COORDINATOR = BabyMindCoordinator()
# Reviewed app-builder plans live in memory only and are single-use.
BUILDER_LOCK = threading.RLock()
BUILDER_PLANS: dict[str, dict] = {}
BUILDER_PLAN_TTL = 1_800
# Mission control state is created lazily so tests can relocate DATA_HOME.
_MISSION_STORE = None
_MISSION_HOME: Path | None = None
MISSION_LOCK = threading.RLock()


def mission_store():
    """Return the encrypted mission store for the current data home."""
    global _MISSION_STORE, _MISSION_HOME
    from .orchestrator import MissionStore

    with MISSION_LOCK:
        if _MISSION_STORE is None or _MISSION_HOME != DATA_HOME:
            _MISSION_STORE = MissionStore(DATA_HOME)
            _MISSION_HOME = DATA_HOME
        return _MISSION_STORE


def orchestrator():
    from .orchestrator import Orchestrator

    budget = int(os.getenv("BABYMIND_MISSION_MAX_SECONDS", "900") or 900)
    return Orchestrator(COORDINATOR.provider, mission_store(), max_seconds=budget)


@contextmanager
def db():
    # Serialize access so a validated restore cannot replace a database while
    # another request still has an open SQLite handle.
    with DB_LOCK:
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
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS execution_proposals (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                action TEXT NOT NULL, payload TEXT NOT NULL, proposal_hash TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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


def _split_host(raw: str) -> tuple[str, str]:
    """Split a Host header into (hostname, port), including bracketed IPv6."""
    value = (raw or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return value, ""
        hostname = value[1:end]
        rest = value[end + 1:]
        return hostname, rest[1:] if rest.startswith(":") else ""
    hostname, separator, port = value.rpartition(":")
    if separator and port.isdigit():
        return hostname, port
    return value, ""


def persist_integration_exchange(
    conversation_id: str, user_content: str, assistant_content: str, agent_id: str = "BM-01"
) -> str:
    """Persist a completed local-tool exchange in the same encrypted chat history."""
    clean_user = user_content.strip()
    clean_assistant = assistant_content.strip()
    if not clean_user or not clean_assistant:
        raise ValueError("Integration exchange content cannot be empty.")
    timestamp = now()
    conversation_id = conversation_id.strip()
    secure = text_store()
    with DB_LOCK, db() as connection:
        if not conversation_id:
            conversation_id = secrets.token_urlsafe(12)
            title = clean_user[:54] + ("…" if len(clean_user) > 54 else "")
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                (conversation_id, secure.encrypt(title), timestamp, timestamp),
            )
        elif not connection.execute(
            "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone():
            raise ValueError("Conversation not found. Start a new conversation.")
        connection.execute(
            "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
            "VALUES (?, 'user', ?, ?, ?)",
            (conversation_id, secure.encrypt(clean_user), agent_id, timestamp),
        )
        connection.execute(
            "INSERT INTO messages (conversation_id, role, content, agent_id, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?)",
            (conversation_id, secure.encrypt(clean_assistant), agent_id, timestamp),
        )
        connection.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (timestamp, conversation_id),
        )
    return conversation_id


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

    def validate_host(self) -> bool:
        """Reject requests addressed to a hostname this server was not started for.

        Without this check a page on the public web can point its own domain at
        127.0.0.1 (DNS rebinding), become same-origin with BabyMind, and read
        decrypted conversations through the plain GET endpoints.
        """
        raw = self.headers.get("Host", "").strip().lower()
        if not raw:
            self.send_json({"error": "Requests must include a Host header."}, 400)
            return False
        hostname, port = _split_host(raw)
        expected_port = str(getattr(self.server, "server_address", ("", 0))[1])
        if port and port != expected_port:
            self.send_json({"error": "Request host does not match this BabyMind server."}, 403)
            return False
        allowed = {"127.0.0.1", "localhost", "::1"}
        lan_ip = getattr(self.server, "lan_ip", None)
        if lan_ip:
            allowed.add(str(lan_ip).lower())
        if hostname not in allowed:
            self.send_json({"error": "Request host does not match this BabyMind server."}, 403)
            return False
        return True

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self.validate_host():
            return
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
                "model_engine": "llama.cpp",
                "model_available": model_ready, "model_name": model_name,
                "privacy": "Local server; conversation data stays on this device."
            })
        elif path == "/api/integrations":
            from .integrations.catalog import integration_status
            self.send_json(integration_status())
        elif path == "/api/workspace/readiness":
            from .workspace_readiness import workspace_readiness
            self.send_json(workspace_readiness())
        elif path == "/api/builder/status":
            from .builder import builder_status
            self.send_json(builder_status())
        elif path == "/api/roles":
            from .orchestrator import phase_catalogue, role_catalogue
            self.send_json({
                "roles": role_catalogue(),
                "phases": phase_catalogue(),
                "count": len(role_catalogue()),
                "notice": "50 roles share one local model; they are not 50 independent models.",
            })
        elif path == "/api/agents/activity":
            self.send_json(mission_store().agent_stats())
        elif path == "/api/missions":
            self.send_json(mission_store().list_missions(limit=30))
        elif path.startswith("/api/missions/"):
            mission_id = path.rstrip("/").rsplit("/", 1)[-1]
            try:
                self.send_json(mission_store().get(mission_id))
            except ValueError:
                self.send_json({"error": "Mission not found."}, 404)
        elif path == "/api/model/hardware":
            from .hardware import hardware_report
            self.send_json(hardware_report(DATA_HOME))
        elif path == "/api/sandbox":
            from .sandbox import status as sandbox_status
            self.send_json(sandbox_status(probe=False))
        elif path == "/api/dev/status":
            from .selfdev import status as selfdev_status
            self.send_json(selfdev_status())
        elif path == "/api/dev/checkpoints":
            from .selfdev import list_checkpoints
            self.send_json(list_checkpoints(limit=20))
        elif path == "/api/dev/tree":
            from .selfdev import tree
            self.send_json({"files": tree()})
        elif path == "/api/dev/file":
            from .selfdev import read_file
            relative = parse_qs(urlparse(self.path).query).get("path", [""])[0]
            self.send_json(read_file(relative))
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
        elif path == "/api/backup/status":
            files = []
            for name in ("app.sqlite3", "memory.sqlite3"):
                database = DATA_HOME / name
                key = DATA_HOME / ("app.key" if name == "app.sqlite3" else "memory.key")
                files.append({
                    "database": name, "available": database.is_file(),
                    "bytes": database.stat().st_size if database.is_file() else 0,
                    "key_available": key.is_file(),
                })
            self.send_json({"home": str(DATA_HOME), "databases": files})
        elif path == "/api/memory":
            self.send_json(COORDINATOR.memory.recent(limit=100))
        elif path == "/api/tasks":
            with db() as connection:
                rows = connection.execute(
                    "SELECT id, title, details, status, created_at, updated_at "
                    "FROM tasks ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            secure = text_store()
            self.send_json([{
                **dict(row), "title": secure.decrypt(row["title"]),
                "details": secure.decrypt(row["details"])
            } for row in rows])
        elif path == "/api/proposals":
            with db() as connection:
                rows = connection.execute(
                    "SELECT id, task_id, action, payload, proposal_hash, status, result, created_at, updated_at "
                    "FROM execution_proposals ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            secure = text_store()
            self.send_json([{
                **dict(row), "payload": json.loads(secure.decrypt(row["payload"])),
                "result": secure.decrypt(row["result"]) if row["result"] else ""
            } for row in rows])
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
        if not self.validate_host():
            return
        if not self.authorize(path):
            return
        if not self.validate_browser_origin():
            return
        try:
            payload = self.read_json()
            if path == "/api/integrations/voicebox/speech":
                audio = COORDINATOR.synthesize_speech(
                    str(payload.get("text", "")),
                    voice=str(payload.get("voice", "")).strip() or None,
                    speed=float(payload.get("speed", 1.0)),
                )
                self.send_json({"audio_base64": base64.b64encode(audio).decode("ascii"), "mime_type": "audio/wav"})
            elif path == "/api/integrations/voicebox/transcribe":
                source = str(payload.get("path", "")).strip()
                if not source or len(source) > 2048:
                    raise ValueError("Enter a local audio file path.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request."}, 429)
                    return
                try:
                    instruction = str(payload.get("instruction", "Summarize this recording and extract important points."))
                    result, transcript = COORDINATOR.process_voicebox_audio(
                        str(payload.get("agent_id", "BM-01")), source, instruction,
                        language=str(payload.get("language", "")).strip() or None,
                        use_memory=bool(payload.get("use_memory")), remember=bool(payload.get("remember")),
                    )
                    conversation_id = persist_integration_exchange(
                        str(payload.get("conversation_id", "")),
                        "Transcribe with local Voicebox: " + source + "\n" + instruction + "\n\n" + str(transcript["text"])[:100_000],
                        result.response, result.agent_id,
                    )
                finally:
                    INFERENCE_SEMAPHORE.release()
                self.send_json({
                    "conversation_id": conversation_id, "user_message": "Transcribe with local Voicebox: " + source,
                    "response": result.response, "transcript": transcript, "agent_id": result.agent_id,
                    "agent_name": result.agent_name, "memories_used": result.memories_used,
                })
            elif path == "/api/integrations/cognee/index":
                if payload.get("user_approved") is not True:
                    raise PermissionError("Confirm that this note may be stored in Cognee's separate local knowledge database.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another local AI operation."}, 429)
                    return
                try:
                    dataset = COORDINATOR.index_knowledge_note(str(payload.get("text", "")), user_approved=True)
                finally:
                    INFERENCE_SEMAPHORE.release()
                self.send_json({
                    "dataset": dataset,
                    "notice": "The approved note was indexed in Cognee's separate local graph/vector store. It is not encrypted by BabyMind's encrypted SQLite memory.",
                }, 201)
            elif path == "/api/integrations/cognee/search":
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another local AI operation."}, 429)
                    return
                try:
                    query = str(payload.get("query", ""))
                    result, results = COORDINATOR.ask_with_knowledge(
                        str(payload.get("agent_id", "BM-01")), query,
                        use_memory=bool(payload.get("use_memory")), remember=bool(payload.get("remember")),
                    )
                    conversation_id = persist_integration_exchange(
                        str(payload.get("conversation_id", "")),
                        "Search local knowledge: " + query, result.response, result.agent_id,
                    )
                finally:
                    INFERENCE_SEMAPHORE.release()
                self.send_json({
                    "conversation_id": conversation_id, "user_message": "Search local knowledge: " + query,
                    "response": result.response, "results": results, "count": len(results), "agent_id": result.agent_id,
                    "agent_name": result.agent_name, "memories_used": result.memories_used,
                })
            elif path == "/api/backup/export":
                destination = str(payload.get("path", "")).strip()
                password = str(payload.get("password", ""))
                if not destination or len(destination) > 2048:
                    raise ValueError("Enter a local backup file path.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy; try the backup again shortly."}, 429)
                    return
                try:
                    from .backup import create_backup
                    from .memory import MEMORY_LOCK
                    with DB_LOCK, MEMORY_LOCK:
                        result = create_backup(DATA_HOME, destination, password)
                finally:
                    INFERENCE_SEMAPHORE.release()
                self.send_json({
                    **result,
                    "notice": "Encrypted backup created. It contains encrypted databases and key files, not plaintext chat or memory. On Windows, DPAPI keys can only be restored by the same Windows user on the same device.",
                }, 201)
            elif path == "/api/backup/restore":
                source = str(payload.get("path", "")).strip()
                password = str(payload.get("password", ""))
                confirmation = str(payload.get("confirmation", ""))
                if not source or len(source) > 2048:
                    raise ValueError("Enter the local BabyMind backup file path.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy; try the restore again shortly."}, 429)
                    return
                try:
                    from .backup import restore_backup
                    from .memory import MEMORY_LOCK, LocalMemory
                    with DB_LOCK, MEMORY_LOCK:
                        result = restore_backup(
                            DATA_HOME, source, password, confirmation=confirmation,
                        )
                        COORDINATOR.memory = LocalMemory(DATA_HOME / "memory.sqlite3")
                finally:
                    INFERENCE_SEMAPHORE.release()
                self.send_json({
                    **result,
                    "notice": "Backup restored and encrypted memory reloaded. Close and reopen BabyMind before continuing.",
                })
            elif path == "/api/conversations":
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
            elif path == "/api/integrations/document":
                source = str(payload.get("path", "")).strip()
                if not source or len(source) > 2048:
                    raise ValueError("Enter a local document path of 1–2,048 characters.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request."}, 429)
                    return
                try:
                    result, extracted_chars = COORDINATOR.process_document(
                        str(payload.get("agent_id", "BM-01")), source,
                        str(payload.get("instruction", "Summarize this document and identify its key points.")),
                        use_memory=bool(payload.get("use_memory")),
                        remember=bool(payload.get("remember")),
                    )
                finally:
                    INFERENCE_SEMAPHORE.release()
                user_message = f"Analyze local document: {source}\n{payload.get('instruction', 'Summarize this document and identify its key points.')}"
                conversation_id = persist_integration_exchange(
                    str(payload.get("conversation_id", "")), user_message, result.response, result.agent_id
                )
                self.send_json({
                    "conversation_id": conversation_id, "user_message": user_message,
                    "response": result.response, "agent_id": result.agent_id,
                    "agent_name": result.agent_name, "extracted_characters": extracted_chars,
                    "memories_used": result.memories_used, "remembered": result.remembered,
                })
            elif path == "/api/integrations/audio":
                source = str(payload.get("path", "")).strip()
                if not source or len(source) > 2048:
                    raise ValueError("Enter a local audio path of 1–2,048 characters.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request."}, 429)
                    return
                try:
                    result, transcript = COORDINATOR.process_audio(
                        str(payload.get("agent_id", "BM-01")), source,
                        str(payload.get("instruction", "Summarize this recording and extract important points.")),
                        language=str(payload.get("language", "")).strip() or None,
                        use_memory=bool(payload.get("use_memory")),
                        remember=bool(payload.get("remember")),
                    )
                finally:
                    INFERENCE_SEMAPHORE.release()
                user_message = f"Transcribe and analyze local audio: {source}\n{payload.get('instruction', 'Summarize this recording and extract important points.')}\n\nTRANSCRIPT:\n{str(transcript.get('text', ''))[:100000]}"
                conversation_id = persist_integration_exchange(
                    str(payload.get("conversation_id", "")), user_message, result.response, result.agent_id
                )
                self.send_json({
                    "conversation_id": conversation_id, "user_message": user_message,
                    "response": result.response, "agent_id": result.agent_id,
                    "agent_name": result.agent_name, "transcript": transcript,
                    "memories_used": result.memories_used, "remembered": result.remembered,
                })
            elif path == "/api/integrations/browser":
                if payload.get("user_approved") is not True:
                    raise PermissionError("Confirm the browser task explicitly before it can run.")
                task = str(payload.get("task", "")).strip()
                if not task or len(task) > 4000:
                    raise ValueError("Browser task must contain 1–4,000 characters.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request."}, 429)
                    return
                try:
                    result = asyncio.run(COORDINATOR.run_browser_task(task, user_approved=True))
                finally:
                    INFERENCE_SEMAPHORE.release()
                notice = "Browser task completed in a supervised local browser. Review any website changes."
                user_message = "Supervised browser task: " + task
                conversation_id = persist_integration_exchange(
                    str(payload.get("conversation_id", "")), user_message, str(result or notice), "BM-01"
                )
                self.send_json({"conversation_id": conversation_id, "user_message": user_message, "result": result, "notice": notice})
            elif path == "/api/integrations/coding":
                if payload.get("user_approved") is not True:
                    raise PermissionError("Confirm the coding request before sending it to BabyMind's local model.")
                task = str(payload.get("task", "")).strip()
                context = str(payload.get("context", "")).strip()
                if not task or len(task) > 12000:
                    raise ValueError("Coding task must contain 1–12,000 characters.")
                if len(context) > 24000:
                    raise ValueError("Optional code context is limited to 24,000 characters.")
                if not INFERENCE_SEMAPHORE.acquire(blocking=False):
                    self.send_json({"error": "BabyMind is busy with another model request."}, 429)
                    return
                try:
                    result = COORDINATOR.coding_assist(task, context=context)
                finally:
                    INFERENCE_SEMAPHORE.release()
                user_message = "Coding assistant request: " + task
                if context:
                    user_message += "\n\nUser-provided code context:\n" + context
                conversation_id = persist_integration_exchange(
                    str(payload.get("conversation_id", "")), user_message, result, "BM-01"
                )
                self.send_json({
                    "conversation_id": conversation_id, "user_message": user_message,
                    "response": result, "agent_id": "BM-01",
                    "agent_name": "BabyMind Coding Assistant",
                    "notice": "Generated by BabyMind's shared local llama.cpp model. No files or commands were accessed."
                })
            elif path == "/api/missions":
                brief = str(payload.get("brief", ""))
                mission_id = orchestrator().start(brief, self_edit=bool(payload.get("self_edit")))
                self.send_json({
                    "id": mission_id, "status": "running", "agents": 50,
                    "self_edit": bool(payload.get("self_edit")),
                    "notice": (
                        "All 50 roles are queued. With self_edit the mission also proposes one patch "
                        "to BabyMind's own source and applies it only if the test suite accepts it."
                        if payload.get("self_edit") else
                        "All 50 roles are queued. Poll this mission for per-role records."
                    ),
                }, 202)
            elif path.startswith("/api/missions/") and path.endswith("/cancel"):
                mission_id = path.strip("/").split("/")[2]
                orchestrator().cancel(mission_id)
                self.send_json({"id": mission_id, "cancelled": True})
            elif path in {"/api/research/github", "/api/research/github/repo"}:
                from .research import github_repository, github_search
                if path.endswith("/repo"):
                    result = github_repository(
                        str(payload.get("owner", "")).strip(),
                        str(payload.get("repo", "")).strip(),
                    )
                else:
                    result = {
                        "results": github_search(str(payload.get("query", "")),
                                                 limit=int(payload.get("limit", 5))),
                        "notice": "Metadata only. Licences are classified, not cleared; "
                                  "never import a repository without review.",
                    }
                self.send_json(result)
            elif path == "/api/dev/checkpoint":
                from .selfdev import checkpoint
                record = checkpoint(str(payload.get("label", ""))[:160])
                self.send_json({"id": record["id"], "file_count": record["file_count"],
                                "bytes": record["bytes"], "created_at": record["created_at"]}, 201)
            elif path == "/api/dev/preview":
                from .selfdev import preview_edits
                reviewed = preview_edits(payload.get("edits"))
                self.send_json({"files": [
                    {key: value for key, value in item.items() if key != "content"}
                    for item in reviewed
                ]})
            elif path == "/api/dev/apply":
                from .selfdev import apply_edits
                result = apply_edits(
                    payload.get("edits"),
                    reason=str(payload.get("reason", "")),
                    agent_id=str(payload.get("agent_id", "BM-03")),
                    verify=bool(payload.get("verify", True)),
                    test_timeout=min(int(payload.get("test_timeout", 300) or 300), 600),
                )
                self.send_json(result, 201 if result["status"] == "applied" else 200)
            elif path == "/api/dev/repair":
                from .orchestrator import _extract_json
                from .selfdev import apply_with_repair

                brief = str(payload.get("brief", "")).strip()
                if not brief:
                    raise ValueError("Describe the change you want the engine to make.")
                attempts = max(1, min(int(payload.get("attempts", 2) or 2), 3))
                provider = COORDINATOR.provider
                system = (
                    "You are BabyMind's Coding Agent working on its own source tree. Return ONLY JSON: "
                    '{"reason": "...", "edits": [{"path": "src/babymind/example.py", '
                    '"content": "full file contents"}]}. Paths are relative to the project; never target '
                    ".git, state/, keys, databases or binaries. If no safe change is possible return "
                    '{"reason": "...", "edits": []}.'
                )

                def propose(attempt: int, failure: str):
                    user = f"BRIEF:\n{brief}"
                    if failure:
                        user += ("\n\nYOUR PREVIOUS PATCH WAS ROLLED BACK. The verification output was:\n"
                                 + failure + "\nReturn a corrected patch that fixes exactly this failure.")
                    proposal = json.loads(_extract_json(provider.complete(system, user)))
                    edits = proposal.get("edits") or []
                    if not isinstance(edits, list):
                        raise ValueError("the model did not return a list of edits")
                    return edits

                outcome = apply_with_repair(
                    propose,
                    attempts=attempts,
                    reason=brief[:200],
                    agent_id="BM-03",
                    verify=True,
                    test_timeout=600,
                )
                self.send_json(outcome, 201 if outcome["status"] == "applied" else 200)
            elif path == "/api/dev/rollback":
                from .selfdev import rollback
                self.send_json(rollback(str(payload.get("checkpoint_id", "")),
                                        agent_id=str(payload.get("agent_id", "BM-47"))))
            elif path == "/api/sandbox/self-test":
                from .sandbox import self_test
                from .selfdev import dev_root
                self.send_json(self_test(dev_root()))
            elif path == "/api/dev/tests":
                from .selfdev import run_tests
                self.send_json(run_tests(timeout=min(int(payload.get("timeout", 300) or 300), 600)))
            elif path == "/api/builder/plan":
                self.handle_builder_plan(payload)
            elif path == "/api/builder/build":
                self.handle_builder_build(payload)
            elif path == "/api/tasks":
                title = str(payload.get("title", "")).strip()
                details = str(payload.get("details", "")).strip()
                if not title:
                    raise ValueError("Give the task a title.")
                if len(title) > 120 or len(details) > 5000:
                    raise ValueError("Task title must be 120 characters or fewer and details 5,000 or fewer.")
                task_id = secrets.token_urlsafe(12)
                timestamp = now()
                with DB_LOCK, db() as connection:
                    count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                    if count >= 100:
                        raise ValueError("The task queue is full (100 tasks). Complete or cancel older tasks first.")
                    secure = text_store()
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, 'queued', ?, ?)",
                        (task_id, secure.encrypt(title), secure.encrypt(details), timestamp, timestamp)
                    )
                self.send_json({
                    "id": task_id, "title": title, "details": details,
                    "status": "queued", "created_at": timestamp, "updated_at": timestamp
                }, 201)
            elif path.startswith("/api/tasks/") and path.endswith("/action"):
                parts = path.strip("/").split("/")
                if len(parts) != 4:
                    raise ValueError("Invalid task action path.")
                task_id, action = parts[2], str(payload.get("action", "")).strip().lower()
                transitions = {
                    "start": {"queued": "active"},
                    "pause": {"active": "paused"},
                    "resume": {"paused": "active"},
                    "cancel": {"queued": "cancelled", "active": "cancelled", "paused": "cancelled"},
                    "terminate": {"queued": "terminated", "active": "terminated", "paused": "terminated"},
                    "complete": {"active": "completed"}
                }
                if action not in transitions:
                    raise ValueError("Unknown task action.")
                with DB_LOCK, db() as connection:
                    row = connection.execute(
                        "SELECT status FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()
                    if not row:
                        self.send_json({"error": "Task not found."}, 404)
                        return
                    next_status = transitions[action].get(row["status"])
                    if not next_status:
                        raise ValueError(f"Cannot {action} a task while it is {row['status']}.")
                    timestamp = now()
                    connection.execute(
                        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                        (next_status, timestamp, task_id)
                    )
                    updated = connection.execute(
                        "SELECT id, title, details, status, created_at, updated_at "
                        "FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()
                secure = text_store()
                self.send_json({
                    **dict(updated), "title": secure.decrypt(updated["title"]),
                    "details": secure.decrypt(updated["details"])
                })
            elif path.startswith("/api/tasks/") and path.endswith("/propose"):
                from .approval import WORKSPACE_FILE_ACTIONS_ENABLED, build_readonly_proposal
                if not WORKSPACE_FILE_ACTIONS_ENABLED:
                    raise ValueError("Workspace file actions are temporarily disabled pending native race-resistant filesystem protection.")
                parts = path.strip("/").split("/")
                if len(parts) != 4:
                    raise ValueError("Invalid proposal path.")
                task_id = parts[2]
                with db() as connection:
                    task_row = connection.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not task_row:
                    self.send_json({"error": "Task not found."}, 404)
                    return
                if task_row["status"] != "active":
                    raise ValueError("Start the task before requesting an execution proposal.")
                proposal_action = str(payload.get("action", "list_directory")).strip()
                proposal = build_readonly_proposal(
                    str(payload.get("relative_path", "")),
                    action=proposal_action,
                    name_contains=str(payload.get("name_contains", "")),
                    content=payload.get("content", ""),
                )
                proposal_id = secrets.token_urlsafe(12)
                timestamp = now()
                secure = text_store()
                with DB_LOCK, db() as connection:
                    connection.execute(
                        "INSERT INTO execution_proposals "
                        "(id, task_id, action, payload, proposal_hash, status, result, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 'awaiting_approval', '', ?, ?)",
                        (proposal_id, task_id, proposal["action"],
                         secure.encrypt(json.dumps(proposal["payload"], ensure_ascii=False)),
                         proposal["proposal_hash"], timestamp, timestamp)
                    )
                self.send_json({
                    "id": proposal_id, "task_id": task_id, "action": proposal["action"],
                    "payload": proposal["payload"], "proposal_hash": proposal["proposal_hash"],
                    "status": "awaiting_approval",
                    "effects": (
                        "Replace the contents of this exact UTF-8 text file after approval, only if its SHA-256 still matches the reviewed version."
                        if proposal["action"] == "edit_text_file"
                        else "Create one new UTF-8 text file up to 32 KB after approval. Existing files are never overwritten."
                        if proposal["action"] == "create_text_file"
                        else "Read up to 32 KB of this UTF-8 text file after approval."
                        if proposal["action"] == "read_text_file"
                        else "Search eligible filenames only; file contents are not opened."
                        if proposal["action"] == "find_files"
                        else "Read directory names and basic item types only; no file contents are opened."
                    ),
                    "created_at": timestamp
                }, 201)
            elif path.startswith("/api/proposals/") and path.endswith("/approve"):
                from .approval import WORKSPACE_FILE_ACTIONS_ENABLED, execute_readonly_proposal
                if not WORKSPACE_FILE_ACTIONS_ENABLED:
                    raise ValueError("Workspace file actions are temporarily disabled pending native race-resistant filesystem protection.")
                parts = path.strip("/").split("/")
                if len(parts) != 4:
                    raise ValueError("Invalid approval path.")
                proposal_id = parts[2]
                supplied_hash = str(payload.get("proposal_hash", ""))
                with DB_LOCK, db() as connection:
                    row = connection.execute(
                        "SELECT * FROM execution_proposals WHERE id=?", (proposal_id,)
                    ).fetchone()
                    if not row:
                        self.send_json({"error": "Proposal not found."}, 404)
                        return
                    if row["status"] != "awaiting_approval":
                        raise ValueError("This proposal is no longer awaiting approval.")
                    if not secrets.compare_digest(supplied_hash, row["proposal_hash"]):
                        raise ValueError("Approval does not match the exact proposal shown.")
                    task_row = connection.execute("SELECT status FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
                    if not task_row or task_row["status"] != "active":
                        raise ValueError("The task must remain active to approve this proposal.")
                    secure = text_store()
                    proposal_payload = json.loads(secure.decrypt(row["payload"]))
                    action = row["action"]
                    connection.execute(
                        "UPDATE execution_proposals SET status='running', updated_at=? "
                        "WHERE id=? AND status='awaiting_approval'",
                        (now(), proposal_id)
                    )
                # Keep filesystem operations outside the database transaction.
                try:
                    result = execute_readonly_proposal(proposal_payload, action=action)
                    final_status = "completed"
                except Exception as error:
                    result = {"error": str(error)}
                    final_status = "failed"
                encoded_result = secure.encrypt(json.dumps(result, ensure_ascii=False))
                with DB_LOCK, db() as connection:
                    connection.execute(
                        "UPDATE execution_proposals SET status=?, result=?, updated_at=? "
                        "WHERE id=? AND status='running'",
                        (final_status, encoded_result, now(), proposal_id)
                    )
                if final_status == "failed":
                    self.send_json({
                        "id": proposal_id, "status": "failed", "result": result,
                        "error": result["error"]
                    }, 400)
                    return
                self.send_json({
                    "id": proposal_id, "status": "completed", "result": result,
                    "notice": (
                        "Approved text file edit completed after matching the reviewed original hash."
                        if action == "edit_text_file"
                        else "Approved new text file created. No existing file was overwritten."
                        if action == "create_text_file"
                        else "Approved text-file preview completed. No files were modified."
                        if action == "read_text_file"
                        else "Filename search completed. No file contents were opened."
                        if action == "find_files"
                        else "Read-only directory listing completed. No file contents were opened or modified."
                    )
                })
            elif path == "/api/research/page":
                page_url = str(payload.get("url", "")).strip()
                if not page_url or len(page_url) > 2048:
                    raise ValueError("Enter a web page URL of 1–2,048 characters.")
                result = fetch_page(page_url)
                self.send_json(result)
            elif path == "/api/research":
                query = str(payload.get("query", "")).strip()
                limit = int(payload.get("limit", 5))
                results = search_web(query, limit=limit)
                self.send_json({
                    "query": query,
                    "provider": "DuckDuckGo HTML",
                    "results": results,
                    "count": len(results),
                    "notice": "Search snippets are unverified third-party content. Review sources before relying on them."
                })
            elif path == "/api/memory/search":
                query = str(payload.get("query", "")).strip()
                limit = int(payload.get("limit", 100))
                self.send_json(COORDINATOR.memory.relevant(query, limit=min(20, max(1, limit))))
            elif path == "/api/memory/clear":
                deleted = COORDINATOR.memory.clear()
                self.send_json({"deleted": deleted})
            else:
                self.send_json({"error": "Not found"}, 404)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except (PermissionError, FileNotFoundError) as error:
            self.send_json({"error": str(error)}, 400)
        except ImportError as error:
            self.send_json({"error": str(error), "kind": "integration_unavailable"}, 503)
        except ProviderError as error:
            # Keep actionable provider diagnostics in the local server log. The
            # browser receives the same safe message, but CI logs must expose
            # the actual cause instead of only an HTTP 503 status.
            print(f"[BabyMind] Model provider error: {error}", flush=True)
            self.send_json({"error": str(error), "kind": "model_unavailable"}, 503)
        except RuntimeError as error:
            print(f"[BabyMind] Integration error: {error}", flush=True)
            self.send_json({"error": str(error), "kind": "integration_unavailable"}, 503)
        except Exception as error:
            self.send_json({"error": f"BabyMind could not complete the request: {error}"}, 500)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not self.validate_host():
            return
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

    def handle_builder_plan(self, payload: dict) -> None:
        """Ask BabyMind's local model to plan a small app, without writing anything."""
        from .builder import create_plan

        self._prune_builder_plans()
        with INFERENCE_SEMAPHORE:
            plan = create_plan(
                str(payload.get("brief", "")),
                COORDINATOR.provider,
                name_hint=str(payload.get("name", "")),
            )
        plan_id = secrets.token_urlsafe(12)
        with BUILDER_LOCK:
            BUILDER_PLANS[plan_id] = {"plan": plan, "created": time.monotonic()}
        self.send_json({
            "plan_id": plan_id,
            "name": plan["name"],
            "summary": plan["summary"],
            "target": plan["target"],
            "entry": plan["entry"] or None,
            "will_run": plan["will_run"],
            "files": plan["file_summary"],
            "total_bytes": plan["total_bytes"],
            "plan_hash": plan["plan_hash"],
            "status": "awaiting_approval",
            "notice": (
                "Nothing has been written yet. Review the file list, then approve this exact "
                "plan hash to create the app and run its entry point once."
            ),
        }, 201)

    def handle_builder_build(self, payload: dict) -> None:
        """Write an approved plan and run its entry point exactly once."""
        from .builder import apply_plan

        plan_id = str(payload.get("plan_id", "")).strip()
        if not plan_id:
            raise ValueError("Choose a reviewed plan to build.")
        with BUILDER_LOCK:
            stored = BUILDER_PLANS.pop(plan_id, None)
        if stored is None:
            raise ValueError("That plan is no longer available. Request a new plan.")
        if time.monotonic() - stored["created"] > BUILDER_PLAN_TTL:
            raise ValueError("That plan expired. Request a new plan.")
        self.send_json(apply_plan(stored["plan"], str(payload.get("plan_hash", ""))), 201)

    @staticmethod
    def _prune_builder_plans() -> None:
        cutoff = time.monotonic() - BUILDER_PLAN_TTL
        with BUILDER_LOCK:
            for key in [key for key, value in BUILDER_PLANS.items() if value["created"] < cutoff]:
                BUILDER_PLANS.pop(key, None)

    def handle_chat(self, payload: dict) -> None:
        task = str(payload.get("message", "")).strip()
        agent_id = str(payload.get("agent_id", "BM-01")).strip().upper()
        conversation_id = str(payload.get("conversation_id") or "").strip()
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
                    "ORDER BY id DESC LIMIT 10", (conversation_id,)
                ).fetchall()
                history = list(reversed(history))
            else:
                history = []
        # Bound dialogue context so long chats do not crowd out the current
        # request when using a compact local model/context window.
        context_parts: list[str] = []
        remaining_chars = 10_000
        for item in reversed(history):
            if remaining_chars <= 0:
                break
            content = text_store().decrypt(item["content"])
            content = content[-min(3_000, remaining_chars):]
            line = f"{'User' if item['role'] == 'user' else 'BabyMind'}: {content}"
            if len(line) > remaining_chars:
                line = line[-remaining_chars:]
            context_parts.append(line)
            remaining_chars -= len(line) + 1
        context = "\n".join(reversed(context_parts))
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
    auth_token = secrets.token_urlsafe(24) if args.lan else None
    lan_ip = None
    tls_context = None
    ca_path = None
    if args.lan:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 80))
            lan_ip = probe.getsockname()[0]
        except OSError as error:
            raise RuntimeError("BabyMind could not determine this computer's LAN IP address.") from error
        finally:
            probe.close()
        tls_context, ca_path = create_lan_tls_context(DATA_HOME, lan_ip)

    host = lan_ip if args.lan else args.host
    server = ThreadingHTTPServer((host, args.port), Handler)
    if tls_context is not None:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    server.auth_token = auth_token
    server.lan_ip = lan_ip
    scheme = "https" if args.lan else "http"
    url = f"{scheme}://127.0.0.1:{args.port}"
    print("BabyMind web app")
    print(f"Open on this computer: {url}")
    print("Data is stored locally in", DATA_HOME)
    if args.lan:
        print(f"Open on a trusted Wi-Fi device: https://{lan_ip}:{args.port}")
        print(f"One-time BabyMind access token: {auth_token}")
        print(f"Install this public CA certificate on your iPhone: {ca_path}")
        print("On iPhone, install the certificate profile, then enable full trust under Settings > General > About > Certificate Trust Settings.")
        print("Use only on a trusted private Wi-Fi network. Keep the access token private.")
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
