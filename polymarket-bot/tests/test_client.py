"""Tests for the Polymarket API client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client import ORDER_TYPE_FOK, ORDER_TYPE_GTC, PolymarketClient
from src.config import Settings


@pytest.fixture
def settings():
    return Settings(
        poly_private_key="a" * 64,
        poly_safe_address="0x" + "b" * 40,
        poly_builder_api_key="test-key",
        poly_builder_api_secret="test-secret",
        poly_builder_api_passphrase="test-pass",
    )


@pytest.fixture
def client(settings):
    return PolymarketClient(settings)


class TestPolymarketClient:
    def test_init_with_credentials(self, client, settings):
        """Client initializes signer when private key is provided."""
        assert client.signer is not None
        assert client.wallet_address != ""
        assert client.wallet_address.startswith("0x")

    def test_init_without_credentials(self):
        """Client works without credentials (read-only mode)."""
        settings = Settings()
        c = PolymarketClient(settings)
        assert c.signer is None
        assert c.wallet_address == ""

    def test_builder_headers(self, client):
        """Builder headers are set when API key is provided."""
        assert client._builder_headers["POLY-API-KEY"] == "test-key"
        assert client._builder_headers["POLY-API-SECRET"] == "test-secret"
        assert client._builder_headers["POLY-API-PASSPHRASE"] == "test-pass"

    @pytest.mark.asyncio
    async def test_get_orderbook(self, client):
        """Test orderbook fetch with mocked HTTP."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bids": [], "asks": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await client.get_orderbook("123456")
            assert "bids" in result
            assert "asks" in result

    @pytest.mark.asyncio
    async def test_get_midpoint(self, client):
        """Test midpoint price fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"mid": "0.55"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            mid = await client.get_midpoint("123456")
            assert mid == 0.55

    @pytest.mark.asyncio
    async def test_place_order(self, client):
        """Test order placement with signing."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"orderID": "order-123"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.place_order(
                token_id="12345",
                price=0.45,
                size=10.0,
                side=0,
                order_type=ORDER_TYPE_GTC,
            )
            assert result["orderID"] == "order-123"

    @pytest.mark.asyncio
    async def test_place_order_no_signer(self):
        """Placing an order without a signer raises RuntimeError."""
        settings = Settings()
        c = PolymarketClient(settings)
        with pytest.raises(RuntimeError, match="No signer configured"):
            await c.place_order("123", 0.5, 10.0, 0)

    @pytest.mark.asyncio
    async def test_search_markets(self, client):
        """Test market search via Gamma API."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"question": "Will BTC go up?", "active": True, "tokens": []}
        ]
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            results = await client.search_markets("bitcoin")
            assert len(results) == 1
            assert results[0]["question"] == "Will BTC go up?"

    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Test health check returns True on 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, client):
        """Test health check returns False on exception."""
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=Exception("down")):
            assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_cancel_order(self, client):
        """Test order cancellation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"canceled": True}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "delete", new_callable=AsyncMock, return_value=mock_response):
            result = await client.cancel_order("order-123")
            assert result["canceled"] is True

    @pytest.mark.asyncio
    async def test_get_positions_no_signer(self):
        """Returns empty list when no signer configured."""
        settings = Settings()
        c = PolymarketClient(settings)
        positions = await c.get_positions()
        assert positions == []
