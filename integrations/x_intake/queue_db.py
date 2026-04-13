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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT    NOT NULL,
    author         TEXT    DEFAULT '',
    post_type      TEXT    DEFAULT 'info',
    relevance      INTEGER DEFAULT 0,
    summary        TEXT    DEFAULT '',
    action         TEXT    DEFAULT 'none',
    suggested_dest TEXT    DEFAULT '',
    status         TEXT    NOT NULL DEFAULT 'pending',
    source         TEXT    DEFAULT 'imessage',
    poly_signals   TEXT    DEFAULT '{}',
    has_transcript INTEGER DEFAULT 0,
    created_at     REAL    NOT NULL,
    reviewed_at    REAL,
    review_note    TEXT
);
CREATE INDEX IF NOT EXISTS idx_xi_status  ON x_intake_queue(status);
CREATE INDEX IF NOT EXISTS idx_xi_created ON x_intake_queue(created_at DESC);
"""

_PRUNE_DAYS = 30


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
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
) -> int:
    """Insert a new analyzed item and return its row id.

    Returns 0 on failure (never raises — queue failures must not crash intake).
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
                has_transcript, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
