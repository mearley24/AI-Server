"""P&L tracker — calculates net profit/loss from trades and CSV exports."""

from __future__ import annotations

import csv
import io
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Trade:
    """A single executed trade."""

    trade_id: str
    timestamp: float
    market: str
    token_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    fee: float = 0.0
    strategy: str = ""
    pnl: float = 0.0  # Realized P&L for this trade


@dataclass
class PositionPnL:
    """P&L for a single position."""

    token_id: str
    market: str
    strategy: str
    entry_price: float
    current_price: float
    size: float
    side: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl


@dataclass
class PnLSummary:
    """Aggregate P&L summary."""

    total_realized: float = 0.0
    total_unrealized: float = 0.0
    total_fees: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    positions: list[PositionPnL] = field(default_factory=list)
    by_strategy: dict[str, float] = field(default_factory=dict)
    by_market: dict[str, float] = field(default_factory=dict)

    @property
    def total_pnl(self) -> float:
        return self.total_realized + self.total_unrealized - self.total_fees

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0


class PnLTracker:
    """Tracks trades and calculates P&L with filtering by keyword and time window."""

    def __init__(self, data_dir: str = "/data") -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._trades: list[Trade] = []
        self._open_positions: dict[str, dict[str, Any]] = {}  # token_id -> position info

    @property
    def trades(self) -> list[Trade]:
        return self._trades

    @property
    def open_positions(self) -> dict[str, dict[str, Any]]:
        return self._open_positions

    def record_trade(self, trade: Trade) -> None:
        """Record a new trade and update position tracking."""
        self._trades.append(trade)
        self._update_position(trade)
        self._persist_trade(trade)
        logger.info(
            "trade_recorded",
            trade_id=trade.trade_id,
            market=trade.market,
            side=trade.side,
            price=trade.price,
            size=trade.size,
            strategy=trade.strategy,
        )
        # Feed Cortex with every trade (fire-and-forget; Cortex down ≠ crash).
        try:
            from src.cortex_client import post_trade_memory

            post_trade_memory(
                side=trade.side,
                market=trade.market,
                strategy=trade.strategy or "unknown",
                amount=float(trade.price) * float(trade.size),
                price=float(trade.price),
            )
        except Exception as exc:
            logger.debug("cortex_record_trade_failed error=%s", exc)

    def _update_position(self, trade: Trade) -> None:
        """Update open position tracking after a trade."""
        tid = trade.token_id
        pos = self._open_positions.get(tid)

        if trade.side == "BUY":
            if pos is None:
                self._open_positions[tid] = {
                    "token_id": tid,
                    "market": trade.market,
                    "strategy": trade.strategy,
                    "entry_price": trade.price,
                    "size": trade.size,
                    "side": "LONG",
                    "realized_pnl": 0.0,
                }
            else:
                # Average in
                total_size = pos["size"] + trade.size
                pos["entry_price"] = (
                    (pos["entry_price"] * pos["size"]) + (trade.price * trade.size)
                ) / total_size
                pos["size"] = total_size
        elif trade.side == "SELL":
            if pos and pos["side"] == "LONG":
                # Realize P&L on the sold portion
                sell_size = min(trade.size, pos["size"])
                realized = (trade.price - pos["entry_price"]) * sell_size
                pos["realized_pnl"] += realized
                pos["size"] -= sell_size
                trade.pnl = realized

                if pos["size"] <= 0.001:  # Effectively closed
                    del self._open_positions[tid]

    def _persist_trade(self, trade: Trade) -> None:
        """Append a trade to the CSV file."""
        csv_path = self._data_dir / "trades.csv"
        write_header = not csv_path.exists()

        with csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "trade_id", "timestamp", "market", "token_id",
                    "side", "price", "size", "fee", "strategy", "pnl",
                ])
            writer.writerow([
                trade.trade_id,
                datetime.fromtimestamp(trade.timestamp, tz=timezone.utc).isoformat(),
                trade.market,
                trade.token_id,
                trade.side,
                f"{trade.price:.6f}",
                f"{trade.size:.6f}",
                f"{trade.fee:.6f}",
                trade.strategy,
                f"{trade.pnl:.6f}",
            ])

    def load_csv(self, csv_path: str | Path) -> int:
        """Load trades from a Polymarket CSV export. Returns number of trades loaded."""
        path = Path(csv_path)
        if not path.exists():
            logger.warning("csv_not_found", path=str(path))
            return 0

        count = 0
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade = self._parse_csv_row(row)
                if trade:
                    self._trades.append(trade)
                    count += 1

        logger.info("csv_loaded", path=str(path), trades=count)
        return count

    def _parse_csv_row(self, row: dict[str, str]) -> Trade | None:
        """Parse a CSV row into a Trade object. Handles multiple CSV formats."""
        try:
            # Try to extract timestamp
            ts_str = row.get("timestamp", row.get("time", row.get("date", "")))
            if ts_str:
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except ValueError:
                    ts = time.time()
            else:
                ts = time.time()

            return Trade(
                trade_id=row.get("trade_id", row.get("id", "")),
                timestamp=ts,
                market=row.get("market", row.get("question", "")),
                token_id=row.get("token_id", row.get("asset_id", "")),
                side=row.get("side", row.get("type", "")).upper(),
                price=float(row.get("price", row.get("avg_price", "0"))),
                size=float(row.get("size", row.get("amount", row.get("quantity", "0")))),
                fee=float(row.get("fee", row.get("fees", "0"))),
                strategy=row.get("strategy", ""),
                pnl=float(row.get("pnl", row.get("profit", "0"))),
            )
        except (ValueError, KeyError) as exc:
            logger.warning("csv_parse_error", error=str(exc), row=str(row)[:200])
            return None

    def get_pnl(
        self,
        keyword: str | None = None,
        hours: float | None = None,
        strategy: str | None = None,
    ) -> PnLSummary:
        """Calculate P&L filtered by keyword, time window, and/or strategy.

        Args:
            keyword: Filter trades where market name contains this string (case-insensitive).
            hours: Only include trades from the last N hours.
            strategy: Filter by strategy name.
        """
        now = time.time()
        cutoff = now - (hours * 3600) if hours else 0.0

        filtered: list[Trade] = []
        for t in self._trades:
            if hours and t.timestamp < cutoff:
                continue
            if keyword and keyword.lower() not in t.market.lower():
                continue
            if strategy and t.strategy != strategy:
                continue
            filtered.append(t)

        summary = PnLSummary(trade_count=len(filtered))
        by_strategy: dict[str, float] = defaultdict(float)
        by_market: dict[str, float] = defaultdict(float)

        for t in filtered:
            summary.total_realized += t.pnl
            summary.total_fees += t.fee
            if t.pnl > 0:
                summary.win_count += 1
            elif t.pnl < 0:
                summary.loss_count += 1
            by_strategy[t.strategy or "unknown"] += t.pnl
            by_market[t.market] += t.pnl

        summary.by_strategy = dict(by_strategy)
        summary.by_market = dict(by_market)

        # Add current open positions for unrealized P&L
        for tid, pos in self._open_positions.items():
            if keyword and keyword.lower() not in pos["market"].lower():
                continue
            if strategy and pos["strategy"] != strategy:
                continue

            pos_pnl = PositionPnL(
                token_id=tid,
                market=pos["market"],
                strategy=pos["strategy"],
                entry_price=pos["entry_price"],
                current_price=0.0,  # Updated by caller with live price
                size=pos["size"],
                side=pos["side"],
                realized_pnl=pos["realized_pnl"],
            )
            summary.positions.append(pos_pnl)
            summary.total_realized += pos["realized_pnl"]

        return summary
