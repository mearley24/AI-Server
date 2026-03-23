"""Weather market strategy — NOAA forecasts vs Polymarket temperature bracket pricing.

Scans Polymarket for active weather/temperature bracket markets and compares
the bracket pricing against NOAA National Weather Service probability
distributions. Buys when Polymarket significantly underprices a bracket
relative to NOAA forecast confidence.

This is the beginner-friendly strategy — weather markets move slower and
are less volatile than crypto short-term markets.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY, SIDE_SELL
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy

logger = structlog.get_logger(__name__)

# NOAA NWS API base URL — free, no key needed
NOAA_API_BASE = "https://api.weather.gov"

# Mapping of station IDs to NOAA grid points (resolved at startup)
# NOAA requires a two-step lookup: station -> (office, gridX, gridY) -> forecast
NOAA_HEADERS = {"User-Agent": "(polymarket-weather-bot, contact@example.com)", "Accept": "application/geo+json"}

# Temperature bracket pattern: "Will it be 80-85°F in Denver on March 25?"
TEMP_BRACKET_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# City/location patterns for matching weather markets to stations
CITY_PATTERNS: dict[str, list[str]] = {
    "KDEN": ["denver", "den", "colorado"],
    "KJFK": ["new york", "nyc", "jfk", "manhattan"],
    "KLAX": ["los angeles", "la", "lax"],
    "KORD": ["chicago", "ord", "o'hare"],
    "KATL": ["atlanta", "atl"],
    "KMIA": ["miami", "mia"],
}


class WeatherTraderStrategy(BaseStrategy):
    """Trades weather temperature bracket markets using NOAA forecast edge.

    Logic:
    1. Fetch NOAA temperature forecasts for configured stations.
    2. Scan Polymarket for active weather/temperature bracket markets.
    3. Compare NOAA-implied probability for each bracket vs Polymarket price.
    4. Buy when Polymarket underprices a bracket by >= edge_threshold.
    5. Exit at expiry or when bracket reprices toward fair value.
    """

    name = "weather_trader"
    description = "Trades weather temperature brackets using NOAA forecast edge"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = settings.weather_check_interval_seconds

        self._params = {
            "stations": settings.weather_noaa_stations,
            "edge_threshold": settings.weather_edge_threshold,
            "max_position_size": settings.weather_max_position_size,
        }

        self._http = httpx.AsyncClient(timeout=30.0, headers=NOAA_HEADERS)
        self._station_grids: dict[str, dict[str, Any]] = {}  # station -> grid info
        self._positions: dict[str, dict[str, Any]] = {}  # token_id -> position
        self._forecasts: dict[str, list[dict[str, Any]]] = {}  # station -> forecast periods
        self._last_forecast_fetch: float = 0.0
        self._forecast_cache_ttl: float = 600.0  # Re-fetch forecasts every 10 minutes

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start strategy and resolve NOAA station grid points."""
        await super().start(params)
        await self._resolve_stations()

    async def stop(self) -> None:
        """Stop strategy and close HTTP client."""
        # Exit all positions
        for token_id in list(self._positions.keys()):
            await self._exit_position(token_id, "strategy_stop")
        await self._http.aclose()
        await super().stop()

    async def on_tick(self) -> None:
        """Fetch forecasts, scan markets, and look for edge."""
        now = time.time()

        # Refresh forecasts periodically
        if now - self._last_forecast_fetch > self._forecast_cache_ttl:
            await self._fetch_all_forecasts()
            self._last_forecast_fetch = now

        # Scan for weather markets and evaluate edge
        await self._scan_and_evaluate()

        # Manage existing positions
        await self._manage_positions()

    async def _resolve_stations(self) -> None:
        """Resolve NOAA station IDs to grid points for forecast lookup."""
        for station in self._params["stations"]:
            try:
                resp = await self._http.get(f"{NOAA_API_BASE}/stations/{station}")
                if resp.status_code != 200:
                    logger.warning("noaa_station_not_found", station=station, status=resp.status_code)
                    continue

                data = resp.json()
                coords = data.get("geometry", {}).get("coordinates", [])
                if len(coords) < 2:
                    continue

                lon, lat = coords[0], coords[1]

                # Get grid point from coordinates
                points_resp = await self._http.get(f"{NOAA_API_BASE}/points/{lat},{lon}")
                if points_resp.status_code != 200:
                    logger.warning("noaa_points_failed", station=station)
                    continue

                points_data = points_resp.json()
                props = points_data.get("properties", {})

                self._station_grids[station] = {
                    "office": props.get("gridId", ""),
                    "gridX": props.get("gridX", 0),
                    "gridY": props.get("gridY", 0),
                    "city": props.get("relativeLocation", {}).get("properties", {}).get("city", ""),
                    "state": props.get("relativeLocation", {}).get("properties", {}).get("state", ""),
                    "lat": lat,
                    "lon": lon,
                }
                logger.info(
                    "noaa_station_resolved",
                    station=station,
                    office=self._station_grids[station]["office"],
                    city=self._station_grids[station]["city"],
                )

            except Exception as exc:
                logger.error("noaa_station_resolve_error", station=station, error=str(exc))

    async def _fetch_all_forecasts(self) -> None:
        """Fetch temperature forecasts for all resolved stations."""
        for station, grid in self._station_grids.items():
            try:
                office = grid["office"]
                gx = grid["gridX"]
                gy = grid["gridY"]
                url = f"{NOAA_API_BASE}/gridpoints/{office}/{gx},{gy}/forecast"

                resp = await self._http.get(url)
                if resp.status_code != 200:
                    logger.warning("noaa_forecast_failed", station=station, status=resp.status_code)
                    continue

                data = resp.json()
                periods = data.get("properties", {}).get("periods", [])
                self._forecasts[station] = periods

                logger.debug(
                    "noaa_forecast_fetched",
                    station=station,
                    periods=len(periods),
                )

            except Exception as exc:
                logger.error("noaa_forecast_error", station=station, error=str(exc))

    async def _scan_and_evaluate(self) -> None:
        """Scan Polymarket for weather markets and evaluate edge."""
        edge_threshold = self._params["edge_threshold"]
        max_size = self._params["max_position_size"]

        try:
            raw_markets = await self._client.search_markets("temperature", limit=100)
        except Exception as exc:
            logger.error("weather_market_scan_error", error=str(exc))
            return

        # Also search for "weather" and "degrees"
        for query in ["weather forecast", "degrees fahrenheit", "high temperature"]:
            try:
                extra = await self._client.search_markets(query, limit=50)
                raw_markets.extend(extra)
            except Exception:
                continue

        # Deduplicate by condition_id
        seen: set[str] = set()
        unique_markets: list[dict[str, Any]] = []
        for mkt in raw_markets:
            cid = mkt.get("condition_id", mkt.get("id", ""))
            if cid and cid not in seen:
                seen.add(cid)
                unique_markets.append(mkt)

        for mkt in unique_markets:
            if not mkt.get("active", False):
                continue

            question = mkt.get("question", "")
            tokens = mkt.get("tokens", [])
            if len(tokens) < 2:
                continue

            # Try to parse a temperature bracket from the question
            bracket = self._parse_temperature_bracket(question)
            if bracket is None:
                continue

            low_f, high_f = bracket

            # Match market to a station
            station = self._match_station(question)
            if station is None or station not in self._forecasts:
                continue

            # Calculate NOAA-implied probability for this bracket
            noaa_prob = self._estimate_bracket_probability(station, low_f, high_f)
            if noaa_prob is None:
                continue

            # Get current Polymarket YES price
            token_id_yes = tokens[0].get("token_id", "")
            poly_price = float(tokens[0].get("price", 0))
            if poly_price <= 0:
                try:
                    poly_price = await self._client.get_midpoint(token_id_yes)
                except Exception:
                    continue

            if poly_price <= 0:
                continue

            # Calculate edge
            edge = noaa_prob - poly_price

            if edge >= edge_threshold:
                # Skip if we already have a position
                if token_id_yes in self._positions:
                    continue

                logger.info(
                    "weather_edge_found",
                    market=question,
                    bracket=f"{low_f}-{high_f}°F",
                    noaa_prob=round(noaa_prob, 3),
                    poly_price=round(poly_price, 3),
                    edge=round(edge, 3),
                    station=station,
                )

                # Size position based on edge (Kelly-lite: edge * bankroll fraction)
                size = min(max_size, round(edge * max_size * 2, 2))
                size = max(size, 5.0)  # Minimum $5

                order = await self._place_limit_order(
                    token_id=token_id_yes,
                    market=question,
                    price=round(poly_price + 0.01, 2),  # Slightly above market
                    size=size,
                    side=SIDE_BUY,
                )

                if order:
                    self._positions[token_id_yes] = {
                        "market": question,
                        "entry_price": poly_price,
                        "size": size,
                        "noaa_prob": noaa_prob,
                        "edge_at_entry": edge,
                        "station": station,
                        "bracket": (low_f, high_f),
                        "bought_at": time.time(),
                    }

    def _parse_temperature_bracket(self, question: str) -> tuple[int, int] | None:
        """Extract temperature bracket (low, high) from a market question."""
        match = TEMP_BRACKET_PATTERN.search(question)
        if not match:
            return None
        low = int(match.group(1))
        high = int(match.group(2))
        if low >= high or high - low > 30:  # Sanity check
            return None
        return (low, high)

    def _match_station(self, question: str) -> str | None:
        """Match a market question to a NOAA station based on city references."""
        question_lower = question.lower()
        for station, patterns in CITY_PATTERNS.items():
            if station in self._station_grids:
                for pattern in patterns:
                    if pattern in question_lower:
                        return station

        # Also try matching against resolved city names
        for station, grid in self._station_grids.items():
            city = grid.get("city", "").lower()
            if city and city in question_lower:
                return station

        return None

    def _estimate_bracket_probability(
        self, station: str, low_f: int, high_f: int
    ) -> float | None:
        """Estimate the probability that temperature falls within a bracket.

        Uses NOAA forecast high/low temperatures with a normal distribution
        assumption. NOAA forecasts are typically accurate to ±3-5°F, so we
        model uncertainty as a gaussian with σ=3°F around the point forecast.
        """
        periods = self._forecasts.get(station, [])
        if not periods:
            return None

        # Use the nearest daytime forecast period
        forecast_temp = None
        for period in periods:
            if period.get("isDaytime", False):
                forecast_temp = period.get("temperature")
                break

        if forecast_temp is None and periods:
            forecast_temp = periods[0].get("temperature")

        if forecast_temp is None:
            return None

        forecast_temp = float(forecast_temp)

        # Model: temperature ~ Normal(forecast_temp, sigma=3.5)
        # P(low <= T <= high) using the error function approximation
        sigma = 3.5
        z_low = (low_f - forecast_temp) / sigma
        z_high = (high_f - forecast_temp) / sigma

        prob = _normal_cdf(z_high) - _normal_cdf(z_low)
        return max(0.0, min(1.0, prob))

    async def _manage_positions(self) -> None:
        """Monitor positions and exit when bracket reprices toward fair value."""
        for token_id, pos in list(self._positions.items()):
            try:
                current_price = await self._client.get_midpoint(token_id)
            except Exception:
                continue

            entry_price = pos["entry_price"]
            noaa_prob = pos["noaa_prob"]

            # Exit if price has moved toward NOAA fair value (take profit)
            if current_price >= noaa_prob - 0.02:
                logger.info(
                    "weather_take_profit",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                    target=noaa_prob,
                )
                await self._exit_position(token_id, "take_profit")
                continue

            # Exit if we've been holding too long (6 hours max)
            if time.time() - pos["bought_at"] > 6 * 3600:
                logger.info(
                    "weather_time_exit",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                    hold_hours=round((time.time() - pos["bought_at"]) / 3600, 1),
                )
                await self._exit_position(token_id, "time_limit")
                continue

            # Stop loss: if edge has reversed (NOAA repriced against us)
            if current_price <= entry_price * 0.70:
                logger.info(
                    "weather_stop_loss",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                )
                await self._exit_position(token_id, "stop_loss")
                continue

    async def _exit_position(self, token_id: str, reason: str) -> None:
        """Exit a weather position."""
        pos = self._positions.get(token_id)
        if not pos:
            return

        try:
            current_price = await self._client.get_midpoint(token_id)
            await self._client.place_order(
                token_id=token_id,
                price=current_price,
                size=pos["size"],
                side=SIDE_SELL,
                order_type="FOK",
            )
            logger.info(
                "weather_position_exited",
                market=pos["market"],
                reason=reason,
                exit_price=current_price,
                entry_price=pos["entry_price"],
                pnl=round(current_price - pos["entry_price"], 4),
            )
        except Exception as exc:
            logger.error("weather_exit_error", token_id=token_id, error=str(exc))

        if token_id in self._positions:
            del self._positions[token_id]


def _normal_cdf(x: float) -> float:
    """Approximate the standard normal CDF using Abramowitz & Stegun formula."""
    import math

    if x < -6:
        return 0.0
    if x > 6:
        return 1.0

    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = 1
    if x < 0:
        sign = -1
    x = abs(x) / math.sqrt(2.0)

    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

    return 0.5 * (1.0 + sign * y)
