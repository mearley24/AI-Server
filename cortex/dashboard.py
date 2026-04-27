"""Cortex dashboard routes — ports Mission Control endpoints into Cortex.

This module adds the operational dashboard API onto the existing Cortex FastAPI
app so Cortex can serve the single unified dashboard that replaces Mission
Control. Every proxy is wrapped in try/except with a 5s timeout so a downstream
failure never crashes Cortex.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

TRADING_BOT_URL = os.environ.get("POLYMARKET_BOT_URL", "http://vpn:8430")
EMAIL_MONITOR_URL = os.environ.get("EMAIL_MONITOR_URL", "http://email-monitor:8092")
CALENDAR_AGENT_URL = os.environ.get("CALENDAR_AGENT_URL", "http://calendar-agent:8094")
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://openclaw:3000")
X_INTAKE_URL = os.environ.get("X_INTAKE_URL", "http://x-intake:8101")
VOICE_RECEPTIONIST_URL = os.environ.get(
    "VOICE_RECEPTIONIST_URL", "http://voice-receptionist:3000"
)

# Data paths (mounted read-only by docker-compose into /app/data/openclaw)
FOLLOW_UPS_DB_CANDIDATES = [
    Path("/app/data/openclaw/follow_ups.db"),
    Path("/data/openclaw/follow_ups.db"),
    Path("data/openclaw/follow_ups.db"),
]
DECISION_JOURNAL_DB_CANDIDATES = [
    Path("/app/data/openclaw/decision_journal.db"),
    Path("/data/openclaw/decision_journal.db"),
    Path("data/openclaw/decision_journal.db"),
]

X_INTAKE_DB_CANDIDATES = [
    Path("/app/data/x_intake/queue.db"),
    Path("/data/x_intake/queue.db"),
    Path("data/x_intake/queue.db"),
]

AUDIO_INTAKE_DB_CANDIDATES = [
    Path("/app/data/audio_intake/queue.db"),
    Path("/data/audio_intake/queue.db"),
    Path("data/audio_intake/queue.db"),
]

TRANSCRIPT_DIR_CANDIDATES = [
    Path("/app/data/transcripts"),
    Path("/data/transcripts"),
    Path("data/transcripts"),
]

# Senders that are NOT real client follow-ups — vendors, newsletters, automated systems.
# Matched case-insensitively against client_name OR client_email.
FOLLOWUP_NOISE_SENDERS = {
    "somfy", "control4", "autodesk", "phoenix marketing", "screen innovations",
    "shade innovations", "cablewholesale", "ups", "zapier", "the futurist",
    "linq", "snapone", "snap one", "netlify", "hiscox", "vyde",
    "d-tools", "billing", "no-reply", "noreply", "mailer-daemon",
    "donotreply", "do-not-reply", "unsubscribe",
    "symphony.placeholder", "pending+",
    # Internal Symphony addresses — self-emails / notification bots are not client follow-ups
    "symphonysh.com",
}

# Subject patterns that indicate automated/marketing emails (case-insensitive substrings)
FOLLOWUP_NOISE_SUBJECTS = {
    "webinar", "unsubscribe", "newsletter", "recommended for you",
    "your order", "credit memo", "payment received", "your shipment",
    "trial has ended", "financial report", "see your business insights",
    "sandbox", "new properties recommended",
}


def _is_followup_noise(followup: dict) -> bool:
    """Return True if a follow-up entry looks like vendor/marketing noise."""
    name = (followup.get("client_name") or "").lower()
    email = (followup.get("client_email") or "").lower()
    subject = (followup.get("last_client_subject") or "").lower()

    for noise in FOLLOWUP_NOISE_SENDERS:
        if noise in name or noise in email:
            return True
    for noise in FOLLOWUP_NOISE_SUBJECTS:
        if noise in subject:
            return True
    return False


STATIC_DIR = Path(__file__).parent / "static"

# ── Tool access registry ─────────────────────────────────────────────────────
#
# Single source of truth for tool links surfaced on the dashboard tabs.
# Edit port / tab / notes here; the frontend reads this via /api/tools.
#
# Tailscale identifiers for Bob (set 2026-04-24):
#   IP:         100.89.1.51
#   MagicDNS:   bobs-mac-mini.tailbcf3fe.ts.net
#
# Ports are verified against PORTS.md on 2026-04-24. Entries whose port is
# not yet documented are marked status="unknown" so the UI can render them
# without implying they're reachable.
BOB_TAILSCALE_IP = "100.89.1.51"
BOB_TAILSCALE_FQDN = "bobs-mac-mini.tailbcf3fe.ts.net"


def _tool(name: str, port: int | None, tab: str, category: str, *,
          health_path: str | None = None, local_path: str = "/",
          notes: str = "", status: str = "ok") -> dict:
    """Build a tool registry entry.

    ``status="ok"``         — port is documented in PORTS.md
    ``status="unknown"``    — port / reachability not yet verified
    ``status="lan_only"``   — host-bound service, LAN not Tailscale
    """
    entry: dict[str, Any] = {
        "name": name,
        "tab": tab,
        "category": category,
        "port": port,
        "status": status,
        "notes": notes,
    }
    if port is not None:
        entry["local_url"] = f"http://127.0.0.1:{port}{local_path}"
        entry["tailscale_url"] = f"http://{BOB_TAILSCALE_IP}:{port}{local_path}"
        entry["tailscale_fqdn_url"] = (
            f"http://{BOB_TAILSCALE_FQDN}:{port}{local_path}"
        )
        if health_path:
            entry["health_url"] = f"http://127.0.0.1:{port}{health_path}"
    else:
        entry["local_url"] = None
        entry["tailscale_url"] = None
        entry["tailscale_fqdn_url"] = None
    return entry


# Tabs match the dashboard tab IDs: overview, xintake, symphony, autonomy
TOOL_REGISTRY: list[dict[str, Any]] = [
    # Overview tab — core Cortex + central services
    _tool("Cortex Dashboard", 8102, "overview", "Core AI",
          health_path="/health", local_path="/dashboard",
          notes="Brain, memory, dashboard. Bound 127.0.0.1:8102 (Docker "
                "loopback); direct Tailscale URL requires `tailscale serve` "
                "or SSH tunnel — the prior *:8102 wildcard was the host "
                "file-watcher agent, rebound to 127.0.0.1:8103 on 2026-04-24.",
          status="lan_only"),
    _tool("OpenClaw", 8099, "overview", "Core AI",
          health_path="/health",
          notes="Central LLM orchestration + routing. Docker-bound "
                "127.0.0.1:8099 — Tailscale URL needs `tailscale serve`.",
          status="lan_only"),
    _tool("Cortex Autobuilder", 8115, "overview", "Core AI",
          health_path="/health",
          notes="Bob/Betty research loop + topic scanning. Docker-bound "
                "127.0.0.1:8115 — Tailscale URL needs `tailscale serve`.",
          status="lan_only"),

    # X Intake tab
    _tool("X Intake", 8101, "xintake", "Intelligence",
          health_path="/health",
          notes="X/Twitter link analysis + bookmarks queue. Docker-bound "
                "127.0.0.1:8101 — Tailscale URL needs `tailscale serve`.",
          status="lan_only"),

    # Symphony Ops tab — business / communication tools
    _tool("Markup Tool", 8088, "symphony", "Business",
          local_path="/",
          notes="Local markup utility. Bound 127.0.0.1 — reachable on Bob "
                "host; Tailscale URL only works if `tailscale serve` "
                "publishes :8088.",
          status="lan_only"),
    _tool("BlueBubbles", 1234, "symphony", "Communication",
          health_path="/api/v1/server/info",
          notes="iMessage bridge. Host service bound to all interfaces "
                "(LAN-accessible)."),
    _tool("Proposals", 8091, "symphony", "Business",
          health_path="/health",
          notes="Symphony proposal generation engine. Docker-bound "
                "127.0.0.1:8091 — Tailscale URL needs `tailscale serve`.",
          status="lan_only"),
    _tool("iMessage Bridge", 8199, "symphony", "Communication",
          health_path="/health",
          notes="Two-way message bridge health/API. Bound 127.0.0.1.",
          status="lan_only"),
    _tool("Voice Receptionist", 8093, "symphony", "Communication",
          health_path="/health",
          notes="Bob the Conductor — Twilio + OpenAI Realtime voice "
                "receptionist. Container 3000 → host 127.0.0.1:8093. "
                "Inbound call flow: Twilio → /incoming-call → WebSocket. "
                "Already publishes ops:voice_followup → Linear (see "
                "operations/linear_ops.py). Cortex call/transcript "
                "ingestion not yet wired — see docs/TAILSCALE_ACCESS.md "
                "and voice_receptionist/README.md.",
          status="lan_only"),

    # Autonomy tab — control plane / ops adjacent
    _tool("Notification Hub", 8095, "autonomy", "Infrastructure",
          health_path="/health",
          notes="Alert routing and delivery. Docker-bound 127.0.0.1:8095 — "
                "Tailscale URL needs `tailscale serve`.",
          status="lan_only"),
    _tool("Intel Feeds", 8765, "autonomy", "Intelligence",
          health_path="/health",
          notes="News, Reddit, Polymarket monitors. Docker-bound "
                "127.0.0.1:8765 — Tailscale URL needs `tailscale serve`.",
          status="lan_only"),

    # Mobile gateway — not yet confirmed in PORTS.md; surface as unknown
    _tool("Mobile Gateway", None, "overview", "Infrastructure",
          notes="Mobile gateway not documented in PORTS.md on 2026-04-24. "
                "Update TOOL_REGISTRY in cortex/dashboard.py when port is "
                "finalized.",
          status="unknown"),
]

# Service map — ports updated for current stack (notification-hub=8095,
# proposals=8091, no mission-control entry since cortex IS the dashboard)
SERVICES: list[dict[str, Any]] = [
    {"name": "OpenClaw", "host": "openclaw", "port": 3000, "ext_port": 8099},
    {"name": "Email Monitor", "host": "email-monitor", "port": 8092, "ext_port": 8092},
    {"name": "Notification Hub", "host": "notification-hub", "port": 8095, "ext_port": 8095},
    {"name": "Proposals", "host": "proposals", "port": 8091, "ext_port": 8091},
    {"name": "Calendar Agent", "host": "calendar-agent", "port": 8094, "ext_port": 8094},
    {"name": "Voice Receptionist", "host": "voice-receptionist", "port": 3000, "ext_port": 8093},
    {"name": "ClawWork", "host": "clawwork", "port": 8097, "ext_port": 8097, "optional": True},
    {"name": "D-Tools Bridge", "host": "dtools-bridge", "port": 5050, "ext_port": 8096},
    {"name": "Client Portal", "host": "client-portal", "port": 8096, "ext_port": None, "optional": True},
    {"name": "Polymarket Bot", "host": "vpn", "port": 8430, "ext_port": 8430},
    {"name": "X Intake", "host": "x-intake", "port": 8101, "ext_port": 8101, "optional": True},
    {"name": "Intel Feeds", "host": "intel-feeds", "port": 8765, "ext_port": 8765, "optional": True},
    {"name": "Cortex Autobuilder", "host": "cortex-autobuilder", "port": 8115, "ext_port": 8115, "optional": True},
]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _safe_get(url: str, timeout: float = 5.0) -> Any:
    """GET url with short timeout; return parsed JSON or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return {"text": resp.text[:500]}
            return None
    except Exception as exc:
        logger.debug("dashboard_proxy_fail url=%s error=%s", url, exc)
        return None


async def _check_service_health(service: dict) -> dict:
    """Check a single service's /health endpoint; return a status dict."""
    url = f"http://{service['host']}:{service['port']}/health"
    name = service["name"]
    ext_port = service.get("ext_port")  # may be None for internal-only services
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                details = resp.json() if "json" in ct else {}
                return {
                    "name": name,
                    "status": "healthy",
                    "port": ext_port,
                    "details": details,
                    "optional": bool(service.get("optional")),
                }
            return {
                "name": name,
                "status": "degraded",
                "port": ext_port,
                "details": {"http_status": resp.status_code},
                "optional": bool(service.get("optional")),
            }
    except Exception:
        return {
            "name": name,
            "status": "down",
            "port": ext_port,
            "details": {},
            "optional": bool(service.get("optional")),
        }


def _parse_zoho_datetime(raw: str):
    """Parse a Zoho Calendar datetime string to a naive local datetime (or None).

    Zoho returns compact strings like ``20260412T080000Z`` (yyyyMMddTHHmmssZ)
    *or* standard ISO-8601 like ``2026-04-12T08:00:00+00:00``.
    Both forms are handled; timezone info is stripped (we treat times as local).
    """
    if not raw:
        return None
    s = raw.strip()
    try:
        # Compact Zoho with time: "20260412T080000Z" or "20260412T080000+0530"
        if len(s) >= 15 and "T" in s and s[:8].isdigit() and "-" not in s[:8]:
            # Drop trailing Z / timezone offset
            base = s.split("+")[0].rstrip("Zz")  # → "20260412T080000"
            date_part = base[:8]   # "20260412"
            time_part = base[9:15] # "080000"
            return datetime(
                int(date_part[0:4]), int(date_part[4:6]), int(date_part[6:8]),
                int(time_part[0:2]), int(time_part[2:4]), int(time_part[4:6]),
            )
        # Compact all-day: "20260412"
        if len(s) == 8 and s.isdigit():
            return datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        pass
    # Standard ISO — strip timezone suffix then parse
    try:
        clean = s.split("+")[0].rstrip("Zz")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def _normalize_calendar_event(event: dict) -> dict:
    """Flatten a raw Zoho Calendar event into a clean shape for the dashboard.

    Zoho nests the start/end times inside ``dateandtime.start`` and uses a
    compact non-ISO date format.  This function extracts a human-readable
    ``start_display`` string and normalises the other fields the tile needs.
    """
    title = (event.get("title") or event.get("summary") or "").strip() or "(no title)"

    dt_block = event.get("dateandtime") or {}
    start_raw = dt_block.get("start") or event.get("start") or ""

    # All-day: Zoho sets isallday == "true" OR start has no time component
    is_all_day = str(event.get("isallday", "")).lower() in ("true", "1", "yes")
    if not is_all_day and start_raw:
        # Date-only compact ("20260412") or ISO date ("2026-04-12") with no T
        is_all_day = "T" not in start_raw and len(start_raw.strip()) <= 10

    is_recurring = bool(
        event.get("recurrence") or event.get("rrule") or event.get("recurring")
    )

    dt_obj = _parse_zoho_datetime(start_raw)

    start_iso = ""
    start_display = ""
    if dt_obj is not None:
        start_iso = dt_obj.isoformat()
        today = datetime.now().date()
        if dt_obj.date() == today:
            start_display = "today, all day" if is_all_day else dt_obj.strftime("%-I:%M %p")
        else:
            day_str = dt_obj.strftime("%-m/%-d")
            start_display = f"{day_str} all day" if is_all_day else dt_obj.strftime("%-m/%-d %-I:%M %p")
    elif start_raw:
        # Fallback: surface raw string rather than showing nothing
        start_display = start_raw

    # Surface a brief description/notes snippet if present (max 80 chars)
    description = (event.get("description") or event.get("notes") or "").strip()
    desc_snippet = description[:80] if description else ""

    return {
        "title": title,
        "start": start_iso,
        "start_display": start_display,
        "is_all_day": is_all_day,
        "is_recurring": is_recurring,
        "uid": event.get("uid") or "",
        "description": desc_snippet,
    }


def _find_db(candidates: list[Path]) -> Path | None:
    """Return the first candidate DB file that exists on disk."""
    for path in candidates:
        if path.exists():
            return path
    return None


def _get_redis_sync():
    """Return a synchronous Redis client (for simple LRANGE/GET calls)."""
    try:
        import redis

        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        return redis.from_url(url, decode_responses=True, socket_timeout=2)
    except Exception as exc:
        logger.debug("redis_connect_fail error=%s", exc)
        return None


# ── Route registration ──────────────────────────────────────────────────────


def register_dashboard_routes(app: FastAPI, engine_ref) -> None:
    """Attach dashboard routes to the Cortex FastAPI app.

    ``engine_ref`` is a zero-arg callable returning the live ``CortexEngine``
    instance (so routes pick up the engine after startup).
    """

    # Static files and the dashboard page itself
    if STATIC_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static",
        )

    @app.get("/dashboard")
    async def dashboard_page():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path))
        return {"error": "dashboard not built"}

    @app.get("/")
    async def root():
        return RedirectResponse("/dashboard")

    # ── /api/tools — intentional tool access registry ───────────────────
    @app.get("/api/tools")
    async def api_tools(tab: str = ""):
        """Return the tool access registry, optionally filtered by tab.

        This is the single source of truth for "how do I reach tool X from
        Bob or from Tailscale." Frontend renders the appropriate entries
        on each tab. When a port changes, edit TOOL_REGISTRY in
        cortex/dashboard.py — no frontend change required.
        """
        items = TOOL_REGISTRY
        if tab:
            items = [t for t in items if t.get("tab") == tab]
        return {
            "tools": items,
            "count": len(items),
            "tailscale": {
                "ip": BOB_TAILSCALE_IP,
                "fqdn": BOB_TAILSCALE_FQDN,
            },
        }

    # ── /api/services ───────────────────────────────────────────────────
    @app.get("/api/services")
    async def api_services():
        results = await asyncio.gather(
            *[_check_service_health(s) for s in SERVICES]
        )
        now = datetime.now().isoformat()
        for r in results:
            r["checked_at"] = now
        core = [r for r in results if not r.get("optional")]
        optional = [r for r in results if r.get("optional")]
        healthy = sum(1 for r in results if r["status"] == "healthy")
        healthy_core = sum(1 for r in core if r["status"] == "healthy")
        healthy_optional = sum(1 for r in optional if r["status"] == "healthy")
        return {
            "services": results,
            "total": len(results),
            "healthy": healthy,
            "total_core": len(core),
            "healthy_core": healthy_core,
            "optional_total": len(optional),
            "optional_healthy": healthy_optional,
        }

    # ── Polymarket bot proxies ──────────────────────────────────────────
    @app.get("/api/wallet")
    async def api_wallet():
        empty = {
            "usdc_balance": 0.0,
            "position_value": 0.0,
            "active_value": 0.0,
            "redeemable_value": 0.0,
            "redeemable_count": 0,
            "lost_count": 0,
            "dust_count": 0,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "error": "unavailable",
        }
        # Prefer Redis snapshot (already computed by the bot)
        r = _get_redis_sync()
        if r is not None:
            try:
                snap = r.get("portfolio:snapshot")
                if snap:
                    data = json.loads(snap)
                    for key in (
                        "active_value",
                        "redeemable_value",
                        "redeemable_count",
                        "lost_count",
                        "dust_count",
                    ):
                        data.setdefault(key, 0)
                    # Pass snapshot timestamp so UI can show staleness
                    snap_ts = (
                        data.get("timestamp")
                        or data.get("updated_at")
                        or data.get("ts")
                    )
                    data["snapshot_age"] = snap_ts
                    return data
            except Exception:
                pass
        # Fall back to live bot — /status has USDC nested under strategies.redeemer
        data = await _safe_get(f"{TRADING_BOT_URL}/status", timeout=5.0)
        if data:
            try:
                redeemer_section = (data.get("strategies") or {}).get("redeemer") or {}
                usdc = float(
                    data.get("usdc_balance")
                    or redeemer_section.get("usdc_balance")
                    or 0
                )
                matic = float(redeemer_section.get("matic_balance") or 0)
                redeemed = int(redeemer_section.get("redeemed_conditions") or 0)
                pending = int((redeemer_section.get("last_cycle_summary") or {}).get("pending") or 0)
                redeemer_ts = redeemer_section.get("last_cycle_at")
                snap_ts = redeemer_ts if redeemer_ts else None
                if snap_ts:
                    from datetime import datetime as _dt
                    snap_ts = _dt.fromtimestamp(snap_ts, tz=timezone.utc).isoformat()
                return {
                    "usdc_balance": usdc,
                    "matic_balance": matic,
                    "position_value": float(data.get("position_value", 0)),
                    "active_value": float(data.get("active_value", 0)),
                    "redeemable_value": float(data.get("redeemable_value", 0)),
                    "redeemable_count": redeemed,
                    "pending_count": pending,
                    "lost_count": int(data.get("lost_count", 0)),
                    "dust_count": int(data.get("dust_count", 0)),
                    "daily_pnl": float(data.get("daily_pnl", 0)),
                    "weekly_pnl": float(data.get("weekly_pnl", 0)),
                    "snapshot_age": snap_ts,
                    "source": "bot_status",
                    "source_type": "real",
                }
            except (TypeError, ValueError):
                pass
        # Third fallback — query Polymarket data API directly (public, no auth)
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        positions_data = await _safe_get(
            f"https://data-api.polymarket.com/positions?user={poly_wallet}&sizeThreshold=0",
            timeout=10.0,
        )
        if positions_data and isinstance(positions_data, list):
            try:
                total_value = sum(float(p.get("currentValue", 0)) for p in positions_data)
                total_initial = sum(float(p.get("initialValue", 0) or 0) for p in positions_data)
                active_value = sum(
                    float(p.get("currentValue", 0))
                    for p in positions_data
                    if 0.05 < float(p.get("curPrice", p.get("currentPrice", 0)) or 0) < 0.95
                )
                return {
                    "usdc_balance": 0.0,  # can't get USDC from data API
                    "position_value": round(total_value, 2),
                    "active_value": round(active_value, 2),
                    "redeemable_value": 0.0,
                    "redeemable_count": 0,
                    "lost_count": 0,
                    "dust_count": sum(1 for p in positions_data if float(p.get("currentValue", 0)) < 0.50),
                    "daily_pnl": 0.0,
                    "weekly_pnl": 0.0,
                    "source": "polymarket_data_api",
                    "position_count": len(positions_data),
                    "unrealized_pnl": round(total_value - total_initial, 2),
                }
            except (TypeError, ValueError):
                pass
        return empty

    @app.get("/api/positions")
    async def api_positions():
        r = _get_redis_sync()
        if r is not None:
            try:
                raw = r.get("portfolio:positions")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        data = await _safe_get(f"{TRADING_BOT_URL}/positions", timeout=5.0)
        if data is not None:
            if isinstance(data, list):
                return data
            return data.get("positions", [])
        # Third fallback — Polymarket data API
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        positions_data = await _safe_get(
            f"https://data-api.polymarket.com/positions?user={poly_wallet}&sizeThreshold=0",
            timeout=10.0,
        )
        if positions_data and isinstance(positions_data, list):
            return [
                {
                    "title": p.get("title", "?"),
                    "outcome": p.get("outcome", "?"),
                    "size": float(p.get("size", 0)),
                    "currentValue": float(p.get("currentValue", 0)),
                    "curPrice": float(p.get("curPrice", p.get("currentPrice", 0)) or 0),
                    "source": "polymarket_data_api",
                }
                for p in sorted(positions_data, key=lambda x: float(x.get("currentValue", 0)), reverse=True)
                if float(p.get("currentValue", 0)) > 0.01
            ]
        return []

    @app.get("/api/polymarket/exposure")
    async def api_polymarket_exposure():
        """Structured on-chain Polymarket positions for the exposure dashboard tile.

        Fetches live positions from the public Polymarket data API (no auth needed).
        Returns masked wallet, all positions sorted by value, top winners/losers,
        and summary stats. Read-only — does not place or modify any orders.
        """
        poly_wallet = os.environ.get(
            "POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2"
        )
        masked = f"{poly_wallet[:6]}...{poly_wallet[-4:]}" if len(poly_wallet) >= 10 else "***"
        empty = {
            "wallet": masked,
            "position_count": 0,
            "cost_basis": 0.0,
            "current_value": 0.0,
            "unrealized_pnl": 0.0,
            "positions": [],
            "top_winners": [],
            "top_losers": [],
            "source": "unavailable",
            "fetched_at": None,
            "error": "unavailable",
        }
        raw = await _safe_get(
            f"https://data-api.polymarket.com/positions"
            f"?user={poly_wallet}&sizeThreshold=0.001&limit=500",
            timeout=12.0,
        )
        if not raw or not isinstance(raw, list):
            return empty

        positions = []
        for p in raw:
            try:
                market = (p.get("title") or p.get("market") or "Unknown")
                outcome = p.get("outcome", p.get("side", "?"))
                shares = float(p.get("size", p.get("shares", 0)) or 0)
                avg_price = float(
                    p.get("avgPrice", p.get("avg_price", p.get("avg", 0))) or 0
                )
                cur_price = float(
                    p.get("curPrice", p.get("currentPrice", p.get("price", 0))) or 0
                )
                value = round(shares * cur_price, 4)
                cost = round(shares * avg_price, 4)
                pnl = round(value - cost, 4)
                positions.append({
                    "market": market,
                    "outcome": outcome,
                    "shares": round(shares, 4),
                    "avg_price": avg_price,
                    "current_price": cur_price,
                    "value": value,
                    "pnl": pnl,
                })
            except (TypeError, ValueError):
                continue

        positions.sort(key=lambda x: x["value"], reverse=True)
        winners = sorted(positions, key=lambda x: x["pnl"], reverse=True)[:5]
        losers = sorted(positions, key=lambda x: x["pnl"])[:5]
        total_value = round(sum(p["value"] for p in positions), 2)
        total_cost = round(sum(p["shares"] * p["avg_price"] for p in positions), 2)

        from datetime import datetime, timezone
        return {
            "wallet": masked,
            "position_count": len(positions),
            "cost_basis": total_cost,
            "current_value": total_value,
            "unrealized_pnl": round(total_value - total_cost, 2),
            "positions": positions,
            "top_winners": winners,
            "top_losers": losers,
            "source": "live_api",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/pnl-series")
    async def api_pnl_series():
        r = _get_redis_sync()
        if r is not None:
            try:
                raw = r.get("portfolio:pnl_series")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return []

    @app.get("/api/pnl-summary")
    async def api_pnl_summary():
        """Realized P&L from Polymarket activity API (public, no auth needed)."""
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        try:
            all_activity = []
            for offset in range(0, 5001, 500):
                data = await _safe_get(
                    f"https://data-api.polymarket.com/activity?user={poly_wallet}&limit=500&offset={offset}",
                    timeout=15.0,
                )
                if not data or not isinstance(data, list) or len(data) == 0:
                    break
                all_activity.extend(data)
                if len(data) < 500:
                    break

            total_spent = sum(float(a.get("usdcSize", 0)) for a in all_activity if a.get("type") in ("TRADE", "BUY"))
            total_redeemed = sum(float(a.get("usdcSize", 0)) for a in all_activity if a.get("type") == "REDEEM")
            trade_count = sum(1 for a in all_activity if a.get("type") in ("TRADE", "BUY"))
            redeem_count = sum(1 for a in all_activity if a.get("type") == "REDEEM")

            return {
                "total_spent": round(total_spent, 2),
                "total_redeemed": round(total_redeemed, 2),
                "realized_pnl": round(total_redeemed - total_spent, 2),
                "trade_count": trade_count,
                "redeem_count": redeem_count,
                "activity_count": len(all_activity),
            }
        except Exception as exc:
            return {"error": str(exc)[:200]}

    # Noise event types that don't represent human-relevant activity
    _ACTIVITY_NOISE_TYPES = frozenset({
        "health.checked", "health.check",
        "jobs.synced",     # D-Tools automation ticks
        "heartbeat",       # bot keepalive pings
        "tick",            # generic strategy ticks
    })

    def _is_activity_noise(event: dict) -> bool:
        p = event.get("payload") or event
        t = (p.get("type") or event.get("kind") or "").lower()
        return t in _ACTIVITY_NOISE_TYPES

    @app.get("/api/activity")
    async def api_activity(debug: bool = Query(False)):
        """Last 50 entries from Redis events:log.

        In normal mode (debug=false) noise events (health checks, sync ticks,
        heartbeats) are removed before capping at 50 — so the feed shows
        human-relevant events only. Debug mode returns the raw feed.
        """
        r = _get_redis_sync()
        raw: list[dict] = []
        if r is not None:
            try:
                # Fetch more raw entries so filtering doesn't starve the result
                fetch_count = 50 if debug else 200
                entries = r.lrange("events:log", 0, fetch_count - 1)
                if entries:
                    for entry in entries:
                        try:
                            raw.append(json.loads(entry))
                        except Exception:
                            raw.append({"timestamp": "", "type": "info", "message": str(entry)})
            except Exception as exc:
                logger.debug("activity_redis_fail error=%s", exc)
        if not raw and r is not None:
            try:
                entries = r.lrange("events:trading", 0, 49)
                raw = [json.loads(e) if isinstance(e, str) else e for e in entries]
            except Exception:
                pass
        if debug:
            return raw[:50]
        filtered = [e for e in raw if not _is_activity_noise(e)]
        return (filtered if filtered else raw)[:50]

    @app.get("/api/trading")
    async def api_trading():
        data = await _safe_get(f"{TRADING_BOT_URL}/status", timeout=5.0)
        if data is None:
            return {"error": "service unavailable"}
        return data

    @app.get("/api/trading/categories")
    async def api_trading_categories():
        data = await _safe_get(f"{TRADING_BOT_URL}/categories", timeout=5.0)
        if data is None:
            return {"error": "service unavailable", "categories": {}}
        return data

    @app.get("/api/trading/positions")
    async def api_trading_positions():
        data = await _safe_get(f"{TRADING_BOT_URL}/positions", timeout=5.0)
        if data is None:
            return {"error": "service unavailable", "positions": []}
        return data

    @app.get("/api/trading/intel")
    async def api_trading_intel():
        """X-intel signal summary from the bot."""
        data = await _safe_get(f"{TRADING_BOT_URL}/x-intel/status", timeout=5.0)
        if data:
            return data
        return {"active_signals": 0, "market_boosts": 0, "status": "unavailable"}

    # ── Email / calendar / follow-ups ──────────────────────────────────
    @app.get("/api/emails")
    async def api_emails():
        from datetime import timedelta
        for path in ("/emails", "/emails/recent", "/api/emails"):
            data = await _safe_get(f"{EMAIL_MONITOR_URL}{path}")
            if data is None:
                continue
            emails = (
                data
                if isinstance(data, list)
                else data.get("emails", data.get("recent", []))
            )
            # Only surface emails from the last 7 days — dashboard shows
            # what needs attention now, not historical inbox state.
            seven_days_ago = (
                datetime.now(timezone.utc) - timedelta(days=7)
            ).isoformat()
            recent_emails = [
                e for e in emails
                if (e.get("received_at") or e.get("date") or "") >= seven_days_ago
                and not e.get("read") and not e.get("processed")
            ]
            unread = sum(
                1 for e in recent_emails
                if not e.get("read") and not e.get("processed")
            )
            as_of = datetime.now(timezone.utc).isoformat()
            return {
                "emails": recent_emails[:20],
                "unread_count": unread,
                "as_of": as_of,
            }
        return {"emails": [], "unread_count": 0, "error": "unavailable"}

    @app.get("/api/calendar")
    async def api_calendar():
        for path in ("/calendar/today", "/calendar/upcoming", "/calendar/week"):
            data = await _safe_get(f"{CALENDAR_AGENT_URL}{path}")
            if data is None:
                continue
            raw_events = (
                data
                if isinstance(data, list)
                else data.get("events", data.get("upcoming", []))
            )
            # Filter out Zoho sentinel objects.  When no events exist Zoho
            # returns [{"message": "No events found."}] instead of [].
            # A real event always has at least one of: uid, title, dateandtime.
            real_events = [
                e for e in raw_events
                if e.get("uid") or e.get("title") or e.get("dateandtime")
            ]
            # If this endpoint returned no real events (e.g. today is empty),
            # continue to the next path so the tile can show upcoming events
            # from /calendar/upcoming (next 4 h) or /calendar/week (next 7 d).
            if not real_events:
                continue
            # Normalize each event: flatten dateandtime.start, parse Zoho compact
            # datetime format, produce human-readable start_display.
            events = [_normalize_calendar_event(e) for e in real_events]
            return {"events": events[:10]}
        return {"events": []}

    @app.get("/api/followups")
    async def api_followups():
        """Read follow_ups.db directly — no dependency on openclaw uptime."""
        db_path = _find_db(FOLLOW_UPS_DB_CANDIDATES)
        if db_path is None:
            return {
                "followups": [],
                "total": 0,
                "overdue_count": 0,
                "error": "db not found",
            }
        try:
            conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM follow_ups ORDER BY last_client_ts DESC LIMIT 50"
            ).fetchall()
            conn.close()
            followups = [dict(r) for r in rows]
            now_utc = datetime.now(timezone.utc)
            from datetime import timedelta
            thirty_days_ago = (now_utc - timedelta(days=30)).isoformat()
            # Only surface follow-ups with client activity in the last 30 days
            recent_followups = [
                f for f in followups
                if (f.get("last_client_ts") or "").strip() >= thirty_days_ago
                and not _is_followup_noise(f)
            ]
            overdue = 0
            for f in recent_followups:
                last_client = f.get("last_client_ts")
                last_matthew = f.get("last_matthew_ts")
                if not last_client:
                    continue
                try:
                    client_dt = datetime.fromisoformat(last_client)
                    if client_dt.tzinfo is None:
                        client_dt = client_dt.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                waiting_on_matt = (not last_matthew) or (last_client > last_matthew)
                if waiting_on_matt and (now_utc - client_dt).total_seconds() >= 4 * 3600:
                    overdue += 1
            return {
                "followups": recent_followups[:20],
                "total": len(recent_followups),
                "overdue_count": overdue,
                "as_of": now_utc.isoformat(),
            }
        except Exception as exc:
            logger.debug("followups_db_fail error=%s", exc)
            return {
                "followups": [],
                "total": 0,
                "overdue_count": 0,
                "error": str(exc),
            }

    # Categories treated as automation noise (not human decisions)
    _AUTOMATION_CATEGORIES = frozenset({"jobs", "sync", "heartbeat", "health"})

    @app.get("/api/decisions/recent")
    async def api_decisions_recent(
        hours: int = Query(48, ge=1, le=720),
        limit: int = Query(20, ge=1, le=100),
        exclude_automation: bool = Query(True),
    ):
        """Read recent decisions from Cortex's own memory + the openclaw
        decision_journal (read-only). Cortex entries first.

        exclude_automation=true (default) hides category=jobs/sync/heartbeat/health
        entries — these are D-Tools and task-runner noise, not human decisions.
        Pass exclude_automation=false (or debug mode) to see everything.
        """
        engine = engine_ref()
        cortex_decisions: list[dict] = []
        if engine is not None:
            try:
                rows = engine.memory.conn.execute(
                    "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
                    (limit * 3,),
                ).fetchall()
                cortex_decisions = [dict(r) for r in rows]
            except Exception:
                cortex_decisions = []

        journal_decisions: list[dict] = []
        db_path = _find_db(DECISION_JOURNAL_DB_CANDIDATES)
        if db_path is not None:
            try:
                conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM decisions ORDER BY rowid DESC LIMIT ?",
                    (limit * 3,),
                ).fetchall()
                conn.close()
                journal_decisions = [dict(r) for r in rows]
            except Exception as exc:
                logger.debug("decisions_db_fail error=%s", exc)

        if exclude_automation:
            def _not_automation(d: dict) -> bool:
                cat = (d.get("category") or "").lower().strip()
                return cat not in _AUTOMATION_CATEGORIES
            cortex_decisions = [d for d in cortex_decisions if _not_automation(d)]
            journal_decisions = [d for d in journal_decisions if _not_automation(d)]

        return {
            "cortex": cortex_decisions[:limit],
            "journal": journal_decisions[:limit],
            "hours": hours,
            "exclude_automation": exclude_automation,
            "automation_note": "Pass exclude_automation=false to see D-Tools/sync entries" if exclude_automation else None,
        }

    @app.get("/api/events-log")
    async def api_events_log(limit: int = 50):
        r = _get_redis_sync()
        if r is None:
            return {"events": [], "count": 0, "error": "redis unavailable"}
        try:
            entries = r.lrange("events:log", 0, min(max(limit, 1), 200) - 1)
            events: list[dict] = []
            for e in entries:
                try:
                    events.append(json.loads(e))
                except Exception:
                    events.append({"raw": str(e)})
            return {"events": events, "count": len(events)}
        except Exception as exc:
            return {"events": [], "count": 0, "error": str(exc)}

    @app.get("/api/redeemer")
    async def api_redeemer():
        """Redeemer status: last cycle time, conditions redeemed, gas balance."""
        data = await _safe_get(f"{TRADING_BOT_URL}/redeem/status", timeout=5.0)
        if data is None:
            return {"status": "unavailable", "error": "bot unreachable"}
        return data

    # ── X Intake review queue proxies ──────────────────────────────────
    @app.get("/api/x-intake/stats")
    async def api_xintake_stats():
        """Proxy to x-intake /queue/stats — counts by status."""
        data = await _safe_get(f"{X_INTAKE_URL}/queue/stats", timeout=5.0)
        if data is None:
            return {"error": "x-intake unavailable", "pending": 0,
                    "auto_approved": 0, "auto_rejected": 0, "approved": 0,
                    "rejected": 0, "total": 0}
        return data

    @app.get("/api/x-intake/queue")
    async def api_xintake_queue(status: str = "", limit: int = 50):
        """Proxy to x-intake /queue — list items optionally filtered by status."""
        qs = f"?limit={min(limit, 100)}"
        if status:
            qs = f"?status={status}&limit={min(limit, 100)}"
        data = await _safe_get(f"{X_INTAKE_URL}/queue{qs}", timeout=5.0)
        if data is None:
            return {"items": [], "count": 0, "error": "x-intake unavailable"}
        return data

    @app.post("/api/x-intake/{item_id}/approve")
    async def api_xintake_approve(item_id: int):
        """Proxy approve action to x-intake."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{X_INTAKE_URL}/queue/{item_id}/approve", json={}
                )
                return resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:100]}

    @app.post("/api/x-intake/{item_id}/reject")
    async def api_xintake_reject(item_id: int):
        """Proxy reject action to x-intake."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{X_INTAKE_URL}/queue/{item_id}/reject", json={}
                )
                return resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:100]}

    @app.get("/api/x-intake/transcripts/stats")
    async def api_xintake_transcript_stats():
        """Return transcript analysis stats from x-intake."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{X_INTAKE_URL}/transcripts/stats")
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)[:100], "files_on_disk": 0, "analyzed": 0, "pending_analysis": 0}

    @app.post("/api/x-intake/transcripts/backfill")
    async def api_xintake_transcript_backfill(body: dict = {}):
        """Trigger transcript backfill analysis via x-intake."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{X_INTAKE_URL}/transcripts/backfill", json=body)
                return resp.json()
        except Exception as exc:
            return {"task_started": False, "error": str(exc)[:100]}

    @app.get("/api/system")
    async def api_system():
        """System info: uptime, disk, memory, container count."""
        result: dict[str, Any] = {
            "cpu_percent": None,
            "memory_percent": None,
            "disk_percent": None,
            "uptime_seconds": None,
            "containers_healthy": None,
            "containers_total": None,
        }
        # Disk
        try:
            total, used, _ = shutil.disk_usage("/")
            result["disk_percent"] = round(used / total * 100, 1)
            result["disk_used_gb"] = used // (1024 ** 3)
            result["disk_total_gb"] = total // (1024 ** 3)
        except Exception:
            pass
        # Memory (Linux /proc/meminfo — works in containers)
        try:
            with open("/proc/meminfo") as f:
                meminfo: dict[str, int] = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(":")] = int(parts[1])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            if total_kb > 0:
                result["memory_percent"] = round(
                    (total_kb - avail_kb) / total_kb * 100, 1
                )
                result["memory_used_mb"] = (total_kb - avail_kb) // 1024
                result["memory_total_mb"] = total_kb // 1024
        except Exception:
            pass
        # Uptime (own container)
        try:
            with open("/proc/uptime") as f:
                result["uptime_seconds"] = int(float(f.read().split()[0]))
        except Exception:
            pass
        # Container count via /api/services (reuse existing check)
        try:
            svc_payload = await api_services()
            result["containers_total"] = svc_payload.get("total")
            result["containers_healthy"] = svc_payload.get("healthy")
        except Exception:
            pass
        return result

    # ── X Intake — direct DB read with full filtering ──────────────────
    @app.get("/api/x-intake/items")
    async def api_xintake_items(
        status: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        """Read x_intake queue directly with status + date range filtering.

        date_from / date_to accept ISO-8601 date strings (YYYY-MM-DD).
        This endpoint bypasses the x-intake service so it works even when
        x-intake is down, and supports pagination + date filtering.
        """
        db_path = _find_db(X_INTAKE_DB_CANDIDATES)
        if db_path is None:
            return {"items": [], "count": 0, "total": 0, "error": "db not found"}
        try:
            conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row

            where_clauses: list[str] = []
            params: list[Any] = []

            if status:
                where_clauses.append("status = ?")
                params.append(status)
            if date_from:
                try:
                    ts_from = datetime.fromisoformat(date_from).timestamp()
                    where_clauses.append("created_at >= ?")
                    params.append(ts_from)
                except ValueError:
                    pass
            if date_to:
                try:
                    # Inclusive end-of-day
                    ts_to = datetime.fromisoformat(date_to).timestamp() + 86399
                    where_clauses.append("created_at <= ?")
                    params.append(ts_to)
                except ValueError:
                    pass

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            count_row = conn.execute(
                f"SELECT COUNT(*) AS n FROM x_intake_queue {where_sql}", params
            ).fetchone()
            total = count_row["n"] if count_row else 0

            rows = conn.execute(
                f"SELECT * FROM x_intake_queue {where_sql} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            conn.close()
            items = [dict(r) for r in rows]
            return {"items": items, "count": len(items), "total": total,
                    "offset": offset, "limit": limit}
        except Exception as exc:
            logger.debug("xintake_items_fail error=%s", exc)
            return {"items": [], "count": 0, "total": 0, "error": str(exc)[:100]}

    # ── Transcripts — list and detail ──────────────────────────────────
    @app.get("/api/transcripts")
    async def api_transcripts_list(
        limit: int = Query(50, ge=1, le=200),
        author: str = "",
    ):
        """List x_intake queue items that have an associated transcript."""
        db_path = _find_db(X_INTAKE_DB_CANDIDATES)
        if db_path is None:
            return {"transcripts": [], "total": 0, "error": "db not found"}
        try:
            conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
            if author:
                rows = conn.execute(
                    "SELECT * FROM x_intake_queue "
                    "WHERE has_transcript = 1 AND author = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (author, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM x_intake_queue "
                    "WHERE has_transcript = 1 "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
            items = [dict(r) for r in rows]
            return {"transcripts": items, "total": len(items)}
        except Exception as exc:
            logger.debug("transcripts_list_fail error=%s", exc)
            return {"transcripts": [], "total": 0, "error": str(exc)[:100]}

    @app.get("/api/transcripts/{item_id}")
    async def api_transcript_detail(item_id: int):
        """Return full transcript detail: queue row + parsed .md sections + Cortex gems."""
        import re as _re

        db_path = _find_db(X_INTAKE_DB_CANDIDATES)
        if db_path is None:
            return {"error": "db not found"}

        # Fetch queue row
        try:
            conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM x_intake_queue WHERE id = ?", (item_id,)
            ).fetchone()
            conn.close()
        except Exception as exc:
            return {"error": str(exc)[:100]}

        if row is None:
            return {"error": "item not found"}

        item = dict(row)
        author = item.get("author", "")
        transcript_path = item.get("transcript_path", "")

        # Parse .md file
        parsed_summary = ""
        parsed_transcript = ""
        flags: list[str] = []
        key_quotes: list[str] = []
        strategies_text = ""

        if transcript_path:
            try:
                md_file = Path(transcript_path)
                if md_file.exists():
                    content = md_file.read_text(encoding="utf-8", errors="replace")
                    m = _re.search(r"## Summary\s*\n(.*?)(?=\n##|\Z)", content, _re.DOTALL)
                    if m:
                        parsed_summary = m.group(1).strip()
                    m = _re.search(r"## Full Transcript\s*\n(.*?)(?=\n##|\Z)", content, _re.DOTALL)
                    if m:
                        parsed_transcript = m.group(1).strip()
                    m = _re.search(r"## Flags\s*\n(.*?)(?=\n##|\Z)", content, _re.DOTALL)
                    if m:
                        for line in m.group(1).strip().splitlines():
                            line = line.strip()
                            if line.startswith("-"):
                                flags.append(line[1:].strip())
                    m = _re.search(r"## Key Quotes\s*\n(.*?)(?=\n##|\Z)", content, _re.DOTALL)
                    if m:
                        for line in m.group(1).strip().splitlines():
                            line = line.strip().lstrip(">").strip()
                            if line:
                                key_quotes.append(line)
                    m = _re.search(r"## Strategies\s*\n(.*?)(?=\n##|\Z)", content, _re.DOTALL)
                    if m:
                        strategies_text = m.group(1).strip()
            except Exception as exc:
                logger.debug("transcript_md_read_fail path=%s error=%s", transcript_path, exc)

        # Fetch Cortex x_intel memories for this author (gems from transcript_analyst)
        gems: list[dict] = []
        engine = engine_ref()
        if engine is not None and author:
            try:
                gem_rows = engine.memory.conn.execute(
                    "SELECT id, title, content, source, created_at, metadata "
                    "FROM memories WHERE category = 'x_intel' AND source LIKE ? "
                    "ORDER BY created_at DESC LIMIT 10",
                    (f"x_intake:@{author}:%",),
                ).fetchall()
                gems = [dict(r) for r in gem_rows]
            except Exception as exc:
                logger.debug("transcript_gems_fail author=%s error=%s", author, exc)

        return {
            "item": item,
            "parsed_summary": parsed_summary,
            "parsed_transcript": parsed_transcript,
            "flags": flags,
            "key_quotes": key_quotes,
            "strategies": strategies_text,
            "gems": gems,
        }

    # ── Meeting Audio Intake ────────────────────────────────────────────
    @app.get("/api/meetings/recent")
    async def api_meetings_recent(limit: int = Query(20, ge=1, le=100)):
        """Return recent meeting-audio queue rows from audio_intake/queue.db.

        Mounted read-only into the Cortex container at /data/audio_intake.
        Returns an empty list (not an error) when the DB is not present yet,
        so the dashboard tile degrades gracefully.
        """
        db_path = _find_db(AUDIO_INTAKE_DB_CANDIDATES)
        if db_path is None:
            return []
        try:
            conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, original_name, source_date, status, summary, "
                "participants, clients, projects, action_items, "
                "cortex_memory_id, transcript_path, created_at, completed_at "
                "FROM audio_intake_queue ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            out: list[dict] = []
            for r in rows:
                row = dict(r)
                for fld in ("participants", "clients", "projects", "action_items"):
                    v = row.get(fld)
                    if isinstance(v, str) and v:
                        try:
                            row[fld] = json.loads(v)
                        except Exception:
                            row[fld] = [v]
                    elif v is None:
                        row[fld] = []
                out.append(row)
            return out
        except Exception as exc:
            logger.debug("meetings_recent_fail error=%s", exc)
            return []

    # ── Symphony Ops proxies ────────────────────────────────────────────────

    PROPOSALS_URL = os.environ.get("PROPOSALS_URL", "http://proposals:8091")
    CLIENT_PORTAL_URL = os.environ.get("CLIENT_PORTAL_URL", "http://client-portal:8096")
    MARKUP_URL = os.environ.get("MARKUP_URL", "http://host.docker.internal:8088")
    @app.get("/api/symphony/bluebubbles/health")
    async def symphony_bluebubbles_health():
        from cortex.bluebubbles import BlueBubblesClient
        ping = await BlueBubblesClient().ping()
        if not ping.get("ok"):
            return {"status": "offline", "error": ping.get("error") or f"http_{ping.get('http_status')}"}
        return {
            "status": "online",
            "server_version": ping.get("server_version"),
            "private_api": ping.get("private_api"),
            "latency_ms": ping.get("latency_ms"),
        }

    @app.get("/api/symphony/markup/health")
    async def symphony_markup_health():
        """Probe the Markup Tool (runs on host via launchd, reached through host.docker.internal:8088)."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{MARKUP_URL}/")
            if r.status_code == 200:
                return {"status": "online", "url": MARKUP_URL}
            return {"status": "offline", "http_status": r.status_code}
        except Exception as exc:
            return {"status": "offline", "error": str(exc)}

    @app.get("/api/symphony/voice-receptionist")
    async def symphony_voice_receptionist():
        """Read-only status + planned-fields contract for the call dashboard.

        Probes the voice-receptionist /health endpoint and returns a stable
        shape the frontend can render even when the upstream is offline.
        Recent-calls/transcripts are intentionally NOT pulled live yet —
        the receptionist's SQLite call log is in-container and Cortex
        ingestion is a planned increment. The ``planned`` block describes
        the future contract so the UI can render an honest empty state.
        """
        status_payload: dict[str, Any] = {
            "status": "unknown",
            "url": VOICE_RECEPTIONIST_URL,
            "checked_at": datetime.now().isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{VOICE_RECEPTIONIST_URL}/health")
            if r.status_code == 200:
                status_payload["status"] = "online"
                try:
                    status_payload["details"] = r.json()
                except Exception:
                    status_payload["details"] = {}
            else:
                status_payload["status"] = "degraded"
                status_payload["http_status"] = r.status_code
        except Exception as exc:
            status_payload["status"] = "offline"
            status_payload["error"] = str(exc)[:200]

        return {
            "service": status_payload,
            "recent_calls": [],
            "missed_calls": [],
            "voicemails": [],
            "planned": {
                "ingestion": (
                    "Twilio call events + OpenAI Realtime transcripts will "
                    "be persisted to Cortex via the existing voice_receptionist "
                    "SQLite call log; a Cortex sync worker will mirror them "
                    "into the dashboard."
                ),
                "redis_channel": "ops:voice_followup",
                "fields": [
                    "caller_name",
                    "phone",
                    "started_at",
                    "duration_s",
                    "status",
                    "transcript_excerpt",
                    "voicemail_url",
                    "matched_client",
                    "matched_project",
                    "suggested_followup",
                ],
                "actions": [
                    "send_text",
                    "send_email",
                    "create_intake",
                    "escalate_to_matt",
                    "schedule_callback",
                ],
            },
        }

    @app.get("/api/symphony/proposals/templates")
    async def symphony_proposals_templates():
        data = await _safe_get(f"{PROPOSALS_URL}/proposals/templates/list")
        if not data:
            return {"templates": [], "error": "proposals service unavailable"}
        # Normalize upstream shape — proposals returns {proposal_templates, email_templates}
        templates = data.get("templates")
        if templates is None:
            templates = data.get("proposal_templates") or []
        return {"templates": templates, "email_templates": data.get("email_templates", [])}

    @app.post("/api/symphony/proposals/generate")
    async def symphony_proposals_generate(request: dict):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{PROPOSALS_URL}/proposals/generate", json=request)
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/api/symphony/portal/health")
    async def symphony_portal_health():
        data = await _safe_get(f"{CLIENT_PORTAL_URL}/health")
        return data or {"status": "offline"}

    @app.post("/api/symphony/agreement/generate")
    async def symphony_generate_agreement(request: dict):
        """Run generate_agreement.py and return the .docx path."""
        import subprocess
        cmd = [
            "python3", "/app/tools/generate_agreement.py",
            "--client", request.get("client", ""),
            "--project", request.get("project", ""),
            "--items", request.get("items", ""),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {"output": result.stdout.strip(), "error": result.stderr.strip() if result.returncode != 0 else None}
        except Exception as exc:
            return {"error": str(exc)}

    @app.post("/api/symphony/tools/{tool_name}")
    async def symphony_run_tool(tool_name: str, request: dict = {}):
        """Run a Symphony business tool by name."""
        tool_map = {
            "room_mapper": "python3 /app/tools/bob_room_mapper.py",
            "project_analyzer": "python3 /app/tools/bob_project_analyzer.py",
            "proposal_to_dtools": "python3 /app/tools/bob_proposal_to_dtools.py",
            "build_inventory": "python3 /app/tools/bob_build_inventory.py",
            "fetch_manuals": "python3 /app/tools/bob_fetch_manuals.py",
            "cortex_curator": "python3 /app/tools/cortex_curator.py --run --json",
            "knowledge_graph": "python3 /app/tools/knowledge_graph.py --status",
            "maintenance": "python3 /app/tools/bob_maintenance.py --dry",
        }
        cmd = tool_map.get(tool_name)
        if not cmd:
            return {"error": f"Unknown tool: {tool_name}"}

        args = request.get("args", "")
        if args:
            cmd += f" {args}"

        import subprocess
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60,
                cwd="/app"
            )
            return {
                "tool": tool_name,
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Tool timed out (60s limit)"}
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/api/symphony/cortex/stats")
    async def symphony_cortex_stats():
        """Get cortex memory/goal/rule stats for the Symphony Ops panel."""
        eng = engine_ref()
        if eng is None:
            return {"total": 0, "active_goals": 0, "rules": 0}
        stats = eng.memory.get_stats()
        rules = eng.memory.get_rules(category="trading_rule", min_confidence=0.6)
        return {
            "total": stats.get("total", 0),
            "active_goals": stats.get("active_goals", 0),
            "rules": len(rules),
        }

    # ── Dashboard audit summary ─────────────────────────────────────────
    @app.get("/api/dashboard/audit-summary", tags=["dashboard"])
    async def api_dashboard_audit_summary():
        """Structured audit health summary for the Cortex dashboard.

        Returns a stable shape describing which sections are live, stale,
        failing, or debug-only so automated monitoring can track dashboard
        health without re-running a full endpoint sweep.

        Generated from the 2026-04-27 full audit
        (ops/verification/20260427T180800Z-cortex-dashboard-audit.md).
        """
        return {
            "as_of": "2026-04-27T18:08:00Z",
            "live_sections": [
                "polymarket_exposure",
                "x_intake",
                "self_improvement",
                "client_intel",
                "services",
                "tools_registry",
                "process_backlog",
                "pnl_summary",
            ],
            "failing_sections": [
                {
                    "section": "wallet",
                    "endpoint": "/api/wallet",
                    "reason": "portfolio:snapshot Redis key not pushed by bot; falls back to Polymarket data API (position_value only, usdc_balance=0)",
                    "priority": "P1",
                },
                {
                    "section": "pnl_series",
                    "endpoint": "/api/pnl-series",
                    "reason": "portfolio:pnl_series Redis key never populated",
                    "priority": "P1",
                },
                {
                    "section": "trading_intel",
                    "endpoint": "/api/trading/intel",
                    "reason": "X-intel not actively scoring; all zeros returned",
                    "priority": "P2",
                },
            ],
            "stale_sections": [
                {
                    "section": "decisions",
                    "endpoint": "/api/decisions/recent",
                    "reason": "journal dominated by D-Tools automation entries, not human decisions",
                    "priority": "P1",
                },
                {
                    "section": "watchdog",
                    "endpoint": "/api/watchdog/status",
                    "reason": "state=degraded for recovery events that fired within 1h window; all containers actually healthy",
                    "priority": "P1",
                },
                {
                    "section": "meetings",
                    "endpoint": "/api/meetings/recent",
                    "reason": "rows have 2024 source_dates and empty summaries",
                    "priority": "P2",
                },
                {
                    "section": "activity",
                    "endpoint": "/api/activity",
                    "reason": "feed dominated by health.checked system noise",
                    "priority": "P2",
                },
            ],
            "debug_only_sections": [
                {
                    "section": "vault",
                    "endpoint": "/api/vault/secrets",
                    "reason": "TEST_VAULT_SECRET synthetic entry was visible in production; now hidden behind CORTEX_DEBUG=true",
                    "fix_applied": True,
                },
            ],
            "planned_sections": [
                {
                    "section": "voice_receptionist",
                    "endpoint": "/api/symphony/voice-receptionist",
                    "reason": "recent_calls/missed_calls/voicemails always empty — Twilio ingestion not yet wired to Cortex",
                    "priority": "P3",
                },
            ],
            "recommendation_count": 6,
            "fixes_applied_count": 1,
        }

    # ── Dashboard data-source audit ─────────────────────────────────────
    @app.get("/api/dashboard/data-source-audit", tags=["dashboard"])
    async def api_dashboard_data_source_audit():
        """Structured audit of every Cortex dashboard data source.

        Produced by the 2026-04-27 full audit (v3).  Updated when new issues
        are discovered or existing ones are resolved.  The frontend can render
        this on the Debug tab to give the operator a live overview of data
        quality without opening the audit markdown file.
        """
        return {
            "as_of": "2026-04-27T18:56:41Z",
            "sources": [
                # ── Live & accurate ──────────────────────────────────────
                {"card": "Service Health", "tab": "today", "endpoint": "/api/services",
                 "status": "live", "note": "13 services monitored"},
                {"card": "Emails", "tab": "today", "endpoint": "/api/emails",
                 "status": "live", "note": "Live, recent"},
                {"card": "X Intake widget", "tab": "today", "endpoint": "/api/x-intake/stats",
                 "status": "live", "note": "70 total, 0 pending"},
                {"card": "Polymarket Exposure", "tab": "money", "endpoint": "/api/polymarket/exposure",
                 "status": "live", "note": "78 positions, $397 value"},
                {"card": "Redeemer", "tab": "money", "endpoint": "/api/redeemer",
                 "status": "live", "note": "$3.72 USDC, 78 pending, 60 POL gas"},
                {"card": "PnL Summary", "tab": "money", "endpoint": "/api/pnl-summary",
                 "status": "live", "note": "$-1112 realized, 2450 paper trades"},
                {"card": "Memory", "tab": "debug", "endpoint": "/health + /memories",
                 "status": "live", "note": "100,816 total memories"},
                {"card": "System", "tab": "footer", "endpoint": "/api/system",
                 "status": "live", "note": "44% mem, 6% disk"},
                {"card": "Dashboard Config", "tab": "debug", "endpoint": "/api/dashboard/config",
                 "status": "live", "note": "CORTEX_DEBUG gate working"},
                {"card": "Vault", "tab": "vault", "endpoint": "/api/vault/secrets",
                 "status": "live", "note": "TEST_* hidden behind CORTEX_DEBUG — correct"},
                {"card": "Client Intel", "tab": "clients", "endpoint": "/api/client-intel/*",
                 "status": "live", "note": "5 profiles, queue active"},
                {"card": "Autonomy", "tab": "autonomy", "endpoint": "/api/autonomy/overview",
                 "status": "live", "note": "Gate summaries working"},
                # ── Failing / broken ────────────────────────────────────
                {"card": "Wallet", "tab": "money", "endpoint": "/api/wallet",
                 "status": "failing", "priority": "P1",
                 "reason": "Redis key portfolio:snapshot never pushed by bot; returns usdc=0 active=0. Real balance: $3.72 USDC on-chain (see Redeemer card)."},
                {"card": "PnL Series", "tab": "money", "endpoint": "/api/pnl-series",
                 "status": "failing", "priority": "P1",
                 "reason": "Redis key portfolio:pnl_series never populated; returns []. Chart has never had data."},
                {"card": "Trading Intel", "tab": "symphony", "endpoint": "/api/trading/intel",
                 "status": "failing", "priority": "P2",
                 "reason": "Returns valid JSON shape but all zeros (active_signals:0, market_boosts:0, top_authors:[]). X-intel not scoring."},
                {"card": "Follow-ups", "tab": "today", "endpoint": "/api/followups",
                 "status": "failing", "priority": "P1",
                 "reason": "DB not mounted in container: error='unable to open database file'. Shown as '0 active' but is actually unavailable."},
                {"card": "Reply Inbox", "tab": "reply-inbox", "endpoint": "/api/reply-inbox",
                 "status": "failing", "priority": "P2",
                 "reason": "Endpoint returns 404. loadReplyInbox() is calling a non-existent route."},
                # ── Stale / misleading ───────────────────────────────────
                {"card": "Decisions Journal", "tab": "debug", "endpoint": "/api/decisions/recent",
                 "status": "stale", "priority": "P1",
                 "reason": "100 entries: 77% D-Tools automation ('D-Tools sync: created=0'), 23% email events. Zero human decisions. cortex[] is empty. Misleadingly labelled 'Decisions'."},
                {"card": "Meetings", "tab": "debug", "endpoint": "/api/meetings/recent",
                 "status": "stale", "priority": "P2",
                 "reason": "All 5 rows from 2024 (July/Aug), empty summaries. 2 years stale. v2 7-day filter should now hide these."},
                {"card": "Activity Feed", "tab": "debug", "endpoint": "/api/activity",
                 "status": "stale", "priority": "P2",
                 "reason": "50 events: 20% are health.checked system pings, 30% have no channel. Noise:signal ~50%."},
                {"card": "Watchdog (stale-ok)", "tab": "today", "endpoint": "/api/watchdog/status",
                 "status": "stale", "priority": "P1",
                 "reason": "4 'ok' services (Tailscale, VPN, Polymarket Bot, X Alpha Collector) not seen in 66-75h. Shown green but state is unknown. Docker 'degraded' is false alarm from recovery event."},
                {"card": "Goals", "tab": "debug", "endpoint": "/goals",
                 "status": "stale", "priority": "P3",
                 "reason": "5 goals have NO updated_at timestamp; freshness cannot be determined. Trading profit goal at 10%, edge discovery at 0% — may be permanently stale."},
                # ── Synthetic / paper (unlabelled) ────────────────────────
                {"card": "Positions", "tab": "money", "endpoint": "/api/positions",
                 "status": "synthetic", "priority": "P1",
                 "reason": "All 13 positions have order_id='paper-*' from cvd_arb strategy simulation. No timestamps. Shown without PAPER label alongside real data. Real legacy positions are in /api/polymarket/exposure."},
                {"card": "PnL Summary (paper)", "tab": "money", "endpoint": "/api/pnl-summary",
                 "status": "synthetic", "priority": "P2",
                 "reason": "$-1112 realized PnL, 2450 trades — these are from paper/simulation runs, not real money. No label distinguishing paper from live."},
            ],
            "totals": {
                "live_sources": 12,
                "stale_sources": 5,
                "failing_sources": 5,
                "synthetic_sources": 2,
                "debug_only_sources": 1,
                "hidden_recommended": 3,
            },
            "fixes_applied": [
                "Positions: PAPER badge added when order_id starts with 'paper-'",
                "Activity: health.checked noise filtered in normal mode",
                "Decisions: category=jobs (D-Tools) filtered in normal mode",
                "Follow-ups: explicit error state when DB unavailable",
            ],
            "fixes_pending_approval": [
                "Watchdog: filter stale-ok entries (>48h) from main view",
                "Follow-ups: fix docker-compose volume mount for follow_ups.db",
                "Reply inbox: audit loadReplyInbox() endpoint URL (currently 404)",
                "Wallet: bot must push portfolio:snapshot Redis key",
                "Goals: add updated_at to goals endpoint",
            ],
        }

    # ── Dashboard runtime config ─────────────────────────────────────────
    @app.get("/api/dashboard/config", tags=["dashboard"])
    async def api_dashboard_config():
        """Returns runtime config flags that the frontend uses to gate behaviour.

        ``debug_mode`` mirrors the server-side ``CORTEX_DEBUG`` env var and
        tells the JS freshness system to disable pruning and show all data.
        """
        _debug = os.environ.get("CORTEX_DEBUG", "").lower() in {"1", "true", "yes"}
        return {
            "debug_mode": _debug,
            "freshness_thresholds": {
                "active_secs": 3_600,
                "recent_secs": 86_400,
                "stale_secs": 7 * 86_400,
            },
        }


# ── Intel Briefing proxy ──────────────────────────────────────────────────────

OPENCLAW_INTERNAL_URL = os.environ.get("OPENCLAW_URL", "http://openclaw:3000")


def register_intel_briefing_routes(app: FastAPI) -> None:
    """Register /api/intel-briefing proxy routes onto the Cortex FastAPI app."""

    @app.get("/api/intel-briefing/preview", tags=["intel-briefing"])
    async def proxy_intel_briefing_preview():
        """Proxy: preview the daily intel briefing text without sending."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{OPENCLAW_INTERNAL_URL}/api/intel-briefing/preview")
            resp.raise_for_status()
            return resp.json()

    @app.post("/api/intel-briefing/send", tags=["intel-briefing"])
    async def proxy_intel_briefing_send():
        """Proxy: manually trigger the daily intel briefing send via iMessage."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{OPENCLAW_INTERNAL_URL}/api/intel-briefing/send")
            resp.raise_for_status()
            return resp.json()


# ── Process backlog (read-only, repo-native) ─────────────────────────────────
#
# Surfaces ops/BACKLOG.md (engineering process backlog) on Cortex so the
# operator can see the engineering workstreams alongside the Symphony tab.
# Strictly read-only: mutations happen by editing the markdown and committing.
# See ops/PROCESS_POLICY.md for the policy this endpoint supports.

# Candidate paths so this works in-container (/app) and in tests (repo-root).
BACKLOG_PATH_CANDIDATES = [
    Path("/app/ops/BACKLOG.md"),
    Path("ops/BACKLOG.md"),
    Path(__file__).resolve().parent.parent / "ops" / "BACKLOG.md",
]
HANDOFF_PATH_CANDIDATES = [
    Path("/app/HANDOFF.md"),
    Path("HANDOFF.md"),
    Path(__file__).resolve().parent.parent / "HANDOFF.md",
]
PROCESS_POLICY_PATH_CANDIDATES = [
    Path("/app/ops/PROCESS_POLICY.md"),
    Path("ops/PROCESS_POLICY.md"),
    Path(__file__).resolve().parent.parent / "ops" / "PROCESS_POLICY.md",
]


def _resolve_first(paths: list[Path]) -> Path | None:
    for p in paths:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _parse_backlog(text: str) -> dict[str, Any]:
    """Parse ops/BACKLOG.md into a JSON-friendly structure.

    Returns a dict with:
      - items: list of {id, title, status, owner, lane, risk, anchor}
      - counts: {by_status: {...}, total: int, active: int, done: int, skip: int}

    Best-effort parser: walks ``### N. Title`` blocks under any heading.
    Items are extracted from the immediately following bullet lines that
    start with a recognized **Field:** prefix. Anything we can't parse is
    skipped silently — the markdown remains the source of truth.
    """
    items: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    heading_re = None  # avoid importing re at module top; build locally
    import re as _re
    heading_re = _re.compile(r"^###\s+(\d+)\.\s+(.+?)\s*$")
    field_re = _re.compile(
        r"^-\s+\*\*(Status|Owner|Lane|Risk):\*\*\s*(.+?)\s*$",
        _re.IGNORECASE,
    )
    while i < n:
        m = heading_re.match(lines[i])
        if not m:
            i += 1
            continue
        item: dict[str, Any] = {
            "id": int(m.group(1)),
            "title": m.group(2).strip(),
            "status": "unknown",
            "owner": "unassigned",
            "lane": "",
            "risk": "low",
            "anchor": _slugify(m.group(2)),
        }
        i += 1
        # Walk forward until the next heading or blank-blank gap; pick up fields.
        while i < n and not heading_re.match(lines[i]) and not lines[i].startswith("## "):
            fm = field_re.match(lines[i])
            if fm:
                key = fm.group(1).lower()
                value = fm.group(2).strip()
                # Strip any trailing parenthetical metadata for status/owner.
                if key == "status":
                    # Take the first token: 'todo', 'done', 'in-progress', etc.
                    value = value.split()[0].rstrip("|").lower() if value else "unknown"
                item[key] = value
            i += 1
        items.append(item)

    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    counts = {
        "total": len(items),
        "by_status": by_status,
        "active": sum(
            v for k, v in by_status.items()
            if k in {"todo", "in-progress", "blocked"}
        ),
        "done": by_status.get("done", 0),
        "skip": by_status.get("skip", 0),
    }
    return {"items": items, "counts": counts}


def _slugify(text: str) -> str:
    import re as _re
    s = text.lower().strip()
    s = _re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def register_process_routes(app: FastAPI) -> None:
    """Register /api/process/* read-only routes onto the Cortex FastAPI app.

    Surfaces the engineering process backlog (ops/BACKLOG.md) and
    pointers to HANDOFF.md / PROCESS_POLICY.md. No mutations — the
    repo files are the canonical source of truth. See
    ops/PROCESS_POLICY.md.
    """

    @app.get("/api/process/backlog", tags=["process"])
    async def process_backlog():
        path = _resolve_first(BACKLOG_PATH_CANDIDATES)
        if path is None:
            return {
                "ok": False,
                "error": "ops/BACKLOG.md not found in any candidate path",
                "candidates": [str(p) for p in BACKLOG_PATH_CANDIDATES],
                "items": [],
                "counts": {"total": 0, "by_status": {}, "active": 0, "done": 0, "skip": 0},
            }
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc), "items": [], "counts": {}}
        parsed = _parse_backlog(text)
        return {
            "ok": True,
            "source": str(path),
            "source_label": "ops/BACKLOG.md",
            "checked_at": datetime.now().isoformat(),
            **parsed,
        }

    @app.get("/api/process/handoff", tags=["process"])
    async def process_handoff():
        """Return pointers to the canonical handoff docs.

        We do not return the full body — operators should open the
        markdown directly. This endpoint exists so the dashboard can
        link to the right files without hardcoding paths in JS.
        """
        backlog = _resolve_first(BACKLOG_PATH_CANDIDATES)
        handoff = _resolve_first(HANDOFF_PATH_CANDIDATES)
        policy = _resolve_first(PROCESS_POLICY_PATH_CANDIDATES)
        return {
            "ok": True,
            "checked_at": datetime.now().isoformat(),
            "documents": {
                "handoff": {
                    "label": "HANDOFF.md",
                    "exists": handoff is not None,
                    "path": str(handoff) if handoff else None,
                },
                "backlog": {
                    "label": "ops/BACKLOG.md",
                    "exists": backlog is not None,
                    "path": str(backlog) if backlog else None,
                },
                "policy": {
                    "label": "ops/PROCESS_POLICY.md",
                    "exists": policy is not None,
                    "path": str(policy) if policy else None,
                },
            },
            "policy_summary": (
                "Linear = live client/business ops only. "
                "Repo = engineering/process source of truth. "
                "Cortex = operator action surface (this endpoint). "
                "See ops/PROCESS_POLICY.md."
            ),
        }
