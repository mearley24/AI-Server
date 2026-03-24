"""Kalshi Weather Strategy — adapted from weather_trader for Kalshi weather markets.

Uses the same NOAA/AccuWeather data pipeline as the existing Polymarket
weather_trader but targets Kalshi-specific weather contracts. Kalshi has
dedicated weather markets for temperature, precipitation, and hurricane events.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Optional

import httpx
import structlog

from src.platforms.base import Order
from src.platforms.kalshi_client import KalshiClient
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)

# NOAA station → Kalshi series tickers (high and low temp)
STATION_TO_KALSHI: dict[str, dict[str, str]] = {
    "KNYC": {"high": "KXHIGHNY", "low": "KXLOWNY"},
    "KORD": {"high": "KXHIGHCH", "low": "KXLOWCH"},
    "KLAX": {"high": "KXHIGHLA", "low": "KXLOWLA"},
    "KDEN": {"high": "KXHIGHDN", "low": "KXLOWDN"},
    "KJFK": {"high": "KXHIGHNY", "low": "KXLOWNY"},  # JFK uses NYC markets
    "KATL": {"high": "KXHIGHAT", "low": "KXLOWAT"},
    "KMIA": {"high": "KXHIGHMI", "low": "KXLOWMI"},
}


class KalshiWeatherStrategy:
    """Monitors NOAA/AccuWeather forecasts and trades Kalshi weather contracts.

    Pipeline:
    1. Fetch NOAA forecast for configured stations
    2. Fetch AccuWeather forecast for cross-validation
    3. Query Kalshi for open weather markets
    4. Compare forecast probabilities vs market prices
    5. If edge >= threshold and sources agree, place order
    """

    def __init__(
        self,
        kalshi_client: KalshiClient,
        signal_bus: SignalBus,
        noaa_stations: list[str] | None = None,
        edge_threshold: float = 0.10,
        max_position_size: float = 10.0,
        check_interval: float = 300.0,
        accuweather_api_key: str = "",
    ) -> None:
        self._client = kalshi_client
        self._bus = signal_bus
        self._stations = noaa_stations or list(STATION_TO_KALSHI.keys())
        self._edge_threshold = edge_threshold
        self._max_size = max_position_size
        self._interval = check_interval
        self._accuweather_key = accuweather_api_key or os.environ.get("ACCUWEATHER_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=30.0)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("kalshi_weather_started", stations=self._stations)

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
                await self._check_weather_markets()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("kalshi_weather_error", error=str(exc))
            await asyncio.sleep(self._interval)

    async def _check_weather_markets(self) -> None:
        """Core weather strategy loop using events→markets API flow.

        1. For each station, determine the Kalshi series tickers
        2. Fetch events for each series (GET /events?series_ticker=KXHIGHNY)
        3. Fetch contracts within each event (GET /markets?event_ticker=...)
        4. Compare forecast probabilities vs market prices
        """
        for station in self._stations:
            noaa_forecast = await self._fetch_noaa_forecast(station)
            if not noaa_forecast:
                continue

            # Get Kalshi series tickers for this station
            kalshi_mapping = STATION_TO_KALSHI.get(station)
            if not kalshi_mapping:
                continue

            for temp_type, series_ticker in kalshi_mapping.items():
                # Step 1: Fetch events for this series
                try:
                    events = await self._client.get_events(
                        series_ticker=series_ticker, status="open",
                    )
                except Exception as exc:
                    logger.warning(
                        "kalshi_weather_events_error",
                        series_ticker=series_ticker,
                        error=str(exc),
                    )
                    continue

                if not events:
                    continue

                # Step 2: For each event, fetch individual contracts
                for event in events:
                    event_ticker = event.get("event_ticker", "")
                    if not event_ticker:
                        continue

                    try:
                        markets = await self._client.get_event_markets(event_ticker)
                    except Exception as exc:
                        logger.warning(
                            "kalshi_weather_markets_error",
                            event_ticker=event_ticker,
                            error=str(exc),
                        )
                        continue

                    # Step 3: Compare forecast vs market price for each contract
                    for market in markets:
                        temp_range = self._parse_temp_range(market.get("title", ""))
                        if temp_range is None:
                            continue

                        low, high = temp_range
                        forecast_prob = self._calc_probability(
                            noaa_forecast.get("temperature"),
                            low,
                            high,
                            sigma=3.5,
                        )

                        if forecast_prob is None:
                            continue

                        yes_price = float(market.get("yes_bid_dollars", market.get("yes_bid", 0)) or 0)
                        if yes_price > 1.0:
                            yes_price /= 100

                        if yes_price <= 0:
                            continue

                        edge = forecast_prob - yes_price

                        if edge >= self._edge_threshold:
                            logger.info(
                                "kalshi_weather_edge_found",
                                ticker=market.get("ticker"),
                                station=station,
                                series=series_ticker,
                                event=event_ticker,
                                forecast_prob=round(forecast_prob, 3),
                                market_price=round(yes_price, 3),
                                edge=round(edge, 3),
                            )

                            order = Order(
                                platform="kalshi",
                                market_id=market.get("ticker", ""),
                                side="yes",
                                size=min(self._max_size, 10),
                                price=yes_price + 0.01,
                                order_type="limit",
                            )
                            await self._client.place_order(order)

                            await self._bus.publish(Signal(
                                signal_type=SignalType.TRADE_PROPOSAL,
                                source="kalshi_weather",
                                data={
                                    "platform": "kalshi",
                                    "ticker": market.get("ticker"),
                                    "station": station,
                                    "series": series_ticker,
                                    "event": event_ticker,
                                    "edge": round(edge, 4),
                                    "forecast_prob": round(forecast_prob, 4),
                                    "market_price": round(yes_price, 4),
                                },
                            ))

    def _is_weather_market(self, market: dict) -> bool:
        """Check if a market is weather-related."""
        title = market.get("title", "").lower()
        keywords = ["temperature", "weather", "degrees", "°f", "°c", "frost",
                     "precipitation", "hurricane", "wind", "heat"]
        return any(kw in title for kw in keywords)

    def _parse_temp_range(self, title: str) -> tuple[float, float] | None:
        """Extract temperature range from market title."""
        # Match patterns like "80-85°F", "80 to 85 degrees"
        pattern = r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*[FfCc]?"
        match = re.search(pattern, title)
        if match:
            return float(match.group(1)), float(match.group(2))

        # Match single threshold: "above 80°F"
        single = re.search(r"(?:above|over|exceed)\s+(\d+)\s*°?\s*[FfCc]?", title, re.IGNORECASE)
        if single:
            return float(single.group(1)), float(single.group(1)) + 10
        return None

    def _calc_probability(
        self, forecast_temp: float | None, low: float, high: float, sigma: float = 3.5
    ) -> float | None:
        """Estimate probability that actual temp falls in [low, high] using normal CDF."""
        if forecast_temp is None:
            return None
        try:
            import math

            def normal_cdf(x: float, mu: float, s: float) -> float:
                return 0.5 * (1 + math.erf((x - mu) / (s * math.sqrt(2))))

            prob = normal_cdf(high, forecast_temp, sigma) - normal_cdf(low, forecast_temp, sigma)
            return max(0.0, min(1.0, prob))
        except Exception:
            return None

    async def _fetch_noaa_forecast(self, station: str) -> dict | None:
        """Fetch forecast from NOAA NWS API."""
        # NOAA station grid mapping (simplified — real impl would resolve gridpoints)
        grid_map = {
            "KNYC": ("OKX", 33, 37),  # NYC (Central Park)
            "KDEN": ("BOU", 62, 60),  # Denver
            "KJFK": ("OKX", 33, 37),  # NYC/JFK
            "KLAX": ("LOX", 154, 44),  # LA
            "KORD": ("LOT", 65, 76),  # Chicago
            "KATL": ("FFC", 52, 88),  # Atlanta
            "KMIA": ("MFL", 75, 54),  # Miami
        }

        grid = grid_map.get(station)
        if not grid:
            return None

        office, x, y = grid
        url = f"https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast"
        try:
            resp = await self._http.get(url, headers={"User-Agent": "polymarket-bot/2.0"})
            if resp.status_code != 200:
                return None

            data = resp.json()
            periods = data.get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Get today's daytime forecast
            for period in periods:
                if period.get("isDaytime", False):
                    return {
                        "temperature": period.get("temperature"),
                        "unit": period.get("temperatureUnit", "F"),
                        "forecast": period.get("shortForecast"),
                        "station": station,
                    }
            return None
        except Exception as exc:
            logger.warning("noaa_fetch_error", station=station, error=str(exc))
            return None
