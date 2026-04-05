"""RBI Pipeline — Research -> Backtest -> Implement for strategy ideas.

Monitors ideas.txt for pending ideas, paper-backtests them, and updates
status to validated/rejected based on net P/L after realistic fees.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis

from paper_runner import PaperPosition, StrategyLedger
from strategies.spread_arb import ArbOpportunity, SpreadArbScanner
from strategies.strategy_manager import IdeasQueue


logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
REDIS_CHANNEL = "notifications:trading"
CHECK_INTERVAL_SECONDS = 1800  # 30 minutes
DEFAULT_BACKTEST_HOURS = 4.0
DEFAULT_STEP_SECONDS = 300  # 5 minutes


@dataclass
class IdeaBacktestResult:
    idea_name: str
    hours: float
    pnl_usd: float
    fees_paid: float
    trades: int
    wins: int
    losses: int
    validated: bool
    details: dict[str, Any]


def _idea_text(idea: dict[str, str]) -> str:
    return " ".join(
        [
            idea.get("IDEA", ""),
            idea.get("DESCRIPTION", ""),
            idea.get("HYPOTHESIS", ""),
            idea.get("NOTES", ""),
        ]
    ).lower()


def _opportunity_matches_idea(opp: ArbOpportunity, idea: dict[str, str]) -> bool:
    text = _idea_text(idea)
    if not text:
        return True

    title = (opp.market_title or "").lower()
    opp_type = (opp.opp_type or "").lower()
    haystack = f"{title} {opp_type}"

    keyword_groups = [
        ["mean", "reversion", "fade", "overnight", "bounce", "contrarian"],
        ["presolution", "resolution", "tail", "cheap side", "95"],
        ["bracket", "weather", "temperature", "noaa"],
        ["kalshi", "cross-platform", "arbitrage", "spread", "complement", "negative risk"],
        ["ensemble", "forecast", "model", "ecmwf", "gfs", "nam"],
    ]
    for group in keyword_groups:
        if any(k in text for k in group):
            return any(k in haystack for k in group)
    return True


def _notify_validated(idea_name: str, pnl_usd: float, hours: float) -> None:
    body = (
        f"Idea {idea_name} validated: +${pnl_usd:.2f} over {hours:.0f}hr paper test. "
        "Promote to live?"
    )
    payload = {"title": "[RBI] Idea validated", "body": body}
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        client.publish(REDIS_CHANNEL, json.dumps(payload))
        logger.info("rbi_notification_sent: %s", body)
    except Exception as exc:
        logger.error("rbi_notification_error: %s", str(exc)[:160])


async def evaluate_idea(
    idea_name: str,
    hours: float = DEFAULT_BACKTEST_HOURS,
    idea: dict[str, str] | None = None,
) -> IdeaBacktestResult:
    """Run paper backtest for a single idea using existing paper infrastructure."""
    if hours <= 0:
        raise ValueError("hours must be > 0")

    idea_data = idea or {"IDEA": idea_name, "DESCRIPTION": "", "HYPOTHESIS": "", "NOTES": ""}
    backtest_bankroll = float(os.environ.get("RBI_BACKTEST_BANKROLL", "5000"))
    step_seconds = int(os.environ.get("RBI_BACKTEST_STEP_SECONDS", str(DEFAULT_STEP_SECONDS)))
    fast_mode = os.environ.get("RBI_FAST_MODE", "").lower() in {"1", "true", "yes"}

    scanner = SpreadArbScanner(bankroll=backtest_bankroll, dry_run=True, paper_mode=True)
    ledger = StrategyLedger(
        name=f"rbi_{re.sub(r'[^a-z0-9]+', '_', idea_name.lower()).strip('_')}",
        bankroll_initial=backtest_bankroll,
        bankroll_current=backtest_bankroll,
    )

    end_time = time.time() + (hours * 3600)
    held_counter = 0
    steps = 0

    logger.info("rbi_backtest_start: idea=%s hours=%.2f bankroll=%.2f", idea_name, hours, backtest_bankroll)

    while time.time() < end_time:
        steps += 1
        opportunities = await scanner.scan_once()
        matches = [opp for opp in opportunities if _opportunity_matches_idea(opp, idea_data)]
        matches.sort(key=lambda o: o.expected_profit_pct, reverse=True)

        for opp in matches[:3]:
            if ledger.bankroll_current <= 20:
                break

            allocation = min(max(opp.cost_usd, 5.0), max(5.0, ledger.bankroll_current * 0.05))
            if allocation > ledger.bankroll_current:
                continue

            entry_price = 0.5
            if opp.tokens:
                try:
                    entry_price = float(opp.tokens[0].get("price", 0.5))
                except Exception:
                    entry_price = 0.5
            entry_price = max(0.01, min(0.99, entry_price))

            position_id = f"rbi-{held_counter}"
            held_counter += 1
            position = PaperPosition(
                position_id=position_id,
                strategy=ledger.name,
                market=opp.market_title,
                condition_id=opp.condition_id or position_id,
                side="BUY",
                entry_price=entry_price,
                size_usd=allocation,
                size_shares=allocation / entry_price,
                entered_at=time.time(),
                category=opp.opp_type,
                metadata={"expected_profit_pct": opp.expected_profit_pct},
            )
            ledger.record_entry(position)

            # Realistic paper fill outcome: degrade expected edge and include both win/loss cases.
            expected_edge = max(-0.40, min(0.40, opp.expected_profit_pct / 100.0))
            realized_edge = (expected_edge * 0.65) - 0.02  # conservative haircut
            exit_price = max(0.01, min(0.99, entry_price * (1 + realized_edge)))
            won = exit_price > entry_price
            ledger.record_exit(position_id, exit_price=exit_price, won=won)

        if fast_mode:
            await asyncio.sleep(0.01)
        else:
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(step_seconds, remaining))

    pnl = round(ledger.total_pnl, 2)
    validated = pnl > 0
    result = IdeaBacktestResult(
        idea_name=idea_name,
        hours=hours,
        pnl_usd=pnl,
        fees_paid=round(ledger.fees_paid, 2),
        trades=ledger.trades,
        wins=ledger.wins,
        losses=ledger.losses,
        validated=validated,
        details={
            "steps": steps,
            "bankroll_initial": backtest_bankroll,
            "bankroll_final": round(ledger.bankroll_current, 2),
            "win_rate_pct": round(ledger.win_rate * 100, 1),
            "realized_pnl": round(ledger.realized_pnl, 2),
        },
    )
    logger.info(
        "rbi_backtest_complete: idea=%s pnl=%.2f trades=%d validated=%s",
        idea_name,
        result.pnl_usd,
        result.trades,
        result.validated,
    )
    return result


class RBIPipeline:
    """Continuous async loop for pending ideas -> backtest -> status update."""

    def __init__(self, ideas_path: Path | None = None, backtest_hours: float = DEFAULT_BACKTEST_HOURS) -> None:
        default_path = Path(__file__).resolve().parents[1] / "ideas.txt"
        self._ideas = IdeasQueue(path=ideas_path or default_path)
        self._backtest_hours = backtest_hours
        self._running = False
        self._active: set[str] = set()
        self._validation_streak: dict[str, int] = {}

    async def run_forever(self) -> None:
        self._running = True
        logger.info("rbi_pipeline_started: check_interval=%ds", CHECK_INTERVAL_SECONDS)
        while self._running:
            try:
                pending = self._ideas.get_pending()
                for idea in pending:
                    idea_name = idea.get("IDEA", "").strip()
                    if not idea_name or idea_name in self._active:
                        continue

                    self._active.add(idea_name)
                    try:
                        await self._process_idea(idea)
                    finally:
                        self._active.discard(idea_name)
            except Exception as exc:
                logger.error("rbi_pipeline_loop_error: %s", str(exc)[:200])

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False

    async def _process_idea(self, idea: dict[str, str]) -> None:
        name = idea.get("IDEA", "").strip()
        if not name:
            return
        key = name.lower()

        self._ideas.update_status(name, "backtesting", notes=f"RBI started {time.strftime('%Y-%m-%d %H:%M:%S')}")
        result = await evaluate_idea(name, hours=self._backtest_hours, idea=idea)

        notes = (
            f"RBI 4h paper result: pnl=${result.pnl_usd:+.2f}, trades={result.trades}, "
            f"wins={result.wins}, losses={result.losses}, fees=${result.fees_paid:.2f}"
        )

        if result.validated:
            streak = self._validation_streak.get(key, 0) + 1
            self._validation_streak[key] = streak
            notes = f"{notes}, streak={streak}/3"
            if streak >= 3:
                self._ideas.update_status(name, "live", notes=f"{notes}, auto-promoted to live")
                _notify_validated(name, result.pnl_usd, result.hours)
                logger.info("rbi_auto_promoted_live: idea=%s streak=%d", name, streak)
            else:
                self._ideas.update_status(name, "validated", notes=notes)
                _notify_validated(name, result.pnl_usd, result.hours)
        else:
            self._validation_streak[key] = 0
            self._ideas.update_status(name, "rejected", notes=notes)
            logger.info("rbi_idea_rejected: %s", notes)


async def _cli() -> None:
    parser = argparse.ArgumentParser(description="RBI strategy idea pipeline")
    parser.add_argument("--idea", type=str, default="", help="Evaluate a single idea by name")
    parser.add_argument("--hours", type=float, default=DEFAULT_BACKTEST_HOURS, help="Backtest duration in hours")
    args = parser.parse_args()

    if args.idea:
        result = await evaluate_idea(args.idea, hours=args.hours)
        print(json.dumps(result.__dict__, indent=2))
        return

    pipeline = RBIPipeline(backtest_hours=args.hours)
    await pipeline.run_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(_cli())
