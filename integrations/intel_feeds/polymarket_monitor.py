"""
Polymarket Monitor
==================
Monitors Polymarket's own platform for trading signals:

  - Volume spikes: sudden increases in trading volume signal something happening
  - Odds movements: if a market moves >10% in an hour, flag it
  - New trending / breaking markets
  - Overall platform awareness (not just tracked wallets)

APIs used (all public, no auth):
  - CLOB API:  https://clob.polymarket.com/markets
  - Gamma API: https://gamma-api.polymarket.com/markets

Poll interval: configurable, default 5 minutes
Redis channel: intel:polymarket
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger("intel_feeds.polymarket")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_URL = "redis://172.18.0.100:6379"
REDIS_CHANNEL = "intel:polymarket"
POLL_INTERVAL_SEC = 5 * 60  # 5 minutes

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Flag markets where price moved this fraction or more in one poll window
ODDS_MOVEMENT_THRESHOLD = 0.10  # 10%

# Flag markets where volume increased this multiple vs the previous snapshot
VOLUME_SPIKE_MULTIPLIER = 2.0  # 2× volume spike

# Number of top markets to monitor from the CLOB active listing
TOP_MARKETS_LIMIT = 100

HEADERS = {
    "User-Agent": "intel_feeds_bot/1.0 (trading intelligence; public API)",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    condition_id: str
    question: str
    # Best yes price (0-1 float)
    yes_price: float
    # 24h volume in USDC
    volume_24h: float
    # Total volume
    volume: float
    # Active / closed / resolved
    status: str
    # Raw category/tags if available
    tags: list[str] = field(default_factory=list)
    taken_at: float = field(default_factory=time.time)


# In-memory history: condition_id → last snapshot
_snapshots: dict[str, MarketSnapshot] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _urgency(relevance: int) -> str:
    if relevance >= 80:
        return "critical"
    if relevance >= 60:
        return "high"
    if relevance >= 40:
        return "medium"
    return "low"


def _odds_movement_signal(prev: MarketSnapshot, curr: MarketSnapshot) -> dict | None:
    """Return a signal dict if odds moved significantly, else None."""
    if prev.yes_price <= 0:
        return None
    movement = abs(curr.yes_price - prev.yes_price)
    pct_change = movement / prev.yes_price

    if pct_change < ODDS_MOVEMENT_THRESHOLD:
        return None

    direction = "UP" if curr.yes_price > prev.yes_price else "DOWN"
    relevance = min(int(40 + pct_change * 200), 100)  # scales with magnitude

    return {
        "source": "polymarket:odds_movement",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relevance_score": relevance,
        "urgency": _urgency(relevance),
        "category": "general",
        "markets_affected": [curr.condition_id],
        "summary": (
            f"Odds movement [{direction} {pct_change:.1%}] on \"{curr.question}\": "
            f"{prev.yes_price:.2f} → {curr.yes_price:.2f}"
        ),
        "raw": {
            "condition_id": curr.condition_id,
            "question": curr.question,
            "prev_yes": prev.yes_price,
            "curr_yes": curr.yes_price,
            "pct_change": round(pct_change, 4),
            "direction": direction,
        },
    }


def _volume_spike_signal(prev: MarketSnapshot, curr: MarketSnapshot) -> dict | None:
    """Return a signal dict if volume spiked significantly, else None."""
    if prev.volume_24h <= 0:
        return None
    ratio = curr.volume_24h / prev.volume_24h

    if ratio < VOLUME_SPIKE_MULTIPLIER:
        return None

    relevance = min(int(30 + (ratio - VOLUME_SPIKE_MULTIPLIER) * 20 + 20), 100)

    return {
        "source": "polymarket:volume_spike",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relevance_score": relevance,
        "urgency": _urgency(relevance),
        "category": "general",
        "markets_affected": [curr.condition_id],
        "summary": (
            f"Volume spike ({ratio:.1f}×) on \"{curr.question}\": "
            f"${prev.volume_24h:,.0f} → ${curr.volume_24h:,.0f} (24h)"
        ),
        "raw": {
            "condition_id": curr.condition_id,
            "question": curr.question,
            "prev_volume_24h": prev.volume_24h,
            "curr_volume_24h": curr.volume_24h,
            "ratio": round(ratio, 2),
        },
    }


def _new_market_signal(curr: MarketSnapshot) -> dict:
    """Signal for a newly discovered active market."""
    return {
        "source": "polymarket:new_market",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relevance_score": 35,
        "urgency": "low",
        "category": "general",
        "markets_affected": [curr.condition_id],
        "summary": f"New active market detected: \"{curr.question}\" (yes={curr.yes_price:.2f})",
        "raw": {
            "condition_id": curr.condition_id,
            "question": curr.question,
            "yes_price": curr.yes_price,
            "volume_24h": curr.volume_24h,
            "tags": curr.tags,
        },
    }


# ---------------------------------------------------------------------------
# API fetchers
# ---------------------------------------------------------------------------


async def fetch_gamma_markets(
    client: httpx.AsyncClient,
    limit: int = TOP_MARKETS_LIMIT,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch active markets from Gamma API sorted by volume.
    Returns raw dicts from the API.
    """
    url = (
        f"{GAMMA_BASE}/markets"
        f"?active=true&closed=false&limit={limit}&offset={offset}"
        f"&order=volumeNum&ascending=false"
    )
    try:
        resp = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        # Gamma API returns a list directly
        if isinstance(data, list):
            return data
        # Or wrapped
        return data.get("markets", data.get("data", []))
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s fetching Gamma markets: %s", exc.response.status_code, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching Gamma markets: %s", exc)
    return []


async def fetch_clob_markets(
    client: httpx.AsyncClient,
    next_cursor: str = "",
) -> tuple[list[dict], str]:
    """
    Fetch a page of markets from the CLOB API.
    Returns (markets_list, next_cursor).
    """
    url = f"{CLOB_BASE}/markets"
    params: dict[str, Any] = {}
    if next_cursor:
        params["next_cursor"] = next_cursor
    try:
        resp = await client.get(url, headers=HEADERS, params=params, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        markets = data.get("data", [])
        cursor = data.get("next_cursor", "")
        return markets, cursor
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s fetching CLOB markets: %s", exc.response.status_code, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching CLOB markets: %s", exc)
    return [], ""


def _gamma_to_snapshot(m: dict) -> MarketSnapshot | None:
    """Parse a Gamma API market dict into a MarketSnapshot."""
    try:
        condition_id = m.get("conditionId") or m.get("id") or ""
        if not condition_id:
            return None
        question = m.get("question") or m.get("title") or ""
        # Best yes price — may be stored as bestAsk/bestBid or outcomes
        yes_price = float(m.get("bestAsk") or m.get("lastTradePrice") or 0.5)
        volume_24h = float(m.get("volume24hr") or m.get("volume24h") or 0)
        volume = float(m.get("volume") or m.get("volumeNum") or 0)
        status = "active" if m.get("active") else "closed"
        tags = [t.get("label", "") for t in (m.get("tags") or [])]
        return MarketSnapshot(
            condition_id=condition_id,
            question=question,
            yes_price=yes_price,
            volume_24h=volume_24h,
            volume=volume,
            status=status,
            tags=tags,
        )
    except Exception as exc:
        logger.debug("Failed to parse Gamma market: %s — %s", m.get("id"), exc)
        return None


def _clob_to_snapshot(m: dict) -> MarketSnapshot | None:
    """Parse a CLOB API market dict into a MarketSnapshot."""
    try:
        condition_id = m.get("condition_id") or ""
        if not condition_id:
            return None
        question = m.get("question") or ""
        # CLOB tokens: first token is typically YES
        tokens = m.get("tokens", [])
        yes_price = 0.5
        if tokens:
            yes_token = next((t for t in tokens if t.get("outcome", "").lower() == "yes"), tokens[0])
            yes_price = float(yes_token.get("price", 0.5))
        volume_24h = float(m.get("volume_24hr") or m.get("volume24h") or 0)
        volume = float(m.get("volume") or 0)
        status = "active" if m.get("active") else "closed"
        tags = m.get("tags", []) or []
        return MarketSnapshot(
            condition_id=condition_id,
            question=question,
            yes_price=yes_price,
            volume_24h=volume_24h,
            volume=volume,
            status=status,
            tags=tags if isinstance(tags, list) else [],
        )
    except Exception as exc:
        logger.debug("Failed to parse CLOB market: %s — %s", m.get("condition_id"), exc)
        return None


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------


class PolymarketMonitor:
    """
    Tracks Polymarket platform state and publishes anomaly signals to Redis.

    Usage:
        monitor = PolymarketMonitor(redis_url=REDIS_URL)
        await monitor.run()
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        poll_interval: int = POLL_INTERVAL_SEC,
        odds_threshold: float = ODDS_MOVEMENT_THRESHOLD,
        volume_multiplier: float = VOLUME_SPIKE_MULTIPLIER,
    ):
        self.redis_url = redis_url
        self.poll_interval = poll_interval
        self.odds_threshold = odds_threshold
        self.volume_multiplier = volume_multiplier
        self._running = False

    async def _fetch_snapshots(self, client: httpx.AsyncClient) -> list[MarketSnapshot]:
        """Fetch current snapshots from both APIs, deduplicated by condition_id."""
        snapshots: dict[str, MarketSnapshot] = {}

        # Primary source: Gamma API (richer data)
        gamma_markets = await fetch_gamma_markets(client, limit=TOP_MARKETS_LIMIT)
        for m in gamma_markets:
            snap = _gamma_to_snapshot(m)
            if snap:
                snapshots[snap.condition_id] = snap

        # Secondary: CLOB API (first page only to avoid rate issues)
        clob_markets, _ = await fetch_clob_markets(client)
        for m in clob_markets:
            snap = _clob_to_snapshot(m)
            if snap and snap.condition_id not in snapshots:
                snapshots[snap.condition_id] = snap

        logger.debug("Fetched %d market snapshots", len(snapshots))
        return list(snapshots.values())

    async def _analyse_and_publish(
        self,
        current: list[MarketSnapshot],
        redis: aioredis.Redis,
    ) -> None:
        signals: list[dict] = []

        for snap in current:
            cid = snap.condition_id
            prev = _snapshots.get(cid)

            if prev is None:
                # First time seeing this market
                if snap.volume_24h > 5000:  # only surface reasonably active new markets
                    signals.append(_new_market_signal(snap))
            else:
                # Check for odds movement
                odds_sig = _odds_movement_signal(prev, snap)
                if odds_sig:
                    signals.append(odds_sig)

                # Check for volume spike
                vol_sig = _volume_spike_signal(prev, snap)
                if vol_sig:
                    signals.append(vol_sig)

            # Update snapshot
            _snapshots[cid] = snap

        for sig in signals:
            await redis.publish(REDIS_CHANNEL, json.dumps(sig))
            logger.info(
                "Published polymarket signal: relevance=%d urgency=%s summary=%s",
                sig["relevance_score"],
                sig["urgency"],
                sig["summary"][:100],
            )

    async def run(self) -> None:
        """Run the monitor loop indefinitely."""
        self._running = True
        logger.info(
            "PolymarketMonitor starting — interval=%ds odds_threshold=%.0f%% volume_multiplier=%.1f×",
            self.poll_interval,
            self.odds_threshold * 100,
            self.volume_multiplier,
        )

        redis = aioredis.from_url(self.redis_url, decode_responses=True)
        try:
            async with httpx.AsyncClient() as client:
                while self._running:
                    start = time.monotonic()
                    try:
                        snapshots = await self._fetch_snapshots(client)
                        await self._analyse_and_publish(snapshots, redis)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("PolymarketMonitor poll error: %s", exc, exc_info=True)

                    elapsed = time.monotonic() - start
                    sleep_time = max(0, self.poll_interval - elapsed)
                    logger.debug("PolymarketMonitor sleeping %.0fs", sleep_time)
                    await asyncio.sleep(sleep_time)
        finally:
            await redis.aclose()
            logger.info("PolymarketMonitor stopped.")

    def stop(self) -> None:
        self._running = False

    def get_snapshot(self, condition_id: str) -> MarketSnapshot | None:
        """Return the most recent snapshot for a given market."""
        return _snapshots.get(condition_id)

    def get_all_snapshots(self) -> dict[str, MarketSnapshot]:
        """Return all current snapshots."""
        return dict(_snapshots)


# ---------------------------------------------------------------------------
# Standalone entry (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
    )
    asyncio.run(PolymarketMonitor().run())
