"""Notification Hub — Centralized notification dispatcher.

Subscribes to all notifications:* Redis channels and dispatches
via console or iMessage (host-side AppleScript bridge).
"""

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Config
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL", "console")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER", "")
DB_PATH = Path(os.getenv("DB_PATH", "/data/notifications.db"))


# ── Database ──────────────────────────────────────────────────

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            channel TEXT NOT NULL,
            title TEXT,
            body TEXT,
            priority TEXT DEFAULT 'normal',
            source TEXT,
            dispatched_via TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def store_notification(channel: str, title: str, body: str, priority: str, source: str, dispatched_via: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO notification_history (timestamp, channel, title, body, priority, source, dispatched_via) VALUES (?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), channel, title, body, priority, source, dispatched_via),
    )
    conn.commit()
    conn.close()


def get_history(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM notification_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Dispatch ──────────────────────────────────────────────────

async def send_console(title: str, body: str):
    logger.info("NOTIFICATION [%s]: %s", title, body)


BRIDGE_RETRY_COUNT = 3
BRIDGE_RETRY_BACKOFF = [2, 4, 8]


async def send_imessage(title: str, body: str):
    """Send iMessage via the host-side AppleScript bridge with retry + backoff."""
    message = f"{title}\n{body}" if title else body

    for attempt in range(BRIDGE_RETRY_COUNT):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    IMESSAGE_BRIDGE_URL,
                    json={"message": message},
                )
                if resp.status_code == 200:
                    logger.info("iMessage queued (attempt %d/%d): %s",
                                attempt + 1, BRIDGE_RETRY_COUNT, title or body[:60])
                    return "imessage"
                logger.warning("iMessage bridge returned %s (attempt %d/%d): %s",
                               resp.status_code, attempt + 1, BRIDGE_RETRY_COUNT, resp.text)
        except Exception as e:
            logger.warning("iMessage bridge error (attempt %d/%d): %s",
                           attempt + 1, BRIDGE_RETRY_COUNT, e)

        if attempt < BRIDGE_RETRY_COUNT - 1:
            backoff = BRIDGE_RETRY_BACKOFF[attempt]
            logger.info("Retrying iMessage bridge in %ds...", backoff)
            await asyncio.sleep(backoff)

    logger.error("All %d iMessage bridge attempts failed — falling back to console", BRIDGE_RETRY_COUNT)
    await send_console(title, body)
    return "console"


async def dispatch(title: str, body: str, priority: str = "normal", source: str = "direct") -> str:
    if NOTIFICATION_CHANNEL == "imessage":
        via = await send_imessage(title, body)
    else:
        await send_console(title, body)
        via = "console"
    store_notification(NOTIFICATION_CHANNEL, title, body, priority, source, via)
    return via


# ── Redis Subscriber ──────────────────────────────────────────

async def redis_subscriber():
    """Subscribe to all notifications:* channels and dispatch."""
    while True:
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.psubscribe("notifications:*")
            logger.info("Subscribed to notifications:* channels")

            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    channel = message.get("channel", "unknown")
                    data = json.loads(message["data"])
                    title = data.get("title", data.get("type", "Notification"))
                    body = data.get("body", data.get("message", json.dumps(data)))
                    priority = data.get("priority", "normal")
                    await dispatch(title, body, priority, source=channel)
                except Exception as e:
                    logger.error("Error processing notification: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber error: %s — retrying in 10s", e)
            await asyncio.sleep(10)


# ── FastAPI App ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(redis_subscriber())
    logger.info("Notification Hub started (channel=%s)", NOTIFICATION_CHANNEL)
    yield
    task.cancel()


app = FastAPI(title="Notification Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "notification-hub",
        "channel": NOTIFICATION_CHANNEL,
    }


@app.post("/notify")
async def notify(body: dict):
    title = body.get("title", "")
    message = body.get("body", "")
    priority = body.get("priority", "normal")
    if not message and not title:
        raise HTTPException(status_code=400, detail="title or body required")
    via = await dispatch(title, message, priority, source="api")
    return {"status": "sent", "via": via}


@app.get("/history")
async def history(limit: int = Query(50, ge=1, le=500)):
    return {"notifications": get_history(limit)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8095)
