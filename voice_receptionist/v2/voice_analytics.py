"""
voice_analytics.py — Symphony Smart Homes Voice Receptionist
Call analytics, reporting, and business intelligence for Bob the Conductor.

Provides:
  - Daily / weekly call summary generation
  - Intent trend analysis
  - Escalation rate tracking
  - Callback follow-up reporting
  - Telegram-formatted digest messages
  - CSV export for owner review
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

from caller_memory import CallerMemory, caller_memory

logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────────

TIMEZONE_NAME = os.getenv("BUSINESS_TIMEZONE", "America/Denver")


# ─── Report Period Helpers ─────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.utcnow()


def _period_cutoff(days: int) -> str:
    """Return ISO8601 UTC timestamp for N days ago."""
    return (_utc_now() - timedelta(days=days)).isoformat() + "Z"


def _today_start() -> str:
    """Return ISO8601 UTC timestamp for the start of today (UTC)."""
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"


def _week_start() -> str:
    """Return ISO8601 UTC timestamp for the start of this week (Monday)."""
    now = _utc_now()
    days_since_monday = now.weekday()
    monday = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.isoformat() + "Z"


# ─── Core Analytics Queries ─────────────────────────────────────────────────────

def get_daily_stats(
    memory: CallerMemory = caller_memory,
) -> dict:
    """
    Return call statistics for today (UTC).
    """
    return memory.get_stats(days=1)


def get_weekly_stats(
    memory: CallerMemory = caller_memory,
) -> dict:
    """
    Return call statistics for the past 7 days.
    """
    return memory.get_stats(days=7)


def get_monthly_stats(
    memory: CallerMemory = caller_memory,
) -> dict:
    """
    Return call statistics for the past 30 days.
    """
    return memory.get_stats(days=30)


def get_top_callers(
    limit: int = 10,
    days: int = 30,
    memory: CallerMemory = caller_memory,
) -> list[dict]:
    """
    Return the top N callers by call count over the past N days.
    """
    cutoff = _period_cutoff(days)
    with memory._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                c.phone_number,
                c.name,
                c.company,
                c.vip,
                COUNT(ce.id) AS call_count,
                SUM(ce.duration_seconds) AS total_seconds,
                MAX(ce.called_at) AS last_call
            FROM callers c
            JOIN call_events ce ON c.phone_number = ce.phone_number
            WHERE ce.called_at >= ?
            GROUP BY c.phone_number
            ORDER BY call_count DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_unanswered_callbacks(
    memory: CallerMemory = caller_memory,
) -> list[dict]:
    """
    Return all callers who requested a callback but haven't been called back.
    Sorted by oldest request first.
    """
    callbacks = memory.list_callbacks(pending_only=True)
    # Sort oldest first (most urgent to follow up)
    return sorted(callbacks, key=lambda x: x.get("called_at", ""))


def get_intent_trends(
    days: int = 7,
    memory: CallerMemory = caller_memory,
) -> dict[str, list]:
    """
    Return daily intent counts over the past N days.
    Returns a dict of intent → list of (date, count) tuples.
    """
    cutoff = _period_cutoff(days)
    with memory._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                DATE(called_at) AS call_date,
                intent_detected,
                COUNT(*) AS count
            FROM call_events
            WHERE called_at >= ? AND intent_detected != ''
            GROUP BY call_date, intent_detected
            ORDER BY call_date ASC
            """,
            (cutoff,),
        ).fetchall()

    trends: dict[str, list] = defaultdict(list)
    for row in rows:
        r = dict(row)
        trends[r["intent_detected"]].append((r["call_date"], r["count"]))
    return dict(trends)


def get_escalation_report(
    days: int = 7,
    memory: CallerMemory = caller_memory,
) -> list[dict]:
    """
    Return all escalated calls over the past N days with full detail.
    """
    cutoff = _period_cutoff(days)
    with memory._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                ce.*,
                c.name,
                c.company,
                c.vip
            FROM call_events ce
            JOIN callers c ON ce.phone_number = c.phone_number
            WHERE ce.escalated = 1 AND ce.called_at >= ?
            ORDER BY ce.called_at DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Summary Formatters ─────────────────────────────────────────────────────────

def _fmt_duration(seconds: int | None) -> str:
    """Format seconds as a human-readable duration string."""
    if not seconds:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m"


def _fmt_intent(intent: str) -> str:
    """Format an intent key as a readable label."""
    return intent.replace("_", " ").title() if intent else "Unknown"


def _sentiment_emoji(sentiment: str) -> str:
    return {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}.get(sentiment, "⚪")


def format_telegram_daily_digest(
    memory: CallerMemory = caller_memory,
) -> str:
    """
    Build a Telegram-formatted daily digest message for the owner.
    Sent each morning via the Telegram bot.
    """
    stats = get_daily_stats(memory)
    callbacks = get_unanswered_callbacks(memory)
    today = datetime.utcnow().strftime("%A, %B %-d")

    total = stats.get("total_calls") or 0
    unique = stats.get("unique_callers") or 0
    total_secs = stats.get("total_seconds") or 0
    avg_secs = int(stats.get("avg_seconds") or 0)
    escalations = stats.get("escalations") or 0
    intent_breakdown = stats.get("intent_breakdown") or {}
    sentiment_breakdown = stats.get("sentiment_breakdown") or {}

    lines = [
        f"🎵 *Symphony Call Digest — {today}*",
        "",
        f"📞 Calls: *{total}* ({unique} unique callers)",
        f"⏱ Total time: *{_fmt_duration(total_secs)}* | Avg: *{_fmt_duration(avg_secs)}*",
        f"⚠️ Escalations: *{escalations}*",
        f"📲 Callbacks pending: *{len(callbacks)}*",
        "",
    ]

    if intent_breakdown:
        lines.append("🎯 *Intent Breakdown:*")
        for intent, count in sorted(intent_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"  • {_fmt_intent(intent)}: {count}")
        lines.append("")

    if sentiment_breakdown:
        lines.append("📊 *Sentiment:*")
        for sent, count in sorted(sentiment_breakdown.items(), key=lambda x: -x[1]):
            emoji = _sentiment_emoji(sent)
            lines.append(f"  {emoji} {sent.title()}: {count}")
        lines.append("")

    if callbacks:
        lines.append("📍 *Callbacks Needed:*")
        for cb in callbacks[:5]:  # Show max 5
            name = cb.get("name") or cb.get("phone_number", "Unknown")
            reason = cb.get("summary", "")[:60]
            time_pref = cb.get("callback_time", "")
            entry = f"  • {name}"
            if reason:
                entry += f" — {reason}"
            if time_pref:
                entry += f" (prefers: {time_pref})"
            lines.append(entry)
        if len(callbacks) > 5:
            lines.append(f"  + {len(callbacks) - 5} more...")
        lines.append("")

    if total == 0:
        lines.append("🙌 *Quiet day — no calls recorded.*")

    lines.append("_Generated by Bob the Conductor — Symphony Smart Homes_")
    return "\n".join(lines)


def format_telegram_weekly_report(
    memory: CallerMemory = caller_memory,
) -> str:
    """
    Build a Telegram-formatted weekly summary for the owner.
    """
    stats = get_weekly_stats(memory)
    top = get_top_callers(limit=5, days=7, memory=memory)
    escalations = get_escalation_report(days=7, memory=memory)
    week_label = datetime.utcnow().strftime("Week of %B %-d")

    total = stats.get("total_calls") or 0
    unique = stats.get("unique_callers") or 0
    total_secs = stats.get("total_seconds") or 0
    avg_secs = int(stats.get("avg_seconds") or 0)
    esc_count = stats.get("escalations") or 0
    intent_breakdown = stats.get("intent_breakdown") or {}

    lines = [
        f"🎵 *Symphony Weekly Report — {week_label}*",
        "",
        f"📞 Total calls: *{total}* | Unique callers: *{unique}*",
        f"⏱ Total time on phone: *{_fmt_duration(total_secs)}* | Avg: *{_fmt_duration(avg_secs)}*",
        f"⚠️ Escalations: *{esc_count}*",
        "",
    ]

    if intent_breakdown:
        lines.append("🎯 *Top Intents This Week:*")
        for intent, count in sorted(intent_breakdown.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  • {_fmt_intent(intent)}: {count} calls")
        lines.append("")

    if top:
        lines.append("👑 *Most Active Callers:*")
        for caller in top:
            name = caller.get("name") or caller.get("phone_number", "Unknown")
            count = caller.get("call_count", 0)
            secs = caller.get("total_seconds", 0)
            vip = " ⭐" if caller.get("vip") else ""
            lines.append(f"  • {name}{vip}: {count} calls ({_fmt_duration(secs)})")
        lines.append("")

    if escalations:
        lines.append(f"⚠️ *Escalations ({len(escalations)}):*")
        for esc in escalations[:3]:
            name = esc.get("name") or esc.get("phone_number", "?")
            reason = esc.get("escalation_reason", "")[:60]
            date_str = esc.get("called_at", "")[:10]
            lines.append(f"  • {date_str} — {name}: {reason}")
        if len(escalations) > 3:
            lines.append(f"  + {len(escalations) - 3} more")
        lines.append("")

    lines.append("_Generated by Bob the Conductor — Symphony Smart Homes_")
    return "\n".join(lines)


# ─── CSV Export ────────────────────────────────────────────────────────────────

def export_calls_csv(
    days: int = 30,
    memory: CallerMemory = caller_memory,
) -> str:
    """
    Export call log to CSV format (string). For owner review.

    Returns:
        CSV string with headers.
    """
    cutoff = _period_cutoff(days)
    with memory._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                ce.called_at,
                c.name,
                c.company,
                ce.phone_number,
                ce.direction,
                ce.intent_detected,
                ce.script_used,
                ce.duration_seconds,
                ce.escalated,
                ce.escalation_reason,
                ce.sentiment,
                ce.callback_requested,
                ce.summary
            FROM call_events ce
            LEFT JOIN callers c ON ce.phone_number = c.phone_number
            WHERE ce.called_at >= ?
            ORDER BY ce.called_at DESC
            """,
            (cutoff,),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date/Time", "Name", "Company", "Phone", "Direction",
        "Intent", "Script", "Duration (s)", "Escalated",
        "Escalation Reason", "Sentiment", "Callback Requested", "Summary"
    ])
    for row in rows:
        writer.writerow(list(row))

    return output.getvalue()


def export_callers_csv(
    memory: CallerMemory = caller_memory,
) -> str:
    """
    Export the full caller directory to CSV.
    """
    with memory._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                phone_number, name, company, email,
                call_count, last_call_at, last_intent,
                vip, notes, preferred_contact,
                birthday, anniversary, dtools_project_id,
                created_at
            FROM callers
            ORDER BY call_count DESC
            """
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Phone", "Name", "Company", "Email",
        "Call Count", "Last Call", "Last Intent",
        "VIP", "Notes", "Preferred Contact",
        "Birthday", "Anniversary", "D-Tools Project ID",
        "Created At"
    ])
    for row in rows:
        writer.writerow(list(row))

    return output.getvalue()


# ─── Upcoming Occasions Alert ───────────────────────────────────────────────────

def format_occasions_alert(
    days_ahead: int = 14,
    memory: CallerMemory = caller_memory,
) -> str:
    """
    Return a Telegram message listing upcoming birthdays and anniversaries.
    """
    occasions = memory.upcoming_occasions(days_ahead=days_ahead)
    if not occasions:
        return ""

    lines = [f"🎉 *Upcoming Occasions (next {days_ahead} days):*", ""]
    for occ in occasions:
        name = occ.get("name", "Unknown")
        occasion_type = occ["occasion"].replace("_", " ").title()
        date_str = occ["date"]
        days_until = occ["days_until"]
        if days_until == 0:
            timing = "TODAY 🎈"
        elif days_until == 1:
            timing = "tomorrow"
        else:
            timing = f"in {days_until} days"
        lines.append(f"  • {name} — {occasion_type} on {date_str} ({timing})")

    return "\n".join(lines)


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Print a sample daily digest."""
    print(format_telegram_daily_digest())
