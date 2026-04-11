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

from strategies import kalshi_client

logger = structlog.get_logger(__name__)

# Configurable thresholds
MIN_COMPLEMENT_SPREAD = float(os.environ.get("ARB_MIN_COMPLEMENT_SPREAD", "0.015"))  # 1.5% minimum
MIN_NEGATIVE_RISK_EDGE = float(os.environ.get("ARB_MIN_NEG_RISK_EDGE", "0.02"))  # 2%
CONTRARIAN_DROP_PCT = float(os.environ.get("ARB_CONTRARIAN_DROP", "0.15"))  # 15% price drop
MAX_POSITION_USD = float(os.environ.get("ARB_MAX_POSITION", "50"))
MAX_PER_SIDE = float(os.environ.get("ARB_MAX_PER_SIDE", "25"))
MAX_DAILY_TRADES = int(os.environ.get("ARB_MAX_DAILY_TRADES", "100"))
MAX_TOTAL_EXPOSURE = float(os.environ.get("ARB_MAX_EXPOSURE", "2000"))
SCAN_INTERVAL = int(os.environ.get("ARB_SCAN_INTERVAL", "300"))  # 5 min between scans

LOW_BALANCE_MODE = os.environ.get("LOW_BALANCE_MODE", "false").lower() in ("true", "1", "yes")


def effective_min_complement_spread() -> float:
    """Double minimum edge when LOW_BALANCE_MODE is on."""
    return MIN_COMPLEMENT_SPREAD * 2 if LOW_BALANCE_MODE else MIN_COMPLEMENT_SPREAD


def effective_scan_interval_sec() -> int:
    """15 min between scans when low-balance mode (vs 5 min default)."""
    return SCAN_INTERVAL * 3 if LOW_BALANCE_MODE else SCAN_INTERVAL


# Fee assumptions for profitability calc
GAS_FEE = 0.005  # Polygon gas is ~$0.003-0.005 per tx
WINNER_TAX = 0.02  # 2% on profit
SLIPPAGE = 0.005  # 0.5%


def _parse_clob_ids(raw: Any) -> list[str]:
    """Parse clobTokenIds from Gamma API (may be JSON string or list)."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(raw, list):
        return [str(x).strip().strip('"') for x in raw if x]
    return []


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
    token_ids: list[str] = field(default_factory=list)  # decimal clobTokenIds from Gamma API
    neg_risk: bool = False
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

    def __init__(self, bankroll: float = 250.0, dry_run: bool = False, paper_mode: bool = False, client: Any = None):
        self._bankroll = bankroll
        self._dry_run = dry_run
        self._paper_mode = paper_mode
        self._client = client
        self._clob_client = None
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            pk = os.environ.get("POLY_PRIVATE_KEY", "")
            api_key = os.environ.get("POLY_BUILDER_API_KEY", "")
            if pk and api_key:
                if not pk.startswith("0x"):
                    pk = f"0x{pk}"
                creds = ApiCreds(
                    api_key=api_key,
                    api_secret=os.environ.get("POLY_BUILDER_API_SECRET", ""),
                    api_passphrase=os.environ.get("POLY_BUILDER_API_PASSPHRASE", ""),
                )
                self._clob_client = ClobClient(
                    os.environ.get("CLOB_API_URL", "https://clob.polymarket.com"),
                    key=pk,
                    chain_id=int(os.environ.get("CHAIN_ID", "137")),
                    creds=creds,
                    signature_type=0,
                )
                logger.info("spread_arb_clob_client_initialized")
        except Exception as exc:
            logger.warning("spread_arb_clob_client_init_error", error=str(exc))
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
        # Guard: daily trade limit and total exposure (skip in paper mode)
        if not self._paper_mode:
            total_exposure = sum(p.get("cost", 0) for p in self._positions.values())
            if self._trades_count >= MAX_DAILY_TRADES:
                logger.info("arb_daily_limit_reached", trades=self._trades_count, limit=MAX_DAILY_TRADES)
                return []
            if total_exposure >= MAX_TOTAL_EXPOSURE:
                logger.info("arb_max_exposure_reached", exposure=total_exposure, limit=MAX_TOTAL_EXPOSURE)
                return []

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

            # 3. Contrarian bounce (skip in low-balance mode — too risky)
            if not LOW_BALANCE_MODE:
                contrarian = self._scan_contrarian(markets)
                opps.extend(contrarian)
            else:
                logger.info("arb_contrarian_skipped_low_balance_mode")

            # 4. Consolidation breakout (MoonDev extreme consolidation)
            consolidation = self._scan_consolidation(markets)
            opps.extend(consolidation)

            # Update price history
            self._update_price_history(markets)

            # 5. Cross-platform (Polymarket vs Kalshi) — Auto-1
            cross = await self._scan_cross_platform(client, markets)
            opps.extend(cross)

        self._opportunities = opps
        return opps


    async def _scan_cross_platform(
        self, client: httpx.AsyncClient, poly_markets: list[dict]
    ) -> list[ArbOpportunity]:
        """Match Polymarket vs Kalshi titles; flag >3% mispricing after fees."""
        try:
            kalshi = await kalshi_client.fetch_kalshi_markets(limit=200)
        except Exception as exc:
            logger.warning("cross_platform_kalshi_failed", error=str(exc)[:120])
            return []
        if not kalshi:
            return []

        min_sim = float(os.environ.get("CROSS_PLATFORM_MIN_SIMILARITY", "0.72"))
        min_gap = float(os.environ.get("CROSS_PLATFORM_MIN_GAP", "0.03"))
        poly_fee = float(os.environ.get("CROSS_PLATFORM_POLY_FEE", "0.02"))
        kalshi_fee = float(os.environ.get("CROSS_PLATFORM_KALSHI_FEE", "0.01"))

        opps: list[ArbOpportunity] = []
        for pm in poly_markets:
            pq = (pm.get("question") or "")[:500]
            if not pq:
                continue
            pyes = 0.0
            try:
                op = pm.get("outcomePrices")
                if isinstance(op, str):
                    import json as _json
                    op = _json.loads(op)
                if isinstance(op, list) and op:
                    pyes = float(op[0])
            except Exception:
                continue
            best_k = None
            best_sim = 0.0
            for km in kalshi:
                title = km.get("title") or km.get("ticker") or ""
                sim = kalshi_client.title_similarity(pq, title)
                if sim > best_sim:
                    best_sim = sim
                    best_k = km
            if best_k is None or best_sim < min_sim:
                continue
            k_mid = kalshi_client.kalshi_mid_price(best_k)
            if k_mid is None or k_mid <= 0:
                continue
            gap = abs(pyes - k_mid)
            net = gap - (poly_fee + kalshi_fee)
            if net < min_gap:
                continue
            profit_pct = net * 100
            size = min(MAX_POSITION_USD, self._bankroll * 0.05)
            clob_ids = _parse_clob_ids(pm.get("clobTokenIds"))
            opps.append(
                ArbOpportunity(
                    opp_type="cross_platform",
                    market_title=f"{pq[:60]} | Kalshi: {best_k.get('ticker','')}",
                    condition_id=pm.get("conditionId", ""),
                    expected_profit_pct=round(profit_pct, 2),
                    expected_profit_usd=round(size * net, 2),
                    cost_usd=round(size, 2),
                    tokens=[{"poly_yes": pyes, "kalshi_mid": k_mid, "similarity": best_sim}],
                    token_ids=clob_ids,
                    metadata={"kalshi_ticker": best_k.get("ticker", "")},
                )
            )
        if opps:
            logger.info("cross_platform_matches", count=len(opps))
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

            if net_spread / total < effective_min_complement_spread():
                continue

            profit_pct = (net_spread / total) * 100
            # Size: how much to deploy
            size = min(MAX_POSITION_USD, self._bankroll * 0.05)
            profit_usd = size * (net_spread / total)

            clob_ids = _parse_clob_ids(m.get("clobTokenIds"))
            opps.append(ArbOpportunity(
                opp_type="complement",
                market_title=m.get("question", "")[:80],
                condition_id=m.get("conditionId", ""),
                expected_profit_pct=round(profit_pct, 2),
                expected_profit_usd=round(profit_usd, 2),
                cost_usd=round(size, 2),
                tokens=[{"outcome": "Yes", "price": yes_p}, {"outcome": "No", "price": no_p}],
                token_ids=clob_ids,
                metadata={"total": round(total, 4), "spread": round(spread, 4), "net_spread": round(net_spread, 4)},
            ))

        if opps:
            logger.info("arb_complement_found", count=len(opps),
                        best_pct=max(o.expected_profit_pct for o in opps))
        return opps

    def _scan_negative_risk(self, events: list[dict]) -> list[ArbOpportunity]:
        """Find multi-outcome events where buying ALL NOs is profitable.
        
        Key: must buy EVERY NO in the event for this to be an arb.
        If you miss even one, it's just a bet. The arb works because
        exactly one outcome resolves YES (its NO loses), but all other
        NOs resolve at $1. Cost = sum(all NO prices). Payout = (n-1) * $1.
        Profit if cost < payout after fees.
        """
        opps = []
        for evt in events:
            markets = evt.get("markets", [])
            if len(markets) < 3:
                continue

            no_prices = []
            all_have_prices = True
            for m in markets:
                op = m.get("outcomePrices", "")
                if not op:
                    all_have_prices = False
                    break
                try:
                    prices = json.loads(op) if isinstance(op, str) else op
                    no_p = float(prices[1]) if len(prices) > 1 else None
                    if no_p and no_p > 0:
                        m_clob = _parse_clob_ids(m.get("clobTokenIds"))
                        no_prices.append({
                            "price": no_p,
                            "market": m.get("question", "")[:50],
                            "condition_id": m.get("conditionId", ""),
                            "no_token_id": m_clob[1] if len(m_clob) > 1 else "",
                        })
                    else:
                        all_have_prices = False
                        break
                except (json.JSONDecodeError, ValueError, IndexError):
                    all_have_prices = False
                    break

            # Must have prices for ALL markets — can't arb with missing data
            if not all_have_prices or len(no_prices) != len(markets):
                continue
            if len(no_prices) < 3:
                continue

            n = len(no_prices)
            total_no_cost = sum(p["price"] for p in no_prices)
            payout = n - 1  # All NOs win except the actual winner

            # Account for fees: gas per trade (n trades), slippage on total, winner tax on profit
            fee_cost = GAS_FEE * n + total_no_cost * SLIPPAGE
            gross_profit = payout - total_no_cost
            winner_tax = gross_profit * WINNER_TAX if gross_profit > 0 else 0
            net_profit = gross_profit - fee_cost - winner_tax

            if total_no_cost <= 0 or net_profit <= 0:
                continue
            profit_pct = (net_profit / total_no_cost) * 100

            if profit_pct < MIN_NEGATIVE_RISK_EDGE * 100:
                continue

            # Size: scale proportionally — buy all NOs at once
            size = min(MAX_POSITION_USD, self._bankroll * 0.03)
            scale = size / total_no_cost if total_no_cost > 0 else 0

            all_no_token_ids = [p["no_token_id"] for p in no_prices if p.get("no_token_id")]
            is_neg_risk = evt.get("negRisk", False) or evt.get("neg_risk", False)
            opps.append(ArbOpportunity(
                opp_type="negative_risk",
                market_title=evt.get("title", "")[:80],
                condition_id=evt.get("slug", ""),  # Event slug as the composite ID
                expected_profit_pct=round(profit_pct, 2),
                expected_profit_usd=round(net_profit * scale, 2),
                cost_usd=round(total_no_cost * scale, 2),
                tokens=[{"condition_id": p["condition_id"], "no_price": p["price"], "market": p["market"], "no_token_id": p.get("no_token_id", "")} for p in no_prices],
                token_ids=all_no_token_ids,
                neg_risk=is_neg_risk,
                metadata={
                    "outcomes": n,
                    "total_no_cost": round(total_no_cost, 4),
                    "payout": payout,
                    "gross_profit": round(gross_profit, 4),
                    "fees": round(fee_cost + winner_tax, 4),
                    "net_profit": round(net_profit, 4),
                    "all_nos_required": True,
                },
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

            clob_ids = _parse_clob_ids(m.get("clobTokenIds"))
            opps.append(ArbOpportunity(
                opp_type="contrarian",
                market_title=m.get("question", "")[:80],
                condition_id=cid,
                expected_profit_pct=round(potential_return, 2),
                expected_profit_usd=round(size * drop_pct, 2),
                cost_usd=round(size, 2),
                tokens=[{"outcome": "Yes", "price": current_price}],
                token_ids=clob_ids,
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

    def _scan_consolidation(self, markets: list[dict]) -> list[ArbOpportunity]:
        """Detect markets in extreme consolidation — price flat within 2% for 6+ hours.
        
        MoonDev's extreme consolidation: when a market has been flat, it's about to explode.
        These are high-probability setups for buying cheap before a big move.
        """
        opps = []
        now = time.time()
        six_hours_ago = now - 21600

        for m in markets:
            cid = m.get("conditionId", "")
            op = m.get("outcomePrices", "")
            if not cid or not op:
                continue
            try:
                prices = json.loads(op) if isinstance(op, str) else op
                current_price = float(prices[0])
            except (json.JSONDecodeError, ValueError, IndexError):
                continue

            # Need 6+ hours of history
            history = self._price_history.get(cid, [])
            recent = [s for s in history if s.timestamp >= six_hours_ago]
            if len(recent) < 20:  # Need enough data points
                continue

            prices_list = [s.price for s in recent]
            high = max(prices_list)
            low = min(prices_list)
            mid = (high + low) / 2

            if mid <= 0:
                continue

            # Consolidation = range < 2% of midpoint
            range_pct = (high - low) / mid
            if range_pct > 0.02:
                continue

            # Only interesting if price is in the 20-80% range (not near-certain)
            if current_price < 0.20 or current_price > 0.80:
                continue

            # Hours consolidated
            hours_flat = (now - recent[0].timestamp) / 3600

            size = min(MAX_POSITION_USD * 0.3, self._bankroll * 0.01)

            clob_ids = _parse_clob_ids(m.get("clobTokenIds"))
            opps.append(ArbOpportunity(
                opp_type="consolidation_breakout",
                market_title=m.get("question", "")[:80],
                condition_id=cid,
                expected_profit_pct=round((1.0 / current_price - 1) * 100 * 0.3, 2),  # Conservative 30% of max
                expected_profit_usd=round(size * 0.3, 2),
                cost_usd=round(size, 2),
                tokens=[{"outcome": "Yes", "price": current_price}],
                token_ids=clob_ids,
                metadata={
                    "hours_flat": round(hours_flat, 1),
                    "range_pct": round(range_pct * 100, 2),
                    "high": round(high, 3),
                    "low": round(low, 3),
                    "current": round(current_price, 3),
                },
            ))

        if opps:
            logger.info("arb_consolidation_found", count=len(opps),
                        best_hours=max(o.metadata.get("hours_flat", 0) for o in opps))
        return opps

    def _update_price_history(self, markets: list[dict]) -> None:
        """Store current prices for contrarian detection."""
        now = time.time()
        cutoff = now - 28800  # Keep 8 hours of history for consolidation detection

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

    async def execute_opportunities(self, opps: list[ArbOpportunity]) -> tuple[int, int]:
        """Execute up to 3 top opportunities. Returns (executed, skipped)."""
        MIN_PROFIT_PCT = 0.5   # arb is risk-free, even small edges compound
        MAX_PER_TICK = 5       # execute up to 5 arbs per scan
        MAX_PER_SIDE = 15.0    # up to $15 per side

        sorted_opps = sorted(opps, key=lambda o: -o.expected_profit_pct)
        executed = 0
        skipped = 0

        total_exposure = sum(p.get("cost", 0) for p in self._positions.values())

        usdc_balance = 999999.0
        try:
            from web3 import Web3
            _w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            _usdc = _w3.eth.contract(
                address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
                abi=[{"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}],
            )
            wallet = os.environ.get("POLY_PROXY_ADDRESS", os.environ.get("POLY_SAFE_ADDRESS", ""))
            if wallet:
                usdc_balance = _usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
                logger.info("arb_wallet_balance", usdc=round(usdc_balance, 2))
        except Exception:
            pass
        try:
            _usdc_native = _w3.eth.contract(
                address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
                abi=[{"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}],
            )
            usdc_native = _usdc_native.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
            usdc_balance += usdc_native
        except Exception:
            pass

        for opp in sorted_opps[:MAX_PER_TICK]:
            min_profitable = (GAS_FEE * 2) + (SLIPPAGE * opp.cost_usd) + 0.01
            if opp.expected_profit_usd < min_profitable:
                logger.info(
                    "arb_skipped_unprofitable",
                    market=opp.market_title[:60],
                    expected_profit=round(opp.expected_profit_usd, 4),
                    min_required=round(min_profitable, 4),
                    reason="fees_exceed_edge",
                )
                skipped += 1
                continue

            if opp.expected_profit_pct < MIN_PROFIT_PCT:
                skipped += 1
                continue

            if opp.condition_id in self._positions:
                skipped += 1
                continue

            if self._trades_count >= MAX_DAILY_TRADES:
                logger.info("arb_daily_limit", trades=self._trades_count)
                break

            if total_exposure + opp.cost_usd > MAX_TOTAL_EXPOSURE:
                skipped += 1
                continue

            size = min(MAX_PER_SIDE, opp.cost_usd / 2.0)
            if size < 1.0:
                skipped += 1
                continue

            available = usdc_balance
            if opp.cost_usd > available * 0.9:
                logger.info(
                    "arb_skipped_low_balance",
                    market=opp.market_title[:60],
                    cost=opp.cost_usd,
                    available=round(available, 2),
                )
                skipped += 1
                continue

            if self._dry_run or not self._clob_client:
                if not self._clob_client and not self._dry_run:
                    logger.info("spread_arb_skip_no_clob_client")
                self._record_paper_trade(opp)
                executed += 1
                total_exposure += opp.cost_usd
                continue

            try:
                from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions, OrderType as ClobOrderType

                loop = asyncio.get_event_loop()
                options = PartialCreateOrderOptions(tick_size="0.01", neg_risk=opp.neg_risk)

                if opp.opp_type == "complement":
                    if len(opp.token_ids) < 2:
                        logger.warning("arb_skip_no_token_ids", market=opp.market_title[:60], type=opp.opp_type, ids=len(opp.token_ids))
                        skipped += 1
                        continue

                    total_cost_check = sum(
                        round(min(0.99, max(0.01, opp.tokens[i]["price"] + 0.005)), 2)
                        for i in range(2)
                    )
                    if total_cost_check >= 1.0:
                        logger.info("arb_complement_skip_no_edge", market=opp.market_title[:60], total_cost=total_cost_check)
                        skipped += 1
                        continue

                    order_results = []
                    for i in range(2):
                        tid = str(opp.token_ids[i])
                        price = min(0.99, min(0.99, max(0.01, round(opp.tokens[i]["price"] + 0.005, 4))))
                        shares = min(round(min(size, MAX_PER_SIDE) / max(0.01, opp.tokens[i]["price"]), 2), 500)
                        logger.info(
                            "arb_order_debug",
                            market=opp.condition_id[:20],
                            side=i,
                            size=size,
                            price=price,
                            shares=shares,
                            cost_usd=round(shares * price, 2),
                        )
                        if shares < 1:
                            continue
                        args = OrderArgs(token_id=tid, price=price, size=shares, side="BUY")
                        resp = await loop.run_in_executor(
                            None, lambda a=args, o=options: self._clob_client.create_and_post_order(a, o),
                        )
                        order_results.append(resp)

                    if order_results:
                        self._positions[opp.condition_id] = {
                            "type": opp.opp_type, "cost": opp.cost_usd,
                            "expected_profit": opp.expected_profit_usd,
                            "entered_at": time.time(), "market": opp.market_title,
                        }
                        self._trades_count += 1
                        self._bankroll -= opp.cost_usd
                        executed += 1
                        total_exposure += opp.cost_usd
                        logger.info("arb_trade_executed", market=opp.market_title[:60], type="complement", size=round(size, 2), expected_profit_pct=opp.expected_profit_pct, orders=len(order_results))

                elif opp.opp_type == "negative_risk":
                    if not opp.token_ids:
                        logger.warning("arb_skip_no_token_ids", market=opp.market_title[:60], type=opp.opp_type)
                        skipped += 1
                        continue

                    order_results = []
                    for idx, tok in enumerate(opp.tokens):
                        no_tid = tok.get("no_token_id", "")
                        if not no_tid and idx < len(opp.token_ids):
                            no_tid = opp.token_ids[idx]
                        if not no_tid:
                            continue
                        no_price = tok.get("no_price") or tok.get("price", 0)
                        if no_price <= 0:
                            continue
                        shares = min(round(size / max(0.01, no_price), 2), 500)
                        if shares < 1:
                            continue
                        args = OrderArgs(token_id=str(no_tid), price=min(0.99, min(0.99, max(0.01, round(no_price + SLIPPAGE, 4)))), size=shares, side="BUY")
                        resp = await loop.run_in_executor(
                            None, lambda a=args, o=options: self._clob_client.create_and_post_order(a, o),
                        )
                        order_results.append(resp)

                    if order_results:
                        self._positions[opp.condition_id] = {
                            "type": opp.opp_type, "cost": opp.cost_usd,
                            "expected_profit": opp.expected_profit_usd,
                            "entered_at": time.time(), "market": opp.market_title,
                        }
                        self._trades_count += 1
                        self._bankroll -= opp.cost_usd
                        executed += 1
                        total_exposure += opp.cost_usd
                        logger.info("arb_trade_executed", market=opp.market_title[:60], type="negative_risk", size=round(size, 2), expected_profit_pct=opp.expected_profit_pct, orders=len(order_results))
                    else:
                        logger.warning("arb_trade_no_orders", type="negative_risk", market=opp.market_title[:60])
                        skipped += 1

                else:
                    if not opp.token_ids:
                        logger.warning("arb_skip_no_token_ids", market=opp.market_title[:60], type=opp.opp_type)
                        skipped += 1
                        continue

                    yes_tid = str(opp.token_ids[0])
                    price = opp.tokens[0].get("price", 0) if opp.tokens else 0
                    if price > 0:
                        shares = min(round(size / max(0.01, price), 2), 500)
                        if shares >= 1:
                            args = OrderArgs(token_id=yes_tid, price=min(0.99, min(0.99, max(0.01, round(price + SLIPPAGE, 4)))), size=shares, side="BUY")
                            resp = await loop.run_in_executor(
                                None, lambda a=args, o=options: self._clob_client.create_and_post_order(a, o),
                            )
                            self._positions[opp.condition_id] = {
                                "type": opp.opp_type, "cost": round(size, 2),
                                "expected_profit": opp.expected_profit_usd,
                                "entered_at": time.time(), "market": opp.market_title,
                            }
                            self._trades_count += 1
                            self._bankroll -= size
                            executed += 1
                            total_exposure += size
                            logger.info("arb_trade_executed", market=opp.market_title[:60], type=opp.opp_type, size=round(size, 2), expected_profit_pct=opp.expected_profit_pct)

            except Exception as exc:
                logger.error("arb_trade_error", market=opp.market_title[:60], error=str(exc)[:200])
                skipped += 1

        return executed, skipped

    async def run(self) -> None:
        """Main loop — scan and execute continuously."""
        self._running = True
        logger.info("spread_arb_started", bankroll=self._bankroll, dry_run=self._dry_run, low_balance_mode=LOW_BALANCE_MODE)
        if LOW_BALANCE_MODE:
            logger.info(
                "low_balance_mode_active",
                min_complement_spread=effective_min_complement_spread(),
                scan_interval_sec=effective_scan_interval_sec(),
            )

        while self._running:
            try:
                # Clean up stale positions (>24h) to prevent exposure leak
                now_cleanup = time.time()
                stale_keys = [k for k, v in self._positions.items() if now_cleanup - v.get("entered_at", 0) > 86400]
                for k in stale_keys:
                    stale_pos = self._positions.pop(k)
                    logger.info("spread_arb_cleared_stale", position_id=k[:20], market=stale_pos.get("market", "")[:40], age_hours=round((now_cleanup - stale_pos.get("entered_at", 0)) / 3600, 1))

                opps = await self.scan_once()
                executed = 0
                skipped = 0

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

                    executed, skipped = await self.execute_opportunities(opps)

                logger.info(
                    "arb_tick_complete",
                    found=len(opps),
                    executed=executed,
                    skipped=skipped,
                    positions=len(self._positions),
                    trades_today=self._trades_count,
                )

            except Exception as e:
                logger.error("arb_scan_error", error=str(e)[:200])

            await asyncio.sleep(effective_scan_interval_sec())

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
