"""Async signal bus — lightweight pub/sub for internal event routing.

Data flow:
    Binance WS → Latency Detector → Signal Bus → Strategies
    BTC 15m Assistant → Redis → Signal Bus → Strategies
    Strategy Decision → Debate Engine → Execute or Reject

Multi-platform extension:
    Signals can now target specific platforms or be broadcast to all:
    - signal.data["platform"] = "kalshi" | "polymarket" | "kraken" | "all"
    - Platform-filtered subscribers only receive matching signals
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)

# Callback type for signal subscribers
SignalCallback = Callable[["Signal"], Coroutine[Any, Any, None]]


class SignalType(str, Enum):
    """Types of signals that flow through the bus."""

    LATENCY_SPREAD = "latency_spread"  # Binance-Polymarket pricing lag
    TA_INDICATOR = "ta_indicator"  # Technical analysis from sidecar
    TRADE_PROPOSAL = "trade_proposal"  # Strategy wants to execute a trade
    MARKET_DATA = "market_data"  # Generic market data update


@dataclass
class Signal:
    """A signal that flows through the bus."""

    signal_type: SignalType
    source: str  # e.g. "latency_detector", "ta_bridge", "stink_bid"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    signal_id: str = ""
    platform: str = "all"  # "kalshi", "polymarket", "kraken", "coinbase", "crypto", "all"

    def __post_init__(self) -> None:
        if not self.signal_id:
            self.signal_id = f"{self.signal_type.value}_{self.source}_{int(self.timestamp * 1000)}"
        # Also check data dict for platform hint
        if self.platform == "all" and "platform" in self.data:
            self.platform = self.data["platform"]


class SignalBus:
    """Async pub/sub bus for routing signals between components.

    Subscribers register for specific signal types. Publishers push signals
    which are delivered to all matching subscribers via asyncio queues.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[SignalType, list[SignalCallback]] = {}
        self._wildcard_subscribers: list[SignalCallback] = []
        self._queue: asyncio.Queue[Signal] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._task: asyncio.Task | None = None
        self._stats: dict[str, int] = {
            "published": 0,
            "delivered": 0,
            "errors": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def subscribe(self, signal_type: SignalType, callback: SignalCallback) -> None:
        """Subscribe to a specific signal type."""
        if signal_type not in self._subscribers:
            self._subscribers[signal_type] = []
        self._subscribers[signal_type].append(callback)
        logger.debug("signal_bus_subscribe", signal_type=signal_type.value)

    def subscribe_platform(
        self, signal_type: SignalType, platform: str, callback: SignalCallback
    ) -> None:
        """Subscribe to a signal type filtered by platform.

        The callback is only invoked when signal.platform matches the given
        platform or is "all" (broadcast).
        """
        async def _filtered(signal: Signal) -> None:
            if signal.platform in (platform, "all"):
                await callback(signal)

        self.subscribe(signal_type, _filtered)
        logger.debug("signal_bus_subscribe_platform", signal_type=signal_type.value, platform=platform)

    def subscribe_all(self, callback: SignalCallback) -> None:
        """Subscribe to all signal types."""
        self._wildcard_subscribers.append(callback)
        logger.debug("signal_bus_subscribe_all")

    async def publish(self, signal: Signal) -> None:
        """Publish a signal to all matching subscribers.

        If the dispatch loop is running, the signal is enqueued. Otherwise
        it is delivered inline (useful for tests or single-threaded callers).
        """
        self._stats["published"] += 1

        if self._running:
            try:
                self._queue.put_nowait(signal)
            except asyncio.QueueFull:
                logger.warning("signal_bus_queue_full", signal_type=signal.signal_type.value)
                self._stats["errors"] += 1
        else:
            # Deliver inline when the dispatch loop isn't running
            await self._dispatch(signal)

    async def start(self) -> None:
        """Start the background dispatch loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("signal_bus_started")

    async def stop(self) -> None:
        """Stop the dispatch loop and drain remaining signals."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Drain queue
        while not self._queue.empty():
            try:
                signal = self._queue.get_nowait()
                await self._dispatch(signal)
            except asyncio.QueueEmpty:
                break
        logger.info("signal_bus_stopped", stats=self._stats)

    async def _run(self) -> None:
        """Dispatch loop — pulls signals off the queue and delivers them."""
        while self._running:
            try:
                signal = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(signal)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _dispatch(self, signal: Signal) -> None:
        """Deliver a signal to all matching subscribers."""
        callbacks = list(self._wildcard_subscribers)
        if signal.signal_type in self._subscribers:
            callbacks.extend(self._subscribers[signal.signal_type])

        for cb in callbacks:
            try:
                await cb(signal)
                self._stats["delivered"] += 1
            except Exception as exc:
                self._stats["errors"] += 1
                logger.error(
                    "signal_delivery_error",
                    signal_type=signal.signal_type.value,
                    error=str(exc),
                )
