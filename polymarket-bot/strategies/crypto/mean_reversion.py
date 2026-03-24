"""Mean Reversion Strategy — Bollinger Bands + RSI for crypto spot trading.

Identifies oversold and overbought conditions using:
- 20-period Bollinger Bands (2 standard deviations)
- 14-period RSI (Relative Strength Index)

BUY when: price < lower band AND RSI < 30 (oversold)
SELL when: price > upper band AND RSI > 70 (overbought)
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

# Default parameters
DEFAULT_BB_PERIOD = 20
DEFAULT_BB_STD_DEV = 2.0
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 30
DEFAULT_RSI_OVERBOUGHT = 70


def _compute_bollinger(closes: list[float], period: int = 20, num_std: float = 2.0) -> dict | None:
    """Compute Bollinger Bands from closing prices."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = math.sqrt(variance)
    return {
        "middle": sma,
        "upper": sma + num_std * std,
        "lower": sma - num_std * std,
        "std": std,
    }


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI from closing prices."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(-period, 0):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class MeanReversionStrategy:
    """Bollinger Bands + RSI mean reversion strategy for crypto."""

    def __init__(
        self,
        crypto_client: CryptoClient,
        signal_bus: SignalBus,
        symbols: list[str] | None = None,
        bb_period: int = DEFAULT_BB_PERIOD,
        bb_std_dev: float = DEFAULT_BB_STD_DEV,
        rsi_period: int = DEFAULT_RSI_PERIOD,
        rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
        rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
        trade_amount_usd: float = 50.0,
        check_interval: float = 60.0,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.04,
    ) -> None:
        self._client = crypto_client
        self._bus = signal_bus
        self._symbols = symbols or ["XRP/USD", "XCN/USD"]
        self._bb_period = bb_period
        self._bb_std = bb_std_dev
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._trade_amount = trade_amount_usd
        self._interval = check_interval
        self._stop_loss = stop_loss_pct
        self._take_profit = take_profit_pct
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._active_trades: dict[str, dict] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("mean_reversion_started", symbols=self._symbols)

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
                await self._manage_exits()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("mean_reversion_error", error=str(exc))
            await asyncio.sleep(self._interval)

    async def _analyze_symbol(self, symbol: str) -> None:
        """Analyze a symbol for mean reversion signals."""
        # Fetch 1h OHLCV candles
        ohlcv = await self._client.fetch_ohlcv(symbol, "1h", limit=200)
        if not ohlcv or len(ohlcv) < self._bb_period + 1:
            return

        closes = [candle[4] for candle in ohlcv]  # close prices
        current_price = closes[-1]

        # Compute indicators
        bb = _compute_bollinger(closes, self._bb_period, self._bb_std)
        rsi = _compute_rsi(closes, self._rsi_period)

        if bb is None or rsi is None:
            return

        # Check for signals
        if current_price < bb["lower"] and rsi < self._rsi_oversold:
            # OVERSOLD — BUY signal
            if symbol not in self._active_trades:
                await self._enter_trade(symbol, "buy", current_price, rsi, bb)

        elif current_price > bb["upper"] and rsi > self._rsi_overbought:
            # OVERBOUGHT — SELL signal (close long or short)
            if symbol in self._active_trades and self._active_trades[symbol]["side"] == "buy":
                await self._exit_trade(symbol, current_price, "overbought_signal")
            elif symbol not in self._active_trades:
                await self._enter_trade(symbol, "sell", current_price, rsi, bb)

    async def _enter_trade(
        self, symbol: str, side: str, price: float, rsi: float, bb: dict
    ) -> None:
        """Enter a mean reversion trade."""
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

        self._active_trades[symbol] = {
            "entry_price": price,
            "side": side,
            "size": size,
            "order_id": result.get("id", ""),
            "entered_at": time.time(),
            "rsi_at_entry": rsi,
        }

        logger.info(
            "mean_reversion_entry",
            symbol=symbol,
            side=side,
            price=price,
            rsi=round(rsi, 2),
            bb_lower=round(bb["lower"], 6),
            bb_upper=round(bb["upper"], 6),
        )

        await self._bus.publish(Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="mean_reversion",
            data={
                "platform": "crypto",
                "symbol": symbol,
                "side": side,
                "price": price,
                "rsi": round(rsi, 2),
                "bb_lower": round(bb["lower"], 6),
                "bb_upper": round(bb["upper"], 6),
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
        if trade["side"] == "buy":
            pnl_pct = (price - entry) / entry
        else:
            pnl_pct = (entry - price) / entry

        logger.info(
            "mean_reversion_exit",
            symbol=symbol,
            reason=reason,
            pnl_pct=round(pnl_pct, 4),
        )
        del self._active_trades[symbol]

    async def _manage_exits(self) -> None:
        """Check active trades for stop-loss and take-profit."""
        for symbol in list(self._active_trades.keys()):
            trade = self._active_trades[symbol]
            try:
                ticker = await self._client.fetch_ticker(symbol)
                if not ticker or "last" not in ticker:
                    continue

                current = float(ticker["last"])
                entry = trade["entry_price"]
                side = trade["side"]

                pnl_pct = ((current - entry) / entry) if side == "buy" else ((entry - current) / entry)

                if pnl_pct >= self._take_profit:
                    await self._exit_trade(symbol, current, "take_profit")
                elif pnl_pct <= -self._stop_loss:
                    await self._exit_trade(symbol, current, "stop_loss")
            except Exception as exc:
                logger.error("mean_reversion_exit_check_error", symbol=symbol, error=str(exc))
