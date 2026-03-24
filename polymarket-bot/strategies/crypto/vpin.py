"""VPIN Circuit Breaker — Volume-Synchronized Probability of Informed Trading.

Detects toxic order flow by measuring volume imbalance in fixed-volume
buckets. When VPIN crosses tiered thresholds, the market maker widens
spreads, reduces size, or stops quoting entirely.

Calculation:
1. Accumulate trades into volume buckets (each bucket = V_bucket volume)
2. Classify each trade as buy or sell using the tick rule
3. Per bucket: |buy_volume - sell_volume| / total_volume
4. VPIN = rolling average of bucket imbalances over N buckets

Circuit Breaker Tiers:
    VPIN < 0.4  → Normal
    0.4 ≤ VPIN < 0.6  → Widen spreads 50%
    0.6 ≤ VPIN < 0.8  → Widen spreads 100%, reduce size 50%
    VPIN ≥ 0.8  → STOP QUOTING
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class VPINState(str, Enum):
    """Circuit breaker states."""

    NORMAL = "normal"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


@dataclass
class VPINAction:
    """Actions the market maker should take based on VPIN state."""

    state: VPINState
    spread_multiplier: float  # 1.0 = normal, 1.5 = widen 50%, etc.
    size_multiplier: float  # 1.0 = normal, 0.5 = reduce 50%
    should_quote: bool  # False = kill switch


class VPINCalculator:
    """Volume-Synchronized Probability of Informed Trading.

    Accumulates trade volume into fixed-size buckets, classifies
    buy/sell via tick rule, and computes a rolling VPIN metric
    that drives the circuit breaker.
    """

    def __init__(
        self,
        bucket_volume: float = 1000.0,
        num_buckets: int = 50,
        warning_threshold: float = 0.4,
        danger_threshold: float = 0.6,
        critical_threshold: float = 0.8,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._bucket_volume = bucket_volume
        self._num_buckets = num_buckets
        self._warning = warning_threshold
        self._danger = danger_threshold
        self._critical = critical_threshold
        self._cooldown = cooldown_seconds

        # Current bucket accumulators
        self._current_buy_volume: float = 0.0
        self._current_sell_volume: float = 0.0
        self._current_total_volume: float = 0.0

        # Completed bucket imbalances
        self._bucket_imbalances: deque[float] = deque(maxlen=num_buckets)

        # Tick rule state
        self._last_price: float | None = None

        # Circuit breaker state
        self._state = VPINState.NORMAL
        self._last_state_change: float = 0.0
        self._cooldown_until: float = 0.0

    @property
    def vpin(self) -> float:
        """Current VPIN value (rolling average of bucket imbalances)."""
        if not self._bucket_imbalances:
            return 0.0
        return sum(self._bucket_imbalances) / len(self._bucket_imbalances)

    @property
    def state(self) -> VPINState:
        return self._state

    @property
    def bucket_count(self) -> int:
        return len(self._bucket_imbalances)

    def record_trade(self, price: float, volume: float) -> VPINAction:
        """Process a trade and return current circuit breaker action.

        Uses the tick rule to classify trades:
        - Price up from last trade → buy
        - Price down from last trade → sell
        - No change → split evenly

        Args:
            price: Trade price
            volume: Trade volume in quote currency (e.g. USDT)

        Returns:
            VPINAction with current spread/size multipliers
        """
        # Classify using tick rule
        if self._last_price is not None:
            if price > self._last_price:
                buy_vol = volume
                sell_vol = 0.0
            elif price < self._last_price:
                buy_vol = 0.0
                sell_vol = volume
            else:
                # No price change — split evenly
                buy_vol = volume / 2.0
                sell_vol = volume / 2.0
        else:
            # First trade — split evenly
            buy_vol = volume / 2.0
            sell_vol = volume / 2.0

        self._last_price = price

        # Accumulate into current bucket
        self._current_buy_volume += buy_vol
        self._current_sell_volume += sell_vol
        self._current_total_volume += volume

        # Check if bucket is full
        while self._current_total_volume >= self._bucket_volume:
            overflow = self._current_total_volume - self._bucket_volume

            # Scale the imbalance for the completed portion
            if self._current_total_volume > 0:
                ratio = self._bucket_volume / self._current_total_volume
            else:
                ratio = 1.0

            bucket_buy = self._current_buy_volume * ratio
            bucket_sell = self._current_sell_volume * ratio
            bucket_total = bucket_buy + bucket_sell

            if bucket_total > 0:
                imbalance = abs(bucket_buy - bucket_sell) / bucket_total
            else:
                imbalance = 0.0

            self._bucket_imbalances.append(imbalance)

            # Carry over the overflow into next bucket
            overflow_buy = self._current_buy_volume * (1 - ratio)
            overflow_sell = self._current_sell_volume * (1 - ratio)
            self._current_buy_volume = overflow_buy
            self._current_sell_volume = overflow_sell
            self._current_total_volume = overflow

        return self._evaluate()

    def _evaluate(self) -> VPINAction:
        """Evaluate VPIN and return appropriate action."""
        current_vpin = self.vpin
        now = time.time()

        # Determine new state from VPIN
        if current_vpin >= self._critical:
            new_state = VPINState.CRITICAL
        elif current_vpin >= self._danger:
            new_state = VPINState.DANGER
        elif current_vpin >= self._warning:
            new_state = VPINState.WARNING
        else:
            new_state = VPINState.NORMAL

        # Apply cooldown when recovering from elevated state
        if new_state.value < self._state.value and now < self._cooldown_until:
            # Still in cooldown — maintain previous (more restrictive) state
            new_state = self._state

        # Log state transitions
        if new_state != self._state:
            old_state = self._state
            self._state = new_state
            self._last_state_change = now

            # Set cooldown when transitioning to a less restrictive state
            if new_state.value < old_state.value:
                self._cooldown_until = now + self._cooldown

            logger.info(
                "vpin_state_change",
                old_state=old_state.value,
                new_state=new_state.value,
                vpin=round(current_vpin, 4),
                buckets=len(self._bucket_imbalances),
            )

        return self._action_for_state(self._state)

    @staticmethod
    def _action_for_state(state: VPINState) -> VPINAction:
        """Map circuit breaker state to concrete trading action."""
        if state == VPINState.NORMAL:
            return VPINAction(
                state=VPINState.NORMAL,
                spread_multiplier=1.0,
                size_multiplier=1.0,
                should_quote=True,
            )
        elif state == VPINState.WARNING:
            return VPINAction(
                state=VPINState.WARNING,
                spread_multiplier=1.5,
                size_multiplier=1.0,
                should_quote=True,
            )
        elif state == VPINState.DANGER:
            return VPINAction(
                state=VPINState.DANGER,
                spread_multiplier=2.0,
                size_multiplier=0.5,
                should_quote=True,
            )
        else:  # CRITICAL
            return VPINAction(
                state=VPINState.CRITICAL,
                spread_multiplier=0.0,
                size_multiplier=0.0,
                should_quote=False,
            )

    def status(self) -> dict[str, Any]:
        """Return current state for logging/debugging."""
        return {
            "vpin": round(self.vpin, 4),
            "state": self._state.value,
            "buckets_filled": len(self._bucket_imbalances),
            "buckets_required": self._num_buckets,
            "current_bucket_volume": round(self._current_total_volume, 2),
            "bucket_size": self._bucket_volume,
            "cooldown_active": time.time() < self._cooldown_until,
        }
