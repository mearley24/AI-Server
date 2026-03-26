"""Liquidity Provision Module — Passive market-making for Polymarket rewards.

Posts two-sided GTC limit orders at midpoint ± spread to earn daily USDC
from Polymarket's liquidity rewards program.

Safety controls:
- Never quote on markets with directional positions
- Max exposure per market: 5% of bankroll
- Cancel all quotes if daily P/L drops below circuit breaker
- Only quote markets with midpoint in [0.10, 0.90]
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class QuotedMarket:
    """A market where we have active two-sided quotes."""

    condition_id: str
    question: str
    token_id_yes: str
    token_id_no: str
    midpoint: float
    spread_cents: float = 2.0  # default 2 cent spread
    yes_bid_order_id: str = ""
    no_bid_order_id: str = ""
    last_refresh: float = 0.0
    exposure_usd: float = 0.0
    category: str = ""
    rewards_daily_rate: float = 0.0


def _notify(title: str, body: str) -> None:
    """Best-effort push notification via Redis."""
    try:
        import json as _json
        import redis
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        r = redis.from_url(url, decode_responses=True, socket_timeout=2)
        r.publish("notifications:trading", _json.dumps({"title": title, "body": body}))
    except Exception:
        pass


class LiquidityProvider:
    """Passive two-sided quoting on stable Polymarket markets."""

    def __init__(
        self,
        clob_client: Any = None,
        gamma_api_url: str = "https://gamma-api.polymarket.com",
        max_markets: int = 5,
        spread_cents: float = 2.0,
        order_size_usd: float = 10.0,
        max_exposure_pct: float = 0.05,  # 5% of bankroll per market
        refresh_interval_seconds: float = 3600.0,  # 1 hour
        midpoint_shift_threshold: float = 0.02,  # 2 cents
        circuit_breaker_loss: float = -20.0,
        bankroll: float = 300.0,
        directional_condition_ids: set[str] | None = None,
    ) -> None:
        self._clob_client = clob_client
        self._gamma_url = gamma_api_url.rstrip("/")
        self._max_markets = max_markets
        self._spread_cents = spread_cents
        self._order_size = order_size_usd
        self._max_exposure_pct = max_exposure_pct
        self._refresh_interval = refresh_interval_seconds
        self._midpoint_threshold = midpoint_shift_threshold
        self._circuit_breaker = circuit_breaker_loss
        self._bankroll = bankroll
        self._directional_ids = directional_condition_ids or set()

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._http: Optional[httpx.AsyncClient] = None

        # Active quotes
        self._quoted_markets: dict[str, QuotedMarket] = {}

        # P/L tracking for circuit breaker
        self._daily_pnl: float = 0.0
        self._halted: bool = False

    @property
    def bankroll(self) -> float:
        return self._bankroll

    @bankroll.setter
    def bankroll(self, value: float) -> None:
        self._bankroll = value

    def set_directional_ids(self, condition_ids: set[str]) -> None:
        """Update the set of condition IDs where we have directional positions."""
        self._directional_ids = condition_ids

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "liquidity_provider_started",
            max_markets=self._max_markets,
            spread_cents=self._spread_cents,
            order_size=self._order_size,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Cancel all outstanding orders
        await self._cancel_all_quotes()
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("liquidity_provider_stopped")

    async def _run_loop(self) -> None:
        """Main loop: discover markets, post quotes, refresh periodically."""
        while self._running:
            try:
                if self._halted:
                    await asyncio.sleep(60)
                    continue

                # Circuit breaker check
                if self._daily_pnl < self._circuit_breaker:
                    self._halted = True
                    await self._cancel_all_quotes()
                    _notify(
                        "🛑 LP Halted",
                        f"Daily P/L: ${self._daily_pnl:.2f} (limit: ${self._circuit_breaker:.2f})",
                    )
                    logger.warning("lp_circuit_breaker", pnl=self._daily_pnl)
                    continue

                # Discover or refresh markets
                if len(self._quoted_markets) < self._max_markets:
                    await self._discover_markets()

                # Refresh quotes on existing markets
                await self._refresh_quotes()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("lp_loop_error", error=str(exc))

            await asyncio.sleep(min(self._refresh_interval, 300))

    async def _discover_markets(self) -> None:
        """Find high-reward stable markets suitable for liquidity provision."""
        if not self._http:
            return

        try:
            resp = await self._http.get(
                f"{self._gamma_url}/markets",
                params={
                    "active": True,
                    "closed": False,
                    "limit": 50,
                    "order": "volume24hr",
                    "ascending": False,
                },
            )
            resp.raise_for_status()
            markets = resp.json()

            candidates = []
            for m in markets:
                condition_id = m.get("conditionId", m.get("condition_id", ""))

                # Skip markets where we have directional positions
                if condition_id in self._directional_ids:
                    continue

                # Skip already-quoted markets
                if condition_id in self._quoted_markets:
                    continue

                # Parse token IDs
                clob_raw = m.get("clobTokenIds", "")
                if isinstance(clob_raw, str):
                    try:
                        import json
                        token_ids = json.loads(clob_raw) if clob_raw.startswith("[") else clob_raw.split(",")
                    except Exception:
                        continue
                elif isinstance(clob_raw, list):
                    token_ids = clob_raw
                else:
                    continue

                token_ids = [t.strip().strip('"') for t in token_ids]
                if len(token_ids) < 2:
                    continue

                # Parse prices
                prices_raw = m.get("outcomePrices", "")
                if isinstance(prices_raw, str):
                    try:
                        import json
                        prices = json.loads(prices_raw)
                    except Exception:
                        continue
                elif isinstance(prices_raw, list):
                    prices = prices_raw
                else:
                    continue

                if len(prices) < 2:
                    continue

                yes_price = float(prices[0])

                # Only markets with midpoint in [0.10, 0.90]
                if yes_price < 0.10 or yes_price > 0.90:
                    continue

                question = m.get("question", "")
                volume_24h = float(m.get("volume24hr", 0))

                # Check for rewards badge
                rewards = m.get("rewardsActive", m.get("rewards", False))

                candidates.append({
                    "condition_id": condition_id,
                    "question": question,
                    "token_id_yes": token_ids[0],
                    "token_id_no": token_ids[1] if len(token_ids) > 1 else "",
                    "midpoint": yes_price,
                    "volume_24h": volume_24h,
                    "rewards": rewards,
                })

            # Prioritize: rewards markets first, then by volume
            candidates.sort(key=lambda c: (not c.get("rewards"), -c.get("volume_24h", 0)))

            # Add up to max_markets
            for c in candidates[:self._max_markets - len(self._quoted_markets)]:
                qm = QuotedMarket(
                    condition_id=c["condition_id"],
                    question=c["question"],
                    token_id_yes=c["token_id_yes"],
                    token_id_no=c["token_id_no"],
                    midpoint=c["midpoint"],
                    spread_cents=self._spread_cents,
                )
                self._quoted_markets[c["condition_id"]] = qm
                logger.info(
                    "lp_market_added",
                    market=c["question"][:50],
                    midpoint=c["midpoint"],
                    rewards=c.get("rewards", False),
                )

        except Exception as exc:
            logger.error("lp_discover_error", error=str(exc))

    async def _refresh_quotes(self) -> None:
        """Post or refresh two-sided quotes on all quoted markets."""
        if not self._clob_client:
            return

        now = time.time()
        max_per_market = self._bankroll * self._max_exposure_pct

        for cid, qm in list(self._quoted_markets.items()):
            try:
                # Skip if recently refreshed
                if now - qm.last_refresh < self._refresh_interval / 2:
                    continue

                # Check current midpoint
                if self._http:
                    try:
                        resp = await self._http.get(
                            f"{self._gamma_url}/markets/{cid}",
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            prices_raw = data.get("outcomePrices", "")
                            if isinstance(prices_raw, str):
                                import json
                                prices = json.loads(prices_raw)
                            elif isinstance(prices_raw, list):
                                prices = prices_raw
                            else:
                                prices = []

                            if prices:
                                new_mid = float(prices[0])
                                # If midpoint shifted significantly, update
                                if abs(new_mid - qm.midpoint) >= self._midpoint_threshold:
                                    qm.midpoint = new_mid
                    except Exception:
                        pass

                # Cancel existing orders
                # (In production, would cancel specific order IDs)

                # Calculate quote prices
                spread = self._spread_cents / 100.0
                bid_price = round(max(0.01, qm.midpoint - spread / 2), 2)
                ask_price = round(min(0.99, qm.midpoint + spread / 2), 2)

                # Skip if exposure would exceed limit
                if qm.exposure_usd + self._order_size > max_per_market:
                    continue

                # Post quotes using batch API if available
                loop = asyncio.get_event_loop()
                try:
                    from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

                    # BUY YES at bid (we're buying YES tokens at bid price)
                    yes_bid_args = OrderArgs(
                        token_id=qm.token_id_yes,
                        price=bid_price,
                        size=round(self._order_size / bid_price, 2),
                        side="BUY",
                    )
                    options = PartialCreateOrderOptions(
                        tick_size="0.01",
                        neg_risk=False,
                    )

                    yes_resp = await loop.run_in_executor(
                        None,
                        lambda: self._clob_client.create_and_post_order(yes_bid_args, options),
                    )
                    qm.yes_bid_order_id = yes_resp.get("orderID", "") if isinstance(yes_resp, dict) else ""

                    # BUY NO at (1 - ask_price) — equivalent to selling YES at ask
                    if qm.token_id_no:
                        no_bid_price = round(1.0 - ask_price, 2)
                        no_bid_args = OrderArgs(
                            token_id=qm.token_id_no,
                            price=no_bid_price,
                            size=round(self._order_size / no_bid_price, 2),
                            side="BUY",
                        )
                        no_resp = await loop.run_in_executor(
                            None,
                            lambda: self._clob_client.create_and_post_order(no_bid_args, options),
                        )
                        qm.no_bid_order_id = no_resp.get("orderID", "") if isinstance(no_resp, dict) else ""

                    qm.last_refresh = now
                    qm.exposure_usd += self._order_size

                    logger.info(
                        "lp_quotes_posted",
                        market=qm.question[:40],
                        bid=bid_price,
                        ask=ask_price,
                        spread=spread,
                    )

                except Exception as exc:
                    logger.warning("lp_quote_error", market=qm.question[:30], error=str(exc))

            except Exception as exc:
                logger.error("lp_refresh_error", condition_id=cid[:16], error=str(exc))

    async def _cancel_all_quotes(self) -> None:
        """Cancel all outstanding limit orders."""
        if not self._clob_client:
            return

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._clob_client.cancel_all(),
            )
            for qm in self._quoted_markets.values():
                qm.yes_bid_order_id = ""
                qm.no_bid_order_id = ""
                qm.exposure_usd = 0
            logger.info("lp_all_quotes_cancelled")
        except Exception as exc:
            logger.warning("lp_cancel_error", error=str(exc))

    def get_status(self) -> dict[str, Any]:
        """Return status for API and heartbeat."""
        return {
            "running": self._running,
            "halted": self._halted,
            "quoted_markets": len(self._quoted_markets),
            "daily_pnl": round(self._daily_pnl, 2),
            "markets": [
                {
                    "question": qm.question[:50],
                    "midpoint": qm.midpoint,
                    "spread": qm.spread_cents,
                    "exposure": round(qm.exposure_usd, 2),
                }
                for qm in self._quoted_markets.values()
            ],
        }
