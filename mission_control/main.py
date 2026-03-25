"""Mission Control — entrypoint that wraps event_server with health monitoring and dashboard."""

import asyncio
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
TRADING_DATA_FILE = Path("/trading-data/paper_trades.jsonl")
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
    """Trading dashboard data — proxies to polymarket-bot live endpoints."""
    empty = {
        "total_trades": 0,
        "buy_trades": 0,
        "sell_trades": 0,
        "first_trade_at": None,
        "last_trade_at": None,
        "pairs": {},
        "recent_trades": [],
        "total_pnl": 0,
    }

    trades = []
    pnl_data = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TRADING_BOT_URL}/paper-trades", params={"limit": 50})
            if resp.status_code == 200:
                trades = resp.json().get("trades", [])
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TRADING_BOT_URL}/pnl")
            if resp.status_code == 200:
                pnl_data = resp.json()
    except Exception:
        pass

    if not trades and not pnl_data:
        return empty

    buy_count = sum(1 for t in trades if (t.get("side") or "").upper() == "BUY")
    sell_count = sum(1 for t in trades if (t.get("side") or "").upper() == "SELL")

    timestamps = []
    for t in trades:
        ts_raw = t.get("timestamp") or t.get("time", "")
        if ts_raw:
            timestamps.append(str(ts_raw))
    timestamps.sort()

    # Build pairs breakdown from pnl_data if available
    pairs = {}
    total_pnl = 0.0
    if pnl_data:
        total_pnl = float(pnl_data.get("total_pnl", 0))
        # Expose per-pair stats if the bot provides them
        for pair_key, info in pnl_data.get("pairs", {}).items():
            pairs[pair_key] = {
                "display_name": info.get("display_name", pair_key),
                "buys": info.get("buys", 0),
                "sells": info.get("sells", 0),
                "avg_buy": info.get("avg_buy", 0),
                "avg_sell": info.get("avg_sell", 0),
                "spread_capture": info.get("spread_capture", 0),
                "estimated_pnl": info.get("estimated_pnl", info.get("pnl", 0)),
                "matched_rounds": info.get("matched_rounds", 0),
            }

    # If pnl_data didn't have per-pair breakdown, build a simple one from trades
    if not pairs and trades:
        from collections import defaultdict as _dd
        pair_buckets = _dd(lambda: {"buys": 0, "sells": 0})
        for t in trades:
            pair = (t.get("market_question") or t.get("market_id") or "UNKNOWN").replace(" spot trade", "")
            side = (t.get("side") or "").upper()
            if side == "BUY":
                pair_buckets[pair]["buys"] += 1
            elif side == "SELL":
                pair_buckets[pair]["sells"] += 1
        for pair, counts in pair_buckets.items():
            pairs[pair] = {
                "display_name": pair,
                "buys": counts["buys"],
                "sells": counts["sells"],
                "avg_buy": 0,
                "avg_sell": 0,
                "spread_capture": 0,
                "estimated_pnl": 0,
                "matched_rounds": 0,
            }

    # Build display name lookup
    display_names = {k: v["display_name"] for k, v in pairs.items()}

    # Enrich recent trades with display_name
    recent = []
    for t in trades[:50]:
        entry = dict(t)
        pair = (t.get("market_question") or t.get("market_id") or "UNKNOWN").replace(" spot trade", "")
        entry["display_name"] = display_names.get(pair, pair)
        recent.append(entry)

    return {
        "total_trades": pnl_data.get("trade_count", len(trades)) if pnl_data else len(trades),
        "buy_trades": buy_count,
        "sell_trades": sell_count,
        "first_trade_at": timestamps[0] if timestamps else None,
        "last_trade_at": timestamps[-1] if timestamps else None,
        "pairs": pairs,
        "recent_trades": recent,
        "total_pnl": total_pnl,
    }


@app.get("/api/trading/paper")
async def api_trading_paper():
    """Paper trading data — reads paper_trades.jsonl for Polymarket/Kalshi paper strategies."""
    trades = []
    if TRADING_DATA_FILE.exists():
        try:
            with open(TRADING_DATA_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            trades.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

    if not trades:
        return {"total_trades": 0, "strategies": {}, "recent_trades": [], "total_pnl": 0}

    # Group by strategy
    from collections import defaultdict
    strats: dict[str, list] = defaultdict(list)
    for t in trades:
        s = t.get("strategy", "unknown")
        strats[s].append(t)

    strategy_summary = {}
    total_pnl = 0.0
    for name, strades in strats.items():
        buys = sum(1 for t in strades if (t.get("side") or "").upper() == "BUY")
        sells = sum(1 for t in strades if (t.get("side") or "").upper() == "SELL")
        profitable = sum(1 for t in strades if t.get("would_have_profited"))
        scored = sum(1 for t in strades if t.get("scored_at") is not None)
        strategy_summary[name] = {
            "trades": len(strades),
            "buys": buys,
            "sells": sells,
            "scored": scored,
            "profitable": profitable,
            "win_rate": round(profitable / scored, 3) if scored > 0 else None,
        }

    recent = []
    for t in trades[-20:][::-1]:
        entry = dict(t)
        pair = (t.get("market_question") or t.get("market_id") or "UNKNOWN").replace(" spot trade", "")
        entry["display_name"] = pair
        recent.append(entry)

    return {
        "total_trades": len(trades),
        "strategies": strategy_summary,
        "recent_trades": recent,
        "total_pnl": total_pnl,
    }


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
