"""Smart Exit Engine — Price-based exits with take-profit, stop-loss, and trailing stops.

Monitors copied positions and triggers exits based on:
- Tiered take-profit (15% → sell 50%, 30% → sell remaining)
- Stop-loss (25% drop → sell all)
- Time-based exit (48h with <5% move → sell)
- Trailing stop (after 15% gain, trail at 10% below peak)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PositionTracker:
    """Tracks peak prices and partial exit state per position."""

    position_id: str
    entry_price: float
    entry_time: float
    peak_price: float = 0.0
    partial_exit_done: bool = False  # True after 15% take-profit (50% sold)
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0

    def update_peak(self, current_price: float) -> None:
        if current_price > self.peak_price:
            self.peak_price = current_price
            if self.trailing_stop_active:
                self.trailing_stop_price = self.peak_price * 0.90  # 10% below peak


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
        take_profit_1_pct: float = 0.15,
        take_profit_2_pct: float = 0.30,
        stop_loss_pct: float = 0.25,
        trailing_stop_pct: float = 0.10,
        time_exit_hours: float = 48.0,
        time_exit_min_move_pct: float = 0.05,
    ) -> None:
        self._tp1 = take_profit_1_pct
        self._tp2 = take_profit_2_pct
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

        # 1. Stop-loss: drop 25% from entry → sell all
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

        # 3. Take-profit tier 2: 30%+ gain → sell remaining
        if pnl_pct >= self._tp2:
            return ExitSignal(
                position_id=position_id,
                reason="take_profit_30pct",
                sell_fraction=1.0,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        # 4. Take-profit tier 1: 15%+ gain → sell 50%, activate trailing stop
        if pnl_pct >= self._tp1 and not tracker.partial_exit_done:
            tracker.partial_exit_done = True
            tracker.trailing_stop_active = True
            tracker.trailing_stop_price = tracker.peak_price * (1 - self._trailing_pct)
            return ExitSignal(
                position_id=position_id,
                reason="take_profit_15pct",
                sell_fraction=0.5,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        # 5. Time-based exit: held >48h with <5% absolute move
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
