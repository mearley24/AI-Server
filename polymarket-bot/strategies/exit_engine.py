"""Smart Exit Engine — Price-based exits with take-profit, stop-loss, and trailing stops.

Monitors copied positions and triggers exits based on:
- Trailing stop activation at higher gain (let cheap brackets run)
- Category-tuned stop-loss and time exits
- Near-resolution take-profit for locked-in gains
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


CATEGORY_EXIT_PARAMS: dict[str, dict[str, float]] = {
    "crypto_updown": {"sl": 0.40, "time_hours": 6, "trailing": 0.08},
    "sports": {"sl": 0.35, "time_hours": 12, "trailing": 0.10},
    "weather": {"sl": 0.60, "time_hours": 48, "trailing": 0.12},
    "politics": {"sl": 0.40, "time_hours": 48, "trailing": 0.15},
    "geopolitics": {"sl": 0.40, "time_hours": 48, "trailing": 0.15},
    "other": {"sl": 0.45, "time_hours": 36, "trailing": 0.12},
    "esports": {"sl": 0.35, "time_hours": 12, "trailing": 0.10},
    "economics": {"sl": 0.45, "time_hours": 48, "trailing": 0.15},
}


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
    # Category-specific overrides
    category: str = ""
    _sl_override: float = 0.0  # 0 = use engine default
    _time_hours_override: float = 0.0  # 0 = use engine default

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
        take_profit_1_pct: float = 0.50,
        take_profit_2_pct: float = 9.99,
        stop_loss_pct: float = 0.45,
        trailing_stop_pct: float = 0.12,
        time_exit_hours: float = 36.0,
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

    def register_position(self, position_id: str, entry_price: float, entry_time: float, category: str = "") -> None:
        """Register a new position for tracking with optional category overrides."""
        # Look up category-specific exit parameters
        cat_params = CATEGORY_EXIT_PARAMS.get(category, {})
        sl_override = cat_params.get("sl", 0.0)
        time_override = cat_params.get("time_hours", 0.0)
        trailing_pct = cat_params.get("trailing", self._trailing_pct)

        self._trackers[position_id] = PositionTracker(
            position_id=position_id,
            entry_price=entry_price,
            entry_time=entry_time,
            peak_price=entry_price,
            _trailing_pct=trailing_pct,
            category=category,
            _sl_override=sl_override,
            _time_hours_override=time_override,
        )
        if category and cat_params:
            logger.debug(
                "exit_category_params_applied",
                position_id=position_id,
                category=category,
                sl=sl_override,
                time_hours=time_override,
                trailing=trailing_pct,
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

        # Use per-position category overrides if set, otherwise engine defaults
        effective_sl = tracker._sl_override if tracker._sl_override > 0 else self._sl
        effective_time_hours = tracker._time_hours_override if tracker._time_hours_override > 0 else self._time_hours

        # Auto-exit positions older than 14 days at current market price
        # Dead money in long-duration markets should be recycled
        position_age_days = (now - tracker.entry_time) / 86400
        if position_age_days > 14:
            return ExitSignal(
                position_id=position_id,
                reason="stale_position",
                sell_fraction=1.0,
                current_price=current_price,
                entry_price=entry,
                pnl_pct=pnl_pct,
                hold_time_hours=hold_hours,
                peak_price=tracker.peak_price,
            )

        # 0. HOLD RULE: cheap entries are asymmetric binary bets.
        # They either resolve at $1.00 (4-10x) or $0.00.
        # Trailing stops and partial TPs destroy the asymmetry.
        deep_value_entry = entry < 0.30  # 10-25c bracket = 122% ROI
        cheap_entry = entry < 0.25
        skip_early_stop = cheap_entry and hold_hours < 6.0 and pnl_pct > -0.80

        # 1. Stop-loss: category-specific drop from entry -> sell all
        #    Deep value entries get wider stop-loss (70% instead of category default)
        #    because these are high-asymmetry bets -- one win covers many losses
        effective_sl_used = max(effective_sl, 0.70) if deep_value_entry else effective_sl
        if not skip_early_stop and pnl_pct <= -effective_sl_used:
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

        # 2. Trailing stop -- SKIP for deep value entries.
        #    A 15c->25c->21c pullback is noise, not a reason to sell.
        #    Resolution at $1.00 = +567%. Trailing stop sells at +40%.
        if not deep_value_entry and tracker.trailing_stop_active and current_price <= tracker.trailing_stop_price:
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

        # 3. Activate trailing stop at gain threshold -- only for NON-deep-value entries
        if not deep_value_entry and pnl_pct >= self._tp1 and not tracker.trailing_stop_active:
            tracker.trailing_stop_active = True
            tracker.trailing_stop_price = tracker.peak_price * (1 - self._trailing_pct)
            logger.info(
                "exit_trailing_activated",
                position_id=position_id,
                pnl_pct=round(pnl_pct * 100, 1),
                peak=tracker.peak_price,
                trailing_price=round(tracker.trailing_stop_price, 4),
            )
            return None  # Don't sell -- just activate trailing

        # 3b. Near-resolution take profit -- ONLY for entries >= 30c.
        #     For deep value entries (<30c), if price went from 15c to 95c,
        #     it's almost certainly resolving YES. Hold for full $1.00 payout.
        #     For entries 30-50c, raise threshold to $0.95 (was $0.85).
        if not deep_value_entry and entry < 0.50:
            near_resolution_price = 0.95  # raised from 0.85
            if current_price >= near_resolution_price:
                return ExitSignal(
                    position_id=position_id,
                    reason="near_resolution_takeprofit",
                    sell_fraction=0.50,  # reduced from 0.75 -- keep more riding
                    current_price=current_price,
                    entry_price=entry,
                    pnl_pct=pnl_pct,
                    hold_time_hours=hold_hours,
                    peak_price=tracker.peak_price,
                )

        # 4. Time-based exit -- deep value entries get 2x time allowance
        effective_time = effective_time_hours * 2.0 if deep_value_entry else effective_time_hours
        stale = hold_hours >= effective_time and abs(pnl_pct) < self._time_min_move
        deteriorating = (
            hold_hours >= effective_time * 0.5
            and pnl_pct <= -0.20
            and tracker.peak_price <= entry * 1.05
        )
        if stale or deteriorating:
            reason = "time_exit_stale" if stale else "time_exit_deteriorating"
            return ExitSignal(
                position_id=position_id,
                reason=reason,
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
