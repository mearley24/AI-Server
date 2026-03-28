"""Mission Control — entrypoint that wraps event_server with health monitoring and dashboard."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8098"))
STATIC_DIR = Path(__file__).parent / "static"
TRADING_BOT_URL = "http://vpn:8430"
COPYTRADE_WALLET_FILE = Path("/trading-data/copytrade_wallets.json")

# Service map: name -> (container_hostname, internal_port, external_port)
SERVICES = [
    {"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000},
    {"name": "Remediator", "host": "remediator", "port": 8090, "ext_port": 8090},
    {"name": "Proposals", "host": "proposals", "port": 8091, "ext_port": 8091},
    {"name": "Email Monitor", "host": "email-monitor", "port": 8092, "ext_port": 8092},
    {"name": "Voice Receptionist", "host": "voice-receptionist", "port": 3000, "ext_port": 8093},
    {"name": "Calendar Agent", "host": "calendar-agent", "port": 8094, "ext_port": 8094},
    {"name": "Notification Hub", "host": "notification-hub", "port": 8095, "ext_port": 8095},
    {"name": "D-Tools Bridge", "host": "dtools-bridge", "port": 5050, "ext_port": 8096},
    {"name": "ClawWork", "host": "clawwork", "port": 8097, "ext_port": 8097},
    {"name": "Polymarket Bot", "host": "vpn", "port": 8430, "ext_port": 8430},
    {"name": "OpenClaw", "host": "openclaw", "port": 3000, "ext_port": 8099},
    {"name": "Knowledge Scanner", "host": "knowledge-scanner", "port": 8100, "ext_port": 8100},
]


async def check_service_health(service: dict) -> dict:
    """Check a single service's health endpoint."""
    url = f"http://{service['host']}:{service['port']}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                details = resp.json() if "json" in ct else {}
                return {"name": service["name"], "status": "healthy", "port": service["ext_port"], "details": details}
            else:
                return {"name": service["name"], "status": "degraded", "port": service["ext_port"], "details": {"http_status": resp.status_code}}
    except Exception:
        return {"name": service["name"], "status": "down", "port": service["ext_port"], "details": {}}


# Import the existing event_server — but override DB path before init
import event_server
data_dir = Path(os.getenv("DATA_DIR", "/data"))
data_dir.mkdir(parents=True, exist_ok=True)
event_server.DB_PATH = data_dir / "events.db"
event_server.STATIC_DIR = STATIC_DIR

# Re-use the existing app from event_server (has WebSocket, events, status, digest)
app = event_server.app

# ── Add new routes ──

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mission-control"}


@app.get("/api/services")
async def api_services():
    """Check health of all services."""
    results = await asyncio.gather(*[check_service_health(s) for s in SERVICES])
    now = datetime.now().isoformat()
    for r in results:
        r["checked_at"] = now
    return {
        "services": results,
        "total": len(results),
        "healthy": sum(1 for r in results if r["status"] == "healthy"),
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the ops dashboard."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Dashboard not found</h1>")


@app.get("/api/trading")
async def api_trading():
    """Trading dashboard data — live from polymarket-bot."""
    result = {
        "pnl": None,
        "positions": [],
        "recent_trades": [],
        "categories": {},
        "summary": {},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch PnL
            try:
                resp = await client.get(f"{TRADING_BOT_URL}/pnl")
                if resp.status_code == 200:
                    result["pnl"] = resp.json()
            except Exception:
                pass

            # Fetch positions
            try:
                resp = await client.get(f"{TRADING_BOT_URL}/positions", params={"platform": "polymarket"})
                if resp.status_code == 200:
                    result["positions"] = resp.json().get("positions", [])
            except Exception:
                pass

            # Fetch recent trades from audit trail
            try:
                resp = await client.get(f"{TRADING_BOT_URL}/audit", params={"type": "trade_decision", "limit": 500})
                if resp.status_code == 200:
                    result["recent_trades"] = resp.json().get("entries", [])
            except Exception:
                pass

            # Fetch paper trades (these are actually polymarket trades)
            try:
                resp = await client.get(f"{TRADING_BOT_URL}/paper-trades", params={"limit": 500})
                if resp.status_code == 200:
                    result["recent_trades"] = resp.json().get("trades", [])
            except Exception:
                pass

    except Exception:
        pass

    return result


# Seed category P/L data (from blockchain analysis as of March 27, 2026)
CATEGORY_PNL_SEED = {
    "crypto": {"total_pnl": 65.48, "trades": 8, "bought": 0, "sold": 0, "redeemed": 0, "open_value": 0, "multiplier": 1.2, "verdict": "Top earner after both-sides fix. 8 resolved wins, avg 105% return.", "status": "success"},
    "sports": {"total_pnl": 25.04, "trades": 7, "bought": 0, "sold": 0, "redeemed": 0, "open_value": 0, "multiplier": 1.3, "verdict": "Tennis + esports = 7/7 wins. Best ROI category.", "status": "success"},
    "weather": {"total_pnl": 11.00, "trades": 2, "bought": 0, "sold": 0, "redeemed": 0, "open_value": 78.52, "multiplier": 1.0, "verdict": "2 resolved wins (Shanghai, Dallas). More positions pending.", "status": "success"},
    "politics": {"total_pnl": 2.85, "trades": 11, "bought": 20.74, "sold": 15.12, "redeemed": 8.47, "open_value": 0, "multiplier": 1.5, "verdict": "Profitable. Highest multiplier — best edge from information.", "status": "success"},
    "other": {"total_pnl": 2.73, "trades": 33, "bought": 101.88, "sold": 33.27, "redeemed": 71.33, "open_value": 0, "multiplier": 1.0, "verdict": "Baseline positive. Mixed markets.", "status": "success"},
}

@app.get("/api/trading/categories")
async def api_trading_categories():
    """Category P/L breakdown with lessons and verdicts."""
    return {"categories": CATEGORY_PNL_SEED, "as_of": "2026-03-27T07:00:00"}


LESSONS = [
    {
        "title": "Both-Sides Buying Trap",
        "severity": "critical",
        "loss": -57.17,
        "category": "crypto_updown",
        "description": "The bot was buying BOTH Up and Down outcomes on the same crypto market simultaneously. When copying wallets that took opposite sides, we'd pay $1 (full price) for what resolves to $1 — guaranteed loss after fees. This was the single biggest money pit.",
        "fix": "Implemented opposite-side detection: before buying any outcome, check if we already hold the opposite side. If so, skip the trade entirely. Also added same-market deduplication within 60-second windows.",
        "example": "Bitcoin Up or Down March 25: Bot bought 'Up' at $0.64 AND 'Down' at $0.36 from different wallets. Combined cost: $1.00 for a $1.00 payout — net loss after fees every time."
    },
    {
        "title": "Crypto 5-Minute Markets Are Coin Flips",
        "severity": "critical",
        "loss": -57.17,
        "category": "crypto_updown",
        "description": "Short-duration crypto up/down markets (5-minute, 15-minute) are essentially random. No wallet has consistent edge on these. The bot was copying wallets that appeared profitable but were just lucky in small samples.",
        "fix": "Reduced crypto_updown multiplier to 0.15x (smallest positions). Added minimum market duration filter. Price bounds tightened to 0.15-0.90 to avoid extreme odds.",
        "example": "Ethereum Up or Down 4:15-4:20PM: 5-minute window, pure noise. Bot bought 'Up' at $0.95 — paying near-max for a coin flip."
    },
    {
        "title": "Esports Low-Liquidity Trap",
        "severity": "high",
        "loss": -24.68,
        "category": "sports",
        "description": "Esports markets had very low liquidity and wide spreads. The bot was copying wallets into markets where exit was nearly impossible. Most positions expired worthless because the markets were too thin to sell before resolution.",
        "fix": "Applied 0.5x reduction factor for esports. Sports multiplier lowered to 0.25x. Added per-category circuit breakers: sports stops at -$15 daily loss.",
        "example": "Multiple League of Legends and CS2 match markets — bot entered at unfavorable prices, couldn't exit, and most resolved as losses."
    },
    {
        "title": "Weather Positions Still Open",
        "severity": "medium",
        "loss": -11.28,
        "category": "weather",
        "description": "Weather category has $78 in open positions that haven't resolved yet. The P/L could swing significantly once these close. Weather markets tend to have longer durations and less predictable outcomes.",
        "fix": "Weather multiplier set to 0.8x. Stop-loss at 50%, stale exit after 72 hours, trailing stop at 15%. Circuit breaker at -$25.",
        "example": "Multiple temperature and precipitation markets for late March — still pending resolution. Could recover or deepen losses."
    },
    {
        "title": "Wallet Quality Varies by Category",
        "severity": "high",
        "loss": 0,
        "category": "all",
        "description": "A wallet that's profitable in politics might be terrible at crypto. The original scoring didn't account for category-specific performance, leading to blind copying across all market types.",
        "fix": "Implemented category-aware wallet scoring. The wallet scorer now tracks per-category win rates and adjusts trust levels. Kelly criterion uses category-specific multipliers.",
        "example": "Wallet 0xa3... had 80% win rate in politics but 30% in crypto. Without category scoring, we'd copy all their trades equally."
    },
    {
        "title": "Position Sizing Was Too Aggressive",
        "severity": "high",
        "loss": 0,
        "category": "all",
        "description": "Early trades used flat $5 sizing regardless of confidence or market quality. This led to large losses on low-confidence trades and missed opportunities on high-confidence ones.",
        "fix": "Kelly criterion now scales position size based on wallet score, category multiplier, and market confidence. Per-category circuit breakers prevent cascading losses.",
        "example": "A $5 bet on a 50/50 crypto coin flip costs the same as a $5 bet on a 75% confidence politics market — but the expected values are very different."
    },
    {
        "title": "No Exit Strategy Was in Place",
        "severity": "high",
        "loss": 0,
        "category": "all",
        "description": "The bot had no mechanism to exit losing positions. Once a trade was made, it sat until resolution — even when the market moved heavily against us.",
        "fix": "Built a category-specific exit engine. Crypto: 35% stop-loss, 12h stale exit, 10% trailing stop. Sports: 40% SL, 24h stale, 12% trail. Weather: 50% SL, 72h stale, 15% trail. Politics: 50% SL, 96h stale, 20% trail.",
        "example": "A crypto position that dropped from $0.64 to $0.20 would have been exited at $0.42 with the stop-loss, saving $0.22 per share."
    },
    {
        "title": "Politics Is the Sweet Spot",
        "severity": "positive",
        "loss": 2.85,
        "category": "politics",
        "description": "Politics markets are the only category that's profitable. They have better liquidity, longer durations, and wallets with genuine information edges. The bot performs best here.",
        "fix": "Increased politics multiplier to 1.2x (highest). Circuit breaker set generously at -$35. Longer stale exit (96h) and wider trailing stop (20%) to let positions develop.",
        "example": "Multiple Trump/Biden policy markets where copied wallets had genuine political insight — small but consistent profits."
    }
]

@app.get("/api/trading/lessons")
async def api_trading_lessons():
    """Lessons learned from trading history analysis."""
    return {"lessons": LESSONS}


TIMELINE = [
    {"time": "03/25 12:55PM", "event": "Bot Goes Live", "detail": "First trade placed — Hyperliquid Up/Down. Copy-trade strategy starts monitoring wallets.", "type": "neutral"},
    {"time": "03/25 02:19PM", "event": "Both-Sides Buying Spree", "detail": "Bot buys Up AND Down on Bitcoin, Ethereum, XRP simultaneously. -$15 in guaranteed losses.", "type": "bad"},
    {"time": "03/25 04:30PM", "event": "First Redemption Wave", "detail": "Several crypto markets resolve. Bot redeems winning sides but net negative due to both-sides trap.", "type": "neutral"},
    {"time": "03/25 08:00PM", "event": "Esports Losses Mount", "detail": "League of Legends and CS2 bets going sideways. Low liquidity means no exit.", "type": "bad"},
    {"time": "03/26 01:00AM", "event": "Weather Positions Open", "detail": "Bot enters multiple temperature markets. Large positions, long duration. $78+ committed.", "type": "neutral"},
    {"time": "03/26 09:00AM", "event": "Balance Hits Low Point", "detail": "USDC balance drops to ~$130. Crypto and sports losses eating capital.", "type": "bad"},
    {"time": "03/26 02:00PM", "event": "Both-Sides Filter Deployed", "detail": "Opposite-side detection goes live. No more buying Up and Down on same market.", "type": "fix"},
    {"time": "03/26 03:00PM", "event": "Category Multipliers Applied", "detail": "crypto=0.15x, sports=0.25x, weather=0.8x, politics=1.2x. Position sizes now category-aware.", "type": "fix"},
    {"time": "03/26 05:00PM", "event": "Exit Engine Deployed", "detail": "Stop-losses, stale exits, and trailing stops now active per category.", "type": "fix"},
    {"time": "03/26 06:00PM", "event": "Circuit Breakers Live", "detail": "Per-category daily loss limits: crypto -$10, sports -$15, weather -$25, politics -$35, global -$50.", "type": "fix"},
    {"time": "03/26 08:00PM", "event": "First Politics Winner", "detail": "Politics trade resolves profitable. Small but validates the category thesis.", "type": "good"},
    {"time": "03/27 06:00AM", "event": "All Logic Tied Together", "detail": "Wallet scorer, Kelly sizing, exit engine, circuit breakers — all category-aware and working in concert.", "type": "fix"},
    {"time": "03/27 07:00AM", "event": "Playbook Dashboard Deployed", "detail": "Complete trading analysis dashboard replaces old Kraken mission control. Every trade tracked, every lesson documented.", "type": "good"},
]

@app.get("/api/trading/timeline")
async def api_trading_timeline():
    """Key timeline events from the trading history."""
    return {"events": TIMELINE}


@app.get("/api/trading/copytrade")
async def api_trading_copytrade():
    """Copy-trade data — reads wallet cache and proxies to polymarket-bot copytrade endpoints."""
    import json as _json

    result = {
        "qualifying_wallets": 0,
        "top_wallets": [],
        "open_positions": [],
        "recent_copies": [],
        "status": "unknown",
        "last_scan_time": None,
    }

    # 1. Read the wallet cache file
    if COPYTRADE_WALLET_FILE.exists():
        try:
            with open(COPYTRADE_WALLET_FILE) as f:
                cache = _json.load(f)
            wallets = cache.get("wallets", [])
            result["qualifying_wallets"] = len(wallets)
            result["last_scan_time"] = cache.get("last_scan_time")
            # Sort by score descending, take top 10
            sorted_wallets = sorted(wallets, key=lambda w: w.get("score", 0), reverse=True)[:10]
            result["top_wallets"] = [
                {
                    "address": w.get("address", ""),
                    "win_rate": w.get("win_rate", 0),
                    "total_resolved": w.get("total_resolved", 0),
                    "wins": w.get("wins", 0),
                    "losses": w.get("losses", 0),
                    "total_volume": w.get("total_volume", 0),
                    "score": w.get("score", 0),
                }
                for w in sorted_wallets
            ]
            result["status"] = "monitoring"
        except (OSError, _json.JSONDecodeError) as exc:
            logger.warning("Failed to read copytrade wallet cache: %s", exc)

    # 2. Try to get live copytrade status from the bot
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TRADING_BOT_URL}/copytrade/status")
            if resp.status_code == 200:
                bot_data = resp.json()
                result["open_positions"] = bot_data.get("open_positions", [])
                result["recent_copies"] = bot_data.get("recent_copies", [])
                if bot_data.get("status"):
                    result["status"] = bot_data["status"]
    except Exception:
        pass  # Bot endpoint may not exist yet — that's fine

    return result


@app.get("/api/trading/bot-status")
async def api_trading_bot_status():
    """Proxy to the polymarket-bot /status and /strategies endpoints."""
    result = {"status": None, "strategies": None}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TRADING_BOT_URL}/status")
            if resp.status_code == 200:
                result["status"] = resp.json()
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TRADING_BOT_URL}/strategies")
            if resp.status_code == 200:
                result["strategies"] = resp.json()
    except Exception:
        pass
    return result


if __name__ == "__main__":
    event_server.init_db()
    logger.info("Mission Control starting on port %d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
