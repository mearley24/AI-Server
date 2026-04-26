"""X API usage tracking and daily limit enforcement.

Logs every API call and enforces X_DAILY_READ_LIMIT (default 100 requests/day).
All tracking is local — nothing is sent to X or any external service.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_reads_used(conn: sqlite3.Connection, date: str | None = None) -> int:
    """Return total request_count for today (UTC)."""
    d = date or _today_utc()
    row = conn.execute(
        "SELECT COALESCE(SUM(request_count), 0) FROM x_api_usage WHERE ts LIKE ?",
        (f"{d}%",),
    ).fetchone()
    return int(row[0]) if row else 0


def daily_limit() -> int:
    return int(os.environ.get("X_DAILY_READ_LIMIT", "100"))


def check_limit(conn: sqlite3.Connection) -> tuple[bool, int, int]:
    """Return (within_limit, used, limit)."""
    used = daily_reads_used(conn)
    lim = daily_limit()
    return used < lim, used, lim


def log_usage(
    conn: sqlite3.Connection,
    endpoint: str,
    request_count: int = 1,
    item_count: int = 0,
    estimated_cost_units: int = 0,
    status: str = "ok",
) -> None:
    conn.execute(
        """INSERT INTO x_api_usage (ts, endpoint, request_count, item_count, estimated_cost_units, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            endpoint,
            request_count,
            item_count,
            estimated_cost_units,
            status,
        ),
    )
    conn.commit()


def usage_summary(conn: sqlite3.Connection) -> dict:
    """Return a summary dict for the dashboard status endpoint."""
    today = _today_utc()
    used = daily_reads_used(conn, today)
    lim = daily_limit()
    last_row = conn.execute(
        "SELECT ts, endpoint, status FROM x_api_usage ORDER BY id DESC LIMIT 1"
    ).fetchone()
    total_items = conn.execute("SELECT COUNT(*) FROM x_items").fetchone()[0]
    return {
        "daily_reads_used":  used,
        "daily_reads_limit": lim,
        "within_limit":      used < lim,
        "last_call_ts":      last_row["ts"] if last_row else None,
        "last_call_endpoint": last_row["endpoint"] if last_row else None,
        "last_call_status":   last_row["status"] if last_row else None,
        "total_items_stored": total_items,
    }
