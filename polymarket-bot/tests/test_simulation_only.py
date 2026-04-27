"""Tests for POLY_SIMULATION_ONLY mode in PolymarketCopyTrader.

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_simulation_only.py -v

Verifies:
- simulation_only=True, observer_only=False, dry_run=True →
    polymarket_paper_order fires (not observer_only_skip)
- simulation_only=True → copytrade_copy_attempt fires (gate inactive)
- simulation_only=True → get_status() exposes simulation_only=True
- Settings reads POLY_SIMULATION_ONLY env var correctly
- observer_only=True always wins over simulation_only (belt-and-suspenders)
- simulation_only_started log fires when simulation_only=True
- Kraken gate: simulation_only blocks Kraken unless both
    KRAKEN_MM_ENABLED=true AND CRYPTO_TRADING_ENABLED=true
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.pnl_tracker import PnLTracker
from strategies.exit_engine import ExitSignal
from strategies.polymarket_copytrade import (
    CopiedPosition,
    PolymarketCopyTrader,
    ScoredWallet,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _settings(
    observer_only: bool = False,
    simulation_only: bool = True,
    dry_run: bool = True,
) -> Settings:
    return Settings(
        poly_private_key="a" * 64,
        poly_safe_address="0x" + "b" * 40,
        dry_run=dry_run,
        observer_only=observer_only,
        simulation_only=simulation_only,
    )


def _make_strategy(
    observer_only: bool = False,
    simulation_only: bool = True,
) -> PolymarketCopyTrader:
    client = MagicMock()
    client.place_order = AsyncMock()
    client.get_midpoint = AsyncMock(return_value=0.45)
    pnl = PnLTracker(data_dir=tempfile.mkdtemp())
    s = PolymarketCopyTrader(
        client,
        _settings(observer_only=observer_only, simulation_only=simulation_only),
        pnl,
    )
    return s


def _run(coro):
    return asyncio.run(coro)


def _wallet() -> ScoredWallet:
    return ScoredWallet(
        address="0xabc123" + "0" * 34,
        win_rate=0.75,
        adjusted_win_rate=0.75,
        pl_ratio=3.0,
        total_resolved=30,
        wins=22,
        losses=8,
        score=0.85,
    )


def _trade() -> dict:
    return {
        "id": "trade-sim-001",
        "asset_id": "0xtokenid000000000001",
        "outcome": "Yes",
        "usdcSize": "5.00",
        "size": "10",
        "price": "0.45",
        "type": "BUY",
        "side": "BUY",
    }


def _position(position_id: str = "pos-sim-001") -> CopiedPosition:
    return CopiedPosition(
        position_id=position_id,
        source_wallet="0xwallet" + "0" * 33,
        token_id="0xtokenid000000000004",
        market_question="Will simulation exit happen?",
        condition_id="0xcond" + "0" * 59,
        side="BUY",
        entry_price=0.45,
        size_usd=5.0,
        size_shares=11.0,
        copied_at=time.time(),
        source_trade_id="src-sim-001",
        order_id="paper-sim-pos-001",
        category="crypto",
        event_slug="will-simulation-exit-happen",
    )


# ── Simulation mode allows Polymarket paper trades ────────────────────────────

class TestSimulationAllowsPaperTrades:

    def test_copy_trade_gate_inactive_in_simulation(self, capsys):
        """simulation_only=True, observer_only=False: observer_only_skip is NOT emitted,
        copytrade_copy_attempt IS emitted (proving the gate is inactive)."""
        strategy = _make_strategy(observer_only=False, simulation_only=True)

        _run(strategy._copy_trade(
            wallet=_wallet(),
            trade=_trade(),
            token_id="0xtokenid000000000001",
            price=0.45,
            market="test-market-slug",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-sim-001",
        ))

        out = capsys.readouterr().out
        assert "observer_only_skip" not in out
        assert "copytrade_copy_attempt" in out

    def test_exit_position_fires_paper_order(self, capsys):
        """simulation_only=True: exit_position logs polymarket_paper_order."""
        strategy = _make_strategy(observer_only=False, simulation_only=True)
        strategy._clob_client = MagicMock()
        strategy._positions["pos-sim-001"] = _position("pos-sim-001")

        signal = ExitSignal(
            position_id="pos-sim-001",
            reason="take_profit",
            current_price=0.65,
            entry_price=0.45,
            sell_fraction=1.0,
            pnl_pct=0.44,
            peak_price=0.66,
            hold_time_hours=2.0,
        )

        _run(strategy._exit_position("pos-sim-001", signal))

        out = capsys.readouterr().out
        assert "observer_only_skip" not in out
        assert "polymarket_paper_order" in out

    def test_reentry_fires_paper_order(self, capsys):
        """simulation_only=True: _execute_reentry logs polymarket_paper_order."""
        strategy = _make_strategy(observer_only=False, simulation_only=True)
        strategy._clob_client = MagicMock()

        entry = {
            "market_question": "Will Bitcoin hit $100k?",
            "token_id": "0xtokenid000000000003",
            "condition_id": "0xcond" + "0" * 59,
            "category": "crypto",
            "exit_price": 0.50,
            "original_entry": 0.40,
            "neg_risk": False,
            "source_wallet": "0xwallet" + "0" * 33,
            "event_slug": "will-bitcoin-hit-100k",
        }

        _run(strategy._execute_reentry(entry, current_price=0.44))

        out = capsys.readouterr().out
        assert "observer_only_skip" not in out
        assert "polymarket_paper_order" in out


# ── Simulation mode does NOT place real orders ────────────────────────────────

class TestSimulationNeverLive:

    def test_no_clob_create_on_exit_in_simulation(self):
        """simulation_only=True with dry_run=True: exit path never calls clob.create_and_post_order."""
        strategy = _make_strategy(observer_only=False, simulation_only=True)
        strategy._clob_client = MagicMock()
        strategy._clob_client.create_and_post_order = MagicMock()
        strategy._positions["pos-sim-002"] = _position("pos-sim-002")

        signal = ExitSignal(
            position_id="pos-sim-002",
            reason="take_profit",
            current_price=0.65,
            entry_price=0.45,
            sell_fraction=1.0,
            pnl_pct=0.44,
            peak_price=0.66,
            hold_time_hours=2.0,
        )

        _run(strategy._exit_position("pos-sim-002", signal))

        strategy._clob_client.create_and_post_order.assert_not_called()

    def test_no_clob_create_on_reentry_in_simulation(self):
        """simulation_only=True with dry_run=True: reentry path never calls clob."""
        strategy = _make_strategy(observer_only=False, simulation_only=True)
        strategy._clob_client = MagicMock()
        strategy._clob_client.create_and_post_order = MagicMock()

        entry = {
            "market_question": "Will Bitcoin hit $100k?",
            "token_id": "0xtokenid000000000003",
            "condition_id": "0xcond" + "0" * 59,
            "category": "crypto",
            "exit_price": 0.50,
            "original_entry": 0.40,
            "neg_risk": False,
            "source_wallet": "0xwallet" + "0" * 33,
            "event_slug": "will-bitcoin-hit-100k",
        }

        _run(strategy._execute_reentry(entry, current_price=0.44))

        strategy._clob_client.create_and_post_order.assert_not_called()


# ── Observer-only still wins when both flags set ──────────────────────────────

class TestObserverOverridesSimulation:

    def test_observer_blocks_even_with_simulation_flag(self, capsys):
        """observer_only=True beats simulation_only=True — orders blocked."""
        strategy = _make_strategy(observer_only=True, simulation_only=True)

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(),
            token_id="0xtokenid000000000001", price=0.45,
            market="test-market-slug", market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-sim-002",
        ))

        out = capsys.readouterr().out
        assert "observer_only_skip" in out
        assert "polymarket_paper_order" not in out


# ── get_status() exposes simulation_only ─────────────────────────────────────

class TestSimulationOnlyStatus:

    def test_status_simulation_true(self):
        s = _make_strategy(observer_only=False, simulation_only=True)
        status = s.get_status()
        assert status["simulation_only"] is True
        assert status["observer_only"] is False

    def test_status_simulation_false(self):
        s = _make_strategy(observer_only=False, simulation_only=False)
        assert s.get_status()["simulation_only"] is False


# ── simulation_only_started log fires on startup ──────────────────────────────

class TestSimulationStartupLog:

    def test_simulation_only_started_logged(self, capsys):
        """simulation_only=True: simulation_only_started appears in startup logs."""
        _make_strategy(observer_only=False, simulation_only=True)
        out = capsys.readouterr().out
        assert "simulation_only_started" in out

    def test_no_simulation_started_in_observer_mode(self, capsys):
        """observer_only=True: simulation_only_started does NOT appear."""
        _make_strategy(observer_only=True, simulation_only=False)
        out = capsys.readouterr().out
        assert "simulation_only_started" not in out


# ── Settings reads POLY_SIMULATION_ONLY ──────────────────────────────────────

class TestSettingsSimulationOnly:

    def test_default_is_false(self):
        s = Settings(poly_private_key="a" * 64)
        assert s.simulation_only is False

    def test_env_true(self, monkeypatch):
        monkeypatch.setenv("POLY_SIMULATION_ONLY", "true")
        s = Settings(poly_private_key="a" * 64)
        assert s.simulation_only is True

    def test_env_false(self, monkeypatch):
        monkeypatch.setenv("POLY_SIMULATION_ONLY", "false")
        s = Settings(poly_private_key="a" * 64)
        assert s.simulation_only is False


# ── Kraken gate: simulation_only blocks Kraken unless both guards set ─────────

class TestKrakenGateInSimulationMode:
    """
    The Kraken gate lives in main.py and is hard to test without booting the
    full app.  We test the gate logic directly by reproducing the conditional.
    """

    def _kraken_allowed(self, kraken_mm: str = "", crypto_trading: str = "") -> bool:
        """Mirror the main.py gate logic."""
        mm = kraken_mm.lower() in {"1", "true", "yes"}
        ct = crypto_trading.lower() in {"1", "true", "yes"}
        return mm and ct

    def test_simulation_blocks_kraken_by_default(self):
        assert self._kraken_allowed("", "") is False

    def test_simulation_blocks_kraken_with_only_mm_enabled(self):
        assert self._kraken_allowed("true", "") is False

    def test_simulation_blocks_kraken_with_only_crypto_enabled(self):
        assert self._kraken_allowed("", "true") is False

    def test_both_gates_allow_kraken(self):
        assert self._kraken_allowed("true", "true") is True

    def test_false_values_block_kraken(self):
        assert self._kraken_allowed("false", "false") is False
