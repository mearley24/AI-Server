"""Enhanced Wallet Scoring — zombie detection, P/L ratio, red flag filters.

Replaces the simple win-rate scoring with a composite score that accounts for:
- Zombie orders (open losing positions that inflate reported win rates)
- Profit/Loss ratio (average win amount vs average loss amount)
- Red flag detection (stat padders, HFT bots, single-market concentration)
- Composite score weighting
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class WalletAnalysis:
    """Detailed wallet analysis result."""

    address: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    open_positions: int = 0
    open_losing_positions: int = 0

    # P/L metrics
    total_profit: float = 0.0
    total_loss: float = 0.0
    avg_profit_per_win: float = 0.0
    avg_loss_per_loss: float = 0.0
    pl_ratio: float = 0.0

    # Red flags
    extreme_price_trade_pct: float = 0.0  # % of trades at >0.95 or <0.05
    avg_trade_interval_seconds: float = 0.0
    market_concentration: float = 0.0  # % of profit from single market
    total_closed: int = 0

    # Scoring components
    adjusted_win_rate: float = 0.0
    pl_ratio_normalized: float = 0.0
    recency_score: float = 0.0
    consistency_score: float = 0.0
    composite_score: float = 0.0

    # Red flag reasons
    red_flags: list[str] = field(default_factory=list)
    is_filtered: bool = False

    last_active: float = 0.0
    total_volume: float = 0.0


class WalletScorer:
    """Scores wallets using composite metrics and red flag detection."""

    def __init__(
        self,
        min_closed_positions: int = 50,
        extreme_price_threshold: float = 0.90,  # >90% trades at extremes
        min_trade_interval_seconds: float = 10.0,
        max_market_concentration: float = 0.80,  # >80% profit from single market
        # Composite weights
        win_rate_weight: float = 0.3,
        pl_ratio_weight: float = 0.4,
        recency_weight: float = 0.2,
        consistency_weight: float = 0.1,
    ) -> None:
        self._min_closed = min_closed_positions
        self._extreme_threshold = extreme_price_threshold
        self._min_interval = min_trade_interval_seconds
        self._max_concentration = max_market_concentration
        self._w_wr = win_rate_weight
        self._w_pl = pl_ratio_weight
        self._w_rec = recency_weight
        self._w_con = consistency_weight

    def analyze_wallet(
        self,
        address: str,
        trades: list[dict[str, Any]],
        open_positions: list[dict[str, Any]] | None = None,
    ) -> WalletAnalysis:
        """Perform full wallet analysis with red flag detection.

        Args:
            address: Wallet address
            trades: List of trade dicts with keys: side, price, size, pnl, market, timestamp
            open_positions: Optional list of open positions for zombie detection
        """
        analysis = WalletAnalysis(address=address)
        open_positions = open_positions or []

        if not trades:
            analysis.is_filtered = True
            analysis.red_flags.append("no_trades")
            return analysis

        analysis.total_trades = len(trades)

        # Categorize wins/losses
        wins_pnl = []
        losses_pnl = []
        market_profits: dict[str, float] = {}
        trade_timestamps = []
        extreme_price_count = 0

        for t in trades:
            price = float(t.get("price", 0.5))
            pnl = float(t.get("pnl", 0))
            market = t.get("market", t.get("conditionId", "unknown"))
            ts = t.get("timestamp", 0)
            if isinstance(ts, str):
                try:
                    ts = float(ts)
                except (ValueError, TypeError):
                    ts = 0

            # Track timestamps for interval calculation
            if isinstance(ts, (int, float)) and ts > 0:
                trade_timestamps.append(ts)
                if ts > analysis.last_active:
                    analysis.last_active = ts

            # Track extreme price trades
            if price > 0.95 or price < 0.05:
                extreme_price_count += 1

            # Track volume
            size = float(t.get("size", 0))
            analysis.total_volume += price * size

            # Categorize by outcome
            side = t.get("side", "").upper()
            if side == "BUY":
                # For resolved markets, we need to check if this was a winning trade
                # We use pnl if available, otherwise infer from result field
                result = t.get("result", "")
                if pnl > 0 or result == "win":
                    analysis.wins += 1
                    wins_pnl.append(abs(pnl) if pnl else price * size)
                elif pnl < 0 or result == "loss":
                    analysis.losses += 1
                    losses_pnl.append(abs(pnl) if pnl else price * size)

                # Track market profits
                if market not in market_profits:
                    market_profits[market] = 0
                market_profits[market] += pnl

        analysis.total_closed = analysis.wins + analysis.losses

        # Zombie order detection: count open losing positions
        for pos in open_positions:
            cur_price = float(pos.get("curPrice", 0))
            avg_price = float(pos.get("avgPrice", 0))
            if avg_price > 0 and cur_price < avg_price:
                analysis.open_losing_positions += 1
            analysis.open_positions += 1

        # Adjusted win rate = wins / (wins + losses + open_losing_positions)
        denominator = analysis.wins + analysis.losses + analysis.open_losing_positions
        analysis.adjusted_win_rate = analysis.wins / denominator if denominator > 0 else 0.0

        # P/L ratio
        if wins_pnl:
            analysis.total_profit = sum(wins_pnl)
            analysis.avg_profit_per_win = analysis.total_profit / len(wins_pnl)
        if losses_pnl:
            analysis.total_loss = sum(losses_pnl)
            analysis.avg_loss_per_loss = analysis.total_loss / len(losses_pnl)

        if analysis.avg_loss_per_loss > 0:
            analysis.pl_ratio = analysis.avg_profit_per_win / analysis.avg_loss_per_loss
        elif analysis.avg_profit_per_win > 0:
            analysis.pl_ratio = 10.0  # no losses → cap at 10

        # Normalize P/L ratio to 0-1 (cap at ratio of 5)
        analysis.pl_ratio_normalized = min(analysis.pl_ratio / 5.0, 1.0)

        # Extreme price percentage
        analysis.extreme_price_trade_pct = (
            extreme_price_count / analysis.total_trades
            if analysis.total_trades > 0
            else 0
        )

        # Average trade interval
        if len(trade_timestamps) >= 2:
            trade_timestamps.sort()
            intervals = [
                trade_timestamps[i + 1] - trade_timestamps[i]
                for i in range(len(trade_timestamps) - 1)
                if trade_timestamps[i + 1] - trade_timestamps[i] > 0
            ]
            analysis.avg_trade_interval_seconds = (
                sum(intervals) / len(intervals) if intervals else 999
            )

        # Market concentration
        if market_profits:
            total_abs_profit = sum(abs(v) for v in market_profits.values())
            if total_abs_profit > 0:
                max_market_profit = max(abs(v) for v in market_profits.values())
                analysis.market_concentration = max_market_profit / total_abs_profit

        # Recency score (0-1): higher if active recently
        if analysis.last_active > 0:
            days_since = (time.time() - analysis.last_active) / 86400
            if days_since < 3:
                analysis.recency_score = 1.0
            elif days_since < 7:
                analysis.recency_score = 0.8
            elif days_since < 14:
                analysis.recency_score = 0.6
            elif days_since < 30:
                analysis.recency_score = 0.3
            else:
                analysis.recency_score = 0.1

        # Consistency score: based on how steady the win rate is
        # (higher total closed = more consistent signal)
        if analysis.total_closed >= 100:
            analysis.consistency_score = 1.0
        elif analysis.total_closed >= 50:
            analysis.consistency_score = 0.7
        elif analysis.total_closed >= 20:
            analysis.consistency_score = 0.4
        else:
            analysis.consistency_score = 0.1

        # Red flag checks
        if analysis.total_closed < self._min_closed:
            analysis.red_flags.append(f"insufficient_trades_{analysis.total_closed}")
            analysis.is_filtered = True

        if analysis.extreme_price_trade_pct > self._extreme_threshold:
            analysis.red_flags.append(f"stat_padding_{analysis.extreme_price_trade_pct:.0%}")
            analysis.is_filtered = True

        if analysis.avg_trade_interval_seconds > 0 and analysis.avg_trade_interval_seconds < self._min_interval:
            analysis.red_flags.append(f"hft_bot_{analysis.avg_trade_interval_seconds:.1f}s")
            analysis.is_filtered = True

        if analysis.market_concentration > self._max_concentration and analysis.total_closed > 0:
            analysis.red_flags.append(f"concentrated_{analysis.market_concentration:.0%}")
            analysis.is_filtered = True

        # Composite score
        if not analysis.is_filtered:
            analysis.composite_score = (
                analysis.adjusted_win_rate * self._w_wr
                + analysis.pl_ratio_normalized * self._w_pl
                + analysis.recency_score * self._w_rec
                + analysis.consistency_score * self._w_con
            )

        return analysis

    def score_from_basic_stats(
        self,
        address: str,
        wins: int,
        losses: int,
        volume: float = 0.0,
        last_active: float = 0.0,
        open_losing: int = 0,
        avg_win_pnl: float = 0.0,
        avg_loss_pnl: float = 0.0,
    ) -> WalletAnalysis:
        """Quick scoring from pre-aggregated stats (used during wallet scan)."""
        analysis = WalletAnalysis(address=address)
        analysis.wins = wins
        analysis.losses = losses
        analysis.total_closed = wins + losses
        analysis.open_losing_positions = open_losing
        analysis.total_volume = volume
        analysis.last_active = last_active

        # Adjusted win rate
        denominator = wins + losses + open_losing
        analysis.adjusted_win_rate = wins / denominator if denominator > 0 else 0.0

        # P/L ratio
        if avg_win_pnl > 0 and avg_loss_pnl > 0:
            analysis.pl_ratio = avg_win_pnl / avg_loss_pnl
            analysis.pl_ratio_normalized = min(analysis.pl_ratio / 5.0, 1.0)
        elif avg_win_pnl > 0:
            analysis.pl_ratio = 5.0
            analysis.pl_ratio_normalized = 1.0

        # Recency
        if last_active > 0:
            days = (time.time() - last_active) / 86400
            analysis.recency_score = max(0.1, 1.0 - (days / 30.0))

        # Consistency
        if analysis.total_closed >= 100:
            analysis.consistency_score = 1.0
        elif analysis.total_closed >= 50:
            analysis.consistency_score = 0.7
        elif analysis.total_closed >= 20:
            analysis.consistency_score = 0.4
        else:
            analysis.consistency_score = 0.1
            analysis.red_flags.append("insufficient_trades")
            analysis.is_filtered = True

        # Composite
        if not analysis.is_filtered:
            analysis.composite_score = (
                analysis.adjusted_win_rate * self._w_wr
                + analysis.pl_ratio_normalized * self._w_pl
                + analysis.recency_score * self._w_rec
                + analysis.consistency_score * self._w_con
            )

        return analysis
