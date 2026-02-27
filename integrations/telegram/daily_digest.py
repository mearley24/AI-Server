#!/usr/bin/env python3
"""
daily_digest.py — Bob the Conductor Daily & Weekly Digest Generator

Compiles a morning briefing from all Bob data sources and sends it via
NotificationManager. Can run as a one-shot command or as a daemon that
fires at the configured time each day.

Usage:
    # One-shot (run once now)
    python daily_digest.py

    # Daemon mode (runs every morning at configured time)
    python daily_digest.py --daemon
"""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from notification_manager import NotificationManager, NotificationType, Priority

load_dotenv()

logger = logging.getLogger("bob.digest")
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

OPENCLAW_API_URL = os.getenv("OPENCLAW_API_URL", "http://openclaw:3000")
BOB_API_URL      = os.getenv("BOB_API_URL", "http://localhost:8080")
CLAWWORK_DB_PATH = os.getenv("CLAWWORK_DB_PATH", "/data/clawwork/earnings.db")
VOICE_DB_PATH    = os.getenv("VOICE_DB_PATH", "/data/voice/calls.db")

CONFIG_PATH = Path(__file__).parent / "bot_config.json"
try:
    with open(CONFIG_PATH) as _f:
        _cfg = json.load(_f)
except FileNotFoundError:
    _cfg = {}

DIGEST_TIME   = _cfg.get("notification_preferences", {}).get("daily_digest", {}).get("send_time", "07:30")
WEEKLY_DAY    = _cfg.get("notification_preferences", {}).get("weekly_summary", {}).get("send_day", "monday")
WEEKLY_TIME   = _cfg.get("notification_preferences", {}).get("weekly_summary", {}).get("send_time", "08:00")


# ─────────────────────────────────────────────
# Data Collection
# ─────────────────────────────────────────────

async def _api_get(url: str, params: dict = None) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.warning(f"API GET {url} failed: {e}")
    return None


def _query_sqlite(db_path: str, query: str, params: tuple = ()) -> list:
    """Read from a local SQLite DB and return rows as dicts."""
    if not Path(db_path).exists():
        logger.warning(f"SQLite DB not found: {db_path}")
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.warning(f"SQLite query failed on {db_path}: {e}")
        return []


async def collect_earnings(days: int = 1) -> dict:
    """ClawWork earnings for the past N days from DB or API."""
    data = await _api_get(f"{OPENCLAW_API_URL}/api/clawwork/earnings", {"days": days})
    if data:
        return data
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = _query_sqlite(
        CLAWWORK_DB_PATH,
        "SELECT SUM(amount) as total, COUNT(*) as task_count FROM earnings WHERE completed_at >= ?",
        (since,),
    )
    if rows and rows[0].get("total") is not None:
        return {
            "period_total": float(rows[0]["total"]),
            "task_count": int(rows[0]["task_count"]),
            "period_days": days,
        }
    return {"period_total": 0.0, "task_count": 0, "period_days": days}


async def collect_calls(days: int = 1) -> list:
    """Calls from the past N days."""
    data = await _api_get(f"{BOB_API_URL}/api/calls", {"days": days})
    if data and isinstance(data, list):
        return data
    since = (date.today() - timedelta(days=days)).isoformat()
    return _query_sqlite(
        VOICE_DB_PATH,
        "SELECT * FROM calls WHERE timestamp >= ? ORDER BY timestamp DESC",
        (since,),
    )


async def collect_health() -> dict:
    """Current node health from OpenClaw."""
    data = await _api_get(f"{OPENCLAW_API_URL}/api/health")
    return data or {}


async def collect_incidents(days: int = 1) -> list:
    """Recent alerts / incidents."""
    since = (date.today() - timedelta(days=days)).isoformat()
    data = await _api_get(f"{OPENCLAW_API_URL}/api/logs", {
        "level": "warn,error",
        "since": since,
        "limit": 50,
    })
    return data if isinstance(data, list) else []


async def collect_calendar() -> list:
    """Today's calendar events from Bob's API."""
    data = await _api_get(f"{BOB_API_URL}/api/calendar/today")
    return data if isinstance(data, list) else []


async def collect_node_uptime() -> dict:
    """Node uptime stats."""
    data = await _api_get(f"{OPENCLAW_API_URL}/api/nodes/uptime")
    return data or {}


# ─────────────────────────────────────────────
# Digest Formatter
# ─────────────────────────────────────────────

def _section(title: str, content: str) -> str:
    return f"*{title}*\n{content}\n"


def format_daily_digest(
    earnings: dict,
    calls: list,
    health: dict,
    incidents: list,
    calendar: list,
    uptime: dict,
    for_date: Optional[date] = None,
) -> str:
    today = for_date or date.today()
    yesterday = today - timedelta(days=1)
    lines = [
        f"☀️ *Good morning — Bob's Daily Digest*",
        f"_{yesterday.strftime('%A, %B %d, %Y')}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    earned = earnings.get("period_total", 0.0)
    task_count = earnings.get("task_count", 0)
    running_total = earnings.get("all_time_total", None)
    earn_line = f"  Earned: `${earned:.2f}` across `{task_count}` task(s)"
    if running_total is not None:
        earn_line += f"\n  Running total: `${running_total:.2f}`"
    if earned == 0 and task_count == 0:
        earn_line = "  No ClawWork tasks completed yesterday."
    lines.append(_section("💰 ClawWork Earnings (Yesterday)", earn_line))

    if calls:
        answered = [c for c in calls if c.get("outcome") not in ("missed", "voicemail")]
        missed   = [c for c in calls if c.get("outcome") in ("missed", "voicemail")]
        call_lines = [
            f"  Total calls: `{len(calls)}` | Answered: `{len(answered)}` | Missed: `{len(missed)}`",
        ]
        for c in calls[:5]:
            caller = c.get("caller_name") or c.get("caller_number", "Unknown")
            outcome = c.get("outcome", "?")
            ts = c.get("timestamp", "")[:16]
            call_lines.append(f"  \u2022 `{ts}` — {caller} ({outcome})")
        if len(calls) > 5:
            call_lines.append(f"  _…and {len(calls) - 5} more_")
        lines.append(_section("📞 Calls Received", "\n".join(call_lines)))
    else:
        lines.append(_section("📞 Calls Received", "  No calls yesterday."))

    nodes = health.get("nodes", {})
    if nodes:
        health_lines = []
        all_ok = True
        for name, info in nodes.items():
            ok = info.get("ok", False)
            if not ok:
                all_ok = False
            icon = "🟢" if ok else "🔴"
            cpu = info.get("cpu", "?")
            mem = info.get("mem", "?")
            disk = info.get("disk", "?")
            health_lines.append(f"  {icon} *{name}* — CPU: `{cpu}` | RAM: `{mem}` | Disk: `{disk}`")
        if all_ok:
            health_lines.insert(0, "  All nodes healthy.")
        lines.append(_section("💚 System Health", "\n".join(health_lines)))
    else:
        lines.append(_section("💚 System Health", "  Health data unavailable."))

    if incidents:
        inc_lines = []
        for inc in incidents[:10]:
            ts = inc.get("timestamp", "")[:16]
            msg = inc.get("message", "")
            lvl = inc.get("level", "?").upper()
            icon = "❌" if lvl in ("ERROR", "CRITICAL") else "⚠️"
            inc_lines.append(f"  {icon} `{ts}` {msg}")
        if len(incidents) > 10:
            inc_lines.append(f"  _{len(incidents) - 10} more in logs_")
        lines.append(_section("🚨 Alerts & Incidents", "\n".join(inc_lines)))
    else:
        lines.append(_section("🚨 Alerts & Incidents", "  No incidents yesterday. Clean run."))

    if calendar:
        cal_lines = []
        for evt in calendar:
            time_str = evt.get("start_time", "")
            title = evt.get("title", "Untitled")
            cal_lines.append(f"  \u2022 `{time_str}` — {title}")
        lines.append(_section("📅 Today's Calendar", "\n".join(cal_lines)))
    else:
        lines.append(_section("📅 Today's Calendar", "  Calendar clear — nothing scheduled today."))

    if uptime:
        up_lines = []
        for name, info in uptime.items():
            pct = info.get("uptime_pct", "?")
            since_str = info.get("since", "")
            up_lines.append(f"  `{name}`: `{pct}` uptime (since {since_str})")
        lines.append(_section("📊 Node Uptime (30d)", "\n".join(up_lines)))

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Generated by Bob \u00b7 {datetime.now().strftime('%H:%M')}_")
    return "\n".join(lines)


def format_weekly_summary(
    earnings_7d: dict,
    calls_7d: list,
    health: dict,
    incidents_7d: list,
) -> str:
    week_start = (date.today() - timedelta(days=7)).strftime("%b %d")
    week_end   = (date.today() - timedelta(days=1)).strftime("%b %d")
    lines = [
        f"📈 *Weekly Summary — {week_start} to {week_end}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    earned = earnings_7d.get("period_total", 0.0)
    tasks  = earnings_7d.get("task_count", 0)
    total  = earnings_7d.get("all_time_total")
    earn_line = f"  Earned: `${earned:.2f}` across `{tasks}` task(s)"
    if total:
        earn_line += f"\n  All-time: `${total:.2f}`"
    lines.append(_section("💰 ClawWork Earnings (7 days)", earn_line))
    lines.append(_section("📞 Calls (7 days)", f"  Total: `{len(calls_7d)}`"))
    critical = [i for i in incidents_7d if i.get("level", "").upper() in ("ERROR", "CRITICAL")]
    lines.append(_section("🚨 Incidents", f"  Total: `{len(incidents_7d)}` | Critical: `{len(critical)}`"))
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Generated by Bob \u00b7 {datetime.now().strftime('%H:%M')}_")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

async def send_daily_digest():
    logger.info("Generating daily digest…")
    try:
        earnings, calls, health, incidents, calendar, uptime = await asyncio.gather(
            collect_earnings(days=1),
            collect_calls(days=1),
            collect_health(),
            collect_incidents(days=1),
            collect_calendar(),
            collect_node_uptime(),
        )
        text = format_daily_digest(earnings, calls, health, incidents, calendar, uptime)
        nm = NotificationManager()
        await nm.send_daily_digest(text)
        logger.info("Daily digest sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send daily digest: {e}", exc_info=True)


async def send_weekly_summary():
    logger.info("Generating weekly summary…")
    try:
        earnings, calls, health, incidents = await asyncio.gather(
            collect_earnings(days=7),
            collect_calls(days=7),
            collect_health(),
            collect_incidents(days=7),
        )
        text = format_weekly_summary(earnings, calls, health, incidents)
        nm = NotificationManager()
        await nm.send(
            notif_type=NotificationType.WEEKLY_SUMMARY,
            message=text,
            priority=Priority.NORMAL,
            deduplicate=False,
        )
        logger.info("Weekly summary sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send weekly summary: {e}", exc_info=True)


def _parse_hhmm(t: str):
    h, m = t.split(":")
    return int(h), int(m)


async def run_daemon():
    logger.info("Digest daemon started. Waiting for scheduled send times.")
    last_daily_date = None
    last_weekly_date = None
    digest_h, digest_m = _parse_hhmm(DIGEST_TIME)
    weekly_h, weekly_m = _parse_hhmm(WEEKLY_TIME)
    weekly_day_num = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"].index(WEEKLY_DAY.lower())

    while True:
        now = datetime.now()
        today = now.date()
        if now.hour == digest_h and now.minute == digest_m and last_daily_date != today:
            await send_daily_digest()
            last_daily_date = today
        if (
            now.weekday() == weekly_day_num
            and now.hour == weekly_h and now.minute == weekly_m
            and last_weekly_date != today
        ):
            await send_weekly_summary()
            last_weekly_date = today
        await asyncio.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Bob Daily Digest")
    parser.add_argument("--daemon", action="store_true", help="Run as a daemon")
    parser.add_argument("--weekly", action="store_true", help="Send weekly summary now")
    args = parser.parse_args()
    if args.daemon:
        asyncio.run(run_daemon())
    elif args.weekly:
        asyncio.run(send_weekly_summary())
    else:
        asyncio.run(send_daily_digest())


if __name__ == "__main__":
    main()
