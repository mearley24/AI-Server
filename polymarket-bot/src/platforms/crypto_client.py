"""Crypto exchange client via CCXT — unified multi-exchange trading.

Implements the PlatformClient interface using CCXT's unified API,
supporting Kraken, Coinbase, and other exchanges for spot trading
of XRP, XCN, PI and other assets.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from src.paper_ledger import PaperLedger, PaperTrade
from src.platforms.base import Order, PlatformClient, Position

logger = structlog.get_logger(__name__)


@dataclass
class PaperPosition:
    """Tracks a simulated position for paper trading."""

    symbol: str
    side: str
    size: float
    entry_price: float
    opened_at: float = field(default_factory=time.time)
    order_id: str = ""


class PaperTrader:
    """Simulates order execution and position tracking for dry-run mode.

    Mimics exchange responses without hitting any real API, following
    the same paper_ledger pattern used by the Polymarket bot.
    """

    def __init__(self, paper_ledger: Optional[PaperLedger] = None) -> None:
        self._positions: dict[str, PaperPosition] = {}
        self._orders: dict[str, dict] = {}
        self._balance: dict[str, float] = {"USD": 10_000.0}  # simulated starting balance
        self._paper_ledger = paper_ledger

    def place_order(self, order: Order) -> dict:
        """Simulate order placement."""
        order_id = f"paper-crypto-{uuid.uuid4().hex[:12]}"
        simulated = {
            "id": order_id,
            "symbol": order.market_id,
            "type": order.order_type,
            "side": order.side,
            "amount": order.size,
            "price": order.price,
            "status": "closed" if order.order_type == "market" else "open",
            "filled": order.size if order.order_type == "market" else 0.0,
            "timestamp": int(time.time() * 1000),
        }

        # Track position for market orders (immediate fill)
        if order.order_type == "market" and order.price:
            pos_key = f"{order.market_id}:{order.side}"
            self._positions[pos_key] = PaperPosition(
                symbol=order.market_id,
                side=order.side,
                size=order.size,
                entry_price=order.price,
                order_id=order_id,
            )
            # Update balance
            cost = order.size * order.price
            if order.side == "buy":
                self._balance["USD"] -= cost
            else:
                self._balance["USD"] += cost

        self._orders[order_id] = simulated

        # Record in paper ledger
        if self._paper_ledger:
            self._paper_ledger.record(PaperTrade(
                timestamp=time.time(),
                strategy="crypto",
                market_id=order.market_id,
                market_question=f"{order.market_id} spot trade",
                side=order.side.upper(),
                size=order.size,
                price=order.price or 0.0,
                signals={"platform": "crypto", "order_type": order.order_type},
            ))

        return simulated

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "canceled"
            return True
        return False

    def get_positions(self) -> list[PaperPosition]:
        return list(self._positions.values())

    def get_balance(self) -> dict[str, float]:
        return dict(self._balance)


class CryptoClient(PlatformClient):
    """CCXT-based multi-exchange crypto client."""

    @staticmethod
    def _fix_base64_padding(secret: str) -> str:
        """Ensure base64 string has correct padding for CCXT/Kraken."""
        s = secret.strip()
        if not s:
            return s
        missing = len(s) % 4
        if missing:
            s += "=" * (4 - missing)
        return s

    def __init__(
        self,
        exchange_id: str = "kraken",
        api_key: str = "",
        api_secret: str = "",
        dry_run: bool = True,
        symbols: Optional[list[str]] = None,
        paper_ledger: Optional[PaperLedger] = None,
    ) -> None:
        self._exchange_id = exchange_id
        self._api_key = api_key
        self._api_secret = self._fix_base64_padding(api_secret)
        self._dry_run = dry_run
        self._symbols = symbols or ["XRP/USD", "XCN/USD", "PI/USD"]
        self._exchange: Any = None
        self._paper_trader = PaperTrader(paper_ledger) if dry_run else None
        self._paper_ledger = paper_ledger

    @property
    def platform_name(self) -> str:
        return self._exchange_id

    @property
    def is_dry_run(self) -> bool:
        return self._dry_run

    @property
    def exchange(self) -> Any:
        """Access the underlying CCXT exchange instance."""
        return self._exchange

    async def connect(self) -> bool:
        """Initialize CCXT exchange and load markets."""
        try:
            import ccxt

            exchange_class = getattr(ccxt, self._exchange_id, None)
            if exchange_class is None:
                logger.error("ccxt_exchange_not_found", exchange=self._exchange_id)
                return False

            config: dict[str, Any] = {"enableRateLimit": True}
            if self._api_key and not self._dry_run:
                config["apiKey"] = self._api_key
                config["secret"] = self._api_secret

            self._exchange = exchange_class(config)

            # Load markets to populate symbol lists
            try:
                self._exchange.load_markets()
                available = [s for s in self._symbols if s in self._exchange.symbols]
                logger.info(
                    "crypto_connected",
                    exchange=self._exchange_id,
                    dry_run=self._dry_run,
                    symbols_requested=self._symbols,
                    symbols_available=available,
                    total_markets=len(self._exchange.symbols),
                )
            except Exception as exc:
                logger.warning(
                    "crypto_load_markets_warning",
                    exchange=self._exchange_id,
                    error=str(exc),
                    msg="Proceeding in dry-run with simulated data",
                )

            return True
        except ImportError:
            logger.error("ccxt_not_installed", msg="pip install ccxt")
            return False
        except Exception as exc:
            logger.error("crypto_connect_failed", error=str(exc))
            return False

    async def get_markets(self, **filters: Any) -> list[dict]:
        """List available trading pairs."""
        if self._exchange is None:
            return []

        symbols = filters.get("symbols", self._symbols)
        markets = []
        for symbol in symbols:
            if symbol in getattr(self._exchange, "symbols", []):
                market_info = self._exchange.markets.get(symbol, {})
                markets.append({
                    "symbol": symbol,
                    "base": market_info.get("base", symbol.split("/")[0]),
                    "quote": market_info.get("quote", "USD"),
                    "active": market_info.get("active", True),
                    "platform": self._exchange_id,
                })
        return markets

    async def get_orderbook(self, market_id: str) -> dict:
        """Fetch orderbook for a symbol."""
        if self._exchange is None:
            return {"bids": [], "asks": [], "symbol": market_id}

        try:
            book = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.fetch_order_book(market_id, limit=20)
            )
            return {
                "bids": book.get("bids", []),
                "asks": book.get("asks", []),
                "symbol": market_id,
                "platform": self._exchange_id,
            }
        except Exception as exc:
            logger.error("crypto_orderbook_error", symbol=market_id, error=str(exc))
            return {"bids": [], "asks": [], "symbol": market_id}

    @staticmethod
    def _crypto_trading_enabled() -> bool:
        """Returns True only if both Kraken guards are explicitly enabled."""
        mm = os.environ.get("KRAKEN_MM_ENABLED", "").lower() in {"1", "true", "yes"}
        ct = os.environ.get("CRYPTO_TRADING_ENABLED", "").lower() in {"1", "true", "yes"}
        return mm and ct

    async def place_order(self, order: Order) -> dict:
        """Place a trade on the exchange."""
        if not self._crypto_trading_enabled():
            logger.info(
                "crypto_disabled_skip",
                path="place_order",
                symbol=order.market_id,
                reason="KRAKEN_MM_ENABLED and CRYPTO_TRADING_ENABLED must both be true",
            )
            return {"status": "disabled", "order_id": ""}

        if self._dry_run and self._paper_trader:
            result = self._paper_trader.place_order(order)
            logger.info(
                "crypto_paper_order",
                symbol=order.market_id,
                side=order.side,
                size=order.size,
                price=order.price,
            )
            return result

        if self._exchange is None:
            raise RuntimeError("Exchange not connected")

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.create_order(
                    symbol=order.market_id,
                    type=order.order_type,
                    side=order.side,
                    amount=order.size,
                    price=order.price,
                ),
            )
            logger.info(
                "crypto_order_placed",
                order_id=result.get("id"),
                symbol=order.market_id,
                side=order.side,
                amount=order.size,
                price=order.price,
            )
            return result
        except Exception as exc:
            logger.error("crypto_place_order_error", error=str(exc))
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if self._dry_run and self._paper_trader:
            return self._paper_trader.cancel_order(order_id)

        if self._exchange is None:
            return False

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.cancel_order(order_id)
            )
            return True
        except Exception as exc:
            logger.error("crypto_cancel_error", order_id=order_id, error=str(exc))
            return False

    async def get_positions(self) -> list[Position]:
        """Get open positions (from balance for spot trading)."""
        if self._dry_run and self._paper_trader:
            return [
                Position(
                    platform=self._exchange_id,
                    market_id=p.symbol,
                    side=p.side,
                    size=p.size,
                    avg_entry=p.entry_price,
                )
                for p in self._paper_trader.get_positions()
            ]

        if self._exchange is None:
            return []

        try:
            balance = await asyncio.get_event_loop().run_in_executor(
                None, self._exchange.fetch_balance
            )
            positions = []
            for currency, amounts in balance.get("total", {}).items():
                if amounts and amounts > 0 and currency != "USD":
                    positions.append(Position(
                        platform=self._exchange_id,
                        market_id=f"{currency}/USD",
                        side="long",
                        size=amounts,
                        avg_entry=0.0,
                    ))
            return positions
        except Exception as exc:
            logger.error("crypto_positions_error", error=str(exc))
            return []

    async def get_balance(self) -> dict:
        """Fetch account balance."""
        if self._dry_run and self._paper_trader:
            return {
                "balance": self._paper_trader.get_balance(),
                "platform": self._exchange_id,
                "dry_run": True,
            }

        if self._exchange is None:
            return {"balance": {}, "platform": self._exchange_id}

        try:
            balance = await asyncio.get_event_loop().run_in_executor(
                None, self._exchange.fetch_balance
            )
            return {
                "balance": {k: v for k, v in balance.get("total", {}).items() if v and v > 0},
                "free": {k: v for k, v in balance.get("free", {}).items() if v and v > 0},
                "platform": self._exchange_id,
            }
        except Exception as exc:
            logger.error("crypto_balance_error", error=str(exc))
            return {"balance": {}, "platform": self._exchange_id}

    async def subscribe_realtime(self, market_ids: list[str], callback: Any) -> None:
        """Subscribe to real-time ticker data via CCXT Pro WebSocket."""
        try:
            import ccxt.pro as ccxtpro

            exchange_class = getattr(ccxtpro, self._exchange_id, None)
            if exchange_class is None:
                logger.warning("ccxtpro_exchange_not_found", exchange=self._exchange_id)
                return

            ws_exchange = exchange_class({"enableRateLimit": True})

            async def _watch_loop() -> None:
                try:
                    while True:
                        for symbol in market_ids:
                            ticker = await ws_exchange.watch_ticker(symbol)
                            if callback:
                                await callback({
                                    "type": "ticker",
                                    "symbol": symbol,
                                    "last": ticker.get("last"),
                                    "bid": ticker.get("bid"),
                                    "ask": ticker.get("ask"),
                                    "volume": ticker.get("quoteVolume"),
                                    "platform": self._exchange_id,
                                })
                except Exception as exc:
                    logger.error("crypto_ws_error", error=str(exc))
                finally:
                    await ws_exchange.close()

            asyncio.create_task(_watch_loop())
        except ImportError:
            logger.warning("ccxtpro_not_installed", msg="pip install ccxt[pro] for WebSocket support")

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> list:
        """Fetch OHLCV candlestick data for technical analysis."""
        if self._exchange is None:
            return []
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit),
            )
        except Exception as exc:
            logger.error("crypto_ohlcv_error", symbol=symbol, error=str(exc))
            return []

    async def fetch_ticker(self, symbol: str) -> dict:
        """Fetch current ticker data for a symbol."""
        if self._exchange is None:
            return {}
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.fetch_ticker(symbol)
            )
        except Exception as exc:
            logger.error("crypto_ticker_error", symbol=symbol, error=str(exc))
            return {}

    async def close(self) -> None:
        """Close exchange connection."""
        if self._exchange:
            try:
                if hasattr(self._exchange, "close"):
                    self._exchange.close()
            except Exception:
                pass
        logger.info("crypto_client_closed", exchange=self._exchange_id)
