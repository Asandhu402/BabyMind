"""Inspectable, bounded cognitive runtime for BabyMind."""
from __future__ import annotations
import importlib.util
import json, math, os, platform, shutil, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .agents import AGENTS, AGENT_BY_ID, AgentSpec, agent_instructions
from .secure_store import SecureTextStore

MAX_TEXT = 4000
VALID_ACTIONS = {"create_goal", "complete_goal", "record_question", "write_note", "wait"}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]

def environment_snapshot() -> dict[str, Any]:
    """Report host facts; a virtualization hint is not proof of simulation."""
    release = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                release[key] = value.strip().strip('"')
    except OSError:
        pass
    try:
        hypervisor = "hypervisor" in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        hypervisor = False
    return {
        "system": platform.system(), "kernel": platform.release(),
        "distribution": release.get("PRETTY_NAME", "unknown"),
        "architecture": platform.machine(), "python": platform.python_version(),
        "python_executable": str(Path(os.sys.executable).resolve()),
        "home_directory": str(Path.home()),
        "babymind_home": str(Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind")).expanduser()),
        "available_commands": {n: shutil.which(n) is not None for n in ("git", "python3", "pytest", "unshare")},
        "virtualization_hint": hypervisor,
        "virtualization_hint_meaning": "Hypervisor flag observed; this does not establish simulation." if hypervisor else "No hypervisor flag observed; this does not establish a physical environment.",
        "agent_count": len(AGENTS), "agent_ids": [a.agent_id for a in AGENTS],
        "capabilities": {
            "role_registry": len(AGENTS) == 1, "coordinator_module": importlib.util.find_spec("babymind.coordinator") is not None,
            "research_module": importlib.util.find_spec("babymind.research") is not None,
            "sandbox_module": importlib.util.find_spec("babymind.sandbox") is not None,
            "model_endpoint_verified": False, "network_research_executed": False,
            "shell_execution_granted_by_cognitive_core": False,
        },
    }

class CognitiveCore:
    """Persistent operational self-model and safe, auditable cognitive cycle."""
    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            home = Path(os.getenv("BABYMIND_HOME", Path.home() / ".babymind")).expanduser()
            database_path = home / "cognitive.sqlite3"
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.secure = SecureTextStore(self.database_path.with_suffix(".key"))
        self.lock = threading.RLock()
        self._initialise()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _initialise(self) -> None:
        with self.lock:
            db = self._connect()
            try:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS goals (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, agent_id TEXT NOT NULL, observation TEXT NOT NULL, understanding TEXT NOT NULL, plan TEXT NOT NULL, action TEXT NOT NULL, expected TEXT NOT NULL, outcome TEXT NOT NULL, verified INTEGER NOT NULL, reflection TEXT NOT NULL, learning TEXT NOT NULL, confidence REAL NOT NULL);
                """)
                if db.execute("SELECT 1 FROM identity WHERE id=1").fetchone() is None:
                    identity = {"name": "BabyMind", "kind": "local AI software system",
                        "purpose": "Help users through its configured model, tools, memory, and approved goals.",
                        "identity_version": 1,
                        "identity_policy": "Describe implementation and observed state; never assert consciousness as fact.",
                        "created_at": _now()}
                    stamp = _now()
                    db.execute("INSERT INTO identity VALUES (1,?,?,?)",
                        (self.secure.encrypt(json.dumps(identity, ensure_ascii=False)), stamp, stamp))
                db.commit()
            finally:
                db.close()

    def identity(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try: row = db.execute("SELECT content FROM identity WHERE id=1").fetchone()
            finally: db.close()
        return json.loads(self.secure.decrypt(row["content"]))

    def active_goals(self, limit: int = 10) -> list[dict[str, str]]:
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute("SELECT id,title,description,status,created_at FROM goals WHERE status='active' ORDER BY created_at LIMIT ?", (max(1,min(limit,50)),)).fetchall()
            finally: db.close()
        return [{"id":r["id"],"title":self.secure.decrypt(r["title"]),"description":self.secure.decrypt(r["description"]),"status":r["status"],"created_at":r["created_at"]} for r in rows]

    def recent_notes(self, limit: int = 10) -> list[dict[str, str]]:
        """Retrieve durable notes and research questions for future cycles."""
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,kind,content,created_at FROM notes ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(limit, 30)),)
                ).fetchall()
            finally:
                db.close()
        return [{
            "id": row["id"], "kind": row["kind"],
            "content": self.secure.decrypt(row["content"]),
            "created_at": row["created_at"],
        } for row in rows]

    def recent_experiences(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve previous reflections and lessons so later cycles can use them."""
        with self.lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT id,created_at,agent_id,verified,confidence,reflection,learning "
                    "FROM cycles ORDER BY id DESC LIMIT ?", (max(1, min(limit, 20)),)
                ).fetchall()
            finally:
                db.close()
        return [{
            "cycle_id": row["id"], "created_at": row["created_at"],
            "agent_id": row["agent_id"], "verified": bool(row["verified"]),
            "confidence": row["confidence"],
            "reflection": self.secure.decrypt(row["reflection"]),
            "learning": self.secure.decrypt(row["learning"]),
        } for row in rows]

    def context_for_agent(self, agent: AgentSpec) -> str:
        env = environment_snapshot()
        return ("COGNITIVE CORE / OPERATIONAL SELF-MODEL (for the single BabyMind identity)\n"
            f"Identity: {self.identity()['name']} — {self.identity()['kind']}.\n"
            f"Current role: {agent.agent_id} {agent.name}; one identity is active.\n"
            f"Observed host: {env['distribution']}; {env['system']} {env['architecture']}; Python {env['python']}.\n"
            f"Known boundaries: {json.dumps(env['capabilities'], sort_keys=True)}.\n"
            f"Active goals: {json.dumps(self.active_goals(5), ensure_ascii=False)}.\n"
            f"Recent learning: {json.dumps(self.recent_experiences(3), ensure_ascii=False)}.\n"
            f"Recent research notes: {json.dumps(self.recent_notes(3), ensure_ascii=False)}.\n"
            "This is operational context, not evidence of subjective consciousness. Never claim an unverified capability or action.")

    def status(self) -> dict[str, Any]:
        with self.lock:
            db = self._connect()
            try:
                cycles = db.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
                notes = db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
                latest = db.execute("SELECT id,created_at,agent_id,verified,confidence FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
            finally: db.close()
        return {"identity":self.identity(),"environment":environment_snapshot(),"active_goals":self.active_goals(),
            "cycles":cycles,"notes":notes,"latest_cycle":dict(latest) if latest else None,"consciousness_claim":False}

    def _apply_action(self, action: dict[str, Any]) -> tuple[str, bool]:
        kind = str(action.get("type", "wait"))
        if kind not in VALID_ACTIONS: raise ValueError(f"Unsupported cognitive action: {kind}")
        stamp = _now()
        with self.lock:
            db = self._connect()
            try:
                if kind == "create_goal":
                    title, desc = _clean(action.get("title"),180), _clean(action.get("description"))
                    if not title: raise ValueError("A goal requires a title.")
                    goal_id = uuid.uuid4().hex
                    db.execute("INSERT INTO goals VALUES (?,?,?,'active',?,?)",(goal_id,self.secure.encrypt(title),self.secure.encrypt(desc),stamp,stamp))
                    db.commit()
                    return f"Created local goal {goal_id}: {title}", db.execute("SELECT 1 FROM goals WHERE id=?",(goal_id,)).fetchone() is not None
                if kind == "complete_goal":
                    goal_id = _clean(action.get("goal_id"),80)
                    cur = db.execute("UPDATE goals SET status='completed',updated_at=? WHERE id=? AND status='active'",(stamp,goal_id))
                    db.commit()
                    return (f"Completed goal {goal_id}" if cur.rowcount else f"No active goal matched {goal_id}"), cur.rowcount == 1
                if kind in {"record_question","write_note"}:
                    content = _clean(action.get("content") or action.get("question"))
                    if not content: raise ValueError(f"{kind} requires content.")
                    note_id = uuid.uuid4().hex
                    db.execute("INSERT INTO notes VALUES (?,?,?,?)",(note_id,kind,self.secure.encrypt(content),stamp))
                    db.commit()
                    return f"Saved {kind} {note_id}", db.execute("SELECT 1 FROM notes WHERE id=?",(note_id,)).fetchone() is not None
                return "Waited without changing external state.", True
            finally: db.close()

    def run_cycle(self, provider, agent_id: str = "BM-01", objective: str | None = None) -> dict[str, Any]:
        """Run one observe-understand-plan-act-verify-reflect-learn cycle."""
        normalized = str(agent_id).strip().upper()
        if normalized not in AGENT_BY_ID: raise KeyError(f"Unknown agent ID: {normalized}")
        agent = AGENT_BY_ID[normalized]
        observation, goals = environment_snapshot(), self.active_goals(10)
        experiences = self.recent_experiences(8)
        notes = self.recent_notes(10)
        roster = [{"id":a.agent_id,"name":a.name,"phase":a.phase} for a in AGENTS]
        system = ("You are BabyMind's cognitive cycle, one software system using a shared local model. "
            "Do not claim consciousness, feelings, or proof of simulation. Use only observable facts. "
            "Choose one small reversible useful action. Never request shell execution, arbitrary code, "
            "network access, file deletion, credential access, or external side effects. Investigate simulation "
            "questions only as falsifiable observable hypotheses; assume neither answer. Return one JSON object "
            "with understanding, plan, action, and expected. action.type must be "
            "create_goal, complete_goal, record_question, write_note, or wait. create_goal needs title and description; "
            "complete_goal needs goal_id; record_question/write_note need content. Return only understanding, plan, action, and expected. No extra prose.")
        user = ("OBSERVATION:\n"+json.dumps(observation,ensure_ascii=False)+
            "\nACTIVE GOALS:\n"+json.dumps(goals,ensure_ascii=False)+
            "\nRECENT EXPERIENCES AND LEARNINGS:\n"+json.dumps(experiences,ensure_ascii=False)+
            "\nPERSISTENT RESEARCH NOTES:\n"+json.dumps(notes,ensure_ascii=False)+
            "\nBABYMIND IDENTITY:\n"+json.dumps(roster,ensure_ascii=False)+
            "\nCURRENT ROLE:\n"+agent_instructions(agent)+
            "\nSELECTED GOAL OBJECTIVE:\n"+_clean(objective, 1000)+
            "\nIf an objective is supplied, work only toward it using permitted local actions. Break it into small verifiable steps; do not claim completion until the goal is explicitly completed and read-back verified."+
            "\nChoose a useful next step and return the structured cycle.")
        complete_for = getattr(provider, "complete_for", None)
        generate = (lambda system_prompt, user_prompt: complete_for(normalized, system_prompt, user_prompt)) if callable(complete_for) else provider.complete
        raw = generate(system,user).strip()
        if raw.startswith(chr(96)*3): raw = raw.split("\n",1)[-1].removesuffix(chr(96)*3).strip()
        try: result = json.loads(raw)
        except json.JSONDecodeError as error: raise ValueError(f"Cognitive planning response was not valid JSON: {error.msg}") from error
        if not isinstance(result,dict): raise ValueError("Cognitive planning response must be a JSON object.")
        action = result.get("action")
        if not isinstance(action,dict): raise ValueError("Cognitive planning response must contain an action object.")
        understanding,plan = _clean(result.get("understanding")),_clean(result.get("plan"))
        expected = _clean(result.get("expected"))
        outcome,verified = self._apply_action(action)

        reflection_system = (
            "You are BabyMind performing the post-action reflection stage. Use the supplied observation, "
            "prediction, actual action result, and verification flag. Distinguish what was verified from "
            "what remains uncertain. Do not claim consciousness or invent experiences. Return one JSON object "
            "with reflection, learning, and confidence (0..1). No extra prose."
        )
        reflection_user = json.dumps({
            "observation": observation, "understanding": understanding, "plan": plan,
            "action": action, "expected": expected, "actual_outcome": outcome,
            "verified": verified, "prior_experiences": experiences,
        }, ensure_ascii=False)
        reflection_error = ""
        try:
            reflection_raw = generate(reflection_system, reflection_user).strip()
            if reflection_raw.startswith(chr(96)*3):
                reflection_raw = reflection_raw.split("\n",1)[-1].removesuffix(chr(96)*3).strip()
            reflection_result = json.loads(reflection_raw)
            if not isinstance(reflection_result,dict):
                raise ValueError("Reflection response must be a JSON object.")
        except Exception as error:
            reflection_error = str(error)[:300]
            reflection_result = {
                "reflection": "Post-action reflection failed; the action outcome remains recorded.",
                "learning": "A failed reflection must be retried and must not be treated as successful learning.",
                "confidence": 0.0,
            }
        reflection = _clean(reflection_result.get("reflection"))
        learning = _clean(reflection_result.get("learning"))
        try: confidence = float(reflection_result.get("confidence",0.5))
        except (TypeError,ValueError): confidence = 0.5
        confidence = max(0.0,min(1.0,confidence)) if math.isfinite(confidence) else 0.0
        stamp = _now()
        encrypted = [self.secure.encrypt(json.dumps(observation,ensure_ascii=False)),
            self.secure.encrypt(understanding),self.secure.encrypt(plan),
            self.secure.encrypt(json.dumps(action,ensure_ascii=False)),self.secure.encrypt(expected),
            self.secure.encrypt(outcome),self.secure.encrypt(reflection),self.secure.encrypt(learning)]
        with self.lock:
            db = self._connect()
            try:
                db.execute("INSERT INTO cycles (created_at,agent_id,observation,understanding,plan,action,expected,outcome,verified,reflection,learning,confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (stamp,normalized,*encrypted[:6],int(verified),*encrypted[6:],confidence))
                cycle_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.commit()
            finally: db.close()
        return {"cycle_id":cycle_id,"agent_id":normalized,"observed":observation,
            "understanding":understanding,"plan":plan,"action":action,"expected":expected,
            "outcome":outcome,"verified":verified,"reflection":reflection,"learning":learning,"reflection_error":reflection_error,
            "confidence":confidence,"active_goals":self.active_goals()}
