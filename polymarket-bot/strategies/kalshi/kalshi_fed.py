"""Kalshi Fed/Economics Strategy — trades on FOMC, CPI, GDP, and jobs markets.

Monitors economic calendar data and positions on Kalshi's dedicated
economics markets (KXCPI, KXCPIYOY, Fed rate series, etc.) based on
consensus forecast divergence from market pricing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog

from src.platforms.base import Order
from src.platforms.kalshi_client import KalshiClient
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)

# Known Kalshi economics series tickers
ECONOMICS_SERIES = {
    "fed_rate": ["FED", "KXFED"],
    "cpi": ["KXCPI", "KXCPIMOM"],
    "inflation": ["KXCPIYOY"],
    "gdp": ["KXGDP"],
    "unemployment": ["KXUNRATE"],
    "jobs": ["KXNFP"],
}

# Economic calendar sources
ECON_CALENDAR_URL = "https://api.stlouisfed.org/fred/releases/dates"


class KalshiFedStrategy:
    """Trades Kalshi economics markets based on economic indicator forecasts.

    Strategy:
    1. Monitor upcoming economic releases (FOMC, CPI, GDP, NFP)
    2. Fetch consensus forecasts from financial data providers
    3. Compare consensus vs Kalshi market pricing
    4. Pre-position when consensus diverges from market
    5. Manage positions through release events
    """

    def __init__(
        self,
        kalshi_client: KalshiClient,
        signal_bus: SignalBus,
        check_interval: float = 600.0,
        edge_threshold: float = 0.08,
        max_position_size: float = 20.0,
        series_tickers: list[str] | None = None,
    ) -> None:
        self._client = kalshi_client
        self._bus = signal_bus
        self._interval = check_interval
        self._edge_threshold = edge_threshold
        self._max_size = max_position_size
        self._series = series_tickers or ["FED", "KXCPI", "KXCPIYOY", "KXGDP"]
        self._http = httpx.AsyncClient(timeout=30.0)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._active_positions: dict[str, dict] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("kalshi_fed_started", series=self._series)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if not self._http.is_closed:
            await self._http.aclose()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._check_economics_markets()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("kalshi_fed_error", error=str(exc))
            await asyncio.sleep(self._interval)

    async def _check_economics_markets(self) -> None:
        """Core economics strategy loop."""
        for series in self._series:
            # Fetch markets in this series
            markets = await self._client.get_markets(series_ticker=series, status="open", limit=50)
            if not markets:
                continue

            for market in markets:
                ticker = market.get("ticker", "")
                title = market.get("title", "")
                yes_price = float(market.get("yes_bid_dollars", 0) or 0)

                if yes_price > 1.0:
                    yes_price /= 100

                if yes_price <= 0 or yes_price >= 1.0:
                    continue

                # Analyze the market for mispricing
                analysis = self._analyze_economics_market(market)
                if analysis is None:
                    continue

                edge = analysis["estimated_prob"] - yes_price

                if abs(edge) >= self._edge_threshold:
                    side = "yes" if edge > 0 else "no"
                    order_price = yes_price + 0.01 if side == "yes" else (1.0 - yes_price) + 0.01

                    logger.info(
                        "kalshi_fed_edge",
                        ticker=ticker,
                        title=title[:60],
                        yes_price=round(yes_price, 3),
                        estimated_prob=round(analysis["estimated_prob"], 3),
                        edge=round(edge, 3),
                        side=side,
                        reasoning=analysis.get("reasoning", ""),
                    )

                    order = Order(
                        platform="kalshi",
                        market_id=ticker,
                        side=side,
                        size=min(self._max_size, 10),
                        price=min(0.99, max(0.01, order_price)),
                        order_type="limit",
                    )
                    await self._client.place_order(order)

                    await self._bus.publish(Signal(
                        signal_type=SignalType.TRADE_PROPOSAL,
                        source="kalshi_fed",
                        data={
                            "platform": "kalshi",
                            "ticker": ticker,
                            "series": series,
                            "edge": round(edge, 4),
                            "side": side,
                            "analysis": analysis,
                        },
                    ))

    def _analyze_economics_market(self, market: dict) -> dict | None:
        """Analyze an economics market for mispricing.

        Uses the market's title and historical patterns to estimate
        fair probability. In production, this would integrate with
        economic forecast APIs (Bloomberg consensus, FRED, etc.).
        """
        title = market.get("title", "").lower()
        yes_price = float(market.get("yes_bid_dollars", 0) or 0)
        if yes_price > 1.0:
            yes_price /= 100

        # Basic heuristic analysis — real implementation would use
        # consensus forecasts from economic data providers
        analysis: dict[str, Any] = {
            "ticker": market.get("ticker", ""),
            "estimated_prob": yes_price,  # default: agree with market
            "reasoning": "no edge detected",
        }

        # Fed rate markets — look for extreme pricing
        if "fed" in title or "rate" in title:
            # Markets priced very high (>0.90) or very low (<0.10) near expiry
            # tend to have compressed edge — skip
            if yes_price > 0.90 or yes_price < 0.10:
                return None

            # Mid-range fed markets may have edge from forward guidance analysis
            analysis["estimated_prob"] = yes_price  # neutral until we have forecast data
            analysis["reasoning"] = "fed_rate_market_monitored"

        # CPI markets
        elif "cpi" in title or "inflation" in title:
            analysis["reasoning"] = "cpi_market_monitored"

        return analysis

    async def get_upcoming_releases(self) -> list[dict]:
        """Fetch upcoming economic release dates."""
        # This would integrate with FRED API or economic calendar
        # For now, return known series with Kalshi markets
        releases = []
        for series in self._series:
            releases.append({
                "series": series,
                "type": "economic_indicator",
                "platform": "kalshi",
            })
        return releases
