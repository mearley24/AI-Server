"""Mission Control — entrypoint that wraps event_server with health monitoring and dashboard."""

import asyncio
import json
import logging
import os
from collections import defaultdict
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
TRADING_DATA_FILE = Path("/trading-data/paper_trades.jsonl")
TRADING_BOT_URL = "http://vpn:8430"

# Service map: name -> (container_hostname, internal_port, external_port)
SERVICES = [
    {"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000},
    {"name": "Uptime Kuma", "host": "uptime-kuma", "port": 3001, "ext_port": 3001},
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


def _format_kalshi_ticker(ticker: str, title: str = "") -> str:
    """Convert raw Kalshi ticker like KXHIGHNY-26MAR25-B51.5 to human-readable name."""
    if title:
        return title.replace("**", "").replace("Will the ", "").replace("?", "").strip()

    parts = ticker.split("-")
    if len(parts) >= 3:
        series = parts[0]
        date_part = parts[1]
        strike_part = parts[2]

        cities = {"NY": "NYC", "CH": "Chicago", "LA": "LA", "DN": "Denver", "AT": "Atlanta", "MI": "Miami"}
        city = "Unknown"
        for code, name in cities.items():
            if series.endswith(code):
                city = name
                break

        date_str = date_part

        if strike_part.startswith("B"):
            temp = float(strike_part[1:])
            strike = f"{int(temp)}-{int(temp)+1}\u00b0F"
        elif strike_part.startswith("T"):
            temp = float(strike_part[1:])
            if "LOW" in series.upper():
                strike = f"<{int(temp)}\u00b0F"
            else:
                strike = f"{int(temp)}\u00b0F"
        else:
            strike = strike_part

        metric = "Low" if "LOW" in series.upper() else "High"
        return f"{city} {metric} {strike} ({date_str})"

    return ticker


def _get_display_name(pair: str, trades_for_pair: list) -> str:
    """Get a human-readable display name for a trading pair."""
    # Already readable crypto pairs
    if "/" in pair and not pair.startswith("KX"):
        return pair

    # Kalshi weather ticker
    if pair.startswith("KX"):
        # Try to get title from one of the trades
        title = ""
        for t in trades_for_pair:
            mq = t.get("market_question", "")
            if mq and "spot trade" not in mq.lower():
                title = mq
                break
        return _format_kalshi_ticker(pair, title)

    # Crypto with " spot trade" suffix already stripped via market_question
    # These are already readable (e.g., "XRP/USDT")
    return pair


def _parse_trades():
    """Read paper_trades.jsonl and return list of trade dicts."""
    trades = []
    if not TRADING_DATA_FILE.exists():
        return trades
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
    return trades


def _calculate_pnl(trades):
    """Calculate P&L by matching BUY/SELL pairs within 1 second per pair."""
    pair_data = defaultdict(lambda: {"buys": [], "sells": [], "raw_trades": []})
    for t in trades:
        # Extract pair from market_id or market_question (strip " spot trade" suffix)
        pair = t.get("market_id") or ""
        if not pair:
            mq = t.get("market_question", "")
            pair = mq.replace(" spot trade", "") if mq else "UNKNOWN"
        pair = pair or "UNKNOWN"
        side = (t.get("side") or "").upper()
        price = float(t.get("price", 0))
        size = float(t.get("size") or t.get("quantity") or t.get("amount", 0))
        ts_raw = t.get("timestamp") or t.get("time", "")
        try:
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw)
            else:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except (ValueError, AttributeError, OSError):
            ts = None
        entry = {"price": price, "size": size, "ts": ts, "raw": t}
        pair_data[pair]["raw_trades"].append(t)
        if side == "BUY":
            pair_data[pair]["buys"].append(entry)
        elif side == "SELL":
            pair_data[pair]["sells"].append(entry)

    pairs_result = {}
    total_pnl = 0.0
    for pair, data in pair_data.items():
        buys = sorted(data["buys"], key=lambda x: x["ts"] or datetime.min)
        sells = sorted(data["sells"], key=lambda x: x["ts"] or datetime.min)
        buy_prices = [b["price"] for b in buys]
        sell_prices = [s["price"] for s in sells]
        avg_buy = sum(buy_prices) / len(buy_prices) if buy_prices else 0
        avg_sell = sum(sell_prices) / len(sell_prices) if sell_prices else 0

        # Match BUY/SELL pairs by timestamp proximity (within 1 second)
        matched_pnl = 0.0
        matched_count = 0
        used_sells = set()
        for b in buys:
            if b["ts"] is None:
                continue
            for j, s in enumerate(sells):
                if j in used_sells or s["ts"] is None:
                    continue
                delta = abs((s["ts"] - b["ts"]).total_seconds())
                if delta <= 1.0:
                    spread = s["price"] - b["price"]
                    size = min(b["size"], s["size"])
                    matched_pnl += spread * size
                    matched_count += 1
                    used_sells.add(j)
                    break

        spread_capture = avg_sell - avg_buy if avg_buy > 0 else 0
        display_name = _get_display_name(pair, data["raw_trades"])
        pairs_result[pair] = {
            "display_name": display_name,
            "buys": len(buys),
            "sells": len(sells),
            "avg_buy": round(avg_buy, 6),
            "avg_sell": round(avg_sell, 6),
            "spread_capture": round(spread_capture, 6),
            "estimated_pnl": round(matched_pnl, 4),
            "matched_rounds": matched_count,
        }
        total_pnl += matched_pnl

    return pairs_result, round(total_pnl, 4)


@app.get("/api/trading")
async def api_trading():
    """Trading dashboard data — reads paper_trades.jsonl, calculates P&L."""
    trades = _parse_trades()
    if not trades:
        return {
            "total_trades": 0,
            "buy_trades": 0,
            "sell_trades": 0,
            "first_trade_at": None,
            "last_trade_at": None,
            "pairs": {},
            "recent_trades": [],
            "total_pnl": 0,
        }

    buy_count = sum(1 for t in trades if (t.get("side") or "").upper() == "BUY")
    sell_count = sum(1 for t in trades if (t.get("side") or "").upper() == "SELL")

    timestamps = []
    for t in trades:
        ts_raw = t.get("timestamp") or t.get("time", "")
        if ts_raw:
            timestamps.append(ts_raw)
    timestamps.sort()

    pairs_result, total_pnl = _calculate_pnl(trades)

    # Build display name lookup: raw pair key -> display_name
    display_names = {k: v["display_name"] for k, v in pairs_result.items()}

    # Enrich recent trades with display_name
    recent = []
    for t in trades[-50:][::-1]:
        entry = dict(t)
        pair = t.get("market_id") or ""
        if not pair:
            mq = t.get("market_question", "")
            pair = mq.replace(" spot trade", "") if mq else "UNKNOWN"
        pair = pair or "UNKNOWN"
        entry["display_name"] = display_names.get(pair, pair)
        recent.append(entry)

    return {
        "total_trades": len(trades),
        "buy_trades": buy_count,
        "sell_trades": sell_count,
        "first_trade_at": timestamps[0] if timestamps else None,
        "last_trade_at": timestamps[-1] if timestamps else None,
        "pairs": pairs_result,
        "recent_trades": recent,
        "total_pnl": total_pnl,
    }


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
