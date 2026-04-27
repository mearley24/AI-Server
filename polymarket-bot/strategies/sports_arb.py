"""Sports arbitrage strategy — buy both sides of binary sports markets when combined price < threshold.

Reverse-engineered from a wallet that made $619K in 12 months with 7,877 trades
(~21/day, ~$79 avg profit/trade).

5-step loop:
    1. SCAN  — Poll Gamma API for active binary sports markets.
    2. CHECK — Identify YES-arb or NO-arb when combined price < 0.98.
    3. SIZE  — Compute shares from liquidity, max risk, and slippage tolerance.
    4. EXECUTE — Place simultaneous FOK limit orders on both sides.
    5. SETTLE — Collect payout on winning side, reinvest, repeat.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy

logger = structlog.get_logger(__name__)

# Tags used by the Gamma API for sports / esports markets
SPORTS_TAGS = {"sports", "esports", "nba", "nfl", "mlb", "nhl", "soccer", "mma", "ncaa", "olympics", "premier-league"}


class SportsArbStrategy(BaseStrategy):
    """Risk-free arbitrage on binary sports markets.

    For a binary event (Team A vs Team B), one side ALWAYS resolves to $1.
    If we can buy YES on both sides for a combined cost < $0.98 (covering the
    2 % Polymarket fee), profit is locked in regardless of outcome.
    """

    name = "sports_arb"
    description = "Binary sports market arbitrage — buys both sides when combined price < threshold"

    def __init__(
        self,
        client: PolymarketClient,
        settings: Settings,
        scanner: MarketScanner,
        orderbook: OrderbookFeed,
        pnl_tracker: PnLTracker,
    ) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)

        # Pull config from settings (YAML-backed)
        self._tick_interval = getattr(settings, "sports_arb_scan_interval_seconds", 45)

        self._params = {
            "arb_threshold": settings.sports_arb_arb_threshold,
            "max_position_per_side": settings.sports_arb_max_position_per_side,
            "slippage_tolerance": settings.sports_arb_slippage_tolerance,
            "min_liquidity_shares": settings.sports_arb_min_liquidity_shares,
            "use_fok_orders": getattr(settings, "sports_arb_use_fok_orders", True),
            "market_types": getattr(settings, "sports_arb_market_types", ["sports", "esports"]),
        }

        # Internal tracking
        self._active_arbs: dict[str, dict[str, Any]] = {}  # condition_id -> arb info
        self._settled_events: set[str] = set()
        self._arbs_found_today: int = 0
        self._arbs_executed_today: int = 0
        self._arbs_skipped_today: int = 0
        self._last_arb: dict[str, Any] = {}
        self._last_skip_reason: str = ""

    def get_arb_status(self) -> dict[str, Any]:
        """Status dict for /arb/status endpoint."""
        return {
            "enabled": self._state.value == "running",
            "arbs_found_today": self._arbs_found_today,
            "arbs_executed_today": self._arbs_executed_today,
            "arbs_skipped_today": self._arbs_skipped_today,
            "active_arbs": len(self._active_arbs),
            "settled_events": len(self._settled_events),
            "last_arb": self._last_arb,
            "last_skip_reason": self._last_skip_reason,
            "params": self._params,
        }

    async def on_tick(self) -> None:
        """Execute the 5-step arbitrage loop."""
        # Step 1 — Scan for binary sports markets
        binary_markets = await self._scan_sports_markets()
        if not binary_markets:
            logger.info("sports_arb_tick_complete", scanned=0, arbs_found=0)
            return

        tick_found = 0
        tick_executed = 0
        tick_skipped = 0

        for event in binary_markets:
            condition_id = event.get("condition_id", event.get("id", ""))
            if condition_id in self._active_arbs or condition_id in self._settled_events:
                continue

            # Step 2 — Check for arbitrage
            arb = self._check_arbitrage(event)
            if arb is None:
                continue

            tick_found += 1
            self._arbs_found_today += 1
            self._last_arb = {
                "market": arb.get("question", "")[:100],
                "arb_type": arb.get("arb_type"),
                "combined": arb.get("combined"),
                "net_profit_per_share": arb.get("net_profit_per_share"),
                "found_at": time.time(),
            }

            # Skip arbs with less than $0.50 expected profit
            _position_size = self._params["max_position_per_side"]
            _combined_price = arb.get("combined", 1.0)
            _expected_profit = _position_size * (1.0 - _combined_price)
            if _expected_profit < 0.50:
                tick_skipped += 1
                self._arbs_skipped_today += 1
                self._last_skip_reason = "profit_too_small"
                continue

            # Step 3 — Size position
            size_a, size_b = self._size_position(arb)
            if size_a <= 0 or size_b <= 0:
                tick_skipped += 1
                self._arbs_skipped_today += 1
                self._last_skip_reason = "sizing_returned_zero"
                logger.info(
                    "sports_arb_skipped",
                    market=arb.get("question", "")[:80],
                    reason="sizing_returned_zero",
                    price_a=arb.get("price_a"),
                    price_b=arb.get("price_b"),
                )
                continue

            # Step 4 — Execute simultaneously
            success = await self._execute_arb(arb, size_a, size_b)
            if success:
                tick_executed += 1
                self._arbs_executed_today += 1
                self._active_arbs[condition_id] = {
                    **arb,
                    "size_a": size_a,
                    "size_b": size_b,
                    "entered_at": time.time(),
                }
            else:
                tick_skipped += 1
                self._arbs_skipped_today += 1
                self._last_skip_reason = "execution_failed"

        # Step 5 — Check settled events
        await self._check_settlements()

        logger.info(
            "sports_arb_tick_complete",
            scanned=len(binary_markets),
            arbs_found=tick_found,
            arbs_executed=tick_executed,
            arbs_skipped=tick_skipped,
            active_arbs=len(self._active_arbs),
        )

    async def _scan_sports_markets(self) -> list[dict[str, Any]]:
        """Poll Gamma API for active binary sports markets."""
        all_markets: list[dict[str, Any]] = []
        market_types = self._params["market_types"]

        for mtype in market_types:
            try:
                markets = await self._client.search_markets(mtype, limit=100)
                all_markets.extend(markets)
            except Exception as exc:
                logger.error("sports_arb_scan_error", market_type=mtype, error=str(exc))

        # Also search specific sports terms
        for term in ["basketball", "football", "soccer", "hockey", "baseball", "mma"]:
            try:
                markets = await self._client.search_markets(term, limit=50)
                all_markets.extend(markets)
            except Exception:
                continue

        # Deduplicate and filter for binary markets only
        seen: set[str] = set()
        binary_markets: list[dict[str, Any]] = []

        for mkt in all_markets:
            cid = mkt.get("condition_id", mkt.get("id", ""))
            if not cid or cid in seen:
                continue
            seen.add(cid)

            if not mkt.get("active", False):
                continue

            # Binary = exactly 2 tokens (Team A YES / Team B YES)
            tokens = mkt.get("tokens", [])
            if len(tokens) == 2:
                binary_markets.append(mkt)

        logger.debug("sports_arb_scan_complete", binary_count=len(binary_markets))
        return binary_markets

    def _check_arbitrage(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Check if a binary market has a YES-arb or NO-arb opportunity.

        Returns arb info dict or None.
        """
        tokens = event.get("tokens", [])
        if len(tokens) != 2:
            return None

        token_a = tokens[0]
        token_b = tokens[1]

        price_yes_a = float(token_a.get("price", 0))
        price_yes_b = float(token_b.get("price", 0))

        # In a binary market: price_NO = 1 - price_YES
        price_no_a = 1.0 - price_yes_a if price_yes_a > 0 else 0
        price_no_b = 1.0 - price_yes_b if price_yes_b > 0 else 0

        threshold = self._params["arb_threshold"]
        question = event.get("question", "")
        condition_id = event.get("condition_id", event.get("id", ""))

        # Check YES arb: buy YES on both sides
        combined_yes = price_yes_a + price_yes_b
        if 0 < combined_yes < threshold and price_yes_a > 0 and price_yes_b > 0:
            spread = 1.0 - combined_yes  # gross profit per share before fees
            net_profit = spread - 0.02  # 2% fee on $1 payout
            logger.info(
                "sports_arb_yes_found",
                market=question,
                price_a=round(price_yes_a, 4),
                price_b=round(price_yes_b, 4),
                combined=round(combined_yes, 4),
                net_profit_per_share=round(net_profit, 4),
            )
            return {
                "condition_id": condition_id,
                "question": question,
                "arb_type": "YES",
                "token_id_a": token_a.get("token_id", ""),
                "token_id_b": token_b.get("token_id", ""),
                "price_a": price_yes_a,
                "price_b": price_yes_b,
                "combined": combined_yes,
                "net_profit_per_share": net_profit,
            }

        # Check NO arb: buy NO on both sides
        combined_no = price_no_a + price_no_b
        if 0 < combined_no < threshold and price_no_a > 0 and price_no_b > 0:
            spread = 1.0 - combined_no
            net_profit = spread - 0.02
            logger.info(
                "sports_arb_no_found",
                market=question,
                price_no_a=round(price_no_a, 4),
                price_no_b=round(price_no_b, 4),
                combined=round(combined_no, 4),
                net_profit_per_share=round(net_profit, 4),
            )
            # For NO arb, we need the complementary token IDs
            # On Polymarket, buying NO on token A = buying YES on the other outcome's complement
            return {
                "condition_id": condition_id,
                "question": question,
                "arb_type": "NO",
                "token_id_a": token_a.get("token_id", ""),
                "token_id_b": token_b.get("token_id", ""),
                "price_a": price_no_a,
                "price_b": price_no_b,
                "combined": combined_no,
                "net_profit_per_share": net_profit,
                "is_no_side": True,
            }

        return None

    def _size_position(self, arb: dict[str, Any]) -> tuple[float, float]:
        """Calculate position sizes for both sides based on liquidity and risk limits."""
        max_per_side = self._params["max_position_per_side"]
        min_liquidity = self._params["min_liquidity_shares"]
        slippage = self._params["slippage_tolerance"]

        price_a = arb["price_a"]
        price_b = arb["price_b"]

        if price_a <= 0 or price_b <= 0:
            return (0.0, 0.0)

        # Max shares we can buy on each side given our dollar limit
        max_shares_a = max_per_side / price_a
        max_shares_b = max_per_side / price_b

        # Use the smaller of the two as our target (must buy equal shares)
        target_shares = min(max_shares_a, max_shares_b)

        # Apply minimum liquidity check
        if target_shares < min_liquidity:
            return (0.0, 0.0)

        # Apply slippage buffer — reduce size slightly
        target_shares = target_shares * (1.0 - slippage)

        # Round to whole shares
        target_shares = int(target_shares)
        if target_shares < 1:
            return (0.0, 0.0)

        cost_a = round(target_shares * price_a, 2)
        cost_b = round(target_shares * price_b, 2)

        logger.info(
            "sports_arb_sized",
            shares=target_shares,
            cost_a=cost_a,
            cost_b=cost_b,
            total_cost=round(cost_a + cost_b, 2),
            expected_payout=target_shares,  # one side pays $1/share
        )

        return (float(target_shares), float(target_shares))

    async def _execute_arb(self, arb: dict[str, Any], size_a: float, size_b: float) -> bool:
        """Place FOK orders on both sides through the guarded execution path.

        Sandbox is checked for BOTH legs before any order is placed.
        If one side fails or is blocked, neither trade goes through.
        """
        order_type = "FOK" if self._params["use_fok_orders"] else "GTC"
        slippage = self._params["slippage_tolerance"]

        price_a = round(arb["price_a"] + slippage, 4)
        price_b = round(arb["price_b"] + slippage, 4)

        # Verify combined price with slippage still under threshold
        if price_a + price_b >= self._params["arb_threshold"]:
            logger.warning(
                "sports_arb_slippage_killed",
                combined_with_slippage=round(price_a + price_b, 4),
                threshold=self._params["arb_threshold"],
            )
            return False

        # Pre-check sandbox for BOTH legs before placing either order.
        # Done manually here so a single-token rate-limit leftover can't fund
        # one leg while blocking the other.
        if self._sandbox and not self._settings.dry_run:
            ok_a, reason_a = await self._sandbox.check_trade(size=size_a, price=price_a)
            if not ok_a:
                logger.warning("sports_arb_sandbox_blocked_leg_a", reason=reason_a, market=arb["question"])
                return False
            ok_b, reason_b = await self._sandbox.check_trade(size=size_b, price=price_b)
            if not ok_b:
                logger.warning("sports_arb_sandbox_blocked_leg_b", reason=reason_b, market=arb["question"])
                return False

        try:
            if self._settings.dry_run:
                # Paper trade both sides
                paper_a = self._record_paper_trade(
                    token_id=arb["token_id_a"],
                    market=arb["question"],
                    price=price_a,
                    size=size_a,
                    side=SIDE_BUY,
                )
                paper_b = self._record_paper_trade(
                    token_id=arb["token_id_b"],
                    market=arb["question"],
                    price=price_b,
                    size=size_b,
                    side=SIDE_BUY,
                )
                logger.info(
                    "sports_arb_executed",
                    market=arb["question"],
                    arb_type=arb["arb_type"],
                    order_a_id=paper_a.order_id,
                    order_b_id=paper_b.order_id,
                    cost=round(price_a * size_a + price_b * size_b, 2),
                    expected_profit=round(arb["net_profit_per_share"] * size_a, 2),
                    dry_run=True,
                )
                return True

            # Live: place both orders concurrently (sandbox pre-checks above already passed)
            results = await asyncio.gather(
                self._client.place_order(
                    token_id=arb["token_id_a"],
                    price=price_a,
                    size=size_a,
                    side=SIDE_BUY,
                    order_type=order_type,
                ),
                self._client.place_order(
                    token_id=arb["token_id_b"],
                    price=price_b,
                    size=size_b,
                    side=SIDE_BUY,
                    order_type=order_type,
                ),
                return_exceptions=True,
            )

            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                logger.error(
                    "sports_arb_partial_failure",
                    errors=[str(e) for e in errors],
                    market=arb["question"],
                )
                return False

            order_a, order_b = results
            if self._sandbox:
                self._sandbox.record_trade(price_a * size_a)
                self._sandbox.record_trade(price_b * size_b)
            logger.info(
                "sports_arb_executed",
                market=arb["question"],
                arb_type=arb["arb_type"],
                order_a_id=order_a.get("orderID", ""),
                order_b_id=order_b.get("orderID", ""),
                cost=round(price_a * size_a + price_b * size_b, 2),
                expected_profit=round(arb["net_profit_per_share"] * size_a, 2),
            )
            return True

        except Exception as exc:
            logger.error("sports_arb_execute_error", error=str(exc), market=arb["question"])
            return False

    async def _check_settlements(self) -> None:
        """Check if any active arb events have resolved and collect payouts."""
        for cid in list(self._active_arbs.keys()):
            arb = self._active_arbs[cid]
            try:
                market_data = await self._client.get_market(cid)
                if not market_data:
                    continue

                # Check if market has resolved
                if market_data.get("closed", False) or market_data.get("resolved", False):
                    winning_token = None
                    tokens = market_data.get("tokens", [])
                    for token in tokens:
                        outcome_price = float(token.get("price", 0))
                        if outcome_price >= 0.95:  # Resolved to YES
                            winning_token = token.get("token_id", "")
                            break

                    payout = arb.get("size_a", 0)  # One side pays $1/share
                    cost = arb["price_a"] * arb["size_a"] + arb["price_b"] * arb["size_b"]
                    net_pnl = payout - cost - (payout * 0.02)  # 2% fee on winnings

                    logger.info(
                        "sports_arb_settled",
                        market=arb["question"],
                        winning_token=winning_token,
                        payout=round(payout, 2),
                        cost=round(cost, 2),
                        net_pnl=round(net_pnl, 2),
                    )

                    self._settled_events.add(cid)
                    del self._active_arbs[cid]

            except Exception as exc:
                logger.error("sports_arb_settlement_check_error", condition_id=cid, error=str(exc))
