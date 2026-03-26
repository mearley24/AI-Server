"""Correlation Exposure Tracker — Category-based position limits.

Tags positions by market category from Gamma API and enforces per-category
exposure limits to prevent correlated losses.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# Keyword-based category detection
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "politics": [
        "president", "election", "congress", "senate", "governor", "trump",
        "biden", "democrat", "republican", "vote", "gop", "dnc", "rnc",
        "cabinet", "supreme court", "impeach", "poll", "primary", "nominee",
        "inauguration", "white house", "presidential",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
        "blockchain", "token", "coin", "defi", "nft", "altcoin", "binance",
        "coinbase", "halvening", "halving", "memecoin", "up or down",
    ],
    "sports": [
        "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
        "baseball", "hockey", "tennis", "golf", "ufc", "mma", "boxing",
        "world cup", "championship", "playoff", "super bowl", "mvp",
        "game", "match", "series", "finals",
    ],
    "weather": [
        "temperature", "weather", "rain", "snow", "hurricane", "tornado",
        "heat", "cold", "celsius", "fahrenheit", "noaa", "forecast",
    ],
    "economics": [
        "fed", "interest rate", "inflation", "gdp", "unemployment", "cpi",
        "recession", "treasury", "yield", "fomc", "jobs report", "tariff",
        "trade war", "debt ceiling", "federal reserve",
    ],
    "geopolitics": [
        "war", "conflict", "nato", "china", "russia", "iran", "israel",
        "ukraine", "missile", "sanctions", "nuclear", "ceasefire", "invasion",
        "military", "peace", "gaza", "hamas",
    ],
    "entertainment": [
        "oscar", "grammy", "emmy", "movie", "film", "album", "celebrity",
        "twitter", "x.com", "tiktok", "youtube", "viral", "reality tv",
    ],
    "science": [
        "nasa", "space", "mars", "moon", "asteroid", "ai", "artificial intelligence",
        "chatgpt", "openai", "google", "apple", "tech",
    ],
}


def categorize_market(question: str, tags: list[str] | None = None) -> str:
    """Categorize a market based on its question text and optional tags.

    Returns the best-matching category or 'other' if no strong match.
    """
    if not question:
        return "other"

    q_lower = question.lower()

    # Check tags first if provided
    if tags:
        for tag in tags:
            tag_lower = tag.lower()
            for category, keywords in CATEGORY_KEYWORDS.items():
                if tag_lower in keywords or tag_lower == category:
                    return category

    # Keyword matching with score
    scores: dict[str, int] = defaultdict(int)
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                scores[category] += 1

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] >= 1:
            return best

    return "other"


class CorrelationTracker:
    """Tracks category-based exposure and enforces per-category limits."""

    def __init__(
        self,
        max_category_pct: float = 0.15,  # 15% of bankroll per category
        bankroll: float = 300.0,
    ) -> None:
        self._max_pct = max_category_pct
        self._bankroll = bankroll

        # Track positions: position_id -> (category, size_usd)
        self._positions: dict[str, tuple[str, float]] = {}

    @property
    def bankroll(self) -> float:
        return self._bankroll

    @bankroll.setter
    def bankroll(self, value: float) -> None:
        self._bankroll = value

    def add_position(
        self,
        position_id: str,
        market_question: str,
        size_usd: float,
        tags: list[str] | None = None,
    ) -> str:
        """Register a position and return its category."""
        category = categorize_market(market_question, tags)
        self._positions[position_id] = (category, size_usd)
        return category

    def remove_position(self, position_id: str) -> None:
        """Remove a position from tracking."""
        self._positions.pop(position_id, None)

    def would_exceed_limit(
        self,
        market_question: str,
        size_usd: float,
        tags: list[str] | None = None,
    ) -> tuple[bool, str, float]:
        """Check if adding a trade would exceed the category limit.

        Returns:
            (would_exceed, category, current_exposure)
        """
        category = categorize_market(market_question, tags)
        current = self.get_category_exposure(category)
        limit = self._bankroll * self._max_pct

        would_exceed = (current + size_usd) > limit
        return would_exceed, category, current

    def get_category_exposure(self, category: str) -> float:
        """Get total exposure in a category."""
        return sum(
            size for cat, size in self._positions.values()
            if cat == category
        )

    def get_all_exposures(self) -> dict[str, float]:
        """Get exposure breakdown by category."""
        exposures: dict[str, float] = defaultdict(float)
        for cat, size in self._positions.values():
            exposures[cat] += size
        return dict(exposures)

    def get_category_limit(self) -> float:
        """Get the per-category USD limit."""
        return self._bankroll * self._max_pct

    def get_summary(self) -> dict[str, Any]:
        """Get a summary for heartbeat reporting."""
        exposures = self.get_all_exposures()
        limit = self.get_category_limit()
        return {
            "bankroll": round(self._bankroll, 2),
            "category_limit_pct": self._max_pct,
            "category_limit_usd": round(limit, 2),
            "total_positions": len(self._positions),
            "categories": {
                cat: {
                    "exposure_usd": round(exp, 2),
                    "pct_of_limit": round(exp / limit * 100, 1) if limit > 0 else 0,
                }
                for cat, exp in sorted(exposures.items(), key=lambda x: -x[1])
            },
        }
