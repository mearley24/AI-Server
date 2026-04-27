"""Stink bid strategy — places low limit orders on high-leverage short-term markets.

The idea: crypto 5m/15m markets on Polymarket often have wild swings.
A "stink bid" is a limit order placed well below current price, hoping to
catch a flash dip. If filled, the position is managed with take-profit and
stop-loss levels.
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
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy, OpenOrder, StrategyState

logger = structlog.get_logger(__name__)


class StinkBidStrategy(BaseStrategy):
    """Places low-ball limit buy orders on 5m/15m crypto markets.

    Logic:
    1. Scan for active 5m/15m BTC/ETH/SOL markets.
    2. For each market, get the current YES token price.
    3. Place a limit buy at (current_price - drop_threshold).
    4. If filled, monitor for take-profit or stop-loss exit.
    5. When market expires or exits, clean up.
    """

    name = "stink_bid"
    description = "Low-ball limit orders catching flash crashes on 5m/15m crypto markets"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = 10.0  # Check every 10 seconds
        self._active_bids: dict[str, dict[str, Any]] = {}  # token_id -> bid info
        self._filled_positions: dict[str, dict[str, Any]] = {}  # token_id -> position info
        self._last_scan: float = 0.0
        self._scan_interval: float = 120.0  # Rescan markets every 2 min

        # Default params from settings
        self._params = {
            "drop_threshold": settings.stink_bid_drop_threshold,
            "take_profit": settings.stink_bid_take_profit,
            "stop_loss": settings.stink_bid_stop_loss,
            "size": settings.poly_default_size,
            "tokens": settings.stink_bid_markets,
            "timeframes": ["5m", "15m", "1h", "spot"],
        }

    async def on_tick(self) -> None:
        """Main strategy tick: scan markets, place bids, manage fills."""
        now = time.time()

        # Periodically rescan for new markets
        if now - self._last_scan > self._scan_interval:
            await self._scan_and_place_bids()
            self._last_scan = now

        # Check if any bids were filled
        await self._check_fills()

        # Manage open positions (take-profit / stop-loss)
        await self._manage_positions()

        logger.info(
            "stink_bid_tick_complete",
            active_bids=len(self._active_bids),
            filled_positions=len(self._filled_positions),
            tick=self._tick_count,
        )

    async def _scan_and_place_bids(self) -> None:
        """Scan for markets and place stink bids on new ones."""
        result = await self._scanner.scan()

        drop_threshold = self._params["drop_threshold"]
        size = self._params["size"]
        timeframes = self._params["timeframes"]
        tokens = self._params["tokens"]

        for market in result.markets:
            # Only target configured timeframes and tokens
            if market.timeframe not in timeframes:
                continue
            if market.token not in tokens:
                continue

            # Skip if we already have a bid on this market
            if market.token_id_yes in self._active_bids:
                continue
            if market.token_id_yes in self._filled_positions:
                continue

            # Get current price
            try:
                current_price = await self._client.get_midpoint(market.token_id_yes)
            except Exception:
                current_price = market.last_price_yes

            if current_price <= 0.01:
                continue

            # Calculate stink bid price: current - threshold, floored at 0.01
            bid_price = max(round(current_price - drop_threshold, 2), 0.01)

            # Don't bid above 0.50 (these are binary markets)
            if bid_price > 0.50:
                continue

            # Place the limit order
            order = await self._place_limit_order(
                token_id=market.token_id_yes,
                market=market.question,
                price=bid_price,
                size=size,
                side=SIDE_BUY,
            )

            if order:
                self._active_bids[market.token_id_yes] = {
                    "order": order,
                    "market": market,
                    "current_price_at_bid": current_price,
                    "bid_price": bid_price,
                    "placed_at": time.time(),
                }
                logger.info(
                    "stink_bid_placed",
                    market=market.question,
                    token=market.token,
                    timeframe=market.timeframe,
                    current_price=current_price,
                    bid_price=bid_price,
                    size=size,
                )

    async def _check_fills(self) -> None:
        """Check if any of our limit orders were filled."""
        for token_id, bid_info in list(self._active_bids.items()):
            order: OpenOrder = bid_info["order"]
            market: ScannedMarket = bid_info["market"]

            try:
                # Check if order is still open
                open_orders = await self._client.get_open_orders()
                order_ids = {o.get("id", o.get("orderID", "")) for o in open_orders}

                if order.order_id not in order_ids:
                    # Order is no longer open — either filled or expired
                    try:
                        current_price = await self._client.get_midpoint(token_id)
                    except Exception:
                        current_price = 0.0

                    if current_price > 0 and current_price <= bid_info["bid_price"] * 1.05:
                        # Likely filled — price near our bid
                        self._record_fill(order, bid_info["bid_price"])
                        self._filled_positions[token_id] = {
                            "market": market,
                            "entry_price": bid_info["bid_price"],
                            "size": order.size,
                            "filled_at": time.time(),
                        }
                        logger.info(
                            "stink_bid_filled",
                            market=market.question,
                            entry_price=bid_info["bid_price"],
                            size=order.size,
                        )

                    # Clean up from active bids either way
                    del self._active_bids[token_id]
                    if order.order_id in self._open_orders:
                        del self._open_orders[order.order_id]

            except Exception as exc:
                logger.error("check_fills_error", token_id=token_id, error=str(exc))

    async def _manage_positions(self) -> None:
        """Manage filled positions with take-profit and stop-loss."""
        take_profit = self._params["take_profit"]
        stop_loss = self._params["stop_loss"]

        for token_id, pos in list(self._filled_positions.items()):
            try:
                current_price = await self._client.get_midpoint(token_id)
            except Exception:
                continue

            entry_price = pos["entry_price"]
            market: ScannedMarket = pos["market"]

            # Take profit: price rose above entry + threshold
            if current_price >= entry_price + take_profit:
                logger.info(
                    "take_profit_triggered",
                    market=market.question,
                    entry=entry_price,
                    current=current_price,
                    profit=current_price - entry_price,
                )
                await self._exit_position(token_id, current_price, "take_profit")
                continue

            # Stop loss: price dropped below entry - threshold
            if current_price <= entry_price - stop_loss:
                logger.info(
                    "stop_loss_triggered",
                    market=market.question,
                    entry=entry_price,
                    current=current_price,
                    loss=entry_price - current_price,
                )
                await self._exit_position(token_id, current_price, "stop_loss")
                continue

    async def _exit_position(self, token_id: str, price: float, reason: str) -> None:
        """Exit a position by selling through the guarded execution path."""
        pos = self._filled_positions.get(token_id)
        if not pos:
            return

        order = await self._place_market_order(
            token_id=token_id,
            market=pos["market"].question,
            price=price,
            size=pos["size"],
            side=SIDE_SELL,
            order_type="FOK",
        )
        if order:
            logger.info(
                "position_exited",
                market=pos["market"].question,
                reason=reason,
                exit_price=price,
                entry_price=pos["entry_price"],
                pnl=price - pos["entry_price"],
                dry_run=self._settings.dry_run,
            )

        # Clean up regardless (position is unrecoverable whether blocked or filled)
        if token_id in self._filled_positions:
            del self._filled_positions[token_id]
