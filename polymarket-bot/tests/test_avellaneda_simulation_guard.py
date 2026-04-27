"""Integration tests: Avellaneda loop/tick blocked in simulation-only mode.

Verifies that when KRAKEN_MM_ENABLED and/or CRYPTO_TRADING_ENABLED are not
both set to true, the Avellaneda strategy's _run_loop() and _place_quote()
emit crypto_disabled_skip and produce NO crypto_paper_order and NO
trade_recorded events — even with a live CryptoClient in dry_run mode.

Env combo under test:
    POLY_DRY_RUN=true
    POLY_OBSERVER_ONLY=false
    POLY_SIMULATION_ONLY=true
    KRAKEN_MM_ENABLED=false  (or absent)
    CRYPTO_TRADING_ENABLED=false  (or absent)

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_avellaneda_simulation_guard.py -v
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pnl_tracker import PnLTracker, Trade
from src.platforms.base import Order
from src.signal_bus import SignalBus
from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_mm(pnl: PnLTracker | None = None) -> AvellanedaMarketMaker:
    client = MagicMock()
    client.platform_name = "kraken"
    client.is_dry_run = True
    client.exchange = None  # no real exchange in tests
    client.place_order = AsyncMock(return_value={"status": "filled", "id": "paper-001"})
    client.get_orderbook = AsyncMock(return_value={
        "bids": [["0.50", "1000"]],
        "asks": [["0.51", "1000"]],
    })
    client.cancel_order = AsyncMock(return_value=True)
    client.get_open_orders = AsyncMock(return_value=[])
    client.get_my_trades = AsyncMock(return_value=[])
    bus = MagicMock(spec=SignalBus)
    bus.publish = AsyncMock()
    if pnl is None:
        pnl = PnLTracker(data_dir=tempfile.mkdtemp())
    return AvellanedaMarketMaker(
        crypto_client=client,
        signal_bus=bus,
        pairs=["XRP/USD"],
        order_size_usdt=50.0,
        tick_interval=0.01,
        pnl_tracker=pnl,
    )


def _run(coro):
    return asyncio.run(coro)


# ── _place_quote guard: no trade_recorded when disabled ───────────────────────

class TestPlaceQuoteGuardBlocked:

    def test_no_trade_recorded_when_both_flags_absent(self, capsys, monkeypatch):
        """Both flags absent → crypto_disabled_skip, no trade_recorded."""
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        pnl = PnLTracker(data_dir=tempfile.mkdtemp())
        mm = _make_mm(pnl)

        _run(mm._place_quote("XRP/USD", "buy", 0.50, 5.0, 0.505, 0.001, 0.01))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert "trade_recorded" not in out
        mm._client.place_order.assert_not_called()

    def test_no_trade_recorded_when_only_mm_enabled(self, capsys, monkeypatch):
        """KRAKEN_MM_ENABLED=true but CRYPTO_TRADING_ENABLED absent → blocked."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        mm = _make_mm()

        _run(mm._place_quote("XRP/USD", "buy", 0.50, 5.0, 0.505, 0.001, 0.01))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "trade_recorded" not in out
        mm._client.place_order.assert_not_called()

    def test_no_trade_recorded_when_only_crypto_enabled(self, capsys, monkeypatch):
        """CRYPTO_TRADING_ENABLED=true but KRAKEN_MM_ENABLED absent → blocked."""
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        mm = _make_mm()

        _run(mm._place_quote("XRP/USD", "buy", 0.50, 5.0, 0.505, 0.001, 0.01))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "trade_recorded" not in out
        mm._client.place_order.assert_not_called()

    def test_full_simulation_only_env_combo(self, capsys, monkeypatch):
        """Full simulation-only combo: all three flags set, both guards off."""
        monkeypatch.setenv("POLY_DRY_RUN", "true")
        monkeypatch.setenv("POLY_OBSERVER_ONLY", "false")
        monkeypatch.setenv("POLY_SIMULATION_ONLY", "true")
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "false")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "false")

        pnl = PnLTracker(data_dir=tempfile.mkdtemp())
        mm = _make_mm(pnl)

        _run(mm._place_quote("XRP/USD", "buy", 0.50, 5.0, 0.505, 0.001, 0.01))
        _run(mm._place_quote("XRP/USD", "sell", 0.51, 5.0, 0.505, 0.001, 0.01))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "crypto_paper_order" not in out
        assert "trade_recorded" not in out
        mm._client.place_order.assert_not_called()
        assert len(pnl._trades) == 0


# ── _place_quote guard: allows orders when both flags enabled ──────────────────

class TestPlaceQuoteGuardAllows:

    def test_trade_recorded_when_both_flags_enabled(self, capsys, monkeypatch):
        """Both flags true → order placed, dry-run fill recorded."""
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        pnl = PnLTracker(data_dir=tempfile.mkdtemp())
        mm = _make_mm(pnl)

        _run(mm._place_quote("XRP/USD", "buy", 0.50, 5.0, 0.505, 0.001, 0.01))

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" not in out
        assert "trade_recorded" in out
        mm._client.place_order.assert_called_once()
        assert len(pnl._trades) == 1
        assert pnl._trades[0].strategy == "avellaneda"


# ── _run_loop guard: loop idles when disabled ─────────────────────────────────

class TestRunLoopGuardBlocked:

    def test_run_loop_emits_disabled_skip_and_skips_tick(self, capsys, monkeypatch):
        """_run_loop emits crypto_disabled_skip and never calls _tick when disabled."""
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        mm = _make_mm()
        mm._running = True

        async def _run_one_iteration():
            # Run the loop for one iteration then stop
            mm._running = True
            task = asyncio.create_task(mm._run_loop())
            await asyncio.sleep(0.05)
            mm._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with patch.object(mm, "_tick", new=AsyncMock()) as mock_tick:
            _run(_run_one_iteration())
            mock_tick.assert_not_called()

        out = capsys.readouterr().out
        assert "crypto_disabled_skip" in out
        assert "avellaneda" in out


# ── _crypto_trading_enabled() unit tests ──────────────────────────────────────

class TestCryptoTradingEnabledHelper:

    def test_false_by_default(self, monkeypatch):
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        assert AvellanedaMarketMaker._crypto_trading_enabled() is False

    def test_false_with_only_mm(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.delenv("CRYPTO_TRADING_ENABLED", raising=False)
        assert AvellanedaMarketMaker._crypto_trading_enabled() is False

    def test_false_with_only_crypto(self, monkeypatch):
        monkeypatch.delenv("KRAKEN_MM_ENABLED", raising=False)
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        assert AvellanedaMarketMaker._crypto_trading_enabled() is False

    def test_true_with_both(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "true")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "true")
        assert AvellanedaMarketMaker._crypto_trading_enabled() is True

    def test_false_with_both_false(self, monkeypatch):
        monkeypatch.setenv("KRAKEN_MM_ENABLED", "false")
        monkeypatch.setenv("CRYPTO_TRADING_ENABLED", "false")
        assert AvellanedaMarketMaker._crypto_trading_enabled() is False
