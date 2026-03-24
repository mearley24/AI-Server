"""Tests for the platform abstraction layer — Order, Position, and interface compliance."""

from __future__ import annotations

import pytest

from src.platforms.base import Order, PlatformClient, Position


class TestOrderModel:
    """Test the unified Order model."""

    def test_basic_order(self):
        order = Order(
            platform="kalshi",
            market_id="KXBTC-24DEC31-T100000",
            side="yes",
            size=5,
            price=0.65,
        )
        assert order.platform == "kalshi"
        assert order.market_id == "KXBTC-24DEC31-T100000"
        assert order.side == "yes"
        assert order.size == 5
        assert order.price == 0.65
        assert order.order_type == "limit"

    def test_market_order(self):
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            order_type="market",
        )
        assert order.price is None
        assert order.order_type == "market"

    def test_order_serialization(self):
        order = Order(
            platform="polymarket",
            market_id="0x123",
            side="buy",
            size=10.0,
            price=0.40,
        )
        d = order.model_dump()
        assert d["platform"] == "polymarket"
        assert d["market_id"] == "0x123"


class TestPositionModel:
    """Test the unified Position model."""

    def test_basic_position(self):
        pos = Position(
            platform="kalshi",
            market_id="KXTEMP-DEN-24-HIGH80",
            side="yes",
            size=10,
            avg_entry=0.45,
        )
        assert pos.platform == "kalshi"
        assert pos.size == 10
        assert pos.current_price == 0.0
        assert pos.unrealized_pnl == 0.0

    def test_position_with_pnl(self):
        pos = Position(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            avg_entry=0.50,
            current_price=0.55,
            unrealized_pnl=5.0,
        )
        assert pos.unrealized_pnl == 5.0

    def test_position_serialization(self):
        pos = Position(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=1000.0,
            avg_entry=0.10,
        )
        d = pos.model_dump()
        assert d["platform"] == "kraken"
        assert d["avg_entry"] == 0.10


class TestPlatformClientInterface:
    """Verify the ABC cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            PlatformClient()
