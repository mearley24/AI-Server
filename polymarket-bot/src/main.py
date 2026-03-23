"""Polymarket Trading Bot — FastAPI service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
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
from src.pnl_tracker import PnLTracker
from src.signal_bus import Signal, SignalBus, SignalType
from src.websocket_client import OrderbookFeed
from strategies.flash_crash import FlashCrashStrategy
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
    settings = load_settings()
    _configure_logging(settings.poly_log_level)
    log = structlog.get_logger("main")

    # Ensure data directory exists
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

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

    # Attach debate engine to all strategies
    for strat in (stink_bid, flash_crash, weather_trader):
        strat.set_debate_engine(debate_engine)

    # Inject dependencies into API routes
    deps.client = client
    deps.scanner = scanner
    deps.orderbook = orderbook
    deps.pnl_tracker = pnl_tracker
    deps.settings = settings
    deps.strategies = {
        "stink_bid": stink_bid,
        "flash_crash": flash_crash,
        "weather_trader": weather_trader,
    }

    # Start components
    await signal_bus.start()
    await orderbook.start()
    await latency_detector.start()

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
    await latency_detector.stop()
    await signal_bus.stop()
    await orderbook.stop()
    await debate_engine.close()
    await client.close()
    log.info("polymarket_bot_stopped")


def _print_banner(settings) -> None:
    """Print startup banner."""
    banner = f"""
╔══════════════════════════════════════════════════╗
║           POLYMARKET TRADING BOT v1.0            ║
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
║    POST /start       — Start a strategy          ║
║    POST /stop        — Stop a strategy           ║
╚══════════════════════════════════════════════════╝
"""
    print(banner, flush=True)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Polymarket Trading Bot",
        version="1.0.0",
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
