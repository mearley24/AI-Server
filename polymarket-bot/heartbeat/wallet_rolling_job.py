"""Daily recalculation of priority-wallet 30d rolling stats (Auto-8)."""

from __future__ import annotations

import logging

import httpx

from strategies.wallet_rolling_redis import PRIORITY_WALLET_ADDRESSES, apply_rolling_policy
from strategies.wallet_scoring import rolling_stats_from_positions

logger = logging.getLogger(__name__)

POSITIONS_URL = "https://data-api.polymarket.com/positions"


async def run_wallet_rolling_daily() -> None:
    """Fetch positions for each priority wallet and update Redis rolling policy."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        for addr in PRIORITY_WALLET_ADDRESSES:
            try:
                resp = await client.get(
                    POSITIONS_URL,
                    params={"user": addr.lower(), "sizeThreshold": "0"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "wallet_rolling_fetch_failed: %s status=%s",
                        addr[:12],
                        resp.status_code,
                    )
                    continue
                positions = resp.json()
                if not isinstance(positions, list):
                    continue
                stats = rolling_stats_from_positions(positions)
                apply_rolling_policy(addr, stats)
                logger.info(
                    "wallet_rolling_updated: addr=%s wr_30d=%.3f closed=%d pl=%.2f",
                    addr[:12],
                    stats.get("wr", 0.0),
                    stats.get("total_closed", 0),
                    stats.get("pl", 0.0),
                )
            except Exception as exc:
                logger.warning("wallet_rolling_job error %s: %s", addr[:12], exc)
