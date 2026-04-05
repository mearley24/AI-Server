import os
"""
Reddit Monitor
==============
Polls r/Polymarket, r/sportsbetting, and r/predictit using Reddit's public
JSON API (no authentication required — appending .json to any Reddit URL
returns structured data).

Poll interval: 15 minutes
Redis channel: intel:reddit
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from . import SIGNAL_SCHEMA  # noqa: F401 — schema reference

logger = logging.getLogger("intel_feeds.reddit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://172.18.0.100:6379")
REDIS_CHANNEL = "intel:reddit"
POLL_INTERVAL_SEC = 15 * 60  # 15 minutes

SUBREDDITS = [
    "Polymarket",
    "sportsbetting",
    "predictit",
]

# Posts with score >= this threshold are flagged for high engagement
HIGH_ENGAGEMENT_THRESHOLD = 50

# Regex to extract Polymarket market slugs from text / URLs
POLYMARKET_URL_RE = re.compile(
    r"polymarket\.com/event/([a-z0-9\-]+)", re.IGNORECASE
)

# Populated at runtime by the aggregator / bot to indicate active positions
# Format: set of condition IDs or market slugs
WATCHED_MARKETS: set[str] = set()

# User-Agent Reddit requires — use a descriptive bot string
USER_AGENT = "intel_feeds_bot/1.0 (trading intelligence layer; public data only)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_id(post: dict) -> str:
    """Stable dedup key for a Reddit post."""
    return post.get("id", hashlib.md5(post.get("title", "").encode()).hexdigest())


def _extract_markets(text: str) -> list[str]:
    """Pull Polymarket market slugs out of free text / URLs."""
    return POLYMARKET_URL_RE.findall(text or "")


def _score_relevance(post: dict, markets_mentioned: list[str]) -> int:
    """
    Heuristic relevance score 0-100.
    - Base 20 for appearing at all
    - +30 if it mentions a watched market
    - +20 if score >= HIGH_ENGAGEMENT_THRESHOLD
    - +10 per watched-market mention (up to 30)
    - +10 for Polymarket-specific subreddit
    """
    score = 20
    subreddit = (post.get("subreddit") or "").lower()
    post_score = post.get("score", 0)

    if subreddit == "polymarket":
        score += 10

    if post_score >= HIGH_ENGAGEMENT_THRESHOLD:
        score += 20

    watched_hits = [m for m in markets_mentioned if m in WATCHED_MARKETS]
    if watched_hits:
        score += 30
        score += min(len(watched_hits) * 10, 30)

    return min(score, 100)


def _urgency(relevance: int) -> str:
    if relevance >= 80:
        return "critical"
    if relevance >= 60:
        return "high"
    if relevance >= 40:
        return "medium"
    return "low"


def _build_signal(post: dict, markets: list[str], relevance: int) -> dict:
    title = post.get("title", "")
    author = post.get("author", "[deleted]")
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)
    subreddit = post.get("subreddit", "")
    permalink = f"https://www.reddit.com{post.get('permalink', '')}"

    summary = (
        f"[r/{subreddit}] \"{title}\" — score:{score} "
        f"comments:{num_comments} by u/{author}"
    )

    return {
        "source": f"reddit:r/{subreddit}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relevance_score": relevance,
        "urgency": _urgency(relevance),
        "category": "general",  # reddit_monitor doesn't deep-categorise
        "markets_affected": markets,
        "summary": summary,
        "raw": {
            "id": post.get("id"),
            "title": title,
            "selftext": (post.get("selftext") or "")[:500],
            "score": score,
            "num_comments": num_comments,
            "author": author,
            "subreddit": subreddit,
            "permalink": permalink,
            "url": post.get("url"),
            "created_utc": post.get("created_utc"),
        },
    }


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


async def fetch_subreddit(
    client: httpx.AsyncClient, subreddit: str, limit: int = 25
) -> list[dict]:
    """Fetch the hot listing of a subreddit via the public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        posts = [child["data"] for child in data.get("data", {}).get("children", [])]
        logger.debug("Fetched %d posts from r/%s", len(posts), subreddit)
        return posts
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s fetching r/%s: %s", exc.response.status_code, subreddit, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching r/%s: %s", subreddit, exc)
    return []


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------


class RedditMonitor:
    """
    Polls configured subreddits and publishes signals to Redis.

    Usage:
        monitor = RedditMonitor(redis_url=REDIS_URL)
        await monitor.run()
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        poll_interval: int = POLL_INTERVAL_SEC,
        subreddits: list[str] | None = None,
    ):
        self.redis_url = redis_url
        self.poll_interval = poll_interval
        self.subreddits = subreddits or SUBREDDITS
        self._seen: set[str] = set()  # dedup cache
        self._running = False

    async def _process_post(self, post: dict, redis: aioredis.Redis) -> None:
        post_id = _post_id(post)
        if post_id in self._seen:
            return
        self._seen.add(post_id)

        title = post.get("title", "")
        body = post.get("selftext", "")
        url_field = post.get("url", "")
        combined = f"{title} {body} {url_field}"

        markets = _extract_markets(combined)
        relevance = _score_relevance(post, markets)

        # Only publish posts that are at least somewhat relevant
        min_score = post.get("score", 0)
        subreddit = (post.get("subreddit") or "").lower()

        # Always surface high-engagement or market-mentioning posts;
        # for generic posts only publish if they're on Polymarket sub or mention markets
        if (
            relevance < 30
            and min_score < HIGH_ENGAGEMENT_THRESHOLD
            and subreddit != "polymarket"
            and not markets
        ):
            return

        signal = _build_signal(post, markets, relevance)
        await redis.publish(REDIS_CHANNEL, json.dumps(signal))
        logger.info(
            "Published reddit signal: relevance=%d urgency=%s summary=%s",
            relevance,
            signal["urgency"],
            signal["summary"][:80],
        )

    async def _poll_once(self, client: httpx.AsyncClient, redis: aioredis.Redis) -> None:
        for subreddit in self.subreddits:
            posts = await fetch_subreddit(client, subreddit)
            for post in posts:
                await self._process_post(post, redis)
            # Small delay between subreddits to be polite
            await asyncio.sleep(2)

    async def run(self) -> None:
        """Run the monitor loop indefinitely."""
        self._running = True
        logger.info(
            "RedditMonitor starting — subreddits=%s interval=%ds",
            self.subreddits,
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
                        logger.error("RedditMonitor poll error: %s", exc, exc_info=True)

                    elapsed = time.monotonic() - start
                    sleep_time = max(0, self.poll_interval - elapsed)
                    logger.debug("RedditMonitor sleeping %.0fs", sleep_time)
                    await asyncio.sleep(sleep_time)
        finally:
            await redis.aclose()
            logger.info("RedditMonitor stopped.")

    def stop(self) -> None:
        self._running = False

    def update_watched_markets(self, markets: set[str]) -> None:
        """Called by the aggregator/bot to update the set of tracked markets."""
        WATCHED_MARKETS.update(markets)
        logger.info("RedditMonitor watched_markets updated: %d markets", len(WATCHED_MARKETS))


# ---------------------------------------------------------------------------
# Standalone entry (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
    )
    asyncio.run(RedditMonitor().run())
