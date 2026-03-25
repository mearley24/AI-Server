"""Polymarket CLOB, Gamma, and Relayer API clients."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac as hmac_mod
import time
from typing import Any

import httpx
import structlog

from src.config import Settings
from src.signer import SIDE_BUY, SIDE_SELL, OrderSigner

logger = structlog.get_logger(__name__)

# Order type constants
ORDER_TYPE_GTC = "GTC"  # Good Till Cancel
ORDER_TYPE_FOK = "FOK"  # Fill Or Kill
ORDER_TYPE_GTD = "GTD"  # Good Till Date


class PolymarketClient:
    """Unified client for Polymarket CLOB + Gamma APIs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clob_url = settings.clob_api_url.rstrip("/")
        self._gamma_url = settings.gamma_api_url.rstrip("/")
        self._signer: OrderSigner | None = None
        self._http = httpx.AsyncClient(timeout=30.0)

        # Builder (gasless) HMAC auth credentials
        self._api_key = settings.poly_builder_api_key
        self._api_secret = settings.poly_builder_api_secret
        self._api_passphrase = settings.poly_builder_api_passphrase
        self._builder_headers: dict[str, str] = {}  # populated per-request via _l2_headers

        if settings.poly_private_key:
            self._signer = OrderSigner(settings.poly_private_key, settings.chain_id)
            logger.info("signer_initialized", address=self._signer.address)

    @property
    def signer(self) -> OrderSigner | None:
        return self._signer

    @property
    def wallet_address(self) -> str:
        if self._signer:
            return self._signer.address
        return ""

    def _l2_headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        """Build Level-2 HMAC-signed headers for authenticated CLOB endpoints."""
        if not self._api_key or not self._api_secret:
            return {}
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + request_path
        if body:
            message += body
        try:
            secret_bytes = base64.urlsafe_b64decode(self._api_secret)
        except Exception:
            secret_bytes = self._api_secret.encode("utf-8")
        sig = hmac_mod.new(secret_bytes, message.encode("utf-8"), hashlib.sha256)
        signature = base64.urlsafe_b64encode(sig.digest()).decode("utf-8")
        headers = {
            "POLY_ADDRESS": self.wallet_address,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_API_KEY": self._api_key,
            "POLY_PASSPHRASE": self._api_passphrase,
        }
        return headers

    async def close(self) -> None:
        await self._http.aclose()

    # ── CLOB API ─────────────────────────────────────────────────────────

    async def get_orderbook(self, token_id: str) -> dict[str, Any]:
        """Fetch current orderbook for a token."""
        resp = await self._http.get(f"{self._clob_url}/book", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()

    async def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        resp = await self._http.get(f"{self._clob_url}/midpoint", params={"token_id": token_id})
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0.0))

    async def get_price(self, token_id: str, side: str = "buy") -> float:
        """Get best price for a token (buy or sell side)."""
        resp = await self._http.get(
            f"{self._clob_url}/price",
            params={"token_id": token_id, "side": side},
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0.0))

    async def get_last_trade_price(self, token_id: str) -> float:
        """Get last trade price for a token."""
        resp = await self._http.get(
            f"{self._clob_url}/last-trade-price",
            params={"token_id": token_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0.0))

    async def place_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: int,
        order_type: str = ORDER_TYPE_GTC,
    ) -> dict[str, Any]:
        """Build, sign, and place an order on the CLOB."""
        if not self._signer:
            raise RuntimeError("No signer configured — set POLY_PRIVATE_KEY")

        order, signature = self._signer.build_and_sign(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
        )

        payload = {
            "order": order,
            "signature": signature,
            "owner": self._settings.poly_safe_address or self._signer.address,
            "orderType": order_type,
        }

        headers = {**self._builder_headers}
        resp = await self._http.post(
            f"{self._clob_url}/order",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "order_placed",
            token_id=token_id,
            price=price,
            size=size,
            side="BUY" if side == SIDE_BUY else "SELL",
            order_type=order_type,
            order_id=result.get("orderID", ""),
        )
        return result

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order."""
        headers = {**self._builder_headers}
        resp = await self._http.delete(
            f"{self._clob_url}/order/{order_id}",
            headers=headers,
        )
        resp.raise_for_status()
        logger.info("order_cancelled", order_id=order_id)
        return resp.json()

    async def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel all open orders."""
        headers = {**self._builder_headers}
        resp = await self._http.delete(f"{self._clob_url}/orders", headers=headers)
        resp.raise_for_status()
        logger.info("all_orders_cancelled")
        return resp.json()

    async def get_open_orders(self, market: str | None = None) -> list[dict[str, Any]]:
        """Get all open orders, optionally filtered by market."""
        params: dict[str, str] = {}
        if market:
            params["market"] = market
        headers = {**self._builder_headers}
        resp = await self._http.get(f"{self._clob_url}/orders", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def get_trades(
        self, market: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get recent trades."""
        params: dict[str, Any] = {"limit": limit}
        if market:
            params["market"] = market
        # Build request path with query string for HMAC
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        request_path = f"/trades?{qs}" if qs else "/trades"
        headers = self._l2_headers("GET", request_path)
        resp = await self._http.get(f"{self._clob_url}/trades", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── Gamma API (market discovery) ─────────────────────────────────────

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch markets from the Gamma API."""
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "active": active,
            "closed": closed,
        }
        resp = await self._http.get(f"{self._gamma_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_market(self, condition_id: str) -> dict[str, Any]:
        """Fetch a single market by condition_id."""
        resp = await self._http.get(f"{self._gamma_url}/markets/{condition_id}")
        resp.raise_for_status()
        return resp.json()

    async def search_markets(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search markets by text query."""
        params = {"query": query, "limit": limit, "active": True}
        resp = await self._http.get(f"{self._gamma_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_events(self, limit: int = 100, active: bool = True) -> list[dict[str, Any]]:
        """Fetch events from Gamma API."""
        params: dict[str, Any] = {"limit": limit, "active": active}
        resp = await self._http.get(f"{self._gamma_url}/events", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Position helpers ─────────────────────────────────────────────────

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions from CLOB API."""
        if not self._signer:
            return []
        headers = {**self._builder_headers}
        try:
            resp = await self._http.get(
                f"{self._clob_url}/positions",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            logger.warning("positions_fetch_failed")
            return []

    async def get_balance(self) -> dict[str, Any]:
        """Get USDC balance info."""
        if not self._signer:
            return {"balance": 0.0}
        headers = {**self._builder_headers}
        try:
            resp = await self._http.get(f"{self._clob_url}/balance", headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            return {"balance": 0.0}

    # ── Utility ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check if the CLOB API is reachable."""
        try:
            resp = await self._http.get(f"{self._clob_url}/")
            return resp.status_code == 200
        except Exception:
            return False
