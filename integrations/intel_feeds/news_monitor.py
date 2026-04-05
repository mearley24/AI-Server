import os
"""
News Monitor
============
Polls RSS feeds for news that could affect prediction markets.

Sources:
  - AP News          (general)
  - NOAA Weather Alerts
  - ESPN             (sports)
  - CoinDesk         (crypto)
  - Federal Reserve / FRED (economics)

Poll interval: 10 minutes
Redis channel: intel:news
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
import redis.asyncio as aioredis

logger = logging.getLogger("intel_feeds.news")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://172.18.0.100:6379")
REDIS_CHANNEL = "intel:news"
POLL_INTERVAL_SEC = 10 * 60  # 10 minutes

# Each feed: (name, url, category)
RSS_FEEDS: list[tuple[str, str, str]] = [
    # AP News — general/politics
    ("ap_news_top", "https://rsshub.app/apnews/topics/apf-topnews", "general"),
    ("ap_news_politics", "https://rsshub.app/apnews/topics/apf-politics", "politics"),
    # NOAA Weather Alerts (CAP/ATOM)
    ("noaa_alerts", "https://alerts.weather.gov/cap/us.php?x=1", "weather"),
    # ESPN
    ("espn_top", "https://www.espn.com/espn/rss/news", "sports"),
    ("espn_nfl", "https://www.espn.com/espn/rss/nfl/news", "sports"),
    ("espn_nba", "https://www.espn.com/espn/rss/nba/news", "sports"),
    ("espn_mlb", "https://www.espn.com/espn/rss/mlb/news", "sports"),
    # CoinDesk — crypto
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    # Federal Reserve / FRED
    ("fed_press", "https://www.federalreserve.gov/feeds/press_all.xml", "economics"),
    # Fallback: Reuters World (publicly accessible RSS)
    ("reuters_world", "https://feeds.reuters.com/Reuters/worldNews", "general"),
]

# Keywords that bump a news item's relevance for prediction markets
PREDICTION_MARKET_KEYWORDS = [
    "election", "vote", "poll", "odds", "forecast", "predict",
    "bitcoin", "ethereum", "btc", "eth", "crypto",
    "fed", "federal reserve", "interest rate", "inflation",
    "hurricane", "tornado", "wildfire", "earthquake", "flood",
    "championship", "super bowl", "world series", "nba finals",
    "supreme court", "legislation", "bill passed", "executive order",
    "gdp", "unemployment", "recession",
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "weather": ["hurricane", "tornado", "flood", "earthquake", "wildfire", "storm", "blizzard", "drought"],
    "sports": ["nfl", "nba", "mlb", "nhl", "soccer", "championship", "playoff", "draft", "trade"],
    "crypto": ["bitcoin", "ethereum", "btc", "eth", "defi", "blockchain", "crypto", "stablecoin", "sec"],
    "politics": ["election", "congress", "senate", "president", "vote", "legislation", "court", "ruling"],
    "economics": ["fed", "rate", "inflation", "gdp", "unemployment", "recession", "treasury", "fiscal"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_id(entry: Any) -> str:
    """Stable dedup key for an RSS entry."""
    raw = getattr(entry, "id", None) or getattr(entry, "link", None) or getattr(entry, "title", "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _parse_published(entry: Any) -> str:
    """Return ISO UTC timestamp from an RSS entry, falling back to now."""
    for field in ("published", "updated"):
        val = getattr(entry, field, None)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def _detect_category(text: str, feed_category: str) -> str:
    """
    Refine category using keyword matching; fall back to feed-declared category.
    """
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return feed_category


def _score_relevance(title: str, summary: str, category: str) -> int:
    """
    Heuristic relevance score 0-100 for a news item.
    """
    combined = (title + " " + summary).lower()
    base = 25

    # Keyword hits
    hits = sum(1 for kw in PREDICTION_MARKET_KEYWORDS if kw in combined)
    base += min(hits * 8, 40)

    # High-signal categories
    if category in ("weather", "crypto", "politics"):
        base += 10
    elif category == "economics":
        base += 8

    # Proper nouns / breaking indicators
    if any(w in combined for w in ["breaking", "urgent", "alert", "warning", "watch"]):
        base += 15

    return min(base, 100)


def _urgency(relevance: int) -> str:
    if relevance >= 80:
        return "critical"
    if relevance >= 60:
        return "high"
    if relevance >= 40:
        return "medium"
    return "low"


def _build_signal(entry: Any, feed_name: str, feed_category: str) -> dict:
    title = getattr(entry, "title", "") or ""
    link = getattr(entry, "link", "") or ""
    summary_raw = getattr(entry, "summary", "") or ""
    # Strip HTML tags from summary
    summary_text = re.sub(r"<[^>]+>", "", summary_raw)[:400]

    combined_text = f"{title} {summary_text}"
    category = _detect_category(combined_text, feed_category)
    relevance = _score_relevance(title, summary_text, category)
    published = _parse_published(entry)

    return {
        "source": f"rss:{feed_name}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relevance_score": relevance,
        "urgency": _urgency(relevance),
        "category": category,
        "markets_affected": [],  # cross-referencing done by aggregator
        "summary": f"[{category.upper()}] {title}",
        "raw": {
            "title": title,
            "link": link,
            "summary": summary_text,
            "published": published,
            "feed": feed_name,
        },
    }


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


async def fetch_feed(
    client: httpx.AsyncClient, feed_name: str, feed_url: str, category: str
) -> list[dict]:
    """Fetch and parse a single RSS feed, returning a list of signal dicts."""
    try:
        resp = await client.get(
            feed_url,
            timeout=20,
            headers={
                "User-Agent": "intel_feeds_bot/1.0 (trading intelligence; public RSS)",
                "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
            },
            follow_redirects=True,
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        entries = feed.get("entries", [])
        logger.debug("Fetched %d entries from %s", len(entries), feed_name)

        signals = []
        for entry in entries[:30]:  # cap at 30 per feed per poll
            sig = _build_signal(entry, feed_name, category)
            signals.append(sig)
        return signals

    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s fetching %s: %s", exc.response.status_code, feed_name, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching %s: %s", feed_name, exc)
    return []


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------


class NewsMonitor:
    """
    Polls RSS feeds and publishes signals to Redis.

    Usage:
        monitor = NewsMonitor(redis_url=REDIS_URL)
        await monitor.run()
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        poll_interval: int = POLL_INTERVAL_SEC,
        feeds: list[tuple[str, str, str]] | None = None,
    ):
        self.redis_url = redis_url
        self.poll_interval = poll_interval
        self.feeds = feeds or RSS_FEEDS
        self._seen: set[str] = set()
        self._running = False

        # Bot can inject active market keywords here for cross-referencing
        self.active_market_keywords: list[str] = []

    def _find_affected_markets(self, text: str) -> list[str]:
        """
        Very lightweight cross-reference: check if text mentions any keyword
        associated with active markets.
        """
        text_lower = text.lower()
        return [kw for kw in self.active_market_keywords if kw.lower() in text_lower]

    async def _publish_signal(self, signal: dict, redis: aioredis.Redis) -> None:
        entry_id = _entry_id(type("E", (), signal["raw"])())
        # Use link + title hash as dedup key
        dedup_key = hashlib.sha256(
            (signal["raw"].get("link", "") + signal["raw"].get("title", "")).encode()
        ).hexdigest()[:16]

        if dedup_key in self._seen:
            return
        self._seen.add(dedup_key)

        # Cross-reference active markets
        combined = signal["raw"].get("title", "") + " " + signal["raw"].get("summary", "")
        signal["markets_affected"] = self._find_affected_markets(combined)

        # Only publish items meeting a minimum threshold
        if signal["relevance_score"] < 30:
            return

        await redis.publish(REDIS_CHANNEL, json.dumps(signal))
        logger.info(
            "Published news signal: relevance=%d urgency=%s summary=%s",
            signal["relevance_score"],
            signal["urgency"],
            signal["summary"][:80],
        )

    async def _poll_once(self, client: httpx.AsyncClient, redis: aioredis.Redis) -> None:
        # Fetch all feeds concurrently
        tasks = [
            fetch_feed(client, name, url, cat)
            for name, url, cat in self.feeds
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Feed fetch exception: %s", result)
                continue
            for signal in result:
                await self._publish_signal(signal, redis)

    async def run(self) -> None:
        """Run the monitor loop indefinitely."""
        self._running = True
        logger.info(
            "NewsMonitor starting — feeds=%d interval=%ds",
            len(self.feeds),
            self.poll_interval,
        )

        redis = aioredis.from_url(self.redis_url, decode_responses=True)
        try:
            async with httpx.AsyncClient() as client:
                while self._running:
                    start = time.monotonic()
                    try:
                        await self._poll_once(client, redis)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("NewsMonitor poll error: %s", exc, exc_info=True)

                    elapsed = time.monotonic() - start
                    sleep_time = max(0, self.poll_interval - elapsed)
                    logger.debug("NewsMonitor sleeping %.0fs", sleep_time)
                    await asyncio.sleep(sleep_time)
        finally:
            await redis.aclose()
            logger.info("NewsMonitor stopped.")

    def stop(self) -> None:
        self._running = False

    def update_market_keywords(self, keywords: list[str]) -> None:
        """Update keywords used to cross-reference news against active markets."""
        self.active_market_keywords = keywords
        logger.info("NewsMonitor market_keywords updated: %d keywords", len(keywords))


# ---------------------------------------------------------------------------
# Standalone entry (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
    )
    asyncio.run(NewsMonitor().run())
