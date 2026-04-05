"""Weather market strategy — Cheap bracket ladder (neobrother approach).

STRATEGY UPGRADE: Instead of buying the most likely bracket at 80-97¢ (terrible
risk/reward), we now buy CHEAP adjacent brackets at 0.2-15¢ and let the 400-1000%
winner cover all the small losses.

Inspiration from top Polymarket weather traders:
- neobrother: $20K+ profit buying dense low-cost orders (0.2-15¢) within a range
- Hans323: $1.1M volume using cheap bracket laddering — one 800%+ hit covers all rungs
- "Weather is pure physics and math — if your model is better than the crowd's, you profit"

Core insight: NOAA forecasts have ~3.5°F standard deviation. When GFS predicts 78°F:
  - 75-80°F bracket: ~60¢ (SKIP — too expensive, bad risk/reward)
  - 70-75°F bracket: ~15¢ ← BUY (if off by 5°F: 566% return)
  - 65-70°F bracket: ~5¢  ← BUY (if off by 8°F: 1900% return)
  - 80-85°F bracket: ~12¢ ← BUY (if off by 4°F: 733% return)
  - 85-90°F bracket: ~4¢  ← BUY (if off by 9°F: 2400% return)

Pipeline:
    1. SCAN    — Fetch active weather markets from Polymarket Gamma API
    2. FORECAST — Pull NOAA/METAR forecast for city+date
    3. MAP     — Identify all brackets for the market and their prices
    4. FILTER  — Skip highest-probability bracket (>25¢), buy cheap adjacent ones
    5. SIZE    — $3-5 per bracket (max $15 per city/date)
    6. EXECUTE — Place orders via py_clob_client, register in shared registry
    7. EXIT    — Time-based primary (24-48h), stop-loss secondary
    8. TRACK   — Log hit rate per city, detect consistent forecast bias
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner
from src.noaa_client import KALSHI_STATIONS, NOAAClient
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY, SIDE_SELL
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy

if TYPE_CHECKING:
    from strategies.strategy_manager import SharedPositionRegistry, StrategyPnL

logger = structlog.get_logger(__name__)

# ── Temperature parsing patterns ───────────────────────────────────────────────

TEMP_BRACKET_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

TEMP_ABOVE_PATTERN = re.compile(
    r"(?:above|over|exceed|higher\s+than|greater\s+than)\s+(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

TEMP_BELOW_PATTERN = re.compile(
    r"(?:below|under|lower\s+than|less\s+than)\s+(\d+)\s*°?\s*F",
    re.IGNORECASE,
)

# Celsius patterns (Polymarket international markets)
TEMP_BRACKET_C_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*°?\s*C\b",
    re.IGNORECASE,
)

TEMP_EXACT_C_PATTERN = re.compile(
    r"be\s+(\d+)\s*°?\s*C\b",
    re.IGNORECASE,
)

# City → NOAA station lookup
CITY_PATTERNS: dict[str, list[str]] = {
    "KNYC": ["new york", "nyc", "manhattan", "central park"],
    "KORD": ["chicago", "ord", "o'hare"],
    "KLAX": ["los angeles", "la", "lax"],
    "KDEN": ["denver", "den", "colorado"],
    "KJFK": ["jfk", "kennedy"],
    "KATL": ["atlanta", "atl"],
    "KMIA": ["miami", "mia"],
}

# City → METAR station (for international cities not in KALSHI_STATIONS)
CITY_METAR_STATIONS: dict[str, list[str]] = {
    "shanghai": ["ZSPD", "ZSSS"],
    "beijing": ["ZBAA", "ZBAD"],
    "tokyo": ["RJTT", "RJAA"],
    "seoul": ["RKSI", "RKSS"],
    "hong kong": ["VHHH"],
    "london": ["EGLL", "EGSS"],
    "paris": ["LFPG", "LFPO"],
    "ankara": ["LTAC"],
    "dubai": ["OMDB"],
    "singapore": ["WSSS"],
    "istanbul": ["LTFM", "LTBA"],
    "moscow": ["UUEE", "UUDD"],
    "delhi": ["VIDP"],
    "mumbai": ["VABB"],
}

# NOAA forecast uncertainty — σ in °F
# Based on NWS Day-1 verification studies (~3.5°F RMSE for 24h forecast)
# Slightly wider for international cities using METAR-only data
NOAA_SIGMA_F = 3.5
METAR_SIGMA_F = 4.5   # wider for international cities

# ── Cheap bracket configuration ────────────────────────────────────────────────

# Maximum price to buy a bracket (neobrother: 0.2-15¢, we allow up to 25¢)
CHEAP_BRACKET_MAX_PRICE = 0.25

# Default position size per bracket (USD)
BRACKET_DEFAULT_SIZE = 3.0
BRACKET_MAX_SIZE = 5.0

# Maximum total exposure per city/date event
MAX_EXPOSURE_PER_EVENT = 15.0

# How far out (in °F) from the forecast to scan for brackets
# neobrother uses ±15°F range to build the full ladder
BRACKET_SCAN_RANGE_F = 15.0

# Minimum expected return multiple to buy (skip brackets with <3x potential)
MIN_POTENTIAL_RETURN_X = 3.0

# Typical bracket width in °F (Polymarket/Kalshi use 5°F brackets)
TYPICAL_BRACKET_WIDTH_F = 5.0


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class CheapBracket:
    """A candidate cheap bracket position identified by the strategy."""

    market_id: str          # Polymarket condition_id or Kalshi ticker
    token_id: str           # Token to buy (YES side)
    platform: str           # "polymarket" or "kalshi"
    city: str
    station: str
    question: str
    bracket_low_f: float    # Lower bound of this bracket in °F
    bracket_high_f: float   # Upper bound of this bracket in °F
    entry_price: float      # Current ask price (e.g., 0.07)
    forecast_temp_f: float  # NOAA/METAR forecast for this city
    forecast_sigma_f: float # Uncertainty (σ) of the forecast
    fair_value: float       # Our model's probability for this bracket
    potential_return_x: float  # (1 / entry_price) — how many x on a win
    bracket_offset_f: float    # Distance from forecast center
    end_date: str = ""
    event_key: str = ""     # "city|date" for per-event exposure tracking


@dataclass
class WeatherPosition:
    """Tracks an open cheap bracket position."""

    market_ticker: str
    market_title: str
    platform: str
    side: str               # "BUY" (always for cheap brackets)
    entry_price: float
    size: float
    entry_time: float
    edge_at_entry: float    # Fair value - entry price (can be negative for cheap brackets)
    station: str
    fair_value: float = 0.0
    end_date: str = ""
    bracket_low_f: float = 0.0
    bracket_high_f: float = 0.0
    forecast_temp_f: float = 0.0
    city: str = ""
    event_key: str = ""     # For per-event exposure tracking


# ── Position tracker ───────────────────────────────────────────────────────────


class WeatherPositionTracker:
    """In-memory tracker for open weather positions."""

    def __init__(self) -> None:
        self.positions: dict[str, WeatherPosition] = {}
        # event_key → total USD exposure (prevents overloading one city/date)
        self._event_exposure: dict[str, float] = {}

    def enter(self, pos: WeatherPosition) -> None:
        self.positions[pos.market_ticker] = pos
        if pos.event_key:
            self._event_exposure[pos.event_key] = (
                self._event_exposure.get(pos.event_key, 0.0) + pos.size
            )

    def exit(self, ticker: str) -> WeatherPosition | None:
        pos = self.positions.pop(ticker, None)
        if pos and pos.event_key:
            current = self._event_exposure.get(pos.event_key, 0.0)
            self._event_exposure[pos.event_key] = max(0.0, current - pos.size)
        return pos

    def has_position(self, ticker: str) -> bool:
        return ticker in self.positions

    def get_event_exposure(self, event_key: str) -> float:
        return self._event_exposure.get(event_key, 0.0)

    def all_positions(self) -> list[WeatherPosition]:
        return list(self.positions.values())

    def total_exposure(self) -> float:
        return sum(p.size for p in self.positions.values())


# ── City forecast bias tracker ─────────────────────────────────────────────────


@dataclass
class ForecastBias:
    """Tracks how NOAA forecast accuracy compares to actual outcomes per city.

    If a city consistently resolves 2°F warmer than NOAA forecast, we shift
    our bracket buying to the warmer side.
    """

    city: str
    observations: list[float] = field(default_factory=list)  # forecast_error = actual - forecast
    max_observations: int = 50

    def record(self, forecast_f: float, actual_f: float) -> None:
        error = actual_f - forecast_f
        self.observations.append(error)
        if len(self.observations) > self.max_observations:
            self.observations.pop(0)

    @property
    def mean_bias_f(self) -> float:
        """Average forecast error (positive = NOAA runs cold, negative = NOAA runs warm)."""
        if not self.observations:
            return 0.0
        return sum(self.observations) / len(self.observations)

    @property
    def rmse_f(self) -> float:
        """Root mean square error of forecasts."""
        if not self.observations:
            return NOAA_SIGMA_F
        return math.sqrt(sum(e ** 2 for e in self.observations) / len(self.observations))

    @property
    def n(self) -> int:
        return len(self.observations)


# ── Main strategy class ────────────────────────────────────────────────────────


class WeatherTraderStrategy(BaseStrategy):
    """Cheap bracket ladder strategy for Polymarket weather markets.

    Core loop (every 15 minutes):
    1. Fetch active weather markets from Polymarket Gamma API
    2. For each market group (city + date), get NOAA/METAR forecast
    3. Map all available brackets and their current prices
    4. Skip the expensive (>25¢) most-likely bracket
    5. Buy cheap adjacent brackets (2-15¢) within ±15°F of forecast
    6. Size: $3-5 per bracket, max $15 per city/date
    7. Exit: time-based (market resolves 24-48h), stop-loss at -50%

    Why this works (neobrother / Hans323 approach):
    - Weather markets are "pure physics" — better models = consistent edge
    - Cheap brackets have asymmetric payoffs: risk $3, win $15-60+
    - Forecasts are wrong ~30% of the time by 4-8°F
    - One 800%+ win covers 8-20 small losses
    - Dense ladder catches the actual outcome wherever it lands
    """

    name = "weather_trader"
    description = "Cheap bracket ladder — buy 2-15¢ brackets adjacent to NOAA forecast"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = getattr(settings, "weather_check_interval_seconds", 900)  # 15 min

        # Edge / price thresholds
        self._cheap_bracket_max_price = CHEAP_BRACKET_MAX_PRICE
        self._bracket_default_size = getattr(settings, "weather_bracket_size_usd", BRACKET_DEFAULT_SIZE)
        self._bracket_max_size = getattr(settings, "weather_bracket_max_size_usd", BRACKET_MAX_SIZE)
        self._max_per_event = getattr(settings, "weather_max_exposure_per_event", MAX_EXPOSURE_PER_EVENT)
        self._bracket_scan_range_f = BRACKET_SCAN_RANGE_F
        self._stop_loss_pct = getattr(settings, "weather_stop_loss_pct", 0.50)
        self._exit_before_resolution_min = getattr(
            settings, "weather_exit_before_resolution_minutes", 30
        )
        self._max_open_positions = getattr(settings, "weather_max_open_positions", 30)

        # Legacy edge thresholds (kept for backward-compat with existing NOAA edge logic)
        self._min_edge = getattr(settings, "weather_min_edge_cents", 5) / 100.0
        self._strong_edge = getattr(settings, "weather_strong_edge_cents", 10) / 100.0
        self._very_strong_edge = getattr(settings, "weather_very_strong_edge_cents", 15) / 100.0
        self._take_profit_edge = getattr(settings, "weather_take_profit_edge_cents", 2) / 100.0
        self._max_position_size = getattr(settings, "weather_max_position_size", 15.0)

        self._params = {
            "cheap_bracket_max_price": self._cheap_bracket_max_price,
            "bracket_default_size": self._bracket_default_size,
            "bracket_max_size": self._bracket_max_size,
            "max_per_event": self._max_per_event,
            "bracket_scan_range_f": self._bracket_scan_range_f,
            "stop_loss_pct": self._stop_loss_pct,
            "exit_before_resolution_min": self._exit_before_resolution_min,
        }

        # NOAA client (initialized in start())
        self._noaa: NOAAClient | None = None
        self._noaa_stations = getattr(settings, "weather_noaa_stations", list(KALSHI_STATIONS.keys()))
        self._vc_key = getattr(settings, "visual_crossing_api_key", "")

        # Kalshi client (optional, injected from main.py)
        self._kalshi_client: Any = None

        # Shared position registry (injected by StrategyManager)
        self._registry: SharedPositionRegistry | None = None

        # Position tracking
        self._position_tracker = WeatherPositionTracker()

        # Station data cache
        self._station_data: dict[str, dict[str, Any]] = {}

        # Per-city forecast bias tracking (learns over time)
        self._city_bias: dict[str, ForecastBias] = {}

        # Current edges for API endpoint (legacy compat)
        self._current_edges: list[dict[str, Any]] = []

        # Per-tick stats
        self._stats = {
            "total_brackets_entered": 0,
            "total_brackets_won": 0,
            "total_brackets_lost": 0,
            "total_pnl": 0.0,
        }

    def set_kalshi_client(self, client: Any) -> None:
        """Attach Kalshi platform client for dual-platform execution."""
        self._kalshi_client = client

    def set_position_registry(self, registry: "SharedPositionRegistry") -> None:
        """Inject the shared position registry from StrategyManager."""
        self._registry = registry

    def set_strategy_pnl(self, pnl: "StrategyPnL") -> None:
        """Inject per-strategy P/L tracker from StrategyManager."""
        self._strategy_pnl = pnl

    @property
    def current_edges(self) -> list[dict[str, Any]]:
        """Current calculated edges (exposed for /weather/edges endpoint)."""
        return list(self._current_edges)

    @property
    def station_data(self) -> dict[str, dict[str, Any]]:
        """Current NOAA station data (exposed for /weather/current endpoint)."""
        return dict(self._station_data)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start strategy: initialize NOAA client and resolve grid points."""
        self._noaa = NOAAClient(
            stations=self._noaa_stations,
            visual_crossing_key=self._vc_key,
        )
        await self._noaa.initialize()
        await super().start(params)

        # Reconcile with on-chain positions so the count is correct after restart
        try:
            from src.position_syncer import sync_positions as _ps
            snap = await _ps(self._client)
            restored = 0
            for p in snap.positions:
                title = (p.market_title or "").lower()
                is_weather = any(kw in title for kw in ("temperature", "°c", "°f", "weather", "rain", "celsius", "fahrenheit", "highest temp"))
                if not is_weather:
                    continue
                if self._position_tracker.has_position(p.token_id):
                    continue
                self._position_tracker.positions[p.token_id] = WeatherPosition(
                    market_ticker=p.token_id,
                    token_id=p.token_id,
                    condition_id=p.condition_id,
                    outcome="YES",
                    size=p.shares * p.current_price if p.current_price > 0 else p.shares * p.avg_entry_price,
                    entry_price=p.avg_entry_price,
                    entered_at=datetime.now(timezone.utc),
                    city="",
                    date_str="",
                    bracket_label=p.market_title[:80],
                    event_key="",
                )
                restored += 1
            if restored:
                logger.info("weather_positions_restored_from_chain", count=restored)
        except Exception as exc:
            logger.debug("weather_position_restore_skip", error=str(exc))

        logger.info(
            "weather_strategy_started",
            mode="cheap_bracket_ladder",
            max_price=self._cheap_bracket_max_price,
            bracket_size=self._bracket_default_size,
            max_per_event=self._max_per_event,
            open_positions=len(self._position_tracker.positions),
        )

    async def stop(self) -> None:
        """Stop strategy: exit all positions and close NOAA client."""
        for pos in list(self._position_tracker.all_positions()):
            await self._exit_position(pos.market_ticker, "strategy_stop")
        if self._noaa:
            await self._noaa.close()
        await super().stop()

    # ── Main tick ─────────────────────────────────────────────────────────────

    async def on_tick(self) -> None:
        """Execute the cheap bracket pipeline each tick (every 15 minutes)."""
        if not self._noaa:
            return

        # Step 1: Pull fresh NOAA data for all stations
        self._station_data = await self._noaa.get_all_stations()
        if not self._station_data:
            logger.warning("weather_no_station_data")
            return

        # Step 2: Check position count limit before scanning
        if len(self._position_tracker.positions) >= self._max_open_positions:
            logger.info(
                "weather_position_limit_reached",
                open_positions=len(self._position_tracker.positions),
                limit=self._max_open_positions,
            )
            await self._manage_positions()
            return

        # Step 3: Scan Polymarket for weather bracket markets
        poly_markets = await self._scan_polymarket_weather()

        # Step 4: Group markets by city+date event
        event_groups = self._group_by_event(poly_markets)

        # Step 5: For each event, identify cheap bracket opportunities
        all_candidates: list[CheapBracket] = []
        for event_key, markets in event_groups.items():
            candidates = await self._find_cheap_brackets(event_key, markets)
            all_candidates.extend(candidates)

        # Also process Kalshi if available
        if self._kalshi_client:
            kalshi_markets = await self._scan_kalshi_weather()
            kalshi_groups = self._group_by_event(kalshi_markets)
            for event_key, markets in kalshi_groups.items():
                candidates = await self._find_cheap_brackets(event_key, markets, platform="kalshi")
                all_candidates.extend(candidates)

        # Store for API endpoint (legacy compat — convert to edge format)
        self._current_edges = [self._bracket_to_edge_dict(c) for c in all_candidates]

        # Step 6: Execute on candidates
        entered = 0
        for bracket in all_candidates:
            result = await self._execute_bracket(bracket)
            if result:
                entered += 1

        # Step 7: Manage existing positions
        await self._manage_positions()

        # Log per-event diagnostics for debugging zero-entry ticks
        if not all_candidates and event_groups:
            for ek, mkts in list(event_groups.items())[:3]:
                prices = []
                for m in mkts:
                    tokens = m.get("tokens", [])
                    for tok in tokens:
                        p = float(tok.get("price", 0))
                        if p > 0:
                            prices.append(round(p, 3))
                logger.info(
                    "weather_no_candidates_detail",
                    event_key=ek[:60],
                    market_count=len(mkts),
                    token_prices=prices[:10],
                    max_price_threshold=self._cheap_bracket_max_price,
                )

        logger.info(
            "weather_tick_complete",
            stations=len(self._station_data),
            poly_markets=len(poly_markets),
            event_groups=len(event_groups),
            candidates=len(all_candidates),
            entered_this_tick=entered,
            open_positions=len(self._position_tracker.positions),
            total_exposure=round(self._position_tracker.total_exposure(), 2),
            max_price_threshold=self._cheap_bracket_max_price,
        )

    # ── Market Scanning ───────────────────────────────────────────────────────

    async def _scan_polymarket_weather(self) -> list[dict[str, Any]]:
        """Scan Polymarket Gamma API for active weather bracket markets.

        Uses the category=weather filter and searches for temperature keywords.
        Deduplicates by condition_id.
        """
        all_markets: list[dict[str, Any]] = []

        # Primary: category-based scan via Gamma API
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as http:
                # Gamma API supports category filter
                resp = await http.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={
                        "category": "weather",
                        "active": "true",
                        "limit": 200,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    markets = data if isinstance(data, list) else data.get("markets", [])
                    all_markets.extend(markets)
                    logger.debug("gamma_weather_scan", count=len(markets))
        except Exception as exc:
            logger.warning("gamma_weather_scan_error", error=str(exc)[:80])

        # Secondary: text search for temperature keywords
        search_terms = ["highest temperature", "temperature", "degrees fahrenheit"]
        for query in search_terms:
            try:
                results = await self._client.search_markets(query, limit=100)
                all_markets.extend(results)
            except Exception:
                continue

        # Deduplicate by condition_id, keep only active markets
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for mkt in all_markets:
            cid = mkt.get("condition_id", mkt.get("id", ""))
            if cid and cid not in seen and mkt.get("active", True):
                seen.add(cid)
                unique.append(mkt)

        logger.debug("weather_poly_scan_complete", markets=len(unique))
        return unique

    async def _scan_kalshi_weather(self) -> list[dict[str, Any]]:
        """Scan Kalshi for active weather markets (unchanged from original)."""
        if not self._kalshi_client:
            return []

        station_to_kalshi: dict[str, dict[str, str]] = {
            "KNYC": {"high": "KXHIGHNY", "low": "KXLOWNY"},
            "KORD": {"high": "KXHIGHCH", "low": "KXLOWCH"},
            "KLAX": {"high": "KXHIGHLA", "low": "KXLOWLA"},
            "KDEN": {"high": "KXHIGHDN", "low": "KXLOWDN"},
            "KJFK": {"high": "KXHIGHNY", "low": "KXLOWNY"},
            "KATL": {"high": "KXHIGHAT", "low": "KXLOWAT"},
            "KMIA": {"high": "KXHIGHMI", "low": "KXLOWMI"},
        }

        series_tickers: set[str] = set()
        series_to_station: dict[str, str] = {}
        for station in self._noaa_stations:
            mapping = station_to_kalshi.get(station)
            if mapping:
                for ticker in mapping.values():
                    series_tickers.add(ticker)
                    series_to_station.setdefault(ticker, station)

        all_markets: list[dict[str, Any]] = []
        for series_ticker in sorted(series_tickers):
            try:
                events = await self._kalshi_client.get_events(
                    series_ticker=series_ticker, status="open"
                )
                if not events:
                    continue
                for event in events:
                    event_ticker = event.get("event_ticker", "")
                    if not event_ticker:
                        continue
                    markets = await self._kalshi_client.get_event_markets(event_ticker)
                    for m in markets:
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
                logger.warning("kalshi_scan_error", series=series_ticker, error=str(exc)[:60])

        return all_markets

    # ── Event Grouping ────────────────────────────────────────────────────────

    def _group_by_event(self, markets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group markets by city + resolution date.

        Key format: "city|YYYY-MM-DD"
        This lets us track total exposure per city/date and build the full bracket ladder.
        """
        groups: dict[str, list[dict[str, Any]]] = {}

        for mkt in markets:
            question = mkt.get("question", mkt.get("title", ""))
            city = self._extract_city(question) or "unknown"
            end_date = mkt.get("end_date_iso", mkt.get("close_time", ""))
            date_key = self._extract_date_key(end_date)
            event_key = f"{city}|{date_key}"

            if event_key not in groups:
                groups[event_key] = []
            groups[event_key].append(mkt)

        return groups

    def _extract_city(self, question: str) -> str | None:
        """Extract city name from a market question."""
        q_lower = question.lower()

        # Check NOAA stations
        for station, patterns in CITY_PATTERNS.items():
            for pat in patterns:
                if pat in q_lower:
                    return pat.split()[0]  # Use first word as city key

        # Check METAR cities (international)
        for city in CITY_METAR_STATIONS:
            if city in q_lower:
                return city

        return None

    def _extract_date_key(self, end_date: str) -> str:
        """Extract YYYY-MM-DD from an ISO datetime string."""
        if not end_date:
            return "unknown"
        try:
            dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return end_date[:10] if len(end_date) >= 10 else "unknown"

    # ── Cheap Bracket Identification ──────────────────────────────────────────

    async def _find_cheap_brackets(
        self,
        event_key: str,
        markets: list[dict[str, Any]],
        platform: str = "polymarket",
    ) -> list[CheapBracket]:
        """For a city+date event, identify all cheap bracket opportunities.

        Algorithm:
        1. Get NOAA forecast for this city
        2. For each market (bracket), extract the temperature range
        3. Skip brackets priced > 25¢ (too expensive)
        4. Skip the most-likely bracket (highest fair value)
        5. Return remaining cheap brackets sorted by potential return
        """
        city = event_key.split("|")[0]
        station = self._match_station_for_city(city)

        # Get forecast — try NOAA first, fall back to METAR
        forecast_temp_f, forecast_sigma_f = await self._get_forecast(city, station)
        if forecast_temp_f is None:
            return []

        # Apply learned city bias correction
        bias = self._city_bias.get(city)
        if bias and bias.n >= 5:
            forecast_temp_f += bias.mean_bias_f
            # Use historical RMSE as sigma if we have enough data
            if bias.n >= 10:
                forecast_sigma_f = max(bias.rmse_f, 1.0)

        logger.debug(
            "weather_forecast",
            event_key=event_key,
            city=city,
            station=station or "metar",
            forecast_f=round(forecast_temp_f, 1),
            sigma_f=round(forecast_sigma_f, 1),
        )

        candidates: list[CheapBracket] = []
        highest_fair_value = 0.0

        # First pass: compute fair values for all brackets
        bracket_info: list[tuple[dict[str, Any], float, float, float]] = []
        for mkt in markets:
            bracket = self._parse_bracket_from_market(mkt, platform)
            if bracket is None:
                continue

            bracket_low_f, bracket_high_f = bracket
            fair_value = _bracket_probability(forecast_temp_f, bracket_low_f, bracket_high_f, forecast_sigma_f)
            market_price = self._get_market_price(mkt, platform)

            if market_price <= 0 or market_price > 0.99:
                continue

            if fair_value > highest_fair_value:
                highest_fair_value = fair_value

            bracket_info.append((mkt, bracket_low_f, bracket_high_f, fair_value))

        # Second pass: filter for cheap brackets
        for mkt, bracket_low_f, bracket_high_f, fair_value in bracket_info:
            market_price = self._get_market_price(mkt, platform)

            # FILTER 1: Skip the most-likely bracket (highest fair value)
            # Also skip anything priced > cheap threshold
            if fair_value >= highest_fair_value * 0.85:
                # This bracket is within 85% of the best probability — too expensive
                logger.debug(
                    "weather_skip_likely_bracket",
                    bracket=f"{bracket_low_f:.0f}-{bracket_high_f:.0f}°F",
                    fair_value=round(fair_value, 3),
                    price=round(market_price, 3),
                )
                continue

            # FILTER 2: Price ceiling — only buy cheap brackets
            if market_price > self._cheap_bracket_max_price:
                logger.debug(
                    "weather_skip_expensive",
                    bracket=f"{bracket_low_f:.0f}-{bracket_high_f:.0f}°F",
                    price=round(market_price, 3),
                    max_price=self._cheap_bracket_max_price,
                )
                continue

            # FILTER 3: Must be within scan range of forecast
            bracket_center = (bracket_low_f + bracket_high_f) / 2
            offset_f = abs(bracket_center - forecast_temp_f)
            if offset_f > self._bracket_scan_range_f:
                continue

            # FILTER 4: Minimum potential return check
            potential_return_x = 1.0 / market_price if market_price > 0 else 0.0
            if potential_return_x < MIN_POTENTIAL_RETURN_X:
                continue

            # FILTER 5: Don't enter if we already have this position
            token_id = self._get_token_id(mkt, platform)
            if self._position_tracker.has_position(token_id):
                continue

            # Check shared registry (cross-strategy overlap prevention)
            if self._registry and self._registry.is_claimed(token_id):
                continue

            end_date = mkt.get("end_date_iso", mkt.get("close_time", ""))
            market_id = mkt.get("condition_id", mkt.get("ticker", token_id))

            c = CheapBracket(
                market_id=market_id,
                token_id=token_id,
                platform=platform,
                city=city,
                station=station or "",
                question=mkt.get("question", mkt.get("title", "")),
                bracket_low_f=bracket_low_f,
                bracket_high_f=bracket_high_f,
                entry_price=market_price,
                forecast_temp_f=forecast_temp_f,
                forecast_sigma_f=forecast_sigma_f,
                fair_value=fair_value,
                potential_return_x=round(potential_return_x, 1),
                bracket_offset_f=round(offset_f, 1),
                end_date=end_date,
                event_key=event_key,
            )
            candidates.append(c)

        # Sort by potential return (best value first)
        candidates.sort(key=lambda c: c.potential_return_x, reverse=True)

        if candidates:
            logger.info(
                "weather_cheap_brackets_found",
                event_key=event_key,
                forecast_f=round(forecast_temp_f, 1),
                candidates=len(candidates),
                price_range=f"${min(c.entry_price for c in candidates):.3f}-${max(c.entry_price for c in candidates):.3f}",
                return_range=f"{min(c.potential_return_x for c in candidates):.0f}x-{max(c.potential_return_x for c in candidates):.0f}x",
            )

        return candidates

    # ── Forecast Fetching ─────────────────────────────────────────────────────

    async def _get_forecast(
        self, city: str, station: str | None
    ) -> tuple[float | None, float]:
        """Get the best available temperature forecast for a city.

        Priority: NOAA station data → METAR TAF → cached NOAA
        Returns (forecast_temp_f, sigma_f) or (None, default_sigma).
        """
        # Try NOAA station data first
        if station and station in self._station_data:
            data = self._station_data[station]
            forecast = data.get("forecast")
            if forecast:
                temp_f = forecast.get("forecast_high_f")
                if temp_f is not None:
                    return float(temp_f), NOAA_SIGMA_F

            # Fall back to current temp from NOAA observation
            current = data.get("current")
            if current and current.get("temp_f"):
                return float(current["temp_f"]), NOAA_SIGMA_F

        # Try hourly NOAA data for peak temperature
        if station and station in self._station_data:
            hourly = self._station_data[station].get("hourly", [])
            if hourly:
                max_temp = max((h.get("temp_f", 0) for h in hourly), default=None)
                if max_temp:
                    return float(max_temp), NOAA_SIGMA_F

        # Try METAR for international cities
        metar_stations = CITY_METAR_STATIONS.get(city.lower(), [])
        if metar_stations:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as http:
                    resp = await http.get(
                        "https://aviationweather.gov/api/data/taf",
                        params={"ids": metar_stations[0], "format": "json"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and isinstance(data, list):
                            raw_taf = data[0].get("rawTAF", "")
                            # Parse TX (max temp) from TAF
                            tx_match = re.search(r"TX(M?\d+)/(\d{4})Z", raw_taf)
                            if tx_match:
                                temp_c_str = tx_match.group(1)
                                temp_c = -int(temp_c_str[1:]) if temp_c_str.startswith("M") else int(temp_c_str)
                                temp_f = temp_c * 9 / 5 + 32
                                return temp_f, METAR_SIGMA_F
            except Exception as exc:
                logger.debug("metar_taf_error", city=city, error=str(exc)[:60])

        return None, NOAA_SIGMA_F

    # ── Market Data Parsing ───────────────────────────────────────────────────

    def _parse_bracket_from_market(
        self, mkt: dict[str, Any], platform: str
    ) -> tuple[float, float] | None:
        """Extract (low_f, high_f) temperature bracket from a market.

        Handles Fahrenheit brackets, Celsius brackets (converted), and
        Kalshi structured strike fields.
        """
        if platform == "kalshi":
            return self._parse_kalshi_bracket(mkt)
        return self._parse_polymarket_bracket(mkt)

    def _parse_polymarket_bracket(self, mkt: dict[str, Any]) -> tuple[float, float] | None:
        """Parse bracket from Polymarket market question."""
        question = mkt.get("question", "")

        # Fahrenheit bracket: "80-85°F"
        match = TEMP_BRACKET_PATTERN.search(question)
        if match:
            low = float(match.group(1))
            high = float(match.group(2))
            if 1 < high - low <= 20:
                return (low, high)

        # Celsius bracket: "15-20°C" → convert
        match_c = TEMP_BRACKET_C_PATTERN.search(question)
        if match_c:
            low_c = float(match_c.group(1))
            high_c = float(match_c.group(2))
            if 1 < high_c - low_c <= 15:
                low_f = low_c * 9 / 5 + 32
                high_f = high_c * 9 / 5 + 32
                return (low_f, high_f)

        # Exact Celsius: "be 15°C" → treat as ±2°C bracket
        match_exact_c = TEMP_EXACT_C_PATTERN.search(question)
        if match_exact_c:
            temp_c = float(match_exact_c.group(1))
            temp_f = temp_c * 9 / 5 + 32
            return (temp_f - 3.6, temp_f + 3.6)  # ±2°C = ±3.6°F

        return None

    def _parse_kalshi_bracket(self, mkt: dict[str, Any]) -> tuple[float, float] | None:
        """Parse bracket from Kalshi structured fields."""
        strike_type = mkt.get("strike_type", "")
        floor_strike = mkt.get("floor_strike")
        cap_strike = mkt.get("cap_strike")

        if strike_type == "between" and floor_strike is not None and cap_strike is not None:
            return (float(floor_strike), float(cap_strike))

        # Fall back to title parsing
        title = mkt.get("title", "")
        match = TEMP_BRACKET_PATTERN.search(title)
        if match:
            low = float(match.group(1))
            high = float(match.group(2))
            if 1 < high - low <= 20:
                return (low, high)

        return None

    def _get_market_price(self, mkt: dict[str, Any], platform: str) -> float:
        """Extract YES ask price from a market."""
        if platform == "kalshi":
            return float(mkt.get("yes_ask_dollars", 0) or 0)

        # Polymarket
        tokens = mkt.get("tokens", [])
        if tokens:
            return float(tokens[0].get("price", 0) or 0)

        # Fallback
        return float(mkt.get("outcomePrices", [0])[0]) if mkt.get("outcomePrices") else 0.0

    def _get_token_id(self, mkt: dict[str, Any], platform: str) -> str:
        """Get the primary identifier for a market."""
        if platform == "kalshi":
            return mkt.get("ticker", mkt.get("market_id", ""))

        tokens = mkt.get("tokens", [])
        if tokens:
            return tokens[0].get("token_id", "")
        return mkt.get("condition_id", "")

    # ── Trade Execution ───────────────────────────────────────────────────────

    async def _execute_bracket(self, bracket: CheapBracket) -> bool:
        """Execute a cheap bracket entry.

        Returns True if order was placed/logged.
        """
        # Check per-event exposure limit
        current_exposure = self._position_tracker.get_event_exposure(bracket.event_key)
        if current_exposure >= self._max_per_event:
            logger.debug(
                "weather_event_exposure_limit",
                event_key=bracket.event_key,
                current=round(current_exposure, 2),
                max=self._max_per_event,
            )
            return False

        # Check time to expiry
        if bracket.end_date and not self._check_time_to_expiry(bracket.end_date):
            return False

        # Calculate position size
        # Use max remaining room under per-event cap
        remaining = self._max_per_event - current_exposure
        size = min(self._bracket_default_size, remaining, self._bracket_max_size)
        if size < 1.0:
            return False

        size = round(size, 2)

        # Try to claim in shared registry (blocks overlap with copytrade)
        if self._registry:
            claimed = await self._registry.claim(
                token_id=bracket.token_id,
                strategy=self.name,
                entry_price=bracket.entry_price,
                size=size,
                market_question=bracket.question,
            )
            if not claimed:
                logger.debug(
                    "weather_registry_blocked",
                    token_id=bracket.token_id[:20],
                    event_key=bracket.event_key,
                )
                return False

        logger.info(
            "weather_bracket_entry",
            event_key=bracket.event_key,
            city=bracket.city,
            bracket=f"{bracket.bracket_low_f:.0f}-{bracket.bracket_high_f:.0f}°F",
            forecast_f=round(bracket.forecast_temp_f, 1),
            offset_f=bracket.bracket_offset_f,
            entry_price=bracket.entry_price,
            potential_return=f"{bracket.potential_return_x:.0f}x",
            fair_value=round(bracket.fair_value, 4),
            size=size,
            platform=bracket.platform,
            event_exposure_after=round(current_exposure + size, 2),
        )

        # Execute on the appropriate platform
        success = False
        if bracket.platform == "polymarket":
            success = await self._execute_polymarket_bracket(bracket, size)
        elif bracket.platform == "kalshi":
            success = await self._execute_kalshi_bracket(bracket, size)

        if success:
            self._stats["total_brackets_entered"] += 1

        return success

    async def _execute_polymarket_bracket(self, bracket: CheapBracket, size: float) -> bool:
        """Place a Polymarket BUY order for a cheap bracket."""
        # Add 0.01 to price to ensure fill (aggressive limit)
        price = min(round(bracket.entry_price + 0.01, 3), 0.99)

        order = await self._place_limit_order(
            token_id=bracket.token_id,
            market=bracket.question,
            price=price,
            size=size,
            side=SIDE_BUY,
        )

        if order:
            pos = WeatherPosition(
                market_ticker=bracket.token_id,
                market_title=bracket.question,
                platform="polymarket",
                side="BUY",
                entry_price=bracket.entry_price,
                size=size,
                entry_time=time.time(),
                edge_at_entry=bracket.fair_value - bracket.entry_price,
                station=bracket.station,
                fair_value=bracket.fair_value,
                end_date=bracket.end_date,
                bracket_low_f=bracket.bracket_low_f,
                bracket_high_f=bracket.bracket_high_f,
                forecast_temp_f=bracket.forecast_temp_f,
                city=bracket.city,
                event_key=bracket.event_key,
            )
            self._position_tracker.enter(pos)
            self._log_bracket_paper_trade(pos, bracket)
            return True

        # If order failed, release registry claim
        if self._registry:
            await self._registry.release(bracket.token_id)
        return False

    async def _execute_kalshi_bracket(self, bracket: CheapBracket, size: float) -> bool:
        """Place a Kalshi YES order for a cheap bracket."""
        if not self._kalshi_client:
            return False

        from src.platforms.base import Order

        price = min(round(bracket.entry_price + 0.01, 3), 0.99)
        order = Order(
            platform="kalshi",
            market_id=bracket.market_id,
            side="yes",
            size=size,
            price=price,
            order_type="limit",
        )

        try:
            result = await self._kalshi_client.place_order(order)
            if result:
                pos = WeatherPosition(
                    market_ticker=bracket.token_id,
                    market_title=bracket.question,
                    platform="kalshi",
                    side="yes",
                    entry_price=bracket.entry_price,
                    size=size,
                    entry_time=time.time(),
                    edge_at_entry=bracket.fair_value - bracket.entry_price,
                    station=bracket.station,
                    fair_value=bracket.fair_value,
                    end_date=bracket.end_date,
                    bracket_low_f=bracket.bracket_low_f,
                    bracket_high_f=bracket.bracket_high_f,
                    forecast_temp_f=bracket.forecast_temp_f,
                    city=bracket.city,
                    event_key=bracket.event_key,
                )
                self._position_tracker.enter(pos)
                self._log_bracket_paper_trade(pos, bracket)
                return True
        except Exception as exc:
            logger.error("kalshi_bracket_order_error", market=bracket.market_id, error=str(exc))

        if self._registry:
            await self._registry.release(bracket.token_id)
        return False

    # ── Position Management ───────────────────────────────────────────────────

    async def _manage_positions(self) -> None:
        """Monitor open positions for exit conditions.

        For cheap brackets:
        - PRIMARY: Time-based — weather markets resolve in 24-48h, let them ride
        - SECONDARY: Stop-loss at -50% (e.g., entry 0.06 → exit if price hits 0.03)
        - TERTIARY: Take-profit if price ≥ 50¢ (the bracket likely resolved or is resolving)
        """
        for pos in list(self._position_tracker.all_positions()):
            ticker = pos.market_ticker

            current_price = await self._get_current_price(ticker, pos.platform)

            if current_price is None or current_price <= 0:
                current_price = pos.entry_price  # Don't exit on missing data

            entry_price = pos.entry_price

            # Exit 1: Take profit — price hit 50¢+ (someone paying 50¢+ for bracket
            # we bought at 5¢ means it's almost certainly going to resolve YES)
            if current_price >= 0.50 and pos.side in ("BUY", "yes"):
                pnl_x = current_price / entry_price if entry_price > 0 else 0
                logger.info(
                    "weather_bracket_take_profit",
                    market=pos.market_title[:60],
                    entry=entry_price,
                    current=current_price,
                    return_x=round(pnl_x, 1),
                    platform=pos.platform,
                )
                await self._exit_position(ticker, "take_profit")
                continue

            # Exit 2: Stop-loss at -50% (bracket moved further out of money)
            if current_price > 0 and pos.side in ("BUY", "yes"):
                loss_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0
                if loss_pct >= self._stop_loss_pct:
                    logger.info(
                        "weather_bracket_stop_loss",
                        market=pos.market_title[:60],
                        entry=entry_price,
                        current=current_price,
                        loss_pct=round(loss_pct * 100, 1),
                        platform=pos.platform,
                    )
                    await self._exit_position(ticker, "stop_loss")
                    continue

            # Exit 3: Time-based — exit just before market resolution to lock in any gains
            if pos.end_date:
                try:
                    expiry = datetime.fromisoformat(pos.end_date.replace("Z", "+00:00"))
                    minutes_to_expiry = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
                    if 0 < minutes_to_expiry < self._exit_before_resolution_min:
                        logger.info(
                            "weather_bracket_time_exit",
                            market=pos.market_title[:60],
                            minutes_to_expiry=round(minutes_to_expiry),
                            current_price=current_price,
                            platform=pos.platform,
                        )
                        await self._exit_position(ticker, "pre_resolution")
                        continue
                except (ValueError, TypeError):
                    pass

    async def _exit_position(self, token_id: str, reason: str) -> None:
        """Exit a weather bracket position."""
        pos = self._position_tracker.positions.get(token_id)
        if not pos:
            return

        current_price = await self._get_current_price(token_id, pos.platform) or pos.entry_price
        exit_price = current_price

        try:
            if pos.platform == "polymarket":
                if self._settings.dry_run:
                    self._record_paper_trade(
                        token_id=token_id,
                        market=pos.market_title,
                        price=exit_price,
                        size=pos.size,
                        side=SIDE_SELL,
                    )
                else:
                    await self._client.place_order(
                        token_id=token_id,
                        price=exit_price,
                        size=pos.size,
                        side=SIDE_SELL,
                        order_type="FOK",
                    )

            elif pos.platform == "kalshi" and self._kalshi_client:
                from src.platforms.base import Order
                exit_order = Order(
                    platform="kalshi",
                    market_id=token_id,
                    side="no",
                    size=pos.size,
                    price=exit_price,
                    order_type="limit",
                )
                await self._kalshi_client.place_order(exit_order)

        except Exception as exc:
            logger.error("weather_exit_error", token_id=token_id, error=str(exc))

        # P/L calculation
        if pos.side in ("BUY", "yes"):
            pnl = (exit_price - pos.entry_price) * pos.size
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100 if pos.entry_price > 0 else 0
        else:
            pnl = (pos.entry_price - exit_price) * pos.size
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100 if pos.entry_price > 0 else 0

        self._stats["total_pnl"] += pnl
        if pnl >= 0:
            self._stats["total_brackets_won"] += 1
        else:
            self._stats["total_brackets_lost"] += 1

        logger.info(
            "weather_bracket_exited",
            market=pos.market_title[:60],
            reason=reason,
            platform=pos.platform,
            bracket=f"{pos.bracket_low_f:.0f}-{pos.bracket_high_f:.0f}°F",
            entry_price=pos.entry_price,
            exit_price=round(exit_price, 4),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 1),
            return_x=round(exit_price / pos.entry_price, 1) if pos.entry_price > 0 else 0,
            hold_seconds=round(time.time() - pos.entry_time),
        )

        # Notify strategy manager for P/L tracking
        if hasattr(self, "_strategy_pnl") and self._strategy_pnl:
            from strategies.strategy_manager import ClosedTrade
            ct = ClosedTrade(
                strategy=self.name,
                token_id=token_id,
                market_question=pos.market_title,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                size=pos.size,
                entry_time=pos.entry_time,
                exit_time=time.time(),
                reason=reason,
            )
            self._strategy_pnl.record_close(ct)

        # Release from shared registry
        if self._registry:
            await self._registry.release(token_id, exit_price=exit_price)

        self._position_tracker.exit(token_id)

    async def _get_current_price(self, token_id: str, platform: str) -> float | None:
        """Get current market price for exit calculations."""
        try:
            if platform == "polymarket":
                return await self._client.get_midpoint(token_id)
            elif platform == "kalshi" and self._kalshi_client:
                markets = await self._kalshi_client.get_markets(ticker=token_id, limit=1)
                if markets:
                    price = float(markets[0].get("yes_bid_dollars", 0) or 0)
                    if price > 0:
                        return price
                # Fallback via event ticker
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
            logger.debug("price_fetch_error", token_id=token_id[:20], error=str(exc)[:60])
        return None

    # ── Station Matching ──────────────────────────────────────────────────────

    def _match_station_for_city(self, city: str) -> str | None:
        """Match a city name to a NOAA station ID."""
        city_lower = city.lower()

        for station, patterns in CITY_PATTERNS.items():
            for pat in patterns:
                if pat in city_lower or city_lower in pat:
                    if station in self._station_data:
                        return station

        for station, data in self._station_data.items():
            city_in_data = data.get("city", "").lower()
            if city_in_data and city_in_data in city_lower:
                return station

        return None

    # ── Logging Helpers ───────────────────────────────────────────────────────

    def _log_bracket_paper_trade(self, pos: WeatherPosition, bracket: CheapBracket) -> None:
        """Log a bracket entry to the paper ledger."""
        if not self._paper_ledger:
            return
        from src.paper_ledger import PaperTrade

        paper_trade = PaperTrade(
            timestamp=pos.entry_time,
            strategy="weather_trader",
            market_id=pos.market_ticker,
            market_question=pos.market_title,
            side="BUY",
            size=pos.size,
            price=pos.entry_price,
            signals={
                "platform": pos.platform,
                "city": bracket.city,
                "station": bracket.station,
                "bracket_low_f": bracket.bracket_low_f,
                "bracket_high_f": bracket.bracket_high_f,
                "forecast_temp_f": round(bracket.forecast_temp_f, 1),
                "bracket_offset_f": bracket.bracket_offset_f,
                "fair_value": round(bracket.fair_value, 4),
                "potential_return_x": bracket.potential_return_x,
                "edge_vs_price": round(bracket.fair_value - bracket.entry_price, 4),
                "event_key": bracket.event_key,
            },
        )
        self._paper_ledger.record(paper_trade)

    def _bracket_to_edge_dict(self, c: CheapBracket) -> dict[str, Any]:
        """Convert a CheapBracket to the legacy edge dict format for API compatibility."""
        return {
            "platform": c.platform,
            "market_id": c.market_id,
            "token_id": c.token_id,
            "question": c.question,
            "market_price": c.entry_price,
            "fair_value": round(c.fair_value, 4),
            "edge": round(c.fair_value - c.entry_price, 4),
            "abs_edge": round(abs(c.fair_value - c.entry_price), 4),
            "side": "BUY",
            "end_date": c.end_date,
            "bracket_low_f": c.bracket_low_f,
            "bracket_high_f": c.bracket_high_f,
            "forecast_temp_f": round(c.forecast_temp_f, 1),
            "bracket_offset_f": c.bracket_offset_f,
            "potential_return_x": c.potential_return_x,
            "event_key": c.event_key,
            "city": c.city,
        }

    # ── Forecast Bias Learning ────────────────────────────────────────────────

    def record_resolution(
        self, city: str, forecast_temp_f: float, actual_temp_f: float
    ) -> None:
        """Record a market resolution to track forecast bias per city.

        Call this when you observe a weather market resolve and know the actual
        temperature. Over time this calibrates the bias correction applied to
        future forecasts.
        """
        if city not in self._city_bias:
            self._city_bias[city] = ForecastBias(city=city)

        self._city_bias[city].record(forecast_temp_f, actual_temp_f)
        bias = self._city_bias[city]

        logger.info(
            "weather_bias_updated",
            city=city,
            forecast_f=round(forecast_temp_f, 1),
            actual_f=round(actual_temp_f, 1),
            error_f=round(actual_temp_f - forecast_temp_f, 1),
            mean_bias_f=round(bias.mean_bias_f, 2),
            rmse_f=round(bias.rmse_f, 2),
            n=bias.n,
        )

    def get_city_bias_summary(self) -> dict[str, dict[str, float]]:
        """Return forecast bias stats per city for monitoring."""
        return {
            city: {
                "mean_bias_f": round(b.mean_bias_f, 2),
                "rmse_f": round(b.rmse_f, 2),
                "observations": b.n,
            }
            for city, b in self._city_bias.items()
        }

    # ── Status / Info ─────────────────────────────────────────────────────────

    def get_positions_with_pnl(self) -> list[dict[str, Any]]:
        """Return all open positions with unrealized P&L for the API."""
        result: list[dict[str, Any]] = []
        for pos in self._position_tracker.all_positions():
            current_price = pos.fair_value  # Use fair value as proxy for unrealized P/L
            if pos.side in ("BUY", "yes"):
                unrealized_pnl = (current_price - pos.entry_price) * pos.size
                return_x = current_price / pos.entry_price if pos.entry_price > 0 else 0
            else:
                unrealized_pnl = (pos.entry_price - current_price) * pos.size
                return_x = 0

            result.append({
                "market_ticker": pos.market_ticker,
                "market_title": pos.market_title,
                "platform": pos.platform,
                "city": pos.city,
                "bracket": f"{pos.bracket_low_f:.0f}-{pos.bracket_high_f:.0f}°F",
                "forecast_temp_f": round(pos.forecast_temp_f, 1),
                "side": pos.side,
                "entry_price": pos.entry_price,
                "fair_value": round(pos.fair_value, 4),
                "size": pos.size,
                "entry_time": pos.entry_time,
                "edge_at_entry": round(pos.edge_at_entry, 4),
                "station": pos.station,
                "unrealized_pnl": round(unrealized_pnl, 4),
                "return_x": round(return_x, 1),
                "hold_seconds": round(time.time() - pos.entry_time),
                "event_key": pos.event_key,
            })
        return result

    @property
    def stats(self) -> dict[str, Any]:
        """Return strategy-level stats."""
        total_entered = self._stats["total_brackets_entered"]
        total_won = self._stats["total_brackets_won"]
        total_closed = total_won + self._stats["total_brackets_lost"]
        return {
            "total_brackets_entered": total_entered,
            "total_brackets_won": total_won,
            "total_brackets_lost": self._stats["total_brackets_lost"],
            "win_rate_pct": round(total_won / total_closed * 100, 1) if total_closed > 0 else 0,
            "total_pnl": round(self._stats["total_pnl"], 2),
            "open_positions": len(self._position_tracker.positions),
            "total_open_exposure": round(self._position_tracker.total_exposure(), 2),
            "city_bias": self.get_city_bias_summary(),
        }

    def _check_time_to_expiry(self, end_date: str) -> bool:
        """Return True if there's enough time before expiry to enter."""
        try:
            expiry = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            minutes = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
            return minutes > self._exit_before_resolution_min * 2
        except (ValueError, TypeError):
            return True


# ── Probability Calculation Functions ─────────────────────────────────────────


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
