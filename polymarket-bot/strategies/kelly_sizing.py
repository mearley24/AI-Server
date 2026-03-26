"""Kelly Criterion Position Sizing for Polymarket copy trades.

Uses quarter-Kelly for conservative sizing based on wallet win rate and market price.
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


class KellySizer:
    """Calculates position sizes using the Kelly Criterion."""

    def __init__(
        self,
        kelly_fraction: float = 0.25,  # quarter Kelly
        min_size_usd: float = 2.0,
        max_bankroll_pct: float = 0.05,  # 5% max per trade
        default_size_usd: float = 5.0,  # fallback
    ) -> None:
        self._kelly_fraction = kelly_fraction
        self._min_size = min_size_usd
        self._max_pct = max_bankroll_pct
        self._default_size = default_size_usd

    def calculate_position_size(
        self,
        wallet_win_rate: float,
        market_price: float,
        bankroll: float,
    ) -> float:
        """Calculate position size using Kelly Criterion for binary prediction markets.

        Args:
            wallet_win_rate: Estimated true probability (from source wallet's win rate)
            market_price: Current market price (0-1)
            bankroll: Available USDC balance

        Returns:
            Position size in USD, clamped to [min_size, max_bankroll_pct * bankroll]
        """
        if bankroll <= 0 or market_price <= 0 or market_price >= 1:
            return self._min_size

        p = wallet_win_rate  # estimated true probability of outcome
        q = 1 - p
        b = (1 / market_price) - 1  # payout odds (e.g., price 0.40 → odds 1.5)

        if b <= 0:
            return self._min_size

        # Kelly fraction: f* = (p*b - q) / b
        kelly = (p * b - q) / b

        if kelly <= 0:
            # Negative Kelly = negative expected value, use minimum
            logger.debug(
                "kelly_negative_ev",
                win_rate=round(wallet_win_rate, 3),
                price=round(market_price, 3),
                kelly=round(kelly, 4),
            )
            return self._min_size

        # Apply fractional Kelly for safety
        position = bankroll * kelly * self._kelly_fraction

        # Clamp to bounds
        max_size = bankroll * self._max_pct
        result = max(self._min_size, min(position, max_size))

        logger.debug(
            "kelly_size_calculated",
            win_rate=round(wallet_win_rate, 3),
            price=round(market_price, 3),
            kelly_raw=round(kelly, 4),
            quarter_kelly=round(kelly * self._kelly_fraction, 4),
            bankroll=round(bankroll, 2),
            position_usd=round(result, 2),
        )

        return round(result, 2)


def get_bankroll_from_env() -> float:
    """Get bankroll from environment variable, defaulting to a conservative amount."""
    return float(os.environ.get("COPYTRADE_BANKROLL", "300"))
