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
from hermes import (
    NotificationRequest,
    normalize_email_recipient,
    resolve_channel,
    send_telegram_text,
    send_zoho_draft,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Config
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
NOTIFICATION_CHANNEL = os.getenv("NOTIFICATION_CHANNEL", "console")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER", "")
MATT_PHONE_NUMBER = os.getenv("MATT_PHONE_NUMBER", "") or OWNER_PHONE_NUMBER
REDIS_URL_SYNC = os.getenv("REDIS_URL", "redis://redis:6379")
DB_PATH = Path(os.getenv("DB_PATH", "/data/notifications.db"))
CORTEX_URL = os.getenv("CORTEX_URL", "http://cortex:8102")


async def _post_to_cortex(payload: dict) -> None:
    """Fire-and-forget POST to Cortex /remember. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{CORTEX_URL}/remember", json=payload)
    except Exception as exc:
        logger.debug("cortex_post_failed: %s", exc)


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


def _thread_key(thread_id: str) -> str:
    return f"hermes:thread:{thread_id}"


def append_thread_message(thread_id: str, channel: str, message: str, metadata: dict | None = None) -> None:
    """Redis list thread log with 30-day TTL."""
    try:
        import redis as redis_sync
        r = redis_sync.from_url(REDIS_URL_SYNC, decode_responses=True, socket_timeout=2)
        entry = {
            "message_id": datetime.now().isoformat(),
            "channel": channel,
            "message": message[:8000],
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        r.rpush(_thread_key(thread_id), json.dumps(entry))
        r.expire(_thread_key(thread_id), 30 * 24 * 3600)
    except Exception as exc:
        logger.warning("hermes thread append failed: %s", exc)


async def send_imessage_to_phone(phone: str, title: str, body: str) -> str:
    """Send iMessage via bridge — expects JSON {phone, body, title?} per imessage-server.py."""
    full_msg = f"{title}\n{body}" if title else body
    for attempt in range(BRIDGE_RETRY_COUNT):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    IMESSAGE_BRIDGE_URL,
                    json={"phone": phone or MATT_PHONE_NUMBER, "body": full_msg, "title": title},
                )
                if resp.status_code == 200:
                    logger.info(
                        "iMessage queued (attempt %d/%d): %s",
                        attempt + 1,
                        BRIDGE_RETRY_COUNT,
                        (title or body)[:60],
                    )
                    return "imessage"
                logger.warning(
                    "iMessage bridge returned %s (attempt %d/%d): %s",
                    resp.status_code,
                    attempt + 1,
                    BRIDGE_RETRY_COUNT,
                    resp.text,
                )
        except Exception as e:
            logger.warning(
                "iMessage bridge error (attempt %d/%d): %s",
                attempt + 1,
                BRIDGE_RETRY_COUNT,
                e,
            )
        if attempt < BRIDGE_RETRY_COUNT - 1:
            backoff = BRIDGE_RETRY_BACKOFF[attempt]
            await asyncio.sleep(backoff)
    logger.error("All iMessage bridge attempts failed — falling back to console")
    await send_console(title, body)
    return "console"


async def send_imessage(title: str, body: str):
    """Backward-compatible: send to Matt / owner."""
    phone = MATT_PHONE_NUMBER or OWNER_PHONE_NUMBER
    return await send_imessage_to_phone(phone, title, body)


async def execute_hermes(req: NotificationRequest) -> dict:
    """Resolve channels and send; imessage+email uses asyncio.gather when both selected."""
    channels = resolve_channel(req)
    title = req.subject or ""
    text = req.message
    results: list[str] = []
    phone = MATT_PHONE_NUMBER or OWNER_PHONE_NUMBER
    rc = (req.recipient or "").strip()
    if rc and "@" not in rc and (rc.startswith("+") or (rc[:1].isdigit())):
        phone = rc

    async def run_imessage() -> str:
        return await send_imessage_to_phone(phone, title, text)

    async def run_email() -> str:
        to_addr = normalize_email_recipient(req.recipient)
        if "@" not in to_addr:
            to_addr = os.environ.get("HERMES_DEFAULT_EMAIL_TO", "") or ""
        if not to_addr:
            logger.warning("hermes email skipped — no recipient address")
            return "email_skipped"
        subj = req.subject or "Symphony notification"
        return await send_zoho_draft(to_addr, subj, text)

    if "imessage" in channels and "email" in channels:
        im_task = asyncio.create_task(run_imessage())
        em_task = asyncio.create_task(run_email())
        im_r, em_r = await asyncio.gather(im_task, em_task, return_exceptions=True)
        results.append(str(im_r) if not isinstance(im_r, Exception) else f"imessage_err:{im_r}")
        results.append(str(em_r) if not isinstance(em_r, Exception) else f"email_err:{em_r}")
    else:
        for ch in channels:
            if ch == "imessage":
                results.append(await run_imessage())
            elif ch == "email":
                results.append(await run_email())
            elif ch == "telegram":
                results.append(await send_telegram_text(f"{title}\n{text}" if title else text))

    if req.thread_id:
        append_thread_message(req.thread_id, ",".join(channels), text, req.metadata)

    via = "+".join(results)
    store_notification("hermes", title, text, req.priority, "api_send", via)
    # Post every hermes dispatch to Cortex (fire-and-forget).
    await _post_to_cortex({
        "category": "notification",
        "title": f"Hermes dispatch [{','.join(channels)}]: {(title or text[:40])[:80]}",
        "content": text[:300],
        "source": "notification-hub",
        "importance": 6 if req.priority in ("high", "urgent") else 4,
        "tags": ["notification", "hermes"] + channels,
    })
    return {"channels": channels, "via": via}


async def dispatch(title: str, body: str, priority: str = "normal", source: str = "direct") -> str:
    if NOTIFICATION_CHANNEL == "imessage":
        via = await send_imessage(title, body)
    else:
        await send_console(title, body)
        via = "console"
    store_notification(NOTIFICATION_CHANNEL, title, body, priority, source, via)
    # Post to Cortex for every dispatched notification (not suppressed ones).
    await _post_to_cortex({
        "category": "notification",
        "title": f"Notification dispatched [{priority}]: {title[:80]}",
        "content": (body or "")[:300],
        "source": "notification-hub",
        "importance": 7 if priority in ("high", "urgent") else 4,
        "tags": ["notification", priority, source, via],
    })
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
                    ch_name = str(channel)
                    if ch_name.endswith(":send"):
                        req = NotificationRequest(**data)
                        await execute_hermes(req)
                        continue
                    # ── Channel allowlist ─────────────────────────────────────
                    # ONLY notifications:email (high priority) reaches iMessage.
                    # Everything else — trading, intel, arb, whale scanner — is
                    # logged to the DB but never sent as a notification.
                    ALLOWED_CHANNELS = {"notifications:email"}
                    if ch_name not in ALLOWED_CHANNELS:
                        logger.debug("notification_suppressed channel=%s", ch_name)
                        store_notification(ch_name,
                            data.get("title", ch_name),
                            data.get("body", data.get("message", ""))[:200],
                            data.get("priority", "low"), ch_name, "suppressed")
                        continue

                    title = data.get("title", data.get("type", "Notification"))
                    body = data.get("body", data.get("message", json.dumps(data)))
                    priority = data.get("priority", "normal")

                    # ── Email: only iMessage on high priority (active clients) ──
                    if priority != "high":
                        logger.debug("email_notification_suppressed priority=%s subject=%s", priority, title)
                        store_notification(ch_name, title, body, priority, ch_name, "suppressed")
                        continue

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
    title    = body.get("title", "")
    message  = body.get("body", "")
    priority = body.get("priority", "normal")
    if not message and not title:
        raise HTTPException(status_code=400, detail="title or body required")
    # Only iMessage on high priority — everything else logged only
    if priority != "high":
        store_notification("api", title, message[:200], priority, "api", "suppressed")
        return {"status": "suppressed", "reason": "priority not high"}
    via = await dispatch(title, message, priority, source="api")
    return {"status": "sent", "via": via}




@app.post("/api/send")
async def api_send(req: NotificationRequest):
    """Hermes unified send — resolves channel unless explicit."""
    if not req.message:
        raise HTTPException(status_code=400, detail="message required")
    return await execute_hermes(req)

@app.get("/history")
async def history(limit: int = Query(50, ge=1, le=500)):
    return {"notifications": get_history(limit)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8095)
