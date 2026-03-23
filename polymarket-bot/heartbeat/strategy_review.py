"""Review strategy performance using paper_ledger or live trade data."""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)


class StrategyReviewer:
    """Reviews all active strategies' performance over the last 24 hours."""

    async def review_all(self) -> list[dict]:
        """Review all active strategies' performance over last 24h.

        Reads from PaperLedger to get trades and signals, calculates metrics,
        and classifies each strategy's status.
        """
        try:
            from src.paper_ledger import PaperLedger
        except ImportError:
            logger.error("paper_ledger_import_failed")
            return self._empty_reviews()

        ledger = PaperLedger()
        strategies = self._get_active_strategies()
        reviews = []
        cutoff = time.time() - (24 * 3600)

        # Read all trades once
        all_trades = ledger.read_all()

        for strategy_name, platform in strategies:
            # Filter trades for this strategy within the last 24h
            trades = [
                t for t in all_trades
                if t.strategy == strategy_name and t.timestamp >= cutoff
            ]

            # Count all trades for this strategy as "signals" (the paper ledger
            # records trades that were signaled — there's no separate signal log)
            signals = trades

            total_trades = len(trades)
            winning = 0
            total_pnl = 0.0
            total_size = 0.0
            total_duration = 0.0

            for t in trades:
                # Calculate P&L for scored trades
                if t.would_have_profited is not None and t.resolved_price is not None:
                    if t.side == "BUY":
                        pnl = (t.resolved_price - t.price) * t.size
                    else:
                        pnl = (t.price - t.resolved_price) * t.size
                    total_pnl += pnl
                    if pnl > 0:
                        winning += 1

                total_size += t.size
                # Duration isn't tracked in PaperTrade dataclass; use scored_at - timestamp
                if t.scored_at and t.timestamp:
                    total_duration += (t.scored_at - t.timestamp) / 60.0

            win_rate = f"{winning / total_trades * 100:.0f}%" if total_trades > 0 else "N/A"

            # Determine status
            status = "active"
            if total_trades == 0 and len(signals) == 0:
                status = "idle"
            elif total_pnl < -50:
                status = "underperforming"
            elif win_rate != "N/A" and total_trades > 0 and winning / total_trades > 0.6:
                status = "strong"

            reviews.append({
                "name": strategy_name,
                "platform": platform,
                "signals": len(signals),
                "trades": total_trades,
                "win_rate": win_rate,
                "pnl": total_pnl,
                "status": status,
                "avg_trade_size": total_size / total_trades if total_trades > 0 else 0,
                "avg_hold_time_min": total_duration / total_trades if total_trades > 0 else 0,
            })

        return reviews

    def _get_active_strategies(self) -> list[tuple[str, str]]:
        """Return list of (strategy_name, platform) tuples for all 12 strategies."""
        return [
            ("latency_detector", "polymarket"),
            ("stink_bid", "polymarket"),
            ("flash_crash", "polymarket"),
            ("weather_trader", "polymarket"),
            ("sports_arb", "polymarket"),
            ("order_flow_analyzer", "polymarket"),
            ("kalshi_scanner", "kalshi"),
            ("kalshi_weather", "kalshi"),
            ("kalshi_fed", "kalshi"),
            ("btc_correlation", "crypto"),
            ("mean_reversion", "crypto"),
            ("momentum", "crypto"),
        ]

    def _empty_reviews(self) -> list[dict]:
        """Return empty reviews for all strategies when ledger is unavailable."""
        return [
            {
                "name": name,
                "platform": platform,
                "signals": 0,
                "trades": 0,
                "win_rate": "N/A",
                "pnl": 0.0,
                "status": "idle",
                "avg_trade_size": 0,
                "avg_hold_time_min": 0,
            }
            for name, platform in self._get_active_strategies()
        ]
