"""Binance-Polymarket latency detector.

Opens a WebSocket to Binance for real-time BTC/USDT spot price and compares
momentum against Polymarket 5m/15m contract pricing. When Binance shows
clear directional momentum but Polymarket hasn't repriced, emits a signal
to the signal bus.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog
import websockets

from src.config import Settings
from src.signal_bus import Signal, SignalBus, SignalType
from src.websocket_client import OrderbookFeed

logger = structlog.get_logger(__name__)


@dataclass
class LatencyMetrics:
    """Tracks detector performance metrics."""

    signals_emitted: int = 0
    avg_spread_pct: float = 0.0
    max_spread_pct: float = 0.0
    avg_latency_ms: float = 0.0
    spreads: list[float] = field(default_factory=list)

    def record_spread(self, spread_pct: float) -> None:
        self.spreads.append(spread_pct)
        # Keep last 1000 observations
        if len(self.spreads) > 1000:
            self.spreads = self.spreads[-1000:]
        self.avg_spread_pct = sum(self.spreads) / len(self.spreads)
        if spread_pct > self.max_spread_pct:
            self.max_spread_pct = spread_pct


class LatencyDetector:
    """Detects pricing lag between Binance BTC spot and Polymarket contracts.

    When Binance spot shows momentum (% change over window) but Polymarket
    contract prices haven't moved, a signal is emitted for strategies to act on.
    """

    BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/{symbol}@trade"

    def __init__(
        self,
        settings: Settings,
        signal_bus: SignalBus,
        orderbook: OrderbookFeed,
    ) -> None:
        self._settings = settings
        self._signal_bus = signal_bus
        self._orderbook = orderbook

        # Config
        self._symbol = settings.latency_binance_symbol
        self._momentum_window = settings.latency_momentum_window_seconds
        self._price_threshold = settings.latency_price_change_threshold_pct
        self._lag_threshold = settings.latency_polymarket_lag_threshold_seconds
        self._cooldown = settings.latency_signal_cooldown_seconds
        self._enabled = settings.latency_detector_enabled

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._binance_prices: deque[tuple[float, float]] = deque(maxlen=5000)
        self._last_signal_time: float = 0.0
        self._last_polymarket_update: dict[str, float] = {}  # token_id -> timestamp
        self._metrics = LatencyMetrics()

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "signals_emitted": self._metrics.signals_emitted,
            "avg_spread_pct": round(self._metrics.avg_spread_pct, 4),
            "max_spread_pct": round(self._metrics.max_spread_pct, 4),
            "binance_observations": len(self._binance_prices),
            "enabled": self._enabled,
        }

    async def start(self) -> None:
        """Start the Binance WebSocket listener and detection loop."""
        if not self._enabled:
            logger.info("latency_detector_disabled")
            return
        if self._running:
            return

        self._running = True
        # Register callback to track Polymarket update times
        self._orderbook.on_price_update(self._on_polymarket_update)
        self._task = asyncio.create_task(self._run_binance_ws())
        logger.info(
            "latency_detector_started",
            symbol=self._symbol,
            momentum_window=self._momentum_window,
            price_threshold=self._price_threshold,
        )

    async def stop(self) -> None:
        """Stop the detector."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("latency_detector_stopped", metrics=self.metrics)

    async def _on_polymarket_update(self, token_id: str, snapshot: dict[str, float]) -> None:
        """Track when Polymarket prices update for lag calculation."""
        self._last_polymarket_update[token_id] = time.time()

    async def _run_binance_ws(self) -> None:
        """Connect to Binance trade stream and process price updates."""
        url = self.BINANCE_WS_URL.format(symbol=self._symbol)
        backoff = 1.0

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    backoff = 1.0
                    logger.info("binance_ws_connected", symbol=self._symbol)

                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw_msg)
                            await self._handle_binance_trade(msg)
                        except json.JSONDecodeError:
                            continue
                        except Exception as exc:
                            logger.error("binance_msg_error", error=str(exc))

            except websockets.ConnectionClosed:
                logger.warning("binance_ws_disconnected")
            except Exception as exc:
                logger.error("binance_ws_error", error=str(exc))

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _handle_binance_trade(self, msg: dict[str, Any]) -> None:
        """Process a Binance trade message and check for momentum."""
        price = float(msg.get("p", 0))
        trade_time = float(msg.get("T", 0)) / 1000.0  # ms -> seconds

        if price <= 0:
            return

        now = time.time()
        self._binance_prices.append((now, price))

        # Calculate momentum over the window
        momentum = self._calculate_momentum()
        if momentum is None:
            return

        abs_momentum = abs(momentum)
        self._metrics.record_spread(abs_momentum)

        # Check if momentum exceeds threshold
        if abs_momentum < self._price_threshold:
            return

        # Check cooldown
        if now - self._last_signal_time < self._cooldown:
            return

        # Check if Polymarket is lagging
        polymarket_lag = self._estimate_polymarket_lag()
        if polymarket_lag < self._lag_threshold:
            return

        # Emit signal
        direction = "bullish" if momentum > 0 else "bearish"
        signal = Signal(
            signal_type=SignalType.LATENCY_SPREAD,
            source="latency_detector",
            data={
                "direction": direction,
                "momentum_pct": round(momentum, 4),
                "binance_price": price,
                "polymarket_lag_seconds": round(polymarket_lag, 2),
                "symbol": self._symbol,
            },
        )

        await self._signal_bus.publish(signal)
        self._last_signal_time = now
        self._metrics.signals_emitted += 1

        logger.info(
            "latency_signal_emitted",
            direction=direction,
            momentum_pct=round(momentum, 4),
            binance_price=price,
            polymarket_lag=round(polymarket_lag, 2),
        )

    def _calculate_momentum(self) -> float | None:
        """Calculate price change percentage over the momentum window."""
        if len(self._binance_prices) < 2:
            return None

        now = time.time()
        cutoff = now - self._momentum_window

        # Find the oldest price within the window
        old_price = None
        for ts, price in self._binance_prices:
            if ts >= cutoff:
                old_price = price
                break

        if old_price is None or old_price == 0:
            return None

        current_price = self._binance_prices[-1][1]
        return ((current_price - old_price) / old_price) * 100.0

    def _estimate_polymarket_lag(self) -> float:
        """Estimate how stale Polymarket pricing is.

        Returns the average age of the last Polymarket price updates
        across all tracked tokens.
        """
        if not self._last_polymarket_update:
            # If no Polymarket updates seen, assume maximum lag
            return self._lag_threshold + 1.0

        now = time.time()
        ages = [now - ts for ts in self._last_polymarket_update.values()]
        return sum(ages) / len(ages)
