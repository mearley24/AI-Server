"""Per-strategy aggregates — Auto-20."""

from __future__ import annotations

import logging
import statistics
import time
from typing import Any

logger = logging.getLogger(__name__)


def summarize_trades(rows: list[dict[str, Any]], window_sec: float) -> dict[str, Any]:
    """Rolling window stats from trade rows with 'pnl' and 'ts_exit'."""
    now = time.time()
    cut = now - window_sec
    pnls = [float(r["pnl"]) for r in rows if r.get("pnl") is not None and (r.get("ts_exit") or 0) >= cut]
    if not pnls:
        return {"count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "sharpe": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    avg = statistics.mean(pnls)
    stdev = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
    sharpe = (avg / stdev) if stdev > 0 else 0.0
    return {
        "count": len(pnls),
        "win_rate": wins / len(pnls),
        "avg_pnl": avg,
        "sharpe": sharpe,
    }
