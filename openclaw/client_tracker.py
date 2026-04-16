"""
Client Tracker — stores client preferences, concerns, and requirements.

Mines preferences from email analysis and manual input. Provides client profiles
that help Bob tailor communication and project execution.

Uses the same jobs.db SQLite database for co-location with job data.
"""

import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("openclaw.client_tracker")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.189:11434")

router = APIRouter(prefix="/clients", tags=["clients"])

def _ollama_chat_preference_extract(prompt: str) -> Optional[str]:
    """POST to Ollama /api/chat; return assistant text or None."""
    if not OLLAMA_HOST.strip():
        return None
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        body = json.dumps(
            {
                "model": os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen3:8b"),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 200},
            }
        ).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        text = (data.get("message") or {}).get("content") or ""
        if text.strip():
            logger.debug("ollama_preference_extraction_success")
        return text.strip() or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.debug("Ollama preference extract failed: %s", e)
        return None




class ClientInfo(BaseModel):
    email: str = ""
    phone: str = ""
    address: str = ""
    company: str = ""
    notes: str = ""
    project_type: str = ""


class ClientPreference(BaseModel):
    preference_type: str  # preference, concern, requirement, style
    content: str
    source: str = "manual"


class ClientTracker:
    """Tracks client preferences, concerns, and requirements."""

    def __init__(self, db_path: str = "/app/data/jobs.db"):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                company TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                project_type TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                preference_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'manual',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_client_prefs_name ON client_preferences(client_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_client_prefs_type ON client_preferences(preference_type)")
        conn.commit()
        conn.close()
        logger.info("Client tracker DB initialized at %s", self._db_path)

    def upsert_client(
        self, name: str, email: str = "", phone: str = "", address: str = "",
        company: str = "", notes: str = "", project_type: str = "", source: str = "",
    ) -> dict:
        """Create or update a client contact record."""
        now = datetime.utcnow().isoformat()
        existing = self._conn.execute(
            "SELECT * FROM clients WHERE name = ?", (name.lower(),)
        ).fetchone()

        if existing:
            # Update only non-empty fields
            updates = []
            params = []
            for field, val in [("email", email), ("phone", phone), ("address", address),
                               ("company", company), ("notes", notes),
                               ("project_type", project_type), ("source", source)]:
                if val:
                    updates.append(f"{field} = ?")
                    params.append(val)
            if updates:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(name.lower())
                self._conn.execute(
                    f"UPDATE clients SET {', '.join(updates)} WHERE name = ?", params
                )
                self._conn.commit()
            return self.get_client(name)
        else:
            self._conn.execute(
                "INSERT INTO clients (name, email, phone, address, company, notes, project_type, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name.lower(), email, phone, address, company, notes, project_type, source, now, now),
            )
            self._conn.commit()
            logger.info("Client created: %s", name)
            return self.get_client(name)

    def get_client(self, name: str) -> dict:
        """Get a client's contact record."""
        row = self._conn.execute(
            "SELECT * FROM clients WHERE name = ?", (name.lower(),)
        ).fetchone()
        if not row:
            return {}
        return dict(row)

    def update_client_from_email(self, client_name: str, sender_email: str, sender_name: str = ""):
        """Auto-update client contact info when we see their email."""
        existing = self.get_client(client_name)
        if existing:
            if not existing.get("email") and sender_email:
                self.upsert_client(client_name, email=sender_email)
        else:
            self.upsert_client(client_name, email=sender_email, source="email")

    def add_preference(self, client_name: str, preference_type: str, content: str, source: str = "manual"):
        """Add a client preference/concern/requirement."""
        # Deduplicate: don't store the exact same content for the same client
        existing = self._conn.execute(
            "SELECT id FROM client_preferences WHERE client_name = ? AND content = ?",
            (client_name.lower(), content),
        ).fetchone()
        if existing:
            return

        self._conn.execute(
            "INSERT INTO client_preferences (client_name, preference_type, content, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (client_name.lower(), preference_type, content, source, datetime.utcnow().isoformat()),
        )
        self._conn.commit()
        logger.info("Client preference added: %s [%s] %s", client_name, preference_type, content[:60])

    def get_client_profile(self, client_name: str) -> dict:
        """Return full client profile: contact info + preferences."""
        # Contact record
        contact = self.get_client(client_name)

        # Preferences
        rows = self._conn.execute(
            "SELECT * FROM client_preferences WHERE client_name = ? ORDER BY created_at DESC",
            (client_name.lower(),),
        ).fetchall()

        profile = {
            "client_name": client_name,
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
            "address": contact.get("address", ""),
            "company": contact.get("company", ""),
            "project_type": contact.get("project_type", ""),
            "notes": contact.get("notes", ""),
            "preferences": [],
            "concerns": [],
            "requirements": [],
            "style": [],
        }

        for row in rows:
            entry = {
                "content": row["content"],
                "source": row["source"],
                "created_at": row["created_at"],
            }
            ptype = row["preference_type"]
            if ptype in profile:
                profile[ptype].append(entry)
            else:
                profile["preferences"].append(entry)

        return profile

    def get_all_clients(self) -> list[str]:
        """Return list of all tracked client names."""
        rows = self._conn.execute(
            "SELECT DISTINCT client_name FROM client_preferences ORDER BY client_name"
        ).fetchall()
        return [row["client_name"] for row in rows]

    def extract_preferences_from_analysis(
        self, client_name: str, sender_name: str, subject: str, snippet: str, analysis_summary: str
    ) -> list[dict]:
        """Use a cheap LLM call to extract preferences from an email analysis.

        Returns list of {type, content} dicts. Stores them in the DB.
        """
        prompt = (
            f"Extract any client preferences, concerns, requirements, or communication style "
            f"from this email. The client is {client_name}.\n\n"
            f"From: {sender_name}\n"
            f"Subject: {subject}\n"
            f"Summary: {analysis_summary}\n"
            f"Preview: {snippet[:300]}\n\n"
            f"Return a JSON array of objects with 'type' (preference/concern/requirement/style) "
            f"and 'content' (the specific preference). Return [] if none found. "
            f"Focus on: scheduling preferences, product preferences, budget concerns, "
            f"communication style, specific worries. Be specific. Max 3 items."
        )

        try:
            content = _ollama_chat_preference_extract(prompt)
            if content is None:
                api_key = os.getenv("OPENAI_API_KEY", "")
                if not api_key:
                    return []
                logger.warning("using_openai_for_client_preferences — Ollama unavailable")
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                    temperature=0.2,
                )
                content = response.choices[0].message.content.strip()
            else:
                content = content.strip()
            # Strip markdown fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            prefs = json.loads(content)
            if not isinstance(prefs, list):
                return []

            results = []
            for pref in prefs[:3]:
                ptype = pref.get("type", "preference")
                pcontent = pref.get("content", "")
                if ptype and pcontent:
                    self.add_preference(client_name, ptype, pcontent, source=f"email:{subject[:50]}")
                    results.append({"type": ptype, "content": pcontent})

            # Rule-based fallback: always record the contact event so the table
            # has at least one row per client even when LLM returns nothing.
            if not results and subject:
                self.add_preference(
                    client_name,
                    "contact",
                    f"Emailed about: {subject[:100]}",
                    source=f"email_auto:{subject[:50]}",
                )
                results.append({"type": "contact", "content": subject[:100]})

            return results
        except Exception as e:
            logger.debug("Client preference extraction failed: %s", e)
            # Minimal fallback even on full exception.
            if subject:
                try:
                    self.add_preference(
                        client_name,
                        "contact",
                        f"Emailed about: {subject[:100]}",
                        source="email_fallback",
                    )
                except Exception:
                    pass
            return []

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ---------------------------------------------------------------------------
# Module-level state (initialized from main.py)
# ---------------------------------------------------------------------------
_tracker: Optional[ClientTracker] = None


def init(tracker: ClientTracker):
    global _tracker
    _tracker = tracker


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@router.get("/{name}/profile")
async def get_client_profile(name: str):
    if not _tracker:
        return JSONResponse(status_code=503, content={"error": "Client tracker not initialized"})
    return _tracker.get_client_profile(name)


@router.post("/{name}/info")
async def update_client_info(name: str, info: ClientInfo):
    """Create or update client contact info."""
    if not _tracker:
        return JSONResponse(status_code=503, content={"error": "Client tracker not initialized"})
    result = _tracker.upsert_client(
        name, email=info.email, phone=info.phone, address=info.address,
        company=info.company, notes=info.notes, project_type=info.project_type,
    )
    return {"status": "ok", "client": result}


@router.post("/{name}/preference")
async def add_client_preference(name: str, pref: ClientPreference):
    if not _tracker:
        return JSONResponse(status_code=503, content={"error": "Client tracker not initialized"})
    _tracker.add_preference(name, pref.preference_type, pref.content, pref.source)
    return {"status": "ok", "client": name}


@router.get("/")
async def list_clients():
    if not _tracker:
        return JSONResponse(status_code=503, content={"error": "Client tracker not initialized"})
    return {"clients": _tracker.get_all_clients()}
