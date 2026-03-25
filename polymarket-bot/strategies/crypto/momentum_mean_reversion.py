"""Momentum / Mean-Reversion Hybrid Strategy for crypto spot trading.

Designed for Kraken XRP/USD where native spreads are ~0.07 bps but maker
fees are 16 bps/side, making spread-capture strategies unprofitable.
Instead we buy dips and sell rips — profiting from price movement, not
spread capture.  Uses **market orders** (taker, ~26 bps on Kraken) for
instant fills.

Signal logic
────────────
1. 15-minute rolling VWAP from ``fetch_trades``
2. Fast EMA(5) / Slow EMA(20) on 1-minute candle closes (built from trades)
3. **Buy**:  price > 0.3 % below VWAP  AND  fast EMA < slow EMA  (mean-rev entry)
4. **Sell**: price > 0.3 % above VWAP  AND  we hold inventory  AND
             (fast EMA > slow EMA  OR  position PnL > +0.2 %)
5. **Stop-loss**: position drops > 0.5 % from entry → immediate market sell
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Any, Optional

import structlog

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient
from src.pnl_tracker import PnLTracker, Trade
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)

# Kraken taker fee (used for PnL estimation)
TAKER_FEE_BPS = 26  # 0.26 %


# ── Indicator helpers ───────────────────────────────────────────────────────

def _compute_vwap(trades: list[dict], window_seconds: float) -> Optional[float]:
    """Volume-weighted average price over the last *window_seconds*."""
    now_ms = time.time() * 1000
    cutoff_ms = now_ms - window_seconds * 1000
    total_pv = 0.0
    total_v = 0.0
    for t in trades:
        ts = t.get("timestamp", 0)
        if ts < cutoff_ms:
            continue
        price = float(t["price"])
        amount = float(t["amount"])
        total_pv += price * amount
        total_v += amount
    if total_v == 0:
        return None
    return total_pv / total_v


def _trades_to_1m_candles(trades: list[dict]) -> list[float]:
    """Bucket trades into 1-minute candle closes, oldest first."""
    if not trades:
        return []
    buckets: dict[int, float] = {}  # minute_ts -> last price
    for t in trades:
        ts_sec = t.get("timestamp", 0) / 1000.0
        bucket = int(ts_sec // 60) * 60
        buckets[bucket] = float(t["price"])
    if not buckets:
        return []
    return [buckets[k] for k in sorted(buckets)]


def _ema(values: list[float], period: int) -> list[float]:
    """Compute exponential moving average; returns list aligned to *values*."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    # Pad leading entries with None-equivalent (we only care about tail)
    return result


# ── Strategy ────────────────────────────────────────────────────────────────

class MomentumMeanReversion:
    """Buy-the-dip / sell-the-rip hybrid using VWAP + EMA crossover."""

    def __init__(
        self,
        crypto_client: CryptoClient,
        signal_bus: SignalBus,
        pairs: list[str] | None = None,
        order_size_usd: float = 50.0,
        tick_interval: float = 15.0,
        vwap_window_minutes: float = 15.0,
        ema_fast: int = 5,
        ema_slow: int = 20,
        buy_dip_pct: float = 0.003,
        sell_rip_pct: float = 0.003,
        take_profit_pct: float = 0.002,
        stop_loss_pct: float = 0.005,
        max_trades_per_hour: int = 10,
        max_inventory_usd: float = 500.0,
        pnl_tracker: PnLTracker | None = None,
    ) -> None:
        self._client = crypto_client
        self._bus = signal_bus
        self._pairs = pairs or ["XRP/USD"]
        self._order_size_usd = order_size_usd
        self._tick_interval = tick_interval
        self._vwap_window_sec = vwap_window_minutes * 60
        self._ema_fast = ema_fast
        self._ema_slow = ema_slow
        self._buy_dip_pct = buy_dip_pct
        self._sell_rip_pct = sell_rip_pct
        self._take_profit_pct = take_profit_pct
        self._stop_loss_pct = stop_loss_pct
        self._max_trades_per_hour = max_trades_per_hour
        self._max_inventory_usd = max_inventory_usd
        self._pnl_tracker = pnl_tracker

        # Runtime state
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Per-pair position tracking: pair -> {entry_price, size, side, entered_at}
        self._positions: dict[str, dict[str, Any]] = {}

        # Rate-limit tracking: deque of trade timestamps (epoch seconds)
        self._trade_timestamps: deque[float] = deque()
        self._last_trade_time: float = 0.0  # absolute epoch of last trade

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "momentum_mr_started",
            pairs=self._pairs,
            order_size_usd=self._order_size_usd,
            tick_interval=self._tick_interval,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("momentum_mr_stopped")

    async def _run_loop(self) -> None:
        while self._running:
            for pair in self._pairs:
                try:
                    await self._tick(pair)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("momentum_mr_tick_error", pair=pair, error=str(exc))
            try:
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break

    # ── Main tick ────────────────────────────────────────────────────────

    async def _tick(self, pair: str) -> None:
        loop = asyncio.get_event_loop()

        # 1. Fetch balance (same pattern as other strategies — run_in_executor)
        try:
            balance_data = await loop.run_in_executor(
                None, self._client.exchange.fetch_balance
            )
        except Exception as exc:
            logger.warning("momentum_mr_balance_error", pair=pair, error=str(exc))
            balance_data = {}

        # 2. Fetch recent trades from exchange
        try:
            raw_trades: list[dict] = await loop.run_in_executor(
                None,
                lambda: self._client.exchange.fetch_trades(pair, limit=200),
            )
        except Exception as exc:
            logger.warning("momentum_mr_fetch_trades_error", pair=pair, error=str(exc))
            return

        if not raw_trades or len(raw_trades) < 20:
            logger.debug("momentum_mr_tick", pair=pair, msg="insufficient trades")
            return

        # 3. Compute 15-min VWAP
        vwap = _compute_vwap(raw_trades, self._vwap_window_sec)
        if vwap is None or vwap <= 0:
            return

        # 4. Compute fast/slow EMA from 1-min candle closes
        candle_closes = _trades_to_1m_candles(raw_trades)
        ema_fast_vals = _ema(candle_closes, self._ema_fast)
        ema_slow_vals = _ema(candle_closes, self._ema_slow)

        if not ema_fast_vals or not ema_slow_vals:
            logger.debug(
                "momentum_mr_tick",
                pair=pair,
                msg="not enough candles for EMA",
                candles=len(candle_closes),
                need=self._ema_slow,
            )
            return

        fast_ema = ema_fast_vals[-1]
        slow_ema = ema_slow_vals[-1]
        last_price = float(raw_trades[-1]["price"])

        # Deviation from VWAP
        vwap_dev = (last_price - vwap) / vwap  # positive = above VWAP

        logger.info(
            "momentum_mr_tick",
            pair=pair,
            price=round(last_price, 6),
            vwap=round(vwap, 6),
            vwap_dev_pct=round(vwap_dev * 100, 4),
            fast_ema=round(fast_ema, 6),
            slow_ema=round(slow_ema, 6),
            has_position=pair in self._positions,
        )

        pos = self._positions.get(pair)

        # 5. Check stop loss first (urgent)
        if pos is not None:
            pnl_pct = (last_price - pos["entry_price"]) / pos["entry_price"]
            if pnl_pct <= -self._stop_loss_pct:
                logger.warning(
                    "momentum_mr_stop_loss",
                    pair=pair,
                    entry=pos["entry_price"],
                    price=last_price,
                    pnl_pct=round(pnl_pct * 100, 4),
                )
                await self._sell(pair, pos, last_price, reason="stop_loss")
                return

        # 6. Check sell signal (take profit / rip exit)
        if pos is not None:
            pnl_pct = (last_price - pos["entry_price"]) / pos["entry_price"]
            ema_cross_up = fast_ema > slow_ema
            above_vwap = vwap_dev > self._sell_rip_pct
            take_profit = pnl_pct >= self._take_profit_pct

            if above_vwap and (ema_cross_up or take_profit):
                reason = "take_profit" if take_profit else "sell_signal"
                logger.info(
                    "momentum_mr_sell_signal",
                    pair=pair,
                    entry=pos["entry_price"],
                    price=last_price,
                    pnl_pct=round(pnl_pct * 100, 4),
                    vwap_dev_pct=round(vwap_dev * 100, 4),
                    ema_cross_up=ema_cross_up,
                    take_profit=take_profit,
                )
                await self._sell(pair, pos, last_price, reason=reason)
                return

        # 7. Check buy signal (dip entry)
        if pos is None:
            below_vwap = vwap_dev < -self._buy_dip_pct
            ema_cross_down = fast_ema < slow_ema

            if below_vwap and ema_cross_down:
                logger.info(
                    "momentum_mr_buy_signal",
                    pair=pair,
                    price=last_price,
                    vwap=round(vwap, 6),
                    vwap_dev_pct=round(vwap_dev * 100, 4),
                    fast_ema=round(fast_ema, 6),
                    slow_ema=round(slow_ema, 6),
                )
                await self._buy(pair, last_price)

    # ── Order execution ─────────────────────────────────────────────────

    def _can_trade(self) -> bool:
        """Enforce rate limits: max N trades/hour and min 60 s between trades."""
        now = time.time()

        # Min 60s between trades
        if now - self._last_trade_time < 60:
            return False

        # Prune old timestamps (> 1 hour)
        while self._trade_timestamps and self._trade_timestamps[0] < now - 3600:
            self._trade_timestamps.popleft()

        if len(self._trade_timestamps) >= self._max_trades_per_hour:
            return False

        return True

    def _record_trade_time(self) -> None:
        now = time.time()
        self._trade_timestamps.append(now)
        self._last_trade_time = now

    async def _buy(self, pair: str, price: float) -> None:
        if not self._can_trade():
            logger.debug("momentum_mr_rate_limited", pair=pair, action="buy")
            return

        # Check max inventory
        total_inventory = sum(
            p["size"] * p["entry_price"] for p in self._positions.values()
        )
        if total_inventory >= self._max_inventory_usd:
            logger.debug("momentum_mr_max_inventory", pair=pair, total=total_inventory)
            return

        size_coins = self._order_size_usd / price

        order = Order(
            platform=self._client.platform_name,
            market_id=pair,
            side="buy",
            size=round(size_coins, 6),
            price=0,  # market order
            order_type="market",
        )

        try:
            result = await self._client.place_order(order)
        except Exception as exc:
            logger.error("momentum_mr_buy_error", pair=pair, error=str(exc))
            return

        self._record_trade_time()

        # Record position
        self._positions[pair] = {
            "entry_price": price,
            "size": size_coins,
            "entered_at": time.time(),
            "order_id": result.get("id", ""),
        }

        logger.info(
            "momentum_mr_trade",
            pair=pair,
            side="buy",
            size=round(size_coins, 6),
            price=price,
            order_id=result.get("id", ""),
        )

        # Publish signal
        await self._bus.publish(Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="momentum_mr",
            platform="crypto",
            data={
                "platform": "crypto",
                "symbol": pair,
                "side": "buy",
                "price": price,
                "size": size_coins,
                "strategy": "momentum_mr",
            },
        ))

        # Record fill in PnL tracker
        await self._record_fill(pair, "BUY", price, size_coins, result)

    async def _sell(self, pair: str, pos: dict, price: float, reason: str) -> None:
        if not self._can_trade() and reason != "stop_loss":
            logger.debug("momentum_mr_rate_limited", pair=pair, action="sell")
            return

        size_coins = pos["size"]

        order = Order(
            platform=self._client.platform_name,
            market_id=pair,
            side="sell",
            size=round(size_coins, 6),
            price=0,  # market order
            order_type="market",
        )

        try:
            result = await self._client.place_order(order)
        except Exception as exc:
            logger.error("momentum_mr_sell_error", pair=pair, error=str(exc))
            return

        self._record_trade_time()

        entry = pos["entry_price"]
        pnl_pct = (price - entry) / entry
        # Account for taker fee on both legs
        fee_pct = TAKER_FEE_BPS * 2 / 10_000
        net_pnl_pct = pnl_pct - fee_pct

        logger.info(
            "momentum_mr_trade",
            pair=pair,
            side="sell",
            size=round(size_coins, 6),
            price=price,
            entry=entry,
            pnl_pct=round(pnl_pct * 100, 4),
            net_pnl_pct=round(net_pnl_pct * 100, 4),
            reason=reason,
            order_id=result.get("id", ""),
        )

        # Remove position
        self._positions.pop(pair, None)

        # Publish signal
        await self._bus.publish(Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="momentum_mr",
            platform="crypto",
            data={
                "platform": "crypto",
                "symbol": pair,
                "side": "sell",
                "price": price,
                "size": size_coins,
                "reason": reason,
                "pnl_pct": pnl_pct,
                "strategy": "momentum_mr",
            },
        ))

        # Record fill in PnL tracker
        await self._record_fill(pair, "SELL", price, size_coins, result)

    async def _record_fill(
        self,
        pair: str,
        side: str,
        price: float,
        size: float,
        order_result: dict,
    ) -> None:
        """Confirm the fill via fetch_my_trades and record in PnL tracker."""
        if self._pnl_tracker is None:
            return

        # Try to fetch the actual fill from the exchange
        fill_price = price
        fill_fee = 0.0
        try:
            loop = asyncio.get_event_loop()
            order_id = order_result.get("id", "")
            if order_id and self._client.exchange:
                my_trades = await loop.run_in_executor(
                    None,
                    lambda: self._client.exchange.fetch_my_trades(pair, limit=5),
                )
                # Find the trade matching our order
                for mt in reversed(my_trades):
                    if mt.get("order") == order_id:
                        fill_price = float(mt.get("price", price))
                        fee_info = mt.get("fee", {})
                        fill_fee = float(fee_info.get("cost", 0)) if fee_info else 0.0
                        break
        except Exception as exc:
            logger.debug("momentum_mr_fetch_fill_error", error=str(exc))

        trade = Trade(
            trade_id=order_result.get("id", f"mmr-{uuid.uuid4().hex[:12]}"),
            timestamp=time.time(),
            market=pair,
            token_id=pair,
            side=side,
            price=fill_price,
            size=size,
            fee=fill_fee,
            strategy="momentum_mr",
        )
        self._pnl_tracker.record_trade(trade)

    # ── Status ──────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "name": "momentum_mean_reversion",
            "running": self._running,
            "pairs": self._pairs,
            "positions": {
                pair: {
                    "entry_price": p["entry_price"],
                    "size": p["size"],
                    "age_seconds": round(time.time() - p["entered_at"]),
                }
                for pair, p in self._positions.items()
            },
            "trades_last_hour": len(self._trade_timestamps),
            "config": {
                "order_size_usd": self._order_size_usd,
                "tick_interval": self._tick_interval,
                "vwap_window_sec": self._vwap_window_sec,
                "ema_fast": self._ema_fast,
                "ema_slow": self._ema_slow,
                "buy_dip_pct": self._buy_dip_pct,
                "sell_rip_pct": self._sell_rip_pct,
                "take_profit_pct": self._take_profit_pct,
                "stop_loss_pct": self._stop_loss_pct,
                "max_trades_per_hour": self._max_trades_per_hour,
                "max_inventory_usd": self._max_inventory_usd,
            },
        }
