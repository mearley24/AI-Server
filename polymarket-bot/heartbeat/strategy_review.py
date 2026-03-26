"""Review copy-trader performance and open Polymarket positions."""

from __future__ import annotations

import os

import httpx
import structlog

logger = structlog.get_logger(__name__)

WALLET_ADDRESS = ""  # Set at runtime from POLY_PRIVATE_KEY


def _get_wallet_address() -> str:
    """Derive wallet address from private key."""
    global WALLET_ADDRESS
    if WALLET_ADDRESS:
        return WALLET_ADDRESS
    pk = os.environ.get("POLY_PRIVATE_KEY", "")
    if not pk:
        return ""
    try:
        from eth_account import Account
        if not pk.startswith("0x"):
            pk = f"0x{pk}"
        WALLET_ADDRESS = Account.from_key(pk).address
        return WALLET_ADDRESS
    except Exception:
        return ""


class StrategyReviewer:
    """Reviews copy-trader performance and open Polymarket positions."""

    async def review_all(self) -> list[dict]:
        """Fetch current positions and copy-trader status."""
        wallet = _get_wallet_address()
        if not wallet:
            return self._empty_reviews()

        reviews = []

        # Fetch Polymarket positions
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://data-api.polymarket.com/positions",
                    params={"user": wallet.lower()},
                )
                positions = resp.json()
        except Exception as exc:
            logger.error("heartbeat_positions_fetch_error", error=str(exc))
            positions = []

        # Categorize positions
        open_positions = []
        won_today = []
        lost_today = []

        for p in positions:
            cur_price = float(p.get("curPrice", 0))
            current_value = float(p.get("currentValue", 0))
            initial_value = float(p.get("initialValue", 0))

            if cur_price == 1.0 and current_value > 0:
                won_today.append(p)
            elif current_value == 0 and initial_value > 0:
                lost_today.append(p)
            elif cur_price > 0 and cur_price < 1.0 and current_value > 0:
                open_positions.append(p)

        total_open_value = sum(float(p.get("currentValue", 0)) for p in open_positions)
        total_won = sum(float(p.get("currentValue", 0)) for p in won_today)
        total_lost = sum(float(p.get("initialValue", 0)) for p in lost_today)

        # Build strategy-level metrics
        avg_trade_size = 0.0
        if open_positions:
            avg_trade_size = total_open_value / len(open_positions)

        total_resolved = len(won_today) + len(lost_today)
        realized_win_rate = len(won_today) / total_resolved if total_resolved > 0 else None

        reviews.append({
            "name": "copytrade",
            "platform": "polymarket",
            "signals": len(positions),
            "trades": total_resolved,
            "win_rate": f"{len(won_today)}W/{len(lost_today)}L" if total_resolved > 0 else "no resolved",
            "pnl": total_won - total_lost,
            "realized_pnl": round(total_won - total_lost, 2),
            "realized_win_rate": realized_win_rate,
            "status": "active" if open_positions else "idle",
            "open_positions": len(open_positions),
            "open_value": round(total_open_value, 2),
            "won_count": len(won_today),
            "won_value": round(total_won, 2),
            "lost_count": len(lost_today),
            "lost_value": round(total_lost, 2),
            "avg_trade_size": round(avg_trade_size, 2),
            "position_details": [
                {
                    "title": p.get("title", "")[:50],
                    "outcome": p.get("outcome", ""),
                    "value": round(float(p.get("currentValue", 0)), 2),
                    "entry": round(float(p.get("avgPrice", 0)), 2),
                    "current": round(float(p.get("curPrice", 0)), 2),
                }
                for p in open_positions[:10]
            ],
        })

        return reviews

    def _get_active_strategies(self) -> list[tuple[str, str]]:
        return [("copytrade", "polymarket")]

    def _empty_reviews(self) -> list[dict]:
        return [
            {
                "name": "copytrade",
                "platform": "polymarket",
                "signals": 0,
                "trades": 0,
                "win_rate": "no resolved",
                "pnl": 0.0,
                "realized_pnl": 0.0,
                "realized_win_rate": None,
                "status": "idle",
                "open_positions": 0,
                "open_value": 0.0,
                "won_count": 0,
                "won_value": 0.0,
                "lost_count": 0,
                "lost_value": 0.0,
                "avg_trade_size": 0.0,
            }
        ]
