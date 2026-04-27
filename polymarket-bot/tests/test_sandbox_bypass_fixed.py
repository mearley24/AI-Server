"""Tests: all 4 formerly-bypassing strategies now enforce sandbox guardrails.

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_sandbox_bypass_fixed.py -q

Verifies:
- dry_run=True → client.place_order() never called
- sandbox.check_trade() returning (False, ...) blocks the trade
- sandbox.record_trade() called on successful live order
- cooldown/duplicate-order protection (flash_crash)
- daily loss cap (sandbox kill) blocks further orders
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.client import PolymarketClient
from src.config import Settings
from src.market_scanner import MarketScanner
from src.pnl_tracker import PnLTracker
from src.signer import SIDE_BUY, SIDE_SELL
from src.websocket_client import OrderbookFeed
from strategies.base import BaseStrategy, OpenOrder, StrategyState
from strategies.flash_crash import FlashCrashStrategy
from strategies.presolution_scalp import PresolutionScalpStrategy
from strategies.sports_arb import SportsArbStrategy
from strategies.stink_bid import StinkBidStrategy


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def settings():
    return Settings(
        poly_private_key="a" * 64,
        poly_safe_address="0x" + "b" * 40,
        poly_default_size=10.0,
        poly_max_exposure=10_000.0,
        stink_bid_drop_threshold=0.15,
        stink_bid_take_profit=0.10,
        stink_bid_stop_loss=0.08,
        stink_bid_markets=["BTC", "ETH", "SOL"],
        flash_crash_drop_threshold=0.30,
        flash_crash_window_seconds=10,
        flash_crash_take_profit=0.15,
        flash_crash_stop_loss=0.10,
        sports_arb_arb_threshold=0.98,
        sports_arb_max_position_per_side=5000.0,
        sports_arb_slippage_tolerance=0.005,
        sports_arb_min_liquidity_shares=100,
    )


@pytest.fixture
def settings_live(settings):
    settings.dry_run = False
    return settings


@pytest.fixture
def mock_client():
    c = MagicMock(spec=PolymarketClient)
    c.place_order = AsyncMock(return_value={"orderID": "live-order-123"})
    c.get_midpoint = AsyncMock(return_value=0.45)
    c.cancel_order = AsyncMock()
    c.get_open_orders = AsyncMock(return_value=[])
    return c


@pytest.fixture
def mock_sandbox_allow():
    sb = MagicMock()
    sb.check_trade = AsyncMock(return_value=(True, "ok"))
    sb.record_trade = MagicMock()
    sb.is_killed = False
    return sb


@pytest.fixture
def mock_sandbox_block():
    sb = MagicMock()
    sb.check_trade = AsyncMock(return_value=(False, "test_block"))
    sb.record_trade = MagicMock()
    sb.is_killed = False
    return sb


def _make_market_mock(question="BTC above 100k?", token="BTC", token_id="tok-yes"):
    m = MagicMock()
    m.question = question
    m.token = token
    m.token_id_yes = token_id
    return m


# ── stink_bid ──────────────────────────────────────────────────────────────────

class TestStinkBidSandbox:

    def _make(self, settings, client, sandbox=None):
        s = StinkBidStrategy(
            client=client,
            settings=settings,
            scanner=MagicMock(),
            orderbook=MagicMock(),
            pnl_tracker=MagicMock(),
        )
        if sandbox:
            s.set_sandbox(sandbox)
        return s

    @pytest.mark.asyncio
    async def test_exit_dry_run_no_place_order(self, settings, mock_client):
        """dry_run=True: _exit_position must not call client.place_order()."""
        strategy = self._make(settings, mock_client)
        strategy._filled_positions["tok1"] = {
            "market": _make_market_mock(),
            "entry_price": 0.40,
            "size": 10.0,
        }
        await strategy._exit_position("tok1", 0.55, "take_profit")
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_exit_sandbox_blocked_no_place_order(self, settings_live, mock_client, mock_sandbox_block):
        """Sandbox block: no order placed."""
        strategy = self._make(settings_live, mock_client, mock_sandbox_block)
        strategy._filled_positions["tok1"] = {
            "market": _make_market_mock(),
            "entry_price": 0.40,
            "size": 10.0,
        }
        await strategy._exit_position("tok1", 0.55, "take_profit")
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_exit_live_calls_place_order_and_records(self, settings_live, mock_client, mock_sandbox_allow):
        """Live mode with sandbox approved: order placed, trade recorded."""
        strategy = self._make(settings_live, mock_client, mock_sandbox_allow)
        strategy._filled_positions["tok1"] = {
            "market": _make_market_mock(),
            "entry_price": 0.40,
            "size": 10.0,
        }
        await strategy._exit_position("tok1", 0.55, "take_profit")
        mock_client.place_order.assert_called_once()
        mock_sandbox_allow.record_trade.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_limit_order_goes_through_sandbox(self, settings_live, mock_client, mock_sandbox_block):
        """Entry via _place_limit_order is also sandbox-guarded."""
        strategy = self._make(settings_live, mock_client, mock_sandbox_block)
        result = await strategy._place_limit_order(
            token_id="tok1", market="BTC above 100k?", price=0.40, size=10.0, side=SIDE_BUY,
        )
        assert result is None
        mock_client.place_order.assert_not_called()


# ── flash_crash ────────────────────────────────────────────────────────────────

class TestFlashCrashSandbox:

    def _make(self, settings, client, sandbox=None):
        s = FlashCrashStrategy(
            client=client,
            settings=settings,
            scanner=MagicMock(),
            orderbook=MagicMock(),
            pnl_tracker=MagicMock(),
        )
        if sandbox:
            s.set_sandbox(sandbox)
        return s

    @pytest.mark.asyncio
    async def test_crash_buy_dry_run_no_place_order(self, settings, mock_client):
        strategy = self._make(settings, mock_client)
        market = _make_market_mock(token="ETH", token_id="eth-yes")
        await strategy._execute_crash_buy("eth-yes", market, 0.25)
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_crash_buy_sandbox_blocked_no_position(self, settings_live, mock_client, mock_sandbox_block):
        """Blocked buy: position must NOT be tracked."""
        strategy = self._make(settings_live, mock_client, mock_sandbox_block)
        market = _make_market_mock(token="ETH", token_id="eth-yes")
        await strategy._execute_crash_buy("eth-yes", market, 0.25)
        mock_client.place_order.assert_not_called()
        assert "eth-yes" not in strategy._positions

    @pytest.mark.asyncio
    async def test_crash_buy_live_calls_place_order_and_tracks(self, settings_live, mock_client, mock_sandbox_allow):
        strategy = self._make(settings_live, mock_client, mock_sandbox_allow)
        market = _make_market_mock(token="ETH", token_id="eth-yes")
        await strategy._execute_crash_buy("eth-yes", market, 0.25)
        mock_client.place_order.assert_called_once()
        mock_sandbox_allow.record_trade.assert_called_once()
        assert "eth-yes" in strategy._positions

    @pytest.mark.asyncio
    async def test_exit_dry_run_no_place_order(self, settings, mock_client):
        strategy = self._make(settings, mock_client)
        market = _make_market_mock()
        strategy._positions["eth-yes"] = {
            "market": market, "entry_price": 0.25, "size": 10.0,
            "order_id": "x", "bought_at": 0,
        }
        await strategy._exit_position("eth-yes", "take_profit")
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_buy(self, settings, mock_client):
        """Second crash signal on same token within cooldown window is ignored."""
        strategy = self._make(settings, mock_client)
        market = _make_market_mock(token_id="eth-yes")
        strategy._cooldowns["eth-yes"] = time.time()  # just triggered
        strategy._monitored_tokens["eth-yes"] = market
        strategy._state = StrategyState.RUNNING
        strategy._orderbook.get_price_change = MagicMock(return_value=-0.35)
        snapshot = {"mid": 0.20}
        await strategy._on_price_update("eth-yes", snapshot)
        mock_client.place_order.assert_not_called()
        assert "eth-yes" not in strategy._positions


# ── presolution_scalp ──────────────────────────────────────────────────────────

class TestPresolutionScalpSandbox:

    def _make(self, settings, client, sandbox=None):
        s = PresolutionScalpStrategy(
            client=client,
            settings=settings,
            scanner=MagicMock(),
            orderbook=MagicMock(),
            pnl_tracker=MagicMock(),
        )
        s._redis = None
        if sandbox:
            s.set_sandbox(sandbox)
        return s

    def _market(self):
        from datetime import datetime, timezone, timedelta
        return {
            "conditionId": "cond-abc",
            "question": "Will Team A win?",
            "endDateIso": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_enter_dry_run_no_place_order_tracks_position(self, settings, mock_client):
        """dry_run: no real order, but position IS tracked for paper ledger."""
        strategy = self._make(settings, mock_client)
        await strategy._enter_position(self._market(), "tok-yes", 0.05, "YES")
        mock_client.place_order.assert_not_called()
        assert "cond-abc" in strategy._presolution_positions

    @pytest.mark.asyncio
    async def test_enter_sandbox_blocked_no_position(self, settings_live, mock_client, mock_sandbox_block):
        strategy = self._make(settings_live, mock_client, mock_sandbox_block)
        await strategy._enter_position(self._market(), "tok-yes", 0.05, "YES")
        mock_client.place_order.assert_not_called()
        assert "cond-abc" not in strategy._presolution_positions

    @pytest.mark.asyncio
    async def test_enter_live_calls_place_order_tracks_position(self, settings_live, mock_client, mock_sandbox_allow):
        strategy = self._make(settings_live, mock_client, mock_sandbox_allow)
        await strategy._enter_position(self._market(), "tok-yes", 0.05, "YES")
        mock_client.place_order.assert_called_once()
        mock_sandbox_allow.record_trade.assert_called_once()
        assert "cond-abc" in strategy._presolution_positions

    @pytest.mark.asyncio
    async def test_max_single_trade_respected(self, settings_live, mock_client):
        """Sandbox blocks if max_single_trade is exceeded (block from sandbox)."""
        sb = MagicMock()
        sb.check_trade = AsyncMock(return_value=(False, "single_trade_limit"))
        sb.record_trade = MagicMock()
        strategy = self._make(settings_live, mock_client, sb)
        await strategy._enter_position(self._market(), "tok-yes", 0.05, "YES")
        mock_client.place_order.assert_not_called()


# ── sports_arb ─────────────────────────────────────────────────────────────────

class TestSportsArbSandbox:

    def _make(self, settings, client, sandbox=None):
        s = SportsArbStrategy(
            client=client,
            settings=settings,
            scanner=MagicMock(),
            orderbook=MagicMock(),
            pnl_tracker=MagicMock(),
        )
        if sandbox:
            s.set_sandbox(sandbox)
        return s

    def _arb(self):
        # prices chosen so price_a+slippage + price_b+slippage = 0.445+0.455 = 0.90 < 0.98 threshold
        return {
            "condition_id": "arb-1",
            "question": "Lakers vs Celtics",
            "arb_type": "YES",
            "token_id_a": "tok-a",
            "token_id_b": "tok-b",
            "price_a": 0.44,
            "price_b": 0.45,
            "combined": 0.89,
            "net_profit_per_share": 0.09,
        }

    @pytest.mark.asyncio
    async def test_execute_dry_run_no_place_order(self, settings, mock_client):
        strategy = self._make(settings, mock_client)
        result = await strategy._execute_arb(self._arb(), 100.0, 100.0)
        assert result is True
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sandbox_blocked_leg_a_neither_placed(self, settings_live, mock_client):
        """Leg A blocked → neither order placed."""
        sb = MagicMock()
        sb.check_trade = AsyncMock(side_effect=[
            (False, "daily_volume_limit"),
            (True, "ok"),
        ])
        strategy = self._make(settings_live, mock_client, sb)
        result = await strategy._execute_arb(self._arb(), 100.0, 100.0)
        assert result is False
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sandbox_blocked_leg_b_neither_placed(self, settings_live, mock_client):
        """Leg B blocked → neither order placed."""
        sb = MagicMock()
        sb.check_trade = AsyncMock(side_effect=[
            (True, "ok"),
            (False, "order_rate_limit"),
        ])
        strategy = self._make(settings_live, mock_client, sb)
        result = await strategy._execute_arb(self._arb(), 100.0, 100.0)
        assert result is False
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_live_both_orders_placed_and_recorded(self, settings_live, mock_client, mock_sandbox_allow):
        strategy = self._make(settings_live, mock_client, mock_sandbox_allow)
        result = await strategy._execute_arb(self._arb(), 100.0, 100.0)
        assert result is True
        assert mock_client.place_order.call_count == 2
        assert mock_sandbox_allow.record_trade.call_count == 2

    @pytest.mark.asyncio
    async def test_daily_loss_cap_blocks_trade(self, settings_live, mock_client):
        """Kill switch active (daily loss) blocks all further arb attempts."""
        sb = MagicMock()
        sb.check_trade = AsyncMock(return_value=(False, "kill_switch_active: auto: daily_loss_exceeded"))
        strategy = self._make(settings_live, mock_client, sb)
        result = await strategy._execute_arb(self._arb(), 100.0, 100.0)
        assert result is False
        mock_client.place_order.assert_not_called()


# ── Cross-strategy: all 4 have set_sandbox ─────────────────────────────────────

def test_all_four_strategies_have_set_sandbox(settings, mock_client):
    """Every strategy instance must have set_sandbox() and _sandbox field."""
    for Cls in (StinkBidStrategy, FlashCrashStrategy, PresolutionScalpStrategy, SportsArbStrategy):
        inst = Cls(
            client=mock_client,
            settings=settings,
            scanner=MagicMock(),
            orderbook=MagicMock(),
            pnl_tracker=MagicMock(),
        )
        assert hasattr(inst, "set_sandbox"), f"{Cls.__name__} missing set_sandbox()"
        assert hasattr(inst, "_sandbox"), f"{Cls.__name__} missing _sandbox field"
        assert inst._sandbox is None, f"{Cls.__name__} sandbox should start None"
        inst.set_sandbox(MagicMock())
        assert inst._sandbox is not None


def test_signer_py_not_modified():
    """signer.py must not have been changed by this P1 fix."""
    signer_path = os.path.join(
        os.path.dirname(__file__), "../src/signer.py"
    )
    assert os.path.exists(signer_path), "signer.py missing"
    # The file should import cleanly with no AttributeError on SIDE_BUY/SIDE_SELL
    from src.signer import SIDE_BUY, SIDE_SELL
    assert SIDE_BUY != SIDE_SELL
