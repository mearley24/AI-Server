"""Kalshi public markets client — Auto-1 cross-platform arb."""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

import httpx

logger = logging.getLogger(__name__)

KALSHI_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"


async def fetch_kalshi_markets(limit: int = 200) -> list[dict[str, Any]]:
    """Fetch open Kalshi markets (public trade API)."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(KALSHI_MARKETS_URL, params={"limit": limit})
            if r.status_code != 200:
                logger.warning("kalshi_fetch_status: %s", r.status_code)
                return []
            data = r.json()
            mkts = data.get("markets") if isinstance(data, dict) else data
            return mkts if isinstance(mkts, list) else []
    except Exception as exc:
        logger.warning("kalshi_fetch_error: %s", str(exc)[:120])
        return []


def title_similarity(a: str, b: str) -> float:
    """0–1 fuzzy match on normalized titles."""
    x = (a or "").lower().strip()
    y = (b or "").lower().strip()
    if not x or not y:
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def kalshi_mid_price(m: dict[str, Any]) -> float | None:
    """Best-effort mid from Kalshi market dict (API fields vary)."""
    try:
        yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
        yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
        if yes_bid > 0 and yes_ask > 0:
            return (yes_bid + yes_ask) / 2.0
        last = float(m.get("last_price_dollars") or m.get("last_price") or 0)
        if last > 0:
            return last
    except (TypeError, ValueError):
        return None
    return None
