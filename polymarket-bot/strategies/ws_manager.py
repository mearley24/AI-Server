"""WebSocket Manager — persistent connections to Polymarket Market and User channels.

Provides real-time price updates to the exit engine and instant fill confirmations.
Runs in its own asyncio tasks alongside the main polling loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Callable, Coroutine, Optional

import structlog

logger = structlog.get_logger(__name__)

# Callback types
PriceUpdateCallback = Callable[[str, float, float, float], Coroutine[Any, Any, None]]
# (token_id, best_bid, best_ask, last_trade_price)

FillCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
# (fill event dict)

MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

PING_INTERVAL = 10  # seconds


class WebSocketManager:
    """Manages persistent WebSocket connections to Polymarket channels."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
    ) -> None:
        self._api_key = api_key or os.environ.get("POLY_BUILDER_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("POLY_BUILDER_API_SECRET", "")
        self._api_passphrase = api_passphrase or os.environ.get("POLY_BUILDER_API_PASSPHRASE", "")

        # Subscriptions
        self._market_token_ids: set[str] = set()
        self._user_condition_ids: set[str] = set()

        # Callbacks
        self._price_callbacks: list[PriceUpdateCallback] = []
        self._fill_callbacks: list[FillCallback] = []

        # State
        self._running = False
        self._market_task: Optional[asyncio.Task] = None
        self._user_task: Optional[asyncio.Task] = None
        self._market_ws: Any = None
        self._user_ws: Any = None

        # Latest prices cache
        self._latest_prices: dict[str, dict[str, float]] = {}

    # ── Public API ────────────────────────────────────────────────────

    def on_price_update(self, callback: PriceUpdateCallback) -> None:
        self._price_callbacks.append(callback)

    def on_fill(self, callback: FillCallback) -> None:
        self._fill_callbacks.append(callback)

    def subscribe_token(self, token_id: str) -> None:
        """Subscribe to market data for a token."""
        self._market_token_ids.add(token_id)
        if self._market_ws and self._running:
            asyncio.create_task(self._send_market_subscribe([token_id]))

    def unsubscribe_token(self, token_id: str) -> None:
        """Unsubscribe from market data for a token."""
        self._market_token_ids.discard(token_id)
        if self._market_ws and self._running:
            asyncio.create_task(self._send_market_unsubscribe([token_id]))

    def subscribe_condition(self, condition_id: str) -> None:
        """Subscribe to user updates for a condition."""
        self._user_condition_ids.add(condition_id)

    def unsubscribe_condition(self, condition_id: str) -> None:
        self._user_condition_ids.discard(condition_id)

    def get_latest_price(self, token_id: str) -> Optional[dict[str, float]]:
        """Get cached latest price for a token."""
        return self._latest_prices.get(token_id)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._market_task = asyncio.create_task(self._market_loop())
        if self._api_key:
            self._user_task = asyncio.create_task(self._user_loop())
        logger.info("ws_manager_started", market_tokens=len(self._market_token_ids))

    async def stop(self) -> None:
        self._running = False
        for task in (self._market_task, self._user_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("ws_manager_stopped")

    # ── Market Channel ────────────────────────────────────────────────

    async def _market_loop(self) -> None:
        """Persistent connection to market channel with auto-reconnect."""
        while self._running:
            try:
                import websockets
                async with websockets.connect(MARKET_WS_URL) as ws:
                    self._market_ws = ws
                    logger.info("ws_market_connected")

                    # Subscribe to all tracked tokens
                    if self._market_token_ids:
                        await self._send_market_subscribe(list(self._market_token_ids))

                    # Start ping task
                    ping_task = asyncio.create_task(self._ping_loop(ws))

                    try:
                        async for raw_msg in ws:
                            if not self._running:
                                break
                            try:
                                msg = json.loads(raw_msg) if isinstance(raw_msg, str) else json.loads(raw_msg.decode())
                                await self._handle_market_message(msg)
                            except json.JSONDecodeError:
                                pass
                            except Exception as exc:
                                logger.debug("ws_market_msg_error", error=str(exc))
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("ws_market_error", error=str(exc))
                self._market_ws = None
                if self._running:
                    await asyncio.sleep(5)  # reconnect delay

    async def _send_market_subscribe(self, token_ids: list[str]) -> None:
        if not self._market_ws or not token_ids:
            return
        try:
            msg = {
                "type": "subscribe",
                "channel": "market",
                "assets_ids": token_ids,
                "custom_feature_enabled": True,
                "features": ["best_bid_ask", "market_resolved", "last_trade_price"],
            }
            await self._market_ws.send(json.dumps(msg))
            logger.debug("ws_market_subscribed", tokens=len(token_ids))
        except Exception as exc:
            logger.debug("ws_market_subscribe_error", error=str(exc))

    async def _send_market_unsubscribe(self, token_ids: list[str]) -> None:
        if not self._market_ws or not token_ids:
            return
        try:
            msg = {
                "type": "unsubscribe",
                "channel": "market",
                "assets_ids": token_ids,
            }
            await self._market_ws.send(json.dumps(msg))
        except Exception:
            pass

    async def _handle_market_message(self, msg: dict[str, Any]) -> None:
        """Process market channel messages."""
        msg_type = msg.get("type", "")

        if msg_type in ("price_change", "last_trade_price"):
            # Extract price data
            for event in msg.get("data", [msg]):
                token_id = event.get("asset_id", event.get("token_id", ""))
                if not token_id:
                    continue

                best_bid = float(event.get("best_bid", 0))
                best_ask = float(event.get("best_ask", 0))
                last_price = float(event.get("last_trade_price", event.get("price", 0)))

                self._latest_prices[token_id] = {
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "last_trade_price": last_price,
                    "mid": (best_bid + best_ask) / 2 if best_bid and best_ask else last_price,
                    "ts": time.time(),
                }

                for cb in self._price_callbacks:
                    try:
                        await cb(token_id, best_bid, best_ask, last_price)
                    except Exception:
                        pass

        elif msg_type == "market_resolved":
            for event in msg.get("data", [msg]):
                token_id = event.get("asset_id", "")
                if token_id:
                    self._latest_prices[token_id] = {
                        "resolved": True,
                        "winning_price": float(event.get("price", 0)),
                        "ts": time.time(),
                    }

    # ── User Channel ──────────────────────────────────────────────────

    async def _user_loop(self) -> None:
        """Persistent connection to user channel with auth."""
        while self._running:
            try:
                import websockets
                async with websockets.connect(USER_WS_URL) as ws:
                    self._user_ws = ws
                    logger.info("ws_user_connected")

                    # Authenticate
                    auth_msg = {
                        "type": "auth",
                        "apiKey": self._api_key,
                        "secret": self._api_secret,
                        "passphrase": self._api_passphrase,
                    }
                    await ws.send(json.dumps(auth_msg))

                    # Subscribe to tracked conditions
                    if self._user_condition_ids:
                        sub_msg = {
                            "type": "subscribe",
                            "channel": "user",
                            "markets": list(self._user_condition_ids),
                        }
                        await ws.send(json.dumps(sub_msg))

                    ping_task = asyncio.create_task(self._ping_loop(ws))

                    try:
                        async for raw_msg in ws:
                            if not self._running:
                                break
                            try:
                                msg = json.loads(raw_msg) if isinstance(raw_msg, str) else json.loads(raw_msg.decode())
                                await self._handle_user_message(msg)
                            except Exception:
                                pass
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("ws_user_error", error=str(exc))
                self._user_ws = None
                if self._running:
                    await asyncio.sleep(5)

    async def _handle_user_message(self, msg: dict[str, Any]) -> None:
        """Process user channel messages (order fills, etc.)."""
        msg_type = msg.get("type", "")

        if msg_type in ("trade", "order_fill"):
            for cb in self._fill_callbacks:
                try:
                    await cb(msg)
                except Exception:
                    pass

    # ── Ping ──────────────────────────────────────────────────────────

    async def _ping_loop(self, ws) -> None:
        """Send PING every 10 seconds to keep connection alive."""
        while True:
            try:
                await asyncio.sleep(PING_INTERVAL)
                await ws.send("PING")
            except asyncio.CancelledError:
                break
            except Exception:
                break
