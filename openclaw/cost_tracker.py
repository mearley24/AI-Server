"""LLM, trading, and ops costs — JSONL events + optional SQLite rollup (next-level-gaps)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openclaw.cost_tracker")


def append_event(data_dir: Path, event: dict[str, Any]) -> None:
    line = json.dumps({"ts": datetime.utcnow().isoformat() + "Z", **event}, default=str)
    path = data_dir / "cost_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.info("cost_track event=%s", event.get("type"))
    try:
        CostTracker(data_dir).record_cost(
            event.get("category", "operational"),
            event.get("description", event.get("type", "")),
            float(event.get("amount", 0) or 0),
        )
    except Exception as e:
        logger.debug("cost_sqlite_skip: %s", e)


def weekly_summary_text(token_summary: Optional[dict[str, Any]], trading_note: str = "") -> str:
    lines = [
        "Weekly Business P&L (estimated):",
        f"  LLM tokens: {token_summary or 'n/a'}",
        f"  Trading note: {trading_note or 'see polymarket-bot /pnl'}",
        "  (Project revenue from D-Tools when wired.)",
    ]
    return "\n".join(lines)


def log_weekly_summary(data_dir: Path, body: str) -> None:
    p = data_dir / "weekly_cost_summary.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.utcnow().isoformat()}Z ---\n{body}\n")
    logger.info("cost_track weekly_summary logged")


class CostTracker:
    """SQLite costs at data/cost_tracker.db."""

    def __init__(self, data_dir: Path):
        self._path = data_dir / "cost_tracker.db"
        self._local = threading.local()
        self._init()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(self._path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self._path))
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USD'
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_costs_ts ON costs(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_costs_cat ON costs(category)")
        c.commit()
        c.close()

    def record_cost(self, category: str, description: str, amount: float, currency: str = "USD") -> None:
        ts = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            "INSERT INTO costs (timestamp, category, description, amount, currency) VALUES (?, ?, ?, ?, ?)",
            (ts, category, description[:500], amount, currency),
        )
        self._conn.commit()

    def get_weekly_summary(self) -> dict[str, Any]:
        since = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        rows = self._conn.execute(
            "SELECT category, SUM(amount) as s FROM costs WHERE timestamp >= ? GROUP BY category",
            (since,),
        ).fetchall()
        return {str(r[0]): float(r[1] or 0) for r in rows}

    def get_daily_pnl(self, days: int = 7) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(days):
            day = datetime.utcnow().date() - timedelta(days=i)
            start = f"{day.isoformat()}T00:00:00Z"
            end = f"{day.isoformat()}T23:59:59Z"
            row = self._conn.execute(
                "SELECT SUM(amount) FROM costs WHERE timestamp >= ? AND timestamp <= ?",
                (start, end),
            ).fetchone()
            out.append({"date": day.isoformat(), "net": float(row[0] or 0)})
        return list(reversed(out))
