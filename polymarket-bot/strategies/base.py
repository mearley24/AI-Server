"""Abstract base class for all trading strategies."""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner, ScannedMarket
from src.pnl_tracker import PnLTracker, Trade
from src.websocket_client import OrderbookFeed

if TYPE_CHECKING:
    from src.debate_engine import DebateEngine
    from src.paper_ledger import PaperLedger
    from src.security.sandbox import ExecutionSandbox

logger = structlog.get_logger(__name__)


class StrategyState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class OpenOrder:
    """Tracks an order placed by a strategy."""

    order_id: str
    token_id: str
    market: str
    side: str
    price: float
    size: float
    placed_at: float = field(default_factory=time.time)
    strategy: str = ""


class BaseStrategy(ABC):
    """Abstract base strategy. Subclass and implement on_tick()."""

    name: str = "base"
    description: str = "Abstract base strategy"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        self._client = client
        self._settings = settings
        self._scanner = scanner
        self._orderbook = orderbook
        self._pnl = pnl_tracker
        self._state = StrategyState.IDLE
        self._task: asyncio.Task | None = None
        self._open_orders: dict[str, OpenOrder] = {}
        self._tick_interval: float = 5.0  # seconds between ticks
        self._params: dict[str, Any] = {}
        self._started_at: float = 0.0
        self._tick_count: int = 0
        self._debate_engine: DebateEngine | None = None
        self._paper_ledger: PaperLedger | None = None
        self._sandbox: ExecutionSandbox | None = None

    def set_debate_engine(self, engine: DebateEngine) -> None:
        """Attach the debate engine for pre-trade validation."""
        self._debate_engine = engine

    def set_paper_ledger(self, ledger: PaperLedger) -> None:
        """Attach the paper ledger for dry-run mode."""
        self._paper_ledger = ledger

    def set_sandbox(self, sandbox: ExecutionSandbox) -> None:
        """Attach the execution sandbox — all order helpers enforce its limits."""
        self._sandbox = sandbox

    @property
    def state(self) -> StrategyState:
        return self._state

    @property
    def open_orders(self) -> dict[str, OpenOrder]:
        return self._open_orders

    @property
    def params(self) -> dict[str, Any]:
        return self._params

    @property
    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "open_orders": len(self._open_orders),
            "tick_count": self._tick_count,
            "started_at": self._started_at,
            "uptime_seconds": time.time() - self._started_at if self._started_at else 0,
            "params": self._params,
        }

    def configure(self, params: dict[str, Any]) -> None:
        """Update strategy parameters."""
        self._params.update(params)
        logger.info("strategy_configured", strategy=self.name, params=params)

    async def start(self, params: dict[str, Any] | None = None) -> None:
        """Start the strategy loop."""
        if self._state == StrategyState.RUNNING:
            logger.warning("strategy_already_running", strategy=self.name)
            return

        if params:
            self.configure(params)

        self._state = StrategyState.RUNNING
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("strategy_started", strategy=self.name)

    async def stop(self) -> None:
        """Stop the strategy loop and cancel open orders."""
        if self._state != StrategyState.RUNNING:
            return

        self._state = StrategyState.STOPPING
        logger.info("strategy_stopping", strategy=self.name)

        # Cancel all open orders (skip API calls in dry-run mode)
        for order_id in list(self._open_orders.keys()):
            if not self._settings.dry_run:
                try:
                    await self._client.cancel_order(order_id)
                except Exception as exc:
                    logger.error("cancel_order_error", order_id=order_id, error=str(exc))
        self._open_orders.clear()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._state = StrategyState.IDLE
        logger.info("strategy_stopped", strategy=self.name)

    async def _run_loop(self) -> None:
        """Main strategy loop — calls on_tick() repeatedly."""
        while self._state == StrategyState.RUNNING:
            try:
                await self.on_tick()
                self._tick_count += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("strategy_tick_error", strategy=self.name, error=str(exc))
                self._state = StrategyState.ERROR
                break

            await asyncio.sleep(self._tick_interval)

    @abstractmethod
    async def on_tick(self) -> None:
        """Called on each strategy tick. Implement trading logic here."""
        ...

    # ── Helper methods for subclasses ────────────────────────────────────

    async def _place_limit_order(
        self,
        token_id: str,
        market: str,
        price: float,
        size: float,
        side: int,
    ) -> OpenOrder | None:
        """Place a limit order and track it.

        If a debate engine is attached and the position exceeds its threshold,
        runs a bull/bear debate before placing the order.
        """
        # Check exposure limit
        current_exposure = sum(o.price * o.size for o in self._open_orders.values())
        if current_exposure + (price * size) > self._settings.poly_max_exposure:
            logger.warning(
                "exposure_limit_reached",
                current=current_exposure,
                max=self._settings.poly_max_exposure,
            )
            return None

        # Run debate engine if attached and qualifying
        debate_confidence: float | None = None
        debate_recommendation: str | None = None
        if self._debate_engine:
            side_str = "BUY" if side == 0 else "SELL"
            debate_out = await self._debate_engine.should_execute(
                strategy_name=self.name,
                market=market,
                side=side_str,
                price=price,
                size=size,
                context={"token_id": token_id, "params": self._params},
            )
            if debate_out is not None:
                debate_confidence = debate_out.confidence
                debate_recommendation = debate_out.recommendation
                if debate_out.confidence < self._debate_engine.confidence_threshold:
                    logger.info(
                        "trade_rejected_by_debate",
                        strategy=self.name,
                        market=market,
                        confidence=debate_out.confidence,
                        recommendation=debate_out.recommendation,
                        reasoning=debate_out.reasoning,
                    )
                    return None

        # Sandbox check (must pass before any live order is placed)
        if self._sandbox and not self._settings.dry_run:
            allowed, reason = await self._sandbox.check_trade(size=size, price=price)
            if not allowed:
                logger.warning(
                    "sandbox_blocked_limit_order",
                    reason=reason,
                    strategy=self.name,
                    market=market,
                    notional=round(size * price, 2),
                )
                return None

        # --- Dry-run mode: log paper trade instead of placing real order ---
        if self._settings.dry_run:
            return self._record_paper_trade(
                token_id=token_id,
                market=market,
                price=price,
                size=size,
                side=side,
                debate_confidence=debate_confidence,
                debate_recommendation=debate_recommendation,
            )

        try:
            result = await self._client.place_order(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
            )
            order_id = result.get("orderID", str(uuid.uuid4()))
            order = OpenOrder(
                order_id=order_id,
                token_id=token_id,
                market=market,
                side="BUY" if side == 0 else "SELL",
                price=price,
                size=size,
                strategy=self.name,
            )
            self._open_orders[order_id] = order
            if self._sandbox:
                self._sandbox.record_trade(size * price)
            return order
        except Exception as exc:
            logger.error("place_order_error", error=str(exc), token_id=token_id)
            return None

    async def _place_market_order(
        self,
        token_id: str,
        market: str,
        price: float,
        size: float,
        side: int,
        order_type: str = "FOK",
    ) -> OpenOrder | None:
        """Place a market/FOK/GTC order through the guarded execution path.

        Checks sandbox limits, enforces dry-run, and records the trade.
        All strategies MUST use this helper instead of calling client.place_order() directly.
        """
        # Sandbox check before any real order
        if self._sandbox and not self._settings.dry_run:
            allowed, reason = await self._sandbox.check_trade(size=size, price=price)
            if not allowed:
                logger.warning(
                    "sandbox_blocked_market_order",
                    reason=reason,
                    strategy=self.name,
                    market=market,
                    notional=round(size * price, 2),
                )
                return None

        # Dry-run: record paper trade, no real API call
        if self._settings.dry_run:
            return self._record_paper_trade(
                token_id=token_id,
                market=market,
                price=price,
                size=size,
                side=side,
            )

        # Live: place real order
        try:
            result = await self._client.place_order(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
                order_type=order_type,
            )
            order_id = result.get("orderID", str(uuid.uuid4()))
            order = OpenOrder(
                order_id=order_id,
                token_id=token_id,
                market=market,
                side="BUY" if side == 0 else "SELL",
                price=price,
                size=size,
                strategy=self.name,
            )
            self._open_orders[order_id] = order
            if self._sandbox:
                self._sandbox.record_trade(size * price)
            return order
        except Exception as exc:
            logger.error("place_market_order_error", error=str(exc), token_id=token_id)
            return None

    def _record_paper_trade(
        self,
        token_id: str,
        market: str,
        price: float,
        size: float,
        side: int,
        debate_confidence: float | None = None,
        debate_recommendation: str | None = None,
    ) -> OpenOrder:
        """Record a paper trade in dry-run mode and return a mock OpenOrder."""
        from src.paper_ledger import PaperTrade

        side_str = "BUY" if side == 0 else "SELL"
        paper_order_id = f"paper-{uuid.uuid4().hex[:12]}"

        if self._paper_ledger:
            paper_trade = PaperTrade(
                timestamp=time.time(),
                strategy=self.name,
                market_id=token_id,
                market_question=market,
                side=side_str,
                size=size,
                price=price,
                signals=self._params,
                debate_confidence=debate_confidence,
                debate_recommendation=debate_recommendation,
            )
            self._paper_ledger.record(paper_trade)

        logger.info(
            "paper_trade_logged",
            strategy=self.name,
            market=market,
            side=side_str,
            price=price,
            size=size,
            order_id=paper_order_id,
        )

        # Return a mock OpenOrder so the strategy loop continues normally
        order = OpenOrder(
            order_id=paper_order_id,
            token_id=token_id,
            market=market,
            side=side_str,
            price=price,
            size=size,
            strategy=self.name,
        )
        self._open_orders[paper_order_id] = order
        return order

    def _record_fill(self, order: OpenOrder, fill_price: float) -> None:
        """Record a filled order as a trade in the P&L tracker."""
        trade = Trade(
            trade_id=order.order_id,
            timestamp=time.time(),
            market=order.market,
            token_id=order.token_id,
            side=order.side,
            price=fill_price,
            size=order.size,
            strategy=self.name,
        )
        self._pnl.record_trade(trade)

        if order.order_id in self._open_orders:
            del self._open_orders[order.order_id]
