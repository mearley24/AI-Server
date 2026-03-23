"""Weather market strategy — NOAA + AccuWeather forecasts vs Polymarket pricing.

Enhanced 4-stage pipeline (from hanakoxbt's Weather Arb Terminal):
    1. SCAN  — Monitor 247+ active weather contracts (temperature, frost, precip, wind)
    2. DISCREPANCY — Cross-reference NOAA + AccuWeather against Polymarket pricing
    3. FILTER — Only trade when edge >= threshold, sources agree, sufficient liquidity,
                and contract not expiring within 30 minutes
    4. EXECUTE — Place order with take-profit at fair value and stop-loss at entry - 5%

Also includes a rare event scanner targeting ultra-low-probability contracts
(< 10%) where forecast data suggests higher probability — asymmetric 20x payoffs.
"""

from __future__ import annotations

import asyncio
import os
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

# AccuWeather API base URL — free tier: 50 calls/day
ACCUWEATHER_API_BASE = "http://dataservice.accuweather.com"

NOAA_HEADERS = {"User-Agent": "(polymarket-weather-bot, contact@example.com)", "Accept": "application/geo+json"}

# Temperature bracket pattern: "Will it be 80-85°F in Denver on March 25?"
TEMP_BRACKET_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# Broader weather patterns for non-temperature markets
WEATHER_PATTERNS = {
    "frost": re.compile(r"frost|freeze|below\s+32", re.IGNORECASE),
    "precipitation": re.compile(r"rain|snow|precip|inches?\s+of", re.IGNORECASE),
    "wind": re.compile(r"wind|mph\s+gust|sustained\s+wind", re.IGNORECASE),
}

# City/location patterns for matching weather markets to stations
CITY_PATTERNS: dict[str, list[str]] = {
    "KDEN": ["denver", "den", "colorado"],
    "KJFK": ["new york", "nyc", "jfk", "manhattan"],
    "KLAX": ["los angeles", "la", "lax"],
    "KORD": ["chicago", "ord", "o'hare"],
    "KATL": ["atlanta", "atl"],
    "KMIA": ["miami", "mia"],
}

# AccuWeather location keys for common cities (resolved at startup)
ACCUWEATHER_CITY_KEYS: dict[str, str] = {
    "denver": "347810",
    "new york": "349727",
    "los angeles": "347625",
    "chicago": "348308",
    "atlanta": "348181",
    "miami": "347936",
    "tokyo": "226396",
    "wellington": "250938",
    "ankara": "316938",
}

# Rare event target cities (ColdMath wallet strategy)
RARE_EVENT_CITIES = ["tokyo", "wellington", "ankara", "denver", "chicago", "miami"]


class WeatherTraderStrategy(BaseStrategy):
    """Trades weather markets using multi-source forecast edge.

    4-stage pipeline:
        SCAN → DISCREPANCY → FILTER → EXECUTE

    Sources: NOAA National Weather Service + AccuWeather (confirmation)
    """

    name = "weather_trader"
    description = "Weather market arbitrage with NOAA + AccuWeather multi-source confirmation"

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
            "use_multi_source_confirmation": getattr(settings, "weather_trader_use_multi_source_confirmation", True),
            "min_sources_agree": getattr(settings, "weather_trader_min_sources_agree", 2),
            "scan_all_weather_types": getattr(settings, "weather_trader_scan_all_weather_types", True),
            "min_time_to_expiry_minutes": getattr(settings, "weather_trader_min_time_to_expiry_minutes", 30),
            "take_profit_at_fair_value": getattr(settings, "weather_trader_take_profit_at_fair_value", True),
            "stop_loss_pct": getattr(settings, "weather_trader_stop_loss_pct", 0.05),
            # Rare event scanner
            "rare_event_enabled": getattr(settings, "weather_trader_rare_event_scanner_enabled", True),
            "rare_event_max_probability": getattr(settings, "weather_trader_rare_event_scanner_max_probability", 0.10),
            "rare_event_min_forecast_edge": getattr(settings, "weather_trader_rare_event_scanner_min_forecast_edge", 0.15),
            "rare_event_max_position_size": getattr(settings, "weather_trader_rare_event_scanner_max_position_size", 25.0),
        }

        self._http = httpx.AsyncClient(timeout=30.0, headers=NOAA_HEADERS)
        self._accuweather_key = os.environ.get("ACCUWEATHER_API_KEY", "")
        self._station_grids: dict[str, dict[str, Any]] = {}  # station -> grid info
        self._positions: dict[str, dict[str, Any]] = {}  # token_id -> position
        self._forecasts: dict[str, list[dict[str, Any]]] = {}  # station -> forecast periods
        self._accuweather_forecasts: dict[str, dict[str, Any]] = {}  # city -> forecast
        self._last_forecast_fetch: float = 0.0
        self._forecast_cache_ttl: float = 600.0  # Re-fetch forecasts every 10 minutes
        self._accuweather_calls_today: int = 0
        self._accuweather_day: str = ""

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start strategy and resolve NOAA station grid points."""
        await super().start(params)
        await self._resolve_stations()

    async def stop(self) -> None:
        """Stop strategy and close HTTP client."""
        for token_id in list(self._positions.keys()):
            await self._exit_position(token_id, "strategy_stop")
        await self._http.aclose()
        await super().stop()

    async def on_tick(self) -> None:
        """Execute the 4-stage pipeline: SCAN → DISCREPANCY → FILTER → EXECUTE."""
        now = time.time()

        # Refresh forecasts periodically
        if now - self._last_forecast_fetch > self._forecast_cache_ttl:
            await self._fetch_all_forecasts()
            await self._fetch_accuweather_forecasts()
            self._last_forecast_fetch = now

        # Stage 1: SCAN for weather markets
        markets = await self._scan_weather_markets()

        # Stage 2 & 3: DISCREPANCY + FILTER → EXECUTE
        for mkt in markets:
            await self._evaluate_and_trade(mkt)

        # Rare event scanner
        if self._params["rare_event_enabled"]:
            await self._scan_rare_events(markets)

        # Manage existing positions
        await self._manage_positions()

    # ── Stage 1: SCAN ──────────────────────────────────────────────────────

    async def _scan_weather_markets(self) -> list[dict[str, Any]]:
        """Scan Polymarket for all active weather contracts."""
        search_terms = ["temperature", "weather forecast", "degrees fahrenheit", "high temperature"]

        if self._params["scan_all_weather_types"]:
            search_terms.extend(["frost", "freeze", "precipitation", "rain", "snow", "wind", "inches"])

        all_markets: list[dict[str, Any]] = []
        for query in search_terms:
            try:
                results = await self._client.search_markets(query, limit=100)
                all_markets.extend(results)
            except Exception:
                continue

        # Deduplicate by condition_id
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for mkt in all_markets:
            cid = mkt.get("condition_id", mkt.get("id", ""))
            if cid and cid not in seen and mkt.get("active", False):
                seen.add(cid)
                unique.append(mkt)

        logger.debug("weather_scan_complete", total=len(unique))
        return unique

    # ── Stage 2 & 3: DISCREPANCY + FILTER ──────────────────────────────────

    async def _evaluate_and_trade(self, mkt: dict[str, Any]) -> None:
        """Evaluate a weather market for edge and place trades if criteria met."""
        question = mkt.get("question", "")
        tokens = mkt.get("tokens", [])
        if len(tokens) < 2:
            return

        # Parse temperature bracket
        bracket = self._parse_temperature_bracket(question)
        if bracket is None:
            return

        low_f, high_f = bracket

        # Match to a station
        station = self._match_station(question)
        if station is None or station not in self._forecasts:
            return

        # NOAA probability
        noaa_prob = self._estimate_bracket_probability(station, low_f, high_f)
        if noaa_prob is None:
            return

        # AccuWeather probability (if available)
        accuweather_prob = self._get_accuweather_probability(question, low_f, high_f)

        # Multi-source confirmation filter
        if self._params["use_multi_source_confirmation"] and accuweather_prob is not None:
            min_sources = self._params["min_sources_agree"]
            sources_agree = 0
            if noaa_prob > 0:
                sources_agree += 1
            if accuweather_prob > 0:
                sources_agree += 1
            if sources_agree < min_sources:
                return

            # Use average of both sources
            fair_value = (noaa_prob + accuweather_prob) / 2
        else:
            fair_value = noaa_prob

        # Get Polymarket YES price
        token_id_yes = tokens[0].get("token_id", "")
        poly_price = float(tokens[0].get("price", 0))
        if poly_price <= 0:
            try:
                poly_price = await self._client.get_midpoint(token_id_yes)
            except Exception:
                return

        if poly_price <= 0:
            return

        # Stage 2: Calculate discrepancy
        edge = fair_value - poly_price

        # Stage 3: Apply filters
        edge_threshold = self._params["edge_threshold"]
        if edge < edge_threshold:
            return

        # Filter: already holding this position
        if token_id_yes in self._positions:
            return

        # Filter: check time to expiry (skip contracts expiring within 30 min)
        end_date = mkt.get("end_date_iso", "")
        if end_date:
            try:
                from datetime import datetime, timezone
                expiry = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                minutes_to_expiry = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
                if minutes_to_expiry < self._params["min_time_to_expiry_minutes"]:
                    logger.debug("weather_skip_expiring", market=question, minutes=round(minutes_to_expiry))
                    return
            except (ValueError, TypeError):
                pass

        # Filter: check liquidity
        try:
            book = await self._client.get_orderbook(token_id_yes)
            asks = book.get("asks", [])
            total_ask_depth = sum(float(a.get("size", 0)) for a in asks)
            if total_ask_depth < 10:  # minimal liquidity check
                return
        except Exception:
            pass

        logger.info(
            "weather_edge_found",
            market=question,
            bracket=f"{low_f}-{high_f}°F",
            noaa_prob=round(noaa_prob, 3),
            accuweather_prob=round(accuweather_prob, 3) if accuweather_prob is not None else None,
            fair_value=round(fair_value, 3),
            poly_price=round(poly_price, 3),
            edge=round(edge, 3),
            station=station,
        )

        # Stage 4: EXECUTE
        max_size = self._params["max_position_size"]
        size = min(max_size, round(edge * max_size * 2, 2))
        size = max(size, 5.0)

        order = await self._place_limit_order(
            token_id=token_id_yes,
            market=question,
            price=round(poly_price + 0.01, 2),
            size=size,
            side=SIDE_BUY,
        )

        if order:
            self._positions[token_id_yes] = {
                "market": question,
                "entry_price": poly_price,
                "size": size,
                "noaa_prob": noaa_prob,
                "accuweather_prob": accuweather_prob,
                "fair_value": fair_value,
                "edge_at_entry": edge,
                "station": station,
                "bracket": (low_f, high_f),
                "bought_at": time.time(),
            }

    # ── Rare Event Scanner ──────────────────────────────────────────────────

    async def _scan_rare_events(self, markets: list[dict[str, Any]]) -> None:
        """Scan for ultra-low-probability contracts where forecast suggests higher odds.

        Targets the ColdMath strategy: buy contracts priced at $0.01-$0.10 where
        forecasts indicate probability should be higher. Asymmetric payoff: $0.05 → $1.00 = 20x.
        """
        max_prob = self._params["rare_event_max_probability"]
        min_edge = self._params["rare_event_min_forecast_edge"]
        max_size = self._params["rare_event_max_position_size"]

        for mkt in markets:
            tokens = mkt.get("tokens", [])
            if len(tokens) < 2:
                continue

            question = mkt.get("question", "")
            token_id_yes = tokens[0].get("token_id", "")
            poly_price = float(tokens[0].get("price", 0))

            # Only look at very low probability contracts
            if poly_price <= 0 or poly_price > max_prob:
                continue

            if token_id_yes in self._positions:
                continue

            # Check if any forecast suggests higher probability
            bracket = self._parse_temperature_bracket(question)
            if bracket is None:
                continue

            low_f, high_f = bracket
            station = self._match_station(question)
            if station is None or station not in self._forecasts:
                continue

            noaa_prob = self._estimate_bracket_probability(station, low_f, high_f)
            if noaa_prob is None:
                continue

            forecast_edge = noaa_prob - poly_price
            if forecast_edge < min_edge:
                continue

            logger.info(
                "rare_event_found",
                market=question,
                poly_price=round(poly_price, 4),
                noaa_prob=round(noaa_prob, 4),
                edge=round(forecast_edge, 4),
                potential_return=f"{1.0 / poly_price:.0f}x",
            )

            # Small position for rare events
            size = min(max_size, 25.0)

            order = await self._place_limit_order(
                token_id=token_id_yes,
                market=question,
                price=round(poly_price + 0.005, 4),
                size=size,
                side=SIDE_BUY,
            )

            if order:
                self._positions[token_id_yes] = {
                    "market": question,
                    "entry_price": poly_price,
                    "size": size,
                    "noaa_prob": noaa_prob,
                    "accuweather_prob": None,
                    "fair_value": noaa_prob,
                    "edge_at_entry": forecast_edge,
                    "station": station,
                    "bracket": (low_f, high_f),
                    "bought_at": time.time(),
                    "is_rare_event": True,
                }

    # ── NOAA Forecast Methods ──────────────────────────────────────────────

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

                logger.debug("noaa_forecast_fetched", station=station, periods=len(periods))

            except Exception as exc:
                logger.error("noaa_forecast_error", station=station, error=str(exc))

    # ── AccuWeather Methods ────────────────────────────────────────────────

    async def _fetch_accuweather_forecasts(self) -> None:
        """Fetch forecasts from AccuWeather as secondary confirmation source."""
        if not self._accuweather_key:
            return

        # Track daily API calls (free tier: 50/day)
        today = time.strftime("%Y-%m-%d")
        if today != self._accuweather_day:
            self._accuweather_calls_today = 0
            self._accuweather_day = today

        for city, location_key in ACCUWEATHER_CITY_KEYS.items():
            if self._accuweather_calls_today >= 45:  # Leave buffer
                logger.warning("accuweather_daily_limit_approaching")
                break

            try:
                url = (
                    f"{ACCUWEATHER_API_BASE}/forecasts/v1/daily/5day/{location_key}"
                    f"?apikey={self._accuweather_key}&details=true"
                )
                resp = await self._http.get(url)
                self._accuweather_calls_today += 1

                if resp.status_code != 200:
                    logger.warning("accuweather_fetch_failed", city=city, status=resp.status_code)
                    continue

                data = resp.json()
                forecasts = data.get("DailyForecasts", [])
                if forecasts:
                    self._accuweather_forecasts[city] = {
                        "forecasts": forecasts,
                        "fetched_at": time.time(),
                    }
                    logger.debug("accuweather_fetched", city=city, days=len(forecasts))

            except Exception as exc:
                logger.error("accuweather_error", city=city, error=str(exc))

    def _get_accuweather_probability(
        self, question: str, low_f: int, high_f: int
    ) -> float | None:
        """Estimate bracket probability from AccuWeather forecast data."""
        if not self._accuweather_forecasts:
            return None

        # Find the matching city
        question_lower = question.lower()
        matched_city = None
        for city in self._accuweather_forecasts:
            if city in question_lower:
                matched_city = city
                break

        if matched_city is None:
            return None

        data = self._accuweather_forecasts[matched_city]
        forecasts = data.get("forecasts", [])
        if not forecasts:
            return None

        # Use the nearest forecast day's high temperature
        forecast = forecasts[0]
        temp_data = forecast.get("Temperature", {})
        high_temp = temp_data.get("Maximum", {}).get("Value")
        low_temp = temp_data.get("Minimum", {}).get("Value")

        if high_temp is None:
            return None

        # Use the high temp as the central estimate
        forecast_temp = float(high_temp)

        # Same normal distribution model as NOAA
        sigma = 4.0  # AccuWeather slightly wider uncertainty
        z_low = (low_f - forecast_temp) / sigma
        z_high = (high_f - forecast_temp) / sigma

        prob = _normal_cdf(z_high) - _normal_cdf(z_low)
        return max(0.0, min(1.0, prob))

    # ── Shared Helpers ─────────────────────────────────────────────────────

    def _parse_temperature_bracket(self, question: str) -> tuple[int, int] | None:
        """Extract temperature bracket (low, high) from a market question."""
        match = TEMP_BRACKET_PATTERN.search(question)
        if not match:
            return None
        low = int(match.group(1))
        high = int(match.group(2))
        if low >= high or high - low > 30:
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
        model uncertainty as a gaussian with σ=3.5°F around the point forecast.
        """
        periods = self._forecasts.get(station, [])
        if not periods:
            return None

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

        sigma = 3.5
        z_low = (low_f - forecast_temp) / sigma
        z_high = (high_f - forecast_temp) / sigma

        prob = _normal_cdf(z_high) - _normal_cdf(z_low)
        return max(0.0, min(1.0, prob))

    # ── Position Management ────────────────────────────────────────────────

    async def _manage_positions(self) -> None:
        """Monitor positions: take-profit at fair value, stop-loss at entry - 5%."""
        for token_id, pos in list(self._positions.items()):
            try:
                current_price = await self._client.get_midpoint(token_id)
            except Exception:
                continue

            entry_price = pos["entry_price"]
            fair_value = pos["fair_value"]
            stop_loss_pct = self._params["stop_loss_pct"]

            # Take profit: price reached fair value
            if self._params["take_profit_at_fair_value"] and current_price >= fair_value - 0.02:
                logger.info(
                    "weather_take_profit",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                    target=fair_value,
                    is_rare=pos.get("is_rare_event", False),
                )
                await self._exit_position(token_id, "take_profit")
                continue

            # Stop loss: price dropped below entry - stop_loss_pct
            if current_price <= entry_price * (1.0 - stop_loss_pct):
                logger.info(
                    "weather_stop_loss",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                    stop_level=round(entry_price * (1.0 - stop_loss_pct), 4),
                )
                await self._exit_position(token_id, "stop_loss")
                continue

            # Time exit: 6 hours max for regular, 24 hours for rare events
            max_hold = 24 * 3600 if pos.get("is_rare_event") else 6 * 3600
            if time.time() - pos["bought_at"] > max_hold:
                logger.info(
                    "weather_time_exit",
                    market=pos["market"],
                    entry=entry_price,
                    current=current_price,
                    hold_hours=round((time.time() - pos["bought_at"]) / 3600, 1),
                )
                await self._exit_position(token_id, "time_limit")
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
