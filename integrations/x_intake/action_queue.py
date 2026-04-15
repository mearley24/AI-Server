"""X-Intake Action Queue — SQLite-backed queue for high-relevance X post actions.

Actions are created for posts with relevance >= 60% that have concrete action suggestions.
Provides a persistent queue for the team to review and act on intelligence.

DB path: /data/x_intake/action_queue.db
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("/data/x_intake/action_queue.db")


def _ensure_db() -> None:
    """Create the actions table if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                author TEXT,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                relevance INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                result TEXT
            )
        """)
        conn.commit()


@contextmanager
def _conn():
    """Context manager for DB connections with Row factory."""
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def enqueue(url: str, author: str, action_type: str, description: str, relevance: int = 0) -> int:
    """Add a new action to the queue. Returns the new action ID."""
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO actions (url, author, action_type, description, relevance) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, author, action_type, description, relevance),
        )
        return cursor.lastrowid


def get_pending(limit: int = 10) -> list[dict]:
    """Get pending actions ordered by relevance descending."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM actions WHERE status = 'pending' "
            "ORDER BY relevance DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_by_status(status: str, limit: int = 20) -> list[dict]:
    """Get actions filtered by status."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM actions WHERE status = ? "
            "ORDER BY relevance DESC, created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def update_status(action_id: int, status: str, result: Optional[str] = None) -> bool:
    """Update the status of an action. Returns True if a row was changed."""
    completed_at = datetime.utcnow().isoformat() if status in ("done", "dismissed") else None
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE actions SET status = ?, result = ?, completed_at = ? WHERE id = ?",
            (status, result, completed_at, action_id),
        )
        return cursor.rowcount > 0


def get_stats() -> dict:
    """Return counts of actions by status, plus total."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM actions GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    stats = {row["status"]: row["count"] for row in rows}
    stats["total"] = total
    return stats


def get_daily_digest() -> str:
    """Build a daily digest of pending actions for iMessage."""
    pending = get_pending(limit=10)
    if not pending:
        return ""
    lines = [f"\U0001f4cb {len(pending)} pending X-intel actions:\n"]
    for i, a in enumerate(pending, 1):
        emoji = {
            "build": "\U0001f528",
            "alpha": "\U0001f4b0",
            "tool": "\U0001f527",
            "investigate": "\U0001f50d",
        }.get(a["action_type"], "\U00002753")
        lines.append(f"{i}. {emoji} [{a['relevance']}%] {a['description'][:100]}")
    lines.append("\nReview: http://100.89.1.51:8420/proxy/x-intake/actions")
    return "\n".join(lines)
