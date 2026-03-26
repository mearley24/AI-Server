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

5. **Position Management** — Smart exit engine: tiered take-profit (15%/30%),
   stop-loss (25%), trailing stop (10% below peak), time-based exit (48h stale).

6. **Redemption** — every 5 minutes, check for resolved winning positions
   and redeem them via the ConditionalTokens contract to recover USDC.e.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from src.client import PolymarketClient, ORDER_TYPE_GTC
from src.config import Settings
from src.pnl_tracker import PnLTracker, Trade
from src.signer import SIDE_BUY, SIDE_SELL

from strategies.exit_engine import ExitEngine, ExitSignal
from strategies.kelly_sizing import KellySizer, get_bankroll_from_env, fetch_onchain_bankroll
from strategies.wallet_scoring import WalletScorer
from strategies.correlation_tracker import CorrelationTracker
from strategies.llm_validator import LLMValidator

logger = structlog.get_logger(__name__)


def _notify(title: str, body: str) -> None:
    """Best-effort push notification via Redis → notification-hub → iMessage."""
    try:
        import json as _json
        import redis
        url = os.environ.get("REDIS_URL", "redis://host.docker.internal:6379")
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Strategy ─────────────────────────────────────────────────────────────────

class PolymarketCopyTrader:
    """Copy-trades top-performing Polymarket wallets with smart exits and Kelly sizing."""

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        pnl_tracker: PnLTracker,
    ) -> None:
        self._client = client
        self._settings = settings
        self._pnl_tracker = pnl_tracker

        # Config from settings
        self._size_usd: float = getattr(settings, "copytrade_size_usd", 5.0)
        self._max_positions: int = getattr(settings, "copytrade_max_positions", 20)
        self._min_win_rate: float = getattr(settings, "copytrade_min_win_rate", 0.55)
        self._min_trades: int = getattr(settings, "copytrade_min_trades", 20)
        self._scan_interval_hours: float = getattr(settings, "copytrade_scan_interval_hours", 6.0)
        self._check_interval: float = getattr(settings, "copytrade_check_interval", 30.0)
        self._dry_run: bool = settings.dry_run

        # Daily risk controls — no fixed spend cap, but stop on drawdown
        self._daily_loss_limit: float = getattr(settings, "copytrade_daily_loss_limit", 50.0)
        self._daily_spend: float = 0.0
        self._daily_wins: float = 0.0
        self._daily_realized_losses: float = 0.0
        self._daily_trades: int = 0
        self._daily_spend_reset_time: float = 0.0
        self._halted: bool = False

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

        # Trade dedup
        self._seen_trades_path = Path(getattr(settings, "data_dir", "/data")) / "copytrade_seen_trades.json"
        self._seen_trade_ids: set[str] = self._load_seen_trades()
        self._initial_seed_done: bool = len(self._seen_trade_ids) > 0
        self._consecutive_errors: int = 0
        self._last_trade_time: float = 0.0
        self._min_trade_gap: float = 10.0

        # ── Trade pacing — rolling hourly cap ─────────────────────────
        self._max_trades_per_hour: int = int(os.environ.get("MAX_TRADES_PER_HOUR", "10"))
        self._hourly_trade_times: list[float] = []  # epoch timestamps of recent trades

        # ── Per-wallet daily trade limit ──────────────────────────────
        self._max_trades_per_wallet_per_day: int = int(os.environ.get("MAX_TRADES_PER_WALLET_PER_DAY", "3"))
        self._wallet_daily_trades: dict[str, int] = {}  # wallet_address -> trade count today

        # ── Per-category absolute position cap ────────────────────────
        self._max_positions_per_category: int = int(os.environ.get("MAX_POSITIONS_PER_CATEGORY", "5"))

        # Open copied positions
        self._positions: dict[str, CopiedPosition] = {}

        # Track condition_ids we already have positions in
        self._active_condition_ids: set[str] = set()

        # Track source-wallet sells for exit signals
        self._source_sells: dict[str, set[str]] = {}

        # Redemption tracking
        self._last_redemption_check: float = 0.0
        self._redemption_interval: float = 300.0

        # ── NEW: Phase 1 — Smart Exit Engine ─────────────────────────
        self._exit_engine = ExitEngine(
            take_profit_1_pct=float(os.environ.get("EXIT_TP1_PCT", "0.15")),
            take_profit_2_pct=float(os.environ.get("EXIT_TP2_PCT", "0.30")),
            stop_loss_pct=float(os.environ.get("EXIT_SL_PCT", "0.25")),
            trailing_stop_pct=float(os.environ.get("EXIT_TRAILING_PCT", "0.10")),
            time_exit_hours=float(os.environ.get("EXIT_TIME_HOURS", "48")),
            time_exit_min_move_pct=float(os.environ.get("EXIT_TIME_MIN_MOVE", "0.05")),
        )

        # ── NEW: Phase 1 — Kelly Criterion Position Sizing ───────────
        self._bankroll = float(os.environ.get("COPYTRADE_BANKROLL", "300"))
        self._last_bankroll_refresh: float = 0.0
        self._bankroll_refresh_interval: float = 3600.0
        self._kelly_enabled = os.environ.get("KELLY_SIZING_ENABLED", "true").lower() in ("true", "1", "yes")
        self._kelly_sizer = KellySizer(
            kelly_fraction=float(os.environ.get("KELLY_FRACTION", "0.25")),
            min_size_usd=float(os.environ.get("KELLY_MIN_SIZE", "2.0")),
            max_bankroll_pct=float(os.environ.get("KELLY_MAX_PCT", "0.05")),
            default_size_usd=self._size_usd,
        )

        # ── NEW: Phase 1 — Enhanced Wallet Scoring ───────────────────
        self._wallet_scorer = WalletScorer(
            min_closed_positions=int(os.environ.get("WALLET_MIN_CLOSED", "50")),
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

        # ── NEW: Phase 2 — Correlation Exposure Tracker ──────────────
        self._correlation_tracker = CorrelationTracker(
            max_category_pct=float(os.environ.get("CORRELATION_MAX_PCT", "0.15")),
            bankroll=self._bankroll,
        )

        # ── NEW: Phase 3 — LLM Trade Validation ─────────────────────
        self._llm_validator = LLMValidator()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        # Load cached wallets if available
        self._load_wallet_cache()

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
            kelly_enabled=self._kelly_enabled,
            bankroll=self._bankroll,
            llm_validation=self._llm_validator.enabled,
        )
        _notify(
            "🟢 Copy-Trader Started",
            f"Mode: {'DRY RUN' if self._dry_run else 'LIVE'}\n"
            f"Kelly: {'ON' if self._kelly_enabled else 'OFF'} | Bankroll: ${self._bankroll:.0f}\n"
            f"LLM Validation: {'ON' if self._llm_validator.enabled else 'OFF'}",
        )

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
        logger.info("copytrade_stopped", open_positions=len(self._positions))

    # ── Main loop ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main loop: scan wallets, monitor trades, manage positions, redeem."""
        tick_count = 0

        while self._running:
            try:
                now = time.time()

                # 0. Reset daily spend at midnight UTC
                self._maybe_reset_daily_spend(now)

                # 0b. Refresh bankroll from on-chain balance every hour
                if now - self._last_bankroll_refresh >= self._bankroll_refresh_interval:
                    try:
                        wallet_addr = self._client.wallet_address
                        if wallet_addr:
                            new_bankroll = await fetch_onchain_bankroll(wallet_addr)
                            if new_bankroll > 0:
                                self._bankroll = new_bankroll
                                logger.info("bankroll_updated", bankroll=round(self._bankroll, 2), source="onchain")
                        self._last_bankroll_refresh = now
                    except Exception as exc:
                        logger.warning("bankroll_refresh_error", error=str(exc)[:100])
                        self._last_bankroll_refresh = now

                # 1. Wallet scan every N hours (or on first run)
                hours_since_scan = (now - self._last_scan_time) / 3600
                if hours_since_scan >= self._scan_interval_hours or self._last_scan_time == 0:
                    await self._scan_and_score_wallets()

                # 2. Monitor top wallets for new trades (every tick)
                await self._monitor_trades()

                # 3. Manage positions with smart exit engine (every other tick ≈ 60s)
                if tick_count % 2 == 0:
                    await self._manage_positions()

                # 4. Redemption handled by standalone PolymarketRedeemer module

                tick_count += 1

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("copytrade_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

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
            self._daily_spend = 0.0
            self._daily_wins = 0.0
            self._daily_realized_losses = 0.0
            self._daily_trades = 0
            self._halted = False
            self._wallet_daily_trades = {}
            self._daily_spend_reset_time = today_midnight

    # ── 1. Wallet Discovery & Scoring ────────────────────────────────────

    async def _scan_and_score_wallets(self) -> None:
        """Discover active wallets and score by composite metrics."""
        logger.info("copytrade_wallet_scan", status="starting")

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
                )

                # Skip wallets flagged by red flag filters
                if analysis.is_filtered and total_resolved < 50:
                    continue

                composite_score = analysis.composite_score
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
                    }

                stats = wallet_stats[wallet_addr]
                trade_value = price * size
                stats["volume"] += trade_value
                if isinstance(ts, (int, float)) and ts > stats["last_active"]:
                    stats["last_active"] = ts

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
                    "🛑 Trading Halted",
                    f"Daily realized losses hit ${daily_realized_loss:.2f} (limit: ${self._daily_loss_limit:.0f})\n"
                    f"Trades today: {self._daily_trades} | Resumes at midnight",
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
        logger.info("copytrade_copy_attempt", market=market_question[:40], price=price, token=token_id[:16])

        # Skip tiny source trades (noise/test)
        source_usdc = float(trade.get("usdcSize", trade.get("size", 0)))
        min_source_trade = float(os.environ.get("COPYTRADE_MIN_SOURCE_USD", "1.0"))
        if source_usdc < min_source_trade:
            logger.info("copytrade_skip", reason="small_trade", usdc=source_usdc, min=min_source_trade, market=market_question[:40])
            return False

        # Guard: max positions
        if len(self._positions) >= self._max_positions:
            logger.info("copytrade_skip", reason="max_positions", current=len(self._positions), limit=self._max_positions)
            return False

        # Guard: per-wallet daily trade limit
        wallet_trades_today = self._wallet_daily_trades.get(wallet.address, 0)
        if wallet_trades_today >= self._max_trades_per_wallet_per_day:
            logger.info(
                "copytrade_skip", reason="wallet_daily_limit",
                wallet=wallet.address[:10] + "...",
                trades_today=wallet_trades_today,
                limit=self._max_trades_per_wallet_per_day,
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

        # Guard: basically-resolved markets
        max_price = float(os.environ.get("COPYTRADE_MAX_PRICE", "0.95"))
        min_price = float(os.environ.get("COPYTRADE_MIN_PRICE", "0.02"))
        if price > max_price or price < min_price:
            logger.info("copytrade_skip", reason="extreme_price", price=price, max=max_price, min=min_price)
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

        # Skip crypto Up/Down markets
        if self._is_crypto_updown_market(market_question):
            logger.info("copytrade_skip", reason="crypto_updown", market=market_question[:40])
            return False

        if not market_question:
            market_question = market

        if self._clob_client is None:
            logger.info("copytrade_skip", reason="no_clob_client")
            return False

        # ── NEW: Correlation exposure check ──────────────────────────
        # Calculate size first (needed for correlation check)
        if self._kelly_enabled:
            size_usd = self._kelly_sizer.calculate_position_size(
                wallet_win_rate=wallet.win_rate,
                market_price=price,
                bankroll=self._bankroll,
            )
        else:
            size_usd = self._size_usd

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
                market=market_question[:40],
            )
            return False

        # Guard: absolute per-category position count cap
        category_position_count = sum(
            1 for p in self._positions.values() if p.category == category
        )
        if category_position_count >= self._max_positions_per_category:
            logger.info(
                "copytrade_skip", reason="category_cap",
                category=category,
                count=category_position_count,
                limit=self._max_positions_per_category,
                market=market_question[:40],
            )
            return False

        # ── NEW: LLM Trade Validation ────────────────────────────────
        if self._llm_validator.enabled:
            validation = await self._llm_validator.validate_trade(
                market_question=market_question,
                current_price=price,
                trade_direction="BUY",
                wallet_win_rate=wallet.win_rate,
            )
            if not validation.approved:
                logger.info(
                    "copytrade_llm_rejected",
                    market=market_question[:40],
                    price=price,
                    llm_prob=validation.llm_probability,
                    ev=round(validation.expected_value, 3),
                    reasoning=validation.reasoning[:80],
                )
                _notify(
                    "🤖 LLM Rejected Trade",
                    f"{market_question[:45]}\n"
                    f"Price: {price:.2f} | LLM prob: {validation.llm_probability:.2f}\n"
                    f"Reason: {validation.reasoning[:60]}",
                )
                return False

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

        # Place order
        logger.info("copytrade_placing_order", market=market_question[:40], buy_price=buy_price, size_usd=round(size_usd, 2), size_shares=size_shares, kelly=self._kelly_enabled, bankroll=round(self._bankroll, 2))
        order_id = ""
        if self._dry_run:
            order_id = f"paper-{position_id}"
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
                    neg_risk=False,
                )
                order_resp = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.create_and_post_order(order_args, options),
                )
                order_id = order_resp.get("orderID", "") if isinstance(order_resp, dict) else str(order_resp)
                status = order_resp.get("status", "") if isinstance(order_resp, dict) else ""

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
        )
        self._positions[position_id] = position

        # Register with exit engine
        self._exit_engine.register_position(position_id, price, time.time())

        # Register with correlation tracker
        self._correlation_tracker.add_position(position_id, market_question, size_usd)

        # Track condition_id
        if market:
            self._active_condition_ids.add(market)

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

        # Send notification
        _notify(
            "📈 Copy Trade",
            f"{market_question[:45]}\n"
            f"Price: {price:.2f} | Size: ${size_usd:.2f}\n"
            f"Wallet: {wallet.address[:10]}... ({wallet.win_rate*100:.0f}% WR)\n"
            f"Category: {category}",
        )
        return True

    # ── 4. Position Management — Smart Exit Engine ───────────────────────

    async def _manage_positions(self) -> None:
        """Check all positions using the smart exit engine."""
        if not self._positions:
            return

        exits_to_execute: list[tuple[str, ExitSignal]] = []

        for pos_id, pos in self._positions.items():
            try:
                # Get current price
                try:
                    current_price = await self._client.get_midpoint(pos.token_id)
                except Exception:
                    try:
                        current_price = await self._client.get_price(pos.token_id, side="sell")
                    except Exception:
                        continue

                if current_price <= 0:
                    continue

                # Check market resolved (price → 0 or 1)
                if current_price >= 0.99 or current_price <= 0.01:
                    exits_to_execute.append((pos_id, ExitSignal(
                        position_id=pos_id,
                        reason="market_resolved",
                        sell_fraction=1.0,
                        current_price=current_price,
                        entry_price=pos.entry_price,
                        pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                        hold_time_hours=(time.time() - pos.copied_at) / 3600,
                    )))
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

            except Exception as exc:
                logger.error("copytrade_position_check_error", position_id=pos_id, error=str(exc))

        # Execute exits
        for pos_id, signal in exits_to_execute:
            await self._exit_position(pos_id, signal)

    async def _exit_position(self, position_id: str, signal: ExitSignal) -> None:
        """Close a copied position (full or partial)."""
        pos = self._positions.get(position_id)
        if not pos:
            return

        sell_shares = round(pos.size_shares * signal.sell_fraction, 2)
        sell_usd = pos.size_usd * signal.sell_fraction
        current_price = signal.current_price
        pnl_pct = signal.pnl_pct
        pnl_usd = pnl_pct * sell_usd
        hold_hours = signal.hold_time_hours

        if self._dry_run:
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
                result = await self._client.place_order(
                    token_id=pos.token_id,
                    price=current_price,
                    size=sell_shares,
                    side=SIDE_SELL,
                    order_type=ORDER_TYPE_GTC,
                )
                logger.info(
                    "copytrade_position_exit",
                    mode="live",
                    position_id=position_id,
                    reason=signal.reason,
                    entry_price=pos.entry_price,
                    exit_price=current_price,
                    pnl_pct=round(pnl_pct * 100, 2),
                    pnl_usd=round(pnl_usd, 4),
                    sell_fraction=signal.sell_fraction,
                    hold_time_hours=round(hold_hours, 1),
                    order_id=result.get("orderID", ""),
                )
            except Exception as exc:
                logger.error("copytrade_exit_order_error", position_id=position_id, reason=signal.reason, error=str(exc))
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

        # Send iMessage notification with full exit details
        emoji = "✅" if pnl_usd >= 0 else "❌"
        _notify(
            f"{emoji} Position Exit — {signal.reason}",
            f"{pos.market_question[:45]}\n"
            f"Entry: {pos.entry_price:.2f} → Exit: {current_price:.2f}\n"
            f"P&L: ${pnl_usd:+.2f} ({pnl_pct*100:+.1f}%)\n"
            f"Hold: {hold_hours:.1f}h | Sold: {signal.sell_fraction*100:.0f}%\n"
            f"Peak: {signal.peak_price:.2f}" if signal.peak_price else "",
        )

        # Handle full vs partial exit
        if signal.sell_fraction >= 1.0:
            # Full exit — remove position entirely
            del self._positions[position_id]
            self._active_condition_ids.discard(pos.condition_id)
            self._exit_engine.unregister_position(position_id)
            self._correlation_tracker.remove_position(position_id)
            wallet_sells = self._source_sells.get(pos.source_wallet, set())
            wallet_sells.discard(pos.token_id)
        else:
            # Partial exit — reduce position size
            pos.size_shares -= sell_shares
            pos.size_usd -= sell_usd

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
                    action="needs_manual_redemption",
                )

        except Exception as exc:
            logger.error("copytrade_redemption_check_error", error=str(exc))

    # ── Status ───────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return current strategy status for API endpoints."""
        return {
            "name": "polymarket_copytrade",
            "running": self._running,
            "dry_run": self._dry_run,
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
            "correlation_exposure": self._correlation_tracker.get_summary(),
            "exit_engine_tracked": self._exit_engine.active_count(),
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
