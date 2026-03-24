"""Weather market strategy — NOAA data edge vs market price comparison.

Enhanced strategy using dedicated NOAA client for fast, parallel data pulls
every 5 minutes across 7 cities. Compares NOAA-implied fair prices against
Kalshi and Polymarket weather markets. Position sizing based on edge magnitude
(5c/10c/15c tiers). Exit logic: take profit when edge narrows, stop loss,
exit before resolution.

Key insight: NOAA forecasts update every 5-10 minutes but weather markets
lag by 6-12 hours. The edge is in speed.

Pipeline:
    1. SCAN  — Pull NOAA data + fetch active weather markets (both platforms)
    2. PRICE — Calculate NOAA-implied fair price for each market
    3. EDGE  — Compare fair price vs market price, filter by thresholds
    4. SIZE  — Position sizing based on edge magnitude (5c/10c/15c tiers)
    5. EXECUTE — Place order with exit logic (take-profit, stop-loss, time)
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner
from src.noaa_client import KALSHI_STATIONS, NOAAClient
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY, SIDE_SELL
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy

logger = structlog.get_logger(__name__)

# Temperature bracket pattern: "Will it be 80-85°F in Denver on March 25?"
TEMP_BRACKET_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# "above X°F" pattern for threshold markets
TEMP_ABOVE_PATTERN = re.compile(
    r"(?:above|over|exceed|higher\s+than|greater\s+than)\s+(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# "below X°F" pattern
TEMP_BELOW_PATTERN = re.compile(
    r"(?:below|under|lower\s+than|less\s+than)\s+(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# City/location patterns for matching weather markets to stations
CITY_PATTERNS: dict[str, list[str]] = {
    "KNYC": ["new york", "nyc", "manhattan", "central park"],
    "KORD": ["chicago", "ord", "o'hare"],
    "KLAX": ["los angeles", "la", "lax"],
    "KDEN": ["denver", "den", "colorado"],
    "KJFK": ["jfk", "kennedy"],
    "KATL": ["atlanta", "atl"],
    "KMIA": ["miami", "mia"],
}

# AccuWeather location keys for cross-validation
ACCUWEATHER_CITY_KEYS: dict[str, str] = {
    "denver": "347810",
    "new york": "349727",
    "los angeles": "347625",
    "chicago": "348308",
    "atlanta": "348181",
    "miami": "347936",
}

# NOAA forecast uncertainty (standard deviation in °F)
NOAA_SIGMA = 3.5


@dataclass
class WeatherPosition:
    """Tracks a single weather market position (paper or live)."""

    market_ticker: str
    market_title: str
    platform: str  # "kalshi" or "polymarket"
    side: str  # "yes", "no", "BUY", or "SELL"
    entry_price: float
    size: float
    entry_time: float
    edge_at_entry: float
    station: str
    fair_value: float = 0.0
    end_date: str = ""


class WeatherPositionTracker:
    """In-memory tracker for open weather positions."""

    def __init__(self) -> None:
        self.positions: dict[str, WeatherPosition] = {}

    def enter(self, pos: WeatherPosition) -> None:
        self.positions[pos.market_ticker] = pos

    def exit(self, ticker: str) -> WeatherPosition | None:
        return self.positions.pop(ticker, None)

    def has_position(self, ticker: str) -> bool:
        return ticker in self.positions

    def all_positions(self) -> list[WeatherPosition]:
        return list(self.positions.values())


class WeatherTraderStrategy(BaseStrategy):
    """Trades weather markets using NOAA data edge vs market prices.

    Core logic (every 5 minutes):
    1. Pull NOAA current temp + forecast for all stations
    2. Fetch active Kalshi weather markets
    3. Fetch active Polymarket weather markets
    4. For each market: calculate NOAA-implied fair price, compare to market
    5. If edge > 5c → signal. Edge > 10c → trade. Edge > 15c → larger position.
    """

    name = "weather_trader"
    description = "Weather market edge trading — NOAA data vs market price comparison"

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

        # Edge thresholds (in dollars, converted from cents)
        self._min_edge = settings.weather_min_edge_cents / 100.0
        self._strong_edge = settings.weather_strong_edge_cents / 100.0
        self._very_strong_edge = settings.weather_very_strong_edge_cents / 100.0
        self._take_profit_edge = settings.weather_take_profit_edge_cents / 100.0
        self._stop_loss_pct = settings.weather_stop_loss_pct
        self._exit_before_resolution_min = settings.weather_exit_before_resolution_minutes
        self._max_position_size = settings.weather_max_position_size

        self._params = {
            "stations": settings.weather_noaa_stations,
            "min_edge": self._min_edge,
            "strong_edge": self._strong_edge,
            "very_strong_edge": self._very_strong_edge,
            "max_position_size": self._max_position_size,
            "take_profit_edge": self._take_profit_edge,
            "stop_loss_pct": self._stop_loss_pct,
            "exit_before_resolution_min": self._exit_before_resolution_min,
        }

        # NOAA client — will be initialized in start()
        self._noaa: NOAAClient | None = None
        self._noaa_stations = settings.weather_noaa_stations
        self._vc_key = settings.visual_crossing_api_key

        # Kalshi client (injected from main.py if available)
        self._kalshi_client: Any = None

        # Position tracking via dedicated tracker
        self._position_tracker = WeatherPositionTracker()

        # Station data cache (populated each tick from NOAA client)
        self._station_data: dict[str, dict[str, Any]] = {}

        # Edge tracking for API endpoint
        self._current_edges: list[dict[str, Any]] = []

    def set_kalshi_client(self, client: Any) -> None:
        """Attach Kalshi platform client for dual-platform execution."""
        self._kalshi_client = client

    @property
    def current_edges(self) -> list[dict[str, Any]]:
        """Current calculated edges (exposed for /weather/edges endpoint)."""
        return list(self._current_edges)

    @property
    def station_data(self) -> dict[str, dict[str, Any]]:
        """Current NOAA station data (exposed for /weather/current endpoint)."""
        return dict(self._station_data)

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start strategy: initialize NOAA client and resolve grid points."""
        self._noaa = NOAAClient(
            stations=self._noaa_stations,
            visual_crossing_key=self._vc_key,
        )
        await self._noaa.initialize()
        await super().start(params)

    async def stop(self) -> None:
        """Stop strategy: exit positions and close NOAA client."""
        for pos in list(self._position_tracker.all_positions()):
            await self._exit_position(pos.market_ticker, "strategy_stop")
        if self._noaa:
            await self._noaa.close()
        await super().stop()

    async def on_tick(self) -> None:
        """Execute the weather edge pipeline each tick."""
        # Step 1: Pull fresh NOAA data for all stations
        if not self._noaa:
            return

        self._station_data = await self._noaa.get_all_stations()
        if not self._station_data:
            logger.warning("weather_no_station_data")
            return

        # Step 2: Scan for weather markets on both platforms
        edges: list[dict[str, Any]] = []

        # Polymarket weather markets
        poly_markets = await self._scan_polymarket_weather()
        for mkt in poly_markets:
            edge_info = self._calculate_edge(mkt, platform="polymarket")
            if edge_info:
                edges.append(edge_info)

        # Kalshi weather markets (if client available)
        if self._kalshi_client:
            kalshi_markets = await self._scan_kalshi_weather()
            for mkt in kalshi_markets:
                edge_info = self._calculate_edge(mkt, platform="kalshi")
                if edge_info:
                    edges.append(edge_info)

        # Store edges for API endpoint
        self._current_edges = edges

        # Step 3: Execute on edges that meet thresholds
        for edge_info in edges:
            await self._execute_on_edge(edge_info)

        # Step 4: Manage existing positions (take-profit, stop-loss, time exit)
        await self._manage_positions()

        logger.info(
            "weather_tick_complete",
            stations=len(self._station_data),
            poly_markets=len(poly_markets),
            kalshi_markets=len(kalshi_markets) if self._kalshi_client else 0,
            edges_found=len(edges),
            positions=len(self._position_tracker.positions),
        )

    # ── Market Scanning ───────────────────────────────────────────────────

    async def _scan_polymarket_weather(self) -> list[dict[str, Any]]:
        """Scan Polymarket for active weather contracts."""
        search_terms = [
            "temperature", "weather forecast", "degrees fahrenheit",
            "high temperature", "low temperature", "frost", "precipitation",
        ]

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

        logger.debug("weather_poly_scan", markets_found=len(unique))
        return unique

    async def _scan_kalshi_weather(self) -> list[dict[str, Any]]:
        """Scan Kalshi for active weather markets using the events→markets flow.

        Kalshi weather markets are organized as:
          series (e.g. KXHIGHNY) → events (e.g. KXHIGHNY-26MAR25) → markets/contracts

        We fetch events for each series ticker, then fetch individual contracts
        within each event to get prices.
        """
        if not self._kalshi_client:
            return []

        # NOAA station → Kalshi series tickers
        station_to_kalshi: dict[str, dict[str, str]] = {
            "KNYC": {"high": "KXHIGHNY", "low": "KXLOWNY"},
            "KORD": {"high": "KXHIGHCH", "low": "KXLOWCH"},
            "KLAX": {"high": "KXHIGHLA", "low": "KXLOWLA"},
            "KDEN": {"high": "KXHIGHDN", "low": "KXLOWDN"},
            "KJFK": {"high": "KXHIGHNY", "low": "KXLOWNY"},  # JFK uses NYC markets
            "KATL": {"high": "KXHIGHAT", "low": "KXLOWAT"},
            "KMIA": {"high": "KXHIGHMI", "low": "KXLOWMI"},
        }

        # Collect unique series tickers from configured stations and build
        # reverse mapping so we can propagate station onto each market.
        series_tickers: set[str] = set()
        series_to_station: dict[str, str] = {}
        for station in self._noaa_stations:
            mapping = station_to_kalshi.get(station)
            if mapping:
                for ticker in mapping.values():
                    series_tickers.add(ticker)
                    # First station wins (KJFK shares tickers with KNYC)
                    series_to_station.setdefault(ticker, station)

        all_markets: list[dict[str, Any]] = []

        for series_ticker in sorted(series_tickers):
            try:
                # Step 1: Fetch events for this series
                events = await self._kalshi_client.get_events(
                    series_ticker=series_ticker, status="open",
                )
                logger.info(
                    "kalshi_weather_series_scan",
                    series_ticker=series_ticker,
                    station=series_to_station.get(series_ticker, "?"),
                    events_found=len(events) if events else 0,
                )
                if not events:
                    continue

                # Step 2: For each event, fetch individual contracts
                for event in events:
                    event_ticker = event.get("event_ticker", "")
                    if not event_ticker:
                        continue

                    markets = await self._kalshi_client.get_event_markets(event_ticker)
                    for m in markets:
                        # Filter: only active markets with volume
                        if m.get("status") != "active":
                            continue
                        volume = float(m.get("volume_24h_fp", 0) or 0)
                        if volume <= 0:
                            continue

                        m["_platform"] = "kalshi"
                        m["_series_ticker"] = series_ticker
                        m["_event_ticker"] = event_ticker
                        m["_station"] = series_to_station.get(series_ticker, "")
                        all_markets.append(m)

            except Exception as exc:
                logger.warning(
                    "kalshi_weather_series_error",
                    series_ticker=series_ticker,
                    error=str(exc),
                )
                continue

        logger.info(
            "kalshi_weather_scan_complete",
            series_scanned=len(series_tickers),
            markets_found=len(all_markets),
        )
        return all_markets

    # ── Edge Calculation ──────────────────────────────────────────────────

    def _calculate_edge(
        self, market: dict[str, Any], platform: str
    ) -> dict[str, Any] | None:
        """Calculate the edge between NOAA-implied fair price and market price.

        Returns edge info dict or None if no edge found.
        """
        if platform == "polymarket":
            return self._calc_polymarket_edge(market)
        elif platform == "kalshi":
            return self._calc_kalshi_edge(market)
        return None

    def _calc_polymarket_edge(self, mkt: dict[str, Any]) -> dict[str, Any] | None:
        """Calculate edge for a Polymarket weather market."""
        question = mkt.get("question", "")
        tokens = mkt.get("tokens", [])
        if len(tokens) < 2:
            return None

        # Parse market type and get fair value
        fair_value = self._get_fair_value(question)
        if fair_value is None:
            return None

        # Get market price
        token_id_yes = tokens[0].get("token_id", "")
        market_price = float(tokens[0].get("price", 0))
        if market_price <= 0:
            return None

        edge = fair_value - market_price

        if abs(edge) < self._min_edge:
            return None

        return {
            "platform": "polymarket",
            "market_id": mkt.get("condition_id", ""),
            "token_id": token_id_yes,
            "question": question,
            "market_price": round(market_price, 4),
            "fair_value": round(fair_value, 4),
            "edge": round(edge, 4),
            "abs_edge": round(abs(edge), 4),
            "side": "BUY" if edge > 0 else "SELL",
            "end_date": mkt.get("end_date_iso", ""),
            "tokens": tokens,
        }

    def _calc_kalshi_edge(self, mkt: dict[str, Any]) -> dict[str, Any] | None:
        """Calculate edge for a Kalshi weather market.

        Uses structured strike fields (strike_type, floor_strike, cap_strike)
        from the Kalshi API instead of regex-parsing market titles.
        """
        title = mkt.get("title", "")
        ticker = mkt.get("ticker", "")
        strike_type = mkt.get("strike_type", "")
        floor_strike = mkt.get("floor_strike")
        cap_strike = mkt.get("cap_strike")

        # Match market to a NOAA station — prefer the station attached during
        # scanning (from series_ticker mapping), fall back to title matching.
        station = mkt.get("_station") or self._match_station(title)
        if station is None or station not in self._station_data:
            return None

        data = self._station_data[station]
        forecast = data.get("forecast")
        if not forecast:
            return None

        forecast_high = forecast.get("forecast_high_f")
        forecast_low = forecast.get("forecast_low_f")

        # Determine fair value from strike fields
        fair_value: float | None = None

        if strike_type == "between" and floor_strike is not None and cap_strike is not None:
            if forecast_high is not None:
                fair_value = _bracket_probability(
                    forecast_high, float(floor_strike), float(cap_strike), NOAA_SIGMA,
                )
        elif strike_type == "greater" and floor_strike is not None:
            if forecast_high is not None:
                fair_value = _above_probability(
                    forecast_high, float(floor_strike), NOAA_SIGMA,
                )
        elif strike_type == "less" and cap_strike is not None:
            ref_temp = forecast_low if forecast_low is not None else forecast_high
            if ref_temp is not None:
                fair_value = _below_probability(
                    ref_temp, float(cap_strike), NOAA_SIGMA,
                )

        # Fallback: try title-based parsing if strike fields are missing
        if fair_value is None:
            fair_value = self._get_fair_value(title, station_hint=station)

        if fair_value is None:
            return None

        # Price fields are dollar strings like "0.0400"
        yes_price = float(mkt.get("yes_ask_dollars", 0) or 0)

        if yes_price <= 0:
            return None

        edge = fair_value - yes_price

        if abs(edge) < self._min_edge:
            return None

        return {
            "platform": "kalshi",
            "market_id": ticker,
            "token_id": ticker,
            "question": title,
            "station": station,
            "strike_type": strike_type,
            "floor_strike": floor_strike,
            "cap_strike": cap_strike,
            "market_price": round(yes_price, 4),
            "fair_value": round(fair_value, 4),
            "edge": round(edge, 4),
            "abs_edge": round(abs(edge), 4),
            "side": "yes" if edge > 0 else "no",
            "end_date": mkt.get("close_time", ""),
            "volume": float(mkt.get("volume_24h_fp", 0) or 0),
        }

    def _get_fair_value(
        self, question: str, station_hint: str | None = None,
    ) -> float | None:
        """Calculate NOAA-implied fair value for a weather market question.

        Handles:
        - high_temp_above: "Will NYC high temp be above 75°F?"
        - low_temp_below: "Will low temp be under 32°F?"
        - temp_bracket: "Will it be 80-85°F in Denver?"
        """
        station = station_hint or self._match_station(question)
        if station is None or station not in self._station_data:
            return None

        data = self._station_data[station]
        forecast = data.get("forecast")
        if not forecast:
            return None

        forecast_high = forecast.get("forecast_high_f")
        forecast_low = forecast.get("forecast_low_f")

        # Try bracket pattern first: "80-85°F"
        bracket = self._parse_bracket(question)
        if bracket:
            low_f, high_f = bracket
            if forecast_high is not None:
                return _bracket_probability(forecast_high, low_f, high_f, NOAA_SIGMA)

        # Try "above X°F" pattern
        above_match = TEMP_ABOVE_PATTERN.search(question)
        if above_match and forecast_high is not None:
            threshold = float(above_match.group(1))
            return _above_probability(forecast_high, threshold, NOAA_SIGMA)

        # Try "below X°F" pattern
        below_match = TEMP_BELOW_PATTERN.search(question)
        if below_match:
            threshold = float(below_match.group(1))
            # Use low forecast for "below" questions if available
            ref_temp = forecast_low if forecast_low is not None else forecast_high
            if ref_temp is not None:
                return _below_probability(ref_temp, threshold, NOAA_SIGMA)

        return None

    def _match_station(self, question: str) -> str | None:
        """Match a market question to a NOAA station based on city references."""
        question_lower = question.lower()

        for station, patterns in CITY_PATTERNS.items():
            if station in self._station_data:
                for pattern in patterns:
                    if pattern in question_lower:
                        return station

        # Also check NOAA client's station metadata
        for station, data in self._station_data.items():
            city = data.get("city", "").lower()
            if city and city in question_lower:
                return station

        return None

    def _parse_bracket(self, question: str) -> tuple[int, int] | None:
        """Extract temperature bracket (low, high) from a market question."""
        match = TEMP_BRACKET_PATTERN.search(question)
        if not match:
            return None
        low = int(match.group(1))
        high = int(match.group(2))
        if low >= high or high - low > 30:
            return None
        return (low, high)

    # ── Position Sizing ───────────────────────────────────────────────────

    def _calculate_position_size(self, edge: float) -> float:
        """Position sizing based on edge magnitude (tiered).

        >= 15 cents: full position
        >= 10 cents: half position
        >= 5 cents: quarter position
        """
        abs_edge = abs(edge)

        if abs_edge >= self._very_strong_edge:
            size = self._max_position_size
        elif abs_edge >= self._strong_edge:
            size = self._max_position_size * 0.5
        elif abs_edge >= self._min_edge:
            size = self._max_position_size * 0.25
        else:
            return 0.0

        return round(max(size, 5.0), 2)  # Minimum $5 position

    # ── Trade Execution ───────────────────────────────────────────────────

    async def _execute_on_edge(self, edge_info: dict[str, Any]) -> None:
        """Execute a trade based on edge calculation."""
        token_id = edge_info["token_id"]
        edge = edge_info["edge"]
        platform = edge_info["platform"]

        # Don't re-enter existing positions
        if self._position_tracker.has_position(token_id):
            return

        # Filter: check time to expiry
        end_date = edge_info.get("end_date", "")
        if end_date and not self._check_time_to_expiry(end_date):
            return

        # Calculate position size
        size = self._calculate_position_size(edge)
        if size <= 0:
            return

        market_price = edge_info["market_price"]
        question = edge_info["question"]

        logger.info(
            "weather_edge_signal",
            platform=platform,
            market=question[:80],
            market_price=market_price,
            fair_value=edge_info["fair_value"],
            edge=edge,
            size=size,
            tier="very_strong" if abs(edge) >= self._very_strong_edge
                 else "strong" if abs(edge) >= self._strong_edge
                 else "standard",
        )

        if platform == "polymarket":
            await self._execute_polymarket(edge_info, size)
        elif platform == "kalshi":
            await self._execute_kalshi(edge_info, size)

    async def _execute_polymarket(self, edge_info: dict[str, Any], size: float) -> None:
        """Place order on Polymarket."""
        token_id = edge_info["token_id"]
        market_price = edge_info["market_price"]
        question = edge_info["question"]
        edge = edge_info["edge"]

        side = SIDE_BUY if edge > 0 else SIDE_SELL
        price = round(market_price + (0.01 if edge > 0 else -0.01), 2)

        order = await self._place_limit_order(
            token_id=token_id,
            market=question,
            price=price,
            size=size,
            side=side,
        )

        if order:
            side_str = "BUY" if side == SIDE_BUY else "SELL"
            station = self._match_station(question) or ""
            pos = WeatherPosition(
                market_ticker=token_id,
                market_title=question,
                platform="polymarket",
                side=side_str,
                entry_price=market_price,
                size=size,
                entry_time=time.time(),
                edge_at_entry=edge,
                station=station,
                fair_value=edge_info["fair_value"],
                end_date=edge_info.get("end_date", ""),
            )
            self._position_tracker.enter(pos)
            self._log_weather_paper_trade(pos)

    async def _execute_kalshi(self, edge_info: dict[str, Any], size: float) -> None:
        """Place order on Kalshi."""
        if not self._kalshi_client:
            return

        from src.platforms.base import Order

        ticker = edge_info["market_id"]
        market_price = edge_info["market_price"]
        edge = edge_info["edge"]
        side_str = edge_info["side"]  # "yes" or "no"

        order = Order(
            platform="kalshi",
            market_id=ticker,
            side=side_str,
            size=min(size, self._max_position_size),
            price=round(market_price + (0.01 if edge > 0 else -0.01), 2),
            order_type="limit",
        )

        try:
            result = await self._kalshi_client.place_order(order)
            logger.info(
                "kalshi_weather_order_placed",
                ticker=ticker,
                side=side_str,
                price=order.price,
                size=order.size,
            )

            station = self._match_station(edge_info["question"]) or ""
            pos = WeatherPosition(
                market_ticker=ticker,
                market_title=edge_info["question"],
                platform="kalshi",
                side=side_str,
                entry_price=market_price,
                size=size,
                entry_time=time.time(),
                edge_at_entry=edge,
                station=station,
                fair_value=edge_info["fair_value"],
                end_date=edge_info.get("end_date", ""),
            )
            self._position_tracker.enter(pos)
            self._log_weather_paper_trade(pos)

        except Exception as exc:
            logger.error("kalshi_weather_order_error", ticker=ticker, error=str(exc))

    # ── Position Management ───────────────────────────────────────────────

    async def _manage_positions(self) -> None:
        """Monitor positions for exit conditions: take-profit, stop-loss, time-based."""
        for pos in list(self._position_tracker.all_positions()):
            ticker = pos.market_ticker

            # Re-fetch current market price from the platform API
            current_price = await self._get_current_price(ticker, pos.platform)

            # If price fetch fails, use entry price as fallback — don't exit on missing data
            if current_price is None or current_price <= 0:
                logger.debug(
                    "weather_price_fetch_failed",
                    ticker=ticker,
                    platform=pos.platform,
                    fallback="entry_price",
                )
                current_price = pos.entry_price

            entry_price = pos.entry_price
            fair_value = pos.fair_value

            # Recalculate fair value from latest NOAA data
            new_fair = self._get_fair_value(pos.market_title)
            if new_fair is not None:
                fair_value = new_fair

            current_edge = abs(fair_value - current_price)

            # Exit 1: Take profit — edge narrowed to < take_profit_edge
            if current_edge < self._take_profit_edge:
                logger.info(
                    "weather_take_profit",
                    market=pos.market_title[:60],
                    entry=entry_price,
                    current=current_price,
                    edge_remaining=round(current_edge, 4),
                    platform=pos.platform,
                )
                await self._exit_position(ticker, "take_profit")
                continue

            # Exit 2: Stop loss — only trigger when current_price > 0 AND loss exceeds threshold
            if current_price > 0 and current_price != entry_price:
                if pos.side in ("BUY", "yes"):
                    loss_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0
                else:
                    loss_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

                if loss_pct >= self._stop_loss_pct:
                    logger.info(
                        "weather_stop_loss",
                        market=pos.market_title[:60],
                        entry=entry_price,
                        current=current_price,
                        loss_pct=round(loss_pct, 4),
                        platform=pos.platform,
                    )
                    await self._exit_position(ticker, "stop_loss")
                    continue

            # Exit 3: Time-based — exit before resolution
            end_date = pos.end_date
            if end_date:
                try:
                    expiry = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    minutes_to_expiry = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
                    if 0 < minutes_to_expiry < self._exit_before_resolution_min:
                        logger.info(
                            "weather_time_exit",
                            market=pos.market_title[:60],
                            minutes_to_expiry=round(minutes_to_expiry),
                            platform=pos.platform,
                        )
                        await self._exit_position(ticker, "pre_resolution")
                        continue
                except (ValueError, TypeError):
                    pass

    async def _exit_position(self, token_id: str, reason: str) -> None:
        """Exit a weather position on the appropriate platform."""
        pos = self._position_tracker.positions.get(token_id)
        if not pos:
            return

        try:
            if pos.platform == "polymarket":
                current_price = await self._get_current_price(token_id, "polymarket")
                if current_price and current_price > 0:
                    side = SIDE_SELL if pos.side == "BUY" else SIDE_BUY
                    if self._settings.dry_run:
                        self._record_paper_trade(
                            token_id=token_id,
                            market=pos.market_title,
                            price=current_price,
                            size=pos.size,
                            side=side,
                        )
                    else:
                        await self._client.place_order(
                            token_id=token_id,
                            price=current_price,
                            size=pos.size,
                            side=side,
                            order_type="FOK",
                        )

            elif pos.platform == "kalshi" and self._kalshi_client:
                from src.platforms.base import Order

                exit_side = "no" if pos.side == "yes" else "yes"
                current_price = await self._get_current_price(token_id, "kalshi")
                if current_price and current_price > 0:
                    order = Order(
                        platform="kalshi",
                        market_id=token_id,
                        side=exit_side,
                        size=pos.size,
                        price=current_price,
                        order_type="limit",
                    )
                    await self._kalshi_client.place_order(order)

            logger.info(
                "weather_position_exited",
                market=pos.market_title[:60],
                reason=reason,
                platform=pos.platform,
                entry_price=pos.entry_price,
                edge_at_entry=pos.edge_at_entry,
                hold_seconds=round(time.time() - pos.entry_time),
            )

        except Exception as exc:
            logger.error("weather_exit_error", token_id=token_id, error=str(exc))

        self._position_tracker.exit(token_id)

    async def _get_current_price(self, token_id: str, platform: str) -> float | None:
        """Get current price for a token/market on the given platform.

        For Kalshi: tries get_markets by ticker first, then falls back to
        get_event_markets using the event ticker derived from the market ticker.
        Returns yes_bid_dollars as the current price.
        """
        try:
            if platform == "polymarket":
                return await self._client.get_midpoint(token_id)
            elif platform == "kalshi" and self._kalshi_client:
                # Primary: fetch by ticker directly
                markets = await self._kalshi_client.get_markets(ticker=token_id, limit=1)
                if markets:
                    price = float(markets[0].get("yes_bid_dollars", 0) or 0)
                    if price > 0:
                        return price

                # Fallback: derive event ticker and fetch via get_event_markets
                # Kalshi tickers follow pattern: KXHIGHNY-26MAR25-B50-B55 -> event KXHIGHNY-26MAR25
                parts = token_id.split("-")
                if len(parts) >= 2:
                    event_ticker = "-".join(parts[:2])
                    event_markets = await self._kalshi_client.get_event_markets(event_ticker)
                    for m in event_markets:
                        if m.get("ticker") == token_id:
                            price = float(m.get("yes_bid_dollars", 0) or 0)
                            if price > 0:
                                return price
        except Exception as exc:
            logger.debug("weather_price_fetch_error", token_id=token_id, platform=platform, error=str(exc))
        return None

    def _log_weather_paper_trade(self, pos: WeatherPosition) -> None:
        """Log a weather trade entry to the paper ledger."""
        if not self._paper_ledger:
            return
        from src.paper_ledger import PaperTrade

        paper_trade = PaperTrade(
            timestamp=pos.entry_time,
            strategy="weather_trader",
            market_id=pos.market_ticker,
            market_question=pos.market_title,
            side="BUY" if pos.side in ("BUY", "yes") else "SELL",
            size=pos.size,
            price=pos.entry_price,
            signals={
                "platform": pos.platform,
                "edge": pos.edge_at_entry,
                "station": pos.station,
            },
        )
        self._paper_ledger.record(paper_trade)

    def get_positions_with_pnl(self) -> list[dict[str, Any]]:
        """Return all open positions with unrealized P&L for the API."""
        result: list[dict[str, Any]] = []
        for pos in self._position_tracker.all_positions():
            if pos.side in ("BUY", "yes"):
                # For long positions: unrealized = (fair_value - entry_price) * size
                unrealized_pnl = (pos.fair_value - pos.entry_price) * pos.size
            else:
                unrealized_pnl = (pos.entry_price - pos.fair_value) * pos.size

            result.append({
                "market_ticker": pos.market_ticker,
                "market_title": pos.market_title,
                "platform": pos.platform,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "size": pos.size,
                "entry_time": pos.entry_time,
                "edge_at_entry": pos.edge_at_entry,
                "station": pos.station,
                "fair_value": pos.fair_value,
                "unrealized_pnl": round(unrealized_pnl, 4),
                "hold_seconds": round(time.time() - pos.entry_time),
            })
        return result

    def _check_time_to_expiry(self, end_date: str) -> bool:
        """Return True if there's enough time before expiry to enter."""
        try:
            expiry = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            minutes = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
            return minutes > self._exit_before_resolution_min * 2  # Need 2x buffer to enter
        except (ValueError, TypeError):
            return True  # If we can't parse, allow the trade


# ── Probability Calculation Functions ─────────────────────────────────────


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using Abramowitz & Stegun approximation."""
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


def _bracket_probability(forecast_temp: float, low: float, high: float, sigma: float) -> float:
    """Probability that actual temp falls in [low, high] given forecast and uncertainty."""
    z_low = (low - forecast_temp) / sigma
    z_high = (high - forecast_temp) / sigma
    prob = _normal_cdf(z_high) - _normal_cdf(z_low)
    return max(0.0, min(1.0, prob))


def _above_probability(forecast_temp: float, threshold: float, sigma: float) -> float:
    """Probability that actual temp exceeds threshold."""
    z = (threshold - forecast_temp) / sigma
    prob = 1.0 - _normal_cdf(z)
    return max(0.0, min(1.0, prob))


def _below_probability(forecast_temp: float, threshold: float, sigma: float) -> float:
    """Probability that actual temp is below threshold."""
    z = (threshold - forecast_temp) / sigma
    prob = _normal_cdf(z)
    return max(0.0, min(1.0, prob))
