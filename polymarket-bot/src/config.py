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
    poly_max_exposure: float = Field(default=100.0, description="Max total portfolio exposure in USDC")

    # --- API URLs ---
    clob_api_url: str = Field(default="https://clob.polymarket.com")
    gamma_api_url: str = Field(default="https://gamma-api.polymarket.com")
    ws_url: str = Field(default="wss://ws-subscriptions-clob.polymarket.com/ws/")

    # --- Service ---
    poly_log_level: str = Field(default="info")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8430)
    data_dir: str = Field(default="/data")
    config_yaml_path: str = Field(default="")

    # --- Strategy defaults (overridable via YAML) ---
    stink_bid_drop_threshold: float = Field(default=0.15, description="Min price drop from fair value")
    stink_bid_take_profit: float = Field(default=0.10, description="Take-profit delta")
    stink_bid_stop_loss: float = Field(default=0.08, description="Stop-loss delta")
    stink_bid_markets: list[str] = Field(
        default_factory=lambda: ["BTC", "ETH", "SOL"],
        description="Tokens to scan for stink bid markets",
    )

    flash_crash_drop_threshold: float = Field(default=0.30, description="Orderbook drop to trigger buy")
    flash_crash_window_seconds: int = Field(default=10, description="Seconds to detect drop")
    flash_crash_take_profit: float = Field(default=0.15, description="Take-profit delta")
    flash_crash_stop_loss: float = Field(default=0.10, description="Stop-loss delta")

    # --- Weather Trader ---
    weather_trader_enabled: bool = Field(default=False, description="Enable weather trader strategy")
    weather_noaa_stations: list[str] = Field(
        default_factory=lambda: ["KDEN", "KJFK", "KLAX"],
        description="NOAA station IDs to track",
    )
    weather_edge_threshold: float = Field(default=0.10, description="Minimum edge (10%) to enter")
    weather_max_position_size: float = Field(default=10.0, description="Max per-position in USDC")
    weather_check_interval_seconds: float = Field(default=300.0, description="Seconds between checks")

    # --- Latency Detector ---
    latency_detector_enabled: bool = Field(default=True, description="Enable Binance-Polymarket latency detector")
    latency_binance_symbol: str = Field(default="btcusdt", description="Binance symbol to monitor")
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
    debate_max_debate_time_seconds: float = Field(default=10.0, description="Max debate duration")

    # --- Redis ---
    redis_url: str = Field(default="redis://redis:6379", description="Redis connection URL")

    # Polygon chain id
    chain_id: int = Field(default=137)

    @field_validator("poly_log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        return v.upper()

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "extra": "ignore",
        "populate_by_name": True,
    }


def load_settings() -> Settings:
    """Build settings: env vars → YAML overrides where env is empty."""
    yaml_path = os.environ.get("POLY_CONFIG_YAML", "")
    yaml_data = _load_yaml(yaml_path) if yaml_path else {}

    # Flatten YAML sections into env-compatible keys for Pydantic
    env_overrides: dict[str, Any] = {}
    strategies_cfg = yaml_data.get("strategies", {})
    for strategy_name, params in strategies_cfg.items():
        for k, v in params.items():
            env_overrides[f"{strategy_name}_{k}"] = v

    top_level = {k: v for k, v in yaml_data.items() if k != "strategies"}
    env_overrides.update(top_level)

    return Settings(**{k: v for k, v in env_overrides.items() if os.environ.get(k.upper(), "") == ""})
