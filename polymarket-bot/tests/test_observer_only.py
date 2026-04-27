"""Tests for POLY_OBSERVER_ONLY mode in PolymarketCopyTrader.

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_observer_only.py -v

Verifies:
- observer_only=True → observer_only_skip logged, no copytrade_copy_attempt
- observer_only=True → whale signal tier 2-4 skipped before order path
- observer_only=True → reentry skipped before order path
- observer_only=True → exit_position skipped before order path
- observer_only=False → copytrade_copy_attempt fires normally (gate inactive)
- observer_only field appears in get_status()
- Settings reads POLY_OBSERVER_ONLY env var correctly
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock

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

def _settings(observer_only: bool = True, dry_run: bool = True) -> Settings:
    return Settings(
        poly_private_key="a" * 64,
        poly_safe_address="0x" + "b" * 40,
        dry_run=dry_run,
        observer_only=observer_only,
    )


def _make_strategy(observer_only: bool = True) -> PolymarketCopyTrader:
    client = MagicMock()
    client.place_order = AsyncMock()
    client.get_midpoint = AsyncMock(return_value=0.45)
    pnl = PnLTracker(data_dir=tempfile.mkdtemp())
    s = PolymarketCopyTrader(client, _settings(observer_only=observer_only), pnl)
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
        "id": "trade-001",
        "asset_id": "0xtokenid000000000001",
        "outcome": "Yes",
        "usdcSize": "5.00",
        "size": "10",
        "price": "0.45",
        "type": "BUY",
        "side": "BUY",
    }


def _position(position_id: str = "pos-001") -> CopiedPosition:
    return CopiedPosition(
        position_id=position_id,
        source_wallet="0xwallet" + "0" * 33,
        token_id="0xtokenid000000000004",
        market_question="Will exit happen?",
        condition_id="0xcond" + "0" * 59,
        side="BUY",
        entry_price=0.45,
        size_usd=5.0,
        size_shares=11.0,
        copied_at=time.time(),
        source_trade_id="src-exit-001",
        order_id="paper-pos-001",
        category="crypto",
        event_slug="will-exit-happen",
    )


# ── _copy_trade gate ──────────────────────────────────────────────────────────

class TestCopyTradeGate:

    def test_observer_on_logs_skip_not_attempt(self, capsys):
        """observer_only=True: logs observer_only_skip, NOT copytrade_copy_attempt."""
        strategy = _make_strategy(observer_only=True)

        result = _run(strategy._copy_trade(
            wallet=_wallet(),
            trade=_trade(),
            token_id="0xtokenid000000000001",
            price=0.45,
            market="test-market-slug",
            market_question="Will X happen?",
            source_trade_id="src-001",
        ))

        assert result is False
        out = capsys.readouterr().out
        assert "observer_only_skip" in out
        assert "copytrade_copy_attempt" not in out

    def test_observer_on_no_order_call(self):
        """observer_only=True: client.place_order never called."""
        strategy = _make_strategy(observer_only=True)
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(),
            token_id="0xtokenid000000000001", price=0.45,
            market="test-market-slug", market_question="Will X happen?",
            source_trade_id="src-001",
        ))
        strategy._client.place_order.assert_not_called()

    def test_observer_off_allows_attempt(self, capsys):
        """observer_only=False: copytrade_copy_attempt fires (gate is inactive)."""
        strategy = _make_strategy(observer_only=False)

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(),
            token_id="0xtokenid000000000001", price=0.45,
            market="test-market-slug", market_question="Will X happen?",
            source_trade_id="src-001",
        ))

        out = capsys.readouterr().out
        assert "observer_only_skip" not in out
        assert "copytrade_copy_attempt" in out


# ── whale signal gate ─────────────────────────────────────────────────────────

class TestWhaleSignalGate:

    def _make_signal(self, confidence: float = 80.0):
        sig = MagicMock()
        sig.confidence_score = confidence
        sig.signal_type = "whale"
        sig.wallet = "0xwhale" + "0" * 34
        sig.market_title = "Will Bitcoin hit $100k?"
        sig.condition_id = "0xcond" + "0" * 59
        sig.market_slug = "will-bitcoin-hit-100k"
        sig.trade_size = 500.0
        sig.details = {"trade_price": 0.45, "wallet_count": 1, "total_cluster_volume": 100.0}
        return sig

    def test_tier2_observer_skip(self, capsys):
        """observer_only=True: whale tier 2 logs observer_only_skip, no order."""
        strategy = _make_strategy(observer_only=True)
        # Fund bankroll to bypass circuit breaker (bankroll < 10 guard)
        strategy._bankroll = 500.0

        signal = self._make_signal(confidence=75.0)
        strategy._whale_scanner = MagicMock()
        strategy._whale_scanner.get_active_signals = MagicMock(return_value=[signal])

        # Mock HTTP so it doesn't call the network; use crypto market to pass tier-2 category filter
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=[{
            "clobTokenIds": ["0xtokenid000000000002"],
            "question": "Will Bitcoin hit $100k?",
            "slug": "will-bitcoin-hit-100k",
        }])
        strategy._http = AsyncMock()
        strategy._http.get = AsyncMock(return_value=mock_resp)
        strategy._clob_client = MagicMock()
        strategy._clob_client.create_and_post_order = MagicMock()

        _run(strategy._check_whale_signals())

        out = capsys.readouterr().out
        assert "observer_only_skip" in out
        strategy._clob_client.create_and_post_order.assert_not_called()

    def test_tier1_not_gated(self, capsys):
        """Tier 1 watch signals are not gated — they already place no orders."""
        strategy = _make_strategy(observer_only=True)
        signal = self._make_signal(confidence=55.0)  # tier 1
        strategy._whale_scanner = MagicMock()
        strategy._whale_scanner.get_active_signals = MagicMock(return_value=[signal])
        strategy._add_wallet_to_watchlist = MagicMock()

        _run(strategy._check_whale_signals())

        out = capsys.readouterr().out
        # Tier 1 logs whale_signal_tier1_watch, not observer_only_skip
        assert "whale_signal_tier1_watch" in out


# ── _execute_reentry gate ─────────────────────────────────────────────────────

class TestReentryGate:

    def test_observer_skip(self, capsys):
        """observer_only=True: reentry logs observer_only_skip, no order."""
        strategy = _make_strategy(observer_only=True)
        strategy._clob_client = MagicMock()
        strategy._clob_client.create_and_post_order = MagicMock()

        entry = {
            "market_question": "Will Z happen?",
            "token_id": "0xtokenid000000000003",
            "condition_id": "0xcond" + "0" * 59,
            "category": "crypto",
            "exit_price": 0.50,
            "original_entry": 0.40,
            "neg_risk": False,
            "source_wallet": "0xwallet" + "0" * 33,
            "event_slug": "will-z-happen",
        }

        _run(strategy._execute_reentry(entry, current_price=0.44))

        out = capsys.readouterr().out
        assert "observer_only_skip" in out
        assert "copytrade_reentry_attempt" not in out
        strategy._clob_client.create_and_post_order.assert_not_called()


# ── _exit_position gate ───────────────────────────────────────────────────────

class TestExitPositionGate:

    def test_observer_skip(self, capsys):
        """observer_only=True: exit_position logs observer_only_skip, no order."""
        strategy = _make_strategy(observer_only=True)
        strategy._clob_client = MagicMock()
        strategy._positions["pos-001"] = _position("pos-001")

        signal = ExitSignal(
            position_id="pos-001",
            reason="take_profit",
            current_price=0.65,
            entry_price=0.45,
            sell_fraction=1.0,
            pnl_pct=0.44,
            peak_price=0.66,
            hold_time_hours=2.0,
        )

        _run(strategy._exit_position("pos-001", signal))

        out = capsys.readouterr().out
        assert "observer_only_skip" in out
        strategy._clob_client.create_and_post_order.assert_not_called()


# ── get_status exposes observer_only ─────────────────────────────────────────

class TestObserverOnlyStatus:

    def test_status_true(self):
        assert _make_strategy(observer_only=True).get_status()["observer_only"] is True

    def test_status_false(self):
        assert _make_strategy(observer_only=False).get_status()["observer_only"] is False


# ── Settings reads POLY_OBSERVER_ONLY ─────────────────────────────────────────

class TestSettingsObserverOnly:

    def test_default_is_true(self):
        s = Settings(poly_private_key="a" * 64)
        assert s.observer_only is True

    def test_env_false(self, monkeypatch):
        monkeypatch.setenv("POLY_OBSERVER_ONLY", "false")
        s = Settings(poly_private_key="a" * 64)
        assert s.observer_only is False

    def test_env_true(self, monkeypatch):
        monkeypatch.setenv("POLY_OBSERVER_ONLY", "true")
        s = Settings(poly_private_key="a" * 64)
        assert s.observer_only is True
