"""REST API endpoints for the Polymarket trading bot."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────

class StartStrategyRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = {}


class StopStrategyRequest(BaseModel):
    strategy: str


class SetModeRequest(BaseModel):
    mode: str  # "dry_run" or "live"


class IngestRequest(BaseModel):
    text: Optional[str] = None
    source_url: Optional[str] = None
    url: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class StatusResponse(BaseModel):
    status: str
    wallet: str
    strategies: dict[str, Any]
    open_orders: int
    polymarket_api: bool
    platforms: dict[str, Any] = {}


class PnLResponse(BaseModel):
    total_pnl: float
    total_realized: float
    total_unrealized: float
    total_fees: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    by_strategy: dict[str, float]
    by_market: dict[str, float]


# ── Dependency holder (set by main.py at startup) ────────────────────────

class _Deps:
    """Mutable container for runtime dependencies injected by main.py."""

    client: Any = None
    scanner: Any = None
    orderbook: Any = None
    pnl_tracker: Any = None
    strategies: dict[str, Any] = {}
    settings: Any = None
    audit_trail: Any = None
    sandbox: Any = None
    paper_ledger: Any = None
    platform_clients: dict[str, Any] = {}  # {"polymarket": ..., "kalshi": ..., "crypto": ...}
    redeemer: Any = None  # PolymarketRedeemer instance
    whale_scanner: Any = None  # ScannerEngine instance


deps = _Deps()


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", service="polymarket-bot", version="3.0.0")


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    api_ok = False
    if deps.client:
        api_ok = await deps.client.health_check()

    strat_status = {}
    total_orders = 0
    for name, strat in deps.strategies.items():
        if hasattr(strat, "get_status"):
            st = strat.get_status()
            strat_status[name] = st
            total_orders += st.get("open_positions", 0)
        else:
            strat_status[name] = strat.status
            total_orders += len(strat.open_orders)

    # Gather platform connection states
    platform_info: dict[str, Any] = {}
    for pname, pclient in deps.platform_clients.items():
        try:
            platform_info[pname] = {
                "connected": True,
                "dry_run": pclient.is_dry_run,
                "platform_name": pclient.platform_name,
            }
        except Exception:
            platform_info[pname] = {"connected": False}

    return StatusResponse(
        status="running",
        wallet=deps.client.wallet_address if deps.client else "",
        strategies=strat_status,
        open_orders=total_orders,
        polymarket_api=api_ok,
        platforms=platform_info,
    )


@router.get("/positions")
async def positions(
    platform: str | None = Query(None, description="Filter by platform: polymarket, kalshi, crypto"),
) -> dict[str, Any]:
    """Current open positions across all strategies and platforms."""
    all_positions: list[dict[str, Any]] = []

    # Polymarket strategy-tracked positions
    if platform is None or platform == "polymarket":
        for name, strat in deps.strategies.items():
            if hasattr(strat, "get_status"):
                st = strat.get_status()
                for pos in st.get("positions", []):
                    pos["platform"] = "polymarket"
                    pos["strategy"] = name
                    all_positions.append(pos)
            elif hasattr(strat, "open_orders"):
                for order_id, order in strat.open_orders.items():
                    all_positions.append({
                        "platform": "polymarket",
                        "order_id": order_id,
                        "token_id": order.token_id,
                        "market": order.market,
                        "side": order.side,
                        "price": order.price,
                        "size": order.size,
                        "strategy": name,
                    })

        # Also fetch from P&L tracker
        if deps.pnl_tracker:
            for tid, pos in deps.pnl_tracker.open_positions.items():
                all_positions.append({
                    "platform": "polymarket",
                    "token_id": tid,
                    "market": pos["market"],
                    "side": pos["side"],
                    "entry_price": pos["entry_price"],
                    "size": pos["size"],
                    "strategy": pos["strategy"],
                    "realized_pnl": pos["realized_pnl"],
                })

    # Cross-platform positions from platform clients
    for pname, pclient in deps.platform_clients.items():
        if pname == "polymarket":
            continue  # already handled above
        if platform is not None and pname != platform:
            continue
        try:
            positions_list = await pclient.get_positions()
            for pos in positions_list:
                pos_dict = pos.model_dump() if hasattr(pos, "model_dump") else vars(pos)
                pos_dict["platform"] = pname
                all_positions.append(pos_dict)
        except Exception as exc:
            logger.error("platform_positions_error", platform=pname, error=str(exc))

    return {"positions": all_positions, "count": len(all_positions)}


@router.get("/platforms")
async def platforms() -> dict[str, Any]:
    """List connected trading platforms and their status."""
    result: dict[str, Any] = {}
    for pname, pclient in deps.platform_clients.items():
        try:
            balance = await pclient.get_balance()
            result[pname] = {
                "connected": True,
                "dry_run": pclient.is_dry_run,
                "balance": balance,
            }
        except Exception as exc:
            result[pname] = {"connected": False, "error": str(exc)}
    return {"platforms": result, "count": len(result)}


@router.get("/strategies")
async def list_strategies() -> dict[str, Any]:
    """List available strategies and their current configs."""
    result = {}
    for name, strat in deps.strategies.items():
        result[name] = {
            "name": strat.name,
            "description": strat.description,
            "state": strat.state.value,
            "params": strat.params,
        }
    return {"strategies": result}


@router.get("/pnl")
async def pnl(keyword: str | None = None, hours: float | None = None, strategy: str | None = None) -> PnLResponse:
    """Get P&L filtered by keyword, time window, and/or strategy."""
    if not deps.pnl_tracker:
        raise HTTPException(status_code=503, detail="P&L tracker not initialized")

    summary = deps.pnl_tracker.get_pnl(keyword=keyword, hours=hours, strategy=strategy)
    return PnLResponse(
        total_pnl=summary.total_pnl,
        total_realized=summary.total_realized,
        total_unrealized=summary.total_unrealized,
        total_fees=summary.total_fees,
        trade_count=summary.trade_count,
        win_count=summary.win_count,
        loss_count=summary.loss_count,
        win_rate=summary.win_rate,
        by_strategy=summary.by_strategy,
        by_market=summary.by_market,
    )


@router.post("/start")
async def start_strategy(req: StartStrategyRequest) -> dict[str, Any]:
    """Start a strategy by name with optional parameters."""
    strat = deps.strategies.get(req.strategy)
    if not strat:
        available = list(deps.strategies.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy}' not found. Available: {available}",
        )

    if strat.state.value == "running":
        return {"status": "already_running", "strategy": req.strategy}

    await strat.start(params=req.params if req.params else None)
    logger.info("strategy_started_via_api", strategy=req.strategy, params=req.params)
    return {"status": "started", "strategy": req.strategy, "params": strat.params}


@router.post("/stop")
async def stop_strategy(req: StopStrategyRequest) -> dict[str, Any]:
    """Stop a running strategy."""
    strat = deps.strategies.get(req.strategy)
    if not strat:
        available = list(deps.strategies.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy}' not found. Available: {available}",
        )

    if strat.state.value != "running":
        return {"status": "not_running", "strategy": req.strategy}

    await strat.stop()
    logger.info("strategy_stopped_via_api", strategy=req.strategy)
    return {"status": "stopped", "strategy": req.strategy}


@router.get("/markets")
async def markets() -> dict[str, Any]:
    """Get currently scanned markets."""
    if not deps.scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    result = await deps.scanner.scan()
    return {
        "markets": [
            {
                "condition_id": m.condition_id,
                "question": m.question,
                "token": m.token,
                "timeframe": m.timeframe,
                "direction": m.direction,
                "token_id_yes": m.token_id_yes,
                "token_id_no": m.token_id_no,
                "last_price_yes": m.last_price_yes,
                "volume": m.volume,
            }
            for m in result.markets
        ],
        "count": len(result.markets),
        "scan_time": result.scan_time,
        "errors": result.errors,
    }


# ── Audit endpoint ───────────────────────────────────────────────────────

@router.get("/audit")
async def audit(
    date: str | None = Query(None, description="ISO date (YYYY-MM-DD), defaults to today"),
    strategy: str | None = Query(None, description="Filter by strategy name"),
    type: str | None = Query(None, description="Entry type: trade_decision, api_call, security_event"),
    limit: int = Query(500, ge=1, le=10000, description="Max entries to return"),
) -> dict[str, Any]:
    """Query the audit trail for trade decisions, API calls, and security events."""
    if not deps.audit_trail:
        raise HTTPException(status_code=503, detail="Audit trail not initialized")

    entries = deps.audit_trail.query(
        date=date,
        strategy=strategy,
        entry_type=type,
        limit=limit,
    )

    return {
        "entries": entries,
        "count": len(entries),
        "date": date or "today",
        "filters": {
            "strategy": strategy,
            "type": type,
            "limit": limit,
        },
    }


@router.get("/audit/dates")
async def audit_dates() -> dict[str, Any]:
    """List available audit trail dates."""
    if not deps.audit_trail:
        raise HTTPException(status_code=503, detail="Audit trail not initialized")

    dates = deps.audit_trail.get_available_dates()
    return {"dates": dates, "count": len(dates)}


# ── Security endpoints ───────────────────────────────────────────────────

@router.get("/security/status")
async def security_status() -> dict[str, Any]:
    """Get security sandbox status including daily limits and kill switch."""
    if not deps.sandbox:
        return {"status": "not_configured"}

    return {
        "status": "active",
        "kill_switch": deps.sandbox.is_killed,
        "kill_reason": deps.sandbox.kill_reason,
        "daily_stats": deps.sandbox.daily_stats,
    }


# ── Observer / Dry-run mode endpoints ────────────────────────────────────

@router.get("/mode")
async def get_mode() -> dict[str, Any]:
    """Return current operating mode (dry_run or live)."""
    if not deps.settings:
        raise HTTPException(status_code=503, detail="Settings not initialized")
    return {
        "mode": "dry_run" if deps.settings.dry_run else "live",
        "dry_run": deps.settings.dry_run,
    }


@router.post("/mode")
async def set_mode(req: SetModeRequest) -> dict[str, Any]:
    """Toggle between dry_run and live mode.

    Switching to live requires the vault to be unlocked (i.e. a wallet
    private key must be configured).
    """
    if not deps.settings:
        raise HTTPException(status_code=503, detail="Settings not initialized")

    if req.mode not in ("dry_run", "live"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{req.mode}'. Must be 'dry_run' or 'live'.",
        )

    if req.mode == "live":
        # Require wallet credentials to go live
        if not deps.client or not deps.client.wallet_address:
            raise HTTPException(
                status_code=403,
                detail="Cannot switch to live mode — no wallet configured. "
                "Unlock the vault or set POLY_PRIVATE_KEY first.",
            )
        deps.settings.dry_run = False
        logger.warning("mode_switched_to_live", wallet=deps.client.wallet_address)
    else:
        deps.settings.dry_run = True
        logger.info("mode_switched_to_dry_run")

    return {
        "mode": "dry_run" if deps.settings.dry_run else "live",
        "dry_run": deps.settings.dry_run,
    }


@router.get("/paper-trades")
async def paper_trades(
    limit: int = Query(100, ge=1, le=10000, description="Max trades to return"),
    strategy: str | None = Query(None, description="Filter by strategy name"),
    platform: str | None = Query(None, description="Filter by platform: polymarket, kalshi, crypto"),
) -> dict[str, Any]:
    """Return recent paper trades from the ledger."""
    if not deps.paper_ledger:
        raise HTTPException(status_code=503, detail="Paper ledger not initialized")

    trades = deps.paper_ledger.read_recent(limit=limit)

    if strategy:
        trades = [t for t in trades if t.strategy == strategy]
    if platform:
        trades = [t for t in trades if getattr(t, "platform", "polymarket") == platform]

    return {
        "trades": [t.to_dict() for t in trades],
        "count": len(trades),
        "mode": "dry_run" if deps.settings and deps.settings.dry_run else "live",
    }


@router.get("/paper-pnl")
async def paper_pnl() -> dict[str, Any]:
    """Return hypothetical P&L calculated from resolved paper trades."""
    if not deps.paper_ledger:
        raise HTTPException(status_code=503, detail="Paper ledger not initialized")

    return deps.paper_ledger.get_paper_pnl()


# ── Knowledge pipeline endpoints ─────────────────────────────────────────

@router.post("/knowledge/ingest")
async def knowledge_ingest(req: IngestRequest) -> dict[str, Any]:
    """Ingest raw text or URL into the knowledge graph."""
    from knowledge.ingest import KnowledgeIngester

    ingester = KnowledgeIngester()

    if req.url:
        result = await ingester.ingest_url(req.url)
    elif req.text:
        result = await ingester.ingest_text(req.text, source_url=req.source_url)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'text' (with optional 'source_url') or 'url'.",
        )

    return {"status": "ingested", "extraction": result}


@router.get("/knowledge/search")
async def knowledge_search(
    q: str = Query(..., description="Search query"),
    type: str | None = Query(None, description="Filter by type: strategy, market, wallet, research"),
    tags: str | None = Query(None, description="Comma-separated tags to filter by"),
) -> dict[str, Any]:
    """Search the knowledge graph."""
    from knowledge.query import KnowledgeQuery

    query = KnowledgeQuery()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = query.search(q, ktype=type, tags=tag_list)
    return {"results": results, "count": len(results), "query": q}


@router.get("/knowledge/digest")
async def knowledge_digest() -> dict[str, Any]:
    """Generate today's learning digest via Claude."""
    from knowledge.digest import generate_daily_digest

    digest = await generate_daily_digest()
    return {"digest": digest}


@router.get("/knowledge/strategy/{name}")
async def knowledge_strategy(name: str) -> dict[str, Any]:
    """Get all knowledge for a specific strategy."""
    from knowledge.query import KnowledgeQuery

    query = KnowledgeQuery()
    content = query.get_strategy_knowledge(name)
    if not content:
        raise HTTPException(status_code=404, detail=f"No knowledge found for strategy '{name}'")
    return {"strategy": name, "content": content}


@router.get("/knowledge/recent")
async def knowledge_recent(
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
) -> dict[str, Any]:
    """Get recent learning log entries."""
    from knowledge.query import KnowledgeQuery

    query = KnowledgeQuery()
    content = query.get_recent_learnings(days=days)
    return {"days": days, "content": content, "has_data": bool(content.strip())}


# ── Heartbeat endpoints ────────────────────────────────────────────────

@router.post("/heartbeat/run")
async def run_heartbeat(
    review_type: str = Query("full", description="Review type: 'full' or 'quick'"),
) -> dict[str, Any]:
    """Trigger a heartbeat review (full self-review or quick pulse)."""
    from heartbeat.runner import HeartbeatRunner

    runner = HeartbeatRunner()
    if review_type == "quick":
        result = await runner.run_quick_pulse()
    else:
        result = await runner.run_full_review()
    return result


@router.get("/heartbeat/status")
async def heartbeat_status() -> dict[str, Any]:
    """Get current HEARTBEAT.md contents."""
    heartbeat_path = Path(__file__).parent.parent / "HEARTBEAT.md"
    if heartbeat_path.exists():
        return {"content": heartbeat_path.read_text()}
    return {"content": "No heartbeat data yet. Run POST /heartbeat/run first."}


class TestNotificationRequest(BaseModel):
    message: str = "Test notification from Bob"


# ── Weather Intelligence endpoints ────────────────────────────────────

@router.get("/weather/current")
async def weather_current() -> dict[str, Any]:
    """Get latest NOAA data for all tracked weather stations."""
    weather_strat = deps.strategies.get("weather_trader")
    if not weather_strat:
        raise HTTPException(status_code=503, detail="Weather trader strategy not initialized")

    station_data = weather_strat.station_data
    stations = {}
    for station_id, data in station_data.items():
        current = data.get("current")
        forecast = data.get("forecast")
        stations[station_id] = {
            "city": data.get("city", ""),
            "current_temp_f": current.get("temp_f") if current else None,
            "observed_at": current.get("observed_at", "") if current else "",
            "source": current.get("source", "") if current else "",
            "forecast_high_f": forecast.get("forecast_high_f") if forecast else None,
            "forecast_low_f": forecast.get("forecast_low_f") if forecast else None,
            "forecast_updated": forecast.get("updated_at", "") if forecast else "",
            "hourly_count": len(data.get("hourly", [])),
            "fetched_at": data.get("fetched_at"),
        }

    return {
        "stations": stations,
        "count": len(stations),
    }


@router.get("/weather/edges")
async def weather_edges() -> dict[str, Any]:
    """Get current calculated edges vs market prices for weather markets."""
    weather_strat = deps.strategies.get("weather_trader")
    if not weather_strat:
        raise HTTPException(status_code=503, detail="Weather trader strategy not initialized")

    edges = weather_strat.current_edges
    open_positions = weather_strat.get_positions_with_pnl()
    return {
        "edges": edges,
        "count": len(edges),
        "positions": len(open_positions),
        "open_positions": open_positions,
    }


@router.post("/notifications/test")
async def test_notification(req: TestNotificationRequest) -> dict[str, Any]:
    """Send a test notification to verify iMessage/console is working."""
    try:
        from notifications.manager import NotificationManager
        nm = NotificationManager()
        channel = type(nm.notifier).__name__
        # Use detailed send if available (IMessageNotifier)
        if hasattr(nm.notifier, "send_message_with_detail"):
            success, detail = await nm.notifier.send_message_with_detail(text=req.message)
            return {"status": "sent" if success else "failed", "channel": channel, "detail": detail}
        success = await nm.notifier.send_message(text=req.message)
        return {"status": "sent" if success else "failed", "channel": channel}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Notification error: {exc}")


@router.post("/redeem")
async def trigger_redeem() -> dict[str, Any]:
    """Manually trigger redemption of all resolved winning positions."""
    if deps.redeemer is None:
        raise HTTPException(status_code=503, detail="Redeemer not initialized")
    try:
        result = await deps.redeemer.redeem_all_winning()
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Redeem error: {exc}")


@router.get("/redeem/status")
async def redeem_status() -> dict[str, Any]:
    """Get redeemer status including USDC.e balance."""
    if deps.redeemer is None:
        return {"status": "not_initialized"}
    return deps.redeemer.get_status()


# ── Whale Scanner endpoints ──────────────────────────────────────────

@router.get("/whale-scanner/status")
async def whale_scanner_status() -> dict[str, Any]:
    """Get whale scanner status: last poll, trades scanned, active signals."""
    if not deps.whale_scanner:
        return {"status": "not_initialized"}
    return deps.whale_scanner.get_status()


@router.get("/whale-scanner/signals")
async def whale_scanner_signals(
    signal_type: str | None = Query(None, description="Filter: whale, insider, cluster"),
    min_confidence: float = Query(0, description="Minimum confidence score"),
) -> dict[str, Any]:
    """Get active whale scanner signals."""
    if not deps.whale_scanner:
        raise HTTPException(status_code=503, detail="Whale scanner not initialized")

    signals = deps.whale_scanner.get_active_signals()
    if signal_type:
        signals = [s for s in signals if s.signal_type == signal_type]
    if min_confidence > 0:
        signals = [s for s in signals if s.confidence_score >= min_confidence]

    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
    }


@router.get("/heartbeat/reports")
async def heartbeat_reports(
    limit: int = Query(10, ge=1, le=100, description="Max reports to return"),
) -> dict[str, Any]:
    """List recent heartbeat report filenames."""
    reports_dir = Path(__file__).parent.parent / "heartbeat_reports"
    if not reports_dir.exists():
        return {"reports": []}
    files = sorted(reports_dir.glob("*.json"), reverse=True)[:limit]
    return {"reports": [f.name for f in files]}


# ── Kraken Market Maker endpoints ─────────────────────────────────

@router.get("/kraken/status")
async def kraken_status() -> dict[str, Any]:
    """Get Kraken Avellaneda market maker status."""
    ks = getattr(deps, "kraken_strategy", None)
    if ks is None:
        return {"enabled": False, "reason": "KRAKEN_API_KEY not set"}
    try:
        status = ks.get_status() if hasattr(ks, "get_status") else {}
    except Exception:
        status = {}
    return {
        "enabled": True,
        "pair": getattr(ks, "pair", os.environ.get("KRAKEN_TRADING_PAIR", "XRP/USD")),
        **status,
    }


# ── Sports Arb endpoints ─────────────────────────────────────────────

@router.get("/arb/status")
async def arb_status() -> dict[str, Any]:
    """Sports arb strategy status: arbs found/executed/skipped today."""
    strat = (getattr(deps, "strategies", None) or {}).get("sports_arb")
    if strat is None:
        return {"enabled": False, "reason": "sports_arb not loaded"}
    if hasattr(strat, "get_arb_status"):
        return strat.get_arb_status()
    return {"enabled": True, "status": strat.status}


# ── Strategy Manager endpoints ────────────────────────────────────────

@router.get("/strategies/status")
async def strategies_status() -> dict[str, Any]:
    """Per-strategy status: bankroll allocation, P/L, positions, last tick."""
    sm = getattr(deps, "strategy_manager", None)
    if sm is not None and hasattr(sm, "get_status"):
        return sm.get_status()
    strats = getattr(deps, "strategies", None) or {}
    if not strats:
        return {"strategy_manager": "not_configured", "strategies": {}}
    return {
        "strategy_manager": "disabled",
        "strategies": {
            name: s.status if hasattr(s, "status") else {"name": name}
            for name, s in strats.items()
        },
    }

