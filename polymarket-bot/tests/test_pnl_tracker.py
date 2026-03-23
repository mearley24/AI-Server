"""Tests for the P&L tracker."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest

from src.pnl_tracker import PnLTracker, Trade


@pytest.fixture
def tracker(tmp_path):
    return PnLTracker(data_dir=str(tmp_path))


@pytest.fixture
def sample_trades():
    now = time.time()
    return [
        Trade(
            trade_id="t1",
            timestamp=now - 3600,  # 1 hour ago
            market="Will Bitcoin go up in 5 minutes?",
            token_id="btc-yes-1",
            side="BUY",
            price=0.40,
            size=25.0,
            fee=0.01,
            strategy="stink_bid",
        ),
        Trade(
            trade_id="t2",
            timestamp=now - 1800,  # 30 min ago
            market="Will Bitcoin go up in 5 minutes?",
            token_id="btc-yes-1",
            side="SELL",
            price=0.52,
            size=25.0,
            fee=0.01,
            strategy="stink_bid",
        ),
        Trade(
            trade_id="t3",
            timestamp=now - 900,  # 15 min ago
            market="Will ETH go up in 5 minutes?",
            token_id="eth-yes-1",
            side="BUY",
            price=0.60,
            size=10.0,
            fee=0.005,
            strategy="flash_crash",
        ),
    ]


class TestPnLTracker:
    def test_record_trade(self, tracker):
        """Recording a trade adds it to the list."""
        trade = Trade(
            trade_id="t1",
            timestamp=time.time(),
            market="Test Market",
            token_id="tok-1",
            side="BUY",
            price=0.50,
            size=10.0,
            strategy="test",
        )
        tracker.record_trade(trade)
        assert len(tracker.trades) == 1
        assert tracker.trades[0].trade_id == "t1"

    def test_position_tracking_buy(self, tracker):
        """Buying creates an open position."""
        trade = Trade(
            trade_id="t1",
            timestamp=time.time(),
            market="Test Market",
            token_id="tok-1",
            side="BUY",
            price=0.40,
            size=20.0,
            strategy="stink_bid",
        )
        tracker.record_trade(trade)
        assert "tok-1" in tracker.open_positions
        pos = tracker.open_positions["tok-1"]
        assert pos["entry_price"] == 0.40
        assert pos["size"] == 20.0

    def test_position_tracking_sell(self, tracker):
        """Selling closes position and realizes P&L."""
        # Buy
        buy = Trade("t1", time.time(), "Market", "tok-1", "BUY", 0.40, 20.0, strategy="test")
        tracker.record_trade(buy)

        # Sell
        sell = Trade("t2", time.time(), "Market", "tok-1", "SELL", 0.55, 20.0, strategy="test")
        tracker.record_trade(sell)

        # Position should be closed
        assert "tok-1" not in tracker.open_positions
        assert sell.pnl == pytest.approx(0.15 * 20.0, abs=0.001)

    def test_partial_sell(self, tracker):
        """Partial sell reduces position size."""
        buy = Trade("t1", time.time(), "Market", "tok-1", "BUY", 0.40, 20.0, strategy="test")
        tracker.record_trade(buy)

        sell = Trade("t2", time.time(), "Market", "tok-1", "SELL", 0.55, 10.0, strategy="test")
        tracker.record_trade(sell)

        assert "tok-1" in tracker.open_positions
        assert tracker.open_positions["tok-1"]["size"] == pytest.approx(10.0, abs=0.001)

    def test_pnl_summary(self, tracker, sample_trades):
        """P&L summary calculates correctly."""
        for t in sample_trades:
            tracker.record_trade(t)

        summary = tracker.get_pnl()
        assert summary.trade_count == 3
        # BTC buy at 0.40, sell at 0.52 = +3.0 realized on 25 shares
        assert summary.total_realized == pytest.approx(3.0, abs=0.1)

    def test_pnl_filter_keyword(self, tracker, sample_trades):
        """P&L filters by keyword."""
        for t in sample_trades:
            tracker.record_trade(t)

        summary = tracker.get_pnl(keyword="bitcoin")
        assert summary.trade_count == 2  # Only BTC trades

    def test_pnl_filter_hours(self, tracker, sample_trades):
        """P&L filters by time window."""
        for t in sample_trades:
            tracker.record_trade(t)

        # Only trades from the last 20 minutes
        summary = tracker.get_pnl(hours=0.33)
        assert summary.trade_count == 1  # Only the ETH trade (15 min ago)

    def test_pnl_filter_strategy(self, tracker, sample_trades):
        """P&L filters by strategy."""
        for t in sample_trades:
            tracker.record_trade(t)

        summary = tracker.get_pnl(strategy="flash_crash")
        assert summary.trade_count == 1
        assert "flash_crash" in summary.by_strategy

    def test_persist_trade_csv(self, tracker, tmp_path):
        """Trades are persisted to CSV."""
        trade = Trade("t1", time.time(), "Market", "tok-1", "BUY", 0.50, 10.0, strategy="test")
        tracker.record_trade(trade)

        csv_path = tmp_path / "trades.csv"
        assert csv_path.exists()

        with csv_path.open() as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert len(rows) == 2  # header + 1 trade
            assert rows[0][0] == "trade_id"
            assert rows[1][0] == "t1"

    def test_load_csv(self, tracker, tmp_path):
        """Loading CSV imports trades."""
        csv_path = tmp_path / "import.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["trade_id", "timestamp", "market", "token_id", "side", "price", "size", "fee", "strategy", "pnl"])
            writer.writerow(["ext-1", "2026-03-23T10:00:00+00:00", "BTC 5m up", "tok-1", "BUY", "0.45", "15.0", "0.01", "manual", "0"])
            writer.writerow(["ext-2", "2026-03-23T10:05:00+00:00", "BTC 5m up", "tok-1", "SELL", "0.60", "15.0", "0.01", "manual", "2.25"])

        count = tracker.load_csv(csv_path)
        assert count == 2
        assert len(tracker.trades) == 2

    def test_load_csv_missing_file(self, tracker):
        """Loading a non-existent CSV returns 0."""
        count = tracker.load_csv("/nonexistent/path.csv")
        assert count == 0

    def test_win_rate(self, tracker):
        """Win rate calculation."""
        tracker.record_trade(Trade("t1", time.time(), "M", "tok-1", "BUY", 0.40, 10.0, strategy="test"))
        tracker.record_trade(Trade("t2", time.time(), "M", "tok-1", "SELL", 0.50, 10.0, strategy="test"))
        tracker.record_trade(Trade("t3", time.time(), "M", "tok-2", "BUY", 0.60, 10.0, strategy="test"))
        tracker.record_trade(Trade("t4", time.time(), "M", "tok-2", "SELL", 0.55, 10.0, strategy="test"))

        summary = tracker.get_pnl()
        assert summary.win_count == 1
        assert summary.loss_count == 1
        assert summary.win_rate == pytest.approx(0.5, abs=0.01)
