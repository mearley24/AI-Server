"""Spread & Arbitrage Scanner — Strategy 3

Three sub-strategies:
1. Complement Arb: YES + NO < $1 on binary markets → buy both, guaranteed profit at settlement
2. Negative Risk Arb: Multi-outcome events where buying all NOs costs less than (n-1)
3. Contrarian Bounce: When a market drops sharply (>15% in 1hr), buy the dip if fundamentals unchanged

Runs every 60 seconds scanning for opportunities.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Configurable thresholds
MIN_COMPLEMENT_SPREAD = float(os.environ.get("ARB_MIN_COMPLEMENT_SPREAD", "0.015"))  # 1.5% minimum
MIN_NEGATIVE_RISK_EDGE = float(os.environ.get("ARB_MIN_NEG_RISK_EDGE", "0.02"))  # 2%
CONTRARIAN_DROP_PCT = float(os.environ.get("ARB_CONTRARIAN_DROP", "0.15"))  # 15% price drop
MAX_POSITION_USD = float(os.environ.get("ARB_MAX_POSITION", "100"))
SCAN_INTERVAL = int(os.environ.get("ARB_SCAN_INTERVAL", "60"))

# Fee assumptions for profitability calc
GAS_FEE = 0.05  # per trade
WINNER_TAX = 0.02  # 2% on profit
SLIPPAGE = 0.005  # 0.5%


@dataclass
class ArbOpportunity:
    """A detected arbitrage or spread opportunity."""
    opp_type: str  # "complement", "negative_risk", "contrarian"
    market_title: str
    condition_id: str
    expected_profit_pct: float
    expected_profit_usd: float
    cost_usd: float
    tokens: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    detected_at: float = field(default_factory=time.time)


@dataclass
class PriceSnapshot:
    """Historical price snapshot for contrarian detection."""
    condition_id: str
    price: float
    timestamp: float


class SpreadArbScanner:
    """Scans Polymarket for arbitrage and spread opportunities."""

    def __init__(self, bankroll: float = 12500.0, dry_run: bool = True):
        self._bankroll = bankroll
        self._dry_run = dry_run
        self._opportunities: list[ArbOpportunity] = []
        self._price_history: dict[str, list[PriceSnapshot]] = {}  # condition_id -> snapshots
        self._positions: dict[str, dict] = {}  # active arb positions
        self._pnl_realized: float = 0.0
        self._pnl_unrealized: float = 0.0
        self._trades_count: int = 0
        self._wins: int = 0
        self._losses: int = 0
        self._running = False

    async def scan_once(self) -> list[ArbOpportunity]:
        """Run a single scan across all three sub-strategies."""
        opps = []
        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch markets
            markets = await self._fetch_markets(client)
            events = await self._fetch_events(client)

            # 1. Complement arbitrage
            complement = self._scan_complement_arb(markets)
            opps.extend(complement)

            # 2. Negative risk arbitrage
            neg_risk = self._scan_negative_risk(events)
            opps.extend(neg_risk)

            # 3. Contrarian bounce
            contrarian = self._scan_contrarian(markets)
            opps.extend(contrarian)

            # Update price history
            self._update_price_history(markets)

        self._opportunities = opps
        return opps

    async def _fetch_markets(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch active binary markets with prices."""
        try:
            r = await client.get("https://gamma-api.polymarket.com/markets", params={
                "active": "true", "closed": "false", "limit": 200,
                "order": "volume24hr", "ascending": "false",
            })
            return r.json() if r.status_code == 200 else []
        except Exception as e:
            logger.error("arb_fetch_markets_error", error=str(e))
            return []

    async def _fetch_events(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch active events (for multi-outcome arb)."""
        try:
            r = await client.get("https://gamma-api.polymarket.com/events", params={
                "active": "true", "closed": "false", "limit": 50,
                "order": "volume24hr", "ascending": "false",
            })
            return r.json() if r.status_code == 200 else []
        except Exception as e:
            logger.error("arb_fetch_events_error", error=str(e))
            return []

    def _scan_complement_arb(self, markets: list[dict]) -> list[ArbOpportunity]:
        """Find binary markets where YES + NO < $1."""
        opps = []
        for m in markets:
            op = m.get("outcomePrices", "")
            if not op:
                continue
            try:
                prices = json.loads(op) if isinstance(op, str) else op
                if len(prices) < 2:
                    continue
                yes_p = float(prices[0])
                no_p = float(prices[1])
            except (json.JSONDecodeError, ValueError, IndexError):
                continue

            total = yes_p + no_p
            if total >= 1.0 or total <= 0:
                continue

            spread = 1.0 - total
            # Account for fees: 2 trades (buy yes + buy no) = 2x gas + slippage on both
            fee_cost = (GAS_FEE * 2) + (total * SLIPPAGE * 2)
            net_spread = spread - fee_cost

            if net_spread / total < MIN_COMPLEMENT_SPREAD:
                continue

            profit_pct = (net_spread / total) * 100
            # Size: how much to deploy
            size = min(MAX_POSITION_USD, self._bankroll * 0.05)
            profit_usd = size * (net_spread / total)

            opps.append(ArbOpportunity(
                opp_type="complement",
                market_title=m.get("question", "")[:80],
                condition_id=m.get("conditionId", ""),
                expected_profit_pct=round(profit_pct, 2),
                expected_profit_usd=round(profit_usd, 2),
                cost_usd=round(size, 2),
                tokens=[{"outcome": "Yes", "price": yes_p}, {"outcome": "No", "price": no_p}],
                metadata={"total": round(total, 4), "spread": round(spread, 4), "net_spread": round(net_spread, 4)},
            ))

        if opps:
            logger.info("arb_complement_found", count=len(opps),
                        best_pct=max(o.expected_profit_pct for o in opps))
        return opps

    def _scan_negative_risk(self, events: list[dict]) -> list[ArbOpportunity]:
        """Find multi-outcome events where buying all NOs is profitable."""
        opps = []
        for evt in events:
            markets = evt.get("markets", [])
            if len(markets) < 3:
                continue

            no_prices = []
            for m in markets:
                op = m.get("outcomePrices", "")
                if not op:
                    continue
                try:
                    prices = json.loads(op) if isinstance(op, str) else op
                    no_p = float(prices[1]) if len(prices) > 1 else None
                    if no_p and no_p > 0:
                        no_prices.append({"price": no_p, "market": m.get("question", "")[:50]})
                except (json.JSONDecodeError, ValueError, IndexError):
                    continue

            if len(no_prices) < 3:
                continue

            n = len(no_prices)
            total_no_cost = sum(p["price"] for p in no_prices)
            payout = n - 1  # All NOs win except the actual winner

            # Account for fees
            fee_cost = GAS_FEE * n + total_no_cost * SLIPPAGE
            net_profit = payout - total_no_cost - fee_cost

            if total_no_cost <= 0:
                continue
            profit_pct = (net_profit / total_no_cost) * 100

            if profit_pct < MIN_NEGATIVE_RISK_EDGE * 100:
                continue

            size = min(MAX_POSITION_USD, self._bankroll * 0.03)
            scale = size / total_no_cost if total_no_cost > 0 else 0

            opps.append(ArbOpportunity(
                opp_type="negative_risk",
                market_title=evt.get("title", "")[:80],
                condition_id=evt.get("slug", ""),
                expected_profit_pct=round(profit_pct, 2),
                expected_profit_usd=round(net_profit * scale, 2),
                cost_usd=round(total_no_cost * scale, 2),
                metadata={"outcomes": n, "total_no_cost": round(total_no_cost, 4), "payout": payout},
            ))

        if opps:
            logger.info("arb_negative_risk_found", count=len(opps),
                        best_pct=max(o.expected_profit_pct for o in opps))
        return opps

    def _scan_contrarian(self, markets: list[dict]) -> list[ArbOpportunity]:
        """Find markets that dropped sharply — potential contrarian bounce."""
        opps = []
        now = time.time()
        one_hour_ago = now - 3600

        for m in markets:
            cid = m.get("conditionId", "")
            op = m.get("outcomePrices", "")
            if not op or not cid:
                continue
            try:
                prices = json.loads(op) if isinstance(op, str) else op
                current_price = float(prices[0])
            except (json.JSONDecodeError, ValueError, IndexError):
                continue

            # Check price history for this market
            history = self._price_history.get(cid, [])
            recent = [s for s in history if s.timestamp >= one_hour_ago]

            if not recent:
                continue

            # Find max price in last hour
            max_recent = max(s.price for s in recent)
            if max_recent <= 0:
                continue

            drop_pct = (max_recent - current_price) / max_recent

            if drop_pct < CONTRARIAN_DROP_PCT:
                continue

            # Only buy if price is now cheap enough (under 60¢)
            if current_price > 0.60:
                continue

            potential_return = (max_recent / current_price - 1) * 100 if current_price > 0 else 0
            size = min(MAX_POSITION_USD * 0.5, self._bankroll * 0.02)  # Smaller size for contrarian

            opps.append(ArbOpportunity(
                opp_type="contrarian",
                market_title=m.get("question", "")[:80],
                condition_id=cid,
                expected_profit_pct=round(potential_return, 2),
                expected_profit_usd=round(size * drop_pct, 2),
                cost_usd=round(size, 2),
                tokens=[{"outcome": "Yes", "price": current_price}],
                metadata={
                    "drop_pct": round(drop_pct * 100, 1),
                    "max_1hr": round(max_recent, 3),
                    "current": round(current_price, 3),
                },
            ))

        if opps:
            logger.info("arb_contrarian_found", count=len(opps),
                        best_drop=max(o.metadata.get("drop_pct", 0) for o in opps))
        return opps

    def _update_price_history(self, markets: list[dict]) -> None:
        """Store current prices for contrarian detection."""
        now = time.time()
        cutoff = now - 7200  # Keep 2 hours of history

        for m in markets:
            cid = m.get("conditionId", "")
            op = m.get("outcomePrices", "")
            if not cid or not op:
                continue
            try:
                prices = json.loads(op) if isinstance(op, str) else op
                price = float(prices[0])
            except (json.JSONDecodeError, ValueError, IndexError):
                continue

            if cid not in self._price_history:
                self._price_history[cid] = []

            self._price_history[cid].append(PriceSnapshot(cid, price, now))
            # Trim old entries
            self._price_history[cid] = [s for s in self._price_history[cid] if s.timestamp >= cutoff]

    async def run(self) -> None:
        """Main loop — scan continuously."""
        self._running = True
        logger.info("spread_arb_started", bankroll=self._bankroll, dry_run=self._dry_run)

        while self._running:
            try:
                opps = await self.scan_once()
                if opps:
                    for opp in sorted(opps, key=lambda o: -o.expected_profit_pct)[:5]:
                        logger.info(
                            "arb_opportunity",
                            type=opp.opp_type,
                            profit_pct=opp.expected_profit_pct,
                            profit_usd=opp.expected_profit_usd,
                            cost=opp.cost_usd,
                            market=opp.market_title[:50],
                        )
                        # In paper mode, record the trade
                        if self._dry_run:
                            self._record_paper_trade(opp)
                        # In live mode, execute via CLOB
                        # (wired up when ready to go live)
                else:
                    logger.debug("arb_no_opportunities")

            except Exception as e:
                logger.error("arb_scan_error", error=str(e)[:200])

            await asyncio.sleep(SCAN_INTERVAL)

    def _record_paper_trade(self, opp: ArbOpportunity) -> None:
        """Record a paper trade for the opportunity."""
        self._trades_count += 1
        self._positions[opp.condition_id] = {
            "type": opp.opp_type,
            "cost": opp.cost_usd,
            "expected_profit": opp.expected_profit_usd,
            "entered_at": time.time(),
            "market": opp.market_title,
        }
        self._bankroll -= opp.cost_usd
        logger.info(
            "arb_paper_trade",
            type=opp.opp_type,
            cost=opp.cost_usd,
            expected_profit=opp.expected_profit_usd,
            bankroll=round(self._bankroll, 2),
            total_trades=self._trades_count,
        )

    def stop(self) -> None:
        self._running = False

    @property
    def status(self) -> dict:
        return {
            "bankroll": round(self._bankroll, 2),
            "positions": len(self._positions),
            "trades": self._trades_count,
            "realized_pnl": round(self._pnl_realized, 2),
            "opportunities_last_scan": len(self._opportunities),
            "price_history_markets": len(self._price_history),
        }
