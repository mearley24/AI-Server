"""Polymarket platform client — wraps the existing client.py as a PlatformClient.

This adapter delegates to the original PolymarketClient while conforming
to the unified PlatformClient interface used by the multi-platform system.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.client import PolymarketClient as LegacyPolymarketClient
from src.config import Settings
from src.platforms.base import Order, PlatformClient, Position

logger = structlog.get_logger(__name__)


class PolymarketPlatformClient(PlatformClient):
    """Adapter wrapping the existing Polymarket CLOB + Gamma client."""

    def __init__(self, settings: Settings, legacy_client: LegacyPolymarketClient) -> None:
        self._settings = settings
        self._legacy = legacy_client

    @property
    def platform_name(self) -> str:
        return "polymarket"

    @property
    def is_dry_run(self) -> bool:
        return self._settings.dry_run

    @property
    def legacy(self) -> LegacyPolymarketClient:
        """Access the underlying legacy client for strategy-specific calls."""
        return self._legacy

    async def connect(self) -> bool:
        return await self._legacy.health_check()

    async def get_markets(self, **filters: Any) -> list[dict]:
        limit = filters.get("limit", 100)
        active = filters.get("active", True)
        query = filters.get("query")
        if query:
            return await self._legacy.search_markets(query, limit=limit)
        return await self._legacy.get_markets(limit=limit, active=active)

    async def get_orderbook(self, market_id: str) -> dict:
        return await self._legacy.get_orderbook(market_id)

    async def place_order(self, order: Order) -> dict:
        if self.is_dry_run:
            logger.info("polymarket_paper_order", order=order.model_dump())
            return {"orderID": f"paper-poly-{order.market_id[:8]}", "status": "paper"}

        side_int = 0 if order.side.lower() in ("buy", "yes") else 1
        order_type_map = {"limit": "GTC", "fok": "FOK", "market": "FOK"}
        result = await self._legacy.place_order(
            token_id=order.market_id,
            price=order.price or 0.0,
            size=order.size,
            side=side_int,
            order_type=order_type_map.get(order.order_type, "GTC"),
        )
        return result

    async def cancel_order(self, order_id: str) -> bool:
        if self.is_dry_run:
            return True
        try:
            await self._legacy.cancel_order(order_id)
            return True
        except Exception as exc:
            logger.error("polymarket_cancel_failed", order_id=order_id, error=str(exc))
            return False

    async def get_positions(self) -> list[Position]:
        raw = await self._legacy.get_positions()
        positions = []
        for p in raw:
            positions.append(Position(
                platform="polymarket",
                market_id=p.get("asset", {}).get("token_id", ""),
                side=p.get("side", "unknown"),
                size=float(p.get("size", 0)),
                avg_entry=float(p.get("avgPrice", 0)),
                current_price=float(p.get("curPrice", 0)),
                unrealized_pnl=float(p.get("unrealizedPnl", 0)),
            ))
        return positions

    async def get_balance(self) -> dict:
        return await self._legacy.get_balance()

    async def subscribe_realtime(self, market_ids: list[str], callback: Any) -> None:
        # Polymarket real-time is handled by the existing OrderbookFeed
        logger.info("polymarket_realtime_handled_by_orderbook_feed")

    async def close(self) -> None:
        await self._legacy.close()
