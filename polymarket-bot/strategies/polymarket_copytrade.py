"""Polymarket Copy-Trading Strategy — Enhanced with all Phase 1-3 upgrades.

Discovers profitable wallets on Polymarket's public blockchain, scores them
by composite metrics (win rate, P/L ratio, recency, consistency), monitors
their trades, and copies BUY entries with dynamic Kelly sizing.

Flow
────
1. **Wallet Discovery** — every 6 hours, query the Gamma API for active
   markets, collect wallets with significant activity, and score using
   enhanced wallet scoring (zombie detection, P/L ratio, red flags).

2. **Trade Monitoring** — every 30 seconds, poll the CLOB API for new trades
   from the top-25 scored wallets. Track seen trade IDs to avoid duplicates.

3. **Pre-Trade Validation** — optionally screen trades through LLM for EV
   assessment, check correlation limits, calculate Kelly sizing.

4. **Copy Execution** — when a top wallet makes a BUY, place a matching
   order sized by Kelly Criterion. Guards: condition_id dedup, daily loss
   circuit breaker, per-market dedup, category exposure limits.

5. **Position Management** — Smart exit engine: trailing stop activation at +30%
   (15% below peak), stop-loss (50%), time-based exit (48h stale). Let winners ride.

6. **Redemption** — every 5 minutes, check for resolved winning positions
   and redeem them via the ConditionalTokens contract to recover USDC.e.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from src.client import PolymarketClient, ORDER_TYPE_FOK, ORDER_TYPE_GTC
from src.config import Settings
from src.metar_client import METARClient
from src.noaa_client import NOAAClient, KALSHI_STATIONS
from src.pnl_tracker import PnLTracker, Trade
from src.signer import SIDE_BUY, SIDE_SELL

from strategies.exit_engine import ExitEngine, ExitSignal, CATEGORY_EXIT_PARAMS
from strategies.kelly_sizing import KellySizer, get_bankroll_from_env, fetch_onchain_bankroll
from strategies.wallet_scoring import WalletScorer
from strategies.correlation_tracker import CorrelationTracker, categorize_market
from strategies.llm_validator import LLMValidator, detect_anti_patterns

logger = structlog.get_logger(__name__)

# ── Temperature cluster dedup (P0) ───────────────────────────────────────────
# Matches "Will the highest temperature in Shanghai be 17°C on April 3?"
# or "Will Shanghai high temperature be 15°C on March 28?"
_TEMP_CELSIUS_PATTERN = re.compile(
    r"(?:high(?:est)?|low(?:est)?)\s+temp(?:erature)?\s+(?:in\s+)?"
    r"([\w\s]+?)\s+be\s+(\d+)\s*°?\s*C\s+(?:on|for)\s+([\w\s,]+)",
    re.IGNORECASE,
)

# Broader fallback: "Shanghai ... 17°C ... April 3"
_TEMP_CELSIUS_FALLBACK = re.compile(
    r"([\w\s]+?)\s+.*?(\d+)\s*°\s*C\s+.*?(?:on|for)\s+([\w\s,]+\d+)",
    re.IGNORECASE,
)

# Date normalization for cluster keys
_DATE_PATTERN = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})",
    re.IGNORECASE,
)

_MONTH_TO_INT = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# ── Dust sweeper constants ────────────────────────────────────────────────────
# Positions with estimated value below DUST_VALUE_THRESHOLD are swept immediately.
# Positions under $2 held longer than STALE_DUST_HOURS are swept as stale dust.
DUST_VALUE_THRESHOLD: float = 0.50   # $0.50 — matches min trade size
STALE_DUST_HOURS: float = 24.0       # 24 h hold + < $2 value triggers stale dust sweep


def _extract_temp_cluster_key(market_question: str) -> tuple[str, str, int] | None:
    """Extract (city_normalized, date_str, temp_celsius) from a temperature market title.

    Returns None if this is not a recognizable temperature bracket market.
    Example: "Will Shanghai high temperature be 17°C on April 3?" → ("shanghai", "april-3", 17)
    """
    for pattern in (_TEMP_CELSIUS_PATTERN, _TEMP_CELSIUS_FALLBACK):
        m = pattern.search(market_question)
        if m:
            city = m.group(1).strip().lower()
            temp = int(m.group(2))
            date_raw = m.group(3).strip().lower()
            # Normalize date to "month-day" format
            dm = _DATE_PATTERN.search(date_raw)
            if dm:
                date_str = f"{dm.group(1)}-{dm.group(2)}"
            else:
                # Fallback: use raw string cleaned of whitespace
                date_str = re.sub(r"\s+", "-", date_raw.strip(" ,?."))
            return (city, date_str, temp)
    return None


# ── Crypto binary short-window filter (P1) ───────────────────────────────────
_SHORT_WINDOW_TITLE_PATTERNS = [
    re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE),
    re.compile(r"next\s+\d+\s+minutes?", re.IGNORECASE),
    re.compile(r"\bup\s+or\s+down\b", re.IGNORECASE),
]

_TIME_WINDOW_PATTERN = re.compile(
    r"(\d{1,2}):(\d{2})\s*([AP]M)\s*[-–]\s*(\d{1,2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)


def _parse_resolution_window_minutes(market_question: str) -> int | None:
    """Parse time window from market title and return duration in minutes.

    E.g. "9:00AM-9:15AM" → 15, "2:00PM-2:05PM" → 5.
    Returns None if no parseable time window found.
    """
    m = _TIME_WINDOW_PATTERN.search(market_question)
    if not m:
        return None

    def _to_minutes(h: int, mi: int, ampm: str) -> int:
        ampm = ampm.upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return h * 60 + mi

    start = _to_minutes(int(m.group(1)), int(m.group(2)), m.group(3))
    end = _to_minutes(int(m.group(4)), int(m.group(5)), m.group(6))
    if end <= start:
        end += 24 * 60  # crosses midnight
    return end - start


# ── Orphan position persistence ──────────────────────────────────────────────
ORPHAN_FILE = "/data/orphan_positions.json"


def _save_orphans(orphans: list[dict]) -> None:
    """Persist orphan positions so the redeemer can track them across restarts."""
    try:
        with open(ORPHAN_FILE, "w") as f:
            json.dump(orphans, f, indent=2)
    except OSError as exc:
        logger.warning("orphan_save_error", error=str(exc)[:100])


def _load_orphans() -> list[dict]:
    """Load previously detected orphan positions."""
    try:
        with open(ORPHAN_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _notify(title: str, body: str) -> None:
    """Best-effort push notification via Redis → notification-hub → iMessage."""
    try:
        import json as _json
        import redis
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        r = redis.from_url(url, decode_responses=True, socket_timeout=2)
        r.publish("notifications:trading", _json.dumps({"title": title, "body": body}))
    except Exception:
        pass  # never block trading on notification failure


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ScoredWallet:
    """A wallet scored by historical win rate."""

    address: str
    win_rate: float
    total_resolved: int
    wins: int
    losses: int
    total_volume: float = 0.0
    last_active: float = 0.0  # epoch
    score: float = 0.0  # composite score
    event_trades: int = 0  # number of event market trades scored on
    # Enhanced scoring fields
    adjusted_win_rate: float = 0.0
    pl_ratio: float = 0.0
    open_losing: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoredWallet:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CopiedPosition:
    """A position opened by copying a top wallet."""

    position_id: str
    source_wallet: str
    token_id: str
    market_question: str
    condition_id: str
    side: str  # "BUY"
    entry_price: float
    size_usd: float
    size_shares: float
    copied_at: float  # epoch
    source_trade_id: str
    order_id: str = ""
    category: str = ""  # market category for correlation tracking
    wallet_win_rate: float = 0.0  # source wallet's win rate at time of copy
    end_date: str = ""  # market end date (ISO string from Gamma API)
    event_slug: str = ""  # event-level slug for both-sides guard
    outcome: str = ""  # outcome label (e.g. Yes/Up) for complementary-outcome guard
    thesis: str = ""  # research thesis -- why this trade was copied
    neg_risk: bool = False  # whether market uses negative risk (CTF Exchange v2)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── On-chain CTF balance query ────────────────────────────────────────
CTF_CONTRACT_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
_ERC1155_BALANCE_ABI = [{"constant": True, "inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
_w3_instance = None
_ctf_contract_instance = None

def _get_onchain_balance(token_id: str, wallet: str) -> float | None:
    """Query ERC1155 balance for a CTF token. Returns shares or None on error."""
    global _w3_instance, _ctf_contract_instance
    if not wallet or not token_id:
        return None
    try:
        from web3 import Web3
        if _w3_instance is None:
            _w3_instance = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            _ctf_contract_instance = _w3_instance.eth.contract(
                address=Web3.to_checksum_address(CTF_CONTRACT_ADDRESS),
                abi=_ERC1155_BALANCE_ABI,
            )
        balance = _ctf_contract_instance.functions.balanceOf(
            Web3.to_checksum_address(wallet),
            int(token_id),
        ).call()
        return balance / 1e6
    except Exception:
        return None


# ── Strategy ─────────────────────────────────────────────────────────────────

class PolymarketCopyTrader:
    """Copy-trades top-performing Polymarket wallets with smart exits and Kelly sizing."""

    CATEGORY_TIERS: dict[str, str] = {
        "weather": "whitelist",
        "crypto": "whitelist",
        "crypto_updown": "whitelist",
        "economics": "whitelist",
        "other": "graylist",
        "esports": "graylist",
        "us_sports": "graylist",
        "sports": "graylist",
        "tennis": "graylist",
        "politics": "graylist",
        "geopolitics": "graylist",
        "science": "graylist",
        "entertainment": "graylist",
        "soccer_intl": "graylist",
        "f1": "graylist",
        "motorsport": "graylist",
    }

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        pnl_tracker: PnLTracker,
        sandbox=None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._pnl_tracker = pnl_tracker
        self._sandbox = sandbox

        # Config from settings
        self._size_usd: float = getattr(settings, "copytrade_size_usd", 3.0)
        self._max_positions: int = getattr(settings, "copytrade_max_positions", 50)
        self._min_win_rate: float = getattr(settings, "copytrade_min_win_rate", 0.60)
        self._min_trades: int = getattr(settings, "copytrade_min_trades", 20)
        self._scan_interval_hours: float = getattr(settings, "copytrade_scan_interval_hours", 6.0)
        self._check_interval: float = getattr(settings, "copytrade_check_interval", 30.0)
        self._dry_run: bool = settings.dry_run
        self._observer_only: bool = getattr(settings, "observer_only", True)
        self._simulation_only: bool = getattr(settings, "simulation_only", False)
        if self._simulation_only and not self._observer_only:
            logger.info("simulation_only_started",
                        message="Polymarket paper trades active; Kraken/crypto disabled by simulation_only mode")

        # Daily risk controls — no fixed spend cap, but stop on drawdown
        self._daily_loss_limit: float = getattr(settings, "copytrade_daily_loss_limit", 40.0)
        self._daily_spend: float = 0.0
        self._daily_wins: float = 0.0
        self._daily_realized_losses: float = 0.0
        self._daily_trades: int = 0
        self._daily_spend_reset_time: float = 0.0
        self._halted: bool = False

        # ── Re-entry queue: buy back into winners after trailing stop exit ────
        # {token_id: {market_question, condition_id, exit_price, exit_time,
        #             category, peak_price, original_entry, token_id}}
        self._reentry_queue: dict[str, dict[str, Any]] = {}
        self._REENTRY_DIP_PCT = 0.10  # re-enter if price dips 10% below exit
        self._REENTRY_MAX_AGE = 3600 * 4  # 4 hours max to re-enter
        self._REENTRY_MIN_PRICE = 0.15  # don't re-enter below this
        self._REENTRY_MAX_PRICE = 0.90  # don't re-enter above this

        # ── Per-category circuit breaker ──────────────────────────────
        self._daily_category_losses: dict[str, float] = {}
        self._halted_categories: set[str] = set()
        self._CATEGORY_LOSS_LIMITS: dict[str, float] = {
            "crypto_updown": 15.0,   # highest conviction — allow more room
            "crypto": 15.0,
            "crypto_binary": 0.0,    # still blocked
            "esports": 5.0,          # cut from 10 to 5
            "tennis": 3.0,
            "sports": 0.0,           # ZERO — no sports losses allowed
            "us_sports": 0.0,        # ZERO
            "soccer_intl": 0.0,      # ZERO
            "weather": 0.0,          # ZERO from copytrade (weather_trader is separate)
            "politics": 3.0,         # cut from 10 to 3
            "geopolitics": 2.0,      # cut from 5 to 2
            "science": 2.0,
            "entertainment": 2.0,    # cut from 5 to 2
            "other": 5.0,            # cut from 15 to 5
            "economics": 5.0,
            "f1": 0.0,               # ZERO
            "motorsport": 0.0,       # ZERO
        }
        self._min_resolution_hours = float(os.environ.get("MIN_RESOLUTION_HOURS", "0.5"))

        # API base URLs
        self._gamma_url = settings.gamma_api_url.rstrip("/")
        self._clob_url = settings.clob_api_url.rstrip("/")

        # HTTP client for public API reads
        self._http: Optional[httpx.AsyncClient] = None

        # Official py-clob-client for authenticated CLOB requests
        self._clob_client = None
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            if settings.poly_private_key and settings.poly_builder_api_key:
                creds = ApiCreds(
                    api_key=settings.poly_builder_api_key,
                    api_secret=settings.poly_builder_api_secret,
                    api_passphrase=settings.poly_builder_api_passphrase,
                )
                pk = settings.poly_private_key
                if not pk.startswith("0x"):
                    pk = f"0x{pk}"
                self._clob_client = ClobClient(
                    self._clob_url,
                    key=pk,
                    chain_id=settings.chain_id,
                    creds=creds,
                    signature_type=0,
                )
                logger.info("copytrade_clob_client_initialized")
        except Exception as exc:
            logger.warning("copytrade_clob_client_init_error", error=str(exc))

        # Runtime state
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Wallet cache
        self._scored_wallets: list[ScoredWallet] = []
        self._last_scan_time: float = 0.0
        self._wallet_cache_path = Path(getattr(settings, "data_dir", "/data")) / "copytrade_wallets.json"

        # Priority wallets — always tracked, proven profitable from research
        # These are added to every scan regardless of leaderboard discovery
        self._PRIORITY_WALLETS: list[str] = [
            # @tradecraft — Tennis directional + hedging. $17K → $372K (2,139% ROI)
            "0xde9f7f4e77a1595623ceb58e469f776257ccd43c",
            # @coldmath — Weather specialist using aviation data. $89K+ portfolio
            "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11",
        ]

        # Trade dedup
        self._seen_trades_path = Path(getattr(settings, "data_dir", "/data")) / "copytrade_seen_trades.json"
        self._seen_trade_ids: set[str] = self._load_seen_trades()
        self._initial_seed_done: bool = len(self._seen_trade_ids) > 0
        self._consecutive_errors: int = 0
        self._last_trade_time: float = 0.0
        self._min_trade_gap: float = 30.0

        # ── Trade pacing — rolling hourly cap ─────────────────────────
        self._max_trades_per_hour: int = int(os.environ.get("MAX_TRADES_PER_HOUR", "15"))
        self._hourly_trade_times: list[float] = []  # epoch timestamps of recent trades

        # ── Attempt throttle — rolling per-minute cap ─────────────────
        self._max_attempts_per_minute: int = int(
            os.environ.get("COPYTRADE_MAX_ATTEMPTS_PER_MINUTE", "5")
        )
        self._attempt_times: list[float] = []  # epoch timestamps of recent copy attempts

        # ── Per-token/market dedup window ─────────────────────────────
        self._dedupe_window_seconds: float = float(
            os.environ.get("COPYTRADE_DEDUPE_WINDOW_SECONDS", "3600")
        )
        self._max_attempts_per_market_per_hour: int = int(
            os.environ.get("COPYTRADE_MAX_ATTEMPTS_PER_MARKET_PER_HOUR", "1")
        )
        self._token_last_attempt: dict[str, float] = {}  # token_id -> last attempt epoch

        # ── Global max entry price ─────────────────────────────────────
        self._copytrade_max_price: float = float(
            os.environ.get("COPYTRADE_MAX_PRICE", "0.90")
        )
        self._allow_high_price: bool = os.environ.get(
            "COPYTRADE_ALLOW_HIGH_PRICE", "false"
        ).lower() in {"1", "true", "yes"}

        # ── Per-wallet daily trade limit ──────────────────────────────
        self._max_trades_per_wallet_per_day: int = int(os.environ.get("MAX_TRADES_PER_WALLET_PER_DAY", "3"))
        self._wallet_daily_trades: dict[str, int] = {}  # wallet_address -> trade count today

        # ── Per-category absolute position cap ────────────────────────
        self._max_positions_per_category: int = int(os.environ.get("MAX_POSITIONS_PER_CATEGORY", "20"))

        # Open copied positions — persisted to disk
        self._positions_path = Path(getattr(settings, "data_dir", "/data")) / "copytrade_positions.json"
        self._positions: dict[str, CopiedPosition] = self._load_positions()

        # Track condition_ids we already have positions in (rebuild from loaded positions)
        self._active_condition_ids: set[str] = {
            p.condition_id for p in self._positions.values() if p.condition_id
        }

        # Track event slugs for both-sides guard — prevents buying multiple outcomes of same event
        self._active_event_slugs: set[str] = {
            p.event_slug for p in self._positions.values()
            if hasattr(p, 'event_slug') and p.event_slug
        }

        # Track source-wallet sells for exit signals
        self._source_sells: dict[str, set[str]] = {}

        # Redemption tracking
        self._last_redemption_check: float = 0.0
        self._redemption_interval: float = 300.0

        # ── Temperature cluster dedup (P0) ─────────────────────────
        # Maps (city, date) → {temp_celsius: condition_id} for entered brackets.
        # Max 2 adjacent brackets per city+date allowed.
        self._temp_cluster_registry: dict[tuple[str, str], dict[int, str]] = {}
        self._temp_cluster_max_brackets = int(os.environ.get("TEMP_CLUSTER_MAX_BRACKETS", "2"))

        # ── NEW: Phase 1 — Smart Exit Engine ─────────────────────────
        self._exit_engine = ExitEngine(
            take_profit_1_pct=float(os.environ.get("EXIT_TP1_PCT", "0.30")),
            take_profit_2_pct=float(os.environ.get("EXIT_TP2_PCT", "9.99")),
            stop_loss_pct=float(os.environ.get("EXIT_SL_PCT", "0.50")),
            trailing_stop_pct=float(os.environ.get("EXIT_TRAILING_PCT", "0.15")),
            time_exit_hours=float(os.environ.get("EXIT_TIME_HOURS", "48")),
            time_exit_min_move_pct=float(os.environ.get("EXIT_TIME_MIN_MOVE", "0.05")),
        )

        # ── NEW: Phase 1 — Kelly Criterion Position Sizing ───────────
        self._bankroll = float(os.environ.get("COPYTRADE_BANKROLL", "300"))
        self._last_bankroll_refresh: float = 0.0
        self._bankroll_refresh_interval: float = 300.0  # refresh every 5 min
        self._kelly_enabled = os.environ.get("KELLY_SIZING_ENABLED", "true").lower() in ("true", "1", "yes")
        self._kelly_sizer = KellySizer(
            kelly_fraction=float(os.environ.get("KELLY_FRACTION", "0.25")),
            min_size_usd=float(os.environ.get("KELLY_MIN_SIZE", "2.0")),
            max_bankroll_pct=float(os.environ.get("KELLY_MAX_PCT", "0.08")),
            default_size_usd=self._size_usd,
        )

        # ── NEW: Phase 1 — Enhanced Wallet Scoring ───────────────────
        self._wallet_scorer = WalletScorer(
            min_closed_positions=int(os.environ.get("WALLET_MIN_CLOSED", "20")),
        )

        # ── NEW: Expanded scan configuration ─────────────────────────
        self._scan_markets_limit = int(os.environ.get("COPYTRADE_SCAN_MARKETS", "500"))
        self._scan_categories = [
            c.strip() for c in
            os.environ.get("COPYTRADE_SCAN_CATEGORIES", "politics,sports,crypto,science").split(",")
            if c.strip()
        ]
        self._leaderboard_enabled = os.environ.get(
            "COPYTRADE_LEADERBOARD_ENABLED", "true"
        ).lower() in ("true", "1", "yes")

        # ── Category P/L tracking for adaptive position sizing ──────
        self._category_pnl: dict[str, float] = {}  # category -> realized P/L
        # Dynamic multipliers — copied from class defaults, updated by learning loop
        self._CATEGORY_MULTIPLIERS: dict[str, float] = dict(self._DEFAULT_CATEGORY_MULTIPLIERS)

        # ── NEW: Phase 2 — Correlation Exposure Tracker ──────────────
        self._correlation_tracker = CorrelationTracker(
            max_category_pct=float(os.environ.get("CORRELATION_MAX_PCT", "0.50")),
            bankroll=self._bankroll,
        )

        # ── NEW: Phase 3 — LLM Trade Validation ─────────────────────
        self._llm_validator = LLMValidator()

        # ── METAR aviation weather data for temperature edge ──────────
        self._metar_client = METARClient()
        self._noaa_client = NOAAClient(stations=list(KALSHI_STATIONS.keys()))

        # ── Whale signal scanner (set externally via set_whale_scanner) ──
        self._whale_scanner = None

        # ── X Intel Processor (set externally via set_x_intel) ──
        self._x_intel = None  # Set via set_x_intel() after startup

        # ── Wallet quality decay — re-score every 30 minutes ──────────
        self._last_wallet_refresh: float = 0.0
        self._wallet_refresh_interval: float = 1800.0  # 30 minutes

        # ── P/L reconciliation against on-chain — every 10 minutes ────
        self._last_pnl_reconciliation: float = 0.0
        self._pnl_reconciliation_interval: float = 600.0  # 10 minutes
        self._our_wallet = "0xa791e3090312981a1e18ed93238e480a03e7c0d2"
        self._last_cleanup_resolved: float = 0.0

        # ── Tick-in-progress guard — prevents bankroll refresh mid-tick ──
        self._tick_in_progress = False

        # ── Performance snapshot timer — 30-minute periodic log ──────
        self._last_perf_log: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        # Load cached wallets if available
        self._load_wallet_cache()

        # Start from zero — let real data accumulate (old seeds were stale)
        # P&L will populate from Redis persistence or live trade tracking

        # Sync bankroll from on-chain USDC.e balance at startup
        try:
            wallet_addr = self._client.wallet_address
            if wallet_addr:
                onchain_balance = await fetch_onchain_bankroll(wallet_addr)
                if onchain_balance > 0:
                    self._bankroll = onchain_balance
                    self._correlation_tracker.bankroll = onchain_balance
                    logger.info("bankroll_startup_sync", balance=round(onchain_balance, 2), source="onchain")
        except Exception as exc:
            logger.warning("bankroll_startup_sync_error", error=str(exc)[:100])

        # Re-register persisted positions with exit engine (category-specific params)
        for pos_id, pos in self._positions.items():
            self._exit_engine.register_position(pos_id, pos.entry_price, pos.copied_at, category=pos.category)
            self._correlation_tracker.add_position(pos_id, pos.market_question, pos.size_usd)
        if self._positions:
            logger.info("copytrade_positions_restored", count=len(self._positions))

        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "copytrade_started",
            size_usd=self._size_usd,
            max_positions=self._max_positions,
            min_win_rate=self._min_win_rate,
            min_trades=self._min_trades,
            scan_interval_hours=self._scan_interval_hours,
            check_interval=self._check_interval,
            daily_loss_limit=self._daily_loss_limit,
            max_trades_per_hour=self._max_trades_per_hour,
            dry_run=self._dry_run,
            observer_only=self._observer_only,
            simulation_only=self._simulation_only,
            kelly_enabled=self._kelly_enabled,
            bankroll=self._bankroll,
            llm_validation=self._llm_validator.enabled,
        )
        _notify(
            "[BOT] Started",
            f"{'DRY RUN' if self._dry_run else 'LIVE'} | ${self._bankroll:.2f} bankroll",
        )

    def set_whale_scanner(self, scanner) -> None:
        """Inject the whale scanner engine (called by main.py after both are initialized)."""
        self._whale_scanner = scanner

    def set_x_intel(self, x_intel) -> None:
        """Wire the X Intel Processor for signal-aware trading."""
        self._x_intel = x_intel
        logger.info("x_intel_wired_to_copytrade")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        await self._noaa_client.close()
        logger.info("copytrade_stopped", open_positions=len(self._positions))

    # ── Main loop ────────────────────────────────────────────────────────

    async def _maybe_refresh_bankroll(self) -> None:
        """Log on-chain USDC balance check. Called at the start of each tick only.

        The internal bankroll tracker is the source of truth — it is debited on
        trade and credited on exit/resolution. The on-chain USDC figure is
        informational only and must not change during a live tick.
        """
        if self._tick_in_progress:
            return  # Never refresh bankroll mid-tick
        now = time.time()
        if now - self._last_bankroll_refresh < self._bankroll_refresh_interval:
            return
        try:
            wallet_addr = self._client.wallet_address
            if wallet_addr:
                onchain_usdc = await fetch_onchain_bankroll(wallet_addr)
                if onchain_usdc > 0:
                    drift = round(self._bankroll - onchain_usdc, 2)
                    logger.info(
                        "bankroll_onchain_check",
                        internal=round(self._bankroll, 2),
                        onchain_usdc=round(onchain_usdc, 2),
                        drift=drift,
                        note="informational only — internal tracker is source of truth",
                    )
            self._last_bankroll_refresh = now
        except Exception as exc:
            logger.warning("bankroll_refresh_error", error=str(exc)[:100])
            self._last_bankroll_refresh = now

    async def _run_loop(self) -> None:
        """Main loop: scan wallets, monitor trades, manage positions, redeem."""
        tick_count = 0

        while self._running:
            try:
                # Refresh bankroll FIRST, before any trade decisions
                await self._maybe_refresh_bankroll()
                self._tick_in_progress = True
                now = time.time()

                # 0. Reset daily spend at midnight UTC
                self._maybe_reset_daily_spend(now)

                # 1. Wallet scan every N hours (or on first run)
                hours_since_scan = (now - self._last_scan_time) / 3600
                if hours_since_scan >= self._scan_interval_hours or self._last_scan_time == 0:
                    await self._scan_and_score_wallets()

                # 2. Monitor top wallets for new trades (every tick)
                await self._monitor_trades()

                # 2b. Check whale scanner signals (every other tick ≈ 60s)
                if tick_count % 2 == 1 and self._whale_scanner is not None:
                    await self._check_whale_signals()

                # 3. Manage positions with smart exit engine (every other tick ≈ 60s)
                if tick_count % 2 == 0:
                    await self._manage_positions()

                # 4. Redemption handled by standalone PolymarketRedeemer module

                # 5. Wallet quality decay — re-score every 30 minutes
                if now - self._last_wallet_refresh >= self._wallet_refresh_interval:
                    await self._refresh_wallet_scores()

                # 6. P/L reconciliation against on-chain — every 10 minutes
                if now - self._last_pnl_reconciliation >= self._pnl_reconciliation_interval:
                    await self._reconcile_pnl()

                # 7. Cleanup resolved positions — free up slots every 10 minutes
                if now - self._last_cleanup_resolved >= 600.0:
                    await self._cleanup_resolved_positions()
                    self._last_cleanup_resolved = now

                # Performance snapshot every 30 minutes
                if time.time() - self._last_perf_log > 1800:
                    self._last_perf_log = time.time()
                    try:
                        active_count = len(self._positions)
                        total_exposure = sum(p.size_usd for p in self._positions.values())
                        daily_pnl = self._daily_wins - self._daily_realized_losses
                        logger.info(
                            "copytrade_performance_30min",
                            active_positions=active_count,
                            total_exposure=round(total_exposure, 2),
                            daily_pnl=round(daily_pnl, 2),
                            daily_trades=self._daily_trades,
                            daily_spend=round(self._daily_spend, 2),
                            bankroll=round(self._bankroll, 2),
                            halted_categories=list(self._halted_categories),
                        )
                    except Exception:
                        pass

                tick_count += 1

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("copytrade_loop_error", error=str(exc))
            finally:
                self._tick_in_progress = False

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

    # ── Category-weighted position sizing ────────────────────────────────

    # Default category sizing multipliers — data-driven from 206 market analysis (2026-03-29)
    # Winners: crypto_updown +$57, esports +$28, tennis +$18, politics +$2
    # Losers: us_sports -$15 (40% WR), soccer_intl -$8 (40% WR), weather +$4 (barely)
    # Data-driven multipliers from 3,500-trade analysis (2026-04-13)
    # Categories sorted by ROI: only positive-ROI categories get >= 1.0x
    _DEFAULT_CATEGORY_MULTIPLIERS: dict[str, float] = {
        "crypto_updown": 1.5,   # BTC brackets are the #1 winner (+$178 single trade)
        "crypto": 1.5,          # alias — crypto price brackets have real edge
        "esports": 0.8,         # -$32 but has big individual winners (+$67 BLG/JDG)
        "tennis": 0.3,          # demote — not enough data to justify 1.3x
        "politics": 0.3,        # -$31 across 18 losses — no proven edge
        "us_sports": 0.0,       # DISABLED — 23% win rate, -$618, zero edge
        "soccer_intl": 0.0,     # DISABLED — part of sports -$618 disaster
        "sports": 0.0,          # DISABLED — generic sports is pure gambling
        "weather": 0.0,         # DISABLED from copytrade — weather_trader handles its own
        "other": 0.2,           # -$476 from "other" — nearly all losers
        "geopolitics": 0.2,     # -$31, 0% win rate on world politics
        "economics": 0.5,       # fed rates have some structure
        "science": 0.3,         # low sample
        "entertainment": 0.3,   # +$8, mixed results
        "f1": 0.0,              # DISABLED — part of sports
        "motorsport": 0.0,      # DISABLED — part of sports
    }

    def _category_size_multiplier(self, category: str) -> float:
        """Scale position size based on category's track record.

        Uses dynamic multipliers that adapt from live P/L data.
        Unknown categories get 0.5x (conservative until proven).
        """
        return self._CATEGORY_MULTIPLIERS.get(category, 0.5)

    def _recalculate_category_multipliers(self) -> None:
        """Recalculate category multipliers from live P/L data.

        Called after every exit to create a feedback loop:
        win → multiplier up → bigger positions → more profit on winners
        lose → multiplier down → smaller positions → less damage
        """
        for cat, pnl in self._category_pnl.items():
            old = self._CATEGORY_MULTIPLIERS.get(cat, 0.5)
            if pnl > 20:
                new = min(1.5, old * 1.1)
            elif pnl > 0:
                new = min(1.2, old * 1.05)
            elif pnl > -25:
                new = max(0.1, old * 0.95)
            else:
                new = max(0.05, old * 0.85)
            if new != old:
                self._CATEGORY_MULTIPLIERS[cat] = round(new, 3)
                logger.info(
                    "copytrade_multiplier_updated",
                    category=cat,
                    pnl=round(pnl, 2),
                    old_mult=round(old, 3),
                    new_mult=round(new, 3),
                )

    # ── Quiet hours (11pm-5am MDT) ──────────────────────────────────────

    @staticmethod
    def _is_quiet_hours() -> bool:
        """Quiet hours DISABLED — trade 24/7, no downtime.

        Previously blocked overnight MDT but we need maximum market coverage.
        Revenue requires constant participation across all time zones.
        """
        return False  # 24/7 trading — no quiet hours

    def _emit_trade_resolved_event(self, pos: CopiedPosition, pos_id: str, pnl_usd: float) -> None:
        """Notify Redis outcome listener (OpenClaw decision journal scoring)."""
        try:
            import redis

            url = os.environ.get("REDIS_URL", "")
            if not url:
                return
            r = redis.from_url(url, decode_responses=True)
            r.publish(
                "events:trading",
                json.dumps(
                    {
                        "type": "trade.redeemed",
                        "data": {
                            "position_id": pos_id,
                            "market": (pos.market_question or "")[:500],
                            "condition_id": pos.condition_id,
                            "pnl": pnl_usd,
                        },
                    }
                ),
            )
            r.close()
        except Exception as exc:
            logger.debug("redis_trade_event", error=str(exc)[:80])

        # Weather / temperature markets — station hit-rate for Kelly hints (close-the-loop §6)
        try:
            mq = pos.market_question or ""
            qlow = mq.lower()
            is_weatherish = (
                _extract_temp_cluster_key(mq) is not None
                or "temperature" in qlow
                or "°" in mq
                or "metar" in qlow
                or ("high" in qlow and "temp" in qlow)
            )
            if is_weatherish:
                from strategies.weather_accuracy import get_store

                cluster = _extract_temp_cluster_key(mq)
                if cluster:
                    city, _date_str, _temp = cluster
                    sid = f"city:{city}"
                else:
                    sid = "weather_other"
                get_store().record_outcome(sid, pnl_usd > 0.0)
        except Exception as exc:
            logger.debug("weather_accuracy_record", error=str(exc)[:80])

    # ── Trade pacing ──────────────────────────────────────────────────────

    def _prune_hourly_trades(self, now: float) -> None:
        """Remove trade timestamps older than 1 hour."""
        cutoff = now - 3600
        self._hourly_trade_times = [t for t in self._hourly_trade_times if t > cutoff]

    def _hourly_limit_reached(self) -> bool:
        """Check if the rolling hourly trade cap has been hit."""
        now = time.time()
        self._prune_hourly_trades(now)
        return len(self._hourly_trade_times) >= self._max_trades_per_hour

    def _record_hourly_trade(self) -> None:
        """Record a trade for hourly pacing."""
        self._hourly_trade_times.append(time.time())

    # ── Daily spend tracking ─────────────────────────────────────────────

    def _maybe_reset_daily_spend(self, now: float) -> None:
        """Reset daily counters at midnight UTC."""
        import datetime
        today_midnight = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        if today_midnight > self._daily_spend_reset_time:
            if self._daily_spend > 0 or self._daily_wins > 0:
                net = self._daily_wins - self._daily_spend
                logger.info("copytrade_daily_reset",
                            spent=round(self._daily_spend, 2),
                            wins=round(self._daily_wins, 2),
                            net_pnl=round(net, 2),
                            trades=self._daily_trades)
            self._log_daily_category_summary()
            self._daily_spend = 0.0
            self._daily_wins = 0.0
            self._daily_realized_losses = 0.0
            self._daily_trades = 0
            self._halted = False
            self._wallet_daily_trades = {}
            self._daily_category_losses = {}
            self._halted_categories = set()
            self._daily_spend_reset_time = today_midnight

    def _log_daily_category_summary(self) -> None:
        """Log daily P&L by category to Cortex for tracking."""
        try:
            import redis
            import json as _json
            url = os.environ.get("REDIS_URL", "")
            if not url:
                return
            r = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            summary = {
                "type": "trading_daily_summary",
                "category_pnl": dict(self._category_pnl),
                "category_multipliers": dict(self._CATEGORY_MULTIPLIERS),
                "halted_categories": list(self._halted_categories),
                "total_positions": len(self._positions),
            }
            r.publish("ops:trading_summary", _json.dumps(summary, default=str))
        except Exception:
            pass

    # ── 1. Wallet Discovery & Scoring ────────────────────────────────────

    async def _scan_and_score_wallets(self) -> None:
        """Discover active wallets and score by composite metrics."""
        logger.info("copytrade_wallet_scan", status="starting")
        min_pl_ratio = float(os.environ.get("WALLET_MIN_PL_RATIO", "1.5"))
        min_trades_high_wr = int(os.environ.get("WALLET_MIN_TRADES_HIGH_WR", "20"))
        min_trades_med_wr = int(os.environ.get("WALLET_MIN_TRADES_MED_WR", "30"))

        try:
            wallet_stats, markets_scored = await self._collect_wallet_activity()

            scored: list[ScoredWallet] = []
            for address, stats in wallet_stats.items():
                total_resolved = stats.get("wins", 0) + stats.get("losses", 0)

                if total_resolved < max(self._min_trades, 5):
                    continue

                wins = stats["wins"]
                losses = stats["losses"]
                win_rate = wins / total_resolved if total_resolved > 0 else 0.0

                if win_rate < self._min_win_rate:
                    continue

                # Use enhanced wallet scorer for composite score
                analysis = self._wallet_scorer.score_from_basic_stats(
                    address=address,
                    wins=wins,
                    losses=losses,
                    volume=stats.get("volume", 0.0),
                    last_active=stats.get("last_active", 0.0),
                    avg_win_pnl=stats.get("avg_win_pnl", 0.0),
                    avg_loss_pnl=stats.get("avg_loss_pnl", 0.0),
                    category_pnl=self._category_pnl,
                    wallet_categories=stats.get("categories"),
                )

                # Skip wallets flagged by red flag filters
                if analysis.is_filtered and total_resolved < 50:
                    continue

                # ── Wallet Quality Floor (P1) ─────────────────────────
                # Remove any wallet with pl_ratio < 1.5 (unless very high sample)
                pl_ratio = analysis.pl_ratio
                is_priority = address in self._PRIORITY_WALLETS
                if not is_priority and pl_ratio < min_pl_ratio and total_resolved < 100:
                    if win_rate < 0.80:
                        logger.debug(
                            "wallet_filtered_pl_ratio",
                            address=address[:12],
                            pl_ratio=round(pl_ratio, 2),
                            win_rate=round(win_rate, 3),
                        )
                        continue

                # Tiered quality gate:
                #   Tier A: win_rate >= 0.70 with >= 20 resolved trades
                #   Tier B: win_rate >= 0.60 with pl_ratio >= 3.0
                # Priority wallets always pass.
                tier_a = win_rate >= 0.70 and total_resolved >= min_trades_high_wr
                tier_b = win_rate >= 0.60 and pl_ratio >= 3.0 and total_resolved >= min_trades_med_wr
                if not (tier_a or tier_b or is_priority):
                    logger.debug(
                        "wallet_filtered_quality_tier",
                        address=address[:12],
                        win_rate=round(win_rate, 3),
                        pl_ratio=round(pl_ratio, 2),
                        total_resolved=total_resolved,
                    )
                    continue

                # Prefer category-adjusted score if available
                composite_score = analysis.category_adjusted_score if analysis.category_adjusted_score > 0 else analysis.composite_score
                if composite_score <= 0:
                    # Fallback to legacy scoring if composite is zero
                    base_score = win_rate * math.log(total_resolved + 1)
                    last_active = stats.get("last_active", 0.0)
                    days_since = (time.time() - last_active) / 86400 if last_active > 0 else 999
                    recency = 2.0 if days_since < 7 else (1.5 if days_since < 30 else 1.0)
                    composite_score = base_score * recency

                wallet = ScoredWallet(
                    address=address,
                    win_rate=win_rate,
                    total_resolved=total_resolved,
                    wins=wins,
                    losses=losses,
                    total_volume=stats.get("volume", 0.0),
                    last_active=stats.get("last_active", 0.0),
                    score=composite_score,
                    event_trades=total_resolved,
                    adjusted_win_rate=analysis.adjusted_win_rate,
                    pl_ratio=analysis.pl_ratio,
                )
                scored.append(wallet)

            scored.sort(key=lambda w: w.score, reverse=True)
            self._scored_wallets = scored

            self._save_wallet_cache()
            self._last_scan_time = time.time()

            logger.info(
                "copytrade_wallet_scan",
                status="complete",
                total_wallets_checked=len(wallet_stats),
                qualifying_wallets=len(scored),
                top_win_rate=round(scored[0].win_rate, 3) if scored else 0,
                top_score=round(scored[0].score, 3) if scored else 0,
                markets_scored=markets_scored,
            )

        except Exception as exc:
            logger.error("copytrade_wallet_scan", status="error", error=str(exc))

    async def _collect_wallet_activity(self) -> tuple[dict[str, dict[str, Any]], int]:
        """Gather wallet activity from multiple Gamma API scan passes.

        Runs several queries to maximise wallet diversity:
        1. Recently closed markets  (proven winners/losers)
        2. High-volume active markets  (liquid markets attract skilled traders)
        3. Category-specific scans  (politics, sports, crypto, science)
        4. Leaderboard / recent-activity wallets  (top performers)
        """
        wallet_stats: dict[str, dict[str, Any]] = {}
        assert self._http is not None

        # Track per-pass diversity metrics
        pass_wallet_counts: dict[str, int] = {}
        seen_condition_ids: set[str] = set()
        all_markets: list[tuple[dict[str, Any], str]] = []  # (market, pass_name)

        # ── Pass 1: Recently closed markets (existing behaviour) ─────
        try:
            closed_markets = await self._fetch_gamma_markets(
                closed=True, active=False, limit=200,
                order="closedTime", ascending=False,
            )
            for m in closed_markets:
                cid = m.get("conditionId", m.get("condition_id", ""))
                if cid and cid not in seen_condition_ids:
                    seen_condition_ids.add(cid)
                    all_markets.append((m, "recently_closed"))
            logger.info("copytrade_pass_recently_closed", fetched=len(closed_markets), unique=len(all_markets))
        except Exception as exc:
            logger.warning("copytrade_pass_recently_closed_error", error=str(exc))

        # ── Pass 2: High-volume active markets (NEW) ─────────────────
        try:
            active_markets = await self._fetch_gamma_markets(
                closed=False, active=True, limit=200,
                order="volume", ascending=False,
            )
            added = 0
            for m in active_markets:
                cid = m.get("conditionId", m.get("condition_id", ""))
                if cid and cid not in seen_condition_ids:
                    seen_condition_ids.add(cid)
                    all_markets.append((m, "high_volume_active"))
                    added += 1
            logger.info("copytrade_pass_high_volume", fetched=len(active_markets), new_unique=added)
        except Exception as exc:
            logger.warning("copytrade_pass_high_volume_error", error=str(exc))

        # ── Pass 3: Category-specific scans (NEW) ────────────────────
        for tag in self._scan_categories:
            try:
                cat_markets = await self._fetch_gamma_markets(
                    closed=True, active=False, limit=50,
                    order="closedTime", ascending=False,
                    tag=tag,
                )
                added = 0
                for m in cat_markets:
                    cid = m.get("conditionId", m.get("condition_id", ""))
                    if cid and cid not in seen_condition_ids:
                        seen_condition_ids.add(cid)
                        all_markets.append((m, f"category_{tag}"))
                        added += 1
                logger.info("copytrade_pass_category", tag=tag, fetched=len(cat_markets), new_unique=added)
            except Exception as exc:
                logger.warning("copytrade_pass_category_error", tag=tag, error=str(exc))

        logger.info(
            "copytrade_scan_markets_fetched",
            total_unique_markets=len(all_markets),
            passes_completed=3 + len(self._scan_categories),
        )

        # ── Process trades from all collected markets ─────────────────
        markets_with_trades = 0
        markets_scored = 0

        for market, pass_name in all_markets:
            condition_id = market.get("conditionId", market.get("condition_id", ""))
            markets_scored += 1

            outcome_prices_raw = market.get("outcomePrices", "")
            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices = json.loads(outcome_prices_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            elif isinstance(outcome_prices_raw, list):
                outcome_prices = outcome_prices_raw
            else:
                continue

            winning_index = None
            for i, p in enumerate(outcome_prices):
                if str(p) == "1":
                    winning_index = i
                    break
            if winning_index is None:
                continue

            clob_raw = market.get("clobTokenIds", "")
            if isinstance(clob_raw, str):
                try:
                    token_ids = json.loads(clob_raw) if clob_raw.startswith("[") else clob_raw.split(",")
                except (json.JSONDecodeError, TypeError):
                    continue
            elif isinstance(clob_raw, list):
                token_ids = clob_raw
            else:
                continue

            token_ids = [t.strip().strip('"') for t in token_ids]
            if winning_index >= len(token_ids):
                continue

            winning_token_id = token_ids[winning_index]

            # Categorize this market for wallet category tracking
            market_question_text = market.get("question", market.get("title", ""))
            market_category = categorize_market(market_question_text)

            try:
                trades = await self._fetch_market_trades(condition_id, limit=200)
            except Exception as exc:
                if markets_with_trades == 0:
                    logger.info("copytrade_market_trades_error", market=condition_id[:16], error=str(exc))
                continue

            if trades:
                markets_with_trades += 1

            wallets_before = set(wallet_stats.keys())

            for trade in trades:
                wallet_addr = trade.get("proxyWallet", trade.get("maker_address", ""))
                trade_token = trade.get("asset", trade.get("asset_id", ""))
                side = trade.get("side", "").upper()
                price = float(trade.get("price", 0))
                size = float(trade.get("size", 0))
                ts = trade.get("timestamp", 0)
                if isinstance(ts, str):
                    try:
                        ts = float(ts)
                    except (ValueError, TypeError):
                        ts = 0

                if not wallet_addr:
                    continue

                if wallet_addr not in wallet_stats:
                    wallet_stats[wallet_addr] = {
                        "wins": 0,
                        "losses": 0,
                        "volume": 0.0,
                        "last_active": 0.0,
                        "win_pnls": [],
                        "loss_pnls": [],
                        "categories": {},  # category -> trade count
                    }

                stats = wallet_stats[wallet_addr]
                trade_value = price * size
                stats["volume"] += trade_value
                if isinstance(ts, (int, float)) and ts > stats["last_active"]:
                    stats["last_active"] = ts

                # Track which categories this wallet trades in
                if market_category:
                    cats = stats.get("categories", {})
                    cats[market_category] = cats.get(market_category, 0) + 1
                    stats["categories"] = cats

                if side == "BUY" and trade_token == winning_token_id:
                    stats["wins"] += 1
                    stats["win_pnls"].append(trade_value)
                elif side == "BUY" and trade_token != winning_token_id:
                    stats["losses"] += 1
                    stats["loss_pnls"].append(trade_value)

            # Count new wallets discovered in this pass
            new_wallets = set(wallet_stats.keys()) - wallets_before
            pass_wallet_counts[pass_name] = pass_wallet_counts.get(pass_name, 0) + len(new_wallets)

        # ── Pass 4: Leaderboard / activity-based wallet discovery (NEW) ──
        leaderboard_wallets = 0
        if self._leaderboard_enabled:
            try:
                lb_addrs = await self._fetch_leaderboard_wallets()
                for addr in lb_addrs:
                    if addr and addr not in wallet_stats:
                        wallet_stats[addr] = {
                            "wins": 0,
                            "losses": 0,
                            "volume": 0.0,
                            "last_active": time.time(),
                            "win_pnls": [],
                            "loss_pnls": [],
                        }
                        leaderboard_wallets += 1
                pass_wallet_counts["leaderboard"] = leaderboard_wallets
                logger.info("copytrade_pass_leaderboard", new_wallets=leaderboard_wallets)
            except Exception as exc:
                logger.warning("copytrade_pass_leaderboard_error", error=str(exc))

        # Calculate avg P/L for each wallet
        for addr, stats in wallet_stats.items():
            win_pnls = stats.pop("win_pnls", [])
            loss_pnls = stats.pop("loss_pnls", [])
            stats["avg_win_pnl"] = sum(win_pnls) / len(win_pnls) if win_pnls else 0
            stats["avg_loss_pnl"] = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0

        # ── Log scan diversity metrics ────────────────────────────────
        logger.info(
            "copytrade_scan_diversity",
            total_wallets=len(wallet_stats),
            markets_with_trades=markets_with_trades,
            markets_scored=markets_scored,
            wallets_per_pass=pass_wallet_counts,
        )

        return wallet_stats, markets_scored

    async def _fetch_gamma_markets(
        self,
        closed: bool = False,
        active: bool = True,
        limit: int = 500,
        order: str = "closedTime",
        ascending: bool = False,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        assert self._http is not None
        params: dict[str, Any] = {
            "limit": min(limit, self._scan_markets_limit),
            "closed": closed,
            "active": active,
            "order": order,
            "ascending": ascending,
        }
        if tag:
            params["tag"] = tag
        resp = await self._http.get(f"{self._gamma_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_market_trades(
        self, market_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        assert self._http is not None
        try:
            params = {"market": market_id, "limit": limit}
            resp = await self._http.get(
                "https://data-api.polymarket.com/trades", params=params
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("copytrade_data_api_error", error=str(exc))
            return []

    async def _fetch_leaderboard_wallets(self) -> list[str]:
        """Discover high-performing wallets from leaderboard / activity APIs.

        Tries multiple sources in order:
        1. Gamma API leaderboard endpoint
        2. Polymarket Data API recent high-volume activity
        """
        assert self._http is not None
        discovered: list[str] = []

        # Attempt 1: Gamma leaderboard (may not exist — best effort)
        try:
            resp = await self._http.get(
                f"{self._gamma_url}/leaderboard",
                params={"limit": 100},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                entries = data if isinstance(data, list) else data.get("results", data.get("leaderboard", []))
                for entry in entries:
                    addr = entry.get("address", entry.get("proxyWallet", entry.get("wallet", "")))
                    if addr:
                        discovered.append(addr.lower())
                logger.info("copytrade_leaderboard_gamma", wallets=len(discovered))
        except Exception as exc:
            logger.debug("copytrade_leaderboard_gamma_unavailable", error=str(exc))

        # Attempt 2: Data API recent activity — find wallets with high volume
        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/activity",
                params={
                    "limit": 500,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                activities = resp.json()
                # Tally volume per wallet and pick the top performers
                wallet_volumes: dict[str, float] = {}
                for act in activities:
                    addr = act.get("proxyWallet", act.get("user", ""))
                    vol = float(act.get("usdcSize", act.get("size", 0)))
                    if addr:
                        addr = addr.lower()
                        wallet_volumes[addr] = wallet_volumes.get(addr, 0.0) + vol
                # Take top 100 by volume
                sorted_wallets = sorted(wallet_volumes.items(), key=lambda x: x[1], reverse=True)
                for addr, vol in sorted_wallets[:100]:
                    if addr not in discovered:
                        discovered.append(addr)
                logger.info("copytrade_leaderboard_activity", wallets_from_activity=len(sorted_wallets))
        except Exception as exc:
            logger.debug("copytrade_leaderboard_activity_error", error=str(exc))

        return discovered

    # ── Wallet cache persistence ─────────────────────────────────────────

    def _load_wallet_cache(self) -> None:
        if not self._wallet_cache_path.exists():
            return
        try:
            data = json.loads(self._wallet_cache_path.read_text())
            self._scored_wallets = [ScoredWallet.from_dict(w) for w in data.get("wallets", [])]
            self._last_scan_time = data.get("last_scan_time", 0.0)
            logger.info(
                "copytrade_wallet_cache_loaded",
                wallets=len(self._scored_wallets),
                last_scan=self._last_scan_time,
            )
        except Exception as exc:
            logger.warning("copytrade_wallet_cache_load_error", error=str(exc))

    def _save_wallet_cache(self) -> None:
        try:
            self._wallet_cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "wallets": [w.to_dict() for w in self._scored_wallets],
                "last_scan_time": self._last_scan_time,
                "count": len(self._scored_wallets),
            }
            self._wallet_cache_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.warning("copytrade_wallet_cache_save_error", error=str(exc))

    def _load_seen_trades(self) -> set[str]:
        if not hasattr(self, '_seen_trades_path') or not self._seen_trades_path.exists():
            return set()
        try:
            data = json.loads(self._seen_trades_path.read_text())
            return set(data.get("trade_ids", []))
        except Exception:
            return set()

    def _save_seen_trades(self) -> None:
        try:
            self._seen_trades_path.parent.mkdir(parents=True, exist_ok=True)
            ids = list(self._seen_trade_ids)[-5000:]
            self._seen_trades_path.write_text(json.dumps({"trade_ids": ids}))
        except Exception:
            pass

    def _load_positions(self) -> dict[str, CopiedPosition]:
        if not hasattr(self, '_positions_path') or not self._positions_path.exists():
            return {}
        try:
            data = json.loads(self._positions_path.read_text())
            positions = {}
            for pos_dict in data.get("positions", []):
                pos = CopiedPosition(**{k: v for k, v in pos_dict.items() if k in CopiedPosition.__dataclass_fields__})
                positions[pos.position_id] = pos
            # Restore category P/L if available
            if hasattr(self, '_category_pnl'):
                self._category_pnl = data.get("category_pnl", {})
            if positions:
                logger.info("copytrade_positions_loaded", count=len(positions))
            return positions
        except Exception as exc:
            logger.warning("copytrade_positions_load_error", error=str(exc)[:80])
            return {}

    def _save_positions(self) -> None:
        try:
            self._positions_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "positions": [p.to_dict() for p in self._positions.values()],
                "category_pnl": self._category_pnl,
            }
            self._positions_path.write_text(json.dumps(data, indent=2, default=str))
        except Exception:
            pass

    # ── Market filtering ─────────────────────────────────────────────────

    @staticmethod
    def _is_crypto_updown_market(title: str) -> bool:
        if not title:
            return False
        title_lower = title.lower()
        if "up or down" in title_lower:
            return True
        if "updown" in title_lower:
            return True
        return False

    def _is_short_window_market(self, market_question: str) -> bool:
        """Fast title-based short-window detector."""
        if not market_question:
            return False
        return any(pattern.search(market_question) for pattern in _SHORT_WINDOW_TITLE_PATTERNS)

    def _check_resolution_window(
        self,
        market_data: dict[str, Any],
        market_question: str,
    ) -> tuple[bool, str]:
        """Block markets resolving too soon (< MIN_RESOLUTION_HOURS)."""
        window_minutes = _parse_resolution_window_minutes(market_question)
        if window_minutes is not None and window_minutes < 30:
            return False, "short_window_market"
        if window_minutes is None and self._is_short_window_market(market_question):
            return False, "short_window_market"

        end_date_str = (
            market_data.get("endDate")
            or market_data.get("end_date_iso")
            or market_data.get("endDateIso")
            or ""
        )
        if not end_date_str:
            return True, ""

        try:
            from datetime import datetime, timezone

            end_dt = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            hours_remaining = (end_dt - now).total_seconds() / 3600
            if hours_remaining < self._min_resolution_hours:
                return False, f"resolution_window_too_short_{hours_remaining:.1f}h"
        except (ValueError, TypeError):
            return True, ""

        return True, ""

    def _check_category_tier(
        self,
        category: str,
        llm_score: float | None,
        market_question: str,
    ) -> tuple[bool, str]:
        """Apply whitelist/graylist/blacklist admission gates."""
        tier = self.CATEGORY_TIERS.get(category, "graylist")

        if tier == "whitelist":
            return True, ""

        if tier == "graylist":
            if not self._llm_validator.enabled:
                return True, ""
            if llm_score is not None and llm_score >= float(os.environ.get("CATEGORY_GRAYLIST_LLM_THRESHOLD", "0.75")):
                return True, ""
            return False, f"graylist_low_llm_score_{(llm_score or 0.0):.2f}"

        if tier == "blacklist":
            # If category is blacklisted, NEVER allow — no LLM or wallet override
            logger.info("copytrade_skip", reason="category_blacklisted", category=category)
            return False, f"blacklist_category_{category}"

        return True, ""

    @staticmethod
    def _parse_cluster_target_date(date_str: str) -> Any:
        """Convert 'april-3' style keys into a date object."""
        from datetime import date

        parts = (date_str or "").split("-", 1)
        if len(parts) != 2:
            return date.today()
        month_raw, day_raw = parts
        month = _MONTH_TO_INT.get(month_raw.lower())
        if month is None:
            return date.today()
        try:
            day = int(day_raw)
            return date(date.today().year, month, day)
        except ValueError:
            return date.today()

    @staticmethod
    def _city_to_noaa_station(city: str) -> str | None:
        """Map market city names to tracked NOAA station codes."""
        city_l = (city or "").strip().lower()
        if not city_l:
            return None

        aliases = {
            "new york": "KNYC",
            "nyc": "KNYC",
            "chicago": "KORD",
            "los angeles": "KLAX",
            "la": "KLAX",
            "denver": "KDEN",
            "atlanta": "KATL",
            "miami": "KMIA",
            "jfk": "KJFK",
        }
        if city_l in aliases:
            return aliases[city_l]

        for station, meta in KALSHI_STATIONS.items():
            station_city = str(meta.get("city", "")).lower()
            if station_city and city_l in station_city:
                return station
        return None

    async def _check_temperature_cluster(
        self,
        market_question: str,
        condition_id: str,
    ) -> tuple[bool, str]:
        """Enforce max-2 temperature brackets per city/date with forecast guidance."""
        cluster_key = _extract_temp_cluster_key(market_question)
        if not cluster_key:
            return True, ""

        city, date_str, temp = cluster_key
        key = (city, date_str)
        existing = self._temp_cluster_registry.get(key, {})
        if condition_id and condition_id in existing.values():
            return False, "temp_cluster_duplicate_condition"

        if len(existing) >= self._temp_cluster_max_brackets:
            return False, "temp_cluster_capped"

        station = self._city_to_noaa_station(city)
        target_date = self._parse_cluster_target_date(date_str)

        if not existing:
            if station:
                try:
                    best = await self._noaa_client.get_best_temperature_bracket(
                        station=station,
                        target_date=target_date,
                        brackets=[temp - 2, temp - 1, temp, temp + 1, temp + 2],
                    )
                    if best:
                        best_temp, _prob = best
                        if temp != best_temp:
                            return False, "temp_cluster_not_primary_bracket"
                except Exception:
                    pass
            return True, "primary_bracket"

        existing_temps = sorted(existing.keys())
        if len(existing_temps) == 1 and abs(temp - existing_temps[0]) > 1:
            return False, "temp_cluster_not_adjacent"

        if len(existing_temps) >= 2:
            return False, "temp_cluster_capped"

        if station:
            try:
                base_temp = existing_temps[0]
                min_t = min(base_temp, temp)
                max_t = max(base_temp, temp)
                best = await self._noaa_client.get_best_temperature_bracket(
                    station=station,
                    target_date=target_date,
                    brackets=[min_t, max_t],
                )
                if best:
                    best_temp, _prob = best
                    if best_temp not in (min_t, max_t):
                        return False, "temp_cluster_outside_forecast_band"
            except Exception:
                pass

        return True, "adjacent_bracket"

    # ── 2. Trade Monitoring ──────────────────────────────────────────────

    async def _monitor_trades(self) -> None:
        """Check top wallets for new trades, with hourly pacing."""
        if not self._scored_wallets:
            return

        top_wallets = self._scored_wallets[:25]

        # First pass: seed ALL existing trades so we never copy old ones
        if not self._initial_seed_done:
            logger.info("copytrade_seeding_existing_trades", wallets=len(top_wallets))
            for wallet in top_wallets:
                try:
                    trades = await self._fetch_wallet_trades(wallet.address)
                    for trade in trades:
                        trade_id = trade.get("transactionHash", trade.get("id", ""))
                        if trade_id:
                            self._seen_trade_ids.add(trade_id)
                except Exception:
                    pass
            self._initial_seed_done = True
            self._save_seen_trades()
            logger.info("copytrade_seeded", seen_trades=len(self._seen_trade_ids))
            return

        # Anti-spam gap (per-trade minimum spacing)
        if time.time() - self._last_trade_time < self._min_trade_gap:
            return

        # Circuit breaker — based on REALIZED losses only (not open positions)
        if self._halted:
            return
        daily_realized_loss = self._daily_realized_losses
        if daily_realized_loss > self._daily_loss_limit:
            if not self._halted:
                self._halted = True
                logger.warning(
                    "copytrade_daily_loss_halt",
                    realized_loss=round(daily_realized_loss, 2),
                    limit=self._daily_loss_limit,
                    trades=self._daily_trades,
                )
                _notify(
                    "[HALT] Trading Paused",
                    f"Daily loss ${daily_realized_loss:.2f} hit ${self._daily_loss_limit:.2f} limit\nResumes midnight UTC",
                )
            return

        # Hourly trade pacing — stop copying if hourly cap reached
        if self._hourly_limit_reached():
            logger.debug(
                "copytrade_hourly_limit",
                trades_this_hour=len(self._hourly_trade_times),
                limit=self._max_trades_per_hour,
            )
            return

        for wallet in top_wallets:
            # Re-check pacing after each wallet (may have copied trades)
            if self._hourly_limit_reached():
                break

            try:
                trades = await self._fetch_wallet_trades(wallet.address)

                for trade in trades:
                    if self._hourly_limit_reached():
                        break

                    trade_id = trade.get("transactionHash", trade.get("id", ""))
                    if not trade_id or trade_id in self._seen_trade_ids:
                        continue

                    self._seen_trade_ids.add(trade_id)
                    self._save_seen_trades()

                    side = trade.get("side", "").upper()
                    token_id = trade.get("asset", trade.get("asset_id", ""))
                    price = float(trade.get("price", 0))
                    size = float(trade.get("usdcSize", trade.get("size", 0)))
                    market = trade.get("conditionId", trade.get("market", ""))
                    market_question = trade.get("title", trade.get("market_question", trade.get("question", "")))

                    if side != "BUY":
                        if side == "SELL":
                            if wallet.address not in self._source_sells:
                                self._source_sells[wallet.address] = set()
                            self._source_sells[wallet.address].add(token_id)
                        continue

                    # Only copy trades from last 10 minutes
                    trade_ts = trade.get("timestamp", 0)
                    if isinstance(trade_ts, (int, float)) and trade_ts > 0:
                        age_seconds = time.time() - trade_ts
                        if age_seconds > 600:
                            continue

                    logger.info(
                        "copytrade_new_trade",
                        wallet=wallet.address[:10] + "...",
                        win_rate=round(wallet.win_rate, 3),
                        side=side,
                        token_id=token_id[:16] + "...",
                        price=price,
                        size=size,
                        market=market_question[:50],
                    )

                    was_placed = await self._copy_trade(
                        wallet=wallet,
                        trade=trade,
                        token_id=token_id,
                        price=price,
                        market=market,
                        market_question=market_question,
                        source_trade_id=trade_id,
                    )
                    if was_placed:
                        self._record_hourly_trade()

            except Exception as exc:
                logger.error(
                    "copytrade_monitor_error",
                    wallet=wallet.address[:10] + "...",
                    error=str(exc),
                )

    async def _fetch_wallet_trades(self, wallet_address: str) -> list[dict[str, Any]]:
        assert self._http is not None
        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/activity",
                params={
                    "user": wallet_address.lower(),
                    "type": "TRADE",
                    "limit": 50,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("copytrade_wallet_activity_error", wallet=wallet_address[:10], error=str(exc))
            return []

    # ── 3. Copy Execution ────────────────────────────────────────────────

    async def _copy_trade(
        self,
        wallet: ScoredWallet,
        trade: dict[str, Any],
        token_id: str,
        price: float,
        market: str,
        market_question: str,
        source_trade_id: str,
    ) -> bool:
        """Copy a BUY trade with Kelly sizing, LLM validation, and correlation checks.
        Returns True if trade was actually placed, False if skipped."""
        if self._observer_only:
            logger.info("observer_only_skip", path="copy_trade", market=market_question[:40], price=price)
            return False

        # ── Throttle 1: per-minute attempt rate cap ──────────────────
        now = time.time()
        self._attempt_times = [t for t in self._attempt_times if now - t < 60.0]
        if len(self._attempt_times) >= self._max_attempts_per_minute:
            logger.info(
                "copytrade_skipped_rate_limited",
                attempts_last_minute=len(self._attempt_times),
                limit=self._max_attempts_per_minute,
                market=market_question[:40],
            )
            return False

        # ── Throttle 2: per-token dedup window ───────────────────────
        last_seen = self._token_last_attempt.get(token_id, 0.0)
        if now - last_seen < self._dedupe_window_seconds:
            logger.info(
                "copytrade_skipped_duplicate",
                token=token_id[:16],
                seconds_ago=round(now - last_seen),
                window=int(self._dedupe_window_seconds),
                market=market_question[:40],
            )
            return False

        # ── Throttle 3: global max entry price ───────────────────────
        if price > self._copytrade_max_price and not self._allow_high_price:
            logger.info(
                "copytrade_skipped_price_too_high",
                price=price,
                max_price=self._copytrade_max_price,
                market=market_question[:40],
            )
            return False

        # Record this attempt against both rate-limit and dedup windows
        self._attempt_times.append(now)
        self._token_last_attempt[token_id] = now

        logger.info("copytrade_copy_attempt", market=market_question[:40], price=price, token=token_id[:16])

        # Skip tiny source trades (noise/test)
        source_usdc = float(trade.get("usdcSize", trade.get("size", 0)))
        min_source_trade = float(os.environ.get("COPYTRADE_MIN_SOURCE_USD", "0.50"))
        if source_usdc < min_source_trade:
            logger.info("copytrade_skip", reason="small_trade", usdc=source_usdc, min=min_source_trade, market=market_question[:40])
            return False

        # Guard: max positions
        if len(self._positions) >= self._max_positions:
            logger.info("copytrade_skip", reason="max_positions", current=len(self._positions), limit=self._max_positions)
            return False

        # Guard: per-wallet daily trade limit — tiered by wallet quality
        wallet_daily_cap = self._max_trades_per_wallet_per_day
        if wallet.win_rate >= 0.80 and wallet.total_resolved >= 20:
            wallet_daily_cap = 5  # Tier A: proven winners get 5/day
        elif wallet.win_rate >= 0.70:
            wallet_daily_cap = 4  # Tier B: solid wallets get 4/day

        wallet_trades_today = self._wallet_daily_trades.get(wallet.address, 0)
        if wallet_trades_today >= wallet_daily_cap:
            logger.info(
                "copytrade_skip", reason="wallet_daily_limit",
                wallet=wallet.address[:10] + "...",
                trades_today=wallet_trades_today,
                limit=wallet_daily_cap,
                win_rate=round(wallet.win_rate, 2),
            )
            return False

        # Guard: circuit breaker (realized losses only)
        if self._daily_realized_losses > self._daily_loss_limit:
            logger.info("copytrade_skip", reason="circuit_breaker", realized_loss=round(self._daily_realized_losses, 2))
            return False

        # Guard: minimum bankroll
        if self._bankroll < 10:
            logger.info("copytrade_skip", reason="low_bankroll", bankroll=round(self._bankroll, 2))
            return False

        # Detect category early — needed for entry price caps and blacklist
        category = categorize_market(market_question)

        # Guard: category-specific entry price caps
        # Research (neobrother, Hans323, @crptAtlas, Binance analysis):
        # - Weather: buy CHEAP brackets (0.2-15¢), one 800%+ hit covers all misses
        # - Sports: moderate pricing, edge comes from domain knowledge
        # - Crypto: only longer-window markets, avoid near-certainties
        # - General: avoid paying >80¢ for any binary outcome
        # Top traders buy LOW and let winners pay for losers.
        # Buying at 90¢+ risks $9 to make $1 — terrible risk/reward.
        CATEGORY_MAX_ENTRY = {
            "weather": 0.20,
            "us_sports": 0.50,
            "sports": 0.50,
            "esports": 0.50,
            "tennis": 0.50,
            "crypto": 0.50,
            "crypto_updown": 0.50,
            "economics": 0.50,
            "science": 0.50,
            "other": 0.50,
            "politics": 0.50,
            "geopolitics": 0.50,
        }
        CATEGORY_MIN_ENTRY = {
            "weather": 0.05,
            "us_sports": 0.08,
            "sports": 0.08,
            "esports": 0.08,
            "tennis": 0.08,
            "crypto": 0.08,
            "crypto_updown": 0.08,
            "economics": 0.08,
            "science": 0.08,
            "other": 0.08,
            "politics": 0.08,
            "geopolitics": 0.08,
        }
        max_entry_price = CATEGORY_MAX_ENTRY.get(category, 0.50)
        min_entry_price = CATEGORY_MIN_ENTRY.get(category, 0.08)
        high_conviction_entry = wallet.win_rate >= 0.90 and wallet.total_resolved >= 30
        if price < min_entry_price:
            logger.info("copytrade_skip", reason="below_min_entry_price", price=price, min=min_entry_price, high_conviction=high_conviction_entry, market=market_question[:40])
            return False
        if price > max_entry_price:
            logger.info("copytrade_skip", reason="above_max_entry_price", price=price, max=max_entry_price, category=category, market=market_question[:40])
            return False

        # Minimum ROI filter — don't risk capital for tiny returns
        if price > 0.80:
            logger.info("copytrade_skip_low_roi", price=price, market=market_question[:50])
            return False

        # Guard: already have position in this market
        if market and market in self._active_condition_ids:
            logger.info("copytrade_skip", reason="same_market", market=market_question[:40] if market_question else market[:16])
            return False

        # Guard: already have position in this exact token
        for pos in self._positions.values():
            if pos.token_id == token_id:
                logger.info("copytrade_skip", reason="same_token", token=token_id[:16])
                return False

        # Guard: event-level both-sides detection — check event slug, not just condition ID
        # This catches buying both outcomes of the same event (e.g., BTC Up AND BTC Down)
        trade_event_slug = trade.get("slug", trade.get("eventSlug", trade.get("event_slug", "")))
        if trade_event_slug and trade_event_slug in self._active_event_slugs:
            logger.info(
                "copytrade_skip",
                reason="event_level_duplicate",
                event_slug=trade_event_slug,
                market=market_question[:40] if market_question else market[:16],
            )
            return False

        if not market_question:
            market_question = market

        if self._clob_client is None:
            logger.info("copytrade_skip", reason="no_clob_client")
            return False

        # ── P0: Resolution-window filter for crypto binaries ─────────
        allowed_resolution, resolution_reason = self._check_resolution_window(
            market_data=trade,
            market_question=market_question,
        )
        if not allowed_resolution:
            logger.info(
                "copytrade_skip",
                reason=resolution_reason or "short_window_market",
                market=market_question[:60],
            )
            return False

        # ── P0: Temperature cluster dedup ─────────────────────────
        allowed_temp_cluster, temp_cluster_reason = await self._check_temperature_cluster(
            market_question=market_question,
            condition_id=market,
        )
        if not allowed_temp_cluster:
            logger.info(
                "copytrade_skip",
                reason=temp_cluster_reason,
                market=market_question[:60],
            )
            return False

        # ── HIGH-CONVICTION BYPASS ─────────────────────────────
        # Wallets with 90%+ win rate on 20+ trades are proven winners.
        # Skip correlation limits and category caps.
        high_conviction = wallet.win_rate >= 0.90 and wallet.total_resolved >= 20

        # ── Per-category circuit breaker (skip for high conviction) ──
        if not high_conviction and category in self._halted_categories:
            logger.info(
                "copytrade_skip", reason="category_halted",
                category=category,
                daily_loss=round(self._daily_category_losses.get(category, 0), 2),
                market=market_question[:40],
            )
            return False

        # ── Tiered position sizing based on wallet quality ────────
        # Default $3, scale to $5 for >80% WR, $10 for >90% WR + >30 resolved in category
        # Data: <$5 positions have 78% WR, $5-10 have 43% WR
        cat_pnl = self._category_pnl.get(category, 0)
        if self._kelly_enabled:
            size_usd = self._kelly_sizer.calculate_position_size(
                wallet_win_rate=wallet.win_rate,
                market_price=price,
                bankroll=self._bankroll,
                category=category,
                category_pnl=cat_pnl,
            )
        else:
            size_usd = self._size_usd

        # Bracket-aware tiered sizing — sweet spot (10-25c) gets biggest sizes
        in_sweet_spot = 0.10 <= price <= 0.25
        in_solid_bracket = 0.25 < price <= 0.50

        if wallet.win_rate >= 0.90 and wallet.total_resolved >= 30:
            tier_cap = 20.0 if in_sweet_spot else 15.0 if in_solid_bracket else 10.0
        elif wallet.win_rate >= 0.80:
            tier_cap = 15.0 if in_sweet_spot else 10.0 if in_solid_bracket else 5.0
        elif wallet.win_rate >= 0.70:
            tier_cap = 10.0 if in_sweet_spot else 7.0 if in_solid_bracket else 3.0
        else:
            tier_cap = 5.0 if in_sweet_spot else 3.0
        size_usd = min(size_usd, tier_cap)

        # ── Category-weighted sizing based on realized P/L ─────────
        would_exceed_cat_check, category, current_exposure = self._correlation_tracker.would_exceed_limit(
            market_question=market_question,
            size_usd=size_usd,
        )
        cat_mult = self._category_size_multiplier(category)
        size_usd = size_usd * cat_mult

        # Esports detection — extra 0.5x size reduction for thin esports markets
        esports_keywords = ["counter-strike", "cs2", "cs:go", "valorant", "dota", "lol ", "league of legends"]
        is_esports = any(kw in (market_question or "").lower() for kw in esports_keywords)
        if is_esports:
            size_usd *= 0.5
            logger.info("copytrade_esports_reduction", market=market_question[:40], size_after=round(size_usd, 2))

        # High conviction wallets get 1.5x size boost (still capped at $10 by hard cap)
        if high_conviction:
            size_usd *= 1.5

        # ── Bankroll-proportional scaling ────────────────────────
        # Scale position size proportional to bankroll.
        # At $386 (full deposit), use full tier sizes.
        # Below $100, floor the ratio at 0.5 so Kelly sizing isn't crushed
        # to the $1 minimum on every trade.
        REFERENCE_BANKROLL = 386.0
        bankroll_ratio = min(self._bankroll / REFERENCE_BANKROLL, 1.0)
        bankroll_ratio = max(bankroll_ratio, 0.5)  # floor: at least half Kelly size
        size_usd = max(size_usd * bankroll_ratio, 1.0)

        # Hard cap: bracket-dependent maximum
        hard_cap = 20.0 if in_sweet_spot else 15.0 if in_solid_bracket else 10.0
        size_usd = min(size_usd, hard_cap)

        # Check if treasury has set a dynamic max position percentage
        try:
            import redis as redis_sync
            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=1)
                treasury_max_pct = rc.get("treasury:max_position_pct")
                rc.close()
                if treasury_max_pct:
                    max_position = float(treasury_max_pct) * self._bankroll
                    size_usd = min(size_usd, max_position)
        except Exception:
            pass

        logger.info("copytrade_category_sizing", category=category, multiplier=cat_mult, tier_cap=tier_cap, esports=is_esports, high_conviction=high_conviction, bankroll_ratio=round(bankroll_ratio, 3), pre_scale_size=round(size_usd, 2), category_pnl=round(self._category_pnl.get(category, 0), 2))

        # ── Correlation + category caps (SKIPPED for high conviction) ──
        if not high_conviction:
            cat_pnl_current = self._category_pnl.get(category, 0)
            category_is_profitable = cat_pnl_current > 0

            if not category_is_profitable:
                would_exceed, category, current_exposure = self._correlation_tracker.would_exceed_limit(
                    market_question=market_question,
                    size_usd=size_usd,
                )
                if would_exceed:
                    logger.info(
                        "copytrade_skip_correlation_limit",
                        category=category,
                        current_exposure=round(current_exposure, 2),
                        limit=round(self._correlation_tracker.get_category_limit(), 2),
                        category_pnl=round(cat_pnl_current, 2),
                        market=market_question[:40],
                    )
                    return False

            correlated, corr_reason, corr_ids = self._correlation_tracker.check_semantic_correlation(
                market_question=market_question,
                max_correlated_positions=1,
            )
            if correlated:
                logger.info(
                    "copytrade_skipped_correlated",
                    reason=corr_reason,
                    existing_positions=corr_ids[:3],
                    market=market_question[:60],
                )
                return False

            category_position_count = sum(
                1 for p in self._positions.values() if p.category == category
            )
            effective_cat_cap = self._max_positions_per_category * 2 if category_is_profitable else self._max_positions_per_category
            if category_position_count >= effective_cat_cap:
                logger.info(
                    "copytrade_skip", reason="category_cap",
                    category=category,
                    count=category_position_count,
                    limit=effective_cat_cap,
                    market=market_question[:40],
                )
                return False
        else:
            logger.info(
                "copytrade_high_conviction_bypass",
                wallet=wallet.address[:10] + "...",
                win_rate=round(wallet.win_rate, 3),
                resolved=wallet.total_resolved,
                category=category,
                market=market_question[:40],
            )

        # ── LLM Validation + category tier gating ─────────────────────
        trade_thesis = ""
        llm_score: float | None = None
        tier = self.CATEGORY_TIERS.get(category, "graylist")
        requires_tier_score = tier != "whitelist"
        run_llm_validation = self._llm_validator.enabled and (requires_tier_score or not high_conviction)

        if run_llm_validation:
            bot_positions_ctx = [
                {"market_question": p.market_question, "condition_id": p.condition_id}
                for p in self._positions.values()
            ]
            validation = await self._llm_validator.validate_trade(
                market_question=market_question,
                current_price=price,
                trade_direction="BUY",
                wallet_win_rate=wallet.win_rate,
                category=category,
                category_pnl=self._category_pnl.get(category, 0),
                source_wallet=wallet.address,
                bot_positions=bot_positions_ctx,
            )
            llm_score = validation.llm_probability
            trade_thesis = validation.thesis
            if not high_conviction and not validation.approved:
                logger.info(
                    "copytrade_rejected",
                    market=market_question[:40],
                    price=price,
                    llm_prob=validation.llm_probability,
                    ev=round(validation.expected_value, 3),
                    reasoning=validation.reasoning[:80],
                    anti_patterns=validation.anti_patterns,
                    thesis=trade_thesis[:80],
                )
                return False
        elif high_conviction:
            trade_thesis = f"High-conviction copy: {wallet.win_rate*100:.0f}% WR on {wallet.total_resolved} trades"

        allowed_tier, tier_reason = self._check_category_tier(
            category=category,
            llm_score=llm_score,
            market_question=market_question,
        )
        if not allowed_tier:
            logger.info(
                "copytrade_skip",
                reason=tier_reason,
                category=category,
                llm_score=round(llm_score, 3) if llm_score is not None else None,
                market=market_question[:60],
            )
            return False

        # ── METAR weather enhancement for weather trades ─────────────
        if category == "weather":
            try:
                city = self._metar_client.find_city_in_market(market_question)
                if city:
                    metar_data = await self._metar_client.get_current_temp(city)
                    if metar_data:
                        edge_info = self._metar_client.evaluate_weather_edge(
                            market_question, price, metar_data["temp_c"]
                        )
                        metar_note = f"METAR: {city} actual {metar_data['temp_c']:.1f}°C/{metar_data['temp_f']:.1f}°F"
                        if edge_info:
                            metar_note += f" | Edge: {edge_info['edge']:+.2f} ({edge_info.get('confidence', 'med')})"
                            # Boost size if METAR confirms the trade direction
                            if edge_info["direction"] == "BUY" and edge_info["edge"] > 0.10:
                                size_usd *= 1.3  # 30% boost for METAR-confirmed weather trades
                                logger.info("metar_confirmed_boost", city=city, edge=edge_info["edge"], size=round(size_usd, 2))
                        trade_thesis = f"{trade_thesis}. {metar_note}" if trade_thesis else metar_note
                        logger.info("metar_weather_check", city=city, temp_c=metar_data["temp_c"], market=market_question[:40])
            except Exception as exc:
                logger.debug("metar_check_error", error=str(exc)[:80])

        # ── X-Intel signal boost ──
        x_boost = None
        matched_keyword = ""
        if self._x_intel is not None:
            try:
                x_boost = self._x_intel.get_market_boost(market_question)
                if x_boost is not None:
                    x_confidence = x_boost.get("confidence", 0)
                    x_direction = x_boost.get("direction", "")
                    x_author = x_boost.get("author", "unknown")
                    matched_keyword = x_boost.get("keyword", "")

                    # Copytrade always buys YES tokens
                    trade_side = "yes"
                    if x_direction == trade_side:
                        # Intel agrees — boost size_usd by up to 20%
                        boost_pct = min(x_confidence * 0.2, 0.20)
                        size_usd *= (1.0 + boost_pct)
                        logger.info(
                            "x_intel_boost_applied",
                            market=market_question[:60],
                            author=x_author,
                            x_confidence=round(x_confidence, 2),
                            boost_pct=round(boost_pct, 3),
                            new_size=round(size_usd, 2),
                        )
                    elif x_direction and x_direction != trade_side:
                        # Intel disagrees — suppress by 30%
                        size_usd *= 0.70
                        logger.info(
                            "x_intel_suppress_applied",
                            market=market_question[:60],
                            author=x_author,
                            x_direction=x_direction,
                            trade_side=trade_side,
                            new_size=round(size_usd, 2),
                        )
            except Exception as exc:
                logger.debug("x_intel_boost_error", error=str(exc)[:80])

        loop = asyncio.get_event_loop()

        # Use the wallet's trade price directly
        buy_price = round(round(price / 0.01) * 0.01, 2)
        if buy_price >= 1.0:
            buy_price = 0.99

        size_shares = size_usd / buy_price
        if size_shares < 5:
            size_shares = 5.0
        size_shares = round(size_shares, 2)

        position_id = f"ct-{uuid.uuid4().hex[:12]}"

        # Fetch market metadata from Gamma API (end date + event slug)
        market_end_date = ""
        event_slug = trade_event_slug  # may already have from trade data
        time_to_close = ""
        try:
            if market and self._http:
                mkt_resp = await self._http.get(
                    f"{self._gamma_url}/markets",
                    params={"condition_id": market, "limit": 1},
                )
                if mkt_resp.status_code == 200:
                    mkt_list = mkt_resp.json()
                    mkt_data = mkt_list[0] if isinstance(mkt_list, list) and mkt_list else mkt_list
                    market_end_date = mkt_data.get("endDate", mkt_data.get("endDateIso", ""))
                    # Extract event slug for both-sides guard
                    if not event_slug:
                        event_slug = mkt_data.get("slug", mkt_data.get("eventSlug", mkt_data.get("groupItemTitle", "")))
                    # Second check: event-level duplicate using Gamma-sourced slug
                    if event_slug and event_slug in self._active_event_slugs:
                        logger.info(
                            "copytrade_skip",
                            reason="event_level_duplicate_gamma",
                            event_slug=event_slug,
                            market=market_question[:40],
                        )
                        return False
                    if market_end_date:
                        import datetime as _dt
                        try:
                            end_dt = _dt.datetime.fromisoformat(market_end_date.replace("Z", "+00:00"))
                            now_dt = _dt.datetime.now(_dt.timezone.utc)
                            delta = end_dt - now_dt
                            if delta.total_seconds() > 0:
                                hours = delta.total_seconds() / 3600
                                if hours < 1:
                                    time_to_close = f"{int(delta.total_seconds() / 60)}min"
                                elif hours < 24:
                                    time_to_close = f"{hours:.1f}h"
                                else:
                                    days = hours / 24
                                    time_to_close = f"{days:.1f}d"
                        except Exception:
                            pass
        except Exception as exc:
            logger.debug("copytrade_enddate_fetch_error", error=str(exc)[:80])

        # Guard: complementary outcome (after Gamma may have filled event_slug)
        trade_outcome = (trade.get("outcome") or "").strip()
        eff_event_slug = (event_slug or trade_event_slug or "").strip()
        if eff_event_slug and trade_outcome:
            to_lower = trade_outcome.lower()
            for pos in self._positions.values():
                po = (getattr(pos, "outcome", None) or "").strip()
                if not po:
                    continue
                if pos.event_slug == eff_event_slug and po.lower() != to_lower:
                    logger.info(
                        "copytrade_skip",
                        reason="complementary_outcome_blocked",
                        held_outcome=po,
                        new_outcome=trade_outcome,
                        event_slug=eff_event_slug,
                    )
                    return False

        # Place order
        logger.info("copytrade_placing_order", market=market_question[:40], buy_price=buy_price, size_usd=round(size_usd, 2), size_shares=size_shares, kelly=self._kelly_enabled, bankroll=round(self._bankroll, 2))
        order_id = ""
        if self._dry_run:
            order_id = f"paper-{position_id}"
            logger.info("polymarket_paper_order", path="copy_trade", market=market_question[:40],
                        price=buy_price, size_usd=round(size_usd, 2), size_shares=size_shares)
            logger.info(
                "copytrade_copy_executed",
                mode="dry_run",
                wallet=wallet.address[:10] + "...",
                market=market_question[:40],
                buy_price=buy_price,
                size_usd=round(size_usd, 2),
                size_shares=size_shares,
                win_rate=round(wallet.win_rate, 3),
                category=category,
                kelly=self._kelly_enabled,
            )
        else:
            try:
                from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

                order_args = OrderArgs(
                    token_id=token_id,
                    price=buy_price,
                    size=size_shares,
                    side="BUY",
                )
                options = PartialCreateOrderOptions(
                    tick_size="0.01",
                    neg_risk=bool(mkt_data.get("neg_risk", mkt_data.get("negativeRisk", False))) if isinstance(mkt_data, dict) else False,
                )
                if self._sandbox:
                    _allowed, _reason = await self._sandbox.check_trade(
                        size=size_shares,
                        price=buy_price,
                    )
                    if not _allowed:
                        logger.warning("sandbox_blocked_trade", reason=_reason, market=market_question[:40], size=size_usd)
                        return False
                order_resp = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.create_and_post_order(order_args, options),
                )
                order_id = order_resp.get("orderID", "") if isinstance(order_resp, dict) else str(order_resp)
                status = order_resp.get("status", "") if isinstance(order_resp, dict) else ""
                if self._sandbox:
                    self._sandbox.record_trade(size_usd, pnl=0.0)

                logger.info(
                    "copytrade_copy_executed",
                    mode="live",
                    wallet=wallet.address[:10] + "...",
                    market=market_question[:40],
                    buy_price=buy_price,
                    wallet_price=price,
                    size_usd=round(size_usd, 2),
                    size_shares=size_shares,
                    order_id=order_id,
                    status=status,
                    win_rate=round(wallet.win_rate, 3),
                    category=category,
                    kelly=self._kelly_enabled,
                )

                self._last_trade_time = time.time()
                self._daily_spend += size_usd
                self._daily_trades += 1
                self._bankroll = max(0, self._bankroll - size_usd)
                self._wallet_daily_trades[wallet.address] = self._wallet_daily_trades.get(wallet.address, 0) + 1

            except Exception as exc:
                err_str = str(exc)
                logger.info("copytrade_order_error", error=err_str[:200], token_id=token_id[:16] + "...", market=market_question[:40])
                return False

        # Track position
        _neg_risk = bool(mkt_data.get("neg_risk", mkt_data.get("negativeRisk", False))) if isinstance(mkt_data, dict) else False
        position = CopiedPosition(
            position_id=position_id,
            source_wallet=wallet.address,
            token_id=token_id,
            market_question=market_question,
            condition_id=market,
            side="BUY",
            entry_price=price,
            size_usd=size_usd,
            size_shares=size_shares,
            copied_at=time.time(),
            source_trade_id=source_trade_id,
            order_id=order_id,
            category=category,
            wallet_win_rate=wallet.win_rate,
            end_date=market_end_date,
            event_slug=event_slug or "",
            outcome=trade_outcome,
            thesis=trade_thesis,
            neg_risk=_neg_risk,
        )
        self._positions[position_id] = position
        self._save_positions()

        # Register with exit engine (category-specific TP/SL/trailing)
        self._exit_engine.register_position(position_id, price, time.time(), category=category)

        # Register with correlation tracker
        self._correlation_tracker.add_position(position_id, market_question, size_usd)

        # Track condition_id and event_slug
        if market:
            self._active_condition_ids.add(market)
        if event_slug:
            self._active_event_slugs.add(event_slug)

        # Register temperature bracket for cluster dedup (P0)
        cluster_key = _extract_temp_cluster_key(market_question)
        if cluster_key:
            city, date_str, temp = cluster_key
            self._temp_cluster_registry.setdefault((city, date_str), {})[temp] = market

        # Record in PnL tracker
        pnl_trade = Trade(
            trade_id=order_id or position_id,
            timestamp=time.time(),
            market=market_question,
            token_id=token_id,
            side="BUY",
            price=price,
            size=size_shares,
            fee=0.0,
            strategy="copytrade",
        )
        self._pnl_tracker.record_trade(pnl_trade)

        # Record signal-influenced trade for performance tracking
        if x_boost is not None:
            try:
                from src.signal_tracker import record_signal_trade
                record_signal_trade(
                    signal={
                        "author": x_boost.get("author", ""),
                        "keyword": matched_keyword,
                        "direction": x_boost.get("direction", ""),
                        "confidence": x_boost.get("confidence", 0),
                        "relevance": x_boost.get("relevance", 0),
                        "timestamp": x_boost.get("timestamp", 0),
                    },
                    trade={
                        "market": market_question,
                        "side": "yes",
                        "price": price,
                        "size_usd": size_usd,
                    },
                )
            except Exception as exc:
                logger.debug("signal_tracker_record_failed", error=str(exc)[:80])

        # Send notification with full context
        # Position lifecycle info — category-specific TP/SL
        cat_exit = CATEGORY_EXIT_PARAMS.get(category, {})
        sl_pct = cat_exit.get("sl", 0.50)
        tp1_price = min(price * 1.30, 0.99)  # trailing stop activation
        sl_price = price * (1 - sl_pct)
        close_line = f"Closes in: {time_to_close}" if time_to_close else ""
        lifecycle = f"Trail@: {tp1_price:.2f} | SL: {sl_price:.2f}"
        cat_pnl = self._category_pnl.get(category, 0)
        daily_net = self._daily_wins - self._daily_realized_losses
        # Enriched trade notification
        pos_count = len(self._positions) + 1
        daily_pnl = round(self._daily_wins - self._daily_realized_losses, 2)
        whale_tag = " WHALE" if size_usd >= 50 or (hasattr(wallet, 'total_volume') and wallet.total_volume >= 5000) else ""
        _notify(
            f"[REAL]{whale_tag}",
            f"{market_question[:55]}\n\n"
            f"${size_usd:.2f} @ {price:.2f}c\n"
            f"{wallet.win_rate*100:.0f}% WR ({wallet.total_resolved} trades)\n"
            f"SL: {sl_price:.2f}\n"
            f"Cat: {category}\n\n"
            f"Bankroll: ${self._bankroll:.0f}\n"
            f"Positions: {pos_count}\n"
            f"Day P/L: ${daily_pnl:+.2f}",
        )
        return True

    # ── 4. Position Management — Smart Exit Engine ───────────────────────

    async def _manage_positions(self) -> None:
        """Check all positions using the smart exit engine."""
        if not self._positions:
            return

        exits_to_execute: list[tuple[str, ExitSignal]] = []
        positions_to_remove: list[str] = []  # resolved/stale — skip sell, just clean up

        for pos_id, pos in self._positions.items():
            try:
                # Get current price
                current_price = 0
                try:
                    current_price = await self._client.get_midpoint(pos.token_id)
                except Exception:
                    try:
                        current_price = await self._client.get_price(pos.token_id, side="sell")
                    except Exception:
                        pass

                # If we can't get a price, check if position is stale and should be removed
                if current_price <= 0:
                    hold_hours = (time.time() - pos.copied_at) / 3600
                    cat_params = CATEGORY_EXIT_PARAMS.get(
                        pos.category if hasattr(pos, 'category') and pos.category else "other", {}
                    )
                    stale_hours = cat_params.get("time_hours", 48)
                    # Remove if older than stale time — market likely delisted/resolved
                    if hold_hours > stale_hours:
                        logger.info(
                            "copytrade_no_price_cleanup",
                            position_id=pos_id,
                            market=pos.market_question[:50],
                            hold_hours=round(hold_hours, 1),
                            stale_hours=stale_hours,
                        )
                        _notify(
                            "[CLEANED]",
                            f"{pos.market_question[:50]}\n{hold_hours:.0f}h old, no price available",
                        )
                        positions_to_remove.append(pos_id)
                    continue

                # Check market resolved (price → 0 or 1)
                # Resolved markets have no orderbook — skip sell, just clean up tracking.
                # The redeemer handles on-chain USDC recovery separately.
                if current_price >= 0.99 or current_price <= 0.01:
                    hold_hours = (time.time() - pos.copied_at) / 3600
                    won = current_price >= 0.99
                    # Calculate actual P/L
                    size_shares = pos.size_shares if hasattr(pos, 'size_shares') and pos.size_shares else 0
                    cost_basis = pos.size_usd if hasattr(pos, 'size_usd') and pos.size_usd else (pos.entry_price * size_shares)
                    payout = size_shares if won else 0  # $1 per share if won, $0 if lost
                    pnl_usd = payout - cost_basis
                    pnl_pct = ((current_price - pos.entry_price) / pos.entry_price * 100) if pos.entry_price > 0 else 0
                    result_label = "WON" if won else "LOST"
                    # Update bankroll: add payout back (won = shares returned as $1 each, lost = $0)
                    # The cost was already deducted when the trade was placed
                    self._bankroll += payout
                    # Track P/L
                    if won:
                        self._daily_wins += abs(pnl_usd) if pnl_usd > 0 else 0
                    else:
                        self._daily_realized_losses += abs(pnl_usd) if pnl_usd < 0 else cost_basis
                    category = getattr(pos, 'category', None) or categorize_market(pos.market_question)
                    self._emit_trade_resolved_event(pos, pos_id, pnl_usd)
                    if category == "weather":
                        try:
                            from strategies.weather_accuracy import get_store

                            city = self._metar_client.find_city_in_market(pos.market_question) or "unknown"
                            sid = city.lower().replace(" ", "_")
                            get_store().record_forecast(
                                station=sid,
                                horizon_hours=24,
                                predicted_temp=0.0,
                                actual_temp=0.0,
                                correct=(pnl_usd > 0),
                            )
                        except Exception:
                            pass
                    self._category_pnl[category] = self._category_pnl.get(category, 0) + pnl_usd
                    logger.info(
                        "copytrade_resolved",
                        position_id=pos_id,
                        market=pos.market_question[:50],
                        result=result_label,
                        entry_price=pos.entry_price,
                        pnl_usd=round(pnl_usd, 2),
                        payout=round(payout, 2),
                        hold_hours=round(hold_hours, 1),
                        bankroll=round(self._bankroll, 2),
                    )
                    _notify(
                        f"[{result_label}]",
                        f"{pos.market_question[:50]}\n"
                        f"Entry: {pos.entry_price:.2f} -> {'$1.00' if won else '$0.00'} = ${pnl_usd:+.2f} ({pnl_pct:+.0f}%)\n"
                        f"Held {hold_hours:.0f}h | Bank: ${self._bankroll:.2f}",
                    )
                    positions_to_remove.append(pos_id)
                    continue

                # Check source wallet sold
                wallet_sells = self._source_sells.get(pos.source_wallet, set())
                if pos.token_id in wallet_sells:
                    exits_to_execute.append((pos_id, ExitSignal(
                        position_id=pos_id,
                        reason="source_wallet_exit",
                        sell_fraction=1.0,
                        current_price=current_price,
                        entry_price=pos.entry_price,
                        pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                        hold_time_hours=(time.time() - pos.copied_at) / 3600,
                    )))
                    continue

                # Smart exit engine evaluation
                signal = self._exit_engine.evaluate(pos_id, current_price)
                if signal:
                    exits_to_execute.append((pos_id, signal))

                # Safety net: force-cleanup positions older than 2x their category stale time
                if not signal:
                    hold_hours = (time.time() - pos.copied_at) / 3600
                    cat_params = CATEGORY_EXIT_PARAMS.get(
                        pos.category if hasattr(pos, 'category') and pos.category else "other", {}
                    )
                    max_stale = cat_params.get("time_hours", 48) * 2
                    if hold_hours > max_stale:
                        logger.warning(
                            "copytrade_force_stale_cleanup",
                            position_id=pos_id,
                            market=pos.market_question[:50],
                            hold_hours=round(hold_hours, 1),
                            max_stale_hours=max_stale,
                            category=getattr(pos, 'category', 'other'),
                        )
                        exits_to_execute.append((pos_id, ExitSignal(
                            position_id=pos_id,
                            reason="force_stale_cleanup",
                            sell_fraction=1.0,
                            current_price=current_price,
                            entry_price=pos.entry_price,
                            pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                            hold_time_hours=hold_hours,
                        )))

                # Dust sweeper: sell positions worth less than $1, or under $2 and held >24h
                if not signal and pos_id not in [e[0] for e in exits_to_execute]:
                    est_value = current_price * pos.size_shares if hasattr(pos, 'size_shares') else 0
                    hold_hours_dust = (time.time() - pos.copied_at) / 3600
                    is_dust = est_value < DUST_VALUE_THRESHOLD
                    is_stale_dust = est_value < 2.0 and hold_hours_dust > STALE_DUST_HOURS

                    if is_dust or is_stale_dust:
                        reason = "dust_sweep" if is_dust else "stale_dust_sweep"
                        logger.info(
                            "copytrade_dust_sweep",
                            position_id=pos_id,
                            market=pos.market_question[:50],
                            est_value=round(est_value, 2),
                            hold_hours=round(hold_hours_dust, 1),
                            reason=reason,
                        )
                        exits_to_execute.append((pos_id, ExitSignal(
                            position_id=pos_id,
                            reason=reason,
                            sell_fraction=1.0,
                            current_price=current_price,
                            entry_price=pos.entry_price,
                            pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                            hold_time_hours=hold_hours_dust,
                        )))

            except Exception as exc:
                logger.error("copytrade_position_check_error", position_id=pos_id, error=str(exc))

        # Execute exits (actual sells via FOK)
        for pos_id, signal in exits_to_execute:
            await self._exit_position(pos_id, signal)

        # Clean up resolved/stale positions (no sell needed — redeemer handles USDC)
        for pos_id in positions_to_remove:
            pos = self._positions.get(pos_id)
            if not pos:
                continue
            del self._positions[pos_id]
            self._active_condition_ids.discard(pos.condition_id)
            if hasattr(pos, 'event_slug') and pos.event_slug:
                self._active_event_slugs.discard(pos.event_slug)
            self._exit_engine.unregister_position(pos_id)
            self._correlation_tracker.remove_position(pos_id)
            self._remove_temp_cluster_entry(pos.market_question, pos.condition_id)
            wallet_sells = self._source_sells.get(pos.source_wallet, set())
            wallet_sells.discard(pos.token_id)
        if positions_to_remove:
            self._save_positions()

        # ── Re-entry check: buy back into winners that dipped ──────────────
        await self._check_reentry_queue()

    # ── Profitable categories for whale tier 2 filtering ────────────────
    _WHALE_PROFITABLE_CATEGORIES: set[str] = {"crypto_updown", "crypto", "tennis", "esports"}

    # ── Wallet quality decay — re-score periodically ─────────────────

    async def _refresh_wallet_scores(self) -> None:
        """Re-score tracked wallets every 30 minutes.

        If a wallet's win rate drops below 50% (was above 55% when added),
        remove it from the active list.
        """
        self._last_wallet_refresh = time.time()

        if not self._scored_wallets or not self._http:
            return

        removed = []
        updated = 0

        for wallet in list(self._scored_wallets):
            try:
                resp = await self._http.get(
                    "https://data-api.polymarket.com/positions",
                    params={"user": wallet.address, "sizeThreshold": "0.1"},
                    timeout=10.0,
                )
                if resp.status_code != 200:
                    continue

                positions = resp.json()
                if not isinstance(positions, list) or not positions:
                    continue

                wins = 0
                losses = 0
                for pos in positions:
                    # Resolved positions have currentValue near 0 or near full payout
                    outcome = pos.get("outcome", "")
                    realized = float(pos.get("realizedPnl", 0) or 0)
                    if realized > 0:
                        wins += 1
                    elif realized < 0:
                        losses += 1

                total = wins + losses
                if total < 10:
                    continue

                new_wr = wins / total if total > 0 else 0

                if new_wr < 0.50 and wallet.win_rate >= 0.55:
                    removed.append(wallet)
                    logger.info(
                        "wallet_quality_decay",
                        wallet=wallet.address[:10] + "...",
                        old_wr=round(wallet.win_rate, 3),
                        new_wr=round(new_wr, 3),
                        msg=f"{wallet.address[:10]} dropped to {new_wr*100:.0f}%, removing",
                    )
                elif abs(new_wr - wallet.win_rate) > 0.02:
                    wallet.win_rate = new_wr
                    wallet.wins = wins
                    wallet.losses = losses
                    wallet.total_resolved = total
                    updated += 1

            except Exception as exc:
                logger.debug("wallet_refresh_error", wallet=wallet.address[:10], error=str(exc)[:80])
                continue

        for wallet in removed:
            self._scored_wallets.remove(wallet)

        if removed or updated:
            logger.info(
                "wallet_scores_refreshed",
                removed=len(removed),
                updated=updated,
                remaining=len(self._scored_wallets),
            )

    # ── P/L reconciliation against on-chain ────────────────────────────

    async def _reconcile_pnl(self) -> None:
        """Reconcile internal state against on-chain positions every 10 minutes.

        - Fetches real positions from Polymarket data API
        - Detects orphan positions (on-chain but not tracked)
        - Cleans up phantom positions (tracked but not on-chain)
        - Updates bankroll if drift exceeds $5
        """
        self._last_pnl_reconciliation = time.time()

        if not self._http:
            return

        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/positions",
                params={"user": self._our_wallet, "sizeThreshold": "0.1"},
                timeout=15.0,
            )
            if resp.status_code != 200:
                logger.debug("pnl_reconciliation_api_error", status=resp.status_code)
                return

            on_chain_positions = resp.json()
            if not isinstance(on_chain_positions, list):
                return

            # Build set of on-chain condition_ids
            on_chain_condition_ids: set[str] = set()
            on_chain_value = 0.0
            for pos in on_chain_positions:
                cid = pos.get("conditionId", pos.get("condition_id", ""))
                if cid:
                    on_chain_condition_ids.add(cid)
                current_val = float(pos.get("currentValue", 0) or 0)
                on_chain_value += current_val

            # Detect orphan positions — on-chain but not in our tracker
            our_condition_ids = {p.condition_id for p in self._positions.values() if p.condition_id}
            orphans = on_chain_condition_ids - our_condition_ids
            if orphans:
                orphan_records = _load_orphans()
                known_orphan_cids = {o["condition_id"] for o in orphan_records}
                for orphan_cid in orphans:
                    # Find the on-chain position data for this orphan
                    orphan_pos = next(
                        (p for p in on_chain_positions
                         if (p.get("conditionId") or p.get("condition_id", "")) == orphan_cid),
                        None,
                    )
                    orphan_value = float(orphan_pos.get("currentValue", 0) or 0) if orphan_pos else 0.0
                    orphan_token = orphan_pos.get("tokenId", orphan_pos.get("token_id", "")) if orphan_pos else ""
                    logger.info(
                        "orphan_position_found",
                        condition_id=orphan_cid[:16],
                        token_id=str(orphan_token)[:16],
                        estimated_value=round(orphan_value, 2),
                    )
                    # Persist orphan if not already tracked
                    if orphan_cid not in known_orphan_cids:
                        orphan_records.append({
                            "condition_id": orphan_cid,
                            "token_id": str(orphan_token),
                            "estimated_value": round(orphan_value, 2),
                            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        })
                        known_orphan_cids.add(orphan_cid)
                _save_orphans(orphan_records)
                logger.info("orphan_positions_persisted", total=len(orphan_records), new=len(orphans - known_orphan_cids))

            # Detect phantom positions — in our tracker but not on-chain
            phantoms = our_condition_ids - on_chain_condition_ids
            phantom_ids_to_remove = []
            for pos_id, pos in self._positions.items():
                if pos.condition_id in phantoms:
                    logger.info(
                        "phantom_position_cleanup",
                        position_id=pos_id,
                        condition_id=pos.condition_id[:16],
                        market=pos.market_question[:40],
                    )
                    phantom_ids_to_remove.append(pos_id)

            for pos_id in phantom_ids_to_remove:
                pos = self._positions.pop(pos_id, None)
                if pos:
                    self._active_condition_ids.discard(pos.condition_id)
                    self._active_event_slugs.discard(pos.event_slug)
                    self._exit_engine.unregister_position(pos_id)
                    self._correlation_tracker.remove_position(pos_id)
                    self._remove_temp_cluster_entry(pos.market_question, pos.condition_id)

            if phantom_ids_to_remove:
                self._save_positions()

            # Log bankroll drift (informational only — do NOT overwrite internal bankroll).
            # on_chain_value includes open position value, but the internal bankroll
            # tracks only CASH available for new trades. Overwriting caused oscillation.
            internal_bankroll = self._bankroll
            drift = abs(internal_bankroll - on_chain_value)
            if drift > 5.0 and on_chain_value > 0:
                logger.info(
                    "pnl_reconciliation_bankroll_drift",
                    internal=round(internal_bankroll, 2),
                    on_chain_total=round(on_chain_value, 2),
                    drift=round(drift, 2),
                    note="informational only — internal tracker is source of truth",
                )

            logger.info(
                "pnl_reconciliation",
                internal_positions=len(self._positions),
                on_chain_positions=len(on_chain_condition_ids),
                orphans=len(orphans),
                phantoms=len(phantoms),
                internal_bankroll=round(internal_bankroll, 2),
                on_chain_value=round(on_chain_value, 2),
                drift=round(drift, 2),
            )

        except Exception as exc:
            logger.warning("pnl_reconciliation_error", error=str(exc)[:100])

    def _add_wallet_to_watchlist(self, wallet_address: str) -> None:
        """Add a whale wallet to copytrade_wallets.json for future monitoring."""
        try:
            data: dict[str, Any] = {"wallets": [], "last_scan_time": 0, "count": 0}
            if self._wallet_cache_path.exists():
                data = json.loads(self._wallet_cache_path.read_text())

            existing_addrs = {w.get("address", "").lower() for w in data.get("wallets", [])}
            if wallet_address.lower() in existing_addrs:
                return

            data["wallets"].append({
                "address": wallet_address.lower(),
                "win_rate": 0.0,
                "total_resolved": 0,
                "wins": 0,
                "losses": 0,
                "total_volume": 0.0,
                "last_active": time.time(),
                "score": 0.0,
                "event_trades": 0,
                "adjusted_win_rate": 0.0,
                "pl_ratio": 0.0,
                "open_losing": 0,
                "source": "whale_scanner",
            })
            data["count"] = len(data["wallets"])
            self._wallet_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._wallet_cache_path.write_text(json.dumps(data, indent=2))
            logger.info("whale_wallet_added_to_watchlist", wallet=wallet_address[:10] + "...")
        except Exception as exc:
            logger.warning("whale_wallet_watchlist_error", error=str(exc)[:100])

    async def _check_whale_signals(self) -> None:
        """Check whale scanner for signals and respond with tiered system.

        Tier 1 (conf 50-70): Alert only — log + notify + add wallet to watchlist
        Tier 2 (conf 70-85): Small $3 entry — only profitable categories
        Tier 3 (conf 85-95): Medium $5 entry — insider/cluster, skip category filter
        Tier 4 (conf 95+):   High conviction $7-10 entry
        """
        if self._whale_scanner is None:
            return

        signals = self._whale_scanner.get_active_signals()
        if not signals:
            return

        for signal in signals:
            # Skip signals below minimum threshold
            if signal.confidence_score < 50:
                continue

            # Determine tier
            conf = signal.confidence_score
            if conf >= 95:
                tier = 4
            elif conf >= 85:
                tier = 3
            elif conf >= 70:
                tier = 2
            else:
                tier = 1

            market_question = signal.market_title or ""
            wallet_short = (signal.wallet[:10] + "...") if signal.wallet else "unknown"
            category = categorize_market(market_question)

            # ── Tier 1: Silent — add wallet to watchlist, no trade, no notification
            if tier == 1:
                self._add_wallet_to_watchlist(signal.wallet)
                logger.info(
                    "whale_signal_tier1_watch",
                    tier=1,
                    signal_type=signal.signal_type,
                    market=market_question[:50],
                    wallet=wallet_short,
                    confidence=round(conf, 1),
                    trade_size=round(signal.trade_size, 2),
                )
                continue

            # ── Tiers 2-4: trading — apply circuit breakers ───────────
            if self._halted:
                continue
            if self._daily_realized_losses > self._daily_loss_limit:
                continue
            if self._hourly_limit_reached():
                break
            if len(self._positions) >= self._max_positions:
                continue
            if self._bankroll < 10:
                continue

            # Skip if already have position in this market
            if signal.condition_id and signal.condition_id in self._active_condition_ids:
                continue

            # Need token_id -- fetch from Gamma API
            token_id = ""
            event_slug = signal.market_slug or ""
            try:
                if signal.condition_id and self._http:
                    mkt_resp = await self._http.get(
                        f"{self._gamma_url}/markets",
                        params={"condition_id": signal.condition_id, "limit": 1},
                    )
                    if mkt_resp.status_code == 200:
                        mkt_list = mkt_resp.json()
                        mkt_data = mkt_list[0] if isinstance(mkt_list, list) and mkt_list else mkt_list
                        token_id = mkt_data.get("clobTokenIds", [""])[0] if isinstance(mkt_data.get("clobTokenIds"), list) else ""
                        if not token_id:
                            token_id = mkt_data.get("tokenID", "")
                        if not market_question:
                            market_question = mkt_data.get("question", mkt_data.get("title", ""))
                        if not event_slug:
                            event_slug = mkt_data.get("slug", mkt_data.get("eventSlug", ""))
            except Exception as exc:
                logger.debug("whale_signal_market_fetch_error", error=str(exc)[:80])
                continue

            if not token_id:
                continue

            # Event-level dedup
            if event_slug and event_slug in self._active_event_slugs:
                continue

            # Entry price filter (same as copytrade: 0.40 - 0.97)
            price = signal.details.get("trade_price", 0)
            if not price:
                try:
                    price = await self._client.get_midpoint(token_id)
                except Exception:
                    continue
            if price < 0.40 or price > 0.97:
                continue

            # ── Tier-specific sizing and filtering ────────────────────
            details = signal.details or {}
            wallet_count = details.get("wallet_count", 1)
            total_volume = details.get("total_cluster_volume", signal.trade_size)
            is_cluster = signal.signal_type == "cluster"
            is_insider = signal.signal_type == "insider"

            if tier == 2:
                # Tier 2: $3, only profitable categories
                if category not in self._WHALE_PROFITABLE_CATEGORIES:
                    logger.info(
                        "whale_signal_tier2_skip_category",
                        tier=2, category=category, market=market_question[:50],
                    )
                    continue
                size_usd = 3.0
            elif tier == 3:
                # Tier 3: $5, skip category filter
                size_usd = 5.0
            else:
                # Tier 4: $7 default, $10 if cluster + insider combo
                if is_cluster and is_insider:
                    size_usd = 10.0
                elif wallet_count >= 3 and total_volume >= 5000:
                    size_usd = 10.0
                else:
                    size_usd = 7.0

            # Bankroll-proportional scaling for whale signals
            REFERENCE_BANKROLL = 386.0
            bankroll_ratio = min(self._bankroll / REFERENCE_BANKROLL, 1.0)
            bankroll_ratio = max(bankroll_ratio, 0.5)  # floor: at least half Kelly size
            size_usd = max(size_usd * bankroll_ratio, 1.0)

            # Hard cap: bracket-dependent maximum for whale signals
            ws_in_sweet = 0.10 <= price <= 0.25
            ws_in_solid = 0.25 < price <= 0.50
            ws_hard_cap = 20.0 if ws_in_sweet else 15.0 if ws_in_solid else 10.0
            size_usd = min(size_usd, ws_hard_cap)

            # Observer-only: log the signal but skip all order placement
            if self._observer_only:
                logger.info("observer_only_skip", path="whale_signal", tier=tier, market=market_question[:50])
                continue

            # Place order
            buy_price = round(round(price / 0.01) * 0.01, 2)
            if buy_price >= 1.0:
                buy_price = 0.99
            size_shares = size_usd / buy_price
            if size_shares < 5:
                size_shares = 5.0
            size_shares = round(size_shares, 2)

            position_id = f"ws-{uuid.uuid4().hex[:12]}"

            logger.info(
                "whale_signal_trade",
                tier=tier,
                signal_type=signal.signal_type,
                market=market_question[:50],
                wallet=wallet_short,
                confidence=round(conf, 1),
                size_usd=round(size_usd, 2),
                price=buy_price,
                category=category,
            )

            order_id = ""
            if self._dry_run:
                order_id = f"paper-{position_id}"
                logger.info("polymarket_paper_order", path="whale_signal", tier=tier,
                            market=market_question[:40], price=buy_price, size_usd=round(size_usd, 2))
                logger.info("whale_signal_trade_executed", mode="dry_run", tier=tier, market=market_question[:40], size=round(size_usd, 2))
            else:
                if self._clob_client is None:
                    continue
                try:
                    from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
                    loop = asyncio.get_event_loop()
                    _ws_neg_risk = bool(mkt_data.get("neg_risk", mkt_data.get("negativeRisk", False))) if isinstance(mkt_data, dict) else False
                    order_args = OrderArgs(token_id=token_id, price=buy_price, size=size_shares, side="BUY")
                    options = PartialCreateOrderOptions(
                        tick_size="0.01",
                        neg_risk=_ws_neg_risk,
                    )
                    if self._sandbox:
                        _allowed, _reason = await self._sandbox.check_trade(
                            size=size_shares,
                            price=buy_price,
                        )
                        if not _allowed:
                            logger.warning("sandbox_blocked_trade", reason=_reason, market=market_question[:40], size=size_usd)
                            continue
                    order_resp = await loop.run_in_executor(
                        None, lambda: self._clob_client.create_and_post_order(order_args, options),
                    )
                    order_id = order_resp.get("orderID", "") if isinstance(order_resp, dict) else str(order_resp)
                    if self._sandbox:
                        self._sandbox.record_trade(size_usd, pnl=0.0)

                    self._last_trade_time = time.time()
                    self._daily_spend += size_usd
                    self._daily_trades += 1
                    self._bankroll = max(0, self._bankroll - size_usd)
                    self._record_hourly_trade()
                except Exception as exc:
                    logger.info("whale_signal_order_error", error=str(exc)[:200], market=market_question[:40])
                    continue

            # Track position
            thesis = f"whale-signal tier {tier}: {signal.signal_type} on {market_question[:40]}"
            _ws_neg = bool(mkt_data.get("neg_risk", mkt_data.get("negativeRisk", False))) if isinstance(mkt_data, dict) else False
            position = CopiedPosition(
                position_id=position_id,
                source_wallet=signal.wallet,
                token_id=token_id,
                market_question=market_question,
                condition_id=signal.condition_id,
                side="BUY",
                entry_price=price,
                size_usd=size_usd,
                size_shares=size_shares,
                copied_at=time.time(),
                source_trade_id=signal.details.get("trade_id", ""),
                order_id=order_id,
                category=category,
                wallet_win_rate=signal.details.get("wallet_win_rate", 0),
                event_slug=event_slug or "",
                outcome=str(signal.details.get("outcome", "") or ""),
                thesis=thesis,
                neg_risk=_ws_neg,
            )
            self._positions[position_id] = position
            self._save_positions()
            self._exit_engine.register_position(position_id, price, time.time(), category=category)
            self._correlation_tracker.add_position(position_id, market_question, size_usd)
            if signal.condition_id:
                self._active_condition_ids.add(signal.condition_id)
            if event_slug:
                self._active_event_slugs.add(event_slug)

            # PnL tracking
            pnl_trade = Trade(
                trade_id=order_id or position_id,
                timestamp=time.time(),
                market=market_question,
                token_id=token_id,
                side="BUY",
                price=price,
                size=size_shares,
                fee=0.0,
                strategy="whale_signal",
            )
            self._pnl_tracker.record_trade(pnl_trade)

            # Tier-specific notifications
            if tier == 2:
                pass  # Tier 2: silent — only log, no notification
            elif tier == 3:
                detail = f"fresh wallet, ${signal.trade_size:.2f} single bet" if is_insider else f"{wallet_count} wallets clustered"
                _notify(
                    "[INSIDER] Entry",
                    f"[INSIDER] ${size_usd:.2f} on {market_question[:50]}\n"
                    f"{detail}",
                )
            elif tier == 4:
                _notify(
                    "[HIGH CONVICTION] Entry",
                    f"[HIGH CONVICTION] ${size_usd:.2f} on {market_question[:50]}\n"
                    f"{wallet_count} wallets, ${total_volume:.2f} total",
                )

    async def _check_reentry_queue(self) -> None:
        """Check queued re-entries — buy back into winners that dipped after trailing stop."""
        if not self._reentry_queue:
            return

        now = time.time()
        expired = []
        reentries = []

        for token_id, entry in self._reentry_queue.items():
            # Expire old entries
            if now - entry["exit_time"] > self._REENTRY_MAX_AGE:
                expired.append(token_id)
                continue

            # Skip if we already have a position in this market
            if entry["condition_id"] in self._active_condition_ids:
                continue

            # Skip if at max positions
            if len(self._positions) >= self._max_positions:
                continue

            # Check current price
            try:
                current_price = await self._client.get_midpoint(token_id)
            except Exception:
                try:
                    current_price = await self._client.get_price(token_id, side="buy")
                except Exception:
                    continue

            if current_price <= 0 or current_price >= 0.99 or current_price <= 0.01:
                expired.append(token_id)
                continue

            # Re-enter if price dipped below our target AND is still in valid range
            if (current_price <= entry["reentry_price"]
                    and current_price >= self._REENTRY_MIN_PRICE
                    and current_price <= self._REENTRY_MAX_PRICE):
                reentries.append((token_id, entry, current_price))

            # Also re-enter if price is ABOVE exit (market still running up) and we're missing out
            elif current_price > entry["exit_price"] * 1.02:  # 2% above exit = momentum continuing
                # Only if still below 0.90 (don't chase near-certainties)
                if current_price <= self._REENTRY_MAX_PRICE:
                    reentries.append((token_id, entry, current_price))

        # Remove expired
        for token_id in expired:
            logger.debug("copytrade_reentry_expired", token_id=token_id[:16])
            del self._reentry_queue[token_id]

        # Execute re-entries
        for token_id, entry, current_price in reentries:
            await self._execute_reentry(entry, current_price)
            self._reentry_queue.pop(token_id, None)

    async def _execute_reentry(self, entry: dict, current_price: float) -> None:
        """Execute a re-entry buy on a market we profitably exited."""
        market_question = entry["market_question"]
        token_id = entry["token_id"]
        condition_id = entry["condition_id"]
        category = entry["category"]
        exit_price = entry["exit_price"]

        # Kelly sizing with category multiplier
        cat_mult = self._category_size_multiplier(category)
        base_size = self._size_usd * cat_mult

        # Size it slightly smaller than original — we're being opportunistic
        size_usd = base_size * 0.75

        buy_price = round(round(current_price / 0.01) * 0.01, 2)
        if buy_price >= 1.0:
            buy_price = 0.99

        size_shares = size_usd / buy_price
        if size_shares < 5:
            size_shares = 5.0
        size_shares = round(size_shares, 2)

        position_id = f"ct-re-{uuid.uuid4().hex[:10]}"

        if self._observer_only:
            logger.info("observer_only_skip", path="reentry", market=market_question[:40])
            return

        logger.info(
            "copytrade_reentry_attempt",
            market=market_question[:40],
            exit_price=round(exit_price, 3),
            reentry_price=round(current_price, 3),
            size_usd=round(size_usd, 2),
        )

        if self._dry_run:
            order_id = f"paper-re-{position_id}"
            logger.info("polymarket_paper_order", path="reentry", market=market_question[:40],
                        price=buy_price, size_usd=round(size_usd, 2), size_shares=size_shares)
        else:
            try:
                loop = asyncio.get_event_loop()
                from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
                order_args = OrderArgs(
                    token_id=token_id,
                    price=buy_price,
                    size=size_shares,
                    side="BUY",
                )
                options = PartialCreateOrderOptions(
                    tick_size="0.01",
                    neg_risk=bool(entry.get("neg_risk", False)),
                )
                if self._sandbox:
                    _allowed, _reason = await self._sandbox.check_trade(
                        size=size_shares,
                        price=buy_price,
                    )
                    if not _allowed:
                        logger.warning("sandbox_blocked_trade", reason=_reason, market=market_question[:40], size=size_usd)
                        return
                order_resp = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.create_and_post_order(order_args, options),
                )
                order_id = order_resp.get("orderID", "") if isinstance(order_resp, dict) else str(order_resp)
                if self._sandbox:
                    self._sandbox.record_trade(size_usd, pnl=0.0)
            except Exception as exc:
                logger.error("copytrade_reentry_error", error=str(exc)[:200], market=market_question[:40])
                return

        # Track the new position
        position = CopiedPosition(
            position_id=position_id,
            source_wallet=entry.get("source_wallet", ""),
            token_id=token_id,
            market_question=market_question,
            condition_id=condition_id,
            side="BUY",
            entry_price=current_price,
            size_usd=size_usd,
            size_shares=size_shares,
            copied_at=time.time(),
            source_trade_id=f"reentry-{position_id}",
            order_id=order_id,
            category=category,
            event_slug=entry.get("event_slug", "") or "",
            outcome=entry.get("outcome", "") or "",
            thesis=f"Re-entry after profitable trailing stop exit at {exit_price:.2f}",
            neg_risk=bool(entry.get("neg_risk", False)),
        )
        self._positions[position_id] = position
        self._save_positions()
        self._exit_engine.register_position(position_id, current_price, time.time(), category=category)
        self._correlation_tracker.add_position(position_id, market_question, size_usd)
        if condition_id:
            self._active_condition_ids.add(condition_id)
        es = entry.get("event_slug", "") or ""
        if es:
            self._active_event_slugs.add(es)

        self._bankroll = max(0, self._bankroll - size_usd)
        self._daily_spend += size_usd
        self._daily_trades += 1

        # Record in PnL tracker
        pnl_trade = Trade(
            trade_id=order_id or position_id,
            timestamp=time.time(),
            market=market_question,
            token_id=token_id,
            side="BUY",
            price=current_price,
            size=size_shares,
            fee=0.0,
            strategy="copytrade",
        )
        self._pnl_tracker.record_trade(pnl_trade)

        _notify(
            "[RE-ENTRY]",
            f"{market_question[:55]}\n"
            f"${size_usd:.2f} @ {current_price:.2f}c | prev exit {exit_price:.2f}\n"
            f"Cat: {category} | Bankroll: ${self._bankroll:.0f}",
        )

        logger.info(
            "copytrade_reentry_executed",
            market=market_question[:40],
            exit_price=round(exit_price, 3),
            reentry_price=round(current_price, 3),
            size_usd=round(size_usd, 2),
            category=category,
        )

    async def _exit_position(self, position_id: str, signal: ExitSignal) -> None:
        """Close a copied position (full or partial)."""
        pos = self._positions.get(position_id)
        if not pos:
            return

        if self._observer_only:
            logger.info("observer_only_skip", path="exit_position", position_id=position_id)
            return

        # Haircut sell size by 0.5% to avoid 'not enough balance' errors from
        # CTF token rounding — on-chain balance can be slightly less than recorded
        _wallet = os.environ.get("POLY_PROXY_ADDRESS", os.environ.get("POLY_SAFE_ADDRESS", ""))
        if not _wallet and self._client:
            _wallet = getattr(self._client, "wallet_address", "")
        onchain = _get_onchain_balance(pos.token_id, _wallet) if pos.token_id else None

        if onchain is not None and onchain > 0:
            # Lesson 17: sell amounts round DOWN to prevent exit loops.
            # Haircut 0.5% — on-chain CTF balance can be slightly less than recorded.
            # Never sell more than held; always round DOWN with math.floor semantics via round().
            sell_shares = round(min(onchain, pos.size_shares) * signal.sell_fraction * 0.995, 2)
            if abs(onchain - pos.size_shares) > 1.0:
                logger.info("balance_drift_detected", position_id=position_id,
                            internal=pos.size_shares, onchain=round(onchain, 2))
        elif onchain == 0:
            logger.info("zero_balance_cleanup", position_id=position_id, market=pos.market_question[:50])
            del self._positions[position_id]
            return
        else:
            # Lesson 17: sell amounts round DOWN to prevent exit loops.
            # 10% haircut when on-chain balance unavailable — conservative to avoid over-sell errors.
            sell_shares = round(pos.size_shares * signal.sell_fraction * 0.90, 2)
        # Lesson 17: skip dust sells instead of forcing to 1 share — forcing above actual balance
        # causes the order to fail, the exit engine re-queues the position, and it loops forever.
        if sell_shares < 1:
            logger.info("sell_skip_dust", shares=sell_shares, position_id=position_id,
                        reason="below_minimum")
            return
        sell_usd = pos.size_usd * signal.sell_fraction
        current_price = signal.current_price
        pnl_pct = signal.pnl_pct
        pnl_usd = pnl_pct * sell_usd
        hold_hours = signal.hold_time_hours

        if self._dry_run:
            logger.info("polymarket_paper_order", path="exit_position", position_id=position_id,
                        price=current_price, size_shares=sell_shares, pnl_pct=round(pnl_pct * 100, 2))
            logger.info(
                "copytrade_position_exit",
                mode="dry_run",
                position_id=position_id,
                reason=signal.reason,
                entry_price=pos.entry_price,
                exit_price=current_price,
                pnl_pct=round(pnl_pct * 100, 2),
                pnl_usd=round(pnl_usd, 4),
                sell_fraction=signal.sell_fraction,
                hold_time_hours=round(hold_hours, 1),
                peak_price=round(signal.peak_price, 3),
            )
        else:
            try:
                # Sell via official py-clob-client (same as buys) — 5% slippage tolerance
                sell_price = round(round((current_price * 0.95) / 0.01) * 0.01, 2)
                if sell_price < 0.01:
                    sell_price = 0.01
                loop = asyncio.get_event_loop()
                from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
                sell_args = OrderArgs(
                    token_id=pos.token_id,
                    price=sell_price,
                    size=sell_shares,
                    side="SELL",
                )
                sell_options = PartialCreateOrderOptions(
                    tick_size="0.01",
                    neg_risk=getattr(pos, "neg_risk", False),
                )
                result = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.create_and_post_order(sell_args, sell_options),
                )
                order_id = result.get("orderID", "")
                status = result.get("status", "")
                if not order_id and status not in ("matched", "filled", ""):
                    if signal.reason in ("market_resolved", "force_stale_cleanup", "dust_sweep", "stale_dust_sweep"):
                        # Resolved/stale markets may have no orderbook — FOK fails.
                        # Fall through to cleanup; redeemer handles on-chain USDC recovery.
                        logger.info(
                            "copytrade_exit_resolved_cleanup",
                            position_id=position_id,
                            reason=f"{signal.reason}_fok_failed",
                            entry_price=pos.entry_price,
                            current_price=current_price,
                        )
                    else:
                        logger.warning(
                            "copytrade_exit_fok_unfilled",
                            position_id=position_id,
                            reason=signal.reason,
                            sell_price=sell_price,
                            current_price=current_price,
                            status=status,
                        )
                        return
                logger.info(
                    "copytrade_position_exit",
                    mode="live",
                    position_id=position_id,
                    reason=signal.reason,
                    entry_price=pos.entry_price,
                    exit_price=current_price,
                    sell_price=sell_price,
                    pnl_pct=round(pnl_pct * 100, 2),
                    pnl_usd=round(pnl_usd, 4),
                    sell_fraction=signal.sell_fraction,
                    hold_time_hours=round(hold_hours, 1),
                    order_id=order_id,
                    order_type="FOK",
                )
            except Exception as exc:
                logger.error(
                    "copytrade_exit_fok_error",
                    position_id=position_id,
                    reason=signal.reason,
                    sell_price=sell_price,
                    error=str(exc)[:200],
                )
                return

        # Record sell in PnL tracker
        sell_trade = Trade(
            trade_id=f"ct-exit-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            market=pos.market_question,
            token_id=pos.token_id,
            side="SELL",
            price=current_price,
            size=sell_shares,
            fee=0.0,
            strategy="copytrade",
            pnl=pnl_usd,
        )
        self._pnl_tracker.record_trade(sell_trade)

        # Track daily wins and realized losses, update bankroll
        self._bankroll += sell_usd
        if pnl_usd > 0:
            self._daily_wins += sell_usd + pnl_usd
        elif pnl_usd < 0:
            self._daily_realized_losses += abs(pnl_usd)

        # Track category P/L for adaptive sizing
        category = pos.category if hasattr(pos, 'category') and pos.category else "other"
        self._category_pnl[category] = self._category_pnl.get(category, 0) + pnl_usd

        # ── Per-category circuit breaker tracking ─────────────────────
        if pnl_usd < 0:
            self._daily_category_losses[category] = (
                self._daily_category_losses.get(category, 0) + abs(pnl_usd)
            )
            cat_loss = self._daily_category_losses[category]
            cat_limit = self._CATEGORY_LOSS_LIMITS.get(category, 25.0)
            if cat_loss >= cat_limit and category not in self._halted_categories:
                self._halted_categories.add(category)
                logger.warning(
                    "copytrade_category_halted",
                    category=category,
                    daily_loss=round(cat_loss, 2),
                    limit=cat_limit,
                )
                _notify(
                    f"[HALT] {category} Paused",
                    f"-${cat_loss:.2f} today (limit ${cat_limit:.2f})\nOther categories still active",
                )

        # ── Learning loop: recalculate dynamic multipliers ────────────
        self._recalculate_category_multipliers()

        # Log learning: outcome vs. original thesis for feedback loop
        pos_thesis = getattr(pos, 'thesis', '') or ''
        outcome = "win" if pnl_usd >= 0 else "loss"
        logger.info(
            "copytrade_learning_update",
            market=pos.market_question[:50],
            thesis=pos_thesis[:80],
            outcome=outcome,
            pnl=round(pnl_usd, 4),
            hold_hours=round(hold_hours, 1),
            category=category,
            category_pnl=round(self._category_pnl.get(category, 0), 2),
            category_mult=self._CATEGORY_MULTIPLIERS.get(category, 0.5),
        )

        # ── Full-context exit notification ────────────────────────────
        reason_label = {
            "trailing_stop": "Trail Stop",
            "stop_loss": "Stop Loss",
            "time_exit_stale": "Timed Out",
            "time_exit_deteriorating": "Deteriorating",
            "near_resolution_takeprofit": "Near Resolution TP",
            "market_resolved": "Resolved",
            "source_wallet_exit": "Wallet Sold",
            "force_stale_cleanup": "Force Cleaned",
            "dust_sweep": "Dust Swept",
            "stale_dust_sweep": "Stale Dust Swept",
        }.get(signal.reason, signal.reason)
        _notify(
            f"[EXIT - {reason_label}]",
            f"[EXIT - {reason_label}] {pos.market_question[:50]}\n"
            f"{pos.entry_price:.2f} -> {current_price:.2f} = ${pnl_usd:+.2f} ({pnl_pct*100:+.0f}%)\n"
            f"Held {hold_hours:.0f}h | Bank: ${self._bankroll:.2f}",
        )

        # ── Re-entry queue: if profitable trailing stop, watch for dip to buy back ──
        if pnl_usd > 0 and signal.reason == "trailing_stop" and current_price < 0.95:
            reentry_price = current_price * (1 - self._REENTRY_DIP_PCT)
            self._reentry_queue[pos.token_id] = {
                "market_question": pos.market_question,
                "condition_id": pos.condition_id,
                "token_id": pos.token_id,
                "exit_price": current_price,
                "exit_time": time.time(),
                "reentry_price": reentry_price,
                "category": category,
                "peak_price": signal.peak_price,
                "original_entry": pos.entry_price,
                "source_wallet": pos.source_wallet,
                "event_slug": getattr(pos, "event_slug", "") or "",
                "outcome": getattr(pos, "outcome", "") or "",
                "neg_risk": getattr(pos, "neg_risk", False),
            }
            logger.info(
                "copytrade_reentry_queued",
                market=pos.market_question[:40],
                exit_price=round(current_price, 3),
                reentry_below=round(reentry_price, 3),
                pnl=round(pnl_usd, 2),
            )
            _notify(
                "[WATCHING] Re-entry",
                f"{pos.market_question[:50]}\nBuy back below ${reentry_price:.2f}",
            )

        # Full exit — remove position entirely (all exits are 100% now)
        del self._positions[position_id]
        self._save_positions()
        self._active_condition_ids.discard(pos.condition_id)
        if hasattr(pos, 'event_slug') and pos.event_slug:
            self._active_event_slugs.discard(pos.event_slug)
        self._exit_engine.unregister_position(position_id)
        self._correlation_tracker.remove_position(position_id)
        self._remove_temp_cluster_entry(pos.market_question, pos.condition_id)
        wallet_sells = self._source_sells.get(pos.source_wallet, set())
        wallet_sells.discard(pos.token_id)

    def _remove_temp_cluster_entry(self, market_question: str, condition_id: str) -> None:
        """Remove a temperature bracket from the cluster registry on position exit."""
        cluster_key = _extract_temp_cluster_key(market_question)
        if cluster_key:
            city, date_str, temp = cluster_key
            key = (city, date_str)
            entries = self._temp_cluster_registry.get(key, {})
            updated = {t: cid for t, cid in entries.items() if cid != condition_id}
            if updated:
                self._temp_cluster_registry[key] = updated
            else:
                self._temp_cluster_registry.pop(key, None)

    # ── 5. Position Redemption ───────────────────────────────────────────

    async def _check_and_redeem_positions(self) -> None:
        """Check for redeemable positions."""
        assert self._http is not None
        try:
            wallet = self._client.wallet_address
            if not wallet:
                return

            resp = await self._http.get(
                "https://data-api.polymarket.com/positions",
                params={"user": wallet},
            )
            resp.raise_for_status()
            positions = resp.json()

            redeemable = [
                p for p in positions
                if p.get("redeemable", False)
                and float(p.get("currentValue", 0)) > 0
                and float(p.get("curPrice", 0)) == 1.0
            ]

            if not redeemable:
                return

            total_value = sum(float(p.get("currentValue", 0)) for p in redeemable)
            logger.info("copytrade_redeemable_found", count=len(redeemable), total_value=round(total_value, 2))

            if self._clob_client is None:
                return

            for pos in redeemable:
                condition_id = pos.get("conditionId", "")
                title = pos.get("title", "")
                value = float(pos.get("currentValue", 0))

                if not condition_id:
                    continue

                logger.info(
                    "copytrade_position_redeemable",
                    title=title[:50],
                    condition_id=condition_id[:20] + "...",
                    value=round(value, 2),
                    action="delegated_to_redeemer",
                )

            logger.info(
                "copytrade_redeemable_summary",
                redeemable_count=len(redeemable),
                total_value=round(total_value, 2),
                note="standalone redeemer handles on-chain redemption",
            )

        except Exception as exc:
            logger.error("copytrade_redemption_check_error", error=str(exc))

    async def _cleanup_resolved_positions(self) -> None:
        """Remove resolved positions from tracking to free up position slots."""
        if not self._http or not self._client.wallet_address:
            return
        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/positions",
                params={"user": self._client.wallet_address},
            )
            resp.raise_for_status()
            api_positions = {p.get("conditionId", ""): p for p in resp.json()}

            cleaned = 0
            for pid, pos in list(self._positions.items()):
                api_pos = api_positions.get(pos.condition_id)
                if api_pos:
                    cur_price = float(api_pos.get("curPrice", 0.5))
                    if cur_price == 1.0 or cur_price == 0.0:
                        self._positions.pop(pid, None)
                        self._exit_engine.unregister_position(pid)
                        self._active_condition_ids.discard(pos.condition_id)
                        es = getattr(pos, "event_slug", "")
                        if es:
                            self._active_event_slugs.discard(es)
                        self._correlation_tracker.remove_position(pid)
                        cleaned += 1

            if cleaned:
                self._save_positions()
                logger.info("copytrade_cleanup_resolved", cleaned=cleaned, remaining=len(self._positions))
        except Exception as exc:
            logger.error("copytrade_cleanup_error", error=str(exc)[:200])

    # ── Status ───────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return current strategy status for API endpoints."""
        return {
            "name": "polymarket_copytrade",
            "running": self._running,
            "dry_run": self._dry_run,
            "observer_only": self._observer_only,
            "simulation_only": self._simulation_only,
            "scored_wallets": len(self._scored_wallets),
            "top_wallets": [
                {
                    "address": w.address[:10] + "..." + w.address[-4:],
                    "win_rate": round(w.win_rate, 3),
                    "adjusted_win_rate": round(w.adjusted_win_rate, 3),
                    "pl_ratio": round(w.pl_ratio, 2),
                    "resolved_trades": w.total_resolved,
                    "score": round(w.score, 3),
                }
                for w in self._scored_wallets[:10]
            ],
            "open_positions": len(self._positions),
            "positions": [
                {
                    "position_id": p.position_id,
                    "token_id": p.token_id[:16] + "...",
                    "market": p.market_question[:50],
                    "entry_price": p.entry_price,
                    "size_usd": round(p.size_usd, 2),
                    "source_wallet": p.source_wallet[:10] + "...",
                    "age_minutes": round((time.time() - p.copied_at) / 60, 1),
                    "category": p.category,
                    "thesis": (getattr(p, 'thesis', '') or '')[:60],
                }
                for p in self._positions.values()
            ],
            "seen_trades": len(self._seen_trade_ids),
            "last_scan_time": self._last_scan_time,
            "daily_spend": round(self._daily_spend, 2),
            "daily_wins": round(self._daily_wins, 2),
            "daily_net": round(self._daily_wins - self._daily_spend, 2),
            "daily_trades": self._daily_trades,
            "daily_loss_limit": self._daily_loss_limit,
            "halted": self._halted,
            "active_markets": len(self._active_condition_ids),
            "kelly_enabled": self._kelly_enabled,
            "bankroll": self._bankroll,
            "llm_validation_enabled": self._llm_validator.enabled,
            "category_pnl": {k: round(v, 2) for k, v in self._category_pnl.items()},
            "correlation_exposure": self._correlation_tracker.get_summary(),
            "exit_engine_tracked": self._exit_engine.active_count(),
            "reentry_queue": [
                {
                    "market": e["market_question"][:50],
                    "exit_price": round(e["exit_price"], 3),
                    "reentry_below": round(e["reentry_price"], 3),
                    "category": e["category"],
                    "age_minutes": round((time.time() - e["exit_time"]) / 60, 1),
                }
                for e in self._reentry_queue.values()
            ],
            "whale_scanner": self._whale_scanner.get_status() if self._whale_scanner else {"status": "disabled"},
            "config": {
                "size_usd": self._size_usd,
                "max_positions": self._max_positions,
                "min_win_rate": self._min_win_rate,
                "min_trades": self._min_trades,
                "scan_interval_hours": self._scan_interval_hours,
                "check_interval": self._check_interval,
                "daily_loss_limit": self._daily_loss_limit,
            },
        }
