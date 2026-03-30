#!/usr/bin/env python3
"""
Daily Briefing — sends Matthew a morning summary via iMessage.

Runs at 7 AM MT via cron/launchd. Gathers:
1. New emails since last briefing (grouped by project)
2. Bid deadlines this week
3. Pending client decisions from Linear
4. Calendar reminder (placeholder until calendar integration)
5. Trading summary (from position data if available)
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# Ensure openclaw/ imports work
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

logger = logging.getLogger("openclaw.daily_briefing")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_REPO_ROOT = Path(__file__).resolve().parent.parent
EMAIL_DB_PATH = os.environ.get("EMAIL_DB_PATH", "/data/emails.db")
ROUTING_CONFIG_PATH = _REPO_ROOT / "email-monitor" / "routing_config.json"

# Mountain Time offset (UTC-6 in summer / UTC-7 in winter)
# We use UTC for DB queries and convert for display.


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def get_new_emails_since(hours: int = 24) -> list[dict]:
    """Read emails from the last N hours, grouped by project/sender."""
    if not os.path.exists(EMAIL_DB_PATH):
        logger.warning("Email DB not found at %s", EMAIL_DB_PATH)
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    conn = sqlite3.connect(EMAIL_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT sender, sender_name, subject, category, received_at
               FROM emails
               WHERE received_at > ?
               ORDER BY received_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_bid_deadlines() -> list[dict]:
    """Load active bids from routing_config.json with upcoming deadlines."""
    if not ROUTING_CONFIG_PATH.exists():
        return []

    try:
        config = json.loads(ROUTING_CONFIG_PATH.read_text())
    except Exception as e:
        logger.error("Failed to read routing config: %s", e)
        return []

    active_bids = config.get("active_bids", {})
    now = datetime.now(timezone.utc)
    deadlines = []

    for name, bid in active_bids.items():
        due_str = bid.get("due", "")
        if not due_str:
            continue

        try:
            # Parse due date — may or may not have time component
            if " " in due_str:
                due = datetime.strptime(due_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            else:
                due = datetime.strptime(due_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        days_until = (due.date() - now.date()).days
        if days_until < 0:
            continue  # Past due, skip

        deadlines.append({
            "name": name,
            "gc": bid.get("gc", ""),
            "due": due_str,
            "days_until": days_until,
            "status": bid.get("status", ""),
        })

    deadlines.sort(key=lambda d: d["days_until"])
    return deadlines


def get_pending_decisions() -> list[dict]:
    """Fetch In Progress issues from Linear for pending client decisions."""
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        return []

    query = """
    query {
        issues(
            filter: {
                team: { key: { eq: "SYM" } }
                state: { name: { eq: "In Progress" } }
            }
            first: 20
            orderBy: updatedAt
        ) {
            nodes {
                identifier
                title
                project { name }
                updatedAt
            }
        }
    }
    """

    try:
        resp = requests.post(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            json={"query": query},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        nodes = data.get("issues", {}).get("nodes", [])
        return [
            {
                "id": n["identifier"],
                "title": n["title"],
                "project": n.get("project", {}).get("name", ""),
            }
            for n in nodes
        ]
    except Exception as e:
        logger.error("Linear API error: %s", e)
        return []


def get_trading_summary() -> Optional[str]:
    """Read trading position summary if available."""
    # Check for polymarket position data
    positions_path = _REPO_ROOT / "data" / "positions.json"
    if not positions_path.exists():
        # Try alternate location
        positions_path = Path("/data/positions.json")
    if not positions_path.exists():
        return None

    try:
        positions = json.loads(positions_path.read_text())
        if not positions:
            return None

        open_count = sum(1 for p in positions if p.get("status") == "open")
        total_value = sum(float(p.get("value", 0)) for p in positions if p.get("status") == "open")
        pnl_24h = sum(float(p.get("pnl_24h", 0)) for p in positions)

        pnl_sign = "+" if pnl_24h >= 0 else ""
        return f"Open positions: {open_count} (${total_value:.2f})\n  24h P&L: {pnl_sign}${pnl_24h:.2f}"
    except Exception as e:
        logger.debug("Could not read trading data: %s", e)
        return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_due_label(days: int) -> str:
    """Format a due-date label relative to today."""
    if days == 0:
        return "due TODAY"
    elif days == 1:
        return "due tomorrow"
    else:
        return f"due in {days} days"


def format_briefing(
    emails: list[dict],
    bids: list[dict],
    decisions: list[dict],
    trading: Optional[str] = None,
) -> str:
    """Format all sections into an iMessage-friendly briefing."""
    lines = ["Good morning — here's your briefing:\n"]

    # --- NEW EMAILS ---
    if emails:
        # Group by project/sender_name
        groups: dict[str, list[dict]] = {}
        for e in emails:
            key = e.get("sender_name") or e.get("sender", "Unknown")
            groups.setdefault(key, []).append(e)

        lines.append(f"NEW EMAILS ({len(emails)})")
        for sender, msgs in groups.items():
            subjects = ", ".join(m["subject"][:40] for m in msgs[:2])
            count_suffix = f" ({len(msgs)})" if len(msgs) > 1 else ""
            lines.append(f"  {sender}: {subjects}{count_suffix}")
    else:
        lines.append("NEW EMAILS (0)\n  Inbox clear.")

    # --- BID DEADLINES ---
    lines.append("")
    if bids:
        lines.append("BID DEADLINES")
        for b in bids:
            label = _format_due_label(b["days_until"])
            lines.append(f"  {b['name']} — {label}")
    else:
        lines.append("BID DEADLINES\n  No active bids with upcoming deadlines.")

    # --- PENDING DECISIONS ---
    lines.append("")
    if decisions:
        # Group by project
        by_project: dict[str, list[dict]] = {}
        for d in decisions:
            proj = d.get("project") or "General"
            by_project.setdefault(proj, []).append(d)

        lines.append("PENDING DECISIONS")
        for project, issues in by_project.items():
            lines.append(f"  [{project}]")
            for i, issue in enumerate(issues[:5], 1):
                lines.append(f"    {i}. {issue['title']}")
    else:
        lines.append("PENDING DECISIONS\n  No In Progress items in Linear.")

    # --- TRADING ---
    lines.append("")
    if trading:
        lines.append("TRADING")
        for tline in trading.split("\n"):
            lines.append(f"  {tline}")
    else:
        lines.append("TRADING\n  No position data available.")

    # --- CALENDAR ---
    lines.append("")
    lines.append("Check Zoho Calendar for today's schedule.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_briefing() -> dict:
    """Compose and send the daily briefing via iMessage."""
    logger.info("Generating daily briefing...")

    emails = get_new_emails_since(hours=24)
    bids = get_bid_deadlines()
    decisions = get_pending_decisions()
    trading = get_trading_summary()

    briefing_text = format_briefing(emails, bids, decisions, trading)

    # Send via iMessage webhook
    url = os.environ.get("IMESSAGE_WEBHOOK_URL", "http://localhost:8098/send")
    phone = os.environ.get("OWNER_PHONE_NUMBER", "")

    if not phone:
        logger.error("OWNER_PHONE_NUMBER not set — cannot send briefing")
        return {"status": "error", "reason": "no_phone_number"}

    try:
        resp = requests.post(
            url,
            json={"to": phone, "message": briefing_text},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Daily briefing sent to Matthew")
        return {"status": "sent", "sections": {
            "emails": len(emails),
            "bids": len(bids),
            "decisions": len(decisions),
            "trading": bool(trading),
        }}
    except Exception as e:
        logger.error("Failed to send briefing: %s", e)
        return {"status": "error", "reason": str(e)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = send_briefing()
    print(json.dumps(result, indent=2))
