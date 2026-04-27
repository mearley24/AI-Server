"""Configuration management — loads env vars and optional YAML overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def _load_yaml(path: str | Path | None) -> dict[str, Any]:
    """Load a YAML config file; return empty dict if missing."""
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open() as f:
        data = yaml.safe_load(f) or {}
    return data


class Settings(BaseSettings):
    """All bot configuration — env vars take precedence over YAML."""

    # --- Observer / Dry-run mode ---
    dry_run: bool = Field(default=True, validation_alias="poly_dry_run", description="Observer mode — no real orders, logs paper trades")
    observer_only: bool = Field(default=True, validation_alias="poly_observer_only", description="Observer-only mode — strategies scan/log signals but skip all order placement (paper or live)")
    paper_ledger_file: str = Field(default="/data/paper_trades.jsonl", description="Path to paper trades ledger")
    paper_ledger_scoring_interval: int = Field(default=3600, description="Seconds between resolved-market scoring checks")

    # --- Polymarket credentials ---
    poly_private_key: str = Field(default="", description="Wallet private key (64 hex chars, no 0x)")
    poly_safe_address: str = Field(default="", description="Polymarket Safe address")
    poly_builder_api_key: str = Field(default="", description="Builder Program API key")
    poly_builder_api_secret: str = Field(default="", description="Builder Program API secret")
    poly_builder_api_passphrase: str = Field(default="", description="Builder Program passphrase")

    # --- Trading limits ---
    poly_default_size: float = Field(default=10.0, description="Default position size in USDC")
    poly_max_exposure: float = Field(default=50.0, description="Max total portfolio exposure in USDC")

    # --- API URLs ---
    clob_api_url: str = Field(default="https://clob.polymarket.com")
    gamma_api_url: str = Field(default="https://gamma-api.polymarket.com")
    ws_url: str = Field(default="wss://ws-subscriptions-clob.polymarket.com/ws/market")

    # --- Service ---
    poly_log_level: str = Field(default="info")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8430)
    data_dir: str = Field(default="/data")
    config_yaml_path: str = Field(default="")

    # --- Strategy defaults (overridable via YAML) ---
    stink_bid_drop_threshold: float = Field(default=0.08, description="Min price drop from fair value")
    stink_bid_take_profit: float = Field(default=0.10, description="Take-profit delta")
    stink_bid_stop_loss: float = Field(default=0.08, description="Stop-loss delta")
    stink_bid_markets: list[str] = Field(
        default_factory=lambda: ["BTC", "ETH", "SOL"],
        description="Tokens to scan for stink bid markets",
    )

    flash_crash_drop_threshold: float = Field(default=0.15, description="Orderbook drop to trigger buy")
    flash_crash_window_seconds: int = Field(default=10, description="Seconds to detect drop")
    flash_crash_take_profit: float = Field(default=0.15, description="Take-profit delta")
    flash_crash_stop_loss: float = Field(default=0.10, description="Stop-loss delta")

    # --- Weather Trader ---
    weather_trader_enabled: bool = Field(default=False, description="DISABLED — 48% win rate, -$163 P&L across 200 markets. Re-enable only with improved NOAA model.")
    weather_noaa_stations: list[str] = Field(
        default_factory=lambda: ["KNYC", "KORD", "KLAX", "KDEN", "KJFK", "KATL", "KMIA"],
        description="NOAA station IDs to track",
    )
    weather_edge_threshold: float = Field(default=0.05, description="Minimum edge (5 cents) to enter")
    weather_max_position_size: float = Field(default=25.0, description="Max per-position in USDC")
    weather_check_interval_seconds: float = Field(default=300.0, description="Seconds between checks (5 min)")
    weather_scan_interval_seconds: float = Field(default=300.0, description="NOAA data scan interval (5 min)")
    weather_min_edge_cents: int = Field(default=5, description="Minimum edge in cents to consider")
    weather_strong_edge_cents: int = Field(default=10, description="Strong edge for half-size position")
    weather_very_strong_edge_cents: int = Field(default=15, description="Very strong edge for full-size position")
    weather_take_profit_edge_cents: int = Field(default=2, description="Exit when edge narrows to this")
    weather_stop_loss_pct: float = Field(default=0.15, description="Stop loss at 15% of position value")
    weather_exit_before_resolution_minutes: int = Field(default=30, description="Exit N minutes before settlement")
    visual_crossing_api_key: str = Field(default="", description="Optional Visual Crossing API key for faster data")

    # --- Sports Arb ---
    sports_arb_arb_threshold: float = Field(default=0.97, description="Max combined price for arbitrage — tightened from 0.995 to require genuine arb")
    sports_arb_scan_interval_seconds: float = Field(default=45.0, description="Scan interval in seconds")
    sports_arb_max_position_per_side: float = Field(default=10.0, description="Max position per side — reduced from 5000 to 10")
    sports_arb_slippage_tolerance: float = Field(default=0.005, description="Slippage tolerance")
    sports_arb_min_liquidity_shares: int = Field(default=100, description="Min liquidity in shares")

    # --- BTC Price Feed ---
    btc_feed_source: str = Field(default="kraken", description="BTC price feed: 'kraken', 'coinbase', or 'binance'")

    # --- Latency Detector ---
    latency_detector_enabled: bool = Field(default=True, description="Enable BTC-Polymarket latency detector")
    latency_binance_symbol: str = Field(default="btcusdt", description="Binance symbol to monitor (legacy, used when btc_feed_source=binance)")
    latency_momentum_window_seconds: float = Field(default=10.0, description="Momentum calculation window")
    latency_price_change_threshold_pct: float = Field(default=0.11, description="Min BTC move % to signal")
    latency_polymarket_lag_threshold_seconds: float = Field(default=3.0, description="Min Polymarket lag")
    latency_signal_cooldown_seconds: float = Field(default=30.0, description="Cooldown between signals")
    latency_entry_delay_ms: int = Field(default=9000, description="Wait ms after detection before entry window opens")
    latency_entry_window_ms: int = Field(default=7000, description="Entry window duration ms (closes at delay + window)")
    latency_track_timing_metrics: bool = Field(default=True, description="Track Binance-Polymarket timing metrics")

    # --- Debate Engine ---
    debate_enabled: bool = Field(default=True, description="Enable bull/bear debate engine")
    debate_model: str = Field(default="claude-3-5-sonnet-20241022", description="Claude model for debates")
    debate_min_position_for_debate: float = Field(default=25.0, description="Only debate trades >= this size")
    debate_confidence_threshold: float = Field(default=0.65, description="Min confidence to proceed")
    debate_max_debate_time_seconds: float = Field(default=240.0, description="Max debate duration (local LLMs often need 60s+)")

    # --- Redis ---
    redis_url: str = Field(default_factory=lambda: __import__("os").environ.get("REDIS_URL", "redis://redis:6379"), description="Redis connection URL")

    # Polygon chain id
    chain_id: int = Field(default=137)

    # --- Multi-platform: Enabled platforms ---
    platforms_enabled: str = Field(default="polymarket", description="Comma-separated list of enabled platforms")

    # --- Kalshi ---
    kalshi_api_key_id: str = Field(default="", description="Kalshi API key UUID")
    kalshi_private_key_path: str = Field(default="/app/secrets/kalshi.key", description="Path to Kalshi RSA private key")
    kalshi_environment: str = Field(default="demo", description="'demo' or 'production'")
    kalshi_dry_run: bool = Field(default=True, description="Kalshi paper trading mode")
    kalshi_scan_interval: float = Field(default=300.0, description="Kalshi market scan interval (seconds)")
    kalshi_edge_threshold: float = Field(default=0.08, description="Min edge to trade on Kalshi")
    kalshi_max_position_size: float = Field(default=20.0, description="Max Kalshi position in contracts")
    kalshi_fed_enabled: bool = Field(default=True, description="Enable Kalshi Fed/economics strategy")
    kalshi_weather_enabled: bool = Field(default=True, description="Enable Kalshi weather strategy")

    # --- Crypto (CCXT) ---
    kraken_api_key: str = Field(default="", description="Kraken API key")
    kraken_api_secret: str = Field(default="", description="Kraken API secret")
    kraken_dry_run: bool = Field(default=True, description="Crypto paper trading mode")
    crypto_exchange: str = Field(default="kraken", description="Primary crypto exchange (CCXT ID)")
    crypto_symbols: list[str] = Field(
        default_factory=lambda: ["XRP/USD", "XCN/USD", "PI/USD"],
        description="Crypto symbols to trade",
    )
    crypto_trade_amount_usd: float = Field(default=50.0, description="Per-trade amount in USD")
    crypto_max_position_usd: float = Field(default=500.0, description="Max per-symbol position in USD")
    crypto_max_total_exposure_usd: float = Field(default=2000.0, description="Max total crypto exposure in USD")
    crypto_poll_interval_seconds: float = Field(default=60.0, description="Crypto strategy poll interval")
    crypto_btc_correlation_enabled: bool = Field(default=False, description="Enable BTC correlation strategy")
    crypto_mean_reversion_enabled: bool = Field(default=False, description="Enable mean reversion strategy")
    crypto_momentum_enabled: bool = Field(default=False, description="Enable momentum strategy (Phase 2)")

    # --- Avellaneda-Stoikov Market Maker (DISABLED — can't profit on Kraken, see momentum_mr) ---
    crypto_avellaneda_enabled: bool = Field(default=False, description="Enable Avellaneda-Stoikov market maker")
    avellaneda_pairs: list[str] = Field(
        default_factory=lambda: ["XRP/USD"],
        description="Pairs for Avellaneda MM to quote",
    )
    avellaneda_risk_aversion: float = Field(default=0.1, description="Risk aversion parameter (γ)")
    avellaneda_session_horizon_seconds: float = Field(default=3600, description="Rolling session horizon (T)")
    avellaneda_volatility_window: int = Field(default=100, description="Mid-price observations for volatility estimate")
    avellaneda_max_inventory: float = Field(default=250.0, description="Max position in base units per pair")
    avellaneda_min_spread_bps: float = Field(default=5.0, description="Global minimum spread in basis points (fallback)")
    avellaneda_max_spread_bps: float = Field(default=200.0, description="Global maximum spread in basis points (fallback)")
    avellaneda_order_size_usdt: float = Field(default=50.0, description="Global order size per quote in USDT (fallback)")
    avellaneda_tick_interval: float = Field(default=60.0, description="Seconds between quoting ticks")
    avellaneda_fee_bps: float = Field(default=16.0, description="Per-side exchange fee in basis points (Kraken maker: 16)")
    avellaneda_pair_configs: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "BTC/USDT": {"min_spread_bps": 10, "max_spread_bps": 100, "order_size_usdt": 50.0, "max_inventory_usdt": 250.0},
            "XRP/USD": {"min_spread_bps": 33, "max_spread_bps": 35, "order_size_usdt": 50.0, "max_inventory_usdt": 500.0},
            "SOL/USDT": {"min_spread_bps": 20, "max_spread_bps": 150, "order_size_usdt": 50.0, "max_inventory_usdt": 250.0},
        },
        description="Per-pair overrides for spread bounds, order size, and inventory limits",
    )
    avellaneda_max_total_exposure: float = Field(default=500.0, description="Max total open order value in USDT before skipping new orders")
    avellaneda_hawkes_mu: float = Field(default=1.0, description="Hawkes baseline arrival rate")
    avellaneda_hawkes_alpha: float = Field(default=0.5, description="Hawkes excitation parameter")
    avellaneda_hawkes_beta: float = Field(default=2.0, description="Hawkes decay parameter")
    avellaneda_hawkes_window: float = Field(default=300.0, description="Hawkes lookback window (seconds)")
    avellaneda_hawkes_sensitivity: float = Field(default=0.5, description="Hawkes imbalance sensitivity (η)")
    avellaneda_vpin_bucket_volume: float = Field(default=1000.0, description="VPIN bucket volume (USDT)")
    avellaneda_vpin_num_buckets: int = Field(default=50, description="VPIN rolling bucket count")
    avellaneda_vpin_warning: float = Field(default=0.4, description="VPIN warning threshold")
    avellaneda_vpin_danger: float = Field(default=0.6, description="VPIN danger threshold")
    avellaneda_vpin_critical: float = Field(default=0.8, description="VPIN critical threshold (stop quoting)")
    avellaneda_vpin_cooldown: float = Field(default=60.0, description="VPIN cooldown seconds after recovery")

    # --- Polymarket Copy-Trading Strategy ---
    copytrade_enabled: bool = Field(default=True, description="Enable Polymarket copy-trading")
    copytrade_size_usd: float = Field(default=3.0, description="USD per copied trade — tiered by wallet quality and entry price bracket")
    copytrade_max_positions: int = Field(default=30, description="Max concurrent copied positions — concentrated, not spray-and-pray")
    copytrade_min_win_rate: float = Field(default=0.60, description="Minimum wallet win rate to copy")
    copytrade_min_trades: int = Field(default=20, description="Minimum resolved trades for wallet to qualify")
    copytrade_scan_interval_hours: float = Field(default=6.0, description="Hours between wallet re-scans")
    copytrade_check_interval: float = Field(default=30.0, description="Seconds between trade checks")
    copytrade_daily_loss_limit: float = Field(default=30.0, description="Max net daily loss before halting trades")

    # --- Momentum/Mean-Reversion Hybrid Strategy ---
    crypto_momentum_mr_enabled: bool = Field(default=False, description="Enable momentum/mean-reversion strategy")
    momentum_mr_pairs: list[str] = Field(default_factory=lambda: ["XRP/USD"])
    momentum_mr_order_size_usd: float = Field(default=50.0)
    momentum_mr_tick_interval: float = Field(default=15.0)
    momentum_mr_vwap_window_minutes: float = Field(default=15.0)
    momentum_mr_ema_fast: int = Field(default=5)
    momentum_mr_ema_slow: int = Field(default=20)
    momentum_mr_buy_dip_pct: float = Field(default=0.003, description="Buy when price is this % below VWAP")
    momentum_mr_sell_rip_pct: float = Field(default=0.003, description="Sell when price is this % above VWAP")
    momentum_mr_take_profit_pct: float = Field(default=0.002, description="Take profit at this % gain")
    momentum_mr_stop_loss_pct: float = Field(default=0.005, description="Stop loss at this % loss")
    momentum_mr_max_trades_per_hour: int = Field(default=10)
    momentum_mr_max_inventory_usd: float = Field(default=500.0)

    # --- Execution sandbox limits (account-appropriate; overridable via env) ---
    # Defaults are conservative — right-size these for your actual account balance.
    security_max_single_trade: float = Field(default=10.0, description="Max per-trade notional in USDC")
    security_max_daily_volume: float = Field(default=100.0, description="Max daily trading volume in USDC")
    security_max_daily_loss: float = Field(default=50.0, description="Daily P&L loss that fires the kill switch")
    security_max_orders_per_minute: int = Field(default=5, description="Order rate cap")
    security_max_api_calls_per_minute: int = Field(default=60, description="API call rate cap")
    security_kill_switch_enabled: bool = Field(default=True, description="Enable automatic kill switch")
    security_audit_retention_days: int = Field(default=90, description="Days to keep audit log files")

    @field_validator("poly_log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        return v.upper()

    model_config = {
        "env_prefix": "",
        "extra": "ignore",
        "populate_by_name": True,
    }


_YAML_FLATTENED_SECTIONS = ("strategies", "security", "kalshi", "crypto")


def load_settings() -> Settings:
    """Build settings: env vars → YAML overrides where env is empty."""
    yaml_path = os.environ.get("POLY_CONFIG_YAML", "")
    yaml_data = _load_yaml(yaml_path) if yaml_path else {}

    # Flatten YAML sections into env-compatible keys for Pydantic
    env_overrides: dict[str, Any] = {}

    # strategies.stink_bid.size → stink_bid_size
    strategies_cfg = yaml_data.get("strategies", {})
    for strategy_name, params in strategies_cfg.items():
        if isinstance(params, dict):
            for k, v in params.items():
                env_overrides[f"{strategy_name}_{k}"] = v

    # security.max_single_trade → security_max_single_trade
    # kalshi.dry_run → kalshi_dry_run  (etc.)
    for section in ("security", "kalshi", "crypto"):
        section_data = yaml_data.get(section, {})
        if isinstance(section_data, dict):
            for k, v in section_data.items():
                env_overrides[f"{section}_{k}"] = v

    # All remaining top-level scalar keys (dry_run, redis_url, …)
    top_level = {
        k: v for k, v in yaml_data.items()
        if k not in _YAML_FLATTENED_SECTIONS
    }
    env_overrides.update(top_level)

    return Settings(**{k: v for k, v in env_overrides.items() if os.environ.get(k.upper(), "") == ""})
