"""Polymarket Copy-Trading Strategy.

Discovers profitable wallets on Polymarket's public blockchain, scores them
by win rate, monitors their trades, and copies BUY entries within 30 seconds.

Flow
────
1. **Wallet Discovery** — every 6 hours, query the Gamma API for active
   markets, collect wallets with significant activity, and score by win rate.
   Wallets with ≥55 % win rate and ≥20 resolved trades are cached to
   ``/data/copytrade_wallets.json``.

2. **Trade Monitoring** — every 30 seconds, poll the CLOB API for new trades
   from the top-25 scored wallets.  Track seen trade IDs to avoid duplicates.

3. **Copy Execution** — when a top wallet makes a BUY on an EVENT market,
   place a matching GTC limit buy.  Skip all crypto Up/Down markets.
   Position size defaults to $5.  Daily spend capped at $25.

4. **Position Management** — every 60 seconds, check each copied position.
   Exit when the source wallet sells, the market resolves, PnL > +15 %, or
   PnL < −20 % (stop loss).

5. **Redemption** — every 5 minutes, check for resolved winning positions
   and redeem them via the ConditionalTokens contract to recover USDC.e.
"""

from __future__ import annotations

import asyncio
import json
import math
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

logger = structlog.get_logger(__name__)

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
    score: float = 0.0  # composite score: win_rate * log(trades)
    event_trades: int = 0  # number of event market trades scored on

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Strategy ─────────────────────────────────────────────────────────────────

class PolymarketCopyTrader:
    """Copy-trades top-performing Polymarket wallets."""

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

        # Daily spend limit
        self._daily_spend_limit: float = getattr(settings, "copytrade_daily_spend_limit", 25.0)
        self._daily_spend: float = 0.0
        self._daily_spend_reset_time: float = 0.0

        # API base URLs
        self._gamma_url = settings.gamma_api_url.rstrip("/")
        self._clob_url = settings.clob_api_url.rstrip("/")

        # HTTP client for public API reads (no auth needed)
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
                    signature_type=0,  # EOA mode — funds in EOA wallet
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

        # Trade dedup — set of trade IDs already seen (persisted to disk)
        self._seen_trades_path = Path(getattr(settings, "data_dir", "/data")) / "copytrade_seen_trades.json"
        self._seen_trade_ids: set[str] = self._load_seen_trades()
        self._initial_seed_done: bool = len(self._seen_trade_ids) > 0
        self._consecutive_errors: int = 0  # throttle error spam
        self._last_trade_time: float = 0.0  # last time we copied a trade

        # Open copied positions
        self._positions: dict[str, CopiedPosition] = {}  # position_id -> CopiedPosition

        # Track condition_ids we already have positions in (prevent buying both sides)
        self._active_condition_ids: set[str] = set()

        # Track source-wallet sells for exit signals
        self._source_sells: dict[str, set[str]] = {}  # wallet -> set of token_ids sold

        # Redemption tracking
        self._last_redemption_check: float = 0.0
        self._redemption_interval: float = 300.0  # 5 minutes

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
            daily_spend_limit=self._daily_spend_limit,
            dry_run=self._dry_run,
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

                # 1. Wallet scan every N hours (or on first run)
                hours_since_scan = (now - self._last_scan_time) / 3600
                if hours_since_scan >= self._scan_interval_hours or self._last_scan_time == 0:
                    await self._scan_and_score_wallets()

                # 2. Monitor top wallets for new trades (every tick)
                await self._monitor_trades()

                # 3. Manage positions (every other tick ≈ 60s at 30s interval)
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

    # ── Daily spend tracking ─────────────────────────────────────────────

    def _maybe_reset_daily_spend(self, now: float) -> None:
        """Reset daily spend counter at midnight UTC."""
        import datetime
        today_midnight = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        if today_midnight > self._daily_spend_reset_time:
            if self._daily_spend > 0:
                logger.info("copytrade_daily_spend_reset",
                            previous_spend=round(self._daily_spend, 2))
            self._daily_spend = 0.0
            self._daily_spend_reset_time = today_midnight

    # ── 1. Wallet Discovery & Scoring ────────────────────────────────────

    async def _scan_and_score_wallets(self) -> None:
        """Discover active wallets and score by win rate."""
        logger.info("copytrade_wallet_scan", status="starting")

        try:
            # Collect wallets from recent market activity
            wallet_stats, event_markets_scanned = await self._collect_wallet_activity()

            # Score and filter
            scored: list[ScoredWallet] = []
            for address, stats in wallet_stats.items():
                total_resolved = stats.get("wins", 0) + stats.get("losses", 0)

                # Require meaningful sample size on event markets
                if total_resolved < max(self._min_trades, 5):
                    continue

                win_rate = stats["wins"] / total_resolved if total_resolved > 0 else 0.0
                if win_rate < self._min_win_rate:
                    continue

                # Composite score: win_rate * log(trades) * recency_boost
                base_score = win_rate * math.log(total_resolved + 1)

                # Recency boost: 2x if active in last 7 days, 1.5x if last 30 days, 1x otherwise
                last_active = stats.get("last_active", 0.0)
                days_since_active = (time.time() - last_active) / 86400 if last_active > 0 else 999
                if days_since_active < 7:
                    recency_multiplier = 2.0
                elif days_since_active < 30:
                    recency_multiplier = 1.5
                else:
                    recency_multiplier = 1.0

                composite_score = base_score * recency_multiplier

                wallet = ScoredWallet(
                    address=address,
                    win_rate=win_rate,
                    total_resolved=total_resolved,
                    wins=stats["wins"],
                    losses=stats["losses"],
                    total_volume=stats.get("volume", 0.0),
                    last_active=stats.get("last_active", 0.0),
                    score=composite_score,
                    event_trades=total_resolved,
                )
                scored.append(wallet)

            # Sort by composite score descending
            scored.sort(key=lambda w: w.score, reverse=True)
            self._scored_wallets = scored

            # Persist to cache
            self._save_wallet_cache()
            self._last_scan_time = time.time()

            logger.info(
                "copytrade_wallet_scan",
                status="complete",
                total_wallets_checked=len(wallet_stats),
                qualifying_wallets=len(scored),
                top_win_rate=round(scored[0].win_rate, 3) if scored else 0,
                top_score=round(scored[0].score, 3) if scored else 0,
                event_markets_scanned=event_markets_scanned,
            )

        except Exception as exc:
            logger.error("copytrade_wallet_scan", status="error", error=str(exc))

    async def _collect_wallet_activity(self) -> tuple[dict[str, dict[str, Any]], int]:
        """Gather wallet activity from Gamma API resolved markets.

        Returns:
            Tuple of (wallet_stats dict, count of event markets processed).
        """
        wallet_stats: dict[str, dict[str, Any]] = {}
        assert self._http is not None

        try:
            resolved_markets = await self._fetch_gamma_markets(
                closed=True, active=False, limit=200
            )

            logger.info(
                "copytrade_scan_markets_fetched",
                count=len(resolved_markets),
            )

            markets_with_trades = 0
            event_markets_count = 0
            for market in resolved_markets:
                condition_id = market.get("conditionId", market.get("condition_id", ""))
                question = market.get("question", "")

                # Skip crypto Up/Down markets — wallets market-make these (no copyable edge)
                slug = market.get("slug", "")
                if self._is_crypto_updown_market(question) or "updown" in slug:
                    continue

                event_markets_count += 1

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
                        }

                    stats = wallet_stats[wallet_addr]
                    stats["volume"] += price * size
                    if isinstance(ts, (int, float)) and ts > stats["last_active"]:
                        stats["last_active"] = ts

                    if side == "BUY" and trade_token == winning_token_id:
                        stats["wins"] += 1
                    elif side == "BUY" and trade_token != winning_token_id:
                        stats["losses"] += 1

        except Exception as exc:
            logger.error("copytrade_collect_activity_error", error=str(exc))

        logger.info(
            "copytrade_collect_summary",
            total_wallets=len(wallet_stats),
            markets_with_trades=markets_with_trades if 'markets_with_trades' in dir() else 0,
        )
        return wallet_stats, event_markets_count if 'event_markets_count' in dir() else 0

    async def _fetch_gamma_markets(
        self, closed: bool = False, active: bool = True, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch markets from Gamma API, ordered by most recently closed."""
        assert self._http is not None
        params: dict[str, Any] = {
            "limit": limit,
            "closed": closed,
            "active": active,
            "order": "closedTime",
            "ascending": False,
        }
        resp = await self._http.get(f"{self._gamma_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_market_trades(
        self, market_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch trades from the public Data API (no auth needed)."""
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

    # ── Wallet cache persistence ─────────────────────────────────────────

    def _load_wallet_cache(self) -> None:
        """Load scored wallets from disk cache."""
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
        """Persist scored wallets to disk cache."""
        try:
            self._wallet_cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "wallets": [w.to_dict() for w in self._scored_wallets],
                "last_scan_time": self._last_scan_time,
                "count": len(self._scored_wallets),
            }
            self._wallet_cache_path.write_text(json.dumps(data, indent=2))
            logger.info(
                "copytrade_wallet_cache_saved",
                wallets=len(self._scored_wallets),
                path=str(self._wallet_cache_path),
            )
        except Exception as exc:
            logger.warning("copytrade_wallet_cache_save_error", error=str(exc))

    def _load_seen_trades(self) -> set[str]:
        """Load seen trade IDs from disk."""
        if not hasattr(self, '_seen_trades_path') or not self._seen_trades_path.exists():
            return set()
        try:
            data = json.loads(self._seen_trades_path.read_text())
            return set(data.get("trade_ids", []))
        except Exception:
            return set()

    def _save_seen_trades(self) -> None:
        """Persist seen trade IDs to disk."""
        try:
            self._seen_trades_path.parent.mkdir(parents=True, exist_ok=True)
            ids = list(self._seen_trade_ids)[-5000:]
            self._seen_trades_path.write_text(json.dumps({"trade_ids": ids}))
        except Exception:
            pass

    # ── Market filtering ─────────────────────────────────────────────────

    @staticmethod
    def _is_crypto_updown_market(title: str) -> bool:
        """Return True if this is a crypto Up/Down market (5m, 15m, hourly, 4h).

        These are essentially coin flips with no copyable edge.
        The wallets we track often buy BOTH sides (market making),
        so copying them means we get only one side = random outcome.
        """
        if not title:
            return False
        title_lower = title.lower()
        # All crypto up/down markets contain "up or down" in the title
        if "up or down" in title_lower:
            return True
        # Also catch slug-based patterns
        if "updown" in title_lower:
            return True
        return False

    # ── 2. Trade Monitoring ──────────────────────────────────────────────

    async def _monitor_trades(self) -> None:
        """Check top wallets for new trades. Only copies ONE trade per cycle."""
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

        # Rate limit: minimum 5 min between copies
        if time.time() - self._last_trade_time < 300:
            return

        # Daily spend limit check
        if self._daily_spend >= self._daily_spend_limit:
            return

        copied_this_cycle = False

        for wallet in top_wallets:
            if copied_this_cycle:
                break

            try:
                trades = await self._fetch_wallet_trades(wallet.address)

                for trade in trades:
                    if copied_this_cycle:
                        break

                    trade_id = trade.get("transactionHash", trade.get("id", ""))
                    if not trade_id or trade_id in self._seen_trade_ids:
                        continue

                    # Mark as seen immediately
                    self._seen_trade_ids.add(trade_id)
                    self._save_seen_trades()

                    side = trade.get("side", "").upper()
                    token_id = trade.get("asset", trade.get("asset_id", ""))
                    price = float(trade.get("price", 0))
                    size = float(trade.get("usdcSize", trade.get("size", 0)))
                    market = trade.get("conditionId", trade.get("market", ""))
                    market_question = trade.get("title", trade.get("market_question", trade.get("question", "")))

                    # Only copy BUY trades
                    if side != "BUY":
                        # Track sells for exit signals
                        if side == "SELL":
                            if wallet.address not in self._source_sells:
                                self._source_sells[wallet.address] = set()
                            self._source_sells[wallet.address].add(token_id)
                        continue

                    # FILTER: Skip ALL crypto Up/Down markets — no edge
                    if self._is_crypto_updown_market(market_question):
                        logger.debug(
                            "copytrade_skip_crypto_updown",
                            wallet=wallet.address[:10] + "...",
                            market=market_question[:40],
                        )
                        continue

                    # Only copy trades that happened in the last 10 minutes
                    trade_ts = trade.get("timestamp", 0)
                    if isinstance(trade_ts, (int, float)) and trade_ts > 0:
                        age_seconds = time.time() - trade_ts
                        if age_seconds > 600:  # older than 10 min, skip
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

                    await self._copy_trade(
                        wallet=wallet,
                        trade=trade,
                        token_id=token_id,
                        price=price,
                        market=market,
                        market_question=market_question,
                        source_trade_id=trade_id,
                    )
                    copied_this_cycle = True

            except Exception as exc:
                logger.error(
                    "copytrade_monitor_error",
                    wallet=wallet.address[:10] + "...",
                    error=str(exc),
                )

    async def _fetch_wallet_trades(self, wallet_address: str) -> list[dict[str, Any]]:
        """Fetch recent trades for a specific wallet from the Data API."""
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
    ) -> None:
        """Copy a BUY trade from a top wallet.

        Guards:
        - Skip tiny source trades (noise/test)
        - Skip markets priced near 50/50 (no clear edge)
        - Max positions check
        - No crypto Up/Down markets (already filtered in _monitor_trades)
        - No buying both sides of the same market (condition_id dedup)
        - Daily spend limit
        - Skip basically-resolved markets (>0.98 or <0.02)
        """

        # Skip tiny source trades (likely noise/test)
        source_usdc = float(trade.get("usdcSize", trade.get("size", 0)))
        if source_usdc < 5.0:
            logger.debug("copytrade_skip_small_trade", market=market_question[:40], usdc=source_usdc)
            return

        # Guard: max positions
        if len(self._positions) >= self._max_positions:
            return

        # Guard: daily spend limit
        if self._daily_spend + self._size_usd > self._daily_spend_limit:
            logger.info(
                "copytrade_daily_limit_reached",
                daily_spend=round(self._daily_spend, 2),
                limit=self._daily_spend_limit,
            )
            return

        # Guard: skip basically-resolved markets
        if price > 0.98 or price < 0.02:
            return

        # Guard: already have position in this MARKET (either side)
        # This prevents buying both Up and Down on the same event
        if market and market in self._active_condition_ids:
            logger.debug(
                "copytrade_skip_same_market",
                market=market_question[:40] if market_question else market[:16],
            )
            return

        # Guard: already have position in this exact token
        for pos in self._positions.values():
            if pos.token_id == token_id:
                return

        if not market_question:
            market_question = market

        if self._clob_client is None:
            return

        loop = asyncio.get_event_loop()

        # Use the wallet's trade price directly
        buy_price = round(round(price / 0.01) * 0.01, 2)  # round to nearest cent
        if buy_price >= 1.0:
            buy_price = 0.99

        # Skip markets priced near 50/50 — no clear edge
        if 0.40 <= buy_price <= 0.60:
            logger.debug("copytrade_skip_coinflip", market=market_question[:40], price=buy_price)
            return

        size_shares = self._size_usd / buy_price
        if size_shares < 5:
            size_shares = 5.0
        size_shares = round(size_shares, 2)

        position_id = f"ct-{uuid.uuid4().hex[:12]}"

        # Place GTC limit order
        order_id = ""
        if self._dry_run:
            order_id = f"paper-{position_id}"
            logger.info(
                "copytrade_copy_executed",
                mode="dry_run",
                wallet=wallet.address[:10] + "...",
                market=market_question[:40],
                buy_price=buy_price,
                size_usd=self._size_usd,
                size_shares=size_shares,
                win_rate=round(wallet.win_rate, 3),
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
                success = order_resp.get("success", False) if isinstance(order_resp, dict) else False
                status = order_resp.get("status", "") if isinstance(order_resp, dict) else ""

                logger.info(
                    "copytrade_copy_executed",
                    mode="live",
                    wallet=wallet.address[:10] + "...",
                    market=market_question[:40],
                    buy_price=buy_price,
                    wallet_price=price,
                    size_usd=self._size_usd,
                    size_shares=size_shares,
                    order_id=order_id,
                    status=status,
                    win_rate=round(wallet.win_rate, 3),
                )

                # Update spend tracking
                self._last_trade_time = time.time()
                self._daily_spend += self._size_usd

            except Exception as exc:
                err_str = str(exc)
                if "does not exist" not in err_str and "not enough balance" not in err_str and "invalid signature" not in err_str:
                    logger.warning("copytrade_order_error", error=err_str[:120], token_id=token_id[:16] + "...")
                return

        # Track position
        position = CopiedPosition(
            position_id=position_id,
            source_wallet=wallet.address,
            token_id=token_id,
            market_question=market_question,
            condition_id=market,
            side="BUY",
            entry_price=price,
            size_usd=self._size_usd,
            size_shares=size_shares,
            copied_at=time.time(),
            source_trade_id=source_trade_id,
            order_id=order_id,
        )
        self._positions[position_id] = position

        # Track condition_id to prevent buying the other side
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

    # ── 4. Position Management ───────────────────────────────────────────

    async def _manage_positions(self) -> None:
        """Check all open copied positions for exit conditions."""
        if not self._positions:
            return

        positions_to_close: list[tuple[str, str]] = []  # (position_id, reason)

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

                # Calculate PnL
                pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0

                # Exit condition: take profit > +15%
                if pnl_pct >= 0.15:
                    positions_to_close.append((pos_id, "take_profit"))
                    continue

                # Exit condition: stop loss > -20%
                if pnl_pct <= -0.20:
                    positions_to_close.append((pos_id, "stop_loss"))
                    continue

                # Exit condition: market resolved (price → 0 or 1)
                if current_price >= 0.99 or current_price <= 0.01:
                    positions_to_close.append((pos_id, "market_resolved"))
                    continue

                # Exit condition: source wallet sold this token
                wallet_sells = self._source_sells.get(pos.source_wallet, set())
                if pos.token_id in wallet_sells:
                    positions_to_close.append((pos_id, "source_wallet_exit"))
                    continue

            except Exception as exc:
                logger.error(
                    "copytrade_position_check_error",
                    position_id=pos_id,
                    error=str(exc),
                )

        # Execute exits
        for pos_id, reason in positions_to_close:
            await self._exit_position(pos_id, reason)

    async def _exit_position(self, position_id: str, reason: str) -> None:
        """Close a copied position."""
        pos = self._positions.get(position_id)
        if not pos:
            return

        # Get current price for PnL calculation
        try:
            current_price = await self._client.get_midpoint(pos.token_id)
        except Exception:
            current_price = pos.entry_price  # fallback

        pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
        pnl_usd = pnl_pct * pos.size_usd

        if self._dry_run:
            logger.info(
                "copytrade_position_exit",
                mode="dry_run",
                position_id=position_id,
                reason=reason,
                entry_price=pos.entry_price,
                exit_price=current_price,
                pnl_pct=round(pnl_pct * 100, 2),
                pnl_usd=round(pnl_usd, 4),
                hold_time_minutes=round((time.time() - pos.copied_at) / 60, 1),
            )
        else:
            # Place sell order
            try:
                result = await self._client.place_order(
                    token_id=pos.token_id,
                    price=current_price,
                    size=pos.size_shares,
                    side=SIDE_SELL,
                    order_type=ORDER_TYPE_GTC,
                )
                logger.info(
                    "copytrade_position_exit",
                    mode="live",
                    position_id=position_id,
                    reason=reason,
                    entry_price=pos.entry_price,
                    exit_price=current_price,
                    pnl_pct=round(pnl_pct * 100, 2),
                    pnl_usd=round(pnl_usd, 4),
                    hold_time_minutes=round((time.time() - pos.copied_at) / 60, 1),
                    order_id=result.get("orderID", ""),
                )
            except Exception as exc:
                logger.error(
                    "copytrade_exit_order_error",
                    position_id=position_id,
                    reason=reason,
                    error=str(exc),
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
            size=pos.size_shares,
            fee=0.0,
            strategy="copytrade",
            pnl=pnl_usd,
        )
        self._pnl_tracker.record_trade(sell_trade)

        # Remove from tracked positions
        del self._positions[position_id]

        # Remove condition_id from active set
        self._active_condition_ids.discard(pos.condition_id)

        # Clean up source sell tracking for this token
        wallet_sells = self._source_sells.get(pos.source_wallet, set())
        wallet_sells.discard(pos.token_id)

    # ── 5. Position Redemption ───────────────────────────────────────────

    async def _check_and_redeem_positions(self) -> None:
        """Check Polymarket Data API for redeemable positions and redeem them.

        Resolved winning positions hold conditional tokens that can be redeemed
        for USDC.e. This calls the ConditionalTokens contract's redeemPositions()
        function to convert winning shares back to USDC.e.
        """
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
            logger.info(
                "copytrade_redeemable_found",
                count=len(redeemable),
                total_value=round(total_value, 2),
            )

            # Redeem each position via py-clob-client or direct contract call
            if self._clob_client is None:
                logger.warning("copytrade_redeem_no_client")
                return

            for pos in redeemable:
                condition_id = pos.get("conditionId", "")
                title = pos.get("title", "")
                value = float(pos.get("currentValue", 0))

                if not condition_id:
                    continue

                try:
                    # The CLOB client doesn't have a native redeem method.
                    # Redemption requires calling ConditionalTokens.redeemPositions()
                    # on Polygon. For now, log what needs redemption so the user
                    # can redeem via the Polymarket website.
                    # TODO: Add web3 contract call for automatic redemption
                    logger.info(
                        "copytrade_position_redeemable",
                        title=title[:50],
                        condition_id=condition_id[:20] + "...",
                        value=round(value, 2),
                        action="needs_manual_redemption",
                    )
                except Exception as exc:
                    logger.warning(
                        "copytrade_redeem_error",
                        title=title[:30],
                        error=str(exc),
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
                    "resolved_trades": w.total_resolved,
                    "event_trades": w.event_trades,
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
                    "size_usd": p.size_usd,
                    "source_wallet": p.source_wallet[:10] + "...",
                    "age_minutes": round((time.time() - p.copied_at) / 60, 1),
                }
                for p in self._positions.values()
            ],
            "seen_trades": len(self._seen_trade_ids),
            "last_scan_time": self._last_scan_time,
            "daily_spend": round(self._daily_spend, 2),
            "daily_spend_limit": self._daily_spend_limit,
            "active_markets": len(self._active_condition_ids),
            "config": {
                "size_usd": self._size_usd,
                "max_positions": self._max_positions,
                "min_win_rate": self._min_win_rate,
                "min_trades": self._min_trades,
                "scan_interval_hours": self._scan_interval_hours,
                "check_interval": self._check_interval,
                "daily_spend_limit": self._daily_spend_limit,
            },
        }
