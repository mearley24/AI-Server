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
            await pubsub.subscribe(
                "polymarket:ta_signals",
                "polymarket:intel_signals",
                "polymarket:volume_alerts",
                "polymarket:knowledge_ingest",
                "polymarket:x_strategies",
            )
            log.info(
                "redis_listener_started",
                channels=["polymarket:ta_signals", "polymarket:intel_signals", "polymarket:volume_alerts", "polymarket:knowledge_ingest", "polymarket:x_strategies"],
            )

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                channel = message.get("channel", "")
                try:
                    data = json.loads(message["data"])

                    if channel == "polymarket:intel_signals":
                        relevance = data.get("relevance", 0)
                        if relevance >= 80:
                            signal = Signal(
                                signal_type=SignalType.MARKET_DATA,
                                source=data.get("source", "intel"),
                                data=data,
                            )
                            await signal_bus.publish(signal)
                            log.info(
                                "intel_signal_received",
                                source=data.get("source"),
                                relevance=relevance,
                                summary=str(data.get("summary", ""))[:80],
                            )
                    elif channel == "polymarket:volume_alerts":
                        signal = Signal(
                            signal_type=SignalType.MARKET_DATA,
                            source="volume_alert",
                            data=data,
                        )
                        await signal_bus.publish(signal)
                        log.info(
                            "volume_spike_received",
                            market_id=data.get("market_id", ""),
                            summary=str(data.get("summary", ""))[:80],
                        )
                    elif channel == "polymarket:knowledge_ingest":
                        # Ingest X intel into knowledge graph
                        try:
                            from knowledge.ingest import KnowledgeIngester
                            ingester = KnowledgeIngester()
                            await ingester.ingest_text(
                                text=data.get("text", ""),
                                source_url=data.get("source_url"),
                                source_type="x_intake",
                            )
                            log.info(
                                "x_intel_ingested",
                                author=data.get("author", ""),
                                source_url=data.get("source_url", ""),
                            )
                        except Exception as ingest_exc:
                            log.warning("x_intel_ingest_failed", error=str(ingest_exc)[:200])

                    elif channel == "polymarket:x_strategies":
                        # Log strategy suggestions for heartbeat review
                        strategies = data.get("strategies", [])
                        for strat in strategies:
                            if isinstance(strat, dict):
                                signal = Signal(
                                    signal_type=SignalType.MARKET_DATA,
                                    source="x_strategy_suggestion",
                                    data={
                                        "strategy_name": strat.get("name", ""),
                                        "description": strat.get("description", ""),
                                        "applicable_to": strat.get("applicable_to", []),
                                        "parameters": strat.get("parameters", {}),
                                        "author": data.get("author", ""),
                                    },
                                )
                                await signal_bus.publish(signal)
                        log.info(
                            "x_strategy_suggestions_received",
                            count=len(strategies),
                            author=data.get("author", ""),
                        )
                    else:
                        signal = Signal(
                            signal_type=SignalType.TA_INDICATOR,
                            source=data.get("source", "redis"),
                            data=data,
                        )
                        await signal_bus.publish(signal)
                except (json.JSONDecodeError, Exception) as exc:
                    log.error("redis_signal_parse_error", channel=channel, error=str(exc))
        except Exception as exc:
            log.error("redis_listener_error", error=str(exc))

    return asyncio.create_task(_listen())


_LIVE_GATE_PASSPHRASE = "I_UNDERSTAND_REAL_MONEY_RISK"


def _enforce_live_gate(settings: Any, log: Any) -> bool:
    """Refuse to run strategies in live mode without an explicit opt-in gate.

    Both conditions must be satisfied to allow live trading:
      1. POLY_DRY_RUN=false  (settings.dry_run is False)
      2. POLY_ALLOW_LIVE=I_UNDERSTAND_REAL_MONEY_RISK

    If live mode is requested but the gate env var is absent or wrong,
    settings.dry_run is forced True and all strategies run in paper mode.

    Returns True if live mode was allowed, False if it was blocked.
    """
    if settings.dry_run:
        log.info("live_gate_safe", message="dry_run=True — observer/paper mode")
        return False  # not live, gate not relevant

    allow_live = os.environ.get("POLY_ALLOW_LIVE", "").strip()
    if allow_live == _LIVE_GATE_PASSPHRASE:
        log.warning(
            "live_gate_passed",
            message="Live trading explicitly authorized. Real money at risk.",
        )
        return True  # gate passed, live allowed

    # Gate not set or wrong — force paper mode
    log.critical(
        "live_gate_blocked",
        dry_run_env=os.environ.get("POLY_DRY_RUN", "(not set)"),
        allow_live_present=bool(allow_live),
        message=(
            "LIVE MODE BLOCKED: POLY_DRY_RUN=false but POLY_ALLOW_LIVE is not set "
            "to the required passphrase. Forcing dry_run=True. "
            "No real orders will be placed. "
            "To enable live trading set POLY_ALLOW_LIVE=I_UNDERSTAND_REAL_MONEY_RISK."
        ),
    )
    settings.dry_run = True
    return False  # blocked, forced to paper


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log = structlog.get_logger("main")

    # Try to unlock vault before loading settings
    _maybe_unlock_vault(log)

    settings = load_settings()
    _configure_logging(settings.poly_log_level)
    log = structlog.get_logger("main")

    # ── Live trading gate — must be explicit; default is always paper mode ──
    _enforce_live_gate(settings, log)

    # Ensure data directory exists
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    # Initialise security components
    audit_trail = AuditTrail(
        audit_dir=Path(settings.data_dir) / "audit",
        retention_days=getattr(settings, "security_audit_retention_days", 90),
    )

    sandbox = ExecutionSandbox(
        max_single_trade=settings.security_max_single_trade,
        max_daily_volume=settings.security_max_daily_volume,
        max_daily_loss=settings.security_max_daily_loss,
        max_orders_per_minute=settings.security_max_orders_per_minute,
        max_api_calls_per_minute=settings.security_max_api_calls_per_minute,
        kill_switch_enabled=settings.security_kill_switch_enabled,
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
    rbi_pipeline = None
    rbi_task = None
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
            sandbox=sandbox,
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
    if settings.weather_trader_enabled:
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
    else:
        log.warning("weather_trader_disabled", reason="Strategy lost $163 across 200 markets at 48% win rate. Set WEATHER_TRADER_ENABLED=true to re-enable.")

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

    # Mean reversion — Auto-6 fade on thin-volume spikes
    try:
        from strategies.mean_reversion import MeanReversionStrategy
        mean_reversion = MeanReversionStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        if strategy_manager_enabled:
            managed_strategies.append(("mean_reversion", mean_reversion))
        else:
            platform_strategies.append(("mean_reversion", mean_reversion))
        log.info("strategy_loaded", strategy="mean_reversion")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="mean_reversion", error=str(exc))

    # Pre-resolution scalp — Auto-7
    try:
        from strategies.presolution_scalp import PresolutionScalpStrategy
        presolution_scalp = PresolutionScalpStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        presolution_scalp.set_sandbox(sandbox)
        if strategy_manager_enabled:
            managed_strategies.append(("presolution_scalp", presolution_scalp))
        else:
            platform_strategies.append(("presolution_scalp", presolution_scalp))
        log.info("strategy_loaded", strategy="presolution_scalp")
    except Exception as exc:
        log.warning("strategy_load_failed", strategy="presolution_scalp", error=str(exc))

    # Sports Arb — zero-risk arbitrage buying both sides when combined < $0.98
    try:
        from strategies.sports_arb import SportsArbStrategy
        sports_arb = SportsArbStrategy(
            client=client, settings=settings, scanner=scanner,
            orderbook=orderbook, pnl_tracker=pnl_tracker,
        )
        sports_arb.set_sandbox(sandbox)
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
        flash_crash.set_sandbox(sandbox)
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
        stink_bid.set_sandbox(sandbox)
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

    # ── Kraken Avellaneda Market Maker ─────────────────────────────────
    kraken_strategy = None
    if settings.observer_only:
        log.info("observer_only_skip", path="kraken_market_maker", reason="observer_only=true")
    elif os.environ.get("KRAKEN_API_KEY"):
        try:
            from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker
            from src.platforms.crypto_client import CryptoClient
            kraken_pair = os.environ.get("KRAKEN_TRADING_PAIR", "XRP/USD")
            _kraken_dry = os.environ.get("KRAKEN_DRY_RUN", "true").lower() in {
                "1",
                "true",
                "yes",
            }
            kraken_crypto = CryptoClient(
                exchange_id="kraken",
                api_key=os.environ["KRAKEN_API_KEY"],
                api_secret=os.environ.get("KRAKEN_SECRET", ""),
                dry_run=_kraken_dry,
            )
            kraken_strategy = AvellanedaMarketMaker(
                crypto_client=kraken_crypto,
                signal_bus=signal_bus,
                pairs=[kraken_pair],
                pnl_tracker=pnl_tracker,
            )
            platform_strategies.append(("kraken_mm", kraken_strategy))
            log.info("kraken_market_maker_enabled", pair=kraken_pair)
        except Exception as exc:
            log.error("kraken_market_maker_failed", error=str(exc))
    else:
        log.info("kraken_market_maker_disabled", reason="no API key")

    # Polymarket position redeemer — automatically redeems resolved winning positions
    redeemer = None
    if settings.poly_private_key:
        try:
            from src.redeemer import PolymarketRedeemer
            _redeem_iv = float(os.environ.get("REDEEMER_CHECK_INTERVAL_SEC", "180"))
            redeemer = PolymarketRedeemer(
                private_key=settings.poly_private_key,
                check_interval=max(60.0, _redeem_iv),
                data_dir=settings.data_dir,
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
    deps.kraken_strategy = kraken_strategy
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

    # Register X Intel Processor
    try:
        from strategies.x_intel_processor import XIntelProcessor
        x_intel = XIntelProcessor()
        signal_bus.subscribe(SignalType.MARKET_DATA, x_intel.on_intel_signal)
        deps.x_intel = x_intel
        log.info("x_intel_processor_registered")
    except Exception as exc:
        log.warning("x_intel_processor_failed", error=str(exc)[:100])

    # Wire x_intel boost into copytrade strategy for signal-aware position sizing
    try:
        copytrade_strat = (getattr(deps, "strategies", None) or {}).get("copytrade")
        if copytrade_strat is not None and hasattr(deps, "x_intel") and hasattr(copytrade_strat, "set_x_intel"):
            copytrade_strat.set_x_intel(deps.x_intel)
    except Exception as exc:
        log.warning("x_intel_copytrade_wire_failed", error=str(exc)[:100])

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

    # Position recovery — log a summary of restored positions
    try:
        from src.position_syncer import sync_positions as _sync_pos
        _snap = await _sync_pos(client)
        _by_strat = {}
        for _p in _snap.positions:
            _s = _p.source or "unknown"
            _by_strat[_s] = _by_strat.get(_s, 0) + 1
        log.info(
            "startup_positions_restored",
            count=len(_snap.positions),
            strategies=list(_by_strat.keys()),
            total_value=_snap.total_position_value,
        )
    except Exception as _exc:
        log.debug("startup_position_sync_skipped", error=str(_exc))

    # Periodic position sync — publish fresh data to Redis every 5 minutes
    async def _position_sync_loop():
        """Keep Redis portfolio snapshot fresh for the dashboard."""
        from src.position_syncer import sync_positions as _sync_fn, persist_snapshot_redis
        await asyncio.sleep(60)  # wait 1 min after startup before first periodic sync
        while True:
            try:
                snap = await _sync_fn(client)
                persist_snapshot_redis(snap)
                log.info(
                    "periodic_position_sync",
                    positions=len(snap.positions),
                    total_value=round(snap.total_position_value, 2),
                    usdc=round(snap.usdc_balance, 2),
                )
            except Exception as exc:
                log.warning("periodic_position_sync_error", error=str(exc)[:200])
            await asyncio.sleep(300)  # 5 minutes

    asyncio.create_task(_position_sync_loop())
    log.info("position_sync_loop_started", interval_sec=300)

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

    # ── Treasury system — profit reinvestment + bankroll scaling ──────────
    treasury_manager = None
    try:
        from openclaw.treasury import TreasuryManager
        treasury_manager = TreasuryManager()
        await treasury_manager.update_state()
        deps.treasury_manager = treasury_manager
        log.info("treasury_manager_initialized")
    except Exception as exc:
        log.warning("treasury_init_failed", error=str(exc)[:200])

    # Treasury periodic loop — update state, evaluate alerts, check bankroll scaling
    async def _treasury_loop():
        """Run treasury state update, alerts, bankroll scaling, and weekly report every 15 minutes."""
        _last_treasury_pnl = 0.0
        await asyncio.sleep(120)  # wait 2 min after startup
        while True:
            try:
                if treasury_manager:
                    state = await treasury_manager.update_state()
                    await treasury_manager.evaluate_alerts(state)
                    decision = await treasury_manager.evaluate_bankroll_scaling()
                    if decision.action != "hold":
                        log.info(
                            "treasury_bankroll_scaled",
                            action=decision.action,
                            new_pct=decision.new_max_position_pct,
                            reason=decision.reason,
                        )
                    report = await treasury_manager.maybe_publish_weekly_report()
                    if report:
                        log.info("treasury_weekly_report_sent")

                    # Feed daily realized P&L from strategy manager into treasury
                    current_total = 0.0
                    try:
                        current_total = sum(
                            p.total_pnl for p in (deps.strategy_manager._pnl.values() if deps.strategy_manager else [])
                        )
                        delta = current_total - _last_treasury_pnl
                        if abs(delta) > 0.01:
                            await treasury_manager.record_trading_pnl(delta)
                            _last_treasury_pnl = current_total
                    except Exception:
                        pass

                    # Record weekly P&L for bankroll scaling decisions (Sunday rollover)
                    from datetime import datetime, timezone
                    now_utc = datetime.now(timezone.utc)
                    _last_weekly_day = getattr(_treasury_loop, '_last_weekly_day', -1)
                    if now_utc.weekday() == 6 and _last_weekly_day != now_utc.day:
                        _treasury_loop._last_weekly_day = now_utc.day
                        try:
                            await treasury_manager.record_weekly_pnl(current_total)
                            log.info("treasury_weekly_pnl_recorded", pnl=round(current_total, 2))
                        except Exception:
                            pass

            except Exception as exc:
                log.warning("treasury_loop_error", error=str(exc)[:200])
            await asyncio.sleep(900)  # every 15 minutes

    if treasury_manager:
        asyncio.create_task(_treasury_loop())
        log.info("treasury_loop_started", interval_sec=900)

    # Start Redis TA signal listener
    redis_task = await _start_redis_listener(settings, signal_bus, log)

    # RBI pipeline — paper-backtest pending ideas from ideas.txt (30 min interval)
    if os.environ.get("RBI_PIPELINE_ENABLED", "true").lower() in {"1", "true", "yes"}:
        try:
            from strategies.rbi_pipeline import RBIPipeline

            rbi_pipeline = RBIPipeline()
            rbi_task = asyncio.create_task(rbi_pipeline.run_forever())
            log.info("rbi_pipeline_task_started", interval_sec=1800)
        except Exception as exc:
            log.warning("rbi_pipeline_start_failed", error=str(exc))

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

    # ── Trading readiness structured log ──────────────────────────────
    # Emit once at startup so the blocker state is grep-able in logs.
    # Does NOT make any network calls — reads only what is already resolved.
    _r_kraken_ok = bool(os.environ.get("KRAKEN_SECRET", "").strip())
    _r_ct = (getattr(deps, "strategies", None) or {}).get("copytrade")
    _r_bankroll = getattr(_r_ct, "_bankroll", float(os.environ.get("COPYTRADE_BANKROLL", "300")))
    _r_wallet = (getattr(deps, "client", None) and deps.client.wallet_address) or "not_configured"
    _r_min_trade = 7.50
    _r_blockers: list[str] = []
    if not _r_kraken_ok:
        _r_blockers.append("KRAKEN_SECRET_MISSING")
    if _r_bankroll < _r_min_trade:
        _r_blockers.append(f"BANKROLL_${_r_bankroll:.2f}_BELOW_MIN_${_r_min_trade:.2f}")
    _r_log = log.warning if _r_blockers else log.info
    _r_log(
        "trading_readiness_summary",
        status="BLOCKED" if _r_blockers else "READY",
        blockers=_r_blockers or ["none"],
        polymarket_wallet=_r_wallet,
        actual_bankroll_usdc=round(_r_bankroll, 2),
        kraken_secret_configured=_r_kraken_ok,
        next_action_1=(
            "Set KRAKEN_SECRET in .env then: docker compose up -d polymarket-bot"
            if not _r_kraken_ok else "n/a"
        ),
        next_action_2=(
            f"Fund {_r_wallet} with $50+ USDC on Polygon (current: ${_r_bankroll:.2f})"
            if _r_bankroll < _r_min_trade else "n/a"
        ),
    )

    yield

    # Shutdown
    log.info("polymarket_bot_stopping")

    # Stop heartbeat scheduler
    if heartbeat_scheduler:
        try:
            heartbeat_scheduler.shutdown(wait=False)
        except Exception:
            pass

    if rbi_pipeline is not None:
        try:
            rbi_pipeline.stop()
        except Exception:
            pass
    if rbi_task and not rbi_task.done():
        rbi_task.cancel()
        try:
            await rbi_task
        except asyncio.CancelledError:
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

    if treasury_manager:
        await treasury_manager.close()

    audit_trail.close()
    log.info("polymarket_bot_stopped")


def _print_banner(settings) -> None:
    """Print startup banner with trading readiness indicators."""
    mode_str = "OBSERVER (dry-run)" if settings.dry_run else "LIVE"
    mode_line = f"  Mode:     {mode_str:<37}"

    wallet_addr = (getattr(deps, "client", None) and deps.client.wallet_address) or "NOT SET"

    # Build active strategy list from deps
    active_strats = list((getattr(deps, "strategies", None) or {}).keys())
    strat_line_1 = ", ".join(active_strats[:4]) if active_strats else "none"
    strat_line_2 = ", ".join(active_strats[4:]) if len(active_strats) > 4 else ""

    # ── Trading readiness indicators ──────────────────────────────────
    _kraken_ok = bool(os.environ.get("KRAKEN_SECRET", "").strip())
    _ct = (getattr(deps, "strategies", None) or {}).get("copytrade")
    _actual_bankroll = getattr(_ct, "_bankroll", float(os.environ.get("COPYTRADE_BANKROLL", "300")))
    _min_trade = 7.50

    kraken_status = "[OK] authenticated" if _kraken_ok else "[!!] MISSING KRAKEN_SECRET"
    bankroll_status = (
        f"[OK] ${_actual_bankroll:.2f} USDC on-chain"
        if _actual_bankroll >= _min_trade
        else f"[!!] UNFUNDED ${_actual_bankroll:.2f} USDC (need >=${_min_trade:.2f})"
    )
    _blocked = (not _kraken_ok) or (_actual_bankroll < _min_trade)
    trading_status = "[!!] BLOCKED — no trades will execute" if _blocked else "[OK] READY"

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
║  TRADING READINESS:                                  ║
║  {"Kraken MM:  " + kraken_status[:40]:<52}║
║  {"Polymarket: " + bankroll_status[:40]:<52}║
║  {"Status:     " + trading_status[:40]:<52}║
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
