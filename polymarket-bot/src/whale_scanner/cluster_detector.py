"""Cluster Detector — finds coordinated multi-wallet entries into the same market."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.whale_scanner.trade_monitor import ParsedTrade

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
CLUSTER_MIN_WALLETS = 3  # min different wallets to trigger
CLUSTER_MIN_TRADE_USD = 100  # each wallet's entry must be > this
CLUSTER_WINDOW_SECONDS = 7200  # 2-hour window for cluster detection


@dataclass
class MarketEntry:
    """A single wallet's entry into a market for cluster tracking."""

    wallet: str
    usdc_value: float
    price: float
    timestamp: float
    trade_id: str


@dataclass
class ClusterSignal:
    """Signal generated when coordinated entry is detected."""

    signal_type: str = "cluster"
    condition_id: str = ""
    market_title: str = ""
    market_slug: str = ""
    wallets_involved: list[str] = field(default_factory=list)
    total_cluster_volume: float = 0.0
    time_span_minutes: float = 0.0
    avg_entry_price: float = 0.0
    confidence_score: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "condition_id": self.condition_id,
            "market_title": self.market_title,
            "market_slug": self.market_slug,
            "wallets_involved": self.wallets_involved,
            "wallet_count": len(self.wallets_involved),
            "total_cluster_volume": self.total_cluster_volume,
            "time_span_minutes": self.time_span_minutes,
            "avg_entry_price": self.avg_entry_price,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp,
        }


class ClusterDetector:
    """Detects coordinated entries: 3+ wallets entering the same market within 2 hours."""

    def __init__(self) -> None:
        # market (condition_id) -> list of entries
        self._market_entries: dict[str, list[MarketEntry]] = defaultdict(list)
        # Track which clusters we've already signaled to avoid duplicates
        self._signaled_clusters: set[str] = set()
        self._signals_generated: int = 0

    def ingest_trades(self, trades: list[ParsedTrade]) -> list[ClusterSignal]:
        """Ingest new trades and check for cluster patterns."""
        now = time.time()

        # Add qualifying trades to market entries
        for trade in trades:
            if trade.side != "BUY":
                continue
            if trade.usdc_value < CLUSTER_MIN_TRADE_USD:
                continue
            if not trade.condition_id:
                continue

            entry = MarketEntry(
                wallet=trade.wallet,
                usdc_value=trade.usdc_value,
                price=trade.price,
                timestamp=trade.timestamp,
                trade_id=trade.trade_id,
            )
            self._market_entries[trade.condition_id].append(entry)

        # Trim old entries and check for clusters
        signals: list[ClusterSignal] = []
        cutoff = now - CLUSTER_WINDOW_SECONDS

        for condition_id in list(self._market_entries.keys()):
            entries = self._market_entries[condition_id]

            # Remove old entries
            entries[:] = [e for e in entries if e.timestamp >= cutoff]
            if not entries:
                del self._market_entries[condition_id]
                continue

            # Check for cluster: 3+ different wallets
            wallet_entries: dict[str, MarketEntry] = {}
            for entry in entries:
                # Keep the largest entry per wallet
                existing = wallet_entries.get(entry.wallet)
                if existing is None or entry.usdc_value > existing.usdc_value:
                    wallet_entries[entry.wallet] = entry

            if len(wallet_entries) < CLUSTER_MIN_WALLETS:
                continue

            # Build cluster key for dedup
            sorted_wallets = sorted(wallet_entries.keys())
            cluster_key = f"{condition_id}:{':'.join(sorted_wallets)}"
            if cluster_key in self._signaled_clusters:
                continue

            self._signaled_clusters.add(cluster_key)

            # Build signal
            all_entries = list(wallet_entries.values())
            total_volume = sum(e.usdc_value for e in all_entries)
            timestamps = [e.timestamp for e in all_entries]
            time_span = (max(timestamps) - min(timestamps)) / 60  # minutes
            avg_price = sum(e.price for e in all_entries) / len(all_entries)

            # Get market title from the most recent trade
            market_title = ""
            market_slug = ""
            for trade in trades:
                if trade.condition_id == condition_id:
                    market_title = trade.market_title
                    market_slug = trade.market_slug
                    break

            confidence = self._compute_cluster_confidence(
                wallet_count=len(wallet_entries),
                total_volume=total_volume,
                time_span_minutes=time_span,
            )

            signal = ClusterSignal(
                condition_id=condition_id,
                market_title=market_title,
                market_slug=market_slug,
                wallets_involved=sorted_wallets,
                total_cluster_volume=round(total_volume, 2),
                time_span_minutes=round(time_span, 1),
                avg_entry_price=round(avg_price, 4),
                confidence_score=confidence,
                timestamp=now,
            )

            signals.append(signal)
            self._signals_generated += 1

            logger.info(
                "cluster_detected",
                market=market_title[:50],
                wallets=len(wallet_entries),
                volume=round(total_volume, 2),
                time_span_min=round(time_span, 1),
                confidence=round(confidence, 1),
            )

        # Periodically clean up old signaled clusters
        if len(self._signaled_clusters) > 1000:
            self._signaled_clusters.clear()

        return signals

    def _compute_cluster_confidence(
        self,
        wallet_count: int,
        total_volume: float,
        time_span_minutes: float,
    ) -> float:
        """Compute cluster confidence.

        More wallets, more volume, tighter time window = higher confidence.
        """
        score = 50.0

        # Wallet count bonus
        if wallet_count >= 6:
            score += 25.0
        elif wallet_count >= 4:
            score += 15.0
        else:
            score += 5.0

        # Volume bonus
        if total_volume >= 5000:
            score += 15.0
        elif total_volume >= 1000:
            score += 10.0
        elif total_volume >= 500:
            score += 5.0

        # Tighter time window = more coordinated = higher confidence
        if time_span_minutes <= 15:
            score += 10.0
        elif time_span_minutes <= 30:
            score += 5.0

        return min(score, 100.0)

    @property
    def signals_generated(self) -> int:
        return self._signals_generated
