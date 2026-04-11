"""Cortex client — fire-and-forget POSTs from the polymarket bot to
``http://cortex:8102/remember``. Cortex being down must never block a trade.

Usage::

    from src.cortex_client import post_trade_memory
    post_trade_memory(side="BUY", market="Trump wins", strategy="copytrade",
                      amount=3.0, price=0.61)
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CORTEX_URL = os.environ.get("CORTEX_URL", "http://cortex:8102")
_TIMEOUT = 3.0


def _fire_and_forget(payload: dict[str, Any]) -> None:
    """POST the payload to Cortex without blocking the caller.

    Works whether or not an asyncio loop is already running.
    """
    if not payload:
        return

    async def _send() -> None:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await client.post(f"{CORTEX_URL}/remember", json=payload)
        except Exception as exc:
            logger.debug("cortex_post_failed url=%s error=%s", CORTEX_URL, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(_send())
        return

    # No running loop — run in a background thread so we don't block.
    def _run() -> None:
        try:
            asyncio.run(_send())
        except Exception as exc:
            logger.debug("cortex_thread_fail error=%s", exc)

    threading.Thread(target=_run, daemon=True).start()


def post_trade_memory(
    *,
    side: str,
    market: str,
    strategy: str,
    amount: float,
    price: float,
    extra_tags: list[str] | None = None,
) -> None:
    """Record a trade in Cortex memory (fire-and-forget)."""
    title = f"{side} {market[:50]}"
    content = (
        f"Strategy: {strategy}, Amount: ${amount:.2f}, Price: {price:.3f}"
    )
    importance = 8 if amount > 10 else 5
    tags = ["trading", strategy or "unknown", side.lower()]
    if extra_tags:
        tags.extend(t for t in extra_tags if t)
    _fire_and_forget(
        {
            "category": "trading",
            "title": title,
            "content": content,
            "importance": importance,
            "tags": tags,
        }
    )


def post_memory(payload: dict[str, Any]) -> None:
    """Generic helper for non-trade memory posts."""
    _fire_and_forget(payload)
