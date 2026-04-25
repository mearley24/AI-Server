"""Lightweight SQLite queue for X intake review visibility.

Every analyzed post is written here with a status:
  auto_approved  — relevance >= 70 (routed by background pipeline as normal)
  pending        — relevance 30-69 (visible in dashboard, awaiting human confirmation)
  auto_rejected  — relevance < 30  (filtered; visible but not routed)
  approved       — human-approved from pending (feedback signal)
  rejected       — human-rejected from pending (feedback signal)
  error          — analysis failed

The table is append-only; statuses are updated in-place for human decisions.
Rows older than 30 days are pruned on each write to keep the file small.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path("/data/x_intake/queue.db")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS x_intake_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL,
    author          TEXT    DEFAULT '',
    post_type       TEXT    DEFAULT 'info',
    relevance       INTEGER DEFAULT 0,
    summary         TEXT    DEFAULT '',
    action          TEXT    DEFAULT 'none',
    suggested_dest  TEXT    DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'pending',
    source          TEXT    DEFAULT 'imessage',
    poly_signals    TEXT    DEFAULT '{}',
    has_transcript  INTEGER DEFAULT 0,
    transcript_path TEXT    DEFAULT '',
    analyzed        INTEGER DEFAULT 0,
    created_at      REAL    NOT NULL,
    reviewed_at     REAL,
    review_note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_xi_status     ON x_intake_queue(status);
CREATE INDEX IF NOT EXISTS idx_xi_created    ON x_intake_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_xi_transcript ON x_intake_queue(has_transcript, analyzed);
"""

# Columns added after initial schema — applied to existing databases.
_MIGRATE_COLUMNS = [
    "ALTER TABLE x_intake_queue ADD COLUMN transcript_path TEXT DEFAULT ''",
    "ALTER TABLE x_intake_queue ADD COLUMN analyzed INTEGER DEFAULT 0",
    "ALTER TABLE x_intake_queue ADD COLUMN error_msg TEXT DEFAULT ''",
    # v2: inbound sender identity (guid masked at API layer) + enriched context
    "ALTER TABLE x_intake_queue ADD COLUMN sender_guid TEXT DEFAULT ''",
    "ALTER TABLE x_intake_queue ADD COLUMN context_json TEXT DEFAULT '{}'",
]

_PRUNE_DAYS = 30


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
    # Apply schema migrations for existing databases (silently skip if already done).
    for stmt in _MIGRATE_COLUMNS:
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    return conn


def _infer_status(relevance: int) -> str:
    """Classify item status from LLM relevance score."""
    if relevance >= 70:
        return "auto_approved"
    if relevance < 30:
        return "auto_rejected"
    return "pending"


def _infer_dest(relevance: int, has_signals: bool) -> str:
    """Human-readable routing destination label."""
    if relevance >= 70 or has_signals:
        return "polymarket+memory"
    if relevance >= 50:
        return "polymarket"
    if relevance >= 40:
        return "polymarket_intel"
    return "discard"


def _prune_old(conn: sqlite3.Connection) -> None:
    """Remove rows older than PRUNE_DAYS (best-effort; never raises)."""
    try:
        cutoff = time.time() - (_PRUNE_DAYS * 86400)
        conn.execute("DELETE FROM x_intake_queue WHERE created_at < ?", (cutoff,))
        conn.commit()
    except Exception:
        pass


def enqueue(
    url: str,
    author: str = "",
    post_type: str = "info",
    relevance: int = 0,
    summary: str = "",
    action: str = "none",
    source: str = "imessage",
    poly_signals: Optional[dict] = None,
    has_transcript: bool = False,
    transcript_path: str = "",
    sender_guid: str = "",
) -> int:
    """Insert a new analyzed item and return its row id.

    Returns 0 on failure (never raises — queue failures must not crash intake).
    sender_guid is stored for deferred context enrichment; never shown raw in UI.
    """
    try:
        status = _infer_status(relevance)
        has_sig = bool((poly_signals or {}).get("signals"))
        suggested_dest = _infer_dest(relevance, has_sig)
        conn = _conn()
        cur = conn.execute(
            """INSERT INTO x_intake_queue
               (url, author, post_type, relevance, summary, action,
                suggested_dest, status, source, poly_signals,
                has_transcript, transcript_path, sender_guid, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url,
                author,
                post_type,
                relevance,
                (summary or "")[:2000],
                (action or "none")[:500],
                suggested_dest,
                status,
                source,
                json.dumps(poly_signals or {}),
                int(bool(has_transcript)),
                (transcript_path or "")[:500],
                (sender_guid or "")[:200],
                time.time(),
            ),
        )
        conn.commit()
        row_id = cur.lastrowid or 0
        _prune_old(conn)
        conn.close()
        return row_id
    except Exception:
        return 0


def get_queue(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Return items newest-first, optionally filtered by status."""
    try:
        conn = _conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM x_intake_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM x_intake_queue ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = [dict(r) for r in rows]
        conn.close()
        return result
    except Exception:
        return []


def update_status(item_id: int, status: str, note: str = "") -> bool:
    """Update item status.  Returns True if a row was changed."""
    try:
        conn = _conn()
        cur = conn.execute(
            "UPDATE x_intake_queue SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (status, time.time(), (note or "")[:500], item_id),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed
    except Exception:
        return False


def set_analyzed(row_id: int, value: int, error_msg: str = "") -> None:
    """Set analyzed=value (1=success, 2=failed) and optional error_msg on a queue row.

    Used by main.py to mark text-only posts as analyzed=1 immediately after the
    LLM analysis completes (transcript posts are marked by transcript_analyst).
    Never raises — caller must not be crashed by a DB write failure.
    """
    if not row_id:
        return
    try:
        conn = _conn()
        conn.execute(
            "UPDATE x_intake_queue SET analyzed = ?, error_msg = ? WHERE id = ?",
            (value, (error_msg or "")[:500], row_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def update_context(row_id: int, sender_guid: str, context_json: str) -> None:
    """Store the enriched context-card JSON on a queue row.

    Called asynchronously after enqueue — never raises, queue must not crash.
    context_json is the full JSON string from /api/x-intake/context-card.
    sender_guid is stored for auditability; masked at the API/UI layer.
    """
    if not row_id:
        return
    try:
        conn = _conn()
        conn.execute(
            "UPDATE x_intake_queue SET sender_guid=?, context_json=? WHERE id=?",
            ((sender_guid or "")[:200], (context_json or "{}")[:8000], row_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_stats() -> dict:
    """Return counts by status for the dashboard summary tile."""
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM x_intake_queue GROUP BY status"
        ).fetchall()
        conn.close()
        stats = {r["status"]: r["cnt"] for r in rows}
        return {
            "pending":       stats.get("pending", 0),
            "auto_approved": stats.get("auto_approved", 0),
            "auto_rejected": stats.get("auto_rejected", 0),
            "approved":      stats.get("approved", 0),
            "rejected":      stats.get("rejected", 0),
            "error":         stats.get("error", 0),
            "total":         sum(stats.values()),
        }
    except Exception:
        return {
            "pending": 0, "auto_approved": 0, "auto_rejected": 0,
            "approved": 0, "rejected": 0, "error": 0, "total": 0,
        }
