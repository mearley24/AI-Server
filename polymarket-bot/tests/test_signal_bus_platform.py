"""Tests for signal bus platform-aware routing."""

from __future__ import annotations

import asyncio

import pytest

from src.signal_bus import Signal, SignalBus, SignalType


class TestSignalPlatformField:
    """Test Signal platform field and auto-detection."""

    def test_default_platform(self):
        sig = Signal(signal_type=SignalType.MARKET_DATA, source="test")
        assert sig.platform == "all"

    def test_explicit_platform(self):
        sig = Signal(signal_type=SignalType.MARKET_DATA, source="test", platform="kalshi")
        assert sig.platform == "kalshi"

    def test_platform_from_data(self):
        sig = Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="btc_correlation",
            data={"platform": "crypto", "symbol": "XRP/USD"},
        )
        assert sig.platform == "crypto"

    def test_explicit_platform_takes_precedence(self):
        sig = Signal(
            signal_type=SignalType.TRADE_PROPOSAL,
            source="test",
            platform="kalshi",
            data={"platform": "crypto"},
        )
        # explicit platform is "kalshi", should remain "kalshi"
        assert sig.platform == "kalshi"


class TestSignalBusPlatformSubscribe:
    """Test platform-filtered subscriptions."""

    @pytest.mark.asyncio
    async def test_platform_subscriber_receives_matching(self):
        bus = SignalBus()
        received = []

        async def on_signal(signal: Signal):
            received.append(signal)

        bus.subscribe_platform(SignalType.MARKET_DATA, "kalshi", on_signal)

        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA,
            source="kalshi_scanner",
            platform="kalshi",
            data={"ticker": "KXTEMP"},
        ))

        assert len(received) == 1
        assert received[0].platform == "kalshi"

    @pytest.mark.asyncio
    async def test_platform_subscriber_ignores_other(self):
        bus = SignalBus()
        received = []

        async def on_signal(signal: Signal):
            received.append(signal)

        bus.subscribe_platform(SignalType.MARKET_DATA, "kalshi", on_signal)

        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA,
            source="crypto_scan",
            platform="crypto",
        ))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_platform_subscriber_receives_broadcast(self):
        bus = SignalBus()
        received = []

        async def on_signal(signal: Signal):
            received.append(signal)

        bus.subscribe_platform(SignalType.MARKET_DATA, "kalshi", on_signal)

        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA,
            source="global",
            platform="all",
        ))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_wildcard_receives_all_platforms(self):
        bus = SignalBus()
        received = []

        async def on_signal(signal: Signal):
            received.append(signal)

        bus.subscribe_all(on_signal)

        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA, source="a", platform="kalshi",
        ))
        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA, source="b", platform="crypto",
        ))
        await bus.publish(Signal(
            signal_type=SignalType.MARKET_DATA, source="c", platform="polymarket",
        ))

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        bus = SignalBus()
        await bus.publish(Signal(signal_type=SignalType.MARKET_DATA, source="test"))
        await bus.publish(Signal(signal_type=SignalType.MARKET_DATA, source="test"))
        assert bus.stats["published"] == 2
