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
import math
import time
from collections import deque
from typing import Any, Optional

import structlog

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient
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

        # Per-pair state
        self._mid_prices: dict[str, deque[float]] = {
            pair: deque(maxlen=volatility_window) for pair in self._pairs
        }
        self._last_trade_fetch: dict[str, float] = {}
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

    async def start(self) -> None:
        """Start the market making loop."""
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "avellaneda_mm_started",
            pairs=self._pairs,
            risk_aversion=self._gamma,
            max_inventory=self._inventory.max_inventory,
            order_size_usdt=self._order_size_usdt,
        )

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

    async def _run_loop(self) -> None:
        """Main loop — calls _tick() for each pair on each interval."""
        while self._running:
            try:
                for pair in self._pairs:
                    try:
                        await self._tick(pair)
                    except Exception as exc:
                        logger.warning(
                            "avellaneda_pair_tick_error",
                            pair=pair,
                            error=str(exc),
                            msg=f"Skipping {pair} this tick",
                        )
                self._tick_count += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("avellaneda_mm_error", error=str(exc))
            await asyncio.sleep(self._tick_interval)

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
        # 0. Cancel all existing orders for this pair before placing new ones
        await self._cancel_stale_orders(pair)

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
        if sigma is None or sigma == 0:
            return  # not enough data yet

        # 3. Feed recent trades into Hawkes + VPIN
        await self._process_recent_trades(pair)

        # 4. Compute reservation price
        q = self._inventory.inventory(pair)
        tau = self._T  # rolling horizon for 24/7 crypto
        r = mid - q * self._gamma * (sigma ** 2) * tau

        # Apply Hawkes order flow adjustment
        hawkes_adj = self._hawkes[pair].reservation_price_adjustment()
        r_adjusted = r + hawkes_adj * mid  # scale by mid-price

        # 5. Compute optimal spread
        kappa = self._estimate_kappa(pair)
        delta = self._gamma * (sigma ** 2) * tau
        if self._gamma > 0 and kappa > 0:
            delta += (2.0 / self._gamma) * math.log(1.0 + self._gamma / kappa)

        # 6. Apply spread bounds (per-pair overrides or global fallback)
        pcfg = self._pair_configs.get(pair, {})
        pair_min_bps = pcfg.get("min_spread_bps", self._min_spread_bps)
        pair_max_bps = pcfg.get("max_spread_bps", self._max_spread_bps)

        # Fee-aware floor: spread must exceed round-trip fees to be profitable
        min_profitable_spread = mid * (2.0 * self._fee_bps / 10000.0)
        min_spread = max(mid * (pair_min_bps / 10000.0), min_profitable_spread)
        max_spread = mid * (pair_max_bps / 10000.0)
        delta = max(min_spread, min(delta, max_spread))

        # 7. Apply VPIN circuit breaker
        vpin_action = self._vpin[pair]._evaluate()
        if not vpin_action.should_quote:
            logger.info(
                "avellaneda_vpin_halt",
                pair=pair,
                vpin=round(self._vpin[pair].vpin, 4),
                state=vpin_action.state.value,
            )
            return

        delta *= vpin_action.spread_multiplier

        # 8. Compute quote prices
        bid_price = r_adjusted - delta / 2.0
        ask_price = r_adjusted + delta / 2.0

        # Sanity: bid must be below ask, both must be positive
        if bid_price <= 0 or ask_price <= 0 or bid_price >= ask_price:
            logger.debug(
                "avellaneda_invalid_quotes",
                pair=pair,
                bid=round(bid_price, 8),
                ask=round(ask_price, 8),
            )
            return

        # 9. Compute order sizes (per-pair USDT amount or global fallback)
        pair_order_usdt = pcfg.get("order_size_usdt", self._order_size_usdt)
        base_size = pair_order_usdt / mid
        base_size *= vpin_action.size_multiplier

        bid_size = self._inventory.bid_size_limit(pair, base_size, mid)
        ask_size = self._inventory.ask_size_limit(pair, base_size, mid)

        # 10. Exposure limit check — skip if total open value would exceed max
        total_open_value = sum(
            abs(self._inventory.inventory(p)) * (self._mid_prices[p][-1] if self._mid_prices[p] else 0)
            for p in self._pairs
        )

        # 11. Fetch balance for pre-order checks
        balance_data = await self._client.get_balance()
        free_balance = balance_data.get("free", {})

        # Determine quote currency and base currency from pair (e.g. "XRP/USDT")
        base_currency, quote_currency = pair.split("/") if "/" in pair else (pair, "USDT")

        # 12. Place at most ONE buy and ONE sell per pair per tick
        if bid_size > 0 and self._inventory.can_quote_bid(pair, mid):
            if total_open_value + (bid_size * bid_price) > self._max_total_exposure:
                logger.debug("exposure_limit_skip", pair=pair, side="buy", current=round(total_open_value, 2), max=self._max_total_exposure)
            else:
                # Check free quote currency balance before buying
                free_quote = float(free_balance.get(quote_currency, 0))
                order_cost = bid_size * bid_price
                if free_quote < order_cost:
                    logger.debug(
                        "insufficient_free_balance",
                        pair=pair,
                        side="buy",
                        free=round(free_quote, 4),
                        needed=round(order_cost, 4),
                    )
                else:
                    await self._place_quote(pair, "buy", bid_price, bid_size, mid, sigma, delta)

        if ask_size > 0 and self._inventory.can_quote_ask(pair, mid):
            if total_open_value + (ask_size * ask_price) > self._max_total_exposure:
                logger.debug("exposure_limit_skip", pair=pair, side="sell", current=round(total_open_value, 2), max=self._max_total_exposure)
            else:
                # Check free base currency balance before selling
                free_base = float(free_balance.get(base_currency, 0))
                if free_base < ask_size:
                    logger.debug(
                        "insufficient_free_balance",
                        pair=pair,
                        side="sell",
                        free=round(free_base, 6),
                        needed=round(ask_size, 6),
                    )
                else:
                    await self._place_quote(pair, "sell", ask_price, ask_size, mid, sigma, delta)

        # 11. Publish signal for debate engine / monitoring
        await self._bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA,
            source="avellaneda_mm",
            data={
                "platform": "crypto",
                "pair": pair,
                "mid": round(mid, 8),
                "reservation_price": round(r_adjusted, 8),
                "optimal_spread": round(delta, 8),
                "bid": round(bid_price, 8),
                "ask": round(ask_price, 8),
                "inventory": round(q, 6),
                "sigma": round(sigma, 8),
                "vpin": round(self._vpin[pair].vpin, 4),
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
            result = await self._client.place_order(order)
            order_id = result.get("id", "")

            # Track for potential cancellation on next tick
            self._active_orders[pair].append(order_id)

            # Record fill in inventory (for paper trading, market orders fill immediately;
            # for limit orders in dry-run mode, simulate immediate fill)
            if self._client.is_dry_run:
                self._inventory.record_fill(pair, side, size, price)

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
