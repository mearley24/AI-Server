"""Fresh Wallet Detector — identifies insider patterns (new wallet, big bet, focused)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.whale_scanner.whale_detector import WhaleDetector, WhaleSignal, WalletStats

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
MAX_POSITIONS_FRESH = 10  # wallet must have fewer than this many positions
MAX_WALLET_AGE_DAYS = 7  # wallet's earliest position must be < this many days old
SINGLE_MARKET_FOCUS_PCT = 0.80  # >80% of value in one market = focused
HIGH_CONFIDENCE_MIN_TRADE = 1000  # min trade size for HIGH confidence insider
INSIDER_MIN_TRADE = 500  # min trade size to flag at all


@dataclass
class InsiderSignal:
    """Signal generated when a fresh wallet insider pattern is detected."""

    signal_type: str = "insider"
    wallet: str = ""
    condition_id: str = ""
    market_title: str = ""
    market_slug: str = ""
    trade_size: float = 0.0
    trade_price: float = 0.0
    wallet_age_days: float = 0.0
    position_count: int = 0
    is_single_market_focus: bool = False
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
            "wallet_age_days": self.wallet_age_days,
            "position_count": self.position_count,
            "is_single_market_focus": self.is_single_market_focus,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp,
            "trade_id": self.trade_id,
        }


class FreshWalletDetector:
    """Detects fresh wallet insider patterns from whale signals."""

    def __init__(self, whale_detector: WhaleDetector) -> None:
        self._whale_detector = whale_detector
        self._signals_generated: int = 0

    def check_whale_signals(self, whale_signals: list[WhaleSignal]) -> list[InsiderSignal]:
        """Check whale signals for fresh wallet insider patterns."""
        signals: list[InsiderSignal] = []

        for ws in whale_signals:
            if ws.trade_size < INSIDER_MIN_TRADE:
                continue

            # Get cached wallet stats from whale detector
            stats = self._whale_detector.get_wallet_stats(ws.wallet)
            if stats is None:
                continue

            # Fresh wallet criteria: < 10 positions AND < 7 days old
            if stats.total_positions >= MAX_POSITIONS_FRESH:
                continue

            wallet_age_days = self._compute_wallet_age(stats)
            if wallet_age_days >= MAX_WALLET_AGE_DAYS:
                continue

            # Check single market focus
            is_focused = self._check_single_market_focus(stats, ws)

            # Compute confidence
            confidence = self._compute_insider_confidence(ws, stats, wallet_age_days, is_focused)

            signal = InsiderSignal(
                wallet=ws.wallet,
                condition_id=ws.condition_id,
                market_title=ws.market_title,
                market_slug=ws.market_slug,
                trade_size=ws.trade_size,
                trade_price=ws.trade_price,
                wallet_age_days=round(wallet_age_days, 1),
                position_count=stats.total_positions,
                is_single_market_focus=is_focused,
                confidence_score=confidence,
                timestamp=ws.timestamp,
                trade_id=ws.trade_id,
            )

            signals.append(signal)
            self._signals_generated += 1

            logger.info(
                "insider_pattern_detected",
                wallet=ws.wallet[:10] + "...",
                size=round(ws.trade_size, 2),
                market=ws.market_title[:50],
                age_days=round(wallet_age_days, 1),
                positions=stats.total_positions,
                focused=is_focused,
                confidence=round(confidence, 1),
            )

        return signals

    def _compute_wallet_age(self, stats: WalletStats) -> float:
        """Compute wallet age in days from earliest position."""
        if stats.earliest_position_ts <= 0:
            return 0.0
        return (time.time() - stats.earliest_position_ts) / 86400

    def _check_single_market_focus(self, stats: WalletStats, whale_signal: WhaleSignal) -> bool:
        """Check if >80% of wallet value is in one market.

        Since we only have aggregate stats, we approximate by checking if
        the whale trade is the dominant position (trade_size > 80% of total_value).
        """
        if stats.total_value <= 0:
            return stats.total_positions <= 2

        return whale_signal.trade_size / max(stats.total_value, 1) >= SINGLE_MARKET_FOCUS_PCT

    def _compute_insider_confidence(
        self,
        ws: WhaleSignal,
        stats: WalletStats,
        age_days: float,
        is_focused: bool,
    ) -> float:
        """Compute insider confidence score.

        HIGH (90+): single market focus AND age < 7 days AND trade > $1000
        MEDIUM (70-89): meets fresh wallet criteria + large trade
        LOW (50-69): meets basic criteria
        """
        score = 50.0

        # Trade size bonus
        if ws.trade_size >= HIGH_CONFIDENCE_MIN_TRADE:
            score += 20.0
        elif ws.trade_size >= 500:
            score += 10.0

        # Freshness bonus (newer = more suspicious)
        if age_days < 1:
            score += 15.0
        elif age_days < 3:
            score += 10.0
        elif age_days < 7:
            score += 5.0

        # Focus bonus
        if is_focused:
            score += 10.0

        # Very few positions = more suspicious
        if stats.total_positions <= 2:
            score += 5.0

        # HIGH confidence insider: all three criteria met
        if is_focused and age_days < MAX_WALLET_AGE_DAYS and ws.trade_size >= HIGH_CONFIDENCE_MIN_TRADE:
            score = max(score, 90.0)

        return min(score, 100.0)

    @property
    def signals_generated(self) -> int:
        return self._signals_generated
