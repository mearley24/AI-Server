"""Execution sandbox — trade limits, rate limiter, kill switch, and approved actions.

Provides hard-coded safety ceilings that cannot be overridden by configuration
to prevent catastrophic losses or runaway spending.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Hard-coded absolute maximums (not overridable by config) ─────────────

ABSOLUTE_MAX_SINGLE_TRADE = 50_000.0  # $50K per trade, period
ABSOLUTE_MAX_DAILY_VOLUME = 500_000.0  # $500K daily volume ceiling
ABSOLUTE_MAX_DAILY_LOSS = 25_000.0  # $25K daily loss ceiling
ABSOLUTE_MAX_ORDERS_PER_MINUTE = 60  # burst cap

# Approved API endpoint prefixes — only these domains are allowed
APPROVED_ENDPOINTS = frozenset({
    "https://clob.polymarket.com",
    "https://gamma-api.polymarket.com",
    "wss://ws-subscriptions-clob.polymarket.com",
    "https://api.weather.gov",
    "http://dataservice.accuweather.com",
    "wss://stream.binance.com",
    "https://stream.binance.com",
})


class TokenBucket:
    """Token bucket rate limiter — allows bursts up to bucket size,
    refills at a steady rate."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate  # tokens per second
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Try to consume one token. Returns False if bucket is empty."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def available(self) -> float:
        return self._tokens


class ExecutionSandbox:
    """Enforces trading guardrails including rate limits, trade size caps,
    daily volume / loss limits, and a kill switch.

    Hard-coded absolute maximums cannot be raised by config — they serve
    as a safety net against misconfiguration.
    """

    def __init__(
        self,
        max_single_trade: float = 10_000.0,
        max_daily_volume: float = 50_000.0,
        max_daily_loss: float = 2_500.0,
        max_orders_per_minute: int = 10,
        max_api_calls_per_minute: int = 100,
        kill_switch_enabled: bool = True,
    ) -> None:
        # Clamp user config to absolute ceilings
        self._max_single_trade = min(max_single_trade, ABSOLUTE_MAX_SINGLE_TRADE)
        self._max_daily_volume = min(max_daily_volume, ABSOLUTE_MAX_DAILY_VOLUME)
        self._max_daily_loss = min(max_daily_loss, ABSOLUTE_MAX_DAILY_LOSS)
        self._kill_switch_enabled = kill_switch_enabled

        # Rate limiters (token bucket)
        clamped_opm = min(max_orders_per_minute, ABSOLUTE_MAX_ORDERS_PER_MINUTE)
        self._order_limiter = TokenBucket(rate=clamped_opm / 60.0, capacity=clamped_opm)
        self._api_limiter = TokenBucket(rate=max_api_calls_per_minute / 60.0, capacity=max_api_calls_per_minute)

        # Daily accumulators (reset at midnight UTC)
        self._daily_volume = 0.0
        self._daily_pnl = 0.0
        self._day_start = self._current_day()
        self._trade_count_today = 0

        # Kill switch state
        self._killed = False
        self._kill_reason = ""

        # Callbacks for kill switch activation
        self._kill_callbacks: list[Any] = []

        logger.info(
            "sandbox_initialized",
            max_single_trade=self._max_single_trade,
            max_daily_volume=self._max_daily_volume,
            max_daily_loss=self._max_daily_loss,
            kill_switch=self._kill_switch_enabled,
        )

    @staticmethod
    def _current_day() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters if a new UTC day has started."""
        today = self._current_day()
        if today != self._day_start:
            logger.info(
                "sandbox_daily_reset",
                prev_day=self._day_start,
                volume=round(self._daily_volume, 2),
                pnl=round(self._daily_pnl, 2),
                trades=self._trade_count_today,
            )
            self._daily_volume = 0.0
            self._daily_pnl = 0.0
            self._trade_count_today = 0
            self._day_start = today

            # Auto-revive kill switch on new day (unless manually killed)
            if self._killed and self._kill_reason.startswith("auto:"):
                self._killed = False
                self._kill_reason = ""
                logger.info("sandbox_kill_switch_auto_revived")

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    @property
    def daily_stats(self) -> dict[str, Any]:
        self._maybe_reset_daily()
        return {
            "daily_volume": round(self._daily_volume, 2),
            "daily_pnl": round(self._daily_pnl, 2),
            "trade_count": self._trade_count_today,
            "max_daily_volume": self._max_daily_volume,
            "max_daily_loss": self._max_daily_loss,
            "killed": self._killed,
            "kill_reason": self._kill_reason,
        }

    def on_kill(self, callback: Any) -> None:
        """Register a callback invoked when the kill switch activates.

        Callback signature: async def handler(reason: str) -> None
        """
        self._kill_callbacks.append(callback)

    async def _activate_kill_switch(self, reason: str) -> None:
        """Halt all trading and fire kill callbacks."""
        self._killed = True
        self._kill_reason = reason
        logger.critical("kill_switch_activated", reason=reason)

        for cb in self._kill_callbacks:
            try:
                await cb(reason)
            except Exception as exc:
                logger.error("kill_callback_error", error=str(exc))

    def manual_kill(self, reason: str = "manual") -> None:
        """Manually activate the kill switch (non-async)."""
        self._killed = True
        self._kill_reason = f"manual: {reason}"
        logger.critical("kill_switch_manual", reason=reason)

    def revive(self) -> None:
        """Manually deactivate the kill switch."""
        self._killed = False
        self._kill_reason = ""
        logger.info("kill_switch_revived")

    async def check_trade(self, size: float, price: float) -> tuple[bool, str]:
        """Validate a proposed trade against all guardrails.

        Returns (allowed, reason).  If allowed is False, the trade
        MUST NOT be placed.
        """
        self._maybe_reset_daily()

        # Kill switch
        if self._killed:
            return False, f"kill_switch_active: {self._kill_reason}"

        # Single trade size
        notional = size * price
        if notional > self._max_single_trade:
            if self._kill_switch_enabled:
                await self._activate_kill_switch(f"auto: single_trade_exceeded ({notional:.2f})")
            return False, f"single_trade_limit: {notional:.2f} > {self._max_single_trade:.2f}"

        # Daily volume
        if self._daily_volume + notional > self._max_daily_volume:
            if self._kill_switch_enabled:
                await self._activate_kill_switch(f"auto: daily_volume_exceeded ({self._daily_volume + notional:.2f})")
            return False, f"daily_volume_limit: {self._daily_volume + notional:.2f} > {self._max_daily_volume:.2f}"

        # Order rate limit
        allowed = await self._order_limiter.acquire()
        if not allowed:
            return False, "order_rate_limit"

        return True, "ok"

    async def check_api_call(self, url: str) -> tuple[bool, str]:
        """Validate an outbound API call against the approved list and rate limit."""
        # Check approved endpoints
        is_approved = any(url.startswith(ep) for ep in APPROVED_ENDPOINTS)
        if not is_approved:
            logger.warning("sandbox_unapproved_endpoint", url=url)
            return False, f"unapproved_endpoint: {url}"

        # API rate limit
        allowed = await self._api_limiter.acquire()
        if not allowed:
            return False, "api_rate_limit"

        return True, "ok"

    def record_trade(self, notional: float, pnl: float = 0.0) -> None:
        """Record a completed trade for daily tracking."""
        self._maybe_reset_daily()
        self._daily_volume += abs(notional)
        self._daily_pnl += pnl
        self._trade_count_today += 1

        # Check daily loss trigger
        if self._daily_pnl < -self._max_daily_loss and self._kill_switch_enabled:
            asyncio.ensure_future(
                self._activate_kill_switch(
                    f"auto: daily_loss_exceeded ({self._daily_pnl:.2f})"
                )
            )

    def record_pnl(self, pnl: float) -> None:
        """Record P&L from a settled position."""
        self._maybe_reset_daily()
        self._daily_pnl += pnl

        if self._daily_pnl < -self._max_daily_loss and self._kill_switch_enabled:
            asyncio.ensure_future(
                self._activate_kill_switch(
                    f"auto: daily_loss_exceeded ({self._daily_pnl:.2f})"
                )
            )

    def is_approved_endpoint(self, url: str) -> bool:
        """Check if a URL is in the approved endpoint list (sync version)."""
        return any(url.startswith(ep) for ep in APPROVED_ENDPOINTS)
