#!/usr/bin/env python3
"""
api.py — FastAPI HTTP API for email monitor.

Exposes endpoints to query stored emails, get summaries, and manage state.
"""

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel

DB_PATH = os.getenv("EMAIL_DB_PATH", "/data/emails.db")

app = FastAPI(title="Email Monitor API", version="1.0.0")


class EmailRecord(BaseModel):
    id: int
    message_id: str
    sender: str
    sender_name: str
    subject: str
    category: str
    priority: str
    received_at: str
    stored_at: str
    read: bool
    responded: bool
    snippet: str
    summary: str = ""
    action_items: str = ""
    urgency: str = "fyi"


class EmailSummary(BaseModel):
    total_today: int
    unread: int
    by_category: dict[str, int]
    action_items: list[dict]


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_record(r: sqlite3.Row) -> EmailRecord:
    """Convert a SQLite row to an EmailRecord, handling missing columns."""
    return EmailRecord(
        id=r["id"],
        message_id=r["message_id"],
        sender=r["sender"],
        sender_name=r["sender_name"],
        subject=r["subject"],
        category=r["category"],
        priority=r["priority"],
        received_at=r["received_at"],
        stored_at=r["stored_at"],
        read=bool(r["read"]),
        responded=bool(r["responded"]),
        snippet=r["snippet"] or "",
        summary=r["summary"] if "summary" in r.keys() else "",
        action_items=r["action_items"] if "action_items" in r.keys() else "",
        urgency=r["urgency"] if "urgency" in r.keys() else "fyi",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "email-monitor"}


@app.get("/emails", response_model=list[EmailRecord])
async def list_emails(
    category: Optional[str] = Query(None, description="Filter by category"),
    unread: Optional[bool] = Query(None, description="Filter unread only"),
    since: Optional[str] = Query(None, description="ISO date to filter from"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List recent emails with optional filters."""
    try:
        conn = _get_db()
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category.upper())
        if unread is not None:
            conditions.append("read = ?")
            params.append(0 if unread else 1)
        if since:
            conditions.append("received_at >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM emails {where} ORDER BY received_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [_row_to_record(r) for r in rows]
    except Exception:
        return []


@app.get("/emails/summary", response_model=EmailSummary)
async def email_summary():
    """Today's email summary with counts by category and action items."""
    try:
        conn = _get_db()
    except Exception:
        return EmailSummary(total_today=0, unread=0, by_category={}, action_items=[])
    today = datetime.now(timezone.utc).date().isoformat()

    # Total today
    total = conn.execute(
        "SELECT COUNT(*) FROM emails WHERE received_at >= ?", (today,)
    ).fetchone()[0]

    # Unread
    unread = conn.execute("SELECT COUNT(*) FROM emails WHERE read = 0").fetchone()[0]

    # By category
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM emails WHERE received_at >= ? GROUP BY category",
        (today,),
    ).fetchall()
    by_category = {r["category"]: r["cnt"] for r in rows}

    # Action items: unread high-priority
    action_rows = conn.execute(
        """SELECT id, sender_name, subject, category, received_at
           FROM emails WHERE read = 0 AND priority IN ('high', 'medium')
           ORDER BY received_at DESC LIMIT 20""",
    ).fetchall()

    action_items = [
        {
            "id": r["id"],
            "sender": r["sender_name"],
            "subject": r["subject"],
            "category": r["category"],
            "received_at": r["received_at"],
        }
        for r in action_rows
    ]

    conn.close()

    return EmailSummary(
        total_today=total,
        unread=unread,
        by_category=by_category,
        action_items=action_items,
    )


@app.get("/emails/bids")
async def list_bids(limit: int = Query(50, ge=1, le=200)):
    """All BuildingConnected bid invites."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM emails WHERE category = 'BID_INVITE' ORDER BY received_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    return [_row_to_record(r) for r in rows]


@app.post("/emails/{email_id}/mark-read")
async def mark_read(email_id: int):
    """Mark an email as handled/read."""
    conn = _get_db()
    conn.execute("UPDATE emails SET read = 1 WHERE id = ?", (email_id,))
    conn.commit()
    changed = conn.total_changes
    conn.close()

    if changed == 0:
        return {"status": "not_found", "id": email_id}
    return {"status": "ok", "id": email_id}


@app.get("/emails/search", response_model=list[EmailRecord])
async def search_emails(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=200),
):
    """Search emails by sender, subject, snippet, or analysis content."""
    try:
        conn = _get_db()
        like = f"%{q}%"
        rows = conn.execute(
            """SELECT * FROM emails
               WHERE sender LIKE ? OR sender_name LIKE ? OR subject LIKE ?
                     OR snippet LIKE ? OR summary LIKE ? OR analysis LIKE ?
               ORDER BY received_at DESC LIMIT ?""",
            (like, like, like, like, like, like, limit),
        ).fetchall()
        conn.close()
        return [_row_to_record(r) for r in rows]
    except Exception:
        return []


@app.get("/emails/{email_id}/analysis")
async def get_analysis(email_id: int):
    """Get the LLM analysis for a single email."""
    import json as _json

    conn = _get_db()
    row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    conn.close()

    if not row:
        return {"error": "not_found"}

    analysis_raw = row["analysis"] if "analysis" in row.keys() else ""
    try:
        analysis = _json.loads(analysis_raw) if analysis_raw else {}
    except Exception:
        analysis = {}

    return {
        "id": row["id"],
        "sender": row["sender_name"] or row["sender"],
        "subject": row["subject"],
        "summary": row["summary"] if "summary" in row.keys() else "",
        "action_items": row["action_items"] if "action_items" in row.keys() else "",
        "urgency": row["urgency"] if "urgency" in row.keys() else "fyi",
        "suggested_reply": analysis.get("suggested_reply"),
    }
