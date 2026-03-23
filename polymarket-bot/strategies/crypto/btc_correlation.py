"""BTC Correlation Strategy — adapted from latency_detector for crypto.

Core insight: When BTC moves >0.11% on Binance within seconds, altcoins
on other exchanges follow with a 9-16 second delay. This strategy monitors
BTC momentum and trades correlated alts during that window.

Adapted from the proven $1.67M wallet pattern (Binance → Polymarket latency).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import structlog

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient
from src.signal_bus import Signal, SignalBus, SignalType

logger = structlog.get_logger(__name__)

# Default correlated pairs to trade when BTC signals
DEFAULT_ALT_SYMBOLS = ["XRP/USD", "HBAR/USD", "XCN/USD"]

# BTC momentum detection parameters
DEFAULT_MOMENTUM_THRESHOLD_PCT = 0.11  # 0.11% BTC move
DEFAULT_MOMENTUM_WINDOW_SEC = 10  # over 10-second window
DEFAULT_ENTRY_DELAY_MS = 9000  # 9 seconds after detection
DEFAULT_ENTRY_WINDOW_MS = 7000  # 7-second entry window


class BTCCorrelationStrategy:
    """Monitors BTC momentum and trades alts during the correlation window.

    Flow:
    1. Poll BTC/USD ticker at high frequency
    2. Track price changes over rolling window
    3. When BTC move >= threshold, start entry timer
    4. After entry_delay, place orders on correlated alts
    5. Exit on mean reversion or stop-loss
    """

    def __init__(
        self,
        crypto_client: CryptoClient,
        signal_bus: SignalBus,
        alt_symbols: list[str] | None = None,
        momentum_threshold_pct: float = DEFAULT_MOMENTUM_THRESHOLD_PCT,
        momentum_window_sec: float = DEFAULT_MOMENTUM_WINDOW_SEC,
        entry_delay_ms: int = DEFAULT_ENTRY_DELAY_MS,
        entry_window_ms: int = DEFAULT_ENTRY_WINDOW_MS,
        trade_amount_usd: float = 50.0,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.03,
        poll_interval_sec: float = 1.0,
    ) -> None:
        self._client = crypto_client
        self._bus = signal_bus
        self._alt_symbols = alt_symbols or DEFAULT_ALT_SYMBOLS
        self._threshold = momentum_threshold_pct
        self._window = momentum_window_sec
        self._entry_delay = entry_delay_ms / 1000.0
        self._entry_window = entry_window_ms / 1000.0
        self._trade_amount = trade_amount_usd
        self._stop_loss = stop_loss_pct
        self._take_profit = take_profit_pct
        self._poll_interval = poll_interval_sec
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._btc_prices: list[tuple[float, float]] = []  # (timestamp, price)
        self._cooldown_until: float = 0.0
        self._active_trades: dict[str, dict] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "btc_correlation_started",
            threshold=self._threshold,
            alts=self._alt_symbols,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """Main monitoring loop — polls BTC price and detects momentum."""
        while self._running:
            try:
                now = time.time()

                # Skip if in cooldown
                if now < self._cooldown_until:
                    await asyncio.sleep(self._poll_interval)
                    continue

                # Fetch BTC price
                ticker = await self._client.fetch_ticker("BTC/USD")
                if not ticker or "last" not in ticker:
                    await asyncio.sleep(self._poll_interval)
                    continue

                btc_price = float(ticker["last"])
                self._btc_prices.append((now, btc_price))

                # Trim old prices outside window
                cutoff = now - self._window
                self._btc_prices = [(t, p) for t, p in self._btc_prices if t >= cutoff]

                if len(self._btc_prices) < 2:
                    await asyncio.sleep(self._poll_interval)
                    continue

                # Calculate momentum
                oldest_price = self._btc_prices[0][1]
                pct_change = (btc_price - oldest_price) / oldest_price * 100

                if abs(pct_change) >= self._threshold:
                    direction = "up" if pct_change > 0 else "down"
                    logger.info(
                        "btc_momentum_detected",
                        pct_change=round(pct_change, 4),
                        direction=direction,
                        btc_price=btc_price,
                    )

                    # Signal the bus
                    await self._bus.publish(Signal(
                        signal_type=SignalType.LATENCY_SPREAD,
                        source="btc_correlation",
                        data={
                            "platform": "crypto",
                            "btc_price": btc_price,
                            "pct_change": round(pct_change, 4),
                            "direction": direction,
                        },
                    ))

                    # Wait for entry delay, then trade alts
                    await asyncio.sleep(self._entry_delay)
                    await self._trade_correlated_alts(direction, pct_change)

                    # Cooldown to avoid repeated triggers
                    self._cooldown_until = time.time() + 30.0

                # Check active trades for exit conditions
                await self._manage_exits()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("btc_correlation_error", error=str(exc))

            await asyncio.sleep(self._poll_interval)

    async def _trade_correlated_alts(self, direction: str, btc_momentum: float) -> None:
        """Place orders on correlated altcoins during the entry window."""
        side = "buy" if direction == "up" else "sell"

        for symbol in self._alt_symbols:
            if symbol in self._active_trades:
                continue  # already positioned

            try:
                ticker = await self._client.fetch_ticker(symbol)
                if not ticker or "last" not in ticker:
                    continue

                price = float(ticker["last"])
                if price <= 0:
                    continue

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
                }

                logger.info(
                    "btc_correlation_trade",
                    symbol=symbol,
                    side=side,
                    price=price,
                    size=round(size, 6),
                    btc_momentum=round(btc_momentum, 4),
                )

            except Exception as exc:
                logger.error("btc_correlation_trade_error", symbol=symbol, error=str(exc))

    async def _manage_exits(self) -> None:
        """Check active trades for take-profit or stop-loss exits."""
        for symbol in list(self._active_trades.keys()):
            trade = self._active_trades[symbol]
            try:
                ticker = await self._client.fetch_ticker(symbol)
                if not ticker or "last" not in ticker:
                    continue

                current = float(ticker["last"])
                entry = trade["entry_price"]
                side = trade["side"]

                if side == "buy":
                    pnl_pct = (current - entry) / entry
                else:
                    pnl_pct = (entry - current) / entry

                # Take profit
                if pnl_pct >= self._take_profit:
                    exit_side = "sell" if side == "buy" else "buy"
                    await self._client.place_order(Order(
                        platform=self._client.platform_name,
                        market_id=symbol,
                        side=exit_side,
                        size=round(trade["size"], 6),
                        price=current,
                        order_type="market",
                    ))
                    logger.info("btc_correlation_take_profit", symbol=symbol, pnl_pct=round(pnl_pct, 4))
                    del self._active_trades[symbol]

                # Stop loss
                elif pnl_pct <= -self._stop_loss:
                    exit_side = "sell" if side == "buy" else "buy"
                    await self._client.place_order(Order(
                        platform=self._client.platform_name,
                        market_id=symbol,
                        side=exit_side,
                        size=round(trade["size"], 6),
                        price=current,
                        order_type="market",
                    ))
                    logger.info("btc_correlation_stop_loss", symbol=symbol, pnl_pct=round(pnl_pct, 4))
                    del self._active_trades[symbol]

            except Exception as exc:
                logger.error("btc_correlation_exit_error", symbol=symbol, error=str(exc))
