#!/usr/bin/env python3
"""
notifier.py — Notification dispatcher for urgent emails.

Subscribes to Redis `email:urgent` channel and dispatches notifications
via console or iMessage (Linq) when configured.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL", "console")
LINQ_API_KEY = os.getenv("LINQ_API_KEY", "")
LINQ_PHONE_NUMBER = os.getenv("LINQ_PHONE_NUMBER", "")
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


def format_notification(data: dict) -> str:
    """Format email notification message."""
    category = data.get("category", "UNKNOWN")
    sender = data.get("sender", "Unknown")
    subject = data.get("subject", "(no subject)")

    labels = {
        "BID_INVITE": "New bid invite",
        "CLIENT_INQUIRY": "Client inquiry",
    }
    label = labels.get(category, f"Urgent email ({category})")

    return f"{label} from {sender}: {subject}"


async def send_console(message: str) -> None:
    """Log notification to console."""
    logger.info("NOTIFICATION: %s", message)


async def send_linq(message: str) -> None:
    """Send notification via Linq iMessage API."""
    if not all([LINQ_API_KEY, OWNER_PHONE_NUMBER]):
        logger.warning("Linq not configured — falling back to console")
        await send_console(message)
        return

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.linqapp.com/api/partner/v2/chats",
                headers={
                    "X-LINQ-INTEGRATION-TOKEN": LINQ_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "phone_number": OWNER_PHONE_NUMBER,
                    "text": message,
                },
            )
            resp.raise_for_status()
            logger.info("Linq notification sent: %s", message[:80])
    except Exception as e:
        logger.error("Linq send failed: %s — falling back to console", e)
        await send_console(message)


async def dispatch(message: str) -> None:
    """Dispatch notification via configured channel."""
    if NOTIFICATION_CHANNEL == "linq" and LINQ_API_KEY:
        await send_linq(message)
    else:
        await send_console(message)


async def run_subscriber() -> None:
    """Subscribe to Redis email:urgent channel and dispatch notifications."""
    logger.info("Notifier subscribing to email:urgent (channel=%s)", NOTIFICATION_CHANNEL)

    while True:
        try:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("email:urgent")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                    notification = format_notification(data)
                    await dispatch(notification)
                except Exception as e:
                    logger.error("Notifier error: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber connection failed: %s — retrying in 10s", e)
            await asyncio.sleep(10)
