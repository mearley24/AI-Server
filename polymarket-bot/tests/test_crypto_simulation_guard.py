"""Regression tests: crypto paper orders blocked in Polymarket simulation-only mode.

Verifies that CryptoClient.place_order() emits crypto_disabled_skip and returns
early (no crypto_paper_order, no PnL record) when KRAKEN_MM_ENABLED and/or
CRYPTO_TRADING_ENABLED are not both set to true.

Env combo under test:
    POLY_DRY_RUN=true
    POLY_OBSERVER_ONLY=false
    POLY_SIMULATION_ONLY=true
    CRYPTO_TRADING_ENABLED=false  (or absent)
    KRAKEN_MM_ENABLED=false       (or absent)
→ expect: no crypto_paper_order, no trade_recorded for any avellaneda fill

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_crypto_simulation_guard.py -v
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from src.platforms.base import Order
from src.platforms.crypto_client import CryptoClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _order() -> Order:
    return Order(
        platform="kraken",
        market_id="XRP/USDT",
        side="buy",
        order_type="limit",
        size=10.0,
        price=0.50,
    )


def _make_client(dry_run: bool = True) -> CryptoClient:
    client = CryptoClient.__new__(CryptoClient)
    client._dry_run = dry_run
    client._paper_trader = MagicMock()
    client._paper_trader.place_order = MagicMock(return_value={"status": "filled", "order_id": "p-001"})
    client._exchange = None
    client._exchange_id = "kraken"
    return client


def _run(coro):
    return asyncio.run(coro)


# ── Guard fires when both flags absent ────────────────────────────────────────

class TestCryptoGuardBlocks:

    def test_no_crypto_paper_order_when_both_flags_absent(self, capsys, monkeypatch):
        """Default env (no flags set) → crypto_disabled_skip, no crypto_paper_order."""
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert result == {"status": "disabled", "order_id": ""}
        client._paper_trader.place_order.assert_not_called()

    def test_no_crypto_paper_order_when_only_mm_enabled(self, capsys, monkeypatch):
        """KRAKEN_MM_ENABLED=true but CRYPTO_TRADING_ENABLED absent → blocked."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert result["status"] == "disabled"

    def test_no_crypto_paper_order_when_only_crypto_enabled(self, capsys, monkeypatch):
        """CRYPTO_TRADING_ENABLED=true but KRAKEN_MM_ENABLED absent → blocked."""
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert result["status"] == "disabled"

    def test_no_crypto_paper_order_when_both_false(self, capsys, monkeypatch):
        """Explicit false values → blocked."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "false")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "false")

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out

    def test_simulation_only_env_combo(self, capsys, monkeypatch):
        """Full simulation-only env combo: POLY_SIMULATION_ONLY=true, both guards off."""
        monkeypatch.setenv("POLY_DRY_RUN", "true")
        monkeypatch.setenv("POLY_OBSERVER_ONLY", "false")
        monkeypatch.setenv("POLY_SIMULATION_ONLY", "true")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "false")
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "false")

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert result["status"] == "disabled"


# ── Guard passes when both flags enabled ──────────────────────────────────────

class TestCryptoGuardAllows:

    def test_crypto_paper_order_when_both_flags_enabled(self, capsys, monkeypatch):
        """Both KRAKEN_MM_ENABLED=true AND CRYPTO_TRADING_ENABLED=true → paper order fires."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" not in out
        assert "crypto_paper_order" in out
        assert result["status"] == "filled"
        client._paper_trader.place_order.assert_called_once()

    def test_various_truthy_values_allowed(self, capsys, monkeypatch):
        """'1' and 'yes' are also truthy for the guards."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "1")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "yes")

        client = _make_client(dry_run=True)
        result = _run(client.place_order(_order()))

        out = capsys.readouterr().out
        assert "crypto_paper_order" in out
        assert result["status"] == "filled"


# ── _crypto_trading_enabled() unit tests ──────────────────────────────────────

class TestCryptoTradingEnabledHelper:

    def test_false_by_default(self, monkeypatch):
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        assert CryptoClient._crypto_trading_enabled() is False

    def test_false_with_only_mm(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        assert CryptoClient._crypto_trading_enabled() is False

    def test_false_with_only_crypto(self, monkeypatch):
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        assert CryptoClient._crypto_trading_enabled() is False

    def test_true_with_both(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        assert CryptoClient._crypto_trading_enabled() is True

    def test_false_with_both_false(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "false")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "false")
        assert CryptoClient._crypto_trading_enabled() is False
