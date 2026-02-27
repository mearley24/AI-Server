#!/usr/bin/env python3
"""
earnings_tracker.py
===================
Detailed earnings tracking and analytics for Bob's ClawWork side hustle.

All ClawWork transactions are stored in a SQLite database with full
analytics support: daily summaries, weekly reports, monthly reports,
ROI calculation, CSV export, and a JSON dashboard endpoint.

Database: ~/.symphony/data/earnings.db
"""

import csv
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytz

log = logging.getLogger("clawwork.earnings")
MST = pytz.timezone("America/Denver")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clawwork_tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT    NOT NULL UNIQUE,
    sector           TEXT    NOT NULL,
    occupation       TEXT    NOT NULL,
    estimated_value  REAL    NOT NULL,
    actual_payment   REAL    NOT NULL DEFAULT 0,
    quality_score    REAL    NOT NULL DEFAULT 0,
    token_cost       REAL    NOT NULL DEFAULT 0,
    net_profit       REAL    NOT NULL DEFAULT 0,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    deliverable_path TEXT,
    completed_at     TEXT    NOT NULL,
    date             TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_balances (
    date          TEXT PRIMARY KEY,
    opening_bal   REAL NOT NULL,
    closing_bal   REAL NOT NULL,
    tasks_run     INTEGER NOT NULL DEFAULT 0,
    gross_earned  REAL NOT NULL DEFAULT 0,
    total_cost    REAL NOT NULL DEFAULT 0,
    net_profit    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sector_performance (
    sector           TEXT    PRIMARY KEY,
    tasks_completed  INTEGER NOT NULL DEFAULT 0,
    total_earned     REAL    NOT NULL DEFAULT 0,
    total_cost       REAL    NOT NULL DEFAULT 0,
    avg_quality      REAL    NOT NULL DEFAULT 0,
    last_updated     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_date      ON clawwork_tasks(date);
CREATE INDEX IF NOT EXISTS idx_tasks_sector    ON clawwork_tasks(sector);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON clawwork_tasks(completed_at);
"""


class EarningsTracker:
    """
    Full earnings analytics for ClawWork.
    Provides daily/weekly/monthly summaries, CSV export, and Telegram reports.
    """

    def __init__(self, config: dict):
        self.db_path = Path(config["earnings_tracking"]["database_path"]).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path(config["earnings_tracking"]["export_csv_dir"]).expanduser()
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._db() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def log_task(self, task_id, sector, occupation, estimated_value,
                 actual_payment, quality_score, token_cost, net_profit,
                 duration_seconds, deliverable_path=None):
        now = datetime.now(MST)
        date_str = now.strftime("%Y-%m-%d")
        with self._db() as conn:
            try:
                conn.execute(
                    """INSERT INTO clawwork_tasks
                       (task_id, sector, occupation, estimated_value, actual_payment,
                        quality_score, token_cost, net_profit, duration_seconds,
                        deliverable_path, completed_at, date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, sector, occupation, estimated_value, actual_payment,
                     quality_score, token_cost, net_profit, duration_seconds,
                     deliverable_path, now.isoformat(), date_str),
                )
                conn.execute(
                    """INSERT INTO daily_balances (date, opening_bal, closing_bal, tasks_run, gross_earned, total_cost, net_profit)
                       VALUES (?, 0, ?, 1, ?, ?, ?)
                       ON CONFLICT(date) DO UPDATE SET
                           tasks_run=tasks_run+1, gross_earned=gross_earned+excluded.gross_earned,
                           total_cost=total_cost+excluded.total_cost, net_profit=net_profit+excluded.net_profit,
                           closing_bal=closing_bal+excluded.net_profit""",
                    (date_str, net_profit, actual_payment, token_cost, net_profit),
                )
                conn.execute(
                    """INSERT INTO sector_performance (sector, tasks_completed, total_earned, total_cost, avg_quality, last_updated)
                       VALUES (?, 1, ?, ?, ?, ?)
                       ON CONFLICT(sector) DO UPDATE SET
                           tasks_completed=tasks_completed+1, total_earned=total_earned+excluded.total_earned,
                           total_cost=total_cost+excluded.total_cost,
                           avg_quality=(avg_quality*tasks_completed+excluded.avg_quality)/(tasks_completed+1),
                           last_updated=excluded.last_updated""",
                    (sector, actual_payment, token_cost, quality_score, now.isoformat()),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                log.warning(f"Task {task_id} already logged")

    def get_daily_summary(self, date=None):
        if date is None:
            date = datetime.now(MST).strftime("%Y-%m-%d")
        with self._db() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS tasks, COALESCE(SUM(actual_payment),0) AS gross,
                   COALESCE(SUM(token_cost),0) AS cost, COALESCE(SUM(net_profit),0) AS net,
                   COALESCE(AVG(quality_score),0) AS avg_q
                   FROM clawwork_tasks WHERE date=?""", (date,)).fetchone()
            sector_rows = conn.execute(
                """SELECT sector, COUNT(*) AS tasks, ROUND(SUM(actual_payment),2) AS earnings
                   FROM clawwork_tasks WHERE date=? GROUP BY sector ORDER BY earnings DESC""",
                (date,)).fetchall()
        return {"date": date, "tasks": row["tasks"], "gross_earnings": round(row["gross"], 2),
                "total_cost": round(row["cost"], 4), "net_profit": round(row["net"], 2),
                "avg_quality": round(row["avg_q"], 3), "by_sector": [dict(r) for r in sector_rows]}

    def get_weekly_report(self, week_end=None):
        end_dt = datetime.now(MST) if week_end is None else datetime.strptime(week_end, "%Y-%m-%d").replace(tzinfo=MST)
        start_str = (end_dt - timedelta(days=6)).strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")
        with self._db() as conn:
            agg = conn.execute(
                """SELECT COUNT(*) AS total_tasks, COALESCE(SUM(actual_payment),0) AS gross,
                   COALESCE(SUM(token_cost),0) AS cost, COALESCE(SUM(net_profit),0) AS net,
                   COALESCE(AVG(quality_score),0) AS avg_q
                   FROM clawwork_tasks WHERE date BETWEEN ? AND ?""",
                (start_str, end_str)).fetchone()
            sector_rows = conn.execute(
                """SELECT sector, COUNT(*) AS tasks, ROUND(SUM(actual_payment),2) AS earnings,
                   ROUND(SUM(net_profit),2) AS net, ROUND(AVG(quality_score),3) AS avg_quality
                   FROM clawwork_tasks WHERE date BETWEEN ? AND ?
                   GROUP BY sector ORDER BY net DESC""",
                (start_str, end_str)).fetchall()
        roi = (agg["net"]/agg["cost"]*100) if agg["cost"] > 0 else 0.0
        return {"period": {"start": start_str, "end": end_str}, "total_tasks": agg["total_tasks"],
                "gross_earnings": round(agg["gross"], 2), "total_cost": round(agg["cost"], 4),
                "net_profit": round(agg["net"], 2), "avg_quality": round(agg["avg_q"], 3),
                "roi_percent": round(roi, 1), "by_sector": [dict(r) for r in sector_rows]}

    def get_lifetime_stats(self):
        with self._db() as conn:
            agg = conn.execute(
                """SELECT COUNT(*) AS total_tasks, COALESCE(SUM(actual_payment),0) AS gross,
                   COALESCE(SUM(token_cost),0) AS cost, COALESCE(SUM(net_profit),0) AS net,
                   COALESCE(AVG(quality_score),0) AS avg_q, COALESCE(MAX(actual_payment),0) AS best_pay
                   FROM clawwork_tasks""").fetchone()
        roi = (agg["net"]/agg["cost"]*100) if agg["cost"] > 0 else 0.0
        return {"total_tasks": agg["total_tasks"], "gross_earnings": round(agg["gross"], 2),
                "net_profit": round(agg["net"], 2), "avg_quality": round(agg["avg_q"], 3),
                "best_single_payment": round(agg["best_pay"], 2), "lifetime_roi_percent": round(roi, 1)}

    def export_csv(self, output_path=None):
        if output_path is None:
            today = datetime.now(MST).strftime("%Y%m%d")
            output_path = self.export_dir / f"clawwork_export_{today}.csv"
        with self._db() as conn:
            rows = conn.execute(
                """SELECT task_id, sector, occupation, estimated_value, actual_payment,
                   quality_score, token_cost, net_profit, duration_seconds, completed_at, date
                   FROM clawwork_tasks ORDER BY completed_at""").fetchall()
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Task ID", "Sector", "Occupation", "Est Value", "Payment",
                             "Quality", "Token Cost", "Net Profit", "Duration", "Completed At", "Date"])
            for row in rows:
                writer.writerow(list(row))
        return output_path

    def generate_telegram_daily(self, date=None):
        s = self.get_daily_summary(date)
        lines = [f"📊 *ClawWork Daily Report* — {s['date']}",
                 f"Tasks: *{s['tasks']}*  Gross: *${s['gross_earnings']:.2f}*",
                 f"Cost: ${s['total_cost']:.4f}  Net: *${s['net_profit']:.2f}* 🎉",
                 f"Avg quality: {s['avg_quality']:.2f}/1.0"]
        if s["by_sector"]:
            lines.append("*Sectors:*")
            for sec in s["by_sector"][:3]:
                lines.append(f"  • {sec['sector']}: ${sec['earnings']:.2f} ({sec['tasks']} tasks)")
        lifetime = self.get_lifetime_stats()
        lines.append(f"Lifetime net: *${lifetime['net_profit']:.2f}*")
        return "\n".join(lines)

    def generate_telegram_weekly(self):
        s = self.get_weekly_report()
        lines = [f"📈 *ClawWork Weekly Report*  {s['period']['start']} → {s['period']['end']}",
                 f"Tasks: *{s['total_tasks']}*  Net: *${s['net_profit']:.2f}*  ROI: {s['roi_percent']:.0f}%"]
        if s["by_sector"]:
            lines.append("*Top sectors:*")
            for sec in s["by_sector"][:3]:
                lines.append(f"  • {sec['sector']}: ${sec['net']:.2f} (q={sec['avg_quality']:.2f})")
        return "\n".join(lines)
