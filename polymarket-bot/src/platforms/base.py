"""Abstract base class for all trading platform clients.

Every platform (Polymarket, Kalshi, Crypto exchanges) implements this
interface so that strategies, the signal bus, and the API routes can
interact with any platform through a single contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class Order(BaseModel):
    """Unified order representation across platforms."""

    platform: str  # "kalshi", "polymarket", "kraken", "coinbase"
    market_id: str  # ticker or symbol
    side: str  # "buy"/"sell" or "yes"/"no"
    size: float  # contracts or token amount
    price: Optional[float] = None  # limit price (None = market order)
    order_type: str = "limit"  # "limit", "market", "fok", "ioc"
    order_id: Optional[str] = None  # assigned after placement


class Position(BaseModel):
    """Unified position representation across platforms."""

    platform: str
    market_id: str
    side: str
    size: float
    avg_entry: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0


class PlatformClient(ABC):
    """Abstract base for all trading platform clients."""

    @abstractmethod
    async def connect(self) -> bool:
        """Authenticate and connect to the platform."""

    @abstractmethod
    async def get_markets(self, **filters: Any) -> list[dict]:
        """List available markets/symbols."""

    @abstractmethod
    async def get_orderbook(self, market_id: str) -> dict:
        """Get current orderbook for a market."""

    @abstractmethod
    async def place_order(self, order: Order) -> dict:
        """Place a trade. Returns order confirmation."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open positions."""

    @abstractmethod
    async def get_balance(self) -> dict:
        """Get account balance."""

    @abstractmethod
    async def subscribe_realtime(self, market_ids: list[str], callback: Any) -> None:
        """Subscribe to real-time price/orderbook updates via WebSocket."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return platform identifier string."""

    @property
    @abstractmethod
    def is_dry_run(self) -> bool:
        """Whether this client is in paper trading mode."""

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
