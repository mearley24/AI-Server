"""Signal Tracker — records which X intel signals influenced trades and their outcomes.

Enables learning: which X accounts, signal types, and keywords lead to profitable trades?
Data stored in SQLite for analysis and auto-tuning.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

DB_PATH = Path(os.environ.get("SIGNAL_TRACKER_DB", "/data/signal_tracker.db"))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_author TEXT NOT NULL,
            signal_keyword TEXT,
            signal_direction TEXT,
            signal_confidence REAL,
            signal_relevance INTEGER,
            signal_timestamp REAL,
            trade_market TEXT,
            trade_side TEXT,
            trade_price REAL,
            trade_size_usd REAL,
            trade_timestamp REAL,
            outcome TEXT DEFAULT 'open',
            pnl REAL DEFAULT 0,
            resolved_at REAL,
            created_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS author_performance (
            author TEXT PRIMARY KEY,
            total_signals INTEGER DEFAULT 0,
            trades_influenced INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            avg_relevance REAL DEFAULT 0,
            last_signal_at REAL,
            updated_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.commit()
    return conn


def record_signal_trade(
    signal: dict[str, Any],
    trade: dict[str, Any],
) -> None:
    """Record that an X signal influenced a trade decision."""
    try:
        conn = _get_conn()
        conn.execute("""
            INSERT INTO signal_trades
                (signal_author, signal_keyword, signal_direction, signal_confidence,
                 signal_relevance, signal_timestamp, trade_market, trade_side,
                 trade_price, trade_size_usd, trade_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.get("author", ""),
            signal.get("keyword", ""),
            signal.get("direction", ""),
            signal.get("confidence", 0),
            signal.get("relevance", 0),
            signal.get("timestamp", 0),
            trade.get("market", ""),
            trade.get("side", ""),
            trade.get("price", 0),
            trade.get("size_usd", 0),
            time.time(),
        ))
        conn.commit()
        conn.close()
        logger.info("signal_trade_recorded", author=signal.get("author"), market=trade.get("market", "")[:50])
    except Exception as exc:
        logger.warning("signal_trade_record_failed", error=str(exc)[:100])


def update_trade_outcome(trade_market: str, outcome: str, pnl: float) -> None:
    """Update the outcome of a signal-influenced trade after resolution."""
    try:
        conn = _get_conn()
        conn.execute("""
            UPDATE signal_trades
            SET outcome = ?, pnl = ?, resolved_at = ?
            WHERE trade_market = ? AND outcome = 'open'
        """, (outcome, pnl, time.time(), trade_market))

        # Update author performance
        conn.execute("""
            INSERT INTO author_performance (author, total_signals, trades_influenced, wins, losses, total_pnl, last_signal_at)
            SELECT
                signal_author,
                COUNT(*),
                COUNT(*),
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END),
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END),
                SUM(pnl),
                MAX(signal_timestamp)
            FROM signal_trades
            WHERE signal_author IN (SELECT signal_author FROM signal_trades WHERE trade_market = ?)
            GROUP BY signal_author
            ON CONFLICT(author) DO UPDATE SET
                trades_influenced = excluded.trades_influenced,
                wins = excluded.wins,
                losses = excluded.losses,
                total_pnl = excluded.total_pnl,
                last_signal_at = excluded.last_signal_at,
                updated_at = unixepoch()
        """, (trade_market,))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("signal_outcome_update_failed", error=str(exc)[:100])


def get_author_leaderboard(limit: int = 20) -> list[dict]:
    """Get top-performing X signal authors by P&L."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT author, trades_influenced, wins, losses, total_pnl,
                   CASE WHEN trades_influenced > 0
                        THEN ROUND(100.0 * wins / trades_influenced, 1)
                        ELSE 0 END as win_rate
            FROM author_performance
            WHERE trades_influenced >= 3
            ORDER BY total_pnl DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_signal_summary() -> dict[str, Any]:
    """Dashboard-friendly signal performance summary."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM signal_trades").fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'open'").fetchone()[0]
        wins = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'win'").fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'loss'").fetchone()[0]
        total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) FROM signal_trades WHERE outcome != 'open'").fetchone()[0]
        conn.close()
        return {
            "total_signal_trades": total,
            "open": open_count,
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(100 * wins / max(wins + losses, 1), 1),
        }
    except Exception:
        return {}
