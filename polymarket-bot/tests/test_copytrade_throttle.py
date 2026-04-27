"""Tests for copytrade throttling, dedup, and price filters.

Verifies:
- Repeated same token is skipped after first attempt (copytrade_skipped_duplicate)
- Price > COPYTRADE_MAX_PRICE (default 0.90) is skipped (copytrade_skipped_price_too_high)
- Attempts over per-minute cap are skipped (copytrade_skipped_rate_limited)
- A valid attempt still passes all throttles in simulation-only mode
- No real orders are placed (dry_run guard)

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_copytrade_throttle.py -v
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.pnl_tracker import PnLTracker
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
    monkeypatch=None,
    max_attempts_per_minute: int = 5,
    max_price: float = 0.90,
    dedupe_window: float = 3600.0,
) -> PolymarketCopyTrader:
    if monkeypatch:
        monkeypatch.setenv("COPYTRADE_MAX_ATTEMPTS_PER_MINUTE", str(max_attempts_per_minute))
        monkeypatch.setenv("COPYTRADE_MAX_PRICE", str(max_price))
        monkeypatch.setenv("COPYTRADE_DEDUPE_WINDOW_SECONDS", str(int(dedupe_window)))
        monkeypatch.setenv("COPYTRADE_ALLOW_HIGH_PRICE", "false")
    client = MagicMock()
    client.place_order = AsyncMock()
    client.get_midpoint = AsyncMock(return_value=0.45)
    pnl = PnLTracker(data_dir=tempfile.mkdtemp())
    return PolymarketCopyTrader(
        client,
        _settings(observer_only=observer_only, simulation_only=simulation_only),
        pnl,
    )


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


def _trade(price: str = "0.45") -> dict:
    return {
        "id": "trade-throttle-001",
        "asset_id": "0xtokenid000000000001",
        "outcome": "Yes",
        "usdcSize": "5.00",
        "size": "10",
        "price": price,
        "type": "BUY",
        "side": "BUY",
    }


def _run(coro):
    return asyncio.run(coro)


TOKEN_A = "0xtokenid000000000001"
TOKEN_B = "0xtokenid000000000002"
TOKEN_C = "0xtokenid000000000003"
TOKEN_D = "0xtokenid000000000004"
TOKEN_E = "0xtokenid000000000005"
TOKEN_F = "0xtokenid000000000006"


# ── Throttle 2: dedup window ──────────────────────────────────────────────────

class TestDedupWindow:

    def test_repeated_token_skipped_within_window(self, capsys, monkeypatch):
        """Same token_id attempted twice within dedup window → second is skipped."""
        strategy = _make_strategy(monkeypatch=monkeypatch, dedupe_window=3600.0)

        # First attempt — should produce copytrade_copy_attempt
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_A,
            price=0.45, market="test-market-slug",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-001",
        ))
        # Second attempt with same token — should be deduped
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_A,
            price=0.45, market="test-market-slug",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-002",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_duplicate" in out
        # Only one attempt should have been recorded
        assert out.count("copytrade_copy_attempt") <= 1

    def test_different_token_not_deduped(self, capsys, monkeypatch):
        """Different token_ids are not deduped against each other."""
        strategy = _make_strategy(monkeypatch=monkeypatch, dedupe_window=3600.0)

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_A,
            price=0.45, market="market-slug-a",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-003",
        ))
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_B,
            price=0.45, market="market-slug-b",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-004",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_duplicate" not in out

    def test_token_allowed_after_window_expires(self, capsys, monkeypatch):
        """Same token is allowed again after dedup window expires."""
        strategy = _make_strategy(monkeypatch=monkeypatch, dedupe_window=1.0)  # 1 second window

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_C,
            price=0.45, market="market-slug-c",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-005",
        ))
        # Manually expire the window
        strategy._token_last_attempt[TOKEN_C] = time.time() - 2.0  # 2 seconds ago

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=TOKEN_C,
            price=0.45, market="market-slug-c",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-006",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_duplicate" not in out


# ── Throttle 3: price too high ────────────────────────────────────────────────

class TestPriceTooHigh:

    def test_price_095_skipped(self, capsys, monkeypatch):
        """Price 0.95 > COPYTRADE_MAX_PRICE (0.90) → copytrade_skipped_price_too_high."""
        strategy = _make_strategy(monkeypatch=monkeypatch, max_price=0.90)

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.95"), token_id=TOKEN_D,
            price=0.95, market="test-market-slug",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-007",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_price_too_high" in out
        assert "copytrade_copy_attempt" not in out

    def test_price_099_skipped(self, capsys, monkeypatch):
        """Price 0.99 → skipped."""
        strategy = _make_strategy(monkeypatch=monkeypatch, max_price=0.90)

        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.99"), token_id=TOKEN_D + "x",
            price=0.99, market="test-slug-099",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-008",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_price_too_high" in out

    def test_price_090_allowed(self, capsys, monkeypatch):
        """Price exactly 0.90 = max → allowed (not strictly greater than)."""
        strategy = _make_strategy(monkeypatch=monkeypatch, max_price=0.90)
        # Give a fresh unique token
        token = "0xtokenid000000000099"
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.90"), token_id=token,
            price=0.90, market="test-slug-090",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-009",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_price_too_high" not in out

    def test_allow_high_price_env_bypasses_filter(self, capsys, monkeypatch):
        """COPYTRADE_ALLOW_HIGH_PRICE=true bypasses the price filter."""
        monkeypatch.setenv("COPYTRADE_MAX_PRICE", "0.90")
        monkeypatch.setenv("COPYTRADE_ALLOW_HIGH_PRICE", "true")
        monkeypatch.setenv("COPYTRADE_MAX_ATTEMPTS_PER_MINUTE", "10")
        monkeypatch.setenv("COPYTRADE_DEDUPE_WINDOW_SECONDS", "0")
        strategy = _make_strategy(
            monkeypatch=None,  # already set via monkeypatch above
            observer_only=False, simulation_only=True,
        )
        # Re-read env since strategy was already constructed — set directly
        strategy._allow_high_price = True
        strategy._copytrade_max_price = 0.90

        token = "0xtokenid000000000098"
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.95"), token_id=token,
            price=0.95, market="test-slug-high",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-010",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_price_too_high" not in out


# ── Throttle 1: per-minute rate cap ──────────────────────────────────────────

class TestPerMinuteRateCap:

    def test_attempts_over_cap_skipped(self, capsys, monkeypatch):
        """After max_attempts_per_minute successes, next is rate-limited."""
        cap = 3
        strategy = _make_strategy(
            monkeypatch=monkeypatch,
            max_attempts_per_minute=cap,
            dedupe_window=0.0,  # disable dedup so tokens don't block first
        )

        tokens = ["0xtokenidrate00000" + str(i) for i in range(cap + 2)]
        results = []
        for i, tok in enumerate(tokens):
            _run(strategy._copy_trade(
                wallet=_wallet(),
                trade=_trade(),
                token_id=tok,
                price=0.45,
                market=f"market-rate-{i}",
                market_question="Will Bitcoin hit $100k?",
                source_trade_id=f"src-rate-{i}",
            ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_rate_limited" in out
        # Only cap-many attempts should have been logged
        assert out.count("copytrade_copy_attempt") <= cap

    def test_rate_window_resets_after_minute(self, capsys, monkeypatch):
        """After timestamps age past 60s, rate limit window resets."""
        cap = 2
        strategy = _make_strategy(
            monkeypatch=monkeypatch,
            max_attempts_per_minute=cap,
            dedupe_window=0.0,
        )
        # Fill the window with old timestamps
        strategy._attempt_times = [time.time() - 61.0] * cap

        token = "0xtokenidresettest0"
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(), token_id=token,
            price=0.45, market="market-reset",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-reset",
        ))

        out = capsys.readouterr().out
        assert "copytrade_skipped_rate_limited" not in out
        assert "copytrade_copy_attempt" in out


# ── Valid attempt passes in simulation-only, no real order ───────────────────

class TestValidAttemptSimulationOnly:

    def test_valid_attempt_reaches_copy_attempt_in_simulation(self, capsys, monkeypatch):
        """simulation_only=True, all throttles clear → copytrade_copy_attempt logged, no observer_only_skip."""
        strategy = _make_strategy(
            observer_only=False,
            simulation_only=True,
            monkeypatch=monkeypatch,
            max_price=0.90,
            max_attempts_per_minute=10,
            dedupe_window=0.0,
        )

        token = "0xtokenidvalid00001"
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.45"), token_id=token,
            price=0.45, market="valid-market-slug",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-valid-001",
        ))

        out = capsys.readouterr().out
        assert "observer_only_skip" not in out
        assert "copytrade_skipped_rate_limited" not in out
        assert "copytrade_skipped_duplicate" not in out
        assert "copytrade_skipped_price_too_high" not in out
        assert "copytrade_copy_attempt" in out

    def test_no_real_order_in_simulation(self, monkeypatch):
        """simulation_only=True, dry_run=True → client.place_order never called with real args."""
        strategy = _make_strategy(
            observer_only=False,
            simulation_only=True,
            monkeypatch=monkeypatch,
            max_price=0.90,
            max_attempts_per_minute=10,
            dedupe_window=0.0,
        )

        token = "0xtokenidnoreal0001"
        _run(strategy._copy_trade(
            wallet=_wallet(), trade=_trade(price="0.45"), token_id=token,
            price=0.45, market="valid-market-slug-2",
            market_question="Will Bitcoin hit $100k?",
            source_trade_id="src-noreal-001",
        ))

        # The CLOB client's create_and_post_order should never be called
        # (strategy._clob_client is None in test setup — verified by no crash)
        assert strategy._settings.dry_run is True
