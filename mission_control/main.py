"""Mission Control — entrypoint that wraps event_server with health monitoring and dashboard."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import redis
import httpx
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8098"))
STATIC_DIR = Path(__file__).parent / "static"
TRADING_BOT_URL = "http://vpn:8430"
COPYTRADE_WALLET_FILE = Path("/trading-data/copytrade_wallets.json")
WALLET_ADDRESS = "0xa791e3090312981a1e18ed93238e480a03e7c0d2"

# ── Redis helper ──
_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        try:
            _redis = redis.from_url(
                os.environ.get("REDIS_URL", "redis://redis:6379"),
                decode_responses=True,
                socket_timeout=2,
            )
        except Exception:
            pass
    return _redis


# Service map: name -> (container_hostname, internal_port, external_port)
# compose = docker compose service name for `docker compose restart <compose>` on the AI-Server host
SERVICES = [
    {"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000, "compose": "openwebui"},
    {"name": "Remediator", "host": "remediator", "port": 8090, "ext_port": 8090, "compose": "remediator", "optional": True},
    {"name": "Proposals", "host": "proposals", "port": 8091, "ext_port": 8091, "compose": "proposals"},
    {"name": "Email Monitor", "host": "email-monitor", "port": 8092, "ext_port": 8092, "compose": "email-monitor"},
    {"name": "Voice Receptionist", "host": "voice-receptionist", "port": 3000, "ext_port": 8093, "compose": "voice-receptionist"},
    {"name": "Calendar Agent", "host": "calendar-agent", "port": 8094, "ext_port": 8094, "compose": "calendar-agent"},
    {"name": "Notification Hub", "host": "notification-hub", "port": 8095, "ext_port": 8095, "compose": "notification-hub"},
    {"name": "D-Tools Bridge", "host": "dtools-bridge", "port": 5050, "ext_port": 8096, "compose": "dtools-bridge"},
    {"name": "ClawWork", "host": "clawwork", "port": 8097, "ext_port": 8097, "compose": "clawwork", "optional": True},
    {"name": "Polymarket Bot", "host": "vpn", "port": 8430, "ext_port": 8430, "compose": "polymarket-bot", "compose_alt": "vpn"},
    {"name": "OpenClaw", "host": "openclaw", "port": 3000, "ext_port": 8099, "compose": "openclaw"},
    {"name": "Knowledge Scanner", "host": "knowledge-scanner", "port": 8100, "ext_port": 8100, "compose": "knowledge-scanner"},
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
                return {
                    "name": service["name"],
                    "status": "healthy",
                    "port": service["ext_port"],
                    "details": details,
                    "compose": service.get("compose"),
                    "compose_alt": service.get("compose_alt"),
                    "health_path": "/health",
                }
            else:
                return {
                    "name": service["name"],
                    "status": "degraded",
                    "port": service["ext_port"],
                    "details": {"http_status": resp.status_code},
                    "compose": service.get("compose"),
                    "compose_alt": service.get("compose_alt"),
                    "health_path": "/health",
                }
    except Exception:
        return {
            "name": service["name"],
            "status": "down",
            "port": service["ext_port"],
            "details": {},
            "compose": service.get("compose"),
            "compose_alt": service.get("compose_alt"),
            "health_path": "/health",
        }


# Import the existing event_server — but override DB path before init
import event_server
data_dir = Path(os.getenv("DATA_DIR", "/data"))
data_dir.mkdir(parents=True, exist_ok=True)
event_server.DB_PATH = data_dir / "events.db"
event_server.STATIC_DIR = STATIC_DIR

# Re-use the existing app from event_server (has WebSocket, events, status, digest)
app = event_server.app

# ── Auth middleware — protects LAN-exposed dashboard ──
_MC_TOKEN = os.getenv("MISSION_CONTROL_TOKEN", "").strip()

if _MC_TOKEN:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse as StarletteJSONResponse

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path == "/health" or path.startswith("/health"):
                return await call_next(request)
            token = request.query_params.get("token", "")
            if not token:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    token = auth[7:].strip()
            if token != _MC_TOKEN:
                return StarletteJSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(_AuthMiddleware)
    logger.info("Mission Control auth enabled (token required on all endpoints except /health)")

# ── Add new routes ──

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mission-control"}


@app.get("/api/services")
async def api_services():
    """Check health of all services."""
    results = await asyncio.gather(*[check_service_health(s) for s in SERVICES])
    now = datetime.now().isoformat()
    for i, r in enumerate(results):
        r["checked_at"] = now
        r["optional"] = bool(SERVICES[i].get("optional"))
    core = [r for r in results if not r.get("optional")]
    optional = [r for r in results if r.get("optional")]
    h = sum(1 for r in results if r["status"] == "healthy")
    hc = sum(1 for r in core if r["status"] == "healthy")
    ho = sum(1 for r in optional if r["status"] == "healthy")
    return {
        "services": results,
        "total": len(results),
        "healthy": h,
        "total_core": len(core),
        "healthy_core": hc,
        "optional_total": len(optional),
        "optional_healthy": ho,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the ops dashboard (legacy)."""
    html_path = STATIC_DIR / "ops.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Dashboard not found</h1>")


@app.get("/ops", response_class=HTMLResponse)
async def ops_page():
    """Serve the legacy ops dashboard."""
    html_path = STATIC_DIR / "ops.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Ops dashboard not found</h1>")


@app.get("/api/wallet")
async def api_wallet():
    """Portfolio wallet summary with categorized position breakdown.

    Returns liquid USDC, active position value (tradeable only),
    redeemable wins (free money awaiting redemption), and lost/dust counts.
    """
    empty = {
        "usdc_balance": 0.0, "position_value": 0.0,
        "active_value": 0.0, "redeemable_value": 0.0, "redeemable_count": 0,
        "lost_count": 0, "dust_count": 0,
        "daily_pnl": 0.0, "weekly_pnl": 0.0, "error": "unavailable",
    }
    try:
        r = _get_redis()
        if r:
            try:
                snap = r.get("portfolio:snapshot")
                if snap:
                    data = json.loads(snap)
                    # Ensure categorized fields are present (backwards compat)
                    for key in ("active_value", "redeemable_value", "redeemable_count", "lost_count", "dust_count"):
                        data.setdefault(key, 0)
                    return data
            except Exception:
                pass
        # Fallback: HTTP to polymarket-bot
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://polymarket-bot:8430/status")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "usdc_balance": float(data.get("usdc_balance", 0)),
                    "position_value": float(data.get("position_value", 0)),
                    "active_value": float(data.get("active_value", 0)),
                    "redeemable_value": float(data.get("redeemable_value", 0)),
                    "redeemable_count": int(data.get("redeemable_count", 0)),
                    "lost_count": int(data.get("lost_count", 0)),
                    "dust_count": int(data.get("dust_count", 0)),
                    "daily_pnl": float(data.get("daily_pnl", 0)),
                    "weekly_pnl": float(data.get("weekly_pnl", 0)),
                }
    except Exception:
        pass
    return empty


@app.get("/api/positions")
async def api_positions():
    """Open positions — Redis first, polymarket-bot fallback."""
    try:
        r = _get_redis()
        if r:
            try:
                raw = r.get("portfolio:positions")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://polymarket-bot:8430/positions")
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("positions", [])
    except Exception:
        pass
    return []


@app.get("/api/pnl-series")
async def api_pnl_series():
    """P&L time series — from Redis portfolio:pnl_series."""
    try:
        r = _get_redis()
        if r:
            try:
                raw = r.get("portfolio:pnl_series")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
    except Exception:
        pass
    return []


@app.get("/api/activity")
async def api_activity():
    """Recent trading activity — from Redis events:trading list."""
    try:
        r = _get_redis()
        if r:
            try:
                entries = r.lrange("events:trading", 0, 49)
                if entries:
                    result = []
                    for entry in entries:
                        try:
                            result.append(json.loads(entry))
                        except Exception:
                            result.append({"timestamp": "", "type": "info", "message": str(entry)})
                    return result
            except Exception:
                pass
        # Fallback: recent activity via polymarket-bot /status
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://polymarket-bot:8430/status")
                if resp.status_code == 200:
                    data = resp.json()
                    logs = data.get("recent_activity", data.get("logs", []))
                    if logs:
                        return logs
        except Exception:
            pass
    except Exception:
        pass
    return []


@app.get("/trading", response_class=HTMLResponse)
async def trading_page():
    """Serve the main trading dashboard (index.html)."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Trading dashboard not found</h1>")


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


# Category multipliers — aligned with playbook lessons (Kelly / risk posture)
CATEGORY_MULTIPLIERS = {
    "crypto": 1.2,
    "crypto_updown": 0.15,
    "sports": 0.25,
    "esports": 0.5,
    "weather": 0.8,
    "politics": 1.5,
    "economics": 1.0,
    "geopolitics": 1.0,
    "entertainment": 1.0,
    "science": 1.0,
    "culture": 1.0,
    "legal": 1.0,
    "health": 1.0,
    "energy": 1.0,
    "other": 1.0,
}


def _categorize(title: str) -> str:
    """Assign a market category from title keywords (split 'other'; playbook-aligned)."""
    t = (title or "").lower()

    if any(u in t for u in ("up or down", "up/down")):
        if any(
            tok in t
            for tok in (
                "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp",
                "bnb", "dogecoin", "doge", "hyperliquid",
            )
        ) or any(
            m in t
            for m in (
                "5m", "5 m", "5-minute", "5 minute", "15m", "15 m", "15-minute", "15 minute",
                "1h", "1 h", "minute", "min:", "pm et", "am et",
            )
        ):
            return "crypto_updown"

    if any(
        k in t
        for k in [
            "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp",
            "crypto", "bnb", "hyperliquid", "dogecoin", "doge",
            "dip to", "price of solana", "price of bitcoin", "price of ethereum",
            "price of xrp",
        ]
    ):
        return "crypto"

    if any(k in t for k in [
        "temperature", "weather", "rain", "celsius", "fahrenheit",
        "\u00b0c", "\u00b0f", "highest temp",
    ]):
        return "weather"

    if any(k in t for k in [
        "president", "election", "congress", "senate", "trump", "biden",
        "governor", "democrat", "republican", "prime minister", "ndp",
        "leadership election", "talarico", "cornyn", "avi lewis",
        "canadian", "magyar", "hungary",
    ]):
        return "politics"

    if any(k in t for k in [
        "counter-strike", "cs2", "cs:go", "csgo", "league of legends", "lol:", "lol ",
        "valorant", "dota", "dota 2", "esports", "cblol", "overwatch", "starcraft",
        "rocket league", "arena of valor", "riot games", "esl",
    ]):
        return "esports"

    if any(k in t for k in [
        "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
        "tennis", "golf", "ufc", "vs.", "win on", "spread:", "split:", "celtics", "hornets", "penguins",
        "senators", "ducks", "flames", "nuggets", "ncaa", "tournament",
        "hart memorial", "mcdavid", "charleston open", "boilermakers", "alicante", "carreno",
        "kalieva", "urhobo", "bo3", "match", " vs ",
        "real racing", "liberia", "benin", "italy win", "france win",
        "ghana", "austria", "o/u ", "f1 ", "grand prix",
        "pole position", "leclerc", "hamilton", "verstappen",
    ]):
        return "sports"

    if any(k in t for k in [
        "openai", "anthropic", "gpt", "gpt-4", "gpt-5", "claude", "llm", "agi", "artificial intelligence",
        "spacex", "nasa", " mars", " moon", "rocket", "moon landing", "telescope",
        "asteroid", "satellite", "nobel", "scientific",
    ]):
        return "science"

    if any(k in t for k in [
        "oscar", "grammy", "emmy", "golden globe", "billboard", "box office", "grossing",
    ]):
        return "culture"

    if any(k in t for k in [
        "mrbeast", "youtube", "views", "subscribers", "tiktok",
    ]):
        return "entertainment"

    if any(k in t for k in [
        "fed ", "interest rate", "inflation", "gdp", "fomc",
        "ipo market cap", "ipo",
    ]):
        return "economics"

    if any(k in t for k in [
        "war", "conflict", "nato", "iran", "israel", "houthi",
        "ceasefire", "strike on", "putin",
    ]):
        return "geopolitics"

    if any(k in t for k in [
        "sec ", "lawsuit", "indict", "trial", "court", "doj", "ftc", "subpoena", "appeal",
    ]):
        return "legal"

    if any(k in t for k in [
        "fda", "vaccine", "clinical trial", "cdc ", "pandemic", "covid",
    ]):
        return "health"

    if any(k in t for k in [
        "opec", "oil", "crude", "wti", "brent", "natural gas", "gas price", "barrel",
    ]):
        return "energy"

    return "other"


_categories_cache: dict = {"data": None, "fetched_at": 0}


async def _fetch_all_polymarket_positions(client: httpx.AsyncClient) -> list:
    """Paginate /positions — default API page size is small; we need every open position."""
    positions: list = []
    offset = 0
    limit = 500
    while True:
        pos_resp = await client.get(
            "https://data-api.polymarket.com/positions",
            params={"user": WALLET_ADDRESS, "limit": limit, "offset": offset},
        )
        pos_resp.raise_for_status()
        batch = pos_resp.json()
        if not batch:
            break
        positions.extend(batch)
        if len(batch) < limit:
            break
        offset += len(batch)
    return positions


async def _fetch_polymarket_data() -> tuple[list, list]:
    """Fetch both positions and full activity history from Polymarket."""
    async with httpx.AsyncClient(timeout=45.0) as client:
        positions = await _fetch_all_polymarket_positions(client)

        # Fetch ALL activity history (buys, sells, redeems)
        activities = []
        offset = 0
        while True:
            act_resp = await client.get(
                "https://data-api.polymarket.com/activity",
                params={"user": WALLET_ADDRESS, "limit": 1000, "offset": offset},
            )
            act_resp.raise_for_status()
            batch = act_resp.json()
            if not batch:
                break
            activities.extend(batch)
            if len(batch) < 1000:
                break
            offset += len(batch)

        return positions, activities


@app.get("/api/trading/categories")
async def api_trading_categories(nocache: bool = Query(False, description="Bypass 5-minute cache")):
    """Category P/L — combines activity history (buys/sells/redeems) with open positions. Cached 5 min."""
    now = time.time()
    if (
        not nocache
        and _categories_cache["data"]
        and now - _categories_cache["fetched_at"] < 300
    ):
        return _categories_payload_with_hints(_categories_cache["data"])

    try:
        positions, activities = await _fetch_polymarket_data()

        # ── Activity-based stats (complete buy/sell/redeem history) ──
        from collections import defaultdict
        cat_bought = defaultdict(float)
        cat_sold = defaultdict(float)
        cat_redeemed = defaultdict(float)
        cat_buy_count = defaultdict(int)
        cat_sell_count = defaultdict(int)
        cat_redeem_count = defaultdict(int)

        # Sort by timestamp to compute deposits
        activities.sort(key=lambda a: a.get("timestamp", 0))

        for a in activities:
            cat = _categorize(a.get("title", ""))
            usdc = a.get("usdcSize", 0) or 0
            if a["type"] == "TRADE":
                if a.get("side") == "BUY":
                    cat_bought[cat] += usdc
                    cat_buy_count[cat] += 1
                elif a.get("side") == "SELL":
                    cat_sold[cat] += usdc
                    cat_sell_count[cat] += 1
            elif a["type"] == "REDEEM":
                cat_redeemed[cat] += usdc
                cat_redeem_count[cat] += 1

        # ── Estimate total deposits by tracking when cash goes negative ──
        running_cash = 0.0
        min_cash = 0.0
        estimated_deposits = 0.0
        for a in activities:
            usdc = a.get("usdcSize", 0) or 0
            if a["type"] == "TRADE":
                if a.get("side") == "BUY":
                    running_cash -= usdc
                elif a.get("side") == "SELL":
                    running_cash += usdc
            elif a["type"] == "REDEEM":
                running_cash += usdc
            if running_cash < min_cash:
                estimated_deposits += min_cash - running_cash
                min_cash = running_cash

        # ── Open positions from /positions endpoint ──
        # Do NOT filter by curPrice band: API uses values like 0.0005 and 0.9995 for live
        # positions; the old 0.001–0.999 rule dropped almost everything.
        cat_open_value = defaultdict(float)
        cat_open_count = defaultdict(int)
        for p in positions:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue
            current_value = float(p.get("currentValue") or 0)
            if current_value <= 0:
                continue
            cat = _categorize(p.get("title", ""))
            cat_open_value[cat] += current_value
            cat_open_count[cat] += 1

        # ── Combine into category stats ──
        all_cats = set(
            list(cat_bought.keys()) + list(cat_sold.keys())
            + list(cat_redeemed.keys()) + list(cat_open_value.keys())
        )

        categories: dict = {}
        total_bought_all = 0.0
        total_returned_all = 0.0
        total_open_all = 0.0
        total_pnl_all = 0.0
        total_trades_all = 0

        for cat in all_cats:
            bought = cat_bought[cat]
            sold = cat_sold[cat]
            redeemed = cat_redeemed[cat]
            returned = sold + redeemed
            open_val = cat_open_value[cat]
            # P/L = (returned + current open value) - total bought
            pnl = round((returned + open_val) - bought, 2)
            trades = cat_buy_count[cat] + cat_sell_count[cat] + cat_redeem_count[cat]  # noqa: F841
            multiplier = CATEGORY_MULTIPLIERS.get(cat, 1.0)

            categories[cat] = {
                "total_pnl": pnl,
                "trades": cat_buy_count[cat],  # number of entries (buys)
                "bought": round(bought, 2),
                "sold": round(sold, 2),
                "redeemed": round(redeemed, 2),
                "returned": round(returned, 2),
                "open_value": round(open_val, 2),
                "open_count": cat_open_count[cat],
                "multiplier": multiplier,
                "status": "profit" if pnl >= 0 else "loss",
            }

            total_bought_all += bought
            total_returned_all += returned
            total_open_all += open_val
            total_pnl_all += pnl
            total_trades_all += cat_buy_count[cat]

        # True P/L = current account value - deposits
        account_value = total_open_all  # cash is $0
        true_pnl = round(account_value - estimated_deposits, 2)

        result = {
            "categories": categories,
            "summary": {
                "estimated_deposits": round(estimated_deposits, 2),
                "total_deployed": round(total_bought_all, 2),
                "total_returned": round(total_returned_all, 2),
                "open_value": round(total_open_all, 2),
                "net_pnl": round(true_pnl, 2),
                "total_trades": total_trades_all,
                "activity_count": len(activities),
            },
            "as_of": datetime.now().isoformat(),
            "source": "live",
        }

        _categories_cache["data"] = result
        _categories_cache["fetched_at"] = now
        return _categories_payload_with_hints(result)

    except Exception as exc:
        logger.warning("Polymarket API fetch failed: %s", exc)
        return _categories_payload_with_hints({
            "categories": {},
            "summary": {},
            "as_of": datetime.now().isoformat(),
            "source": "error",
            "error": str(exc),
        })


@app.get("/api/trading/positions")
async def api_trading_positions():
    """Slim Polymarket positions for the Trading view (same proxy wallet as category P/L)."""
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            raw = await _fetch_all_polymarket_positions(client)
        slim: list = []
        for p in raw:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue
            cv = float(p.get("currentValue") or 0)
            if cv <= 0:
                continue
            slim.append(
                {
                    "title": p.get("title") or "",
                    "outcome": p.get("outcome") or "",
                    "size": round(size, 4),
                    "currentValue": round(cv, 4),
                    "curPrice": p.get("curPrice"),
                    "cashPnl": p.get("cashPnl"),
                    "avgPrice": p.get("avgPrice"),
                    "slug": p.get("slug"),
                }
            )
        slim.sort(key=lambda x: -x["currentValue"])
        return {
            "positions": slim,
            "count": len(slim),
            "as_of": datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.warning("Polymarket positions list failed: %s", exc)
        return {
            "positions": [],
            "count": 0,
            "error": str(exc),
            "as_of": datetime.now().isoformat(),
        }


LESSONS = [
    {
        "title": "Both-Sides Buying Trap",
        "severity": "critical",
        "loss": 0,
        "category": "crypto_updown",
        "description": "The bot was buying BOTH Up and Down outcomes on the same crypto market simultaneously. When copying wallets that took opposite sides, we'd pay $1 (full price) for what resolves to $1 — guaranteed loss after fees. This was the single biggest money pit.",
        "fix": "Implemented opposite-side detection: before buying any outcome, check if we already hold the opposite side. If so, skip the trade entirely. Also added same-market deduplication within 60-second windows.",
        "example": "Bitcoin Up or Down March 25: Bot bought 'Up' at $0.64 AND 'Down' at $0.36 from different wallets. Combined cost: $1.00 for a $1.00 payout — net loss after fees every time."
    },
    {
        "title": "Crypto 5-Minute Markets Are Coin Flips",
        "severity": "critical",
        "loss": 0,
        "category": "crypto_updown",
        "description": "Short-duration crypto up/down markets (5-minute, 15-minute) are essentially random. No wallet has consistent edge on these. The bot was copying wallets that appeared profitable but were just lucky in small samples.",
        "fix": "Reduced crypto_updown multiplier to 0.15x (smallest positions). Added minimum market duration filter. Price bounds tightened to 0.15-0.90 to avoid extreme odds.",
        "example": "Ethereum Up or Down 4:15-4:20PM: 5-minute window, pure noise. Bot bought 'Up' at $0.95 — paying near-max for a coin flip."
    },
    {
        "title": "Esports Low-Liquidity Trap",
        "severity": "high",
        "loss": 0,
        "category": "esports",
        "description": "Esports markets had very low liquidity and wide spreads. The bot was copying wallets into markets where exit was nearly impossible. Most positions expired worthless because the markets were too thin to sell before resolution.",
        "fix": "Applied 0.5x reduction factor for esports. Sports multiplier lowered to 0.25x. Added per-category circuit breakers: sports stops at -$15 daily loss.",
        "example": "Multiple League of Legends and CS2 match markets — bot entered at unfavorable prices, couldn't exit, and most resolved as losses."
    },
    {
        "title": "Weather Positions Still Open",
        "severity": "medium",
        "loss": 0,
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
        "loss": +2.85,
        "category": "politics",
        "description": "Politics markets are the only category that's profitable. They have better liquidity, longer durations, and wallets with genuine information edges. The bot performs best here.",
        "fix": "Increased politics multiplier to 1.2x (highest). Circuit breaker set generously at -$35. Longer stale exit (96h) and wider trailing stop (20%) to let positions develop.",
        "example": "Multiple Trump/Biden policy markets where copied wallets had genuine political insight — small but consistent profits."
    },
    {
        "title": "Neg Risk Redemption Requires NegRiskAdapter",
        "severity": "critical",
        "loss": -110.0,
        "category": "all",
        "description": "$110 in winning positions were stuck because the redeemer was calling CTF.redeemPositions directly. Neg risk markets require NegRiskAdapter.redeemPositions(conditionId, amounts) with [0, balance] for No tokens or [balance, 0] for Yes tokens.",
        "fix": "Redeemer now detects negativeRisk flag from the Data API and routes through NegRiskAdapter automatically. All 11 stuck positions recovered.",
        "example": "Shanghai 15\u00b0C: 15.47 shares sitting unredeemed for 2 days. Standard CTF calls succeeded (status=OK) but returned $0. NegRiskAdapter call recovered $15.47 instantly."
    }
]


def _playbook_hints_for_categories() -> dict:
    """Group playbook LESSONS by category for the Categories API (skip ``all``)."""
    from collections import defaultdict

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for L in LESSONS:
        cat = (L.get("category") or "other").strip()
        if cat == "all":
            continue
        by_cat[cat].append({
            "title": L.get("title"),
            "severity": L.get("severity"),
            "lesson": L.get("description"),
            "fix": L.get("fix"),
            "loss": L.get("loss"),
        })
    return dict(sorted(by_cat.items()))


def _categories_payload_with_hints(payload: dict) -> dict:
    """Attach static playbook hints (derived from LESSONS) to categories API responses."""
    out = dict(payload)
    out["playbook_hints"] = _playbook_hints_for_categories()
    return out


# ── Email, Calendar, Follow-ups, System endpoints ──

@app.get("/api/emails")
async def api_emails():
    """Proxy to email-monitor for recent emails."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for path in ["/emails/recent", "/api/emails", "/emails"]:
                try:
                    resp = await client.get(f"http://email-monitor:8092{path}")
                    if resp.status_code == 200:
                        data = resp.json()
                        emails = data if isinstance(data, list) else data.get("emails", data.get("recent", []))
                        unread = sum(1 for e in emails if not e.get("read") and not e.get("processed"))
                        return {"emails": emails[:20], "unread_count": unread}
                except Exception:
                    continue
    except Exception:
        pass
    return {"emails": [], "unread_count": 0}


@app.get("/api/calendar")
async def api_calendar():
    """Proxy to calendar-agent for today's events."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for path in ["/calendar/today", "/api/events", "/events", "/calendar"]:
                try:
                    resp = await client.get(f"http://calendar-agent:8094{path}")
                    if resp.status_code == 200:
                        data = resp.json()
                        events = data if isinstance(data, list) else data.get("events", data.get("upcoming", []))
                        return {"events": events}
                except Exception:
                    continue
    except Exception:
        pass
    return {"events": []}


@app.get("/api/followups")
async def api_followups():
    """Proxy to OpenClaw for pending follow-ups / jobs."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for path in ["/api/jobs", "/api/tasks", "/jobs", "/tasks"]:
                try:
                    resp = await client.get(f"http://openclaw:3000{path}")
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data if isinstance(data, list) else data.get("followups", data.get("jobs", data.get("tasks", [])))
                        overdue = sum(1 for i in items if i.get("overdue"))
                        return {"followups": items, "overdue_count": overdue}
                except Exception:
                    continue
    except Exception:
        pass
    return {"followups": [], "overdue_count": 0}


@app.get("/api/intelligence")
async def api_intelligence_summary():
    """Proxy OpenClaw intelligence summary (Settings quick link)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://openclaw:3000/intelligence/summary")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("api_intelligence_summary: %s", e)
    return {"error": "unavailable"}


@app.get("/api/decisions/recent")
async def api_decisions_recent(hours: int = Query(48, ge=1, le=720), limit: int = Query(20, ge=1, le=100)):
    """Proxy OpenClaw recent decisions (Settings quick link)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "http://openclaw:3000/intelligence/decisions/recent",
                params={"hours": hours, "limit": limit},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("api_decisions_recent: %s", e)
    return {"decisions": [], "error": "unavailable"}


@app.get("/api/events-log")
async def api_events_log(limit: int = 50):
    """Proxy to OpenClaw: Redis ``events:log`` audit trail (orchestrator + bus)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "http://openclaw:3000/intelligence/events-log",
                params={"limit": min(max(limit, 1), 200)},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("api_events_log: %s", e)
    return {"events": [], "count": 0, "error": "unavailable"}


@app.get("/api/system")
async def api_system():
    """System resource info + employee status. Reads /proc inside container."""
    result = {
        "cpu_percent": None,
        "memory_percent": None,
        "disk_percent": None,
        "containers": [],
        "employees": event_server.manager.employee_status,
        "connections": len(event_server.manager.active_connections),
    }
    # Disk (works in any Linux container)
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        result["disk_percent"] = round(used / total * 100, 1)
        result["disk_used"] = f"{used // (1024**3)}GB"
        result["disk_total"] = f"{total // (1024**3)}GB"
    except Exception:
        pass
    # Memory from /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            if total_kb > 0:
                result["memory_percent"] = round((total_kb - avail_kb) / total_kb * 100, 1)
                result["memory_used"] = f"{(total_kb - avail_kb) // 1024}MB"
                result["memory_total"] = f"{total_kb // 1024}MB"
    except Exception:
        pass
    # CPU from /proc/stat (snapshot — shows cumulative, but gives a rough idle%)
    try:
        with open("/proc/stat") as f:
            line = f.readline()
            parts = line.split()
            if parts[0] == "cpu":
                vals = [int(v) for v in parts[1:]]
                idle = vals[3] if len(vals) > 3 else 0
                total_cpu = sum(vals)
                if total_cpu > 0:
                    result["cpu_percent"] = round((1 - idle / total_cpu) * 100, 1)
    except Exception:
        pass
    # Container list via service health (reuse existing check)
    try:
        svc_data = await api_services()
        for svc in svc_data.get("services", []):
            result["containers"].append({
                "name": svc["name"],
                "status": "running" if svc["status"] == "healthy" else svc["status"]
            })
    except Exception:
        pass
    return result


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
    {"time": "03/27 11:00AM", "event": "Stale Position Fix Deployed", "detail": "Positions with no price data now auto-clean. Resolved markets no longer block trade slots.", "type": "fix"},
    {"time": "03/27 11:30AM", "event": "Sell Orders Fixed", "detail": "Switched from custom client to py-clob-client for sells. Stop-losses and trailing stops now execute properly.", "type": "fix"},
    {"time": "03/28 09:00AM", "event": "Strategy Updated from Real Data", "detail": "All categories profitable. Crypto 0.15x\u21921.2x, Sports 0.4x\u21921.3x. Based on 17/17 resolved wins, +$139.", "type": "good"},
    {"time": "03/28 11:00AM", "event": "METAR Weather Data Added", "detail": "Aviation weather sensors for 30+ cities. Temperature accurate to 0.1\u00b0C, hours ahead of forecasts.", "type": "fix"},
    {"time": "03/28 11:30AM", "event": "Priority Wallets Added", "detail": "@tradecraft (tennis, 2139% ROI) and @coldmath (weather, $89K) always tracked.", "type": "good"},
    {"time": "03/29 10:30AM", "event": "$110 Recovered from Neg Risk", "detail": "11 winning positions were stuck — redeemer wasn't using NegRiskAdapter. All recovered. Redeemer permanently fixed.", "type": "good"},
    {"time": "03/29 10:30AM", "event": "Bob Employee Upgrade", "detail": "Hermes Agent, smux workspace, CLAUDE.md, BOB_TRAINING.md, self-improving learnings. Bob is a full 24/7 employee.", "type": "good"},
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
