"""Market scanner — discovers active 5m/15m up/down markets for BTC, ETH, SOL."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.client import PolymarketClient
from src.config import Settings

logger = structlog.get_logger(__name__)

# Patterns that match Polymarket's crypto price movement markets
# e.g. "Will Bitcoin go up in the next 5 minutes?", "BTC 5-minute up", etc.
CRYPTO_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth", "ether"],
    "SOL": ["solana", "sol"],
}

TIMEFRAME_PATTERNS = [
    (r"5[\s-]?min", "5m"),
    (r"15[\s-]?min", "15m"),
    (r"1[\s-]?hour", "1h"),
]

DIRECTION_PATTERNS = [
    (r"\bup\b|\babove\b|\bhigher\b|\bover\b", "up"),
    (r"\bdown\b|\bbelow\b|\blower\b|\bunder\b", "down"),
]

# Broader search terms to discover more market types beyond just directional moves
EXTRA_SEARCH_TERMS: list[str] = [
    "BTC price",
    "ETH price",
    "SOL price",
    "bitcoin above",
    "bitcoin below",
    "ethereum above",
    "ethereum below",
    "crypto",
]


@dataclass
class ScannedMarket:
    """A discovered tradeable market."""

    condition_id: str
    question: str
    token: str  # BTC, ETH, SOL
    timeframe: str  # 5m, 15m
    direction: str  # up, down
    token_id_yes: str
    token_id_no: str
    end_date: str
    volume: float = 0.0
    last_price_yes: float = 0.0
    last_price_no: float = 0.0
    active: bool = True


@dataclass
class ScanResult:
    """Result of a market scan."""

    markets: list[ScannedMarket] = field(default_factory=list)
    scan_time: float = 0.0
    errors: list[str] = field(default_factory=list)


class MarketScanner:
    """Scans Polymarket for active crypto price movement markets."""

    def __init__(self, client: PolymarketClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._scan_tokens = settings.stink_bid_markets
        self._cached_markets: list[ScannedMarket] = []
        self._last_scan: float = 0.0
        self._cache_ttl: float = 60.0  # Rescan every 60s

    @property
    def cached_markets(self) -> list[ScannedMarket]:
        return self._cached_markets

    async def scan(self, force: bool = False) -> ScanResult:
        """Scan for active crypto markets. Uses cache unless force=True or TTL expired."""
        now = time.time()
        if not force and self._cached_markets and (now - self._last_scan) < self._cache_ttl:
            return ScanResult(markets=self._cached_markets, scan_time=0.0)

        start = time.time()
        result = ScanResult()
        seen_ids: set[str] = set()

        for token in self._scan_tokens:
            try:
                markets = await self._scan_token(token)
                for m in markets:
                    if m.condition_id not in seen_ids:
                        seen_ids.add(m.condition_id)
                        result.markets.append(m)
            except Exception as exc:
                err = f"Error scanning {token}: {exc}"
                logger.error("scan_error", token=token, error=str(exc))
                result.errors.append(err)

        # Broader search: "BTC price", "bitcoin above", etc. to catch markets
        # that don't match the strict alias patterns (e.g. "Will BTC be above $70k?")
        for term in EXTRA_SEARCH_TERMS:
            try:
                raw_markets = await self._client.search_markets(term, limit=100)
                for mkt in raw_markets:
                    # Try to match against all known tokens
                    for token, aliases in CRYPTO_ALIASES.items():
                        parsed = self._parse_market(mkt, token)
                        if parsed and parsed.condition_id not in seen_ids:
                            seen_ids.add(parsed.condition_id)
                            result.markets.append(parsed)
                            break
            except Exception as exc:
                logger.warning("extra_search_failed", term=term, error=str(exc))

        result.scan_time = time.time() - start
        self._cached_markets = result.markets
        self._last_scan = time.time()

        logger.info(
            "scan_complete",
            markets_found=len(result.markets),
            scan_time=f"{result.scan_time:.2f}s",
            tokens=self._scan_tokens,
        )
        return result

    async def _scan_token(self, token: str) -> list[ScannedMarket]:
        """Search Gamma API for markets matching a token."""
        aliases = CRYPTO_ALIASES.get(token, [token.lower()])
        all_markets: list[ScannedMarket] = []

        for alias in aliases:
            try:
                raw_markets = await self._client.search_markets(alias, limit=100)
            except Exception as exc:
                logger.warning("search_failed", alias=alias, error=str(exc))
                continue

            for mkt in raw_markets:
                parsed = self._parse_market(mkt, token)
                if parsed:
                    all_markets.append(parsed)

        # Deduplicate by condition_id
        seen: set[str] = set()
        unique: list[ScannedMarket] = []
        for m in all_markets:
            if m.condition_id not in seen:
                seen.add(m.condition_id)
                unique.append(m)

        return unique

    def _parse_market(self, raw: dict[str, Any], token: str) -> ScannedMarket | None:
        """Parse a raw Gamma market into a ScannedMarket if it matches our criteria."""
        question = raw.get("question", "").lower()
        description = raw.get("description", "").lower()
        text = f"{question} {description}"

        # Must be active
        if not raw.get("active", False):
            return None

        # Detect timeframe — also accept markets without an explicit timeframe
        # (e.g. "Will BTC be above $70k?" style) as "spot"
        timeframe = None
        for pattern, tf in TIMEFRAME_PATTERNS:
            if re.search(pattern, text):
                timeframe = tf
                break

        if not timeframe:
            # Accept price-level markets ("above $X", "below $X") without a timeframe
            if not re.search(r"\b(above|below|over|under)\b.*\$[\d,]+", text):
                return None
            timeframe = "spot"

        # Detect direction
        direction = None
        for pattern, d in DIRECTION_PATTERNS:
            if re.search(pattern, text):
                direction = d
                break

        if not direction:
            return None

        # Extract token IDs
        tokens = raw.get("tokens", [])
        if len(tokens) < 2:
            return None

        token_id_yes = tokens[0].get("token_id", "")
        token_id_no = tokens[1].get("token_id", "")

        return ScannedMarket(
            condition_id=raw.get("condition_id", raw.get("id", "")),
            question=raw.get("question", ""),
            token=token,
            timeframe=timeframe,
            direction=direction,
            token_id_yes=token_id_yes,
            token_id_no=token_id_no,
            end_date=raw.get("end_date_iso", ""),
            volume=float(raw.get("volume", 0)),
            last_price_yes=float(tokens[0].get("price", 0)) if tokens else 0.0,
            last_price_no=float(tokens[1].get("price", 0)) if len(tokens) > 1 else 0.0,
            active=raw.get("active", True),
        )

    def get_markets_for_strategy(
        self,
        token: str | None = None,
        timeframe: str | None = None,
        direction: str | None = None,
    ) -> list[ScannedMarket]:
        """Filter cached markets by criteria."""
        results = self._cached_markets
        if token:
            results = [m for m in results if m.token == token]
        if timeframe:
            results = [m for m in results if m.timeframe == timeframe]
        if direction:
            results = [m for m in results if m.direction == direction]
        return results
