"""Smart Exit Engine — Price-based exits with take-profit, stop-loss, and trailing stops.

Monitors copied positions and triggers exits based on:
- Trailing stop activation at 30% gain (trail at 15% below peak, let winners ride)
- Stop-loss (50% drop → sell all)
- Time-based exit (48h with <5% move → sell)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PositionTracker:
    """Tracks peak prices and trailing stop state per position."""

    position_id: str
    entry_price: float
    entry_time: float
    peak_price: float = 0.0
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0
    _trailing_pct: float = 0.15  # set by ExitEngine on registration

    def update_peak(self, current_price: float) -> None:
        if current_price > self.peak_price:
            self.peak_price = current_price
            if self.trailing_stop_active:
                self.trailing_stop_price = self.peak_price * (1 - self._trailing_pct)


@dataclass
class ExitSignal:
    """Describes an exit action to take."""

    position_id: str
    reason: str
    sell_fraction: float  # 0.0 to 1.0 — how much of the position to sell
    current_price: float
    entry_price: float
    pnl_pct: float
    hold_time_hours: float
    peak_price: float = 0.0


class ExitEngine:
    """Evaluates positions and generates exit signals."""

    def __init__(
        self,
        take_profit_1_pct: float = 0.30,
        take_profit_2_pct: float = 9.99,
        stop_loss_pct: float = 0.50,
        trailing_stop_pct: float = 0.15,
        time_exit_hours: float = 48.0,
        time_exit_min_move_pct: float = 0.05,
    ) -> None:
        self._tp1 = take_profit_1_pct  # trailing stop activation threshold
        self._tp2 = take_profit_2_pct  # effectively disabled
        self._sl = stop_loss_pct
        self._trailing_pct = trailing_stop_pct
        self._time_hours = time_exit_hours
        self._time_min_move = time_exit_min_move_pct

        # Track per-position state
        self._trackers: dict[str, PositionTracker] = {}

    def register_position(self, position_id: str, entry_price: float, entry_time: float) -> None:
        """Register a new position for tracking."""
        self._trackers[position_id] = PositionTracker(
            position_id=position_id,
            entry_price=entry_price,
            entry_time=entry_time,
            peak_price=entry_price,
            _trailing_pct=self._trailing_pct,
        )

    def unregister_position(self, position_id: str) -> None:
        """Remove a position from tracking."""
        self._trackers.pop(position_id, None)

    def evaluate(self, position_id: str, current_price: float) -> Optional[ExitSignal]:
        """Evaluate a position and return an ExitSignal if exit is warranted."""
        tracker = self._trackers.get(position_id)
        if not tracker:
            return None

        now = time.time()
        entry = tracker.entry_price
        if entry <= 0:
            return None

        pnl_pct = (current_price - entry) / entry
        hold_hours = (now - tracker.entry_time) / 3600

        # Update peak price
        tracker.update_peak(current_price)

        # 1. Stop-loss: 50% drop from entry → sell all
        if pnl_pct <= -self._sl:
            return ExitSignal(
                position_id=position_id,
                reason="stop_loss",
                sell_fraction=1.0,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        # 2. Trailing stop: if active and price drops below trailing stop level
        if tracker.trailing_stop_active and current_price <= tracker.trailing_stop_price:
            return ExitSignal(
                position_id=position_id,
                reason="trailing_stop",
                sell_fraction=1.0,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        # 3. Activate trailing stop at 30% gain (don't sell — let winners ride)
        if pnl_pct >= self._tp1 and not tracker.trailing_stop_active:
            tracker.trailing_stop_active = True
            tracker.trailing_stop_price = tracker.peak_price * (1 - self._trailing_pct)
            logger.info(
                "exit_trailing_activated",
                position_id=position_id,
                pnl_pct=round(pnl_pct * 100, 1),
                peak=tracker.peak_price,
                trailing_price=round(tracker.trailing_stop_price, 4),
            )
            return None  # Don't sell — just activate trailing

        # 4. Time-based exit: held >48h with <5% absolute move → stale position
        if hold_hours >= self._time_hours and abs(pnl_pct) < self._time_min_move:
            return ExitSignal(
                position_id=position_id,
                reason="time_exit_stale",
                sell_fraction=1.0,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        return None

    def get_tracker(self, position_id: str) -> Optional[PositionTracker]:
        return self._trackers.get(position_id)

    def active_count(self) -> int:
        return len(self._trackers)
