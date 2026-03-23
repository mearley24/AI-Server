"""Order flow analyzer — smart money signals from order book dynamics.

Detects:
    - Order book imbalance (bid/ask depth skew)
    - Liquidity grabs (stop hunts / wicks)
    - Compression / expansion (Bollinger squeeze via ATR)
    - Volume delta tracking (hidden accumulation / distribution)
    - Trapped trader detection (failed breakouts)

Publishes signals to the existing SignalBus for strategies to consume.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.config import Settings
from src.signal_bus import Signal, SignalBus, SignalType
from src.websocket_client import OrderbookFeed

logger = structlog.get_logger(__name__)


# Extend SignalType with order flow types (string enums are open)
SIGNAL_ORDER_BOOK_IMBALANCE = "order_book_imbalance"
SIGNAL_LIQUIDITY_GRAB = "liquidity_grab"
SIGNAL_COMPRESSION_BREAKOUT = "compression_breakout"
SIGNAL_VOLUME_DIVERGENCE = "volume_divergence"
SIGNAL_TRAPPED_TRADERS = "trapped_traders"


@dataclass
class Candle:
    """OHLCV candle built from order book snapshots."""

    timestamp: float
    open: float
    high: float
    low: float
    close: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0

    @property
    def volume(self) -> float:
        return self.buy_volume + self.sell_volume

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class OrderFlowState:
    """Tracks running state for a single token."""

    token_id: str
    candles: deque[Candle] = field(default_factory=lambda: deque(maxlen=200))
    cumulative_volume_delta: float = 0.0
    last_price: float = 0.0
    last_bid_depth: float = 0.0
    last_ask_depth: float = 0.0
    recent_highs: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    recent_lows: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    last_signal_time: dict[str, float] = field(default_factory=dict)


class OrderFlowAnalyzer:
    """Analyzes order book dynamics and publishes smart-money signals.

    Integrates with the existing SignalBus — strategies subscribe to
    order flow signal types alongside latency and TA signals.
    """

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
        self._imbalance_threshold = getattr(settings, "order_flow_imbalance_threshold", 2.5)
        self._compression_atr_periods = getattr(settings, "order_flow_compression_atr_periods", 14)
        self._compression_squeeze_factor = getattr(settings, "order_flow_compression_squeeze_factor", 0.5)
        self._delta_divergence_threshold = getattr(settings, "order_flow_delta_divergence_threshold", 0.3)
        self._lookback_candles = getattr(settings, "order_flow_lookback_candles", 50)
        self._enabled = getattr(settings, "order_flow_enabled", True)

        # Per-token state
        self._states: dict[str, OrderFlowState] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._tick_interval = 5.0  # analyze every 5 seconds
        self._signal_cooldown = 60.0  # min seconds between same signal type per token

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        """Start the order flow analysis loop."""
        if not self._enabled:
            logger.info("order_flow_analyzer_disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("order_flow_analyzer_started")

    async def stop(self) -> None:
        """Stop the analyzer."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("order_flow_analyzer_stopped")

    async def _run(self) -> None:
        """Main analysis loop."""
        while self._running:
            try:
                await self._analyze_all()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("order_flow_tick_error", error=str(exc))
            await asyncio.sleep(self._tick_interval)

    async def _analyze_all(self) -> None:
        """Analyze order flow for all tracked tokens."""
        # Get all token IDs the orderbook feed is tracking
        tracked_tokens = self._orderbook.tracked_tokens if hasattr(self._orderbook, "tracked_tokens") else []

        for token_id in tracked_tokens:
            state = self._states.setdefault(token_id, OrderFlowState(token_id=token_id))

            # Fetch current orderbook snapshot
            try:
                book = self._orderbook.get_snapshot(token_id) if hasattr(self._orderbook, "get_snapshot") else None
            except Exception:
                book = None

            if book is None:
                continue

            bids = book.get("bids", [])
            asks = book.get("asks", [])

            # Calculate depths
            bid_depth = sum(float(b.get("size", 0)) for b in bids)
            ask_depth = sum(float(a.get("size", 0)) for a in asks)
            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 0.0
            mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else state.last_price

            # Update state
            state.last_bid_depth = bid_depth
            state.last_ask_depth = ask_depth

            # Build candle from price action
            if mid_price > 0:
                self._update_candle(state, mid_price, bid_depth, ask_depth)

            state.last_price = mid_price

            # Run detectors
            await self._detect_imbalance(state, token_id, bid_depth, ask_depth, mid_price)
            await self._detect_liquidity_grab(state, token_id, mid_price)
            await self._detect_compression(state, token_id, mid_price)
            await self._detect_volume_divergence(state, token_id, mid_price)
            await self._detect_trapped_traders(state, token_id, mid_price)

    def _update_candle(
        self, state: OrderFlowState, price: float, bid_depth: float, ask_depth: float
    ) -> None:
        """Update the current candle or start a new one (1-minute candles)."""
        now = time.time()
        candle_start = int(now / 60) * 60  # floor to minute

        if state.candles and int(state.candles[-1].timestamp / 60) * 60 == candle_start:
            # Update existing candle
            candle = state.candles[-1]
            candle.high = max(candle.high, price)
            candle.low = min(candle.low, price)
            candle.close = price
            # Attribute volume to buy/sell based on price movement
            if price > candle.close:
                candle.buy_volume += bid_depth * 0.1  # weighted snapshot
            else:
                candle.sell_volume += ask_depth * 0.1
        else:
            # New candle
            candle = Candle(
                timestamp=now,
                open=price,
                high=price,
                low=price,
                close=price,
            )
            state.candles.append(candle)

        # Track highs/lows
        state.recent_highs.append(price)
        state.recent_lows.append(price)

        # Update CVD
        delta = bid_depth - ask_depth
        state.cumulative_volume_delta += delta * 0.01

    def _can_signal(self, state: OrderFlowState, signal_type: str) -> bool:
        """Check if we can emit this signal type (cooldown)."""
        last = state.last_signal_time.get(signal_type, 0)
        return (time.time() - last) >= self._signal_cooldown

    async def _emit_signal(
        self, signal_type_str: str, token_id: str, data: dict[str, Any], state: OrderFlowState
    ) -> None:
        """Publish an order flow signal to the bus."""
        state.last_signal_time[signal_type_str] = time.time()

        signal = Signal(
            signal_type=SignalType.MARKET_DATA,  # Use existing generic type
            source=f"order_flow_{signal_type_str}",
            data={
                "order_flow_type": signal_type_str,
                "token_id": token_id,
                **data,
            },
        )
        await self._signal_bus.publish(signal)

        logger.info(
            "order_flow_signal",
            signal_type=signal_type_str,
            token_id=token_id,
            **{k: v for k, v in data.items() if not isinstance(v, (list, dict))},
        )

    async def _detect_imbalance(
        self,
        state: OrderFlowState,
        token_id: str,
        bid_depth: float,
        ask_depth: float,
        mid_price: float,
    ) -> None:
        """Detect order book imbalance (heavily skewed bid:ask ratio)."""
        if not self._can_signal(state, SIGNAL_ORDER_BOOK_IMBALANCE):
            return

        if ask_depth <= 0 or bid_depth <= 0:
            return

        ratio = bid_depth / ask_depth

        if ratio >= self._imbalance_threshold:
            await self._emit_signal(
                SIGNAL_ORDER_BOOK_IMBALANCE,
                token_id,
                {
                    "direction": "bullish",
                    "bid_ask_ratio": round(ratio, 2),
                    "bid_depth": round(bid_depth, 2),
                    "ask_depth": round(ask_depth, 2),
                    "mid_price": round(mid_price, 4),
                },
                state,
            )
        elif (1 / ratio) >= self._imbalance_threshold:
            await self._emit_signal(
                SIGNAL_ORDER_BOOK_IMBALANCE,
                token_id,
                {
                    "direction": "bearish",
                    "bid_ask_ratio": round(ratio, 2),
                    "bid_depth": round(bid_depth, 2),
                    "ask_depth": round(ask_depth, 2),
                    "mid_price": round(mid_price, 4),
                },
                state,
            )

    async def _detect_liquidity_grab(
        self, state: OrderFlowState, token_id: str, mid_price: float
    ) -> None:
        """Detect liquidity grabs — price wicks through a level then reverses.

        Classic stop hunt: price briefly pushes past a cluster of stops,
        triggers them, then reverses sharply.
        """
        if not self._can_signal(state, SIGNAL_LIQUIDITY_GRAB):
            return

        candles = list(state.candles)
        if len(candles) < 3:
            return

        current = candles[-1]
        prev = candles[-2]

        # Detect bearish liquidity grab: wick below recent lows then close above
        if len(state.recent_lows) >= 10:
            recent_low = min(list(state.recent_lows)[-10:])
            if current.low < recent_low and current.close > prev.close:
                wick_depth = recent_low - current.low
                if wick_depth > 0 and current.range > 0:
                    wick_ratio = wick_depth / current.range
                    if wick_ratio > 0.5:
                        await self._emit_signal(
                            SIGNAL_LIQUIDITY_GRAB,
                            token_id,
                            {
                                "direction": "bullish_reversal",
                                "wick_low": round(current.low, 4),
                                "recent_low": round(recent_low, 4),
                                "close": round(current.close, 4),
                                "wick_ratio": round(wick_ratio, 2),
                            },
                            state,
                        )

        # Detect bullish liquidity grab: wick above recent highs then close below
        if len(state.recent_highs) >= 10:
            recent_high = max(list(state.recent_highs)[-10:])
            if current.high > recent_high and current.close < prev.close:
                wick_depth = current.high - recent_high
                if wick_depth > 0 and current.range > 0:
                    wick_ratio = wick_depth / current.range
                    if wick_ratio > 0.5:
                        await self._emit_signal(
                            SIGNAL_LIQUIDITY_GRAB,
                            token_id,
                            {
                                "direction": "bearish_reversal",
                                "wick_high": round(current.high, 4),
                                "recent_high": round(recent_high, 4),
                                "close": round(current.close, 4),
                                "wick_ratio": round(wick_ratio, 2),
                            },
                            state,
                        )

    async def _detect_compression(
        self, state: OrderFlowState, token_id: str, mid_price: float
    ) -> None:
        """Detect compression (ATR squeeze) — precursor to expansion move.

        When the Average True Range over N periods is less than squeeze_factor
        times the 20-period average ATR, volatility is compressed and a breakout
        is likely.
        """
        if not self._can_signal(state, SIGNAL_COMPRESSION_BREAKOUT):
            return

        candles = list(state.candles)
        atr_periods = self._compression_atr_periods
        if len(candles) < max(atr_periods, 20) + 1:
            return

        # Calculate ATR for recent candles
        def true_range(c: Candle, prev_c: Candle) -> float:
            return max(c.high - c.low, abs(c.high - prev_c.close), abs(c.low - prev_c.close))

        trs = [true_range(candles[i], candles[i - 1]) for i in range(-atr_periods, 0)]
        current_atr = sum(trs) / len(trs) if trs else 0

        # 20-period average ATR (longer lookback)
        lookback = min(20, len(candles) - 1)
        long_trs = [true_range(candles[i], candles[i - 1]) for i in range(-lookback, 0)]
        long_atr = sum(long_trs) / len(long_trs) if long_trs else 0

        if long_atr <= 0:
            return

        squeeze_ratio = current_atr / long_atr

        if squeeze_ratio < self._compression_squeeze_factor:
            # Now check if we're seeing early signs of expansion
            latest_range = candles[-1].range
            is_expanding = latest_range > current_atr * 1.5

            await self._emit_signal(
                SIGNAL_COMPRESSION_BREAKOUT,
                token_id,
                {
                    "squeeze_ratio": round(squeeze_ratio, 3),
                    "current_atr": round(current_atr, 4),
                    "long_atr": round(long_atr, 4),
                    "is_expanding": is_expanding,
                    "mid_price": round(mid_price, 4),
                    "direction": "up" if candles[-1].close > candles[-1].open else "down",
                },
                state,
            )

    async def _detect_volume_divergence(
        self, state: OrderFlowState, token_id: str, mid_price: float
    ) -> None:
        """Detect divergence between price direction and cumulative volume delta.

        If price is rising but CVD is falling (or vice versa), hidden
        accumulation/distribution is occurring.
        """
        if not self._can_signal(state, SIGNAL_VOLUME_DIVERGENCE):
            return

        candles = list(state.candles)
        lookback = min(self._lookback_candles, len(candles))
        if lookback < 10:
            return

        recent = candles[-lookback:]

        # Price trend: simple linear direction
        price_start = recent[0].close
        price_end = recent[-1].close
        price_change = (price_end - price_start) / price_start if price_start > 0 else 0

        # CVD trend over same period
        cvd_values = []
        running_cvd = 0.0
        for c in recent:
            running_cvd += c.delta
            cvd_values.append(running_cvd)

        if len(cvd_values) < 2:
            return

        cvd_start = cvd_values[0]
        cvd_end = cvd_values[-1]
        cvd_range = max(abs(v) for v in cvd_values) or 1.0
        cvd_change = (cvd_end - cvd_start) / cvd_range if cvd_range > 0 else 0

        threshold = self._delta_divergence_threshold

        # Bearish divergence: price up, CVD down
        if price_change > threshold and cvd_change < -threshold:
            await self._emit_signal(
                SIGNAL_VOLUME_DIVERGENCE,
                token_id,
                {
                    "divergence_type": "bearish",
                    "price_change_pct": round(price_change * 100, 2),
                    "cvd_direction": "falling",
                    "mid_price": round(mid_price, 4),
                    "interpretation": "hidden_distribution",
                },
                state,
            )

        # Bullish divergence: price down, CVD up
        elif price_change < -threshold and cvd_change > threshold:
            await self._emit_signal(
                SIGNAL_VOLUME_DIVERGENCE,
                token_id,
                {
                    "divergence_type": "bullish",
                    "price_change_pct": round(price_change * 100, 2),
                    "cvd_direction": "rising",
                    "mid_price": round(mid_price, 4),
                    "interpretation": "hidden_accumulation",
                },
                state,
            )

    async def _detect_trapped_traders(
        self, state: OrderFlowState, token_id: str, mid_price: float
    ) -> None:
        """Detect trapped traders — failed breakout then quick reversal.

        When price breaks a key level (recent high/low), traders pile in.
        If price quickly reverses, those traders are trapped and forced to
        exit, accelerating the reversal.
        """
        if not self._can_signal(state, SIGNAL_TRAPPED_TRADERS):
            return

        candles = list(state.candles)
        if len(candles) < 5:
            return

        # Check last 3 candles for a failed breakout pattern
        c_minus2 = candles[-3]
        c_minus1 = candles[-2]
        c_current = candles[-1]

        # Look for recent swing high/low over last 20 candles
        lookback = min(20, len(candles) - 3)
        lookback_candles = candles[-(lookback + 3):-3]
        if not lookback_candles:
            return

        swing_high = max(c.high for c in lookback_candles)
        swing_low = min(c.low for c in lookback_candles)

        # Failed bullish breakout: broke above swing high then reversed
        if c_minus1.high > swing_high and c_current.close < swing_high:
            if c_current.close < c_minus1.open:  # Strong reversal candle
                await self._emit_signal(
                    SIGNAL_TRAPPED_TRADERS,
                    token_id,
                    {
                        "trap_type": "bull_trap",
                        "breakout_high": round(c_minus1.high, 4),
                        "swing_high": round(swing_high, 4),
                        "reversal_close": round(c_current.close, 4),
                        "direction": "bearish",
                        "mid_price": round(mid_price, 4),
                    },
                    state,
                )

        # Failed bearish breakout: broke below swing low then reversed
        if c_minus1.low < swing_low and c_current.close > swing_low:
            if c_current.close > c_minus1.open:  # Strong reversal candle
                await self._emit_signal(
                    SIGNAL_TRAPPED_TRADERS,
                    token_id,
                    {
                        "trap_type": "bear_trap",
                        "breakout_low": round(c_minus1.low, 4),
                        "swing_low": round(swing_low, 4),
                        "reversal_close": round(c_current.close, 4),
                        "direction": "bullish",
                        "mid_price": round(mid_price, 4),
                    },
                    state,
                )
