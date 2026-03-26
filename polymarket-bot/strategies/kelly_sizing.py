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


async def fetch_onchain_bankroll(wallet_address: str, rpc_url: str = None) -> float:
    """Fetch USDC.e balance from Polygon to use as real bankroll.

    Falls back to COPYTRADE_BANKROLL env var if on-chain check fails.
    """
    if not rpc_url:
        rpc_url = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

    usdc_e = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    try:
        import httpx
        data = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{
                "to": usdc_e,
                "data": f"0x70a08231000000000000000000000000{wallet_address[2:].lower()}"
            }, "latest"],
            "id": 1,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(rpc_url, json=data)
            result = resp.json().get("result", "0x0")
            balance_raw = int(result, 16)
            balance = balance_raw / 1e6
            logger.info("bankroll_onchain_fetched", balance=round(balance, 2), wallet=wallet_address[:12])
            return balance if balance > 0 else get_bankroll_from_env()
    except Exception as exc:
        logger.warning("bankroll_onchain_error", error=str(exc)[:80])
        return get_bankroll_from_env()
