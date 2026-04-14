"""
Intel Briefing — Matt's daily morning report via iMessage.

Pulls live data from:
  - Redis portfolio:snapshot (position syncer)
  - Redis portfolio:history (24h comparison)
  - Polymarket data API (fallback if Redis empty)
  - x-intake queue stats (signal scorecard)
  - Cortex /api/goals (goal progress)
  - emails.db (new emails last 24h)
  - follow_ups.db (due today / overdue)
  - jobs.db (active jobs)

Sends via notification-hub POST /api/send with channel=imessage.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("openclaw.intel_briefing")

_REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/app"))
REDIS_URL = os.environ.get(
    "REDIS_URL",
    "redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379",
)
NOTIFICATION_HUB = os.environ.get(
    "NOTIFICATION_HUB_URL",
    "http://notification-hub:8095",
)
CORTEX_URL = os.environ.get("CORTEX_URL", "http://cortex:8102")
X_INTAKE_URL = os.environ.get("X_INTAKE_URL", "http://x-intake:8101")
POLYMARKET_WALLET = os.environ.get(
    "POLYMARKET_WALLET",
    "0xa791E3090312981A1E18ed93238e480a03E7C0d2",
)
OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "")

# DB paths — container vs host fallback
EMAILS_DB = os.environ.get("EMAIL_DB_PATH", "")
FOLLOW_UPS_DB = os.environ.get("FOLLOW_UPS_DB_PATH", "")
JOBS_DB = os.environ.get("JOBS_DB_PATH", "")

_DB_SEARCH_DIRS = [
    Path("/data"),
    _REPO_ROOT / "data" / "openclaw",
    _REPO_ROOT / "data" / "email-monitor",
    _REPO_ROOT / "data",
    Path.home() / "AI-Server" / "data" / "openclaw",
    Path.home() / "AI-Server" / "data" / "email-monitor",
]


def _find_db(name: str, env_override: str) -> Optional[Path]:
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p
    for d in _DB_SEARCH_DIRS:
        p = d / name
        if p.exists():
            return p
    return None


# ── Redis helper ──────────────────────────────────────────────────────────────

def _redis_get(key: str) -> Optional[str]:
    try:
        import redis as _redis
        r = _redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        return r.get(key)
    except Exception:
        return None


def _redis_lrange(key: str, start: int, end: int) -> list[str]:
    try:
        import redis as _redis
        r = _redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        return r.lrange(key, start, end) or []
    except Exception:
        return []


# ── Data collectors ───────────────────────────────────────────────────────────

def _get_portfolio_snapshot() -> dict[str, Any]:
    """Get current portfolio from Redis or Polymarket API fallback."""
    raw = _redis_get("portfolio:snapshot")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass

    # Fallback: Polymarket data API
    try:
        url = f"https://data-api.polymarket.com/positions?user={POLYMARKET_WALLET}&sizeThreshold=0"
        resp = requests.get(url, timeout=10)
        positions = resp.json()
        total_value = sum(float(p.get("currentValue", 0)) for p in positions)
        active = [p for p in positions if float(p.get("currentValue", 0)) >= 0.50]
        return {
            "total_position_value": round(total_value, 2),
            "usdc_balance": 0,
            "total_portfolio_value": round(total_value, 2),
            "raw_count": len(positions),
            "active_count": len(active),
            "source": "polymarket_api",
        }
    except Exception as exc:
        logger.warning("portfolio_fetch_failed error=%s", str(exc)[:80])
        return {}


def _get_24h_pnl() -> dict[str, Any]:
    """Compare oldest snapshot in history to current for 24h P&L."""
    history = _redis_lrange("portfolio:history", 0, 288)  # 5-min intervals * 24h = 288
    if len(history) < 2:
        return {"available": False}
    try:
        current = json.loads(history[0])
        oldest = json.loads(history[-1])
        cur_val = float(current.get("total_portfolio_value", 0))
        old_val = float(oldest.get("total_portfolio_value", 0))
        delta = cur_val - old_val
        pct = (delta / old_val * 100) if old_val > 0 else 0
        return {
            "available": True,
            "current_value": cur_val,
            "value_24h_ago": old_val,
            "delta": round(delta, 2),
            "delta_pct": round(pct, 1),
        }
    except Exception:
        return {"available": False}


def _get_stale_positions() -> list[dict]:
    """Find positions approaching the 14-day auto-exit (Z5 rule)."""
    try:
        url = f"https://data-api.polymarket.com/activity?user={POLYMARKET_WALLET}&limit=500&offset=0"
        resp = requests.get(url, timeout=15)
        activities = resp.json()

        # Find first buy date per market
        market_first_buy: dict[str, str] = {}
        for a in activities:
            if a.get("type") in ("BUY", "buy"):
                slug = a.get("slug") or a.get("market_slug") or ""
                ts = a.get("timestamp") or a.get("createdAt") or ""
                if slug and ts:
                    if slug not in market_first_buy or ts < market_first_buy[slug]:
                        market_first_buy[slug] = ts

        now = datetime.now(timezone.utc)
        stale = []
        for slug, first_ts in market_first_buy.items():
            try:
                buy_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                age_days = (now - buy_dt).days
                if age_days >= 10:  # Alert at 10+ days (auto-exit at 14)
                    stale.append({"slug": slug, "age_days": age_days, "first_buy": first_ts[:10]})
            except Exception:
                pass
        stale.sort(key=lambda x: x["age_days"], reverse=True)
        return stale[:5]
    except Exception:
        return []


def _get_x_intake_stats() -> dict[str, Any]:
    """Get x-intake signal queue stats."""
    try:
        resp = requests.get(f"{X_INTAKE_URL}/queue/stats", timeout=5)
        return resp.json()
    except Exception:
        return {}


def _get_x_intake_recent_signals(limit: int = 5) -> list[dict]:
    """Get recent high-value x-intake signals."""
    try:
        resp = requests.get(f"{X_INTAKE_URL}/queue?status=auto_approved&limit={limit}", timeout=5)
        data = resp.json()
        return data.get("items", [])[:limit]
    except Exception:
        return []


def _get_new_emails(hours: int = 24) -> int:
    """Count new emails in the last N hours."""
    db_path = _find_db("emails.db", EMAILS_DB)
    if not db_path:
        return -1
    try:
        conn = sqlite3.connect(str(db_path))
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE received_at >= ?", (cutoff,)
        ).fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


def _get_follow_ups_due() -> list[dict]:
    """Get follow-ups that are due today or overdue."""
    db_path = _find_db("follow_ups.db", FOLLOW_UPS_DB)
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT * FROM follow_ups WHERE next_date <= ? AND status = 'pending' ORDER BY next_date LIMIT 10",
            (today,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_active_jobs() -> int:
    """Count active jobs."""
    db_path = _find_db("jobs.db", JOBS_DB)
    if not db_path:
        return -1
    try:
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('active', 'in_progress', 'proposal', 'negotiation')"
        ).fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


def _get_cortex_goals() -> list[dict]:
    """Get active goals from Cortex."""
    try:
        resp = requests.get(f"{CORTEX_URL}/api/goals", timeout=5)
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("goals", [])
    except Exception:
        return []


# ── Compose ───────────────────────────────────────────────────────────────────

def compose_intel_briefing() -> str:
    """Build the full intelligence briefing text."""
    now_mt = datetime.now()
    date_str = now_mt.strftime("%A, %B %d")
    lines = [f"DAILY INTEL — {date_str}\n"]

    # ── TRADING ──
    snap = _get_portfolio_snapshot()
    pnl_24h = _get_24h_pnl()

    lines.append("TRADING")
    if snap:
        total_val = snap.get("total_position_value", 0)
        usdc = snap.get("usdc_balance", 0)
        portfolio = snap.get("total_portfolio_value", total_val + usdc)
        pos_count = snap.get("raw_count", snap.get("active_count", "?"))
        lines.append(f"  Portfolio: ${portfolio:.2f}")
        lines.append(f"  Positions: {pos_count} | USDC: ${usdc:.2f}")

        # Category breakdown if available
        active_val = snap.get("active_value")
        redeemable_val = snap.get("redeemable_value")
        if active_val is not None:
            lines.append(f"  Active: ${active_val:.2f} | Redeemable: ${redeemable_val:.2f}")

        if pnl_24h.get("available"):
            delta = pnl_24h["delta"]
            pct = pnl_24h["delta_pct"]
            sign = "+" if delta >= 0 else ""
            lines.append(f"  24h P&L: {sign}${delta:.2f} ({sign}{pct}%)")
        else:
            lines.append("  24h P&L: insufficient snapshot history")
    else:
        lines.append("  Portfolio data unavailable — check bot status")

    # ── STALE POSITIONS ──
    stale = _get_stale_positions()
    if stale:
        lines.append("")
        lines.append("STALE POSITION ALERT")
        for s in stale:
            days_left = 14 - s["age_days"]
            if days_left <= 0:
                tag = "AUTO-EXIT IMMINENT"
            elif days_left <= 3:
                tag = f"{days_left}d to auto-exit"
            else:
                tag = f"{s['age_days']}d old"
            slug_short = s["slug"][:45] if s["slug"] else "?"
            lines.append(f"  {slug_short} — {tag}")

    # ── X-INTAKE SIGNALS ──
    x_stats = _get_x_intake_stats()
    lines.append("")
    lines.append("X SIGNALS")
    if x_stats and not x_stats.get("error"):
        pending = x_stats.get("pending", 0)
        auto_approved = x_stats.get("auto_approved", 0)
        total = x_stats.get("total", 0)
        lines.append(f"  Total: {total} | Auto-approved: {auto_approved} | Pending review: {pending}")

        if pending > 0:
            lines.append(f"  ** {pending} signals need your review in Cortex dashboard **")
    else:
        lines.append("  X-intake stats unavailable")

    # Top recent signals
    recent_signals = _get_x_intake_recent_signals(3)
    if recent_signals:
        lines.append("  Recent high-value:")
        for sig in recent_signals:
            summary = (sig.get("summary") or sig.get("title") or "?")[:60]
            relevance = sig.get("relevance", "?")
            lines.append(f"    [{relevance}] {summary}")

    # ── GOALS ──
    goals = _get_cortex_goals()
    if goals:
        lines.append("")
        lines.append("GOALS")
        for g in goals[:3]:
            name = g.get("name") or g.get("title") or "?"
            status = g.get("status", "?")
            current = g.get("current", "?")
            target = g.get("target", "?")
            lines.append(f"  {name}: {current}/{target} ({status})")

    # ── BUSINESS ──
    lines.append("")
    lines.append("BUSINESS")

    new_emails = _get_new_emails(24)
    if new_emails >= 0:
        lines.append(f"  New emails (24h): {new_emails}")
    else:
        lines.append("  Email data unavailable")

    followups = _get_follow_ups_due()
    if followups:
        lines.append(f"  Follow-ups due: {len(followups)}")
        for fu in followups[:3]:
            client = fu.get("client_name") or fu.get("project_name") or "Unknown"
            lines.append(f"    - {client}")
    else:
        lines.append("  Follow-ups due: 0")

    active_jobs = _get_active_jobs()
    if active_jobs >= 0:
        lines.append(f"  Active jobs: {active_jobs}")

    lines.append("")
    lines.append("— Bob")

    return "\n".join(lines)


# ── Send ──────────────────────────────────────────────────────────────────────

def send_intel_briefing() -> dict[str, Any]:
    """Compose and send the intel briefing via notification-hub."""
    logger.info("composing_intel_briefing")
    text = compose_intel_briefing()

    # Log to Cortex
    try:
        requests.post(
            f"{CORTEX_URL}/remember",
            json={
                "category": "system",
                "title": "Intel briefing assembled",
                "content": text[:500],
                "source": "intel_briefing",
                "importance": 5,
                "tags": ["briefing", "intel", "daily"],
            },
            timeout=5,
        )
    except Exception:
        pass

    # Send via notification-hub
    try:
        resp = requests.post(
            f"{NOTIFICATION_HUB}/api/send",
            json={
                "recipient": OWNER_PHONE,
                "message": text,
                "channel": "imessage",
                "priority": "normal",
                "message_type": "alert",
                "subject": "Daily Intel Briefing",
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("intel_briefing_sent")
        return {"status": "sent", "length": len(text)}
    except Exception as exc:
        logger.error("intel_briefing_send_failed error=%s", str(exc)[:120])

        # Fallback: try iMessage webhook directly
        try:
            webhook = os.environ.get("IMESSAGE_WEBHOOK_URL", "http://host.docker.internal:8199/send")
            resp2 = requests.post(
                webhook,
                json={"to": OWNER_PHONE, "message": text},
                timeout=15,
            )
            resp2.raise_for_status()
            logger.info("intel_briefing_sent_via_webhook_fallback")
            return {"status": "sent_fallback", "length": len(text)}
        except Exception as exc2:
            logger.error("intel_briefing_fallback_failed error=%s", str(exc2)[:120])
            return {"status": "error", "reason": str(exc)[:200]}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    result = send_intel_briefing()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") in ("sent", "sent_fallback") else 1)
