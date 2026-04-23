"""
Action ID store — Phase 1 foundation.

Persists per-message action contexts in SQLite so inbound replies can be
resolved back to the correct action slot and payload context.

This module is intentionally NOT wired to any handler or executor.
Execution is Phase 4. Here we only store, look up, and expire action IDs.

DB default: /data/x_intake/reply_actions.db (the existing Docker volume).
Pass db_path= to override (e.g. a tmp path in unit tests).
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

_DEFAULT_DB = Path("/data/x_intake/reply_actions.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS action_contexts (
    action_id    TEXT    PRIMARY KEY,
    created_at   REAL    NOT NULL,
    expires_at   REAL    NOT NULL,
    slots_json   TEXT    NOT NULL,
    context_json TEXT    NOT NULL,
    used_at      REAL,
    used_slot    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ac_expires ON action_contexts(expires_at);
"""


@dataclass(frozen=True)
class ActionContext:
    action_id: str
    created_at: float
    expires_at: float
    valid_slots: FrozenSet[int]
    context: Dict[str, Any]   # url, author, summary, etc.
    used_at: Optional[float]
    used_slot: Optional[int]

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def used(self) -> bool:
        return self.used_at is not None


class ActionStore:
    """Thread-safe SQLite store for reply-action contexts."""

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        valid_slots: List[int],
        context: Dict[str, Any],
        expiry_seconds: int = 86400,
    ) -> str:
        """
        Store a new action context and return its opaque action_id (12-char hex).

        *valid_slots* — which slot numbers are active for this message.
        *context*     — arbitrary dict (url, author, summary, etc.) for handlers.
        *expiry_seconds* — how long (seconds) this action ID is valid.
        """
        action_id = secrets.token_hex(6)  # 6 bytes → 12 hex chars
        now = time.time()
        expires_at = now + expiry_seconds
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO action_contexts VALUES (?,?,?,?,?,NULL,NULL)",
                (
                    action_id,
                    now,
                    expires_at,
                    json.dumps(sorted(valid_slots)),
                    json.dumps(context),
                ),
            )
        return action_id

    def lookup(self, action_id: str) -> Optional[ActionContext]:
        """
        Return the ActionContext for *action_id*, or None if not found.

        Does NOT delete expired rows — call prune() separately.
        Callers should check .expired on the returned context.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT action_id,created_at,expires_at,slots_json,context_json,"
                "used_at,used_slot FROM action_contexts WHERE action_id=?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return ActionContext(
            action_id=row[0],
            created_at=row[1],
            expires_at=row[2],
            valid_slots=frozenset(json.loads(row[3])),
            context=json.loads(row[4]),
            used_at=row[5],
            used_slot=row[6],
        )

    def mark_used(self, action_id: str, slot: int) -> bool:
        """
        Mark an action ID as consumed so it cannot be executed again.

        Returns True if the row was updated, False if not found or already used.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE action_contexts SET used_at=?,used_slot=? "
                "WHERE action_id=? AND used_at IS NULL",
                (time.time(), slot, action_id),
            )
            return cur.rowcount == 1

    def prune(self, before: Optional[float] = None) -> int:
        """Delete expired rows. Returns the count removed."""
        cutoff = before if before is not None else time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM action_contexts WHERE expires_at < ?", (cutoff,)
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
