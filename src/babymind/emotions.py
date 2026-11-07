"""Lightweight persistent affect state for BabyMind (computational, not subjective feelings)."""
from __future__ import annotations
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from .secure_store import SecureTextStore

_LOCK = threading.RLock()
_BASE = {"joy": 0.25, "curiosity": 0.35, "calm": 0.60, "confidence": 0.50, "frustration": 0.05, "concern": 0.10}
_LEXICON = {
    "joy": ({"happy","great","awesome","wonderful","thanks","thankful","love","excited","good","success","glad"}, 0.10),
    "curiosity": ({"why","how","wonder","curious","learn","explore","understand","question","discover"}, 0.09),
    "calm": ({"okay","fine","peaceful","safe","resolved","clear","relaxed"}, 0.06),
    "confidence": ({"done","working","fixed","achieved","verified","progress","confident"}, 0.08),
    "frustration": ({"angry","annoyed","frustrated","broken","failed","wrong","hate","stuck","terrible"}, 0.12),
    "concern": ({"worried","scared","afraid","risk","danger","hurt","pain","problem","urgent","sad"}, 0.10),
}
_LABELS = {"joy":"content","curiosity":"curious","calm":"calm","confidence":"confident","frustration":"frustrated","concern":"concerned"}

class EmotionSystem:
    """A small decaying affect model, persisted locally and encrypted at rest."""
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secure = SecureTextStore(self.path.with_suffix(".key"))
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS affect_state (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT NOT NULL, updated_at TEXT NOT NULL)")
            if not db.execute("SELECT 1 FROM affect_state WHERE id=1").fetchone():
                db.execute("INSERT INTO affect_state VALUES (1, ?, ?)", (self.secure.encrypt(json.dumps(_BASE)), self._now()))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _connect(self):
        db=sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA secure_delete=ON")
        return db

    def state(self):
        with _LOCK:
            db=self._connect()
            try: row=db.execute("SELECT content,updated_at FROM affect_state WHERE id=1").fetchone()
            finally: db.close()
        values=json.loads(self.secure.decrypt(row[0]))
        dominant=max(values, key=values.get)
        return {"values":values,"dominant":dominant,"label":_LABELS[dominant],"updated_at":row[1],
                "notice":"These are modelled internal signals, not evidence of subjective experience."}

    def observe(self, text: str):
        words=set(re.findall(r"[a-z']+", str(text).casefold()))
        with _LOCK:
            current=self.state()["values"]
            # Gradual return toward baseline prevents one message dominating the mood.
            updated={key: round(base+(current[key]-base)*0.88,3) for key,base in _BASE.items()}
            for key,(terms,weight) in _LEXICON.items():
                hits=len(words.intersection(terms))
                if hits:
                    updated[key]=round(min(1.0,updated[key]+min(0.30,hits*weight)),3)
            if updated["frustration"] > 0.55:
                updated["calm"]=round(max(0.0,updated["calm"]-0.08),3)
            stamp=self._now()
            db=self._connect()
            try:
                db.execute("UPDATE affect_state SET content=?,updated_at=? WHERE id=1",
                           (self.secure.encrypt(json.dumps(updated)),stamp))
                db.commit()
            finally: db.close()
        return self.state()

    def context(self):
        state=self.state()
        values=", ".join(f"{name}={value:.2f}" for name,value in state["values"].items())
        return ("BABYMIND AFFECT MODEL: " + values + f". Current dominant state: {state['label']}. "
                "Treat these as computational signals that can shape tone and priorities, not as proof of conscious feeling. "
                "Respond with empathy and natural emotional expression when appropriate; never claim literal human feelings.")
