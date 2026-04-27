"""Avellaneda-Stoikov Market Making Strategy for crypto spot markets.

Implements the full A-S optimal quoting framework with:
- Reservation price adjusted for inventory risk
- Optimal spread from market microstructure parameters
- Hawkes process order flow prediction for directional bias
- VPIN circuit breaker for toxic flow detection
- Inventory manager for position limits and risk

Reservation Price:
    r = s - q * γ * σ² * (T - t)

Optimal Spread:
    δ = γ * σ² * (T - t) + (2/γ) * ln(1 + γ/κ)

Quote Generation:
    bid = reservation_price - δ/2
    ask = reservation_price + δ/2

Targets Kraken crypto pairs (continuous orderbook, 24/7 markets)
via the existing CryptoClient (CCXT).
"""

from __future__ import annotations

import asyncio
import os
import math
import time
from collections import deque
from typing import Any, Optional

import structlog

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient
from src.pnl_tracker import PnLTracker, Trade
from src.signal_bus import Signal, SignalBus, SignalType
from strategies.crypto.hawkes_process import HawkesOrderFlow
from strategies.crypto.inventory_manager import InventoryManager
from strategies.crypto.vpin import VPINCalculator

logger = structlog.get_logger(__name__)

# Default parameters matching the spec
DEFAULT_PAIRS = ["XRP/USDT"]
DEFAULT_RISK_AVERSION = 0.1
DEFAULT_SESSION_HORIZON = 3600  # 1 hour rolling window for 24/7 crypto
DEFAULT_VOLATILITY_WINDOW = 100  # last 100 mid-price changes
DEFAULT_MAX_INVENTORY = 10
DEFAULT_MIN_SPREAD_BPS = 5
DEFAULT_MAX_SPREAD_BPS = 200
DEFAULT_ORDER_SIZE_USDT = 10.0
DEFAULT_MAX_TOTAL_EXPOSURE = 50.0
DEFAULT_TICK_INTERVAL = 15.0
DEFAULT_FEE_BPS = 16.0  # Kraken maker fee per side
DEFAULT_MAX_DAILY_LOSS = -50.0
DEFAULT_SPREAD_FLOOR_BPS = 10.0  # never tighter than 0.1%
DEFAULT_CONSECUTIVE_FAIL_LIMIT = 3
DEFAULT_FAIL_PAUSE_SECONDS = 300.0  # 5 minutes


class AvellanedaMarketMaker:
    """Avellaneda-Stoikov optimal market making strategy.

    Flow per tick:
    1. Fetch orderbook → compute mid-price
    2. Update volatility estimate from mid-price changes
    3. Fetch recent trades → feed Hawkes + VPIN
    4. Compute reservation price (A-S + Hawkes adjustment)
    5. Compute optimal spread (A-S formula)
    6. Apply VPIN circuit breaker (spread/size multipliers)
    7. Apply inventory limits (clip sizes, skew if needed)
    8. Place bid and ask limit orders
    """

    def __init__(
        self,
        crypto_client: CryptoClient,
        signal_bus: SignalBus,
        pairs: list[str] | None = None,
        risk_aversion: float = DEFAULT_RISK_AVERSION,
        session_horizon_seconds: float = DEFAULT_SESSION_HORIZON,
        volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
        max_inventory: float = DEFAULT_MAX_INVENTORY,
        min_spread_bps: float = DEFAULT_MIN_SPREAD_BPS,
        max_spread_bps: float = DEFAULT_MAX_SPREAD_BPS,
        order_size_usdt: float = DEFAULT_ORDER_SIZE_USDT,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        fee_bps: float = DEFAULT_FEE_BPS,
        max_total_exposure: float = DEFAULT_MAX_TOTAL_EXPOSURE,
        pair_configs: dict[str, dict[str, float]] | None = None,
        hawkes_config: dict[str, Any] | None = None,
        vpin_config: dict[str, Any] | None = None,
        pnl_tracker: PnLTracker | None = None,
    ) -> None:
        self._client = crypto_client
        self._bus = signal_bus
        self._pairs = pairs or DEFAULT_PAIRS
        self._gamma = risk_aversion
        self._T = session_horizon_seconds
        self._vol_window = volatility_window
        self._min_spread_bps = min_spread_bps
        self._max_spread_bps = max_spread_bps
        self._order_size_usdt = order_size_usdt
        self._tick_interval = tick_interval
        self._fee_bps = fee_bps
        self._max_total_exposure = max_total_exposure
        self._pair_configs = pair_configs or {}

        # PnL tracker (optional — when provided, fills are recorded for dashboard)
        self._pnl = pnl_tracker

        # Per-pair state
        self._mid_prices: dict[str, deque[float]] = {
            pair: deque(maxlen=volatility_window) for pair in self._pairs
        }
        self._last_trade_fetch: dict[str, float] = {}
        self._last_fill_fetch: dict[str, float] = {}
        self._seen_fill_ids: set[str] = set()
        self._active_orders: dict[str, list[str]] = {pair: [] for pair in self._pairs}

        # Shared components (one per pair)
        hcfg = hawkes_config or {}
        vcfg = vpin_config or {}

        self._hawkes: dict[str, HawkesOrderFlow] = {
            pair: HawkesOrderFlow(
                mu=hcfg.get("mu", 1.0),
                alpha=hcfg.get("alpha", 0.5),
                beta=hcfg.get("beta", 2.0),
                window_seconds=hcfg.get("window_seconds", 300.0),
                sensitivity=hcfg.get("sensitivity", 0.5),
            )
            for pair in self._pairs
        }

        self._vpin: dict[str, VPINCalculator] = {
            pair: VPINCalculator(
                bucket_volume=vcfg.get("bucket_volume", 1000.0),
                num_buckets=vcfg.get("num_buckets", 50),
                warning_threshold=vcfg.get("warning_threshold", 0.4),
                danger_threshold=vcfg.get("danger_threshold", 0.6),
                critical_threshold=vcfg.get("critical_threshold", 0.8),
                cooldown_seconds=vcfg.get("cooldown_seconds", 60.0),
            )
            for pair in self._pairs
        }

        # Build per-pair USDT inventory limits from pair_configs
        pair_max_inventory_usdt: dict[str, float] = {}
        for pair, pcfg in self._pair_configs.items():
            if "max_inventory_usdt" in pcfg:
                pair_max_inventory_usdt[pair] = pcfg["max_inventory_usdt"]

        self._inventory = InventoryManager(
            max_inventory=max_inventory,
            pair_max_inventory_usdt=pair_max_inventory_usdt,
        )

        # Lifecycle
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._tick_count = 0
        self._started_at = 0.0

        # Safety guards
        self._max_position_usdt = float(os.environ.get("KRAKEN_MAX_POSITION", "500"))
        self._max_daily_loss = float(os.environ.get("KRAKEN_MAX_DAILY_LOSS", str(DEFAULT_MAX_DAILY_LOSS)))
        self._spread_floor_bps = DEFAULT_SPREAD_FLOOR_BPS
        self._daily_pnl: float = 0.0
        self._daily_pnl_halted: bool = False
        self._consecutive_failures: int = 0
        self._paused_until: float = 0.0

    async def start(self) -> None:
        """Start the market making loop."""
        if self._running:
            return

        # Ensure CCXT exchange is connected (load_markets) before ticks
        if self._client.exchange is None:
            connected = await self._client.connect()
            if not connected:
                logger.error(
                    "avellaneda_mm_connect_failed",
                    msg="Could not connect to exchange — aborting start",
                )
                return

        self._running = True
        self._started_at = time.time()

        # Sync inventory with actual exchange balances so manually
        # deposited or externally acquired assets are visible.
        await self._sync_exchange_inventory()

        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "avellaneda_mm_started",
            pairs=self._pairs,
            risk_aversion=self._gamma,
            max_inventory=self._inventory.max_inventory,
            order_size_usdt=self._order_size_usdt,
        )

    async def _sync_exchange_inventory(self) -> None:
        """Fetch actual balances from the exchange and seed the inventory manager.

        This ensures manually deposited or transferred assets are recognized
        so the bot can quote both buy and sell sides immediately.
        """
        if self._client.exchange is None or self._client.is_dry_run:
            return
        try:
            balance = await asyncio.get_event_loop().run_in_executor(
                None, self._client.exchange.fetch_balance
            )
            total = balance.get("total", {})
            for pair in self._pairs:
                base = pair.split("/")[0]  # e.g. "XRP" from "XRP/USDT"
                held = float(total.get(base, 0))
                if held > 0:
                    # Fetch current mid price for avg_entry estimate
                    try:
                        book = await self._client.get_orderbook(pair)
                        best_bid = float(book["bids"][0][0]) if book.get("bids") else 0
                        best_ask = float(book["asks"][0][0]) if book.get("asks") else 0
                        mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 0
                    except Exception:
                        mid = 0

                    pos = self._inventory.get_position(pair)
                    if pos.quantity == 0 and held > 0:
                        pos.quantity = held
                        pos.avg_entry_price = mid if mid > 0 else 0
                        pos.total_bought = held
                        logger.info(
                            "avellaneda_inventory_synced",
                            pair=pair,
                            coins=round(held, 6),
                            avg_price=round(mid, 6),
                        )
        except Exception as exc:
            logger.warning("avellaneda_inventory_sync_failed", error=str(exc))

    async def stop(self) -> None:
        """Stop the market making loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "avellaneda_mm_stopped",
            ticks=self._tick_count,
            inventory=self._inventory.status(),
        )

    @staticmethod
    def _crypto_trading_enabled() -> bool:
        """Returns True only if both Kraken guards are explicitly enabled."""
        mm = os.environ.get("KRAKEN_MM_ENABLED", "").lower() in {"1", "true", "yes"}
        ct = os.environ.get("CRYPTO_TRADING_ENABLED", "").lower() in {"1", "true", "yes"}
        return mm and ct

    async def _run_loop(self) -> None:
        """Main loop — calls _tick() for each pair on each interval."""
        while self._running:
            # Simulation guard: both KRAKEN_MM_ENABLED and CRYPTO_TRADING_ENABLED must be true
            if not self._crypto_trading_enabled():
                logger.info(
                    "crypto_disabled_skip",
                    strategy="avellaneda",
                    path="_run_loop",
                    reason="KRAKEN_MM_ENABLED and CRYPTO_TRADING_ENABLED must both be true",
                )
                await asyncio.sleep(self._tick_interval)
                continue

            # Daily loss circuit breaker
            if self._daily_pnl <= self._max_daily_loss and not self._daily_pnl_halted:
                self._daily_pnl_halted = True
                logger.warning(
                    "avellaneda_daily_loss_halt",
                    daily_pnl=round(self._daily_pnl, 2),
                    limit=self._max_daily_loss,
                )
            if self._daily_pnl_halted:
                await asyncio.sleep(60)
                continue

            # Consecutive failure pause
            if time.time() < self._paused_until:
                await asyncio.sleep(self._tick_interval)
                continue

            try:
                tick_ok = True
                for pair in self._pairs:
                    try:
                        await self._tick(pair)
                    except Exception as exc:
                        tick_ok = False
                        logger.warning(
                            "avellaneda_pair_tick_error",
                            pair=pair,
                            error=str(exc),
                            msg=f"Skipping {pair} this tick",
                        )

                if tick_ok:
                    self._consecutive_failures = 0
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= DEFAULT_CONSECUTIVE_FAIL_LIMIT:
                        self._paused_until = time.time() + DEFAULT_FAIL_PAUSE_SECONDS
                        logger.warning(
                            "avellaneda_consecutive_fail_pause",
                            failures=self._consecutive_failures,
                            pause_seconds=DEFAULT_FAIL_PAUSE_SECONDS,
                        )
                        self._consecutive_failures = 0

                self._tick_count += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("avellaneda_mm_error", error=str(exc))
            await asyncio.sleep(self._tick_interval)

    async def _fetch_my_fills(self, pair: str) -> None:
        """Fetch our own recent fills from Kraken and record them.

        Called each tick BEFORE cancelling stale orders so that any fills
        from the previous tick's limit orders are captured in the PnL
        tracker and inventory manager.
        """
        if self._client.exchange is None or self._client.is_dry_run:
            return  # dry_run fills are recorded immediately in _place_quote

        try:
            now_ms = int(time.time() * 1000)
            since_ms = int(self._last_fill_fetch.get(pair, self._started_at) * 1000)

            fills = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.exchange.fetch_my_trades(pair, since=since_ms, limit=50),
            )

            if not fills:
                self._last_fill_fetch[pair] = time.time()
                return

            new_count = 0
            for fill in fills:
                fill_id = str(fill.get("id", ""))
                if not fill_id or fill_id in self._seen_fill_ids:
                    continue

                self._seen_fill_ids.add(fill_id)
                side = fill.get("side", "")
                price = float(fill.get("price", 0))
                amount = float(fill.get("amount", 0))
                fee_info = fill.get("fee", {})
                fee_cost = float(fee_info.get("cost", 0)) if isinstance(fee_info, dict) else 0.0
                fill_ts = fill.get("timestamp", now_ms) / 1000.0

                if not side or price <= 0 or amount <= 0:
                    continue

                # Record to inventory manager (live fills with actual price)
                self._inventory.record_fill(pair, side, amount, price)

                # Record to PnL tracker
                if self._pnl is not None:
                    trade = Trade(
                        trade_id=fill_id,
                        timestamp=fill_ts,
                        market=pair,
                        token_id=pair,
                        side=side.upper(),
                        price=price,
                        size=amount,
                        fee=fee_cost,
                        strategy="avellaneda",
                    )
                    self._pnl.record_trade(trade)

                new_count += 1

            if new_count > 0:
                logger.info(
                    "avellaneda_fills_recorded",
                    pair=pair,
                    count=new_count,
                )

            self._last_fill_fetch[pair] = time.time()

        except Exception as exc:
            logger.warning("avellaneda_fetch_fills_error", pair=pair, error=str(exc))

    async def _cancel_stale_orders(self, pair: str) -> None:
        """Cancel all open orders for this pair before placing new quotes.

        Uses tracked order IDs first, then falls back to fetching open orders
        from the exchange to catch any we missed.
        """
        # Cancel tracked orders from previous tick
        tracked = self._active_orders.get(pair, [])
        for order_id in tracked:
            try:
                await self._client.cancel_order(order_id)
            except Exception:
                pass  # Order may have already filled or been cancelled

        self._active_orders[pair] = []

        # Also cancel any open orders on the exchange for this pair
        # (catches orders missed by tracking, e.g. after a restart)
        if self._client.exchange is not None and not self._client.is_dry_run:
            try:
                open_orders = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._client.exchange.fetch_open_orders(pair)
                )
                for order in open_orders:
                    try:
                        await self._client.cancel_order(order["id"])
                    except Exception:
                        pass
                if open_orders:
                    logger.info(
                        "cancelled_stale_orders",
                        pair=pair,
                        count=len(open_orders),
                    )
            except Exception as e:
                logger.warning("cancel_stale_orders_error", pair=pair, error=str(e))

    async def _tick(self, pair: str) -> None:
        """Execute one quoting cycle for a pair."""
        # 0a. Fetch fills from previous tick's orders before cancelling them
        await self._fetch_my_fills(pair)

        # 0b. Cancel all existing orders for this pair before placing new ones
        await self._cancel_stale_orders(pair)

        # 0c. Fetch REAL balances from exchange every tick
        base_currency, quote_currency = pair.split("/") if "/" in pair else (pair, "USD")
        free_base = 0.0
        free_quote = 0.0

        if self._client.exchange is not None and not self._client.is_dry_run:
            try:
                balance = await asyncio.get_event_loop().run_in_executor(
                    None, self._client.exchange.fetch_balance
                )
                free_base = float(balance.get("free", {}).get(base_currency, 0))
                free_quote = float(balance.get("free", {}).get(quote_currency, 0))
                total_base = float(balance.get("total", {}).get(base_currency, 0))

                # Sync inventory manager with real exchange balance
                pos = self._inventory.get_position(pair)
                pos.quantity = total_base

                logger.info(
                    "avellaneda_balance_sync",
                    pair=pair,
                    free_base=round(free_base, 6),
                    free_quote=round(free_quote, 4),
                    total_base=round(total_base, 6),
                )
            except Exception as exc:
                logger.warning("avellaneda_balance_fetch_error", pair=pair, error=str(exc))
                return  # Cannot quote without knowing real balances
        else:
            # Dry-run mode: use inventory manager values
            free_base = max(self._inventory.get_position(pair).quantity, 0)
            free_quote = 10000.0  # unlimited in dry-run

        # 1. Fetch orderbook → mid-price
        try:
            book = await self._client.get_orderbook(pair)
        except Exception as exc:
            logger.warning("avellaneda_orderbook_error", pair=pair, error=str(exc))
            return
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            logger.debug("avellaneda_no_book", pair=pair)
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0

        if mid <= 0:
            return

        # 2. Update mid-price history and compute volatility
        self._mid_prices[pair].append(mid)
        sigma = self._estimate_volatility(pair)
        if sigma is None:
            sigma = 0.0001  # default fallback, not used for spread calculation

        # 3. Feed recent trades into Hawkes + VPIN
        await self._process_recent_trades(pair)

        # 4. Compute reservation price — simple and safe
        inventory_coins = self._inventory.get_position(pair).quantity
        pcfg = self._pair_configs.get(pair, {})
        max_inventory_usdt = pcfg.get("max_inventory_usdt", self._max_total_exposure)
        max_inventory_coins = max_inventory_usdt / mid if mid > 0 else 1.0

        # inventory_ratio capped to [-1, 1]
        inventory_ratio = inventory_coins / max_inventory_coins if max_inventory_coins > 0 else 0.0
        inventory_ratio = max(-1.0, min(1.0, inventory_ratio))

        # Reservation price: mid with tiny inventory skew (max ±0.05% at full inventory)
        r = mid - (inventory_ratio * mid * 0.0005)

        # No Hawkes adjustment — disabled for stability
        r_adjusted = r

        logger.info(
            "avellaneda_inventory",
            pair=pair,
            coins=round(inventory_coins, 6),
            value_usd=round(inventory_coins * mid, 4),
            inventory_ratio=round(inventory_ratio, 4),
            r_offset_bps=round((r - mid) / mid * 10000, 2),
        )

        # 5. Compute spread — simple, bounded
        pair_max_bps = pcfg.get("max_spread_bps", self._max_spread_bps)
        spread = mid * (pair_max_bps / 10000.0)

        # 6. Apply VPIN circuit breaker — only halt at CRITICAL level (0.8+)
        vpin_val = self._vpin[pair].vpin
        vpin_action = self._vpin[pair]._evaluate()

        if vpin_val >= 0.8 and not vpin_action.should_quote:
            logger.info(
                "avellaneda_vpin_halt",
                pair=pair,
                vpin=round(vpin_val, 4),
                state=vpin_action.state.value,
            )
            return

        # Apply VPIN spread multiplier (widens spread under toxic flow)
        spread *= vpin_action.spread_multiplier

        # Enforce spread floor (never tighter than 0.1%)
        spread = max(spread, mid * (self._spread_floor_bps / 10000.0))
        # Cap final spread to 100bps max
        spread = min(spread, mid * 0.01)

        # 7. Compute quote prices
        bid_price = r_adjusted - spread / 2.0
        ask_price = r_adjusted + spread / 2.0

        # Sanity check: quotes must stay within 1% of mid
        if bid_price <= mid * 0.99 or ask_price >= mid * 1.01:
            logger.warning(
                "avellaneda_quote_sanity_fail",
                pair=pair,
                bid=round(bid_price, 8),
                ask=round(ask_price, 8),
                mid=round(mid, 8),
                bid_off_bps=round((mid - bid_price) / mid * 10000, 2),
                ask_off_bps=round((ask_price - mid) / mid * 10000, 2),
            )
            return

        if bid_price <= 0 or ask_price <= 0 or bid_price >= ask_price:
            return

        # 8. Compute order sizes from REAL free balances
        pair_order_usdt = pcfg.get("order_size_usdt", self._order_size_usdt)

        # Buy side: limited by free quote currency (USD)
        buy_size_usd = min(pair_order_usdt, free_quote * 0.95)
        buy_size_coins = buy_size_usd / bid_price if bid_price > 0 else 0

        # Sell side: limited by free base currency (e.g. XRP)
        sell_size_coins = min(pair_order_usdt / ask_price, free_base * 0.95) if ask_price > 0 else 0

        logger.info(
            "avellaneda_tick",
            pair=pair,
            mid=round(mid, 6),
            r=round(r_adjusted, 6),
            spread_bps=round(spread / mid * 10000, 2),
            bid=round(bid_price, 6),
            ask=round(ask_price, 6),
            buy_coins=round(buy_size_coins, 4),
            sell_coins=round(sell_size_coins, 4),
            free_base=round(free_base, 6),
            free_quote=round(free_quote, 4),
            vpin=round(vpin_val, 4),
        )

        # 9. Place orders — only if size meets Kraken minimum (1 coin for XRP)
        if buy_size_coins >= 1:
            await self._place_quote(pair, "buy", bid_price, buy_size_coins, mid, sigma, spread)

        if sell_size_coins >= 1:
            await self._place_quote(pair, "sell", ask_price, sell_size_coins, mid, sigma, spread)

        # 10. Publish signal for debate engine / monitoring
        await self._bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA,
            source="avellaneda_mm",
            data={
                "platform": "crypto",
                "pair": pair,
                "mid": round(mid, 8),
                "reservation_price": round(r_adjusted, 8),
                "optimal_spread": round(spread, 8),
                "bid": round(bid_price, 8),
                "ask": round(ask_price, 8),
                "inventory": round(inventory_coins, 6),
                "sigma": round(sigma, 8),
                "vpin": round(vpin_val, 4),
                "vpin_state": vpin_action.state.value,
                "hawkes_imbalance": round(self._hawkes[pair].imbalance(), 4),
            },
        ))

    async def _place_quote(
        self,
        pair: str,
        side: str,
        price: float,
        size: float,
        mid: float,
        sigma: float,
        spread: float,
    ) -> None:
        """Place a limit order quote."""
        order = Order(
            platform=self._client.platform_name,
            market_id=pair,
            side=side,
            size=round(size, 6),
            price=round(price, 8),
            order_type="limit",
        )

        try:
            # Belt-and-suspenders: refuse to place or record if crypto trading disabled
            if not self._crypto_trading_enabled():
                logger.info(
                    "crypto_disabled_skip",
                    strategy="avellaneda",
                    path="_place_quote",
                    pair=pair,
                    side=side,
                    reason="KRAKEN_MM_ENABLED and CRYPTO_TRADING_ENABLED must both be true",
                )
                return

            result = await self._client.place_order(order)
            order_id = result.get("id", "")

            # Track for potential cancellation on next tick
            self._active_orders[pair].append(order_id)

            # In dry-run mode, simulate immediate fill for both inventory and PnL.
            # In live mode, actual fills are recorded via _fetch_my_fills() each tick.
            if self._client.is_dry_run:
                self._inventory.record_fill(pair, side, size, price)
                if self._pnl is not None:
                    dry_trade = Trade(
                        trade_id=f"dry_{order_id}",
                        timestamp=time.time(),
                        market=pair,
                        token_id=pair,
                        side=side.upper(),
                        price=price,
                        size=size,
                        fee=price * size * (self._fee_bps / 10000.0),
                        strategy="avellaneda",
                    )
                    self._pnl.record_trade(dry_trade)

            estimated_fee = price * size * (self._fee_bps / 10000.0)
            logger.info(
                "avellaneda_quote",
                pair=pair,
                side=side,
                price=round(price, 8),
                size=round(size, 6),
                mid=round(mid, 8),
                spread_bps=round(spread / mid * 10000, 2),
                sigma=round(sigma, 8),
                estimated_fee=round(estimated_fee, 6),
            )
        except Exception as exc:
            logger.error("avellaneda_quote_error", pair=pair, side=side, error=str(exc))

    def _estimate_volatility(self, pair: str) -> float | None:
        """Estimate rolling volatility from mid-price returns.

        Uses standard deviation of log-returns over the volatility window.
        """
        prices = self._mid_prices[pair]
        if len(prices) < 3:
            return None

        # Compute log-returns
        returns = []
        price_list = list(prices)
        for i in range(1, len(price_list)):
            if price_list[i - 1] > 0 and price_list[i] > 0:
                returns.append(math.log(price_list[i] / price_list[i - 1]))

        if len(returns) < 2:
            return None

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)

    def _estimate_kappa(self, pair: str) -> float:
        """Estimate order arrival intensity κ from Hawkes process.

        Uses the sum of buy and sell intensities as a proxy for
        overall order arrival rate.
        """
        hawkes = self._hawkes[pair]
        kappa = hawkes.buy_intensity() + hawkes.sell_intensity()
        # Floor at baseline to avoid division by zero in spread formula
        return max(kappa, hawkes._buy_process.mu + hawkes._sell_process.mu)

    async def _process_recent_trades(self, pair: str) -> None:
        """Fetch recent trades and feed them into Hawkes + VPIN.

        Uses the CCXT exchange's fetch_trades method. Only processes
        trades that arrived since the last fetch.
        """
        if self._client.exchange is None:
            return

        try:
            since = self._last_trade_fetch.get(pair, 0)
            now = time.time()

            # Rate-limit trade fetching to at most once per tick
            if now - since < self._tick_interval * 0.8:
                return

            trades = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.exchange.fetch_trades(pair, limit=50),
            )

            if not trades:
                self._last_trade_fetch[pair] = now
                return

            since_ms = since * 1000
            for trade in trades:
                trade_ts = trade.get("timestamp", 0)
                if trade_ts and trade_ts <= since_ms:
                    continue

                trade_price = float(trade.get("price", 0))
                trade_amount = float(trade.get("amount", 0))
                trade_cost = float(trade.get("cost", 0)) or (trade_price * trade_amount)
                trade_side = trade.get("side", "")
                trade_time = trade_ts / 1000.0 if trade_ts else now

                # Feed Hawkes process
                if trade_side in ("buy", "sell"):
                    self._hawkes[pair].record_trade(trade_side, trade_time)

                # Feed VPIN calculator
                if trade_price > 0 and trade_cost > 0:
                    self._vpin[pair].record_trade(trade_price, trade_cost)

            self._last_trade_fetch[pair] = now

        except Exception as exc:
            logger.debug("avellaneda_trades_fetch_error", pair=pair, error=str(exc))

    def get_status(self) -> dict[str, Any]:
        """Return status for /kraken/status API endpoint."""
        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "uptime_seconds": round(time.time() - self._started_at) if self._started_at else 0,
            "pairs": self._pairs,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_pnl_halted": self._daily_pnl_halted,
            "consecutive_failures": self._consecutive_failures,
            "paused_until": self._paused_until,
            "max_position_usdt": self._max_position_usdt,
            "max_daily_loss": self._max_daily_loss,
            "spread_floor_bps": self._spread_floor_bps,
            "inventory": self._inventory.status(),
        }

    @property
    def status(self) -> dict[str, Any]:
        """Return current state for API / debugging."""
        pair_status = {}
        for pair in self._pairs:
            pair_status[pair] = {
                "mid_prices_collected": len(self._mid_prices[pair]),
                "hawkes": self._hawkes[pair].status(),
                "vpin": self._vpin[pair].status(),
                "inventory": round(self._inventory.inventory(pair), 6),
            }
        return {
            "name": "avellaneda_market_maker",
            "running": self._running,
            "tick_count": self._tick_count,
            "uptime_seconds": time.time() - self._started_at if self._started_at else 0,
            "risk_aversion": self._gamma,
            "session_horizon": self._T,
            "pairs": pair_status,
            "inventory": self._inventory.status(),
        }
