"""
Inbound-reply listener — Phase 2.

Subscribes to events:imessage, parses digit-reply iMessages, resolves the
referenced ActionContext, and hands off to the dispatcher.  Mirrors the
reconnect pattern already in integrations/x_intake/main.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from .action_store import ActionStore, AlreadyUsed
from .parser import parse_reply

logger = logging.getLogger(__name__)

_RECONNECT_BACKOFF = 5  # seconds between reconnect attempts


async def process_message(
    raw: str,
    store: ActionStore,
    dispatcher: "Dispatcher",  # type: ignore[name-defined]
    send_ack: Callable[..., Awaitable[None]],
    *,
    dry_run: bool = True,
) -> None:
    """Process one raw JSON string from events:imessage.

    Extracted from the listener loop so tests can call it directly.
    """
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return
    if not isinstance(data, dict):
        return

    text = data.get("text") or data.get("body") or ""
    thread_guid = data.get("chat_guid") or data.get("thread_guid") or ""
    author_handle = data.get("from") or data.get("author_handle") or ""
    event_id = data.get("message_id") or data.get("event_id") or ""

    if not text or not thread_guid:
        return

    open_slots = store.list_open_slots(thread_guid)
    if not open_slots:
        return  # No pending actions for this thread — not a reply context

    parsed = parse_reply(text, open_slots)
    if not parsed.matched:
        return  # Noise — not a recognizable slot reply

    ctx = store.lookup_by_slot(thread_guid, parsed.slot)
    if ctx is None:
        logger.debug("reply_no_context", thread=thread_guid, slot=parsed.slot)
        return
    if ctx.expired:
        logger.debug("reply_expired", action_id=ctx.action_id, slot=parsed.slot)
        return

    try:
        await dispatcher.dispatch(
            slot=parsed.slot,
            ctx=ctx,
            send_ack=send_ack,
            author_handle=author_handle,
            dry_run=dry_run,
        )
    except AlreadyUsed:
        logger.info("reply_already_used", action_id=ctx.action_id, slot=parsed.slot)
    except Exception as exc:
        logger.warning("reply_dispatch_error", error=str(exc)[:200])


async def run_listener(
    redis_url: str,
    store: ActionStore,
    dispatcher: "Dispatcher",  # type: ignore[name-defined]
    send_ack: Callable[..., Awaitable[None]],
    *,
    dry_run: bool = True,
    channel: str = "events:imessage",
) -> None:
    """Subscribe to *channel* and process inbound replies indefinitely.

    Reconnects with _RECONNECT_BACKOFF on any error.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis not installed — reply listener disabled")
        return

    while True:
        try:
            client = aioredis.from_url(redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            logger.info("reply_listener_started", channel=channel, dry_run=dry_run)

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw = message.get("data", "")
                try:
                    await process_message(raw, store, dispatcher, send_ack, dry_run=dry_run)
                except Exception as exc:
                    logger.warning("reply_message_error", error=str(exc)[:200])
        except Exception as exc:
            logger.warning("reply_listener_reconnecting", error=str(exc)[:200])
            await asyncio.sleep(_RECONNECT_BACKOFF)
