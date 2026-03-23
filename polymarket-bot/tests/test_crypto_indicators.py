"""Tests for pure-Python technical indicator implementations in crypto strategies."""

from __future__ import annotations

import math

import pytest

import importlib
import importlib.util
import os
import sys
import types

# Import crypto strategy modules directly to avoid strategies/__init__.py
# which imports BaseStrategy → client → signer (requires web3/eth-account)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(name: str, filepath: str):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mr = _load_module("_mean_reversion", os.path.join(_root, "strategies", "crypto", "mean_reversion.py"))
_mm = _load_module("_momentum", os.path.join(_root, "strategies", "crypto", "momentum.py"))

_compute_bollinger = _mr._compute_bollinger
_compute_rsi = _mr._compute_rsi
_atr = _mm._atr
_ema = _mm._ema
_macd = _mm._macd


class TestEMA:
    def test_simple_ema(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _ema(data, 3)
        assert len(result) > 0
        # First value is SMA of first 3 elements
        assert result[0] == pytest.approx(2.0, abs=0.01)

    def test_insufficient_data(self):
        assert _ema([1.0, 2.0], 5) == []

    def test_ema_tracks_price(self):
        # EMA should trend upward for rising prices
        data = list(range(1, 21))  # 1..20
        result = _ema([float(x) for x in data], 5)
        assert result[-1] > result[0]


class TestMACD:
    def test_returns_none_for_short_data(self):
        assert _macd([1.0] * 10) is None

    def test_macd_structure(self):
        # Generate enough data (need 26 + 9 = 35 minimum)
        import random
        random.seed(42)
        data = [100.0 + random.uniform(-2, 2) for _ in range(100)]
        result = _macd(data)
        assert result is not None
        assert "macd" in result
        assert "signal" in result
        assert "histogram" in result
        assert "prev_histogram" in result

    def test_macd_histogram_is_difference(self):
        import random
        random.seed(42)
        data = [100.0 + random.uniform(-2, 2) for _ in range(100)]
        result = _macd(data)
        assert result is not None
        assert result["histogram"] == pytest.approx(
            result["macd"] - result["signal"], abs=1e-10
        )


class TestATR:
    def test_returns_none_for_short_data(self):
        assert _atr([1.0] * 5, [0.5] * 5, [0.8] * 5, period=14) is None

    def test_atr_positive(self):
        import random
        random.seed(42)
        n = 30
        closes = [100.0 + random.uniform(-3, 3) for _ in range(n)]
        highs = [c + random.uniform(0, 2) for c in closes]
        lows = [c - random.uniform(0, 2) for c in closes]
        result = _atr(highs, lows, closes, period=14)
        assert result is not None
        assert result > 0

    def test_atr_zero_range(self):
        # All prices identical → ATR should be 0
        n = 20
        closes = [50.0] * n
        highs = [50.0] * n
        lows = [50.0] * n
        result = _atr(highs, lows, closes, period=14)
        assert result is not None
        assert result == pytest.approx(0.0, abs=1e-10)


class TestBollingerBands:
    def test_returns_none_for_short_data(self):
        assert _compute_bollinger([1.0, 2.0], period=20) is None

    def test_bollinger_structure(self):
        data = [100.0 + i * 0.1 for i in range(30)]
        result = _compute_bollinger(data, period=20, num_std=2.0)
        assert result is not None
        assert "middle" in result
        assert "upper" in result
        assert "lower" in result
        assert "std" in result

    def test_bollinger_symmetry(self):
        data = [100.0 + i * 0.1 for i in range(30)]
        result = _compute_bollinger(data, period=20, num_std=2.0)
        assert result is not None
        # Upper and lower should be symmetric around middle
        assert (result["upper"] - result["middle"]) == pytest.approx(
            result["middle"] - result["lower"], abs=1e-10
        )

    def test_bollinger_upper_above_lower(self):
        import random
        random.seed(42)
        data = [100.0 + random.uniform(-5, 5) for _ in range(30)]
        result = _compute_bollinger(data, period=20, num_std=2.0)
        assert result is not None
        assert result["upper"] > result["lower"]


class TestRSI:
    def test_returns_none_for_short_data(self):
        assert _compute_rsi([1.0, 2.0], period=14) is None

    def test_rsi_in_range(self):
        import random
        random.seed(42)
        data = [100.0 + random.uniform(-5, 5) for _ in range(30)]
        result = _compute_rsi(data, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_rsi_all_gains(self):
        # Monotonically increasing → RSI = 100
        data = [float(i) for i in range(20)]
        result = _compute_rsi(data, period=14)
        assert result is not None
        assert result == 100.0

    def test_rsi_all_losses(self):
        # Monotonically decreasing → RSI = 0
        data = [float(20 - i) for i in range(20)]
        result = _compute_rsi(data, period=14)
        assert result is not None
        assert result == 0.0
