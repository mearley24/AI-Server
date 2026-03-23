"""Kalshi prediction market client — RSA-PSS auth, REST + WebSocket.

Implements the PlatformClient interface for Kalshi's CFTC-regulated
prediction market exchange.

Authentication uses RSA-PSS asymmetric key signing:
  - Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
  - Signature = RSA-PSS SHA-256 over "{timestamp}{METHOD}{path_without_query}"
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import structlog

from src.paper_ledger import PaperLedger, PaperTrade
from src.platforms.base import Order, PlatformClient, Position

logger = structlog.get_logger(__name__)

# Environment URLs
KALSHI_URLS = {
    "production": {
        "rest": "https://api.elections.kalshi.com/trade-api/v2",
        "ws": "wss://api.elections.kalshi.com/trade-api/ws/v2",
    },
    "demo": {
        "rest": "https://demo-api.kalshi.co/trade-api/v2",
        "ws": "wss://demo-api.kalshi.co/trade-api/ws/v2",
    },
}


def _load_private_key(key_path: str | Path):
    """Load an RSA private key from a PEM file."""
    from cryptography.hazmat.primitives import serialization

    path = Path(key_path)
    if not path.exists():
        raise FileNotFoundError(f"Kalshi private key not found: {path}")
    with path.open("rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _create_signature(private_key: Any, timestamp_ms: str, method: str, path: str) -> str:
    """Create RSA-PSS SHA-256 signature for Kalshi API request."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    path_clean = path.split("?")[0]
    message = f"{timestamp_ms}{method}{path_clean}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


class KalshiClient(PlatformClient):
    """Kalshi prediction market client with RSA-PSS authentication."""

    def __init__(
        self,
        api_key_id: str,
        private_key_path: str,
        environment: str = "demo",
        dry_run: bool = True,
        paper_ledger: Optional[PaperLedger] = None,
    ) -> None:
        self._api_key_id = api_key_id
        self._private_key_path = private_key_path
        self._environment = environment
        self._dry_run = dry_run
        self._paper_ledger = paper_ledger
        self._private_key: Any = None
        self._http: Optional[httpx.AsyncClient] = None
        self._ws_task: Optional[asyncio.Task] = None

        urls = KALSHI_URLS.get(environment, KALSHI_URLS["demo"])
        self._base_url = urls["rest"]
        self._ws_url = urls["ws"]

    @property
    def platform_name(self) -> str:
        return "kalshi"

    @property
    def is_dry_run(self) -> bool:
        return self._dry_run

    def _get_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Generate authenticated headers for a request."""
        timestamp_ms = str(int(time.time() * 1000))
        sign_path = urlparse(self._base_url + path).path
        signature = _create_signature(self._private_key, timestamp_ms, method, sign_path)
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make an authenticated request to the Kalshi API."""
        if not self._http or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)

        headers = self._get_auth_headers(method, path)
        url = f"{self._base_url}{path}"

        if method == "GET":
            resp = await self._http.get(url, headers=headers, params=params)
        elif method == "POST":
            resp = await self._http.post(url, headers=headers, json=body)
        elif method == "DELETE":
            resp = await self._http.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        return resp.json()

    async def connect(self) -> bool:
        """Load private key and verify connectivity."""
        try:
            self._private_key = _load_private_key(self._private_key_path)
            self._http = httpx.AsyncClient(timeout=30.0)

            if self._dry_run:
                logger.info(
                    "kalshi_connected_dry_run",
                    environment=self._environment,
                    key_id=self._api_key_id[:8] + "...",
                )
                return True

            # Verify by fetching balance
            result = await self._request("GET", "/portfolio/balance")
            balance_dollars = result.get("balance", 0) / 100
            logger.info(
                "kalshi_connected",
                environment=self._environment,
                balance=f"${balance_dollars:.2f}",
            )
            return True
        except FileNotFoundError:
            logger.warning(
                "kalshi_key_not_found",
                path=self._private_key_path,
                msg="Kalshi client will operate in dry-run only",
            )
            self._dry_run = True
            return True
        except Exception as exc:
            logger.error("kalshi_connect_failed", error=str(exc))
            return False

    async def get_markets(self, **filters: Any) -> list[dict]:
        """Fetch open markets from Kalshi."""
        if self._dry_run and self._private_key is None:
            return []

        params: dict[str, Any] = {"status": filters.get("status", "open")}
        if "series_ticker" in filters:
            params["series_ticker"] = filters["series_ticker"]
        if "limit" in filters:
            params["limit"] = filters["limit"]
        if "cursor" in filters:
            params["cursor"] = filters["cursor"]

        try:
            result = await self._request("GET", "/markets", params=params)
            markets = result.get("markets", [])
            # Convert cents to dollars for display
            for m in markets:
                for key in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
                    cents_key = key + "_dollars"
                    if cents_key not in m and key in m:
                        m[cents_key] = m[key] / 100 if isinstance(m[key], (int, float)) else m[key]
            return markets
        except Exception as exc:
            logger.error("kalshi_get_markets_error", error=str(exc))
            return []

    async def get_orderbook(self, market_id: str) -> dict:
        """Fetch orderbook for a market ticker."""
        if self._dry_run and self._private_key is None:
            return {"yes": [], "no": []}

        try:
            result = await self._request("GET", f"/markets/{market_id}/orderbook")
            orderbook = result.get("orderbook_fp", result.get("orderbook", {}))
            # Kalshi only returns bids — yes_ask = 1.00 - no_bid
            return {
                "yes_bids": orderbook.get("yes_dollars", orderbook.get("yes", [])),
                "no_bids": orderbook.get("no_dollars", orderbook.get("no", [])),
                "ticker": market_id,
            }
        except Exception as exc:
            logger.error("kalshi_orderbook_error", ticker=market_id, error=str(exc))
            return {"yes_bids": [], "no_bids": [], "ticker": market_id}

    async def place_order(self, order: Order) -> dict:
        """Place an order on Kalshi."""
        if self._dry_run:
            paper_id = f"paper-kalshi-{uuid.uuid4().hex[:12]}"
            logger.info(
                "kalshi_paper_order",
                ticker=order.market_id,
                side=order.side,
                size=order.size,
                price=order.price,
            )
            if self._paper_ledger:
                self._paper_ledger.record(PaperTrade(
                    timestamp=time.time(),
                    strategy="kalshi",
                    market_id=order.market_id,
                    market_question=order.market_id,
                    side=order.side.upper(),
                    size=order.size,
                    price=order.price or 0.0,
                    signals={"platform": "kalshi", "order_type": order.order_type},
                ))
            return {"order_id": paper_id, "status": "paper"}

        # Map order types
        tif_map = {
            "limit": "good_till_canceled",
            "fok": "fill_or_kill",
            "ioc": "immediate_or_cancel",
            "market": "fill_or_kill",
        }

        # Kalshi prices are in cents (integer 1-99)
        price_cents = int((order.price or 0.50) * 100)
        price_cents = max(1, min(99, price_cents))

        body = {
            "ticker": order.market_id,
            "side": order.side.lower(),
            "action": "buy" if order.side.lower() in ("buy", "yes") else "sell",
            "count": int(order.size),
            "yes_price": price_cents,
            "client_order_id": str(uuid.uuid4()),
            "time_in_force": tif_map.get(order.order_type, "good_till_canceled"),
        }

        try:
            result = await self._request("POST", "/portfolio/orders", body=body)
            order_data = result.get("order", {})
            logger.info(
                "kalshi_order_placed",
                order_id=order_data.get("order_id"),
                ticker=order.market_id,
                side=order.side,
                price_cents=price_cents,
                count=int(order.size),
            )
            return order_data
        except Exception as exc:
            logger.error("kalshi_place_order_error", error=str(exc))
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending Kalshi order."""
        if self._dry_run:
            return True
        try:
            await self._request("DELETE", f"/portfolio/orders/{order_id}")
            logger.info("kalshi_order_cancelled", order_id=order_id)
            return True
        except Exception as exc:
            logger.error("kalshi_cancel_error", order_id=order_id, error=str(exc))
            return False

    async def get_positions(self) -> list[Position]:
        """Fetch open positions from Kalshi."""
        if self._dry_run and self._private_key is None:
            return []
        try:
            result = await self._request("GET", "/portfolio/positions")
            positions = []
            for p in result.get("market_positions", []):
                positions.append(Position(
                    platform="kalshi",
                    market_id=p.get("ticker", ""),
                    side="yes" if p.get("market_exposure", 0) > 0 else "no",
                    size=abs(float(p.get("total_traded", 0))),
                    avg_entry=float(p.get("realized_pnl", 0)),
                    current_price=0.0,
                    unrealized_pnl=0.0,
                ))
            return positions
        except Exception as exc:
            logger.error("kalshi_positions_error", error=str(exc))
            return []

    async def get_balance(self) -> dict:
        """Fetch account balance (returned in dollars)."""
        if self._dry_run and self._private_key is None:
            return {"balance": 0.0, "currency": "USD", "platform": "kalshi"}
        try:
            result = await self._request("GET", "/portfolio/balance")
            balance_cents = result.get("balance", 0)
            return {
                "balance": balance_cents / 100,
                "balance_cents": balance_cents,
                "currency": "USD",
                "platform": "kalshi",
            }
        except Exception as exc:
            logger.error("kalshi_balance_error", error=str(exc))
            return {"balance": 0.0, "currency": "USD", "platform": "kalshi"}

    async def subscribe_realtime(self, market_ids: list[str], callback: Any) -> None:
        """Subscribe to Kalshi WebSocket for real-time data."""
        if self._private_key is None:
            logger.warning("kalshi_ws_no_key", msg="Cannot connect WebSocket without private key")
            return

        async def _ws_loop() -> None:
            try:
                import websockets

                headers = self._get_auth_headers("GET", "/trade-api/ws/v2")
                # websockets uses 'extra_headers' or 'additional_headers' depending on version
                async with websockets.connect(self._ws_url, additional_headers=headers) as ws:
                    logger.info("kalshi_ws_connected")

                    # Subscribe to ticker for specified markets
                    subscribe_msg = {
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["ticker"],
                            "market_tickers": market_ids,
                        },
                    }
                    await ws.send(json.dumps(subscribe_msg))

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if callback:
                                await callback(data)
                        except json.JSONDecodeError:
                            continue
            except ImportError:
                logger.warning("websockets_not_installed")
            except Exception as exc:
                logger.error("kalshi_ws_error", error=str(exc))

        self._ws_task = asyncio.create_task(_ws_loop())

    async def get_event(self, event_ticker: str) -> dict:
        """Fetch event details with child markets."""
        try:
            return await self._request("GET", f"/events/{event_ticker}")
        except Exception as exc:
            logger.error("kalshi_event_error", event_ticker=event_ticker, error=str(exc))
            return {}

    async def get_market_history(self, ticker: str) -> dict:
        """Fetch price candlestick history for a market."""
        try:
            return await self._request("GET", f"/markets/{ticker}/candlesticks")
        except Exception as exc:
            logger.error("kalshi_history_error", ticker=ticker, error=str(exc))
            return {}

    async def close(self) -> None:
        """Shut down HTTP client and WebSocket."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        logger.info("kalshi_client_closed")
