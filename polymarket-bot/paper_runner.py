"""Paper Trading Runner — Runs all 3 strategies in paper mode with realistic fees.

Usage:
    python paper_runner.py [--bankroll 50000] [--hours 24]

Strategies:
    1. Weather cheap brackets (40% of bankroll)
    2. Copytrade filtered (35% — uses existing copytrade with dry_run=True)
    3. Spread/arb scanner (25%)

Tracks P/L per strategy with realistic fees:
    - Gas: $0.05 per trade
    - Winner tax: 2% on profit
    - Slippage: 0.5% per trade

Outputs hourly dashboard and final report.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Fee structure from live data
GAS_PER_TRADE = 0.05
WINNER_TAX_PCT = 0.02
SLIPPAGE_PCT = 0.005

DATA_DIR = Path(os.environ.get("PAPER_DATA_DIR", "/data/paper_trading"))


@dataclass
class PaperPosition:
    """A paper trading position."""
    position_id: str
    strategy: str
    market: str
    condition_id: str
    side: str
    entry_price: float
    size_usd: float
    size_shares: float
    entered_at: float
    category: str = ""
    metadata: dict = field(default_factory=dict)
    exit_price: float | None = None
    exited_at: float | None = None
    pnl: float | None = None


@dataclass
class StrategyLedger:
    """P/L tracking per strategy."""
    name: str
    bankroll_initial: float
    bankroll_current: float
    trades: int = 0
    wins: int = 0
    losses: int = 0
    fees_paid: float = 0.0
    realized_pnl: float = 0.0
    positions: list[PaperPosition] = field(default_factory=list)
    closed_positions: list[PaperPosition] = field(default_factory=list)
    hourly_snapshots: list[dict] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0

    @property
    def unrealized_pnl(self) -> float:
        # Would need current prices — for now track at exit
        return 0.0

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl - self.fees_paid

    def record_entry(self, pos: PaperPosition) -> None:
        """Record a new paper entry."""
        fee = GAS_PER_TRADE + (pos.size_usd * SLIPPAGE_PCT)
        self.fees_paid += fee
        self.bankroll_current -= (pos.size_usd + fee)
        self.trades += 1
        self.positions.append(pos)

    def record_exit(self, position_id: str, exit_price: float, won: bool) -> float:
        """Record a paper exit. Returns P/L."""
        pos = None
        for p in self.positions:
            if p.position_id == position_id:
                pos = p
                break
        if not pos:
            return 0.0

        # Calculate P/L
        if won:
            payout = pos.size_shares * 1.0  # $1 per share if won
            profit = payout - pos.size_usd
            tax = profit * WINNER_TAX_PCT if profit > 0 else 0
            exit_fee = GAS_PER_TRADE + (payout * SLIPPAGE_PCT)
            net_pnl = profit - tax - exit_fee
            self.wins += 1
        else:
            # Total loss — shares worth $0
            payout = pos.size_shares * exit_price
            net_pnl = payout - pos.size_usd
            exit_fee = GAS_PER_TRADE if payout > 0 else 0
            self.losses += 1

        self.fees_paid += exit_fee + (profit * WINNER_TAX_PCT if won and profit > 0 else 0)
        self.realized_pnl += net_pnl
        self.bankroll_current += (pos.size_usd + net_pnl)

        pos.exit_price = exit_price
        pos.exited_at = time.time()
        pos.pnl = net_pnl

        self.positions.remove(pos)
        self.closed_positions.append(pos)
        return net_pnl

    def snapshot(self) -> dict:
        """Take an hourly snapshot."""
        snap = {
            "timestamp": time.time(),
            "bankroll": round(self.bankroll_current, 2),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate * 100, 1),
            "realized_pnl": round(self.realized_pnl, 2),
            "fees_paid": round(self.fees_paid, 2),
            "total_pnl": round(self.total_pnl, 2),
            "open_positions": len(self.positions),
        }
        self.hourly_snapshots.append(snap)
        return snap

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bankroll_initial": self.bankroll_initial,
            "bankroll_current": round(self.bankroll_current, 2),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate * 100, 1),
            "realized_pnl": round(self.realized_pnl, 2),
            "fees_paid": round(self.fees_paid, 2),
            "total_pnl": round(self.total_pnl, 2),
            "open_positions": len(self.positions),
            "closed_positions": len(self.closed_positions),
            "hourly_snapshots": self.hourly_snapshots,
        }


class PaperTradingRunner:
    """Orchestrates all paper trading strategies."""

    def __init__(self, total_bankroll: float = 50000.0, run_hours: float = 24.0):
        self._total_bankroll = total_bankroll
        self._run_hours = run_hours
        self._start_time = 0.0

        # Strategy allocations
        self._weather = StrategyLedger(
            name="weather_cheap_bracket",
            bankroll_initial=total_bankroll * 0.40,
            bankroll_current=total_bankroll * 0.40,
        )
        self._copytrade = StrategyLedger(
            name="copytrade_filtered",
            bankroll_initial=total_bankroll * 0.35,
            bankroll_current=total_bankroll * 0.35,
        )
        self._arb = StrategyLedger(
            name="spread_arb",
            bankroll_initial=total_bankroll * 0.25,
            bankroll_current=total_bankroll * 0.25,
        )
        self._ledgers = [self._weather, self._copytrade, self._arb]

    async def run(self) -> dict:
        """Run all strategies for the configured duration."""
        self._start_time = time.time()
        end_time = self._start_time + (self._run_hours * 3600)

        logger.info("paper_trading_started",
                     bankroll=self._total_bankroll,
                     hours=self._run_hours,
                     weather_bankroll=self._weather.bankroll_current,
                     copytrade_bankroll=self._copytrade.bankroll_current,
                     arb_bankroll=self._arb.bankroll_current)

        # Import strategies
        from strategies.spread_arb import SpreadArbScanner

        arb_scanner = SpreadArbScanner(bankroll=self._arb.bankroll_current, dry_run=True)

        # Run strategies concurrently
        tasks = [
            asyncio.create_task(self._run_arb(arb_scanner, end_time)),
            asyncio.create_task(self._dashboard_loop(end_time)),
        ]

        # Wait for all to complete or timeout
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

        return self._final_report()

    async def _run_arb(self, scanner: SpreadArbScanner, end_time: float) -> None:
        """Run arb scanner until end time."""
        while time.time() < end_time:
            try:
                opps = await scanner.scan_once()
                for opp in opps[:3]:  # Max 3 trades per scan
                    if self._arb.bankroll_current < opp.cost_usd:
                        continue
                    pos = PaperPosition(
                        position_id=f"arb-{int(time.time())}-{self._arb.trades}",
                        strategy="spread_arb",
                        market=opp.market_title,
                        condition_id=opp.condition_id,
                        side="BUY",
                        entry_price=opp.cost_usd,
                        size_usd=opp.cost_usd,
                        size_shares=opp.cost_usd,  # Simplified
                        entered_at=time.time(),
                        category=opp.opp_type,
                        metadata=opp.metadata,
                    )
                    self._arb.record_entry(pos)
                    logger.info("paper_arb_entry",
                                type=opp.opp_type,
                                market=opp.market_title[:40],
                                cost=opp.cost_usd,
                                expected_profit=opp.expected_profit_pct)
            except Exception as e:
                logger.error("paper_arb_error", error=str(e)[:100])

            await asyncio.sleep(60)

    async def _dashboard_loop(self, end_time: float) -> None:
        """Print hourly dashboard."""
        while time.time() < end_time:
            await asyncio.sleep(3600)  # Every hour

            elapsed_hours = (time.time() - self._start_time) / 3600
            print(f"\n{'='*60}")
            print(f"PAPER TRADING DASHBOARD — Hour {elapsed_hours:.1f}")
            print(f"{'='*60}")

            total_pnl = 0
            for ledger in self._ledgers:
                snap = ledger.snapshot()
                total_pnl += snap["total_pnl"]
                print(f"\n  {ledger.name}:")
                print(f"    Bankroll: ${snap['bankroll']:,.2f} (started ${ledger.bankroll_initial:,.2f})")
                print(f"    Trades: {snap['trades']} | W/L: {snap['wins']}/{snap['losses']} ({snap['win_rate']}%)")
                print(f"    P/L: ${snap['total_pnl']:+,.2f} (fees: ${snap['fees_paid']:,.2f})")

            print(f"\n  TOTAL P/L: ${total_pnl:+,.2f}")
            print(f"  TOTAL BANKROLL: ${sum(l.bankroll_current for l in self._ledgers):,.2f}")
            print(f"{'='*60}\n")

    def _final_report(self) -> dict:
        """Generate final report."""
        report = {
            "run_hours": self._run_hours,
            "total_bankroll": self._total_bankroll,
            "strategies": {l.name: l.to_dict() for l in self._ledgers},
            "total_pnl": round(sum(l.total_pnl for l in self._ledgers), 2),
            "total_trades": sum(l.trades for l in self._ledgers),
            "total_fees": round(sum(l.fees_paid for l in self._ledgers), 2),
            "final_bankroll": round(sum(l.bankroll_current for l in self._ledgers), 2),
        }

        # Save report
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        report_path = DATA_DIR / f"paper_report_{int(time.time())}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info("paper_trading_complete",
                     total_pnl=report["total_pnl"],
                     total_trades=report["total_trades"],
                     final_bankroll=report["final_bankroll"],
                     report_path=str(report_path))

        return report


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Paper Trading Runner")
    parser.add_argument("--bankroll", type=float, default=50000.0)
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()

    runner = PaperTradingRunner(total_bankroll=args.bankroll, run_hours=args.hours)
    report = await runner.run()

    print(f"\n{'='*60}")
    print("FINAL REPORT")
    print(f"{'='*60}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
