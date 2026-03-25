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
   from the top-10 scored wallets.  Track seen trade IDs to avoid duplicates.

3. **Copy Execution** — when a top wallet makes a BUY, place a matching
   market-buy on the same token via the existing Polymarket client.  Position
   size defaults to $5.  Skip markets >90 % or <10 %.

4. **Position Management** — every 60 seconds, check each copied position.
   Exit when the source wallet sells, the market resolves, PnL > +15 %, or
   PnL < −20 % (stop loss).
"""

from __future__ import annotations

import asyncio
import json
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

        # Open copied positions
        self._positions: dict[str, CopiedPosition] = {}  # position_id -> CopiedPosition

        # Track source-wallet sells for exit signals
        self._source_sells: dict[str, set[str]] = {}  # wallet -> set of token_ids sold

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
        """Main loop: scan wallets, monitor trades, manage positions."""
        tick_count = 0

        while self._running:
            try:
                now = time.time()

                # 1. Wallet scan every N hours (or on first run)
                hours_since_scan = (now - self._last_scan_time) / 3600
                if hours_since_scan >= self._scan_interval_hours or self._last_scan_time == 0:
                    await self._scan_and_score_wallets()

                # 2. Monitor top wallets for new trades (every tick)
                await self._monitor_trades()

                # 3. Manage positions (every other tick ≈ 60s at 30s interval)
                if tick_count % 2 == 0:
                    await self._manage_positions()

                tick_count += 1

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("copytrade_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

    # ── 1. Wallet Discovery & Scoring ────────────────────────────────────

    async def _scan_and_score_wallets(self) -> None:
        """Discover active wallets and score by win rate."""
        logger.info("copytrade_wallet_scan", status="starting")

        try:
            # Collect wallets from recent market activity
            wallet_stats = await self._collect_wallet_activity()

            # Score and filter
            scored: list[ScoredWallet] = []
            for address, stats in wallet_stats.items():
                total_resolved = stats.get("wins", 0) + stats.get("losses", 0)
                if total_resolved < self._min_trades:
                    continue

                win_rate = stats["wins"] / total_resolved if total_resolved > 0 else 0.0
                if win_rate < self._min_win_rate:
                    continue

                import math
                composite_score = win_rate * math.log(total_resolved + 1)

                wallet = ScoredWallet(
                    address=address,
                    win_rate=win_rate,
                    total_resolved=total_resolved,
                    wins=stats["wins"],
                    losses=stats["losses"],
                    total_volume=stats.get("volume", 0.0),
                    last_active=stats.get("last_active", 0.0),
                    score=composite_score,
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
            )

        except Exception as exc:
            logger.error("copytrade_wallet_scan", status="error", error=str(exc))

    async def _collect_wallet_activity(self) -> dict[str, dict[str, Any]]:
        """Gather wallet activity from Gamma API resolved markets.

        Strategy: Fetch recently resolved markets, then look at the trades
        on those markets to build per-wallet win/loss statistics.
        """
        wallet_stats: dict[str, dict[str, Any]] = {}
        assert self._http is not None

        try:
            # Fetch resolved markets (closed=True) — these have known outcomes
            # TODO: The Gamma API may paginate differently; adjust if needed
            resolved_markets = await self._fetch_gamma_markets(
                closed=True, active=False, limit=200
            )

            logger.info(
                "copytrade_scan_markets_fetched",
                count=len(resolved_markets),
            )

            markets_with_trades = 0
            for market in resolved_markets:
                condition_id = market.get("conditionId", market.get("condition_id", ""))
                question = market.get("question", "")

                # Determine resolution from outcomePrices — e.g. ["1", "0"] means first outcome won
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

                # Find which outcome index resolved to 1 (winner)
                winning_index = None
                for i, p in enumerate(outcome_prices):
                    if str(p) == "1":
                        winning_index = i
                        break
                if winning_index is None:
                    continue  # not cleanly resolved

                # Parse clobTokenIds to get token IDs
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

                # Fetch trades for this market to identify wallets
                try:
                    trades = await self._fetch_market_trades(condition_id, limit=200)
                except Exception as exc:
                    # Log first error at info level so we can see it
                    if markets_with_trades == 0:
                        logger.info("copytrade_market_trades_error", market=condition_id[:16], error=str(exc))
                    continue

                if trades:
                    markets_with_trades += 1

                for trade in trades:
                    # Data API uses proxyWallet, side, asset, price, size
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

                    # Wallet bought the winning token → win
                    # Wallet bought the losing token → loss
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
        return wallet_stats

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

        # Rate limit: only copy one trade per cycle, minimum 5 min between copies
        if time.time() - self._last_trade_time < 300:
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

                    # Only log and copy BUY trades
                    if side != "BUY":
                        # Track sells for exit signals
                        if side == "SELL":
                            if wallet.address not in self._source_sells:
                                self._source_sells[wallet.address] = set()
                            self._source_sells[wallet.address].add(token_id)
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
                    )

                    await self._copy_trade(
                        wallet=wallet,
                        trade=trade,
                        token_id=token_id,
                        price=price,
                        market=market,
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
        """Fetch recent trades for a specific wallet from the CLOB API.

        TODO: The exact CLOB endpoint for per-wallet trades may vary.
        Common patterns:
          - GET /trades?maker_address={wallet}
          - GET /trades?taker_address={wallet}
        Adjust based on actual API behavior.
        """
        # Use the public Data API activity endpoint
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
        source_trade_id: str,
    ) -> None:
        """Copy a BUY trade from a top wallet."""

        # Guard: max positions
        if len(self._positions) >= self._max_positions:
            logger.info(
                "copytrade_skip_max_positions",
                current=len(self._positions),
                max=self._max_positions,
            )
            return

        # Guard: skip if market price >95% (basically resolved) or <2% (dust)
        if price > 0.95 or price < 0.02:
            logger.info(
                "copytrade_skip_extreme_price",
                price=price,
                token_id=token_id[:16] + "...",
            )
            return

        # Guard: already have position in this token
        for pos in self._positions.values():
            if pos.token_id == token_id:
                logger.debug("copytrade_skip_duplicate_position", token_id=token_id[:16])
                return

        # Calculate position size
        size_shares = self._size_usd / price if price > 0 else 0
        if size_shares <= 0:
            return

        position_id = f"ct-{uuid.uuid4().hex[:12]}"
        market_question = trade.get("title", trade.get("market_question", trade.get("question", market)))

        # Place order
        order_id = ""
        if self._dry_run:
            # Paper trade
            order_id = f"paper-{position_id}"
            logger.info(
                "copytrade_copy_executed",
                mode="dry_run",
                wallet=wallet.address[:10] + "...",
                token_id=token_id[:16] + "...",
                price=price,
                size_usd=self._size_usd,
                size_shares=round(size_shares, 4),
                win_rate=round(wallet.win_rate, 3),
            )
        else:
            # Live order via the official py-clob-client
            try:
                if self._clob_client is None:
                    logger.error("copytrade_no_clob_client")
                    return
                loop = asyncio.get_event_loop()
                from py_clob_client.clob_types import MarketOrderArgs, PartialCreateOrderOptions
                from py_clob_client.order_builder.constants import BUY as CLOB_BUY

                # Use market order (FOK) for instant fill
                # amount = USD amount for BUY orders
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=self._size_usd,
                    side="BUY",
                    price=round(min(price * 1.05, 0.99), 2),  # 5% slippage tolerance
                )

                options = PartialCreateOrderOptions(
                    tick_size="0.01",
                    neg_risk=False,
                )
                market_order = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.create_market_order(order_args, options),
                )
                order_resp = await loop.run_in_executor(
                    None,
                    lambda: self._clob_client.post_order(market_order, "FOK"),
                )
                order_id = order_resp.get("orderID", "") if isinstance(order_resp, dict) else str(order_resp)
                success = order_resp.get("success", False) if isinstance(order_resp, dict) else False
                status = order_resp.get("status", "") if isinstance(order_resp, dict) else ""

                if not success and status != "matched" and status != "live":
                    logger.debug(
                        "copytrade_fok_not_filled",
                        token_id=token_id[:16] + "...",
                        status=status,
                        resp=str(order_resp)[:100],
                    )
                    return

                logger.info(
                    "copytrade_copy_executed",
                    mode="live",
                    wallet=wallet.address[:10] + "...",
                    token_id=token_id[:16] + "...",
                    price=price,
                    size_usd=self._size_usd,
                    size_shares=round(size_shares, 2),
                    order_id=order_id,
                    win_rate=round(wallet.win_rate, 3),
                    status=status,
                )
            except Exception as exc:
                err_str = str(exc)
                # Silently skip known non-fatal errors
                if "does not exist" in err_str or "not enough balance" in err_str or "invalid signature" in err_str:
                    logger.debug(
                        "copytrade_order_skipped",
                        reason=err_str[:80],
                        token_id=token_id[:16] + "...",
                    )
                else:
                    logger.warning(
                        "copytrade_order_error",
                        error=err_str[:120],
                        token_id=token_id[:16] + "...",
                    )
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

        # Clean up source sell tracking for this token
        wallet_sells = self._source_sells.get(pos.source_wallet, set())
        wallet_sells.discard(pos.token_id)

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
                    "score": round(w.score, 3),
                }
                for w in self._scored_wallets[:10]
            ],
            "open_positions": len(self._positions),
            "positions": [
                {
                    "position_id": p.position_id,
                    "token_id": p.token_id[:16] + "...",
                    "entry_price": p.entry_price,
                    "size_usd": p.size_usd,
                    "source_wallet": p.source_wallet[:10] + "...",
                    "age_minutes": round((time.time() - p.copied_at) / 60, 1),
                }
                for p in self._positions.values()
            ],
            "seen_trades": len(self._seen_trade_ids),
            "last_scan_time": self._last_scan_time,
            "config": {
                "size_usd": self._size_usd,
                "max_positions": self._max_positions,
                "min_win_rate": self._min_win_rate,
                "min_trades": self._min_trades,
                "scan_interval_hours": self._scan_interval_hours,
                "check_interval": self._check_interval,
            },
        }
