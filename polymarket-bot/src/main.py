"""Polymarket Trading Bot — FastAPI service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import deps, router
from src.client import PolymarketClient
from src.config import load_settings
from src.debate_engine import DebateEngine
from src.latency_detector import LatencyDetector
from src.market_scanner import MarketScanner
from src.order_flow_analyzer import OrderFlowAnalyzer
from src.pnl_tracker import PnLTracker
from src.security.audit import AuditTrail
from src.security.sandbox import ExecutionSandbox
from src.security.vault import CredentialVault
from src.signal_bus import Signal, SignalBus, SignalType
from src.websocket_client import OrderbookFeed
from strategies.flash_crash import FlashCrashStrategy
from strategies.sports_arb import SportsArbStrategy
from strategies.stink_bid import StinkBidStrategy
from strategies.weather_trader import WeatherTraderStrategy


def _configure_logging(level: str) -> None:
    """Set up structlog with JSON output for production."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _maybe_unlock_vault(log) -> None:
    """Attempt to unlock the credential vault and inject secrets into env.

    If POLY_VAULT_PASSPHRASE is set and a vault file exists, decrypt it
    and populate os.environ so that Pydantic Settings picks them up.
    """
    passphrase = os.environ.get("POLY_VAULT_PASSPHRASE", "")
    if not passphrase:
        return

    vault_path = os.environ.get("POLY_VAULT_PATH", "")
    vault = CredentialVault(vault_path) if vault_path else CredentialVault()

    if not vault.is_initialized:
        log.info("vault_not_found", msg="No vault file — using env vars directly")
        return

    try:
        vault.unlock(passphrase)
        vault.inject_into_env()
        log.info("vault_unlocked_and_injected", keys=vault.list_keys())
    except Exception as exc:
        log.error("vault_unlock_failed", error=str(exc))


async def _start_redis_listener(settings, signal_bus, log) -> asyncio.Task | None:
    """Start a background task that subscribes to Redis TA signals and
    forwards them to the signal bus. Returns the task or None if Redis
    is unavailable."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.warning("redis_not_installed", msg="pip install redis[hiredis]")
        return None

    async def _listen() -> None:
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe("polymarket:ta_signals")
            log.info("redis_ta_listener_started", channel="polymarket:ta_signals")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    signal = Signal(
                        signal_type=SignalType.TA_INDICATOR,
                        source=data.get("source", "redis"),
                        data=data,
                    )
                    await signal_bus.publish(signal)
                except (json.JSONDecodeError, Exception) as exc:
                    log.error("redis_ta_parse_error", error=str(exc))
        except Exception as exc:
            log.error("redis_listener_error", error=str(exc))

    return asyncio.create_task(_listen())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log = structlog.get_logger("main")

    # Try to unlock vault before loading settings
    _maybe_unlock_vault(log)

    settings = load_settings()
    _configure_logging(settings.poly_log_level)
    log = structlog.get_logger("main")

    # Ensure data directory exists
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    # Initialise security components
    audit_trail = AuditTrail(
        audit_dir=Path(settings.data_dir) / "audit",
        retention_days=getattr(settings, "security_audit_retention_days", 90),
    )

    sandbox = ExecutionSandbox(
        max_single_trade=getattr(settings, "security_max_single_trade", 10_000.0),
        max_daily_volume=getattr(settings, "security_max_daily_volume", 50_000.0),
        max_daily_loss=getattr(settings, "security_max_daily_loss", 2_500.0),
        max_orders_per_minute=getattr(settings, "security_max_orders_per_minute", 10),
        max_api_calls_per_minute=getattr(settings, "security_max_api_calls_per_minute", 100),
        kill_switch_enabled=getattr(settings, "security_kill_switch_enabled", True),
    )

    # Initialise core components
    client = PolymarketClient(settings)
    scanner = MarketScanner(client, settings)
    orderbook = OrderbookFeed(settings)
    pnl_tracker = PnLTracker(data_dir=settings.data_dir)

    # Load any existing trade CSV
    trades_csv = Path(settings.data_dir) / "trades.csv"
    if trades_csv.exists():
        pnl_tracker.load_csv(trades_csv)

    # Initialise new components
    signal_bus = SignalBus()
    debate_engine = DebateEngine(settings)
    latency_detector = LatencyDetector(settings, signal_bus, orderbook)
    order_flow = OrderFlowAnalyzer(settings, signal_bus, orderbook)

    # Build strategies
    strategy_args = dict(
        client=client,
        settings=settings,
        scanner=scanner,
        orderbook=orderbook,
        pnl_tracker=pnl_tracker,
    )

    stink_bid = StinkBidStrategy(**strategy_args)
    flash_crash = FlashCrashStrategy(**strategy_args)
    weather_trader = WeatherTraderStrategy(**strategy_args)
    sports_arb = SportsArbStrategy(**strategy_args)

    # Attach debate engine to all strategies
    for strat in (stink_bid, flash_crash, weather_trader, sports_arb):
        strat.set_debate_engine(debate_engine)

    # Inject dependencies into API routes
    deps.client = client
    deps.scanner = scanner
    deps.orderbook = orderbook
    deps.pnl_tracker = pnl_tracker
    deps.settings = settings
    deps.audit_trail = audit_trail
    deps.sandbox = sandbox
    deps.strategies = {
        "stink_bid": stink_bid,
        "flash_crash": flash_crash,
        "weather_trader": weather_trader,
        "sports_arb": sports_arb,
    }

    # Register kill switch callback to stop all strategies
    async def _on_kill(reason: str) -> None:
        log.critical("kill_switch_stopping_all_strategies", reason=reason)
        audit_trail.log_security_event("kill_switch_activated", {"reason": reason})
        for strat in deps.strategies.values():
            try:
                await strat.stop()
            except Exception:
                pass
        try:
            await client.cancel_all_orders()
        except Exception:
            pass

    sandbox.on_kill(_on_kill)

    # Start components
    await signal_bus.start()
    await orderbook.start()
    await latency_detector.start()
    await order_flow.start()

    # Start Redis TA signal listener
    redis_task = await _start_redis_listener(settings, signal_bus, log)

    log.info(
        "polymarket_bot_started",
        port=settings.port,
        wallet=client.wallet_address or "(not configured)",
        strategies=list(deps.strategies.keys()),
        max_exposure=settings.poly_max_exposure,
        default_size=settings.poly_default_size,
        debate_engine=debate_engine.enabled,
        latency_detector=settings.latency_detector_enabled,
        order_flow=order_flow.enabled,
        security_sandbox="active",
        audit_trail="active",
    )

    _print_banner(settings)

    yield

    # Shutdown
    log.info("polymarket_bot_stopping")
    if redis_task and not redis_task.done():
        redis_task.cancel()
        try:
            await redis_task
        except asyncio.CancelledError:
            pass
    for strat in deps.strategies.values():
        await strat.stop()
    await order_flow.stop()
    await latency_detector.stop()
    await signal_bus.stop()
    await orderbook.stop()
    await debate_engine.close()
    await client.close()
    audit_trail.close()
    log.info("polymarket_bot_stopped")


def _print_banner(settings) -> None:
    """Print startup banner."""
    banner = f"""
╔══════════════════════════════════════════════════╗
║           POLYMARKET TRADING BOT v2.0            ║
║                                                  ║
║  Port:      {settings.port:<37}║
║  Wallet:    {(deps.client.wallet_address or 'NOT SET')[:37]:<37}║
║  Exposure:  ${settings.poly_max_exposure:<36}║
║  Size:      ${settings.poly_default_size:<36}║
║                                                  ║
║  Endpoints:                                      ║
║    GET  /health      — Health check              ║
║    GET  /status      — Bot status                ║
║    GET  /positions   — Open positions             ║
║    GET  /strategies  — Available strategies       ║
║    GET  /pnl         — Profit & Loss             ║
║    GET  /markets     — Scanned markets           ║
║    GET  /audit       — Audit trail               ║
║    GET  /security/status — Security sandbox      ║
║    POST /start       — Start a strategy          ║
║    POST /stop        — Stop a strategy           ║
╚══════════════════════════════════════════════════╝
"""
    print(banner, flush=True)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Polymarket Trading Bot",
        version="2.0.0",
        description="Automated trading bot for Polymarket prediction markets",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    settings = load_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.poly_log_level.lower(),
    )
