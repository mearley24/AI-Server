"""Background task that checks upcoming events and publishes reminders to Redis."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

import redis.asyncio as aioredis

from calendar_client import ZohoCalendarClient
from scheduler import parse_event_times

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
REMINDER_CHANNEL = "notifications:calendar"
CHECK_INTERVAL = 300  # 5 minutes
REMINDER_WINDOW = 30  # minutes ahead


async def reminder_loop(cal_client: ZohoCalendarClient):
    """Run every 5 minutes: check for events in the next 30 minutes, publish reminders."""
    reminded: set[str] = set()
    redis_client = None

    while True:
        try:
            if not cal_client.configured:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            if redis_client is None:
                redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

            now = datetime.now()
            window_end = now + timedelta(minutes=REMINDER_WINDOW)

            events = await cal_client.list_events(
                now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                window_end.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            )

            for ev in events:
                uid = ev.get("uid", "")
                if uid in reminded:
                    continue

                start, _ = parse_event_times(ev)
                if start and now <= start <= window_end:
                    title = ev.get("title", "Untitled")
                    minutes_until = int((start - now).total_seconds() / 60)
                    payload = json.dumps({
                        "type": "calendar_reminder",
                        "title": title,
                        "starts_in_minutes": minutes_until,
                        "start_time": start.isoformat(),
                        "event_uid": uid,
                    })
                    await redis_client.publish(REMINDER_CHANNEL, payload)
                    reminded.add(uid)
                    logger.info("Reminder published: %s in %d min", title, minutes_until)

            # Prune old reminded entries daily
            if len(reminded) > 500:
                reminded.clear()

        except Exception as e:
            logger.warning("Reminder loop error: %s", e)
            redis_client = None

        await asyncio.sleep(CHECK_INTERVAL)
