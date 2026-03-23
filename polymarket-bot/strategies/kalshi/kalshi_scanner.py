"""Kalshi Market Scanner — discovers and scores trading opportunities.

Fetches open markets from Kalshi, filters by category/volume/liquidity,
and scores opportunities for downstream strategies.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.platforms.kalshi_client import KalshiClient
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)

# Market categories of interest
CATEGORY_KEYWORDS = {
    "weather": ["weather", "temperature", "hurricane", "precipitation", "frost", "wind"],
    "economics": ["fed", "cpi", "inflation", "gdp", "unemployment", "interest rate", "fomc", "jobs"],
    "politics": ["president", "election", "congress", "senate", "governor", "approval"],
    "sports": ["nfl", "nba", "mlb", "nhl", "super bowl", "march madness", "ufc"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto"],
}


@dataclass
class ScoredMarket:
    """A market scored for trading opportunity quality."""

    ticker: str
    title: str
    category: str
    yes_price: float  # dollars
    no_price: float  # dollars
    volume: float
    open_interest: float
    close_time: str
    score: float = 0.0  # 0-100 opportunity score
    edge_estimate: float = 0.0


class KalshiScanner:
    """Scans Kalshi markets and publishes discovery signals."""

    def __init__(
        self,
        kalshi_client: KalshiClient,
        signal_bus: SignalBus,
        scan_interval_seconds: float = 300.0,
        min_volume: float = 100.0,
        min_open_interest: float = 50.0,
        categories: list[str] | None = None,
    ) -> None:
        self._client = kalshi_client
        self._bus = signal_bus
        self._interval = scan_interval_seconds
        self._min_volume = min_volume
        self._min_oi = min_open_interest
        self._categories = categories or list(CATEGORY_KEYWORDS.keys())
        self._task: asyncio.Task | None = None
        self._last_scan: list[ScoredMarket] = []
        self._running = False

    @property
    def last_scan(self) -> list[ScoredMarket]:
        return list(self._last_scan)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("kalshi_scanner_started", interval=self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("kalshi_scanner_stopped")

    async def scan(self) -> list[ScoredMarket]:
        """Perform a single scan of Kalshi markets."""
        markets = await self._client.get_markets(status="open", limit=200)
        if not markets:
            return []

        scored: list[ScoredMarket] = []
        for m in markets:
            category = self._classify(m.get("title", ""))
            if category not in self._categories:
                continue

            volume = float(m.get("volume_fp", m.get("volume", 0)) or 0)
            oi = float(m.get("open_interest_fp", m.get("open_interest", 0)) or 0)

            if volume < self._min_volume or oi < self._min_oi:
                continue

            yes_price = float(m.get("yes_bid_dollars", m.get("yes_bid", 0)) or 0)
            if isinstance(yes_price, str):
                yes_price = float(yes_price)

            # If price is in cents, convert to dollars
            if yes_price > 1.0:
                yes_price = yes_price / 100

            no_price = 1.0 - yes_price if yes_price > 0 else 0.0

            score = self._score_market(yes_price, volume, oi, m)

            scored.append(ScoredMarket(
                ticker=m.get("ticker", ""),
                title=m.get("title", ""),
                category=category,
                yes_price=round(yes_price, 4),
                no_price=round(no_price, 4),
                volume=volume,
                open_interest=oi,
                close_time=m.get("close_time", ""),
                score=round(score, 2),
            ))

        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)
        self._last_scan = scored
        return scored

    def _classify(self, title: str) -> str:
        """Classify a market into a category based on title keywords."""
        title_lower = title.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in title_lower for kw in keywords):
                return category
        return "other"

    def _score_market(self, yes_price: float, volume: float, oi: float, raw: dict) -> float:
        """Score a market's trading opportunity quality (0-100).

        Higher scores indicate better opportunities:
        - Mid-range prices (30-70 cents) have more edge potential
        - Higher volume and OI indicate better liquidity
        - Markets closer to settlement with mispricing are higher value
        """
        score = 0.0

        # Price range scoring — mid-range has most edge + fee efficiency
        if 0.20 <= yes_price <= 0.80:
            # Peak score at 0.50, declining towards edges
            price_score = 30.0 * (1.0 - abs(yes_price - 0.50) / 0.30)
            score += max(0, price_score)
        elif 0.05 <= yes_price <= 0.15:
            # Rare event premium — asymmetric payoff
            score += 25.0

        # Volume scoring (log scale)
        import math
        if volume > 0:
            score += min(25.0, 5.0 * math.log10(volume))

        # Open interest scoring
        if oi > 0:
            score += min(20.0, 4.0 * math.log10(oi))

        # Liquidity depth bonus
        if volume > 1000 and oi > 500:
            score += 10.0

        return min(100.0, score)

    async def _scan_loop(self) -> None:
        """Periodic scan loop."""
        while self._running:
            try:
                results = await self.scan()
                if results:
                    # Publish top opportunities to signal bus
                    for market in results[:10]:
                        signal = Signal(
                            signal_type=SignalType.MARKET_DATA,
                            source="kalshi_scanner",
                            data={
                                "platform": "kalshi",
                                "ticker": market.ticker,
                                "title": market.title,
                                "category": market.category,
                                "yes_price": market.yes_price,
                                "score": market.score,
                                "volume": market.volume,
                            },
                        )
                        await self._bus.publish(signal)

                    logger.info(
                        "kalshi_scan_complete",
                        total=len(results),
                        top_score=results[0].score if results else 0,
                        top_market=results[0].ticker if results else "",
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("kalshi_scan_error", error=str(exc))

            await asyncio.sleep(self._interval)
