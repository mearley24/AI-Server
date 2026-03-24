"""Inventory Manager — position tracking and risk limits for market making.

Tracks inventory per pair, enforces max position limits, and provides
quote skewing signals to the Avellaneda-Stoikov strategy when inventory
approaches risk boundaries.

Features:
- Current inventory per pair (signed: positive = long, negative = short)
- Max inventory limits (symmetric long/short)
- Soft limit: skew quotes aggressively to reduce inventory
- Hard limit: cancel all quotes on the overloaded side
- P&L tracking per pair
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class InventoryPosition:
    """Tracks inventory state for a single pair."""

    pair: str
    quantity: float = 0.0  # signed: positive = long, negative = short
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    total_bought: float = 0.0
    total_sold: float = 0.0
    last_update: float = field(default_factory=time.time)


class InventoryManager:
    """Manages inventory across multiple pairs with risk limits.

    Provides skew signals to the market maker:
    - At soft limit (default 70% of max): aggressive skewing
    - At hard limit (100% of max): cancel quotes on overloaded side
    """

    def __init__(
        self,
        max_inventory: float = 10.0,
        soft_limit_pct: float = 0.7,
    ) -> None:
        self._max_inventory = max_inventory
        self._soft_limit = max_inventory * soft_limit_pct
        self._positions: dict[str, InventoryPosition] = {}

    @property
    def max_inventory(self) -> float:
        return self._max_inventory

    def get_position(self, pair: str) -> InventoryPosition:
        """Get or create position for a pair."""
        if pair not in self._positions:
            self._positions[pair] = InventoryPosition(pair=pair)
        return self._positions[pair]

    def inventory(self, pair: str) -> float:
        """Get current inventory (signed quantity) for a pair."""
        return self.get_position(pair).quantity

    def record_fill(self, pair: str, side: str, size: float, price: float) -> None:
        """Record a filled order.

        Args:
            pair: Trading pair (e.g. "XRP/USDT")
            side: "buy" or "sell"
            size: Filled quantity (always positive)
            price: Fill price
        """
        pos = self.get_position(pair)

        if side == "buy":
            # Going long or reducing short
            new_qty = pos.quantity + size
            if pos.quantity < 0:
                # Closing short: realise P&L on the closed portion
                closed = min(size, abs(pos.quantity))
                pos.realized_pnl += closed * (pos.avg_entry_price - price)
            # Update average entry for the long side
            if new_qty > 0:
                if pos.quantity > 0:
                    # Adding to existing long
                    total_cost = pos.avg_entry_price * pos.quantity + price * size
                    pos.avg_entry_price = total_cost / new_qty
                else:
                    # New long after being flat or short
                    remaining_long = new_qty
                    if remaining_long > 0:
                        pos.avg_entry_price = price
            pos.quantity = new_qty
            pos.total_bought += size

        elif side == "sell":
            # Going short or reducing long
            new_qty = pos.quantity - size
            if pos.quantity > 0:
                # Closing long: realise P&L on the closed portion
                closed = min(size, pos.quantity)
                pos.realized_pnl += closed * (price - pos.avg_entry_price)
            # Update average entry for the short side
            if new_qty < 0:
                if pos.quantity < 0:
                    # Adding to existing short
                    total_cost = pos.avg_entry_price * abs(pos.quantity) + price * size
                    pos.avg_entry_price = total_cost / abs(new_qty)
                else:
                    # New short after being flat or long
                    remaining_short = abs(new_qty)
                    if remaining_short > 0:
                        pos.avg_entry_price = price
            pos.quantity = new_qty
            pos.total_sold += size

        pos.last_update = time.time()

        logger.debug(
            "inventory_fill",
            pair=pair,
            side=side,
            size=round(size, 6),
            price=round(price, 6),
            new_qty=round(pos.quantity, 6),
            realized_pnl=round(pos.realized_pnl, 4),
        )

    def can_quote_bid(self, pair: str) -> bool:
        """Check if we can place a bid (would increase long / reduce short)."""
        qty = self.inventory(pair)
        return qty < self._max_inventory

    def can_quote_ask(self, pair: str) -> bool:
        """Check if we can place an ask (would increase short / reduce long)."""
        qty = self.inventory(pair)
        return qty > -self._max_inventory

    def bid_size_limit(self, pair: str, desired_size: float) -> float:
        """Clip bid size to respect inventory limits.

        Returns the maximum allowable bid size (could be 0 at hard limit).
        """
        qty = self.inventory(pair)
        room = self._max_inventory - qty
        if room <= 0:
            return 0.0
        return min(desired_size, room)

    def ask_size_limit(self, pair: str, desired_size: float) -> float:
        """Clip ask size to respect inventory limits.

        Returns the maximum allowable ask size (could be 0 at hard limit).
        """
        qty = self.inventory(pair)
        room = self._max_inventory + qty  # qty is negative when short
        if room <= 0:
            return 0.0
        return min(desired_size, room)

    def skew_factor(self, pair: str) -> float:
        """Compute inventory skew factor in [-1, 1].

        0 = neutral (no skewing needed)
        positive = long heavy → skew asks lower (encourage selling)
        negative = short heavy → skew bids higher (encourage buying)

        Beyond soft limit, the factor scales aggressively.
        """
        qty = self.inventory(pair)
        if self._max_inventory == 0:
            return 0.0

        ratio = qty / self._max_inventory  # in [-1, 1]

        # Below soft limit: linear skew
        soft_ratio = self._soft_limit / self._max_inventory
        if abs(ratio) <= soft_ratio:
            return ratio

        # Beyond soft limit: aggressive non-linear skew
        # Maps [soft_ratio, 1.0] → [soft_ratio, 1.0] with steeper slope
        sign = 1.0 if ratio > 0 else -1.0
        abs_ratio = abs(ratio)
        # Quadratic ramp beyond soft limit
        excess = (abs_ratio - soft_ratio) / (1.0 - soft_ratio)
        aggressive = soft_ratio + (1.0 - soft_ratio) * (excess ** 0.5)
        return sign * min(aggressive, 1.0)

    def unrealized_pnl(self, pair: str, current_price: float) -> float:
        """Calculate unrealised P&L for a pair at current market price."""
        pos = self.get_position(pair)
        if pos.quantity == 0:
            return 0.0
        if pos.quantity > 0:
            return pos.quantity * (current_price - pos.avg_entry_price)
        else:
            return abs(pos.quantity) * (pos.avg_entry_price - current_price)

    def total_realized_pnl(self) -> float:
        """Sum of realized P&L across all pairs."""
        return sum(p.realized_pnl for p in self._positions.values())

    def status(self) -> dict[str, Any]:
        """Return current state for logging/debugging."""
        positions = {}
        for pair, pos in self._positions.items():
            positions[pair] = {
                "quantity": round(pos.quantity, 6),
                "avg_entry": round(pos.avg_entry_price, 6),
                "realized_pnl": round(pos.realized_pnl, 4),
                "total_bought": round(pos.total_bought, 6),
                "total_sold": round(pos.total_sold, 6),
            }
        return {
            "max_inventory": self._max_inventory,
            "soft_limit": self._soft_limit,
            "positions": positions,
            "total_realized_pnl": round(self.total_realized_pnl(), 4),
        }
