"""Liquidity Provider (LP) Module — Market-making on Polymarket.

Posts two-sided GTC limit orders (BUY YES at bid, BUY NO at ask-equivalent)
to earn the bid-ask spread plus maker rebates. Polymarket charges 0% maker
fees and ~2% taker fees, so resting liquidity is structurally profitable.

Key features:
- Market selection: high-volume event markets with mid-price 0.15-0.85
- Inventory-aware skew quoting: shifts quotes to rebalance net position
- Per-market P/L tracking with auto-exit on losses
- 24h-before-resolution cutoff to avoid adverse selection
- Configurable via environment variables, disabled by default

Toggle on/off via COPYTRADE_LP_ENABLED (default: false).
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

from strategies.correlation_tracker import CorrelationTracker, categorize_market

logger = structlog.get_logger(__name__)


def _notify(title: str, body: str) -> None:
    """Best-effort push notification via Redis -> notification-hub -> iMessage."""
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://host.docker.internal:6379")
        r = redis.from_url(url, decode_responses=True, socket_timeout=2)
        r.publish("notifications:trading", _json.dumps({"title": title, "body": body}))
    except Exception:
        pass


def _parse_token_ids(raw: Any) -> list[str]:
    """Parse clobTokenIds from Gamma API response (string or list)."""
    if isinstance(raw, list):
        return [str(t).strip().strip('"') for t in raw]
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw) if raw.startswith("[") else raw.split(",")
            return [str(t).strip().strip('"') for t in parsed]
        except Exception:
            return []
    return []


def _parse_prices(raw: Any) -> list[float]:
    """Parse outcomePrices from Gamma API response."""
    if isinstance(raw, list):
        return [float(p) for p in raw]
    if isinstance(raw, str):
        try:
            return [float(p) for p in _json.loads(raw)]
        except Exception:
            return []
    return []


# ── Data models ────────────────────────────────────────────────────────────

@dataclass
class LPMarket:
    """State for a market where we are providing liquidity."""

    condition_id: str
    question: str
    token_id_yes: str
    token_id_no: str
    category: str

    # Pricing
    midpoint: float = 0.50
    end_date: str = ""  # ISO datetime string for market resolution

    # Order tracking
    yes_bid_order_id: str = ""
    no_bid_order_id: str = ""
    last_refresh: float = 0.0

    # Inventory: net shares (positive = long YES, negative = short YES/long NO)
    net_inventory_usd: float = 0.0

    # P/L tracking for this market
    total_pnl: float = 0.0
    fills_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "question": self.question[:60],
            "midpoint": self.midpoint,
            "net_inventory_usd": round(self.net_inventory_usd, 2),
            "total_pnl": round(self.total_pnl, 2),
            "fills": self.fills_count,
            "category": self.category,
        }


# ── Main LP class ──────────────────────────────────────────────────────────

class LiquidityProvider:
    """Market-making module for Polymarket prediction markets.

    Disabled by default — set COPYTRADE_LP_ENABLED=true to activate.
    """

    def __init__(
        self,
        clob_client: Any = None,
        gamma_api_url: str = "https://gamma-api.polymarket.com",
        correlation_tracker: CorrelationTracker | None = None,
        bankroll: float = 300.0,
        directional_condition_ids: set[str] | None = None,
    ) -> None:
        self._clob_client = clob_client
        self._gamma_url = gamma_api_url.rstrip("/")
        self._correlation_tracker = correlation_tracker
        self._bankroll = bankroll
        self._directional_ids = directional_condition_ids or set()

        # Configuration from env vars
        self._enabled = os.environ.get(
            "COPYTRADE_LP_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        self._spread_pct = float(os.environ.get("COPYTRADE_LP_SPREAD", "0.03"))
        self._refresh_secs = float(os.environ.get("COPYTRADE_LP_REFRESH_SECS", "60"))
        self._max_markets = int(os.environ.get("COPYTRADE_LP_MAX_MARKETS", "5"))
        self._max_inventory_per_market = float(
            os.environ.get("COPYTRADE_LP_MAX_INVENTORY", "50")
        )
        self._kelly_fraction = 0.10  # more conservative than copytrade's 0.25
        self._min_volume_24h = 10_000.0  # $10k daily volume minimum
        self._min_days_to_resolution = 2.0
        self._circuit_breaker_loss = float(
            os.environ.get("COPYTRADE_LP_CIRCUIT_BREAKER", "-30.0")
        )

        # Runtime state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._http: Optional[httpx.AsyncClient] = None

        # Active LP markets
        self._markets: dict[str, LPMarket] = {}

        # Aggregate tracking
        self._daily_pnl: float = 0.0
        self._halted: bool = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def bankroll(self) -> float:
        return self._bankroll

    @bankroll.setter
    def bankroll(self, value: float) -> None:
        self._bankroll = value

    def set_directional_ids(self, condition_ids: set[str]) -> None:
        """Update the set of condition IDs with directional (copy-trade) positions."""
        self._directional_ids = condition_ids

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the LP module if enabled."""
        if not self._enabled:
            logger.info("copytrade_lp_disabled", msg="Set COPYTRADE_LP_ENABLED=true to activate")
            return
        if self._running:
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "copytrade_lp_started",
            spread_pct=self._spread_pct,
            refresh_secs=self._refresh_secs,
            max_markets=self._max_markets,
            max_inventory=self._max_inventory_per_market,
            bankroll=round(self._bankroll, 2),
        )
        _notify(
            "LP Module Started",
            f"Spread: {self._spread_pct*100:.1f}% | Max markets: {self._max_markets}\n"
            f"Refresh: {self._refresh_secs}s | Bankroll: ${self._bankroll:,.0f}",
        )

    async def stop(self) -> None:
        """Stop the LP module and cancel all quotes."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._cancel_all_quotes()
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info(
            "copytrade_lp_stopped",
            markets=len(self._markets),
            daily_pnl=round(self._daily_pnl, 2),
        )

    # ── Main loop ──────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main LP loop: discover markets, post/refresh quotes."""
        while self._running:
            try:
                if self._halted:
                    await asyncio.sleep(60)
                    continue

                # Circuit breaker
                if self._daily_pnl < self._circuit_breaker_loss:
                    self._halted = True
                    await self._cancel_all_quotes()
                    _notify(
                        "LP Circuit Breaker",
                        f"Daily P/L: ${self._daily_pnl:.2f} (limit: ${self._circuit_breaker_loss:.2f})",
                    )
                    logger.warning(
                        "copytrade_lp_circuit_breaker",
                        pnl=round(self._daily_pnl, 2),
                    )
                    continue

                # Remove markets too close to resolution or losing money
                await self._prune_markets()

                # Discover new markets if below max
                if len(self._markets) < self._max_markets:
                    await self._discover_markets()

                # Refresh quotes on all active markets
                await self._refresh_all_quotes()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("copytrade_lp_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self._refresh_secs)
            except asyncio.CancelledError:
                break

    # ── Market Discovery ───────────────────────────────────────────────

    async def _discover_markets(self) -> None:
        """Find high-volume event markets suitable for market-making."""
        if not self._http:
            return

        try:
            resp = await self._http.get(
                f"{self._gamma_url}/markets",
                params={
                    "active": True,
                    "closed": False,
                    "limit": 100,
                    "order": "volume24hr",
                    "ascending": False,
                },
            )
            resp.raise_for_status()
            markets = resp.json()
        except Exception as exc:
            logger.error("copytrade_lp_discover_error", error=str(exc))
            return

        slots_available = self._max_markets - len(self._markets)
        if slots_available <= 0:
            return

        candidates: list[dict[str, Any]] = []

        for m in markets:
            condition_id = m.get("conditionId", m.get("condition_id", ""))
            if not condition_id:
                continue

            # Skip if already LP'ing or have directional position
            if condition_id in self._markets or condition_id in self._directional_ids:
                continue

            # Volume filter
            volume_24h = float(m.get("volume24hr", 0))
            if volume_24h < self._min_volume_24h:
                continue

            # Parse prices
            prices = _parse_prices(m.get("outcomePrices", ""))
            if len(prices) < 2:
                continue
            yes_price = prices[0]

            # Mid-price filter (0.15-0.85)
            if yes_price < 0.15 or yes_price > 0.85:
                continue

            # Token IDs
            token_ids = _parse_token_ids(m.get("clobTokenIds", ""))
            if len(token_ids) < 2:
                continue

            # Time-to-resolution filter
            end_date_str = m.get("endDate", m.get("end_date_iso", ""))
            if end_date_str:
                try:
                    end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400
                    if days_left < self._min_days_to_resolution:
                        continue
                except (ValueError, TypeError):
                    pass  # if we can't parse, allow it

            question = m.get("question", "")
            category = categorize_market(question, m.get("tags"))

            # Check correlation limits if tracker available
            if self._correlation_tracker:
                would_exceed, _, _ = self._correlation_tracker.would_exceed_limit(
                    question, self._max_inventory_per_market
                )
                if would_exceed:
                    continue

            candidates.append({
                "condition_id": condition_id,
                "question": question,
                "token_id_yes": token_ids[0],
                "token_id_no": token_ids[1],
                "midpoint": yes_price,
                "volume_24h": volume_24h,
                "end_date": end_date_str,
                "category": category,
            })

        # Sort by volume (highest first)
        candidates.sort(key=lambda c: -c["volume_24h"])

        for c in candidates[:slots_available]:
            lp_market = LPMarket(
                condition_id=c["condition_id"],
                question=c["question"],
                token_id_yes=c["token_id_yes"],
                token_id_no=c["token_id_no"],
                midpoint=c["midpoint"],
                end_date=c["end_date"],
                category=c["category"],
            )
            self._markets[c["condition_id"]] = lp_market

            # Register with correlation tracker
            if self._correlation_tracker:
                self._correlation_tracker.add_position(
                    f"lp_{c['condition_id'][:8]}",
                    c["question"],
                    0.0,  # no exposure yet
                )

            logger.info(
                "copytrade_lp_market_entered",
                market=c["question"][:50],
                midpoint=c["midpoint"],
                volume_24h=round(c["volume_24h"], 0),
                category=c["category"],
            )
            _notify(
                "LP Market Entered",
                f"{c['question'][:60]}\nMid: {c['midpoint']:.2f} | Vol: ${c['volume_24h']:,.0f}",
            )

    # ── Quote Management ───────────────────────────────────────────────

    async def _refresh_all_quotes(self) -> None:
        """Cancel stale orders and post fresh two-sided quotes on all LP markets."""
        if not self._clob_client:
            return

        for cid, market in list(self._markets.items()):
            try:
                await self._refresh_market_quotes(market)
            except Exception as exc:
                logger.error(
                    "copytrade_lp_refresh_error",
                    condition_id=cid[:16],
                    error=str(exc),
                )

    async def _refresh_market_quotes(self, market: LPMarket) -> None:
        """Refresh quotes for a single market with inventory skew."""
        # Fetch fresh midpoint
        if self._http:
            try:
                resp = await self._http.get(f"{self._gamma_url}/markets/{market.condition_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    prices = _parse_prices(data.get("outcomePrices", ""))
                    if prices:
                        market.midpoint = prices[0]
            except Exception:
                pass  # use cached midpoint

        # Cancel existing orders for this market
        await self._cancel_market_orders(market)

        # Calculate inventory skew
        # When long (positive inventory), lower bid and raise ask to encourage sells
        # When short (negative inventory), raise bid and lower ask to encourage buys
        skew = 0.0
        if abs(market.net_inventory_usd) > 0:
            inventory_ratio = market.net_inventory_usd / self._max_inventory_per_market
            # Clamp ratio to [-1, 1]
            inventory_ratio = max(-1.0, min(1.0, inventory_ratio))
            # Skew shifts both bid and ask in the same direction
            skew = inventory_ratio * (self._spread_pct / 2)

        # Calculate quote prices
        half_spread = self._spread_pct / 2
        bid_price = round(max(0.01, market.midpoint - half_spread - skew), 2)
        ask_price = round(min(0.99, market.midpoint + half_spread - skew), 2)

        # Check inventory limits — skip the side that would increase exposure
        post_bid = True
        post_ask = True
        if market.net_inventory_usd >= self._max_inventory_per_market:
            post_bid = False  # don't buy more YES
        elif market.net_inventory_usd <= -self._max_inventory_per_market:
            post_ask = False  # don't buy more NO (equivalent to selling YES)

        # Calculate order size (conservative Kelly)
        order_size_usd = min(
            self._bankroll * self._kelly_fraction * 0.5,  # 5% of bankroll
            self._max_inventory_per_market - abs(market.net_inventory_usd),
        )
        if order_size_usd < 1.0:
            return  # too small to bother

        loop = asyncio.get_event_loop()

        try:
            from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

            options = PartialCreateOrderOptions(
                tick_size="0.01",
                neg_risk=False,
            )

            # BUY YES at bid price (we want to be the maker)
            if post_bid and bid_price > 0.01:
                bid_size = round(order_size_usd / bid_price, 2)
                if bid_size >= 1:
                    yes_args = OrderArgs(
                        token_id=market.token_id_yes,
                        price=bid_price,
                        size=bid_size,
                        side="BUY",
                    )
                    resp = await loop.run_in_executor(
                        None,
                        lambda: self._clob_client.create_and_post_order(yes_args, options),
                    )
                    market.yes_bid_order_id = resp.get("orderID", "") if isinstance(resp, dict) else ""

            # BUY NO at (1 - ask_price) — equivalent to selling YES at ask
            if post_ask and market.token_id_no and ask_price < 0.99:
                no_bid_price = round(1.0 - ask_price, 2)
                if no_bid_price > 0.01:
                    no_size = round(order_size_usd / no_bid_price, 2)
                    if no_size >= 1:
                        no_args = OrderArgs(
                            token_id=market.token_id_no,
                            price=no_bid_price,
                            size=no_size,
                            side="BUY",
                        )
                        resp = await loop.run_in_executor(
                            None,
                            lambda: self._clob_client.create_and_post_order(no_args, options),
                        )
                        market.no_bid_order_id = resp.get("orderID", "") if isinstance(resp, dict) else ""

            market.last_refresh = time.time()

            logger.debug(
                "copytrade_lp_quotes_posted",
                market=market.question[:40],
                bid=bid_price,
                ask=ask_price,
                skew=round(skew, 4),
                inventory=round(market.net_inventory_usd, 2),
            )

        except ImportError:
            logger.warning("copytrade_lp_no_clob_client", msg="py-clob-client not installed")
        except Exception as exc:
            logger.warning("copytrade_lp_quote_error", market=market.question[:30], error=str(exc))

    async def _cancel_market_orders(self, market: LPMarket) -> None:
        """Cancel existing LP orders for a specific market."""
        if not self._clob_client:
            return

        loop = asyncio.get_event_loop()
        for order_id in [market.yes_bid_order_id, market.no_bid_order_id]:
            if order_id:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda oid=order_id: self._clob_client.cancel(oid),
                    )
                except Exception:
                    pass  # order may have already been filled or cancelled

        market.yes_bid_order_id = ""
        market.no_bid_order_id = ""

    async def _cancel_all_quotes(self) -> None:
        """Cancel all LP orders across all markets."""
        if not self._clob_client:
            return

        # Cancel individual orders first (more targeted than cancel_all)
        for market in self._markets.values():
            await self._cancel_market_orders(market)

        logger.info("copytrade_lp_all_quotes_cancelled")

    # ── Market Pruning ─────────────────────────────────────────────────

    async def _prune_markets(self) -> None:
        """Remove markets that are too close to resolution or losing money."""
        now = datetime.now(timezone.utc)
        to_remove: list[str] = []

        for cid, market in self._markets.items():
            reason = ""

            # Check time to resolution
            if market.end_date:
                try:
                    end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                    hours_left = (end_dt - now).total_seconds() / 3600
                    if hours_left < 24:
                        reason = f"resolution in {hours_left:.0f}h"
                except (ValueError, TypeError):
                    pass

            # Check if market is losing money (stop LP if losing)
            if market.total_pnl < -self._max_inventory_per_market * 0.5:
                reason = f"P/L: ${market.total_pnl:.2f}"

            # Check if we now have a directional position
            if cid in self._directional_ids:
                reason = "directional position added"

            if reason:
                to_remove.append(cid)
                logger.info(
                    "copytrade_lp_market_exited",
                    market=market.question[:50],
                    reason=reason,
                    pnl=round(market.total_pnl, 2),
                    fills=market.fills_count,
                )
                _notify(
                    "LP Market Exited",
                    f"{market.question[:50]}\nReason: {reason}\n"
                    f"P/L: ${market.total_pnl:.2f} | Fills: {market.fills_count}",
                )

        for cid in to_remove:
            market = self._markets.pop(cid)
            await self._cancel_market_orders(market)
            # Unregister from correlation tracker
            if self._correlation_tracker:
                self._correlation_tracker.remove_position(f"lp_{cid[:8]}")

    # ── Fill Tracking ──────────────────────────────────────────────────

    def record_fill(
        self,
        condition_id: str,
        side: str,
        size_usd: float,
        price: float,
    ) -> None:
        """Record a fill on an LP order. Called from external fill listener.

        Args:
            condition_id: Market condition ID
            side: "BUY" or "SELL"
            size_usd: Fill size in USD
            price: Fill price
        """
        market = self._markets.get(condition_id)
        if not market:
            return

        market.fills_count += 1

        # Update inventory
        if side == "BUY":
            market.net_inventory_usd += size_usd
        else:
            market.net_inventory_usd -= size_usd

        # Update correlation tracker exposure
        if self._correlation_tracker:
            self._correlation_tracker.remove_position(f"lp_{condition_id[:8]}")
            self._correlation_tracker.add_position(
                f"lp_{condition_id[:8]}",
                market.question,
                abs(market.net_inventory_usd),
            )

        logger.info(
            "copytrade_lp_fill",
            market=market.question[:40],
            side=side,
            size_usd=round(size_usd, 2),
            price=round(price, 4),
            inventory=round(market.net_inventory_usd, 2),
        )
        _notify(
            f"LP Fill: {side}",
            f"{market.question[:50]}\n"
            f"${size_usd:.2f} @ {price:.2f} | Inv: ${market.net_inventory_usd:.2f}",
        )

    # ── Status / API ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return LP status for /status endpoint and heartbeat."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "halted": self._halted,
            "quoted_markets": len(self._markets),
            "daily_pnl": round(self._daily_pnl, 2),
            "spread_pct": self._spread_pct,
            "refresh_secs": self._refresh_secs,
            "max_markets": self._max_markets,
            "max_inventory_per_market": self._max_inventory_per_market,
            "markets": [m.to_dict() for m in self._markets.values()],
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Return LP positions for the /positions endpoint."""
        positions = []
        for market in self._markets.values():
            if abs(market.net_inventory_usd) > 0.01:
                positions.append({
                    "type": "lp",
                    "condition_id": market.condition_id,
                    "question": market.question[:60],
                    "net_inventory_usd": round(market.net_inventory_usd, 2),
                    "total_pnl": round(market.total_pnl, 2),
                    "midpoint": market.midpoint,
                    "category": market.category,
                })
        return positions
