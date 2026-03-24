#!/usr/bin/env python3
"""
notifier.py — Notification dispatcher for urgent emails.

Subscribes to Redis `email:urgent` channel, formats notifications,
and publishes them to `notifications:email` for notification-hub dispatch.
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


async def dispatch(redis_client: aioredis.Redis, message: str) -> None:
    """Publish notification to notifications:email for notification-hub."""
    payload = json.dumps({"title": "Email Alert", "body": message, "priority": "high"})
    await redis_client.publish("notifications:email", payload)
    logger.info("Published to notifications:email: %s", message[:80])


async def run_subscriber() -> None:
    """Subscribe to Redis email:urgent channel and dispatch notifications."""
    logger.info("Notifier subscribing to email:urgent")

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
                    await dispatch(redis_client, notification)
                except Exception as e:
                    logger.error("Notifier error: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber connection failed: %s — retrying in 10s", e)
            await asyncio.sleep(10)
