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
# Sub-categories for sports are checked FIRST to get granular classification
# us_sports: 40% WR, -$15 net. soccer_intl: 40% WR, -$8 net. tennis/esports: profitable.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # ── Sports sub-categories (checked before generic "sports") ──────
    "us_sports": [
        "nba", "nfl", "mlb", "nhl", "spread", "lakers", "celtics", "warriors",
        "knicks", "bulls", "nets", "heat", "bucks", "76ers", "suns", "clippers",
        "mavericks", "nuggets", "timberwolves", "pacers", "cavaliers", "thunder",
        "chiefs", "eagles", "cowboys", "49ers", "ravens", "lions", "bills",
        "yankees", "dodgers", "braves", "astros", "mets", "padres", "phillies",
        "bruins", "rangers", "oilers", "panthers", "avalanche", "maple leafs",
        "hockey", "basketball", "baseball", "super bowl", "mvp",
        "touchdown", "home run", "slam dunk", "hat trick",
    ],
    "soccer_intl": [
        "friendly", "friendlies", "international soccer", "international football",
        "liberia", "benin", "togo", "cameroon", "senegal", "ghana", "nigeria",
        "ivory coast", "algeria", "morocco", "tunisia", "egypt", "ethiopia",
        "kenya", "tanzania", "mozambique", "angola", "zambia", "zimbabwe",
        "afcon", "concacaf", "copa america", "nations league",
        "international match", "qualifying",
    ],
    "esports": [
        "counter-strike", "cs2", "cs:go", "valorant", "dota", "dota 2",
        "lol ", "league of legends", "overwatch", "fortnite", "pubg",
        "esports", "e-sports", "gaming tournament",
    ],
    "tennis": [
        "tennis", "wimbledon", "us open tennis", "french open", "australian open",
        "roland garros", "atp", "wta", "grand slam", "djokovic", "nadal",
        "alcaraz", "sinner", "medvedev", "swiatek", "sabalenka",
    ],
    # ── Main categories ──────────────────────────────────────────────
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
        "soccer", "football", "golf", "ufc", "mma", "boxing",
        "world cup", "championship", "playoff",
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


# Sub-categories that should be checked FIRST (before their parent category)
# This ensures "NBA spread" → us_sports, not generic "sports"
_PRIORITY_CATEGORIES = ["us_sports", "soccer_intl", "esports", "tennis"]


def categorize_market(question: str, tags: list[str] | None = None) -> str:
    """Categorize a market based on its question text and optional tags.

    Returns the best-matching category or 'other' if no strong match.
    Sub-categories (us_sports, soccer_intl, esports, tennis) are checked first
    to ensure granular classification before falling back to generic "sports".
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

    # Priority check: sub-categories first (us_sports, soccer_intl, esports, tennis)
    for priority_cat in _PRIORITY_CATEGORIES:
        keywords = CATEGORY_KEYWORDS.get(priority_cat, [])
        for kw in keywords:
            if kw in q_lower:
                return priority_cat

    # Keyword matching with score for remaining categories
    scores: dict[str, int] = defaultdict(int)
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category in _PRIORITY_CATEGORIES:
            continue  # already checked above
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
