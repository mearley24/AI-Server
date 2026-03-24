"""Hawkes Process — self-exciting point process for order flow prediction.

Models order arrival as a self-exciting point process where each event
increases the probability of subsequent events. Maintains separate
processes for buy and sell trades to detect directional pressure.

Intensity function:
    λ(t) = μ + Σ α * exp(-β * (t - tᵢ))

The imbalance between buy and sell intensities feeds into the
Avellaneda-Stoikov reservation price as an additive signal.
"""

from __future__ import annotations

import math
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class HawkesProcess:
    """Single-sided Hawkes process tracking event intensity."""

    def __init__(
        self,
        mu: float = 1.0,
        alpha: float = 0.5,
        beta: float = 2.0,
        window_seconds: float = 300.0,
    ) -> None:
        self._mu = mu
        self._alpha = alpha
        self._beta = beta
        self._window = window_seconds
        self._events: list[float] = []  # timestamps of past events

    @property
    def mu(self) -> float:
        return self._mu

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def beta(self) -> float:
        return self._beta

    def add_event(self, timestamp: float | None = None) -> None:
        """Record a new event (trade arrival)."""
        ts = timestamp or time.time()
        self._events.append(ts)
        self._prune(ts)

    def intensity(self, t: float | None = None) -> float:
        """Compute current intensity λ(t) = μ + Σ α * exp(-β * (t - tᵢ))."""
        now = t or time.time()
        self._prune(now)

        excitation = 0.0
        for ti in self._events:
            dt = now - ti
            if dt >= 0:
                excitation += self._alpha * math.exp(-self._beta * dt)

        return self._mu + excitation

    def _prune(self, now: float) -> None:
        """Remove events older than the lookback window."""
        cutoff = now - self._window
        self._events = [t for t in self._events if t >= cutoff]

    @property
    def event_count(self) -> int:
        return len(self._events)


class HawkesOrderFlow:
    """Dual Hawkes processes for buy/sell order flow imbalance detection.

    When buy intensity >> sell intensity → buying pressure → shift
    reservation price up (and vice versa).

    The imbalance feeds into the reservation price as:
        r_adjusted = r + η * (λ_buy - λ_sell) / (λ_buy + λ_sell)
    """

    def __init__(
        self,
        mu: float = 1.0,
        alpha: float = 0.5,
        beta: float = 2.0,
        window_seconds: float = 300.0,
        sensitivity: float = 0.5,
    ) -> None:
        self._buy_process = HawkesProcess(mu, alpha, beta, window_seconds)
        self._sell_process = HawkesProcess(mu, alpha, beta, window_seconds)
        self._sensitivity = sensitivity

    def record_trade(self, side: str, timestamp: float | None = None) -> None:
        """Record a trade event.

        Args:
            side: "buy" or "sell" (tick-rule classified)
            timestamp: Event time (defaults to now)
        """
        if side == "buy":
            self._buy_process.add_event(timestamp)
        elif side == "sell":
            self._sell_process.add_event(timestamp)

    def imbalance(self, t: float | None = None) -> float:
        """Compute normalised order flow imbalance in [-1, 1].

        Returns:
            Positive = buying pressure, negative = selling pressure.
            Zero if no intensity on either side.
        """
        lambda_buy = self._buy_process.intensity(t)
        lambda_sell = self._sell_process.intensity(t)
        total = lambda_buy + lambda_sell

        if total == 0:
            return 0.0

        return (lambda_buy - lambda_sell) / total

    def reservation_price_adjustment(self, t: float | None = None) -> float:
        """Compute the additive adjustment to the reservation price.

        Returns:
            η * (λ_buy - λ_sell) / (λ_buy + λ_sell)
        """
        return self._sensitivity * self.imbalance(t)

    def buy_intensity(self, t: float | None = None) -> float:
        return self._buy_process.intensity(t)

    def sell_intensity(self, t: float | None = None) -> float:
        return self._sell_process.intensity(t)

    def status(self) -> dict[str, Any]:
        """Return current state for logging/debugging."""
        now = time.time()
        return {
            "buy_intensity": round(self.buy_intensity(now), 4),
            "sell_intensity": round(self.sell_intensity(now), 4),
            "imbalance": round(self.imbalance(now), 4),
            "adjustment": round(self.reservation_price_adjustment(now), 4),
            "buy_events": self._buy_process.event_count,
            "sell_events": self._sell_process.event_count,
        }
