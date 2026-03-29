"""Whale Detector — flags large single trades and enriches with wallet history."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from src.whale_scanner.trade_monitor import ParsedTrade

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
WHALE_THRESHOLD_USD = 500  # min USDC for a trade to be "whale"
POSITIONS_URL = "https://data-api.polymarket.com/positions"
WALLET_CACHE_TTL = 300  # 5 minutes cache for wallet lookups


@dataclass
class WalletStats:
    """Cached stats for a wallet."""

    address: str
    total_positions: int = 0
    total_value: float = 0.0
    total_pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    earliest_position_ts: float = 0.0
    fetched_at: float = 0.0


@dataclass
class WhaleSignal:
    """Signal generated when a whale trade is detected."""

    signal_type: str = "whale"
    wallet: str = ""
    condition_id: str = ""
    market_title: str = ""
    market_slug: str = ""
    trade_size: float = 0.0
    trade_price: float = 0.0
    trade_side: str = ""
    wallet_total_value: float = 0.0
    wallet_pnl: float = 0.0
    wallet_win_rate: float = 0.0
    wallet_positions: int = 0
    confidence_score: float = 0.0
    timestamp: float = field(default_factory=time.time)
    trade_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "wallet": self.wallet,
            "condition_id": self.condition_id,
            "market_title": self.market_title,
            "market_slug": self.market_slug,
            "trade_size": self.trade_size,
            "trade_price": self.trade_price,
            "trade_side": self.trade_side,
            "wallet_total_value": self.wallet_total_value,
            "wallet_pnl": self.wallet_pnl,
            "wallet_win_rate": self.wallet_win_rate,
            "wallet_positions": self.wallet_positions,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp,
            "trade_id": self.trade_id,
        }


class WhaleDetector:
    """Detects large trades and enriches them with wallet history."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        threshold_usd: float = WHALE_THRESHOLD_USD,
    ) -> None:
        self._http = http
        self._threshold = threshold_usd
        self._wallet_cache: dict[str, WalletStats] = {}
        self._signals_generated: int = 0

    async def check_trades(self, trades: list[ParsedTrade]) -> list[WhaleSignal]:
        """Check a batch of trades for whale activity. Returns whale signals."""
        signals: list[WhaleSignal] = []

        for trade in trades:
            if trade.usdc_value < self._threshold:
                continue
            if trade.side != "BUY":
                continue

            # Fetch wallet stats (cached)
            stats = await self._get_wallet_stats(trade.wallet)

            # Compute confidence score
            confidence = self._compute_confidence(trade, stats)

            signal = WhaleSignal(
                wallet=trade.wallet,
                condition_id=trade.condition_id,
                market_title=trade.market_title,
                market_slug=trade.market_slug,
                trade_size=trade.usdc_value,
                trade_price=trade.price,
                trade_side=trade.side,
                wallet_total_value=stats.total_value,
                wallet_pnl=stats.total_pnl,
                wallet_win_rate=stats.win_rate,
                wallet_positions=stats.total_positions,
                confidence_score=confidence,
                timestamp=trade.timestamp,
                trade_id=trade.trade_id,
            )

            signals.append(signal)
            self._signals_generated += 1

            logger.info(
                "whale_detected",
                wallet=trade.wallet[:10] + "...",
                size=round(trade.usdc_value, 2),
                market=trade.market_title[:50],
                confidence=round(confidence, 1),
                wallet_positions=stats.total_positions,
                wallet_pnl=round(stats.total_pnl, 2),
            )

        return signals

    def get_wallet_stats(self, wallet: str) -> WalletStats | None:
        """Return cached wallet stats if available."""
        stats = self._wallet_cache.get(wallet.lower())
        if stats and time.time() - stats.fetched_at < WALLET_CACHE_TTL:
            return stats
        return None

    async def _get_wallet_stats(self, wallet: str) -> WalletStats:
        """Fetch and cache wallet position history."""
        wallet = wallet.lower()
        cached = self._wallet_cache.get(wallet)
        if cached and time.time() - cached.fetched_at < WALLET_CACHE_TTL:
            return cached

        stats = WalletStats(address=wallet, fetched_at=time.time())

        try:
            resp = await self._http.get(
                POSITIONS_URL,
                params={"user": wallet},
                timeout=15.0,
            )
            resp.raise_for_status()
            positions = resp.json()

            if not isinstance(positions, list):
                positions = []

            stats.total_positions = len(positions)

            for pos in positions:
                value = float(pos.get("currentValue", pos.get("value", 0)))
                pnl = float(pos.get("pnl", pos.get("realizedPnl", 0)))
                stats.total_value += value
                stats.total_pnl += pnl

                # Track wins/losses from resolved positions
                outcome = pos.get("outcome", "")
                if outcome == "won" or pnl > 0:
                    stats.wins += 1
                elif outcome == "lost" or (pnl < 0 and outcome):
                    stats.losses += 1

                # Track earliest position
                created = pos.get("createdAt", pos.get("timestamp", 0))
                if isinstance(created, str):
                    try:
                        from datetime import datetime
                        created = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        created = 0
                if created and (stats.earliest_position_ts == 0 or float(created) < stats.earliest_position_ts):
                    stats.earliest_position_ts = float(created)

            total_resolved = stats.wins + stats.losses
            stats.win_rate = stats.wins / total_resolved if total_resolved > 0 else 0.0

        except Exception as exc:
            logger.debug("whale_wallet_fetch_error", wallet=wallet[:10], error=str(exc)[:100])

        self._wallet_cache[wallet] = stats
        return stats

    def _compute_confidence(self, trade: ParsedTrade, stats: WalletStats) -> float:
        """Compute confidence score for a whale signal.

        Formula: base 50
            + min(trade_size/1000 * 10, 30)  — bigger trade = more confident
            + win_rate * 20 if positions > 5   — proven winner bonus
        """
        score = 50.0

        # Trade size component (cap at 30)
        size_bonus = min(trade.usdc_value / 1000 * 10, 30.0)
        score += size_bonus

        # Win rate component (only if wallet has history)
        if stats.total_positions > 5:
            score += stats.win_rate * 20.0

        return min(score, 100.0)

    @property
    def signals_generated(self) -> int:
        return self._signals_generated
