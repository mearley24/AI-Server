"""Flash crash strategy — monitors orderbook for sudden drops and buys the dip.

When a token's price drops by >= threshold within a short window (e.g. 0.30
in 10 seconds), the strategy assumes a flash crash has occurred and buys,
expecting a reversion to a more reasonable level.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner, ScannedMarket
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY, SIDE_SELL
from src.websocket_client import OrderbookFeed, PriceSnapshot
from strategies.base import BaseStrategy, StrategyState

logger = structlog.get_logger(__name__)


class FlashCrashStrategy(BaseStrategy):
    """Detects flash crashes via WebSocket orderbook and buys the dip.

    Logic:
    1. Subscribe to orderbook feeds for all scanned markets.
    2. On each price update, check if the price has dropped >= threshold
       within the configured time window.
    3. If crash detected, immediately buy at market (FOK order).
    4. Manage the position with take-profit and stop-loss.
    """

    name = "flash_crash"
    description = "Monitors orderbook for sudden price drops and buys crashed tokens"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = 15.0
        self._positions: dict[str, dict[str, Any]] = {}  # token_id -> position
        self._monitored_tokens: dict[str, ScannedMarket] = {}  # token_id -> market
        self._cooldowns: dict[str, float] = {}  # token_id -> last trigger time
        self._cooldown_seconds: float = 60.0  # Don't re-trigger within 60s
        self._last_scan: float = 0.0
        self._scan_interval: float = 120.0

        self._params = {
            "drop_threshold": settings.flash_crash_drop_threshold,
            "window_seconds": settings.flash_crash_window_seconds,
            "take_profit": settings.flash_crash_take_profit,
            "stop_loss": settings.flash_crash_stop_loss,
            "size": settings.poly_default_size,
            "tokens": settings.stink_bid_markets,
            "timeframes": ["5m", "15m", "1h", "spot"],
        }

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start strategy and register WebSocket callback."""
        await super().start(params)
        self._orderbook.on_price_update(self._on_price_update)

    async def stop(self) -> None:
        """Stop strategy and exit all positions."""
        # Exit all open positions at market
        for token_id in list(self._positions.keys()):
            await self._exit_position(token_id, "strategy_stop")

        await super().stop()

    async def on_tick(self) -> None:
        """Periodic tick: rescan markets, subscribe to new feeds, manage positions."""
        now = time.time()

        # Periodically rescan for new markets
        if now - self._last_scan > self._scan_interval:
            await self._scan_and_subscribe()
            self._last_scan = now

        # Manage open positions
        await self._manage_positions()

        logger.info(
            "flash_crash_tick_complete",
            monitored_tokens=len(self._monitored_tokens),
            open_positions=len(self._positions),
            tick=self._tick_count,
        )

    async def _scan_and_subscribe(self) -> None:
        """Scan for markets and subscribe to their orderbook feeds."""
        result = await self._scanner.scan()
        timeframes = self._params["timeframes"]
        tokens = self._params["tokens"]

        for market in result.markets:
            if market.timeframe not in timeframes:
                continue
            if market.token not in tokens:
                continue

            # Subscribe to YES token orderbook if not already
            if market.token_id_yes not in self._monitored_tokens:
                self._monitored_tokens[market.token_id_yes] = market
                self._orderbook.subscribe(market.token_id_yes)
                logger.info(
                    "flash_crash_subscribed",
                    market=market.question,
                    token_id=market.token_id_yes,
                )

    async def _on_price_update(self, token_id: str, snapshot: PriceSnapshot) -> None:
        """WebSocket callback — check for flash crash on every price update."""
        if self._state != StrategyState.RUNNING:
            return

        if token_id not in self._monitored_tokens:
            return

        # Skip if we already have a position in this token
        if token_id in self._positions:
            return

        # Check cooldown
        now = time.time()
        last_trigger = self._cooldowns.get(token_id, 0)
        if now - last_trigger < self._cooldown_seconds:
            return

        # Check for flash crash: price drop >= threshold within window
        window = self._params["window_seconds"]
        threshold = self._params["drop_threshold"]

        price_change = self._orderbook.get_price_change(token_id, window)
        if price_change is None:
            return

        # Negative price_change means drop
        if price_change <= -threshold:
            market = self._monitored_tokens[token_id]
            current_mid = snapshot["mid"]

            logger.info(
                "flash_crash_detected",
                market=market.question,
                token=market.token,
                price_drop=abs(price_change),
                current_mid=current_mid,
                window_seconds=window,
            )

            await self._execute_crash_buy(token_id, market, current_mid)
            self._cooldowns[token_id] = now

    async def _execute_crash_buy(
        self, token_id: str, market: ScannedMarket, current_price: float
    ) -> None:
        """Execute a buy order when a flash crash is detected, via guarded path."""
        size = self._params["size"]

        order = await self._place_market_order(
            token_id=token_id,
            market=market.question,
            price=current_price,
            size=size,
            side=SIDE_BUY,
            order_type="FOK",
        )
        if not order:
            logger.warning("flash_crash_buy_blocked", market=market.question)
            return

        self._positions[token_id] = {
            "market": market,
            "entry_price": current_price,
            "size": size,
            "order_id": order.order_id,
            "bought_at": time.time(),
        }
        logger.info(
            "flash_crash_bought",
            market=market.question,
            entry_price=current_price,
            size=size,
            order_id=order.order_id,
            dry_run=self._settings.dry_run,
        )

    async def _manage_positions(self) -> None:
        """Check take-profit and stop-loss for open positions."""
        take_profit = self._params["take_profit"]
        stop_loss = self._params["stop_loss"]

        for token_id, pos in list(self._positions.items()):
            try:
                current_price = await self._client.get_midpoint(token_id)
            except Exception:
                continue

            entry_price = pos["entry_price"]
            market: ScannedMarket = pos["market"]

            # Take profit
            if current_price >= entry_price + take_profit:
                logger.info(
                    "flash_crash_take_profit",
                    market=market.question,
                    entry=entry_price,
                    current=current_price,
                    profit=current_price - entry_price,
                )
                await self._exit_position(token_id, "take_profit")
                continue

            # Stop loss
            if current_price <= entry_price - stop_loss:
                logger.info(
                    "flash_crash_stop_loss",
                    market=market.question,
                    entry=entry_price,
                    current=current_price,
                    loss=entry_price - current_price,
                )
                await self._exit_position(token_id, "stop_loss")
                continue

    async def _exit_position(self, token_id: str, reason: str) -> None:
        """Exit a position by selling at current price, via guarded path."""
        pos = self._positions.get(token_id)
        if not pos:
            return

        try:
            current_price = await self._client.get_midpoint(token_id)
        except Exception as exc:
            logger.error("flash_crash_exit_price_error", token_id=token_id, error=str(exc))
            if token_id in self._positions:
                del self._positions[token_id]
            return

        order = await self._place_market_order(
            token_id=token_id,
            market=pos["market"].question,
            price=current_price,
            size=pos["size"],
            side=SIDE_SELL,
            order_type="FOK",
        )
        if order:
            logger.info(
                "flash_crash_exited",
                market=pos["market"].question,
                reason=reason,
                exit_price=current_price,
                entry_price=pos["entry_price"],
                pnl=current_price - pos["entry_price"],
                dry_run=self._settings.dry_run,
            )

        if token_id in self._positions:
            del self._positions[token_id]
