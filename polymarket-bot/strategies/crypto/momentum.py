"""Momentum Strategy — MACD + EMA crossover trend following for crypto.

Uses MACD (12/26/9) for entry signals confirmed by EMA 50/200 crossover
for major trend direction. Only trades in the direction of the 200-period
EMA trend with trailing stops based on ATR.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Optional

import structlog

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)


def _ema(data: list[float], period: int) -> list[float]:
    """Compute exponential moving average."""
    if len(data) < period:
        return []
    multiplier = 2.0 / (period + 1)
    ema_values = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def _macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict | None:
    """Compute MACD, signal line, and histogram."""
    if len(closes) < slow + signal:
        return None

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    # Align lengths
    offset = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[offset:]

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)

    offset2 = len(macd_line) - len(signal_line)
    macd_line = macd_line[offset2:]

    histogram = [m - s for m, s in zip(macd_line, signal_line)]

    return {
        "macd": macd_line[-1] if macd_line else 0,
        "signal": signal_line[-1] if signal_line else 0,
        "histogram": histogram[-1] if histogram else 0,
        "prev_histogram": histogram[-2] if len(histogram) >= 2 else 0,
    }


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Compute Average True Range."""
    if len(closes) < period + 1:
        return None
    true_ranges = []
    for i in range(-period, 0):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return sum(true_ranges) / period


class MomentumStrategy:
    """MACD + EMA crossover trend following strategy."""

    def __init__(
        self,
        crypto_client: CryptoClient,
        signal_bus: SignalBus,
        symbols: list[str] | None = None,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        ema_short: int = 50,
        ema_long: int = 200,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
        trade_amount_usd: float = 50.0,
        check_interval: float = 300.0,
    ) -> None:
        self._client = crypto_client
        self._bus = signal_bus
        self._symbols = symbols or ["XRP/USD", "XCN/USD"]
        self._macd_fast = macd_fast
        self._macd_slow = macd_slow
        self._macd_signal = macd_signal
        self._ema_short = ema_short
        self._ema_long = ema_long
        self._atr_period = atr_period
        self._atr_mult = atr_multiplier
        self._trade_amount = trade_amount_usd
        self._interval = check_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._active_trades: dict[str, dict] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("momentum_started", symbols=self._symbols)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while self._running:
            try:
                for symbol in self._symbols:
                    await self._analyze_symbol(symbol)
                await self._manage_trailing_stops()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("momentum_error", error=str(exc))
            await asyncio.sleep(self._interval)

    async def _analyze_symbol(self, symbol: str) -> None:
        """Analyze a symbol for momentum entry signals."""
        ohlcv = await self._client.fetch_ohlcv(symbol, "1h", limit=300)
        if not ohlcv or len(ohlcv) < self._ema_long + 10:
            return

        closes = [c[4] for c in ohlcv]
        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        current_price = closes[-1]

        # Compute EMA 50 and 200
        ema50 = _ema(closes, self._ema_short)
        ema200 = _ema(closes, self._ema_long)

        if not ema50 or not ema200:
            return

        # Determine major trend from EMA 200
        bullish_trend = current_price > ema200[-1]
        ema_crossover = ema50[-1] > ema200[-1]

        # Compute MACD
        macd_data = _macd(closes, self._macd_fast, self._macd_slow, self._macd_signal)
        if macd_data is None:
            return

        # Compute ATR for trailing stop
        atr_val = _atr(highs, lows, closes, self._atr_period)

        # Entry signals
        macd_cross_up = macd_data["prev_histogram"] < 0 and macd_data["histogram"] > 0
        macd_cross_down = macd_data["prev_histogram"] > 0 and macd_data["histogram"] < 0

        if macd_cross_up and bullish_trend and ema_crossover:
            # Bullish entry
            if symbol not in self._active_trades:
                await self._enter_trade(symbol, "buy", current_price, atr_val, macd_data)

        elif macd_cross_down and not bullish_trend and not ema_crossover:
            # Bearish entry
            if symbol not in self._active_trades:
                await self._enter_trade(symbol, "sell", current_price, atr_val, macd_data)

        elif macd_cross_down and symbol in self._active_trades and self._active_trades[symbol]["side"] == "buy":
            # Exit long on bearish MACD crossover
            await self._exit_trade(symbol, current_price, "macd_cross_exit")

        elif macd_cross_up and symbol in self._active_trades and self._active_trades[symbol]["side"] == "sell":
            # Exit short on bullish MACD crossover
            await self._exit_trade(symbol, current_price, "macd_cross_exit")

    async def _enter_trade(
        self, symbol: str, side: str, price: float, atr: float | None, macd_data: dict
    ) -> None:
        """Enter a momentum trade with ATR-based trailing stop."""
        size = self._trade_amount / price
        order = Order(
            platform=self._client.platform_name,
            market_id=symbol,
            side=side,
            size=round(size, 6),
            price=price,
            order_type="market",
        )
        result = await self._client.place_order(order)

        trailing_distance = (atr or price * 0.02) * self._atr_mult
        if side == "buy":
            stop_price = price - trailing_distance
        else:
            stop_price = price + trailing_distance

        self._active_trades[symbol] = {
            "entry_price": price,
            "side": side,
            "size": size,
            "order_id": result.get("id", ""),
            "entered_at": time.time(),
            "trailing_stop": stop_price,
            "trailing_distance": trailing_distance,
            "highest_price": price if side == "buy" else None,
            "lowest_price": price if side == "sell" else None,
        }

        logger.info(
            "momentum_entry",
            symbol=symbol,
            side=side,
            price=price,
            trailing_stop=round(stop_price, 6),
            macd=round(macd_data["macd"], 6),
        )

        await self._bus.publish(Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="momentum",
            data={
                "platform": "crypto",
                "symbol": symbol,
                "side": side,
                "price": price,
                "macd": macd_data["macd"],
                "trailing_stop": stop_price,
            },
        ))

    async def _exit_trade(self, symbol: str, price: float, reason: str) -> None:
        """Exit an active trade."""
        trade = self._active_trades.get(symbol)
        if not trade:
            return

        exit_side = "sell" if trade["side"] == "buy" else "buy"
        await self._client.place_order(Order(
            platform=self._client.platform_name,
            market_id=symbol,
            side=exit_side,
            size=round(trade["size"], 6),
            price=price,
            order_type="market",
        ))

        entry = trade["entry_price"]
        pnl_pct = ((price - entry) / entry) if trade["side"] == "buy" else ((entry - price) / entry)

        logger.info(
            "momentum_exit",
            symbol=symbol,
            reason=reason,
            pnl_pct=round(pnl_pct, 4),
        )
        del self._active_trades[symbol]

    async def _manage_trailing_stops(self) -> None:
        """Update trailing stops and check for stop-loss exits."""
        for symbol in list(self._active_trades.keys()):
            trade = self._active_trades[symbol]
            try:
                ticker = await self._client.fetch_ticker(symbol)
                if not ticker or "last" not in ticker:
                    continue

                current = float(ticker["last"])
                side = trade["side"]
                distance = trade["trailing_distance"]

                if side == "buy":
                    # Update highest price and trail stop upward
                    if trade["highest_price"] is None or current > trade["highest_price"]:
                        trade["highest_price"] = current
                        trade["trailing_stop"] = current - distance

                    # Check if stop hit
                    if current <= trade["trailing_stop"]:
                        await self._exit_trade(symbol, current, "trailing_stop")

                else:  # sell
                    # Update lowest price and trail stop downward
                    if trade["lowest_price"] is None or current < trade["lowest_price"]:
                        trade["lowest_price"] = current
                        trade["trailing_stop"] = current + distance

                    if current >= trade["trailing_stop"]:
                        await self._exit_trade(symbol, current, "trailing_stop")

            except Exception as exc:
                logger.error("momentum_trailing_stop_error", symbol=symbol, error=str(exc))
