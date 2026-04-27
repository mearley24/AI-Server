"""Tests for the Crypto platform client — paper trading and CCXT integration."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from src.platforms.base import Order, Position
from src.platforms.crypto_client import CryptoClient, PaperTrader


# ── PaperTrader tests ──────────────────────────────────────────────────


class TestPaperTrader:
    """Test the paper trading simulator."""

    def test_place_market_order(self):
        trader = PaperTrader()
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        result = trader.place_order(order)

        assert result["id"].startswith("paper-crypto-")
        assert result["status"] == "closed"
        assert result["filled"] == 100.0
        assert result["side"] == "buy"

    def test_place_limit_order(self):
        trader = PaperTrader()
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=500.0,
            price=0.10,
            order_type="limit",
        )
        result = trader.place_order(order)

        assert result["status"] == "open"
        assert result["filled"] == 0.0

    def test_balance_deducted_on_buy(self):
        trader = PaperTrader()
        initial = trader.get_balance()["USD"]
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        trader.place_order(order)
        assert trader.get_balance()["USD"] == initial - 50.0  # 100 * 0.50

    def test_balance_credited_on_sell(self):
        trader = PaperTrader()
        initial = trader.get_balance()["USD"]
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="sell",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        trader.place_order(order)
        assert trader.get_balance()["USD"] == initial + 50.0

    def test_position_tracked(self):
        trader = PaperTrader()
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=200.0,
            price=0.50,
            order_type="market",
        )
        trader.place_order(order)

        positions = trader.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "XRP/USD"
        assert positions[0].side == "buy"
        assert positions[0].size == 200.0
        assert positions[0].entry_price == 0.50

    def test_cancel_order(self):
        trader = PaperTrader()
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=500.0,
            price=0.10,
            order_type="limit",
        )
        result = trader.place_order(order)
        order_id = result["id"]

        assert trader.cancel_order(order_id) is True
        assert trader._orders[order_id]["status"] == "canceled"

    def test_cancel_nonexistent_order(self):
        trader = PaperTrader()
        assert trader.cancel_order("fake-id-123") is False

    def test_paper_ledger_integration(self):
        mock_ledger = MagicMock()
        mock_ledger.record = MagicMock()

        trader = PaperTrader(paper_ledger=mock_ledger)
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        trader.place_order(order)

        mock_ledger.record.assert_called_once()
        trade = mock_ledger.record.call_args[0][0]
        assert trade.market_id == "XRP/USD"
        assert trade.side == "BUY"
        assert trade.size == 100.0


# ── CryptoClient tests ────────────────────────────────────────────────


class TestCryptoClient:
    """Test CryptoClient initialization and properties."""

    def test_platform_name(self):
        client = CryptoClient(exchange_id="kraken", dry_run=True)
        assert client.platform_name == "kraken"

    def test_dry_run_default(self):
        client = CryptoClient(dry_run=True)
        assert client.is_dry_run is True

    def test_paper_trader_created_in_dry_run(self):
        client = CryptoClient(dry_run=True)
        assert client._paper_trader is not None

    def test_no_paper_trader_in_live(self):
        client = CryptoClient(dry_run=False)
        assert client._paper_trader is None


_KRAKEN_ENABLED_ENV = {
    "KRAKEN_MM_ENABLED": "true",
    "CRYPTO_TRADING_ENABLED": "true",
}


class TestCryptoClientDryRun:
    """Test CryptoClient with dry-run paper trading."""

    @pytest.mark.asyncio
    @patch.dict("os.environ", _KRAKEN_ENABLED_ENV)
    async def test_place_order_dry_run(self):
        client = CryptoClient(dry_run=True)
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        result = await client.place_order(order)
        assert result["id"].startswith("paper-crypto-")
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    @patch.dict("os.environ", _KRAKEN_ENABLED_ENV)
    async def test_cancel_order_dry_run(self):
        client = CryptoClient(dry_run=True)
        # Place an order first
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=500.0,
            price=0.10,
            order_type="limit",
        )
        result = await client.place_order(order)
        assert await client.cancel_order(result["id"]) is True

    @pytest.mark.asyncio
    @patch.dict("os.environ", _KRAKEN_ENABLED_ENV)
    async def test_get_positions_dry_run(self):
        client = CryptoClient(dry_run=True)
        order = Order(
            platform="kraken",
            market_id="XRP/USD",
            side="buy",
            size=100.0,
            price=0.50,
            order_type="market",
        )
        await client.place_order(order)

        positions = await client.get_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], Position)
        assert positions[0].market_id == "XRP/USD"

    @pytest.mark.asyncio
    async def test_get_balance_dry_run(self):
        client = CryptoClient(dry_run=True)
        balance = await client.get_balance()
        assert "balance" in balance
        assert balance["balance"]["USD"] == 10_000.0
        assert balance["dry_run"] is True

    @pytest.mark.asyncio
    async def test_get_markets_no_exchange(self):
        client = CryptoClient(dry_run=True)
        markets = await client.get_markets()
        assert markets == []

    @pytest.mark.asyncio
    async def test_get_orderbook_no_exchange(self):
        client = CryptoClient(dry_run=True)
        book = await client.get_orderbook("XRP/USD")
        assert book["bids"] == []
        assert book["asks"] == []

    @pytest.mark.asyncio
    async def test_close_no_error(self):
        client = CryptoClient(dry_run=True)
        await client.close()  # should not raise
