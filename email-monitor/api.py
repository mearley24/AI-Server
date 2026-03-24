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


class EmailSummary(BaseModel):
    total_today: int
    unread: int
    by_category: dict[str, int]
    action_items: list[dict]


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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

    return [
        EmailRecord(
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
        )
        for r in rows
    ]


@app.get("/emails/summary", response_model=EmailSummary)
async def email_summary():
    """Today's email summary with counts by category and action items."""
    conn = _get_db()
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

    return [
        EmailRecord(
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
        )
        for r in rows
    ]


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
