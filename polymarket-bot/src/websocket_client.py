"""Real-time orderbook WebSocket feed from Polymarket CLOB."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog
import websockets

from src.config import Settings

logger = structlog.get_logger(__name__)

# Snapshot of a token's orderbook at a point in time
PriceSnapshot = dict[str, float]  # {"best_bid": 0.45, "best_ask": 0.55, "mid": 0.50, "ts": ...}

# Callback type for price updates
PriceCallback = Callable[[str, PriceSnapshot], Coroutine[Any, Any, None]]


class OrderbookFeed:
    """WebSocket client that maintains live orderbook snapshots.

    Subscribes to token-level orderbook channels and tracks:
    - Current best bid/ask/mid for each token
    - Price history (ring buffer) for flash-crash detection
    """

    def __init__(self, settings: Settings, history_depth: int = 120) -> None:
        self._ws_url = settings.ws_url
        self._subscriptions: set[str] = set()
        self._callbacks: list[PriceCallback] = []
        self._ws: Any = None
        self._running = False
        self._task: asyncio.Task | None = None

        # Current orderbook state per token_id
        self.books: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"bids": [], "asks": [], "best_bid": 0.0, "best_ask": 0.0, "mid": 0.0}
        )

        # Price history ring buffer: token_id -> list of (timestamp, mid_price)
        self._history_depth = history_depth
        self.price_history: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def subscribe(self, token_id: str) -> None:
        """Add a token to the subscription set."""
        self._subscriptions.add(token_id)

    def unsubscribe(self, token_id: str) -> None:
        """Remove a token from the subscription set."""
        self._subscriptions.discard(token_id)

    def on_price_update(self, callback: PriceCallback) -> None:
        """Register a callback for price updates."""
        self._callbacks.append(callback)

    def get_snapshot(self, token_id: str) -> PriceSnapshot:
        """Get the current price snapshot for a token."""
        book = self.books[token_id]
        return {
            "best_bid": book["best_bid"],
            "best_ask": book["best_ask"],
            "mid": book["mid"],
            "ts": time.time(),
        }

    def get_price_change(self, token_id: str, window_seconds: float) -> float | None:
        """Calculate price change over a time window. Returns delta or None if insufficient data."""
        history = self.price_history.get(token_id, [])
        if len(history) < 2:
            return None

        now = time.time()
        cutoff = now - window_seconds

        # Find the oldest price within the window
        old_price = None
        for ts, price in history:
            if ts >= cutoff:
                old_price = price
                break

        if old_price is None or old_price == 0:
            return None

        current_price = history[-1][1]
        return current_price - old_price

    async def start(self) -> None:
        """Start the WebSocket connection and message processing loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("orderbook_feed_started", subscriptions=len(self._subscriptions))

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("orderbook_feed_stopped")

    async def _run_loop(self) -> None:
        """Main reconnect loop with exponential backoff capped at 5 minutes.

        After 10 consecutive failures, reduces to checking every 10 minutes
        with a single warning log line instead of error spam.
        """
        backoff = 1.0
        consecutive_failures = 0
        _MAX_FAILURES_FOR_DEGRADED = 10
        _BACKOFF_CAP = 300.0  # 5 minutes
        _DEGRADED_INTERVAL = 600.0  # 10 minutes

        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0
                    consecutive_failures = 0
                    logger.info("ws_connected", url=self._ws_url)

                    # Subscribe to all tracked tokens in one batch
                    if self._subscriptions:
                        await self._send_subscribe_batch(ws, list(self._subscriptions))

                    # Process messages
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw_msg)
                            await self._handle_message(msg)
                        except json.JSONDecodeError:
                            logger.warning("ws_invalid_json", data=str(raw_msg)[:200])
                        except Exception as exc:
                            logger.error("ws_message_error", error=str(exc))

            except websockets.ConnectionClosed as exc:
                consecutive_failures += 1
                if consecutive_failures <= _MAX_FAILURES_FOR_DEGRADED:
                    logger.warning("ws_disconnected", code=exc.code, reason=exc.reason)
            except Exception as exc:
                consecutive_failures += 1
                if consecutive_failures <= _MAX_FAILURES_FOR_DEGRADED:
                    logger.error("ws_error", error=str(exc), consecutive_failures=consecutive_failures)
                elif consecutive_failures == _MAX_FAILURES_FOR_DEGRADED + 1:
                    logger.warning(
                        "ws_degraded_mode",
                        msg="Polymarket WS: too many failures, reducing retry to every 10 min",
                        consecutive_failures=consecutive_failures,
                    )

            if self._running:
                if consecutive_failures > _MAX_FAILURES_FOR_DEGRADED:
                    await asyncio.sleep(_DEGRADED_INTERVAL)
                else:
                    logger.info("ws_reconnecting", backoff=backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_CAP)

    async def _send_subscribe(self, ws: Any, token_id: str) -> None:
        """Send a subscription message for a single token."""
        msg = {
            "assets_ids": [token_id],
            "type": "market",
            "custom_feature_enabled": True,
        }
        await ws.send(json.dumps(msg))
        logger.debug("ws_subscribed", token_id=token_id)

    async def _send_subscribe_batch(self, ws: Any, token_ids: list[str]) -> None:
        """Send a batch subscription for multiple tokens."""
        msg = {
            "assets_ids": token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }
        await ws.send(json.dumps(msg))
        logger.info("ws_subscribed_batch", count=len(token_ids))

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Process an incoming WebSocket message."""
        msg_type = msg.get("type", "")

        if msg_type in ("book", "book_update"):
            await self._handle_book_update(msg)
        elif msg_type == "error":
            logger.error("ws_server_error", message=msg.get("message", ""))

    async def _handle_book_update(self, msg: dict[str, Any]) -> None:
        """Update the local orderbook from a WebSocket message."""
        token_id = msg.get("asset_id", "")
        if not token_id:
            return

        book = self.books[token_id]

        # Update bids/asks if present
        if "bids" in msg:
            book["bids"] = msg["bids"]
        if "asks" in msg:
            book["asks"] = msg["asks"]

        # Recalculate best bid/ask/mid
        bids = book["bids"]
        asks = book["asks"]

        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        mid = (best_bid + best_ask) / 2.0 if bids and asks else 0.0

        book["best_bid"] = best_bid
        book["best_ask"] = best_ask
        book["mid"] = mid

        # Record in history
        now = time.time()
        history = self.price_history[token_id]
        history.append((now, mid))

        # Trim history to depth
        if len(history) > self._history_depth:
            self.price_history[token_id] = history[-self._history_depth :]

        # Fire callbacks
        snapshot: PriceSnapshot = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "ts": now,
        }
        for cb in self._callbacks:
            try:
                await cb(token_id, snapshot)
            except Exception as exc:
                logger.error("price_callback_error", error=str(exc))
