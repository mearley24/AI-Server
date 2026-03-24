"""Notification Hub — Centralized notification dispatcher.

Subscribes to all notifications:* Redis channels and dispatches
via console or iMessage (Linq API).
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
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
LINQ_API_KEY = os.getenv("LINQ_API_KEY", "")
LINQ_PHONE_NUMBER = os.getenv("LINQ_PHONE_NUMBER", "")
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


async def send_imessage(title: str, body: str):
    if not all([LINQ_API_KEY, OWNER_PHONE_NUMBER]):
        logger.warning("Linq not configured — falling back to console")
        await send_console(title, body)
        return "console"
    try:
        message = f"{title}\n{body}" if title else body
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.linqapp.com/api/partner/v2/chats",
                headers={"X-LINQ-INTEGRATION-TOKEN": LINQ_API_KEY, "Content-Type": "application/json"},
                json={"phone_number": OWNER_PHONE_NUMBER, "text": message},
            )
            resp.raise_for_status()
            logger.info("iMessage sent: %s", title or body[:60])
            return "imessage"
    except Exception as e:
        logger.error("Linq send failed: %s — falling back to console", e)
        await send_console(title, body)
        return "console"


async def dispatch(title: str, body: str, priority: str = "normal", source: str = "direct") -> str:
    if NOTIFICATION_CHANNEL == "imessage" and LINQ_API_KEY:
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
