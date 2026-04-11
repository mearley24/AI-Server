"""OpportunityScanner — scans all intel sources for new edges and opportunities."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import structlog

from cortex.config import REDIS_URL
from cortex.memory import MemoryStore

logger = structlog.get_logger(__name__)


class OpportunityScanner:
    """Scans all intel sources for new edges and opportunities."""

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    async def scan(self) -> list[dict[str, Any]]:
        """Run all scanners. Returns list of opportunities."""
        opps: list[dict[str, Any]] = []
        opps.extend(await self._scan_x_intel())
        opps.extend(await self._scan_whale_moves())
        opps.extend(await self._scan_market_inefficiencies())
        opps.extend(await self._scan_strategy_gaps())
        logger.info("opportunity_scan_complete", total=len(opps))
        return opps

    async def _scan_x_intel(self) -> list[dict[str, Any]]:
        """Check Redis for recent X intel that hasn't been acted on."""
        opps: list[dict[str, Any]] = []
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(REDIS_URL)
            # Read last 20 signals from the stream / list
            raw_items = await r.lrange("polymarket:intel_signals:log", 0, 19)
            await r.aclose()

            for raw in raw_items:
                try:
                    signal = json.loads(raw)
                    relevance = signal.get("relevance", 0)
                    if relevance >= 70:
                        # Cross-reference with existing memories to avoid duplicates
                        existing = self.memory.recall(
                            signal.get("title", "")[:30],
                            category="x_intel",
                            limit=1,
                        )
                        if not existing:
                            opps.append({
                                "type": "x_intel",
                                "title": signal.get("title", "X Signal"),
                                "confidence": relevance / 100.0,
                                "importance": min(10, relevance // 10),
                                "data": signal,
                                "action": "Review X signal for trade entry",
                            })
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("x_intel_scan_error", error=str(exc))
        return opps

    async def _scan_whale_moves(self) -> list[dict[str, Any]]:
        """Check if tracked whales made unusual moves."""
        opps: list[dict[str, Any]] = []
        try:
            # Pull recent whale intel memories
            whale_mems = self.memory.get_by_category("whale_intel", limit=20)
            for mem in whale_mems:
                # Flag if high-importance whale intel hasn't been acted on recently
                if mem.get("importance", 0) >= 8 and mem.get("access_count", 0) == 0:
                    opps.append({
                        "type": "whale_move",
                        "title": mem.get("title", "Whale Move"),
                        "confidence": mem.get("confidence", 0.5),
                        "importance": mem.get("importance", 5),
                        "data": {"memory_id": mem["id"], "content": mem["content"][:200]},
                        "action": "Review whale pattern and consider copying position",
                    })
        except Exception as exc:
            logger.warning("whale_scan_error", error=str(exc))
        return opps

    async def _scan_market_inefficiencies(self) -> list[dict[str, Any]]:
        """Look for mispriced markets (complements don't sum to 1, stale prices)."""
        opps: list[dict[str, Any]] = []
        try:
            # Fetch active markets from Polymarket gamma API
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": 100,
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                if resp.status_code != 200:
                    return opps
                markets = resp.json()

            for market in markets:
                try:
                    tokens = market.get("tokens", [])
                    if len(tokens) == 2:
                        prices = [float(t.get("price", 0)) for t in tokens]
                        price_sum = sum(prices)
                        # Significant mispricing: doesn't sum close to 1.0
                        if abs(price_sum - 1.0) > 0.05:
                            opps.append({
                                "type": "market_inefficiency",
                                "title": f"Mispriced: {market.get('question', '')[:60]}",
                                "confidence": 0.7,
                                "importance": 7,
                                "data": {
                                    "market_id": market.get("id"),
                                    "question": market.get("question"),
                                    "price_sum": round(price_sum, 4),
                                    "prices": prices,
                                    "volume24h": market.get("volume24hr"),
                                },
                                "action": f"Prices sum to {price_sum:.3f} — arbitrage opportunity",
                            })
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("market_inefficiency_scan_error", error=str(exc))
        return opps[:5]  # Cap to avoid noise

    async def _scan_strategy_gaps(self) -> list[dict[str, Any]]:
        """Are there market categories we're not covering that we should be?"""
        opps: list[dict[str, Any]] = []
        try:
            # Profitable categories from memory
            profitable_rules = self.memory.recall(
                "crypto esports tennis weather",
                category="trading_rule",
                min_importance=7,
                limit=10,
            )
            # Check which categories have recent performance memories
            perf_mems = self.memory.get_by_category("strategy_performance", limit=20)
            covered = set()
            for m in perf_mems:
                for kw in ["crypto", "esports", "tennis", "weather", "politics", "sports"]:
                    if kw in m.get("content", "").lower() or kw in m.get("title", "").lower():
                        covered.add(kw)

            # Known profitable categories per AGENT_LEARNINGS
            known_profitable = {"crypto_updown", "esports", "tennis"}
            for cat in known_profitable:
                base = cat.split("_")[0]
                if base not in covered:
                    opps.append({
                        "type": "strategy_gap",
                        "title": f"Gap: {cat} not in recent performance data",
                        "confidence": 0.6,
                        "importance": 6,
                        "data": {"category": cat, "covered": list(covered)},
                        "action": f"Verify {cat} strategy is active and logging results",
                    })
        except Exception as exc:
            logger.warning("strategy_gap_scan_error", error=str(exc))
        return opps
