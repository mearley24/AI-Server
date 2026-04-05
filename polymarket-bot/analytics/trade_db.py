"""SQLite trade ledger — Auto-20."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class TradeRow:
    ts_entry: float
    ts_exit: float | None
    strategy: str
    market: str
    condition_id: str
    entry_price: float
    exit_price: float | None
    shares: float
    fees: float
    pnl: float | None
    outcome: str | None


class TradeDB:
    def __init__(self, path: Path | None = None) -> None:
        base = Path(__file__).resolve().parents[1] / "data"
        self.path = path or (base / "trades_analytics.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_entry REAL,
                    ts_exit REAL,
                    strategy TEXT,
                    market TEXT,
                    condition_id TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    shares REAL,
                    fees REAL,
                    pnl REAL,
                    outcome TEXT
                )
                """
            )
            c.commit()

    def insert(self, row: TradeRow) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO trades (ts_entry, ts_exit, strategy, market, condition_id,
                    entry_price, exit_price, shares, fees, pnl, outcome)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.ts_entry,
                    row.ts_exit,
                    row.strategy,
                    row.market,
                    row.condition_id,
                    row.entry_price,
                    row.exit_price,
                    row.shares,
                    row.fees,
                    row.pnl,
                    row.outcome,
                ),
            )
            c.commit()

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as c:
            cur = c.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
