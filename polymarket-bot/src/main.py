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
from src.paper_ledger import PaperLedger
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

# Platform clients — imported with try/except so one broken dependency
# doesn't crash the whole bot.  The health checker reports "dependency_missing"
# instead.
_PLATFORM_IMPORT_ERRORS: dict[str, str] = {}

try:
    from src.platforms.kalshi_client import KalshiClient
except ImportError as _exc:
    KalshiClient = None  # type: ignore[assignment,misc]
    _PLATFORM_IMPORT_ERRORS["kalshi"] = str(_exc)

try:
    from src.platforms.crypto_client import CryptoClient
except ImportError as _exc:
    CryptoClient = None  # type: ignore[assignment,misc]
    _PLATFORM_IMPORT_ERRORS["crypto"] = str(_exc)

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

    # Initialise paper ledger for dry-run mode
    paper_ledger = PaperLedger(
        ledger_path=settings.paper_ledger_file,
        gamma_api_url=settings.gamma_api_url,
    )

    # Attach debate engine and paper ledger to all strategies
    for strat in (stink_bid, flash_crash, weather_trader, sports_arb):
        strat.set_debate_engine(debate_engine)
        strat.set_paper_ledger(paper_ledger)

    # ── Multi-platform initialization ────────────────────────────────────
    enabled_platforms = [p.strip() for p in settings.platforms_enabled.split(",") if p.strip()]
    platform_clients: dict[str, Any] = {}
    platform_strategies: list[Any] = []  # strategies with start/stop lifecycle

    # Log any platform import failures
    for pname, perr in _PLATFORM_IMPORT_ERRORS.items():
        log.warning("platform_dependency_missing", platform=pname, error=perr)

    # Polymarket platform adapter (wraps existing client)
    if PolymarketPlatformClient is not None:
        polymarket_platform = PolymarketPlatformClient(settings, client)
        platform_clients["polymarket"] = polymarket_platform
    else:
        log.warning("polymarket_platform_unavailable", error=_PLATFORM_IMPORT_ERRORS.get("polymarket", "unknown"))

    # Kalshi platform
    kalshi_client = None
    kalshi_scanner = None
    if "kalshi" in enabled_platforms and KalshiClient is None:
        log.warning("kalshi_dependency_missing", error=_PLATFORM_IMPORT_ERRORS.get("kalshi", "unknown"))
    elif "kalshi" in enabled_platforms:
        kalshi_client = KalshiClient(
            api_key_id=settings.kalshi_api_key_id,
            private_key_path=settings.kalshi_private_key_path,
            environment=settings.kalshi_environment,
            dry_run=settings.kalshi_dry_run,
            paper_ledger=paper_ledger,
        )
        connected = await kalshi_client.connect()
        if connected:
            platform_clients["kalshi"] = kalshi_client
            log.info("kalshi_platform_enabled", environment=settings.kalshi_environment, dry_run=settings.kalshi_dry_run)

            # Kalshi scanner
            from strategies.kalshi.kalshi_scanner import KalshiScanner
            kalshi_scanner = KalshiScanner(
                kalshi_client=kalshi_client,
                signal_bus=signal_bus,
                scan_interval_seconds=settings.kalshi_scan_interval,
            )

            # Kalshi weather strategy
            if settings.kalshi_weather_enabled:
                from strategies.kalshi.kalshi_weather import KalshiWeatherStrategy
                kalshi_weather = KalshiWeatherStrategy(
                    kalshi_client=kalshi_client,
                    signal_bus=signal_bus,
                    noaa_stations=settings.weather_noaa_stations,
                    edge_threshold=settings.kalshi_edge_threshold,
                    max_position_size=settings.kalshi_max_position_size,
                    check_interval=settings.weather_check_interval_seconds,
                )
                platform_strategies.append(("kalshi_weather", kalshi_weather))

            # Kalshi Fed strategy
            if settings.kalshi_fed_enabled:
                from strategies.kalshi.kalshi_fed import KalshiFedStrategy
                kalshi_fed = KalshiFedStrategy(
                    kalshi_client=kalshi_client,
                    signal_bus=signal_bus,
                    edge_threshold=settings.kalshi_edge_threshold,
                    max_position_size=settings.kalshi_max_position_size,
                )
                platform_strategies.append(("kalshi_fed", kalshi_fed))
        else:
            log.warning("kalshi_connect_failed", msg="Kalshi platform disabled")

    # Crypto platform
    crypto_client = None
    if "crypto" in enabled_platforms and CryptoClient is None:
        log.warning("crypto_dependency_missing", error=_PLATFORM_IMPORT_ERRORS.get("crypto", "unknown"))
    elif "crypto" in enabled_platforms:
        crypto_client = CryptoClient(
            exchange_id=settings.crypto_exchange,
            api_key=settings.kraken_api_key,
            api_secret=settings.kraken_api_secret,
            dry_run=settings.kraken_dry_run,
            symbols=settings.crypto_symbols,
            paper_ledger=paper_ledger,
        )
        connected = await crypto_client.connect()
        if connected:
            platform_clients["crypto"] = crypto_client
            log.info("crypto_platform_enabled", exchange=settings.crypto_exchange, dry_run=settings.kraken_dry_run)

            # BTC Correlation strategy
            if settings.crypto_btc_correlation_enabled:
                from strategies.crypto.btc_correlation import BTCCorrelationStrategy
                btc_corr = BTCCorrelationStrategy(
                    crypto_client=crypto_client,
                    signal_bus=signal_bus,
                    alt_symbols=settings.crypto_symbols,
                    trade_amount_usd=settings.crypto_trade_amount_usd,
                )
                platform_strategies.append(("btc_correlation", btc_corr))

            # Mean Reversion strategy
            if settings.crypto_mean_reversion_enabled:
                from strategies.crypto.mean_reversion import MeanReversionStrategy
                mean_rev = MeanReversionStrategy(
                    crypto_client=crypto_client,
                    signal_bus=signal_bus,
                    symbols=settings.crypto_symbols,
                    trade_amount_usd=settings.crypto_trade_amount_usd,
                    check_interval=settings.crypto_poll_interval_seconds,
                )
                platform_strategies.append(("mean_reversion", mean_rev))

            # Avellaneda-Stoikov Market Maker
            if settings.crypto_avellaneda_enabled:
                from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker
                avellaneda_mm = AvellanedaMarketMaker(
                    crypto_client=crypto_client,
                    signal_bus=signal_bus,
                    pairs=settings.avellaneda_pairs,
                    risk_aversion=settings.avellaneda_risk_aversion,
                    session_horizon_seconds=settings.avellaneda_session_horizon_seconds,
                    volatility_window=settings.avellaneda_volatility_window,
                    max_inventory=settings.avellaneda_max_inventory,
                    min_spread_bps=settings.avellaneda_min_spread_bps,
                    max_spread_bps=settings.avellaneda_max_spread_bps,
                    order_size_usdt=settings.avellaneda_order_size_usdt,
                    tick_interval=settings.avellaneda_tick_interval,
                    fee_bps=settings.avellaneda_fee_bps,
                    pair_configs=settings.avellaneda_pair_configs,
                    max_total_exposure=settings.avellaneda_max_total_exposure,
                    hawkes_config={
                        "mu": settings.avellaneda_hawkes_mu,
                        "alpha": settings.avellaneda_hawkes_alpha,
                        "beta": settings.avellaneda_hawkes_beta,
                        "window_seconds": settings.avellaneda_hawkes_window,
                        "sensitivity": settings.avellaneda_hawkes_sensitivity,
                    },
                    vpin_config={
                        "bucket_volume": settings.avellaneda_vpin_bucket_volume,
                        "num_buckets": settings.avellaneda_vpin_num_buckets,
                        "warning_threshold": settings.avellaneda_vpin_warning,
                        "danger_threshold": settings.avellaneda_vpin_danger,
                        "critical_threshold": settings.avellaneda_vpin_critical,
                        "cooldown_seconds": settings.avellaneda_vpin_cooldown,
                    },
                    pnl_tracker=pnl_tracker,
                )
                platform_strategies.append(("avellaneda_mm", avellaneda_mm))

            # Momentum strategy
            if settings.crypto_momentum_enabled:
                from strategies.crypto.momentum import MomentumStrategy
                momentum = MomentumStrategy(
                    crypto_client=crypto_client,
                    signal_bus=signal_bus,
                    symbols=settings.crypto_symbols,
                    trade_amount_usd=settings.crypto_trade_amount_usd,
                    check_interval=settings.crypto_poll_interval_seconds,
                )
                platform_strategies.append(("momentum", momentum))

            # Momentum/Mean-Reversion Hybrid strategy
            if settings.crypto_momentum_mr_enabled:
                from strategies.crypto.momentum_mean_reversion import MomentumMeanReversion
                mmr = MomentumMeanReversion(
                    crypto_client=crypto_client,
                    signal_bus=signal_bus,
                    pairs=settings.momentum_mr_pairs,
                    order_size_usd=settings.momentum_mr_order_size_usd,
                    tick_interval=settings.momentum_mr_tick_interval,
                    vwap_window_minutes=settings.momentum_mr_vwap_window_minutes,
                    ema_fast=settings.momentum_mr_ema_fast,
                    ema_slow=settings.momentum_mr_ema_slow,
                    buy_dip_pct=settings.momentum_mr_buy_dip_pct,
                    sell_rip_pct=settings.momentum_mr_sell_rip_pct,
                    take_profit_pct=settings.momentum_mr_take_profit_pct,
                    stop_loss_pct=settings.momentum_mr_stop_loss_pct,
                    max_trades_per_hour=settings.momentum_mr_max_trades_per_hour,
                    max_inventory_usd=settings.momentum_mr_max_inventory_usd,
                    pnl_tracker=pnl_tracker,
                )
                platform_strategies.append(("momentum_mr", mmr))
        else:
            log.warning("crypto_connect_failed", msg="Crypto platform disabled")

    # Polymarket copy-trading strategy (uses existing Polymarket client)
    if settings.copytrade_enabled:
        from strategies.polymarket_copytrade import PolymarketCopyTrader
        copytrade = PolymarketCopyTrader(
            client=client,  # existing Polymarket client
            settings=settings,
            pnl_tracker=pnl_tracker,
        )
        platform_strategies.append(("copytrade", copytrade))

    # Attach Kalshi client to weather trader for dual-platform execution
    if kalshi_client and "kalshi" in platform_clients:
        weather_trader.set_kalshi_client(kalshi_client)
        log.info("weather_trader_kalshi_attached", msg="Weather trader will scan both Polymarket and Kalshi")

    # Inject dependencies into API routes
    deps.client = client
    deps.scanner = scanner
    deps.orderbook = orderbook
    deps.pnl_tracker = pnl_tracker
    deps.settings = settings
    deps.audit_trail = audit_trail
    deps.sandbox = sandbox
    deps.paper_ledger = paper_ledger
    deps.platform_clients = platform_clients
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
        if not settings.dry_run:
            try:
                await client.cancel_all_orders()
            except Exception:
                pass

    sandbox.on_kill(_on_kill)

    # Start components
    await signal_bus.start()

    # Only start Polymarket WebSocket feed if polymarket is an enabled platform
    if "polymarket" in enabled_platforms:
        await orderbook.start()
    else:
        log.info("polymarket_ws_disabled", msg="Polymarket WebSocket disabled — platform not enabled")

    await latency_detector.start()
    await order_flow.start()

    # Start Kalshi scanner
    if kalshi_scanner:
        await kalshi_scanner.start()

    # Start platform-specific strategies
    for name, strat in platform_strategies:
        try:
            await strat.start()
            log.info("platform_strategy_started", strategy=name)
        except Exception as exc:
            log.error("platform_strategy_start_failed", strategy=name, error=str(exc))

    # Auto-start core Polymarket strategies
    for name, strat in deps.strategies.items():
        try:
            await strat.start()
            log.info("core_strategy_started", strategy=name)
        except Exception as exc:
            log.error("core_strategy_start_failed", strategy=name, error=str(exc))

    # Start Redis TA signal listener
    redis_task = await _start_redis_listener(settings, signal_bus, log)

    # Start paper ledger scoring loop (periodically checks resolved markets)
    scoring_task: asyncio.Task | None = None
    if settings.dry_run:
        async def _scoring_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(settings.paper_ledger_scoring_interval)
                    result = await paper_ledger.score_resolved_markets()
                    if result["scored"] > 0:
                        log.info("paper_ledger_scoring_complete", **result)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    log.error("paper_ledger_scoring_error", error=str(exc))

        scoring_task = asyncio.create_task(_scoring_loop())

    # ── Heartbeat scheduler ────────────────────────────────────────────────
    heartbeat_scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from heartbeat.runner import HeartbeatRunner

        heartbeat_runner = HeartbeatRunner()
        heartbeat_scheduler = AsyncIOScheduler()

        # Full review at 6:00 AM MT (13:00 UTC) daily
        heartbeat_scheduler.add_job(
            heartbeat_runner.run_full_review,
            "cron",
            hour=13,
            minute=0,
            id="heartbeat_full_review",
        )

        # Quick pulse every 4 hours
        heartbeat_scheduler.add_job(
            heartbeat_runner.run_quick_pulse,
            "interval",
            hours=4,
            id="heartbeat_quick_pulse",
        )

        heartbeat_scheduler.start()
        log.info("heartbeat_scheduler_started", full_review="13:00 UTC daily", quick_pulse="every 4h")
    except ImportError as exc:
        log.warning("heartbeat_scheduler_unavailable", error=str(exc), msg="pip install apscheduler>=3.10.0")
    except Exception as exc:
        log.error("heartbeat_scheduler_error", error=str(exc))

    log.info(
        "polymarket_bot_started",
        mode="OBSERVER (dry-run)" if settings.dry_run else "LIVE",
        port=settings.port,
        wallet=client.wallet_address or "(not configured)",
        strategies=list(deps.strategies.keys()),
        platform_strategies=[n for n, _ in platform_strategies],
        platforms=list(platform_clients.keys()),
        max_exposure=settings.poly_max_exposure,
        default_size=settings.poly_default_size,
        debate_engine=debate_engine.enabled,
        latency_detector=settings.latency_detector_enabled,
        order_flow=order_flow.enabled,
        security_sandbox="active",
        audit_trail="active",
    )

    if settings.dry_run:
        log.info(
            "observer_mode_active",
            msg="OBSERVER MODE — watching markets, logging paper trades, no real orders",
            paper_ledger=settings.paper_ledger_file,
            scoring_interval=settings.paper_ledger_scoring_interval,
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

    if scoring_task and not scoring_task.done():
        scoring_task.cancel()
        try:
            await scoring_task
        except asyncio.CancelledError:
            pass
    if redis_task and not redis_task.done():
        redis_task.cancel()
        try:
            await redis_task
        except asyncio.CancelledError:
            pass

    # Stop platform-specific strategies
    for name, strat in platform_strategies:
        try:
            await strat.stop()
        except Exception:
            pass

    # Stop Kalshi scanner
    if kalshi_scanner:
        await kalshi_scanner.stop()

    for strat in deps.strategies.values():
        await strat.stop()
    await order_flow.stop()
    await latency_detector.stop()
    await signal_bus.stop()
    await orderbook.stop()
    await debate_engine.close()
    await paper_ledger.close()
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
    observer_lines = ""
    if settings.dry_run:
        observer_lines = """║                                                  ║
║  OBSERVER MODE — no real orders placed       ║
║  Paper trades → {ledger:<32}║""".format(
            ledger=settings.paper_ledger_file[:32]
        )

    platforms_str = ", ".join(getattr(deps, "platform_clients", {}).keys()) or "polymarket"
    banner = f"""
╔══════════════════════════════════════════════════╗
║        MULTI-PLATFORM TRADING BOT v3.0           ║
║                                                  ║
║{mode_line}║
║  Port:      {settings.port:<37}║
║  Platforms: {platforms_str[:37]:<37}║
║  Wallet:    {(deps.client.wallet_address or 'NOT SET')[:37]:<37}║
║  Exposure:  ${settings.poly_max_exposure:<36}║
║  Size:      ${settings.poly_default_size:<36}║
{observer_lines}║                                                  ║
║  Endpoints:                                      ║
║    GET  /health        — Health check            ║
║    GET  /status        — Bot status              ║
║    GET  /mode          — Current mode            ║
║    GET  /positions     — Open positions          ║
║    GET  /strategies    — Available strategies    ║
║    GET  /pnl           — Profit & Loss           ║
║    GET  /paper-trades  — Paper trade ledger      ║
║    GET  /paper-pnl     — Paper P&L               ║
║    GET  /markets       — Scanned markets         ║
║    GET  /audit         — Audit trail             ║
║    GET  /security/status — Security sandbox      ║
║    GET  /weather/current — NOAA station data     ║
║    GET  /weather/edges  — Weather market edges    ║
║    POST /start         — Start a strategy        ║
║    POST /stop          — Stop a strategy         ║
║    POST /mode          — Switch mode             ║
║    POST /heartbeat/run — Trigger heartbeat       ║
║    GET  /heartbeat/status — HEARTBEAT.md         ║
║    GET  /heartbeat/reports — Recent reports      ║
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
