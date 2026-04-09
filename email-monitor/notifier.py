#!/usr/bin/env python3
"""
notifier.py — Notification dispatcher for emails.

Subscribes to Redis `email:urgent` and `email:new` channels, formats
notifications, and publishes them to `notifications:email` for
notification-hub dispatch.

Dedup is persisted in SQLite so container restarts never re-fire
the same notification. Each message_id is suppressed for 24 hours.
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time

# Allow importing monitor helpers without circular import
sys.path.insert(0, os.path.dirname(__file__))

import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DB_PATH   = os.getenv("EMAIL_DB_PATH", "/data/emails.db")
DEDUP_TTL = int(os.getenv("NOTIFIER_DEDUP_TTL_HOURS", "24")) * 3600  # default 24h


CATEGORY_LABELS = {
    "BID_INVITE":       "New bid invite",
    "CLIENT_INQUIRY":   "Client inquiry",
    "FOLLOW_UP_NEEDED": "Follow-up needed",
    "SCHEDULING":       "Scheduling",
    "INVOICE":          "Invoice",
    "VENDOR":           "Vendor update",
    "GENERAL":          "Email",
}


# ── Persistent dedup ──────────────────────────────────────────────────────────

def _ensure_notified_table() -> None:
    """Create the notified_emails table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notified_emails (
                dedup_key  TEXT PRIMARY KEY,
                notified_at INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Could not init notified_emails table: %s", e)


def _already_notified(dedup_key: str) -> bool:
    """Return True if we sent a notification for this key within DEDUP_TTL."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT notified_at FROM notified_emails WHERE dedup_key = ?",
            (dedup_key,)
        ).fetchone()
        conn.close()
        if row is None:
            return False
        return (time.time() - row[0]) < DEDUP_TTL
    except Exception:
        return False  # on error, allow through rather than suppress


def _mark_notified(dedup_key: str) -> None:
    """Record that we sent a notification for this key."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO notified_emails (dedup_key, notified_at) VALUES (?, ?)",
            (dedup_key, int(time.time()))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Could not mark notified: %s", e)


def _prune_notified() -> None:
    """Delete stale dedup records older than DEDUP_TTL."""
    try:
        cutoff = int(time.time()) - DEDUP_TTL
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM notified_emails WHERE notified_at < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Formatting ────────────────────────────────────────────────────────────────

def format_notification(data: dict, *, urgent: bool = False) -> str:
    """Format email notification message with analysis summary."""
    category    = data.get("category", "UNKNOWN")
    sender      = data.get("sender", "Unknown")
    subject     = data.get("subject", "(no subject)")
    summary     = data.get("summary", "")
    action_items = data.get("action_items", "")

    prefix = "[URGENT] " if urgent else ""
    header = f"{prefix}New email from {sender}: {subject}"

    parts = [header]
    if summary and summary not in ("Analysis unavailable", "Analysis failed (parse error)"):
        parts.append(summary)
    if action_items:
        parts.append(f"\u2192 {action_items.replace(chr(10), ', ').strip('- ')}")

    return "\n".join(parts)


def _priority_for_channel(channel: str, data: dict) -> str:
    if channel == "email:urgent":
        return "high"
    priority = data.get("priority", "low")
    if priority == "medium":
        return "normal"
    return "low"


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def dispatch(redis_client: aioredis.Redis, message: str, priority: str = "high") -> None:
    """Publish notification to notifications:email for notification-hub."""
    payload = json.dumps({"title": "Email Alert", "body": message, "priority": priority})
    await redis_client.publish("notifications:email", payload)
    logger.info("Published to notifications:email [%s]: %s", priority, message[:80])


# ── Main subscriber ───────────────────────────────────────────────────────────

async def run_subscriber() -> None:
    """Subscribe to Redis email channels and dispatch notifications (dedup via SQLite)."""
    logger.info("Notifier subscribing to email:urgent and email:new")
    _ensure_notified_table()

    prune_counter = 0

    while True:
        try:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("email:urgent", "email:new")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    channel = message["channel"]
                    data    = json.loads(message["data"])

                    # Build a stable dedup key: sender + subject
                    # Use message_id if available (more precise)
                    msg_id    = data.get("message_id") or ""
                    sender    = data.get("sender", "")
                    subject   = data.get("subject", "")
                    dedup_key = msg_id if msg_id else f"{sender}:{subject}"

                    if _already_notified(dedup_key):
                        logger.debug("Suppressed duplicate notification: %s", dedup_key[:80])
                        continue

                    urgent       = (channel == "email:urgent")
                    priority     = _priority_for_channel(channel, data)
                    notification = format_notification(data, urgent=urgent)

                    await dispatch(redis_client, notification, priority)
                    _mark_notified(dedup_key)

                    # Mark email as read in the emails table
                    msg_id = data.get("message_id") or ""
                    if msg_id:
                        try:
                            from monitor import mark_email_read
                            mark_email_read(msg_id)
                        except Exception:
                            pass

                    # Prune old records every 50 dispatches
                    prune_counter += 1
                    if prune_counter >= 50:
                        _prune_notified()
                        prune_counter = 0

                except Exception as e:
                    logger.error("Notifier error: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber connection failed: %s — retrying in 10s", e)
            await asyncio.sleep(10)
