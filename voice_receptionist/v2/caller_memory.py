"""
caller_memory.py — Symphony Smart Homes Voice Receptionist
Caller relationship management database for Bob the Conductor.

SQLite-backed store tracking:
  - Call history (count, last call, duration, outcomes)
  - Topics discussed and sentiment per call
  - D-Tools project linkage
  - Caller notes and preferences
  - Birthday / anniversary tracking for VIP service
  - REST API endpoints for Telegram bot integration
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# ─── Database Path ────────────────────────────────────────────────────────────

DB_PATH = os.getenv("CALLER_MEMORY_DB", str(Path(__file__).parent / "caller_memory.db"))


# ─── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class CallerRecord:
    """
    Represents a caller in the memory database.
    phone_number is the primary key (E.164 format).
    """
    phone_number: str
    name: str = ""
    company: str = ""
    email: str = ""
    call_count: int = 0
    last_call_at: str = ""          # ISO8601
    last_call_duration: int = 0     # seconds
    last_intent: str = ""
    last_script_used: str = ""
    total_call_seconds: int = 0
    notes: str = ""
    vip: bool = False
    birthday: str = ""              # YYYY-MM-DD
    anniversary: str = ""           # YYYY-MM-DD (project anniversary or personal)
    dtools_project_id: str = ""
    preferred_contact: str = "phone"  # phone | text | email
    systems: str = ""               # JSON list of installed systems
    created_at: str = ""
    updated_at: str = ""


@dataclass
class CallEvent:
    """
    A single call log entry linked to a caller record.
    """
    phone_number: str
    call_sid: str
    direction: str = "inbound"      # inbound | outbound
    script_used: str = ""
    intent_detected: str = ""
    duration_seconds: int = 0
    escalated: bool = False
    escalation_reason: str = ""
    summary: str = ""
    sentiment: str = "neutral"      # positive | neutral | negative
    topics: str = ""                # JSON list of topics discussed
    recording_url: str = ""
    transcription: str = ""
    steps_taken: str = ""           # JSON list of actions taken
    callback_requested: bool = False
    callback_time: str = ""
    called_at: str = ""
    id: Optional[int] = field(default=None, compare=False)


# ─── Database Manager ────────────────────────────────────────────────────────────

class CallerMemory:
    """
    SQLite-backed caller relationship manager.

    Thread safety: Uses WAL mode + per-call connections for concurrent access.
    Each method opens and closes its own connection so it's safe to call from
    multiple threads (e.g., multiple simultaneous phone calls).
    
    Note: For production use, consider using a connection pool. The current
    implementation re-opens the connection on each call for simplicity;
    the connection is per-call.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_PATH
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS callers (
                    phone_number        TEXT PRIMARY KEY,
                    name                TEXT NOT NULL DEFAULT '',
                    company             TEXT NOT NULL DEFAULT '',
                    email               TEXT NOT NULL DEFAULT '',
                    call_count          INTEGER NOT NULL DEFAULT 0,
                    last_call_at        TEXT NOT NULL DEFAULT '',
                    last_call_duration  INTEGER NOT NULL DEFAULT 0,
                    last_intent         TEXT NOT NULL DEFAULT '',
                    last_script_used    TEXT NOT NULL DEFAULT '',
                    total_call_seconds  INTEGER NOT NULL DEFAULT 0,
                    notes               TEXT NOT NULL DEFAULT '',
                    vip                 INTEGER NOT NULL DEFAULT 0,
                    birthday            TEXT NOT NULL DEFAULT '',
                    anniversary         TEXT NOT NULL DEFAULT '',
                    dtools_project_id   TEXT NOT NULL DEFAULT '',
                    preferred_contact   TEXT NOT NULL DEFAULT 'phone',
                    systems             TEXT NOT NULL DEFAULT '[]',
                    created_at          TEXT NOT NULL DEFAULT '',
                    updated_at          TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS call_events (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number        TEXT NOT NULL REFERENCES callers(phone_number),
                    call_sid            TEXT NOT NULL UNIQUE,
                    direction           TEXT NOT NULL DEFAULT 'inbound',
                    script_used         TEXT NOT NULL DEFAULT '',
                    intent_detected     TEXT NOT NULL DEFAULT '',
                    duration_seconds    INTEGER NOT NULL DEFAULT 0,
                    escalated           INTEGER NOT NULL DEFAULT 0,
                    escalation_reason   TEXT NOT NULL DEFAULT '',
                    summary             TEXT NOT NULL DEFAULT '',
                    sentiment           TEXT NOT NULL DEFAULT 'neutral',
                    topics              TEXT NOT NULL DEFAULT '[]',
                    recording_url       TEXT NOT NULL DEFAULT '',
                    transcription       TEXT NOT NULL DEFAULT '',
                    steps_taken         TEXT NOT NULL DEFAULT '[]',
                    callback_requested  INTEGER NOT NULL DEFAULT 0,
                    callback_time       TEXT NOT NULL DEFAULT '',
                    called_at           TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_call_events_phone
                    ON call_events (phone_number);
                CREATE INDEX IF NOT EXISTS idx_call_events_called_at
                    ON call_events (called_at);
            """)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that yields an auto-committing SQLite connection."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ─── Caller CRUD ─────────────────────────────────────────────────────────────

    def lookup_by_phone(self, phone_number: str) -> Optional[CallerRecord]:
        """
        Return a CallerRecord for the given phone number, or None if not found.
        """
        normalized = self._normalise_phone(phone_number)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM callers WHERE phone_number = ?", (normalized,)
            ).fetchone()
        if row:
            return self._row_to_caller(dict(row))
        return None

    def get_or_create_caller(
        self,
        phone_number: str,
        name: str = "",
        company: str = "",
    ) -> tuple[CallerRecord, bool]:
        """
        Return (CallerRecord, created: bool).
        If the caller doesn't exist, create a minimal record.
        """
        normalized = self._normalise_phone(phone_number)
        existing = self.lookup_by_phone(normalized)
        if existing:
            return existing, False

        now = datetime.utcnow().isoformat() + "Z"
        record = CallerRecord(
            phone_number=normalized,
            name=name,
            company=company,
            created_at=now,
            updated_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO callers
                    (phone_number, name, company, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (normalized, name, company, now, now),
            )
        logger.info(f"Created new caller record: {normalized} ({name})")
        return record, True

    def update_caller(
        self,
        phone_number: str,
        **kwargs,
    ) -> CallerRecord:
        """
        Update one or more fields on a caller record.

        Allowed fields: name, company, email, notes, vip, birthday,
                        anniversary, dtools_project_id, preferred_contact, systems
        """
        ALLOWED = {
            "name", "company", "email", "notes", "vip", "birthday",
            "anniversary", "dtools_project_id", "preferred_contact", "systems",
        }
        updates = {k: v for k, v in kwargs.items() if k in ALLOWED}
        if not updates:
            raise ValueError("No valid fields to update.")

        updates["updated_at"] = datetime.utcnow().isoformat() + "Z"
        normalized = self._normalise_phone(phone_number)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [normalized]

        with self._conn() as conn:
            conn.execute(
                f"UPDATE callers SET {set_clause} WHERE phone_number = ?",
                values,
            )

        result = self.lookup_by_phone(normalized)
        if result is None:
            raise ValueError(f"Caller {normalized} not found after update.")
        return result

    def delete_caller(self, phone_number: str) -> bool:
        """Delete a caller and all associated call events. Returns True if deleted."""
        normalized = self._normalise_phone(phone_number)
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM callers WHERE phone_number = ?", (normalized,)
            )
        return cursor.rowcount > 0

    # ─── Call Event Logging ────────────────────────────────────────────────────────

    def log_call(
        self,
        phone_number: str,
        call_sid: str,
        duration_seconds: int = 0,
        direction: str = "inbound",
        script_used: str | None = None,
        intent_detected: str | None = None,
        escalated: bool = False,
        escalation_reason: str = "",
        summary: str = "",
        sentiment: str = "neutral",
        topics: list[str] | None = None,
        recording_url: str = "",
        transcription: str = "",
        steps_taken: list[str] | None = None,
        callback_requested: bool = False,
        callback_time: str = "",
    ) -> CallEvent:
        """
        Log a completed call and update the caller's aggregate stats.

        Creates a caller record if one doesn't exist.

        Returns:
            The persisted CallEvent.
        """
        normalized = self._normalise_phone(phone_number)
        now = datetime.utcnow().isoformat() + "Z"

        # Ensure caller record exists
        self.get_or_create_caller(normalized)

        event = CallEvent(
            phone_number=normalized,
            call_sid=call_sid,
            direction=direction,
            script_used=script_used or "",
            intent_detected=intent_detected or "",
            duration_seconds=duration_seconds,
            escalated=escalated,
            escalation_reason=escalation_reason,
            summary=summary,
            sentiment=sentiment,
            topics=json.dumps(topics or []),
            recording_url=recording_url,
            transcription=transcription,
            steps_taken=json.dumps(steps_taken or []),
            callback_requested=callback_requested,
            callback_time=callback_time,
            called_at=now,
        )

        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO call_events
                    (phone_number, call_sid, direction, script_used, intent_detected,
                     duration_seconds, escalated, escalation_reason, summary, sentiment,
                     topics, recording_url, transcription, steps_taken,
                     callback_requested, callback_time, called_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.phone_number, event.call_sid, event.direction,
                    event.script_used, event.intent_detected, event.duration_seconds,
                    int(event.escalated), event.escalation_reason, event.summary,
                    event.sentiment, event.topics, event.recording_url,
                    event.transcription, event.steps_taken,
                    int(event.callback_requested), event.callback_time, event.called_at,
                ),
            )
            event.id = cursor.lastrowid

            # Update caller aggregate stats
            conn.execute(
                """
                UPDATE callers SET
                    call_count         = call_count + 1,
                    last_call_at       = ?,
                    last_call_duration = ?,
                    last_intent        = ?,
                    last_script_used   = ?,
                    total_call_seconds = total_call_seconds + ?,
                    updated_at         = ?
                WHERE phone_number = ?
                """,
                (
                    now, duration_seconds,
                    intent_detected or "",
                    script_used or "",
                    duration_seconds,
                    now,
                    normalized,
                ),
            )

        logger.info(
            f"Logged call: {normalized} | SID={call_sid} | "
            f"{duration_seconds}s | intent={intent_detected}"
        )
        return event

    def get_call_history(
        self,
        phone_number: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Return recent call events for a caller, newest first.
        """
        normalized = self._normalise_phone(phone_number)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM call_events
                WHERE phone_number = ?
                ORDER BY called_at DESC
                LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            if r.get("steps_taken"):
                try:
                    r["steps_taken"] = json.loads(r["steps_taken"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if r.get("topics"):
                try:
                    r["topics"] = json.loads(r["topics"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(r)
        return result

    # ─── Caller Summary (for Bob's context) ───────────────────────────────────────

    def get_caller_summary(
        self,
        phone_number: str,
    ) -> dict:
        """
        Return a structured summary of a caller for injection into Bob's system prompt.

        Returns:
            dict with keys:
              found, name, company, call_count, last_call_at,
              last_intent, systems, notes, vip, recent_topics,
              dtools_project_id, preferred_contact
        """
        record = self.lookup_by_phone(phone_number)
        if not record:
            return {"found": False, "phone_number": phone_number}

        # Fetch recent topics from last 3 calls
        history = self.get_call_history(phone_number, limit=3)
        recent_topics: list[str] = []
        for call in history:
            topics = call.get("topics", [])
            if isinstance(topics, list):
                recent_topics.extend(topics)

        systems = []
        if record.systems:
            try:
                systems = json.loads(record.systems)
            except (json.JSONDecodeError, ValueError):
                systems = [record.systems]

        return {
            "found": True,
            "phone_number": record.phone_number,
            "name": record.name,
            "company": record.company,
            "call_count": record.call_count,
            "last_call_at": record.last_call_at,
            "last_intent": record.last_intent,
            "systems": systems,
            "notes": record.notes,
            "vip": record.vip,
            "recent_topics": list(dict.fromkeys(recent_topics)),  # Deduplicated
            "dtools_project_id": record.dtools_project_id,
            "preferred_contact": record.preferred_contact,
            "birthday": record.birthday,
            "anniversary": record.anniversary,
        }

    # ─── Analytics Queries ──────────────────────────────────────────────────────────

    def get_stats(
        self,
        days: int = 30,
    ) -> dict:
        """
        Return aggregate call statistics for the past N days.
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                AS total_calls,
                    COUNT(DISTINCT phone_number) AS unique_callers,
                    SUM(duration_seconds)   AS total_seconds,
                    AVG(duration_seconds)   AS avg_seconds,
                    SUM(escalated)          AS escalations,
                    SUM(callback_requested) AS callbacks_requested
                FROM call_events
                WHERE called_at >= ?
                """,
                (cutoff,),
            ).fetchone()

            intent_rows = conn.execute(
                """
                SELECT intent_detected, COUNT(*) as count
                FROM call_events
                WHERE called_at >= ? AND intent_detected != ''
                GROUP BY intent_detected
                ORDER BY count DESC
                """,
                (cutoff,),
            ).fetchall()

            sentiment_rows = conn.execute(
                """
                SELECT sentiment, COUNT(*) as count
                FROM call_events
                WHERE called_at >= ?
                GROUP BY sentiment
                """,
                (cutoff,),
            ).fetchall()

        stats = dict(row) if row else {}
        stats["intent_breakdown"] = {r["intent_detected"]: r["count"] for r in intent_rows}
        stats["sentiment_breakdown"] = {r["sentiment"]: r["count"] for r in sentiment_rows}
        stats["period_days"] = days
        return stats

    def list_callbacks(
        self,
        pending_only: bool = True,
    ) -> list[dict]:
        """
        Return callers who requested a callback.
        """
        with self._conn() as conn:
            if pending_only:
                rows = conn.execute(
                    """
                    SELECT ce.*, c.name, c.company
                    FROM call_events ce
                    JOIN callers c ON ce.phone_number = c.phone_number
                    WHERE ce.callback_requested = 1
                    ORDER BY ce.called_at DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ce.*, c.name, c.company
                    FROM call_events ce
                    JOIN callers c ON ce.phone_number = c.phone_number
                    ORDER BY ce.called_at DESC
                    LIMIT 50
                    """
                ).fetchall()
        return [dict(r) for r in rows]

    def list_vip_callers(self) -> list[CallerRecord]:
        """Return all VIP callers."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM callers WHERE vip = 1 ORDER BY name"
            ).fetchall()
        return [self._row_to_caller(dict(r)) for r in rows]

    # ─── Telegram Bot API Methods ──────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Full-text search over caller records (name, company, phone, notes).
        Used by the Telegram bot's /search command.
        """
        like = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM callers
                WHERE name LIKE ? OR company LIKE ? OR phone_number LIKE ? OR notes LIKE ?
                ORDER BY call_count DESC
                LIMIT ?
                """,
                (like, like, like, like, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def upcoming_occasions(
        self,
        days_ahead: int = 14,
    ) -> list[dict]:
        """
        Return callers with birthdays or anniversaries in the next N days.
        Used for VIP proactive outreach.
        """
        today = date.today()
        results = []

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM callers WHERE birthday != '' OR anniversary != ''"
            ).fetchall()

        for row in rows:
            r = dict(row)
            for field_name in ("birthday", "anniversary"):
                val = r.get(field_name, "")
                if not val:
                    continue
                try:
                    occasion_date = date.fromisoformat(val)
                    # Check if it falls within the next N days (any year)
                    this_year = occasion_date.replace(year=today.year)
                    delta = (this_year - today).days
                    if 0 <= delta <= days_ahead:
                        results.append({
                            "phone_number": r["phone_number"],
                            "name": r["name"],
                            "occasion": field_name,
                            "date": str(this_year),
                            "days_until": delta,
                        })
                except (ValueError, TypeError):
                    continue

        results.sort(key=lambda x: x["days_until"])
        return results

    # ─── Internal Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_caller(row: dict) -> CallerRecord:
        """Convert a DB row dict to a CallerRecord."""
        return CallerRecord(
            phone_number=row["phone_number"],
            name=row.get("name", ""),
            company=row.get("company", ""),
            email=row.get("email", ""),
            call_count=row.get("call_count", 0),
            last_call_at=row.get("last_call_at", ""),
            last_call_duration=row.get("last_call_duration", 0),
            last_intent=row.get("last_intent", ""),
            last_script_used=row.get("last_script_used", ""),
            total_call_seconds=row.get("total_call_seconds", 0),
            notes=row.get("notes", ""),
            vip=bool(row.get("vip", 0)),
            birthday=row.get("birthday", ""),
            anniversary=row.get("anniversary", ""),
            dtools_project_id=row.get("dtools_project_id", ""),
            preferred_contact=row.get("preferred_contact", "phone"),
            systems=row.get("systems", "[]"),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    @staticmethod
    def _normalise_phone(number: str) -> str:
        """Strip all non-digit characters, add +1 prefix if needed."""
        import re
        digits = re.sub(r"\D", "", number)
        if len(digits) == 10:
            digits = "1" + digits
        return "+" + digits


# ─── Module-level singleton ───────────────────────────────────────────────────────────

caller_memory = CallerMemory()


# ─── Smoke Test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Quick smoke test using an in-memory DB."""
    import tempfile

    tmp_db = tempfile.mktemp(suffix=".db")
    try:
        mem = CallerMemory(db_path=tmp_db)

        # Create a caller
        record, created = mem.get_or_create_caller("+13035551234", name="Test User")
        assert created is True
        assert record.name == "Test User"

        # Log a call
        event = mem.log_call(
            phone_number="+13035551234",
            call_sid="CA_test_001",
            duration_seconds=90,
            intent_detected="sales_inquiry",
            sentiment="positive",
            topics=["home theater", "lighting"],
        )
        assert event.id is not None

        # Get summary
        summary = mem.get_caller_summary("+13035551234")
        assert summary["found"] is True
        assert summary["call_count"] == 1

        print("CallerMemory smoke test PASSED ✓")
    finally:
        os.unlink(tmp_db)
