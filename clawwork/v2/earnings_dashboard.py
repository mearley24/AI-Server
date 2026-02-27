#!/usr/bin/env python3
"""
earnings_dashboard.py
=====================
Enhanced earnings tracking, analytics, and reporting for Bob's ClawWork operation.

Extends the existing earnings_tracker.py with:
  - Rich terminal dashboard (ASCII art)
  - Milestone tracking against targets
  - Sector breakdown analysis
  - Platform performance comparison
  - 90-day revenue forecast
  - CSV/JSON export
  - Daily/weekly/monthly summary reports

Usage:
    python earnings_dashboard.py dashboard   # Live terminal dashboard
    python earnings_dashboard.py daily       # Today's report
    python earnings_dashboard.py weekly      # 7-day summary
    python earnings_dashboard.py monthly     # 30-day summary
    python earnings_dashboard.py forecast    # 90-day projection
    python earnings_dashboard.py milestones  # Progress vs. targets
    python earnings_dashboard.py export      # Export to CSV/JSON
"""

import csv
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────────────

DAILY_TARGETS = {
    30:  40.0,    # Day 1–30 target: $40/day
    60:  75.0,    # Day 31–60 target: $75/day
    90:  90.0,    # Day 61–90 target: $90/day
    180: 125.0,   # Day 91–180 target: $125/day
    365: 200.0,   # Day 181–365 target: $200/day
}

MILESTONES = [
    {"label": "First ClawWork dollar",    "type": "cumulative",  "target": 1.0},
    {"label": "$100 cumulative",           "type": "cumulative",  "target": 100.0},
    {"label": "$500 cumulative",           "type": "cumulative",  "target": 500.0},
    {"label": "$1,000 cumulative",         "type": "cumulative",  "target": 1000.0},
    {"label": "$5,000 cumulative",         "type": "cumulative",  "target": 5000.0},
    {"label": "$10,000 cumulative",        "type": "cumulative",  "target": 10000.0},
    {"label": "$50,000 cumulative",        "type": "cumulative",  "target": 50000.0},
    {"label": "$100,000 cumulative",       "type": "cumulative",  "target": 100000.0},
    {"label": "First $50 day",             "type": "single_day",  "target": 50.0},
    {"label": "First $100 day",            "type": "single_day",  "target": 100.0},
    {"label": "First $200 day",            "type": "single_day",  "target": 200.0},
    {"label": "First $500 day",            "type": "single_day",  "target": 500.0},
    {"label": "20 tasks completed",        "type": "task_count",  "target": 20},
    {"label": "100 tasks completed",       "type": "task_count",  "target": 100},
    {"label": "500 tasks completed",       "type": "task_count",  "target": 500},
    {"label": "Average quality ≥ 0.87",    "type": "avg_quality", "target": 0.87},
    {"label": "Average quality ≥ 0.90",    "type": "avg_quality", "target": 0.90},
]

SECTORS = [
    "research_reports", "technical_writing", "code_review",
    "bookkeeping", "content_writing", "real_estate",
    "customer_support", "data_entry",
]


# ── Database layer ────────────────────────────────────────────────────────────────────

class EarningsDB:
    """
    Thin wrapper around the ClawWork earnings SQLite database.
    
    Schema (created if not exists):
      tasks: task_id, platform, sector, gross_value, net_value,
             quality_score, completed_at, client_id, title
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn    = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id       TEXT PRIMARY KEY,
                platform      TEXT NOT NULL,
                sector        TEXT NOT NULL,
                gross_value   REAL NOT NULL,
                net_value     REAL NOT NULL,
                quality_score REAL,
                completed_at  TEXT NOT NULL,
                client_id     TEXT,
                title         TEXT
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_date
            ON tasks(completed_at)
        """)
        self.conn.commit()

    def insert_task(self, task_id, platform, sector, gross, net,
                    quality, completed_at, client_id=None, title=None):
        self.conn.execute("""
            INSERT OR IGNORE INTO tasks
            (task_id, platform, sector, gross_value, net_value,
             quality_score, completed_at, client_id, title)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (task_id, platform, sector, gross, net,
               quality, completed_at.isoformat(), client_id, title))
        self.conn.commit()

    def query(self, sql: str, params=()) -> list:
        cur = self.conn.execute(sql, params)
        return cur.fetchall()

    def total_net(self, since: Optional[date] = None) -> float:
        if since:
            rows = self.query(
                "SELECT SUM(net_value) FROM tasks WHERE completed_at >= ?",
                (since.isoformat(),)
            )
        else:
            rows = self.query("SELECT SUM(net_value) FROM tasks")
        return rows[0][0] or 0.0

    def task_count(self, since: Optional[date] = None) -> int:
        if since:
            rows = self.query(
                "SELECT COUNT(*) FROM tasks WHERE completed_at >= ?",
                (since.isoformat(),)
            )
        else:
            rows = self.query("SELECT COUNT(*) FROM tasks")
        return rows[0][0] or 0

    def avg_quality(self, since: Optional[date] = None) -> float:
        if since:
            rows = self.query(
                "SELECT AVG(quality_score) FROM tasks WHERE completed_at >= ?",
                (since.isoformat(),)
            )
        else:
            rows = self.query("SELECT AVG(quality_score) FROM tasks")
        return rows[0][0] or 0.0

    def daily_earnings(self, since: date, until: date) -> dict:
        """
        Returns {date_str: net_amount} for each day in range.
        """
        rows = self.query("""
            SELECT DATE(completed_at) as day, SUM(net_value)
            FROM tasks
            WHERE completed_at >= ? AND completed_at <= ?
            GROUP BY day ORDER BY day
        """, (since.isoformat(), until.isoformat()))
        return {row[0]: row[1] for row in rows}

    def sector_breakdown(self, since: Optional[date] = None) -> list:
        if since:
            rows = self.query("""
                SELECT sector,
                       COUNT(*) as cnt,
                       SUM(net_value) as total,
                       AVG(quality_score) as avg_q
                FROM tasks WHERE completed_at >= ?
                GROUP BY sector ORDER BY total DESC
            """, (since.isoformat(),))
        else:
            rows = self.query("""
                SELECT sector, COUNT(*) as cnt,
                       SUM(net_value) as total, AVG(quality_score) as avg_q
                FROM tasks GROUP BY sector ORDER BY total DESC
            """)
        return [dict(r) for r in rows]

    def platform_breakdown(self, since: Optional[date] = None) -> list:
        if since:
            rows = self.query("""
                SELECT platform, COUNT(*) as cnt, SUM(net_value) as total
                FROM tasks WHERE completed_at >= ?
                GROUP BY platform ORDER BY total DESC
            """, (since.isoformat(),))
        else:
            rows = self.query("""
                SELECT platform, COUNT(*) as cnt, SUM(net_value) as total
                FROM tasks GROUP BY platform ORDER BY total DESC
            """)
        return [dict(r) for r in rows]

    def best_day(self) -> tuple:
        rows = self.query("""
            SELECT DATE(completed_at) as day, SUM(net_value) as total
            FROM tasks GROUP BY day ORDER BY total DESC LIMIT 1
        """)
        if rows:
            return rows[0]["day"], rows[0]["total"]
        return None, 0.0

    def all_tasks_export(self) -> list:
        rows = self.query("SELECT * FROM tasks ORDER BY completed_at")
        return [dict(r) for r in rows]


# ── Dashboard ──────────────────────────────────────────────────────────────────────────

class EarningsDashboard:
    """
    Analytics and reporting engine for ClawWork earnings.
    """

    def __init__(self, db: EarningsDB, start_date: Optional[date] = None):
        self.db         = db
        self.start_date = start_date or date.today()
        self.today      = date.today()

    @property
    def days_active(self) -> int:
        return (self.today - self.start_date).days + 1

    def current_daily_target(self) -> float:
        for threshold, target in sorted(DAILY_TARGETS.items()):
            if self.days_active <= threshold:
                return target
        return DAILY_TARGETS[365]

    # ── Core metrics ────────────────────────────────────────────────────────────────

    def today_earnings(self) -> float:
        daily = self.db.daily_earnings(self.today, self.today)
        return daily.get(self.today.isoformat(), 0.0)

    def period_earnings(self, days: int) -> float:
        since = self.today - timedelta(days=days - 1)
        return self.db.total_net(since=since)

    def daily_average(self, days: int = 30) -> float:
        since = self.today - timedelta(days=days - 1)
        days_with_data = max(1, days)
        return self.period_earnings(days) / days_with_data

    def total_earnings(self) -> float:
        return self.db.total_net()

    def total_tasks(self) -> int:
        return self.db.task_count()

    def avg_task_value(self) -> float:
        count = self.total_tasks()
        if count == 0:
            return 0.0
        return self.total_earnings() / count

    def avg_quality(self) -> float:
        return self.db.avg_quality()

    def best_day(self) -> tuple:
        return self.db.best_day()

    # ── Milestone tracking ───────────────────────────────────────────────────────────

    def milestone_status(self) -> list:
        """
        Returns list of milestone dicts with 'achieved' and 'progress' fields.
        """
        cumulative    = self.total_earnings()
        task_count    = self.total_tasks()
        avg_q         = self.avg_quality()
        daily_history = self.db.daily_earnings(
            self.start_date, self.today
        )
        best_day_val  = max(daily_history.values(), default=0.0)

        results = []
        for m in MILESTONES:
            achieved = False
            progress = 0.0

            if m["type"] == "cumulative":
                achieved = cumulative >= m["target"]
                progress = min(1.0, cumulative / m["target"])
            elif m["type"] == "single_day":
                achieved = best_day_val >= m["target"]
                progress = min(1.0, best_day_val / m["target"])
            elif m["type"] == "task_count":
                achieved = task_count >= m["target"]
                progress = min(1.0, task_count / m["target"])
            elif m["type"] == "avg_quality":
                achieved = avg_q >= m["target"]
                progress = min(1.0, avg_q / m["target"])

            results.append({
                **m,
                "achieved":  achieved,
                "progress":  round(progress * 100, 1),
            })

        return results

    # ── Forecasting ──────────────────────────────────────────────────────────────────────

    def forecast_90d(self) -> dict:
        """
        Project earnings over the next 90 days using a weighted moving average.

        Returns:
            {
                "daily_rate":       float,
                "30d_forecast":     float,
                "60d_forecast":     float,
                "90d_forecast":     float,
                "days_to_targets": {50: int, 100: int, 200: int}
            }
        """
        # 14-day weighted average (recent days weighted 2×)
        last_14 = self.db.daily_earnings(
            self.today - timedelta(days=13), self.today
        )
        values = list(last_14.values())
        if not values:
            daily_rate = self.current_daily_target() * 0.5   # cold start estimate
        else:
            n = len(values)
            weights    = [1 if i < n // 2 else 2 for i in range(n)]
            daily_rate = sum(v * w for v, w in zip(values, weights)) / sum(weights)

        cumulative_now = self.total_earnings()

        forecast = {
            "daily_rate":    round(daily_rate, 2),
            "30d_forecast":  round(daily_rate * 30, 2),
            "60d_forecast":  round(daily_rate * 60, 2),
            "90d_forecast":  round(daily_rate * 90, 2),
            "days_to_targets": {},
        }

        for target in [1000, 5000, 10000, 50000, 100000]:
            gap = target - cumulative_now
            if gap <= 0:
                forecast["days_to_targets"][target] = 0
            elif daily_rate > 0:
                forecast["days_to_targets"][target] = int(gap / daily_rate)
            else:
                forecast["days_to_targets"][target] = 9999

        return forecast

    # ── Reports ────────────────────────────────────────────────────────────────────────────

    def daily_report(self) -> str:
        today_net = self.today_earnings()
        target    = self.current_daily_target()
        pct       = (today_net / target * 100) if target > 0 else 0
        status    = "✅" if today_net >= target else ("⚠️" if today_net >= target * 0.7 else "❌")

        lines = [
            f"── ClawWork Daily Report — {self.today} ──",
            f"Day {self.days_active} of operations",
            "",
            f"Today's earnings:  ${today_net:.2f}",
            f"Daily target:      ${target:.2f}  {status} ({pct:.0f}%)",
            f"7-day total:       ${self.period_earnings(7):.2f}",
            f"Cumulative total:  ${self.total_earnings():.2f}",
            "",
            f"Tasks today:       {self.db.task_count(since=self.today)}",
            f"Avg quality:       {self.avg_quality():.3f}",
        ]

        # Best day
        bd_date, bd_val = self.best_day()
        if bd_date:
            lines.append(f"Best day ever:     ${bd_val:.2f} ({bd_date})")

        return "\n".join(lines)

    def weekly_report(self) -> str:
        since = self.today - timedelta(days=6)
        daily = self.db.daily_earnings(since, self.today)
        target = self.current_daily_target()

        lines = [
            f"── ClawWork Weekly Report ──",
            f"{since} → {self.today}",
            "",
        ]

        total = 0.0
        for i in range(7):
            d     = since + timedelta(days=i)
            earned = daily.get(d.isoformat(), 0.0)
            total += earned
            bar   = "█" * int(earned / 10)
            mark  = "✓" if earned >= target else "·"
            lines.append(f"  {d.strftime('%a %b %d')}  {mark}  ${earned:>7.2f}  {bar}")

        lines += [
            "",
            f"Week total:  ${total:.2f}",
            f"Daily avg:   ${total / 7:.2f}  (target: ${target:.2f})",
            f"Hit rate:    {sum(1 for v in daily.values() if v >= target)}/7 days",
        ]
        return "\n".join(lines)

    def monthly_report(self) -> str:
        since = self.today - timedelta(days=29)
        sector_data = self.db.sector_breakdown(since=since)
        plat_data   = self.db.platform_breakdown(since=since)
        month_total = self.period_earnings(30)
        task_count  = self.db.task_count(since=since)

        lines = [
            f"── ClawWork Monthly Report ──",
            f"{since} → {self.today}",
            "",
            f"Total net:     ${month_total:.2f}",
            f"Daily average: ${month_total / 30:.2f}",
            f"Total tasks:   {task_count}",
            f"Avg task value:${month_total / max(1, task_count):.2f}",
            "",
            "── By Sector:",
        ]

        for s in sector_data:
            pct = s['total'] / month_total * 100 if month_total > 0 else 0
            lines.append(
                f"  {s['sector']:<22} {s['cnt']:>4} tasks   "
                f"${s['total']:>8.2f}  ({pct:.0f}%)   "
                f"q={s['avg_q']:.3f}"
            )

        lines += ["", "── By Platform:"]
        for p in plat_data:
            pct = p['total'] / month_total * 100 if month_total > 0 else 0
            lines.append(
                f"  {p['platform']:<12} {p['cnt']:>4} tasks   "
                f"${p['total']:>8.2f}  ({pct:.0f}%)"
            )

        return "\n".join(lines)

    def milestones_report(self) -> str:
        milestones = self.milestone_status()
        achieved   = [m for m in milestones if m["achieved"]]
        pending    = [m for m in milestones if not m["achieved"]]

        lines = [
            "── ClawWork Milestone Tracker ──",
            f"Day {self.days_active} | Cumulative: ${self.total_earnings():.2f}",
            "",
            f"✅ ACHIEVED ({len(achieved)})",
        ]
        for m in achieved:
            lines.append(f"   • {m['label']}")

        lines += ["", f"🎯 PENDING ({len(pending)}):"]
        for m in pending[:8]:  # show next 8
            bar_len = int(m['progress'] / 10)
            bar     = "█" * bar_len + "░" * (10 - bar_len)
            lines.append(f"   [{bar}] {m['progress']:>5.1f}%  {m['label']}")

        return "\n".join(lines)

    def forecast_report(self) -> str:
        f = self.forecast_90d()
        lines = [
            "── ClawWork 90-Day Forecast ──",
            f"Based on 14-day weighted average: ${f['daily_rate']:.2f}/day",
            "",
            f"30-day projection:  ${f['30d_forecast']:,.2f}",
            f"60-day projection:  ${f['60d_forecast']:,.2f}",
            f"90-day projection:  ${f['90d_forecast']:,.2f}",
            "",
            "── Days to Milestones:",
        ]
        for target, days in sorted(f["days_to_targets"].items()):
            status = "ACHIEVED" if days == 0 else f"~{days} days"
            lines.append(f"  ${target:>8,}  →  {status}")
        return "\n".join(lines)

    def ascii_dashboard(self) -> str:
        today_net = self.today_earnings()
        target    = self.current_daily_target()
        total     = self.total_earnings()
        tasks     = self.total_tasks()
        quality   = self.avg_quality()
        bd_date, bd_val = self.best_day()
        f         = self.forecast_90d()
        target_pct = int(today_net / target * 100) if target > 0 else 0

        bar_width = 30
        filled    = int(bar_width * min(1.0, today_net / target))
        bar       = "█" * filled + "░" * (bar_width - filled)

        return (
            "┌" + "─" * 54 + "┐\n"
            "│  🦞  ClawWork Operations Dashboard" + " " * 18 + "│\n"
            "│  Day {days:<4}  |  📅 {today}" + " " * 14 + "│\n"
            "├" + "─" * 54 + "┤\n"
            "│  TODAY:    ${today_net:>8.2f}  [{bar}] {pct}%" + " " * 2 + "│\n"
            "│  TARGET:   ${target:>8.2f}" + " " * 30 + "│\n"
            "│  TOTAL:    ${total:>8.2f}  ({tasks} tasks, avg q={quality:.3f})" + " " * 2 + "│\n"
            "│  BEST DAY: ${bd:>8.2f}  ({bd_date})" + " " * 14 + "│\n"
            "│  FORECAST: ${forecast:>8.2f}/day  |  90d: ${forecast90:>10,.0f}" + " " * 2 + "│\n"
            "└" + "─" * 54 + "┘"
        ).format(
            days=self.days_active,
            today=self.today,
            today_net=today_net,
            bar=bar,
            pct=target_pct,
            target=target,
            total=total,
            tasks=tasks,
            quality=quality,
            bd=bd_val,
            bd_date=bd_date or "n/a",
            forecast=f["daily_rate"],
            forecast90=f["90d_forecast"],
        )

    # ── Export ─────────────────────────────────────────────────────────────────────────────────

    def export_csv(self, output_path: str):
        tasks = self.db.all_tasks_export()
        if not tasks:
            print("No data to export.")
            return
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=tasks[0].keys())
            writer.writeheader()
            writer.writerows(tasks)
        print(f"Exported {len(tasks)} tasks to {output_path}")

    def export_json(self, output_path: str):
        tasks = self.db.all_tasks_export()
        with open(output_path, "w") as f:
            json.dump(tasks, f, indent=2, default=str)
        print(f"Exported {len(tasks)} tasks to {output_path}")


# ── CLI entrypoint ──────────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    config_path = Path("/home/user/workspace/clawwork_integration/clawwork_config.json")
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {"earnings_tracking": {"database_path": "/data/clawwork_earnings.db"}}


def main():
    config   = _load_config()
    db_path  = config.get("earnings_tracking", {}).get(
        "database_path", "/data/clawwork_earnings.db"
    )
    start_str = config.get("start_date", None)
    start_date = datetime.strptime(start_str, "%Y-%m-%d").date() if start_str else date(2026, 2, 27)

    db        = EarningsDB(db_path)
    dashboard = EarningsDashboard(db, start_date=start_date)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"

    if cmd == "daily":
        print(dashboard.daily_report())

    elif cmd == "weekly":
        print(dashboard.weekly_report())

    elif cmd == "monthly":
        print(dashboard.monthly_report())

    elif cmd == "milestones":
        print(dashboard.milestones_report())

    elif cmd == "forecast":
        print(dashboard.forecast_report())

    elif cmd == "export":
        fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"
        out = sys.argv[3] if len(sys.argv) > 3 else f"clawwork_export_{date.today()}.{fmt}"
        if fmt == "json":
            dashboard.export_json(out)
        else:
            dashboard.export_csv(out)

    elif cmd == "dashboard":
        print(dashboard.ascii_dashboard())


if __name__ == "__main__":
    main()
