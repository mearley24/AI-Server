#!/usr/bin/env python3
"""
notifier.py — Notification dispatcher for emails.

Subscribes to Redis `email:urgent` and `email:new` channels, formats
notifications, and publishes them to `notifications:email` for
notification-hub dispatch.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

CATEGORY_LABELS = {
    "BID_INVITE": "New bid invite",
    "CLIENT_INQUIRY": "Client inquiry",
    "FOLLOW_UP_NEEDED": "Follow-up needed",
    "SCHEDULING": "Scheduling",
    "INVOICE": "Invoice",
    "VENDOR": "Vendor update",
    "GENERAL": "Email",
}


def format_notification(data: dict, *, urgent: bool = False) -> str:
    """Format email notification message with analysis summary."""
    category = data.get("category", "UNKNOWN")
    sender = data.get("sender", "Unknown")
    subject = data.get("subject", "(no subject)")
    summary = data.get("summary", "")
    action_items = data.get("action_items", "")

    prefix = "[URGENT] " if urgent else ""
    header = f"{prefix}New email from {sender}: {subject}"

    # Build rich notification with analysis if available
    parts = [header]
    if summary and summary not in ("Analysis unavailable", "Analysis failed (parse error)"):
        parts.append(summary)
    if action_items:
        parts.append(f"\u2192 {action_items.replace(chr(10), ', ').strip('- ')}")

    return "\n".join(parts)


def _priority_for_channel(channel: str, data: dict) -> str:
    """Determine notification priority based on source channel."""
    if channel == "email:urgent":
        return "high"
    priority = data.get("priority", "low")
    if priority == "medium":
        return "normal"
    return "low"


async def dispatch(redis_client: aioredis.Redis, message: str, priority: str = "high") -> None:
    """Publish notification to notifications:email for notification-hub."""
    payload = json.dumps({"title": "Email Alert", "body": message, "priority": priority})
    await redis_client.publish("notifications:email", payload)
    logger.info("Published to notifications:email [%s]: %s", priority, message[:80])


async def run_subscriber() -> None:
    """Subscribe to Redis email:urgent and email:new channels and dispatch notifications."""
    logger.info("Notifier subscribing to email:urgent and email:new")

    while True:
        try:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("email:urgent", "email:new")

            # Track message IDs from urgent to avoid duplicate dispatch
            recent_urgent = set()

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    channel = message["channel"]
                    data = json.loads(message["data"])

                    # De-duplicate: if we already sent an urgent notification
                    # for this email, skip the email:new one
                    dedup_key = f"{data.get('sender', '')}:{data.get('subject', '')}"
                    if channel == "email:urgent":
                        recent_urgent.add(dedup_key)
                        # Cap the set to prevent unbounded growth
                        if len(recent_urgent) > 200:
                            recent_urgent.clear()
                    elif channel == "email:new" and dedup_key in recent_urgent:
                        continue

                    urgent = channel == "email:urgent"
                    priority = _priority_for_channel(channel, data)
                    notification = format_notification(data, urgent=urgent)
                    await dispatch(redis_client, notification, priority)
                except Exception as e:
                    logger.error("Notifier error: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber connection failed: %s — retrying in 10s", e)
            await asyncio.sleep(10)
