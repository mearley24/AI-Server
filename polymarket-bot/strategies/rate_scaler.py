"""Bankroll-based auto-scaling for MAX_TRADES_PER_HOUR.

Adjusts the hourly trade rate based on current on-chain bankroll tiers.
When the user's bankroll grows (e.g. new deposits), the bot automatically
scales up trading frequency. If COPYTRADE_MAX_TRADES_PER_HOUR is explicitly
set in the environment, auto-scaling is disabled and that value is used.
"""

from __future__ import annotations

import os
from typing import Callable

import structlog

logger = structlog.get_logger(__name__)

# Bankroll tiers: (min_bankroll, max_trades_per_hour)
# Evaluated top-down; first matching tier wins.
_TIERS: list[tuple[float, int]] = [
    (2000.0, 30),
    (1000.0, 20),
    (500.0, 15),
    (100.0, 10),
    (0.0, 5),
]


def _tier_rate(bankroll: float) -> int:
    """Return the trades-per-hour rate for a given bankroll."""
    for threshold, rate in _TIERS:
        if bankroll >= threshold:
            return rate
    return _TIERS[-1][1]


class RateScaler:
    """Scales MAX_TRADES_PER_HOUR based on current bankroll.

    Usage:
        scaler = RateScaler(notify_fn=my_notify)
        new_rate = scaler.update(bankroll=1200.0)
        # new_rate == 20  (from $1000-$2000 tier)
    """

    def __init__(
        self,
        notify_fn: Callable[[str, str], None] | None = None,
    ) -> None:
        self._notify = notify_fn

        # If env var is explicitly set, disable auto-scaling
        env_override = os.environ.get("COPYTRADE_MAX_TRADES_PER_HOUR")
        if env_override is not None:
            self._override = int(env_override)
            logger.info(
                "copytrade_rate_scaler_override",
                rate=self._override,
                msg="COPYTRADE_MAX_TRADES_PER_HOUR set, auto-scaling disabled",
            )
        else:
            self._override = None

        self._current_rate: int | None = None

    @property
    def is_auto(self) -> bool:
        """True if auto-scaling is active (no env override)."""
        return self._override is None

    @property
    def current_rate(self) -> int:
        """Current effective rate."""
        if self._override is not None:
            return self._override
        return self._current_rate or _TIERS[-1][1]

    def update(self, bankroll: float) -> int:
        """Recalculate rate from bankroll. Returns the new rate.

        Logs and notifies when the tier changes.
        """
        if self._override is not None:
            return self._override

        new_rate = _tier_rate(bankroll)
        old_rate = self._current_rate

        if old_rate is not None and new_rate != old_rate:
            logger.info(
                "copytrade_rate_adjusted",
                old_rate=old_rate,
                new_rate=new_rate,
                bankroll=round(bankroll, 2),
            )
            if self._notify:
                direction = "up" if new_rate > old_rate else "down"
                try:
                    self._notify(
                        f"Rate Scaled {direction.title()}",
                        f"Trades/hour: {old_rate} -> {new_rate}\n"
                        f"Bankroll: ${bankroll:,.2f}",
                    )
                except Exception:
                    pass  # never block trading on notification failure

        self._current_rate = new_rate
        return new_rate
