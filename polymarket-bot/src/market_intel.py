"""Market intelligence module — gathers live data for debate engine context.

Pulls real-time data from Perplexity (news research), CoinGecko (crypto prices),
and the existing Polymarket client before each bull/bear debate round.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

PERPLEXITY_API_URL = "https://api.openrouter.ai/api/v1/chat/completions"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# Rate limiting: max 10 Perplexity queries per hour
_MAX_PERPLEXITY_PER_HOUR = 10
# Cache TTL: 5 minutes
_CACHE_TTL_SECONDS = 300


@dataclass
class MarketContext:
    """Structured market context for debate injection."""

    market_question: str
    gathered_at: str
    polymarket_price: str | None = None
    crypto_prices: dict[str, Any] = field(default_factory=dict)
    perplexity_research: str | None = None
    order_book_summary: str | None = None

    def format(self) -> str:
        """Format as a [MARKET CONTEXT] block for prompt injection."""
        lines = [
            f"[MARKET CONTEXT — gathered at {self.gathered_at}]",
            f"Market: \"{self.market_question}\"",
        ]
        if self.polymarket_price:
            lines.append(f"Polymarket data: {self.polymarket_price}")
        if self.crypto_prices:
            for coin, data in self.crypto_prices.items():
                price = data.get("usd", "N/A")
                change = data.get("usd_24h_change")
                change_str = f" (24h: {change:+.1f}%)" if change is not None else ""
                lines.append(f"{coin.upper()} spot: ${price:,.2f}{change_str}" if isinstance(price, (int, float)) else f"{coin.upper()}: ${price}")
        if self.perplexity_research:
            lines.append(f"Research: {self.perplexity_research}")
        if self.order_book_summary:
            lines.append(f"Order book: {self.order_book_summary}")
        return "\n".join(lines)


class MarketIntel:
    """Gathers live market data for debate context injection."""

    def __init__(self) -> None:
        self._perplexity_key = os.environ.get("PERPLEXITY_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=15)
        # Rate limiting state
        self._perplexity_timestamps: list[float] = []
        # Cache: market_question -> (timestamp, MarketContext)
        self._cache: dict[str, tuple[float, MarketContext]] = {}

    @property
    def enabled(self) -> bool:
        return True  # Always enabled; degrades gracefully without API keys

    async def gather(
        self,
        market: str,
        context: dict[str, Any] | None = None,
    ) -> MarketContext:
        """Gather all available market intelligence for a given market.

        Returns a MarketContext even if some sources fail — never raises.
        """
        now = time.time()

        # Check cache
        cached = self._cache.get(market)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            logger.debug("market_intel_cache_hit", market=market)
            return cached[1]

        gathered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ctx = MarketContext(market_question=market, gathered_at=gathered_at)

        # Run all data fetches concurrently
        tasks = [
            self._fetch_crypto_prices(),
            self._fetch_perplexity_research(market),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        crypto_result, perplexity_result = results

        if isinstance(crypto_result, dict):
            ctx.crypto_prices = crypto_result
        elif isinstance(crypto_result, Exception):
            logger.debug("market_intel_crypto_error", error=str(crypto_result))

        if isinstance(perplexity_result, str) and perplexity_result:
            ctx.perplexity_research = perplexity_result
        elif isinstance(perplexity_result, Exception):
            logger.debug("market_intel_perplexity_error", error=str(perplexity_result))

        # Extract Polymarket-specific context from caller-provided dict
        if context:
            price_info = context.get("current_price") or context.get("price")
            if price_info is not None:
                ctx.polymarket_price = str(price_info)
            ob = context.get("order_book")
            if ob:
                ctx.order_book_summary = str(ob)

        # Cache result
        self._cache[market] = (now, ctx)

        logger.info(
            "market_intel_gathered",
            market=market,
            has_crypto=bool(ctx.crypto_prices),
            has_research=bool(ctx.perplexity_research),
        )
        return ctx

    async def _fetch_crypto_prices(self) -> dict[str, Any]:
        """Fetch crypto prices from CoinGecko free API."""
        try:
            resp = await self._http.get(
                COINGECKO_PRICE_URL,
                params={
                    "ids": "bitcoin,ripple,hedera",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("coingecko_fetch_error", error=str(exc))
            return {}

    async def _fetch_perplexity_research(self, market: str) -> str:
        """Query Perplexity API for real-time market research."""
        if not self._perplexity_key:
            return ""

        # Rate limiting: max 10 per hour
        now = time.time()
        cutoff = now - 3600
        self._perplexity_timestamps = [t for t in self._perplexity_timestamps if t > cutoff]
        if len(self._perplexity_timestamps) >= _MAX_PERPLEXITY_PER_HOUR:
            logger.warning("perplexity_rate_limited")
            return ""

        try:
            resp = await self._http.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._perplexity_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "perplexity/sonar",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a concise market research assistant. Provide a 2-3 sentence summary of the latest relevant news and data. Focus on facts, numbers, and recent developments.",
                        },
                        {
                            "role": "user",
                            "content": f"What is the latest news and current market sentiment for: {market}",
                        },
                    ],
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._perplexity_timestamps.append(now)

            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

        except Exception as exc:
            logger.debug("perplexity_fetch_error", error=str(exc))
            return ""

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
