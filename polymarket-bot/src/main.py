"""Polymarket Trading Bot — FastAPI service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import deps, router
from src.client import PolymarketClient
from src.config import load_settings
from src.latency_detector import LatencyDetector
from src.order_flow_analyzer import OrderFlowAnalyzer
from src.pnl_tracker import PnLTracker
from src.security.audit import AuditTrail
from src.security.sandbox import ExecutionSandbox
from src.security.vault import CredentialVault
from src.signal_bus import Signal, SignalBus, SignalType
from src.websocket_client import OrderbookFeed

_PLATFORM_IMPORT_ERRORS: dict[str, str] = {}

try:
    from src.platforms.polymarket_client import PolymarketPlatformClient
except ImportError as _exc:
    PolymarketPlatformClient = None  # type: ignore[assignment,misc]
    _PLATFORM_IMPORT_ERRORS["polymarket"] = str(_exc)


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
    orderbook = OrderbookFeed(settings)
    pnl_tracker = PnLTracker(data_dir=settings.data_dir)

    # Load any existing trade CSV
    trades_csv = Path(settings.data_dir) / "trades.csv"
    if trades_csv.exists():
        pnl_tracker.load_csv(trades_csv)

    # Initialise new components
    signal_bus = SignalBus()
    latency_detector = LatencyDetector(settings, signal_bus, orderbook)
    order_flow = OrderFlowAnalyzer(settings, signal_bus, orderbook)

    # ── Platform initialization (Polymarket only) ──────────────────────
    platform_clients: dict[str, Any] = {}
    platform_strategies: list[Any] = []  # strategies with start/stop lifecycle
    managed_strategies: list[tuple[str, Any]] = []
    strategy_manager = None
    strategy_manager_enabled = os.environ.get("STRATEGY_MANAGER_ENABLED", "true").lower() in {"1", "true", "yes"}

    # Log any platform import failures
    for pname, perr in _PLATFORM_IMPORT_ERRORS.items():
        log.warning("platform_dependency_missing", platform=pname, error=perr)

    # Polymarket platform adapter (wraps existing client)
    if PolymarketPlatformClient is not None:
        polymarket_platform = PolymarketPlatformClient(settings, client)
        platform_clients["polymarket"] = polymarket_platform
    else:
        log.warning("polymarket_platform_unavailable", error=_PLATFORM_IMPORT_ERRORS.get("polymarket", "unknown"))

    # ── Whale signal scanner ─────────────────────────────────────────────
    whale_scanner = None
    try:
        from src.whale_scanner.scanner_engine import ScannerEngine
        whale_scanner = ScannerEngine(data_dir=settings.data_dir)
        log.info("whale_scanner_initialized")
    except Exception as exc:
        log.warning("whale_scanner_init_failed", error=str(exc))

    # Polymarket copy-trading strategy (uses existing Polymarket client)
    if settings.copytrade_enabled:
        from strategies.polymarket_copytrade import PolymarketCopyTrader
        copytrade = PolymarketCopyTrader(
            client=client,  # existing Polymarket client
            settings=settings,
            pnl_tracker=pnl_tracker,
        )
        if whale_scanner:
            copytrade.set_whale_scanner(whale_scanner)
        if strategy_manager_enabled:
            managed_strategies.append(("copytrade", copytrade))
        else:
            platform_strategies.append(("copytrade", copytrade))

    # ── Activate additional autonomous strategies ──────────────────────
    # Each strategy is wrapped in try/except so one broken strategy doesn't kill the bot.
    # All BaseStrategy subclasses need: client, settings, scanner, orderbook, pnl_tracker.
    scanner = None
    try:
        from src.market_scanner import MarketScanner
        scanner = MarketScanner(client=client, settings=settings)
    except Exception as exc:
        log.warning("market_scanner_init_failed", error=str(exc))

    # Weather Trader — standalone autonomous weather strategy using NOAA data
    try:
        from strategies.weather_trader import WeatherTraderStrategy
        weather_trader = WeatherTraderStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        if strategy_manager_enabled:
            managed_strategies.append(("weather_trader", weather_trader))
        else:
            platform_strategies.append(("weather_trader", weather_trader))
        log.info("strategy_loaded", strategy="weather_trader")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="weather_trader", error=str(exc))

    # CVD/Arb Combined — order-flow divergence plus spread opportunities
    try:
        from strategies.cvd_detector import CVDDetectorStrategy
        cvd_arb = CVDDetectorStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        if strategy_manager_enabled:
            managed_strategies.append(("cvd_arb", cvd_arb))
        else:
            platform_strategies.append(("cvd_arb", cvd_arb))
        log.info("strategy_loaded", strategy="cvd_arb")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="cvd_arb", error=str(exc))

    # Sports Arb — zero-risk arbitrage buying both sides when combined < $0.98
    try:
        from strategies.sports_arb import SportsArbStrategy
        sports_arb = SportsArbStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        platform_strategies.append(("sports_arb", sports_arb))
        log.info("strategy_loaded", strategy="sports_arb")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="sports_arb", error=str(exc))

    # Flash Crash — monitors for sudden price drops and buys the dip
    try:
        from strategies.flash_crash import FlashCrashStrategy
        flash_crash = FlashCrashStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        platform_strategies.append(("flash_crash", flash_crash))
        log.info("strategy_loaded", strategy="flash_crash")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="flash_crash", error=str(exc))

    # Stink Bid — low limit orders on crypto short-duration markets
    try:
        from strategies.stink_bid import StinkBidStrategy
        stink_bid = StinkBidStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        platform_strategies.append(("stink_bid", stink_bid))
        log.info("strategy_loaded", strategy="stink_bid")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="stink_bid", error=str(exc))

    # Liquidity Provider — passive market making for Polymarket rewards
    try:
        from strategies.liquidity_provider import LiquidityProvider
        lp = LiquidityProvider(
            clob_client=getattr(client, '_clob_client', None),
            bankroll=float(os.environ.get("COPYTRADE_BANKROLL", "300")),
        )
        platform_strategies.append(("liquidity_provider", lp))
        log.info("strategy_loaded", strategy="liquidity_provider")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="liquidity_provider", error=str(exc))

    # Polymarket position redeemer — automatically redeems resolved winning positions
    redeemer = None
    if settings.poly_private_key:
        try:
            from src.redeemer import PolymarketRedeemer
            redeemer = PolymarketRedeemer(
                private_key=settings.poly_private_key,
                check_interval=300.0,  # every 5 minutes
            )
            platform_strategies.append(("redeemer", redeemer))
            log.info("redeemer_enabled", msg="Will auto-redeem resolved winning positions")
        except Exception as exc:
            log.warning("redeemer_init_failed", error=str(exc))

    # Inject dependencies into API routes
    deps.client = client
    deps.orderbook = orderbook
    deps.pnl_tracker = pnl_tracker
    deps.settings = settings
    deps.audit_trail = audit_trail
    deps.sandbox = sandbox
    deps.platform_clients = platform_clients
    deps.redeemer = redeemer
    deps.whale_scanner = whale_scanner
    deps.strategies = {}
    for name, strat in platform_strategies:
        deps.strategies[name] = strat
    deps.strategy_manager = None

    # Register kill switch callback to stop all strategies
    async def _on_kill(reason: str) -> None:
        log.critical("kill_switch_stopping_all_strategies", reason=reason)
        audit_trail.log_security_event("kill_switch_activated", {"reason": reason})
        for _name, strat in platform_strategies:
            try:
                await strat.stop()
            except Exception:
                pass
        if not settings.dry_run:
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

    # Start whale scanner before strategies so signals are available
    if whale_scanner:
        try:
            await whale_scanner.start()
            log.info("whale_scanner_started")
        except Exception as exc:
            log.warning("whale_scanner_start_failed", error=str(exc))

    # Start platform-specific strategies (copytrade + redeemer)
    for name, strat in platform_strategies:
        try:
            await strat.start()
            log.info("platform_strategy_started", strategy=name)
        except Exception as exc:
            log.error("platform_strategy_start_failed", strategy=name, error=str(exc))

    # Start StrategyManager for the 3-strategy architecture (weather/copytrade/cvd_arb)
    if strategy_manager_enabled and managed_strategies:
        try:
            from strategies.strategy_manager import StrategyManager
            strategy_manager = StrategyManager(
                total_bankroll=float(os.environ.get("COPYTRADE_BANKROLL", "1000")),
                dry_run=settings.dry_run,
            )
            for name, strat in managed_strategies:
                strategy_manager.register_strategy(name, strat)
                deps.strategies[name] = strat
            await strategy_manager.start()
            deps.strategy_manager = strategy_manager
            log.info(
                "strategy_manager_started",
                managed_strategies=[name for name, _ in managed_strategies],
            )
        except Exception as exc:
            log.error("strategy_manager_start_failed", error=str(exc))

    # Start Redis TA signal listener
    redis_task = await _start_redis_listener(settings, signal_bus, log)

    # ── Heartbeat scheduler ────────────────────────────────────────────────
    heartbeat_scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from heartbeat.runner import HeartbeatRunner

        heartbeat_runner = HeartbeatRunner()
        heartbeat_scheduler = AsyncIOScheduler()

        # Position update every hour — sends open positions + P&L via iMessage
        heartbeat_scheduler.add_job(
            heartbeat_runner.run_full_review,
            "interval",
            hours=1,
            id="heartbeat_hourly_update",
        )

        heartbeat_scheduler.start()
        log.info("heartbeat_scheduler_started", update="every 1h")
    except ImportError as exc:
        log.warning("heartbeat_scheduler_unavailable", error=str(exc), msg="pip install apscheduler>=3.10.0")
    except Exception as exc:
        log.error("heartbeat_scheduler_error", error=str(exc))

    active_strategy_names = [n for n, _ in platform_strategies] + [n for n, _ in managed_strategies]
    log.info(
        "polymarket_bot_started",
        mode="OBSERVER (dry-run)" if settings.dry_run else "LIVE",
        port=settings.port,
        wallet=client.wallet_address or "(not configured)",
        strategies=active_strategy_names,
        strategy_count=len(active_strategy_names),
        platforms=list(platform_clients.keys()),
        max_exposure=settings.poly_max_exposure,
        default_size=settings.poly_default_size,
        latency_detector=settings.latency_detector_enabled,
        order_flow=order_flow.enabled,
        security_sandbox="active",
        audit_trail="active",
        whale_scanner="active" if whale_scanner else "disabled",
        llm_validation=os.environ.get("LLM_VALIDATION_ENABLED", "true"),
    )

    _print_banner(settings)

    yield

    # Shutdown
    log.info("polymarket_bot_stopping")

    # Stop heartbeat scheduler
    if heartbeat_scheduler:
        try:
            heartbeat_scheduler.shutdown(wait=False)
        except Exception:
            pass

    if redis_task and not redis_task.done():
        redis_task.cancel()
        try:
            await redis_task
        except asyncio.CancelledError:
            pass

    # Stop whale scanner
    if whale_scanner:
        try:
            await whale_scanner.stop()
        except Exception:
            pass

    # Stop platform-specific strategies (copytrade + redeemer)
    if strategy_manager:
        try:
            await strategy_manager.stop()
        except Exception:
            pass

    for name, strat in platform_strategies:
        try:
            await strat.stop()
        except Exception:
            pass

    await order_flow.stop()
    await latency_detector.stop()
    await signal_bus.stop()
    await orderbook.stop()
    await client.close()

    # Close platform clients
    for pname, pclient in platform_clients.items():
        try:
            await pclient.close()
        except Exception:
            pass

    audit_trail.close()
    log.info("polymarket_bot_stopped")


def _print_banner(settings) -> None:
    """Print startup banner."""
    mode_str = "OBSERVER (dry-run)" if settings.dry_run else "LIVE"
    mode_line = f"  Mode:     {mode_str:<37}"

    wallet_addr = (getattr(deps, "client", None) and deps.client.wallet_address) or "NOT SET"

    # Build active strategy list from deps
    active_strats = list((getattr(deps, "strategies", None) or {}).keys())
    strat_line_1 = ", ".join(active_strats[:4]) if active_strats else "none"
    strat_line_2 = ", ".join(active_strats[4:]) if len(active_strats) > 4 else ""

    banner = f"""
╔══════════════════════════════════════════════════════╗
║      POLYMARKET TRADING BOT v5.0 — ALL STRATEGIES    ║
║                                                      ║
║{mode_line}     ║
║  Port:      {settings.port:<41}║
║  Wallet:    {wallet_addr[:41]:<41}║
║  Exposure:  ${settings.poly_max_exposure:<40}║
║                                                      ║
║  Strategies: {strat_line_1:<40}║"""

    if strat_line_2:
        banner += f"""
║  + {strat_line_2:<49}║"""

    banner += f"""
║  + whale_scanner + LLM_validator                     ║
║                                                      ║
║  Endpoints:                                          ║
║    GET  /health        — Health check                ║
║    GET  /status        — Bot status                  ║
║    GET  /positions     — Open positions              ║
║    GET  /pnl           — Profit & Loss               ║
║    POST /heartbeat/run — Trigger heartbeat           ║
║    GET  /heartbeat/status — HEARTBEAT.md             ║
║    GET  /whale-scanner/status — Scanner health       ║
╚══════════════════════════════════════════════════════════╝
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
