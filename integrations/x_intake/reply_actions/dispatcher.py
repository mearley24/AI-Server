"""
Executor-router — Phase 4.

HANDLER_REGISTRY maps string names to async handler callables.  Handler names
are resolved from ctx.context["slot_handler_map"][str(slot)]; any name NOT in
the registry is rejected (fail-closed — no reflection, no getattr).

Rate limit: ≤ 10 executions per rolling 60 s per author_handle.
Idempotency: ActionStore.mark_used() is called before the handler; AlreadyUsed
is caught by the caller (listener.process_message).
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from .action_store import ActionContext, ActionStore, AlreadyUsed

logger = logging.getLogger(__name__)

_CORTEX_URL = os.environ.get("CORTEX_URL", "http://cortex:8102")
_HANDLER_TIMEOUT = 8.0          # seconds — hard cap on any outbound HTTP
_RATE_WINDOW = 60.0             # rolling window in seconds
_RATE_LIMIT = 10                # max executions per author per window


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _cortex_remember(ctx: ActionContext) -> Dict[str, Any]:
    payload = {
        "category": ctx.context.get("category", "x_intel"),
        "title": ctx.context.get("title", ctx.context.get("url", "saved")[:80]),
        "content": ctx.context.get("summary", ctx.context.get("url", "")),
        "source": ctx.context.get("url", ""),
        "importance": int(ctx.context.get("importance", 7)),
        "tags": ctx.context.get("tags", ["x_intake", "reply_saved"]),
        "dedupe_hint": ctx.action_id,
    }
    async with httpx.AsyncClient(timeout=_HANDLER_TIMEOUT) as client:
        resp = await client.post(f"{_CORTEX_URL}/remember", json=payload)
    resp.raise_for_status()
    return {"handler": "cortex_remember", "status": "ok", "mem_id": resp.json().get("id")}


async def _cortex_dismiss(ctx: ActionContext) -> Dict[str, Any]:
    mem_id = ctx.context.get("memory_id") or ctx.context.get("mem_id")
    if not mem_id:
        return {"handler": "cortex_dismiss", "status": "skip", "reason": "no_memory_id"}
    payload = {"importance": 0, "metadata": {"dismissed_at": _now_iso()}}
    async with httpx.AsyncClient(timeout=_HANDLER_TIMEOUT) as client:
        resp = await client.post(f"{_CORTEX_URL}/remember", json={
            "category": ctx.context.get("category", "x_intel"),
            "title": ctx.context.get("title", "dismissed"),
            "content": ctx.context.get("summary", ""),
            "source": ctx.context.get("url", ""),
            "importance": 0,
            "dedupe_hint": ctx.action_id,
            "metadata": {"dismissed_at": _now_iso(), "dismissed_action": ctx.action_id},
        })
    resp.raise_for_status()
    return {"handler": "cortex_dismiss", "status": "ok"}


async def _send_reply(ctx: ActionContext) -> Dict[str, Any]:
    """Send an explicit body string as the outbound ACK — no Cortex side-effect.

    Use this when the action should transmit a specific pre-composed message
    rather than a handler-generated confirmation string.  Set context["body"]
    to the exact text to send.
    """
    body = (ctx.context.get("body") or "").strip()
    if not body:
        return {"handler": "send_reply", "status": "skip", "reason": "no_body_in_context"}
    return {"handler": "send_reply", "status": "ok", "body": body}


async def _escalate_to_matt(ctx: ActionContext) -> Dict[str, Any]:
    # Write a Cortex note — no external message, no upload.
    payload = {
        "category": "business_operations",
        "title": f"Escalation requested: {ctx.context.get('title', ctx.context.get('url', 'unknown'))[:80]}",
        "content": f"Matt requested escalation via reply. URL: {ctx.context.get('url', '')}",
        "source": f"reply_action:{ctx.action_id}",
        "importance": 9,
        "tags": ["escalation", "reply_action"],
        "dedupe_hint": f"escalate:{ctx.action_id}",
    }
    async with httpx.AsyncClient(timeout=_HANDLER_TIMEOUT) as client:
        resp = await client.post(f"{_CORTEX_URL}/remember", json=payload)
    resp.raise_for_status()
    return {"handler": "escalate_to_matt", "status": "ok", "mem_id": resp.json().get("id")}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# Explicit registry — no reflection, no getattr.
HANDLER_REGISTRY: Dict[str, Callable[[ActionContext], Awaitable[Dict[str, Any]]]] = {
    "cortex_remember":  _cortex_remember,
    "cortex_dismiss":   _cortex_dismiss,
    "escalate_to_matt": _escalate_to_matt,
    "send_reply":       _send_reply,
}


# ── Rate limiter ──────────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, limit: int = _RATE_LIMIT, window: float = _RATE_WINDOW) -> None:
        self._limit = limit
        self._window = window
        self._buckets: Dict[str, deque] = {}

    def is_allowed(self, handle: str) -> bool:
        import time
        now = time.time()
        bucket = self._buckets.setdefault(handle, deque())
        # Evict timestamps outside the window
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True


# ── Dispatcher ────────────────────────────────────────────────────────────────

class Dispatcher:
    def __init__(self, store: ActionStore) -> None:
        self._store = store
        self._rate = _RateLimiter()

    async def dispatch(
        self,
        *,
        slot: int,
        ctx: ActionContext,
        send_ack: Callable[..., Awaitable[None]],
        author_handle: str = "",
        dry_run: bool = True,
    ) -> None:
        # Rate limit
        if author_handle and not self._rate.is_allowed(author_handle):
            logger.warning("reply_rate_limited handle=%s", author_handle[:40])
            await send_ack(ctx.context.get("thread_guid", ""), "Too many actions — slow down.", dry_run=dry_run)
            return

        # Idempotency — mark used before executing so double-taps are no-ops
        marked = self._store.mark_used(ctx.action_id, slot)
        if not marked:
            raise AlreadyUsed(f"{ctx.action_id}:{slot}")

        # Resolve handler
        slot_map: Dict[str, str] = ctx.context.get("slot_handler_map", {})
        handler_name = slot_map.get(str(slot)) or slot_map.get(slot)  # type: ignore[arg-type]
        if handler_name not in HANDLER_REGISTRY:
            logger.warning("reply_unknown_handler handler=%s action_id=%s",
                           str(handler_name)[:40], ctx.action_id)
            await send_ack(
                ctx.context.get("thread_guid", ""),
                "Action not recognized.",
                dry_run=dry_run,
            )
            return

        handler = HANDLER_REGISTRY[handler_name]
        try:
            result = await asyncio.wait_for(handler(ctx), timeout=_HANDLER_TIMEOUT)
            ack_text = _ack_text(handler_name, result)
        except asyncio.TimeoutError:
            logger.warning("reply_handler_timeout handler=%s", handler_name)
            ack_text = "Action timed out — Bob will retry."
        except Exception as exc:
            logger.warning("reply_handler_error handler=%s error=%s", handler_name, str(exc)[:100])
            ack_text = "Action failed — Bob logged it."

        thread_guid = ctx.context.get("thread_guid", "")
        await send_ack(thread_guid, ack_text, dry_run=dry_run)


def _ack_text(handler_name: str, result: Dict[str, Any]) -> str:
    if handler_name == "send_reply":
        # Body is passed through directly — no fixed confirmation string.
        body = result.get("body", "")
        return body if body else "Done ✓"
    if handler_name == "cortex_remember":
        return "Saved to Bob's memory ✓"
    if handler_name == "cortex_dismiss":
        return "Dismissed ✓"
    if handler_name == "escalate_to_matt":
        return "Escalated — Bob flagged it for you ✓"
    return "Done ✓"
