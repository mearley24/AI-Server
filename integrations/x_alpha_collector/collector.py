"""X Alpha Collector — actively monitors curated X accounts via self-hosted RSSHub.

Polls RSS feeds from RSSHub for 40+ accounts, filters for trading-relevant content,
and routes qualifying posts through x-intake's LLM analysis pipeline.

Architecture:
  RSSHub (Docker) → collector polls RSS feeds every 10 min
  → keyword filter + dedup → x-intake /analyze endpoint
  → bot receives signals via Redis (from Prompt K wiring)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("x_alpha_collector")

RSSHUB_BASE = os.getenv("RSSHUB_URL", "http://rsshub:1200")
X_INTAKE_URL = os.getenv("X_INTAKE_URL", "http://x-intake:8101")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "600"))  # 10 minutes
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
SEEN_DB_PATH = Path(os.getenv("SEEN_DB_PATH", "/data/x_alpha_seen.json"))
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")

RELEVANCE_KEYWORDS = {
    "prediction market", "polymarket", "kalshi", "manifold",
    "arbitrage", "arb", "edge", "alpha", "strategy", "setup",
    "probability", "odds", "resolve", "resolution",
    "negative risk", "neg risk", "spread",
    "weather", "hurricane", "tornado", "earthquake", "wildfire",
    "fed", "fomc", "rate cut", "rate hike", "inflation", "cpi",
    "election", "trump", "biden", "vote", "ballot",
    "whale", "smart money", "on-chain",
    "bot", "trading bot", "automated", "algorithm",
    "entry", "exit", "stop loss", "take profit",
    "bullish", "bearish", "breakout", "breakdown",
    "mcp", "agent", "autonomous", "cursor", "ai server",
    "docker", "self-host", "local-first",
    "sports", "nba", "nfl", "mlb", "ufc",
    "crypto", "bitcoin", "btc", "ethereum", "eth", "solana",
    "market maker", "liquidity", "orderbook", "order book",
    "copytrade", "copy trade",
}

ALWAYS_PROCESS_AUTHORS = {
    "domahhhh", "verrissimus", "debased_pm", "scottonpoly",
    "polymarkettrade", "polymarket",
}


class SeenPostDB:
    """Simple JSON-backed dedup database for processed post IDs."""

    def __init__(self, path: Path = SEEN_DB_PATH):
        self.path = path
        self._seen: dict[str, float] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._seen = json.load(f)
            except (json.JSONDecodeError, Exception):
                self._seen = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Prune entries older than 7 days
        cutoff = time.time() - (7 * 86400)
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        with open(self.path, "w") as f:
            json.dump(self._seen, f)

    def is_seen(self, post_id: str) -> bool:
        return post_id in self._seen

    def mark_seen(self, post_id: str):
        self._seen[post_id] = time.time()
        if len(self._seen) % 20 == 0:
            self._save()

    def flush(self):
        self._save()


def load_watchlist() -> dict:
    """Load the account watchlist from JSON."""
    if not WATCHLIST_PATH.exists():
        logger.error("watchlist.json not found at %s", WATCHLIST_PATH)
        return {}
    with open(WATCHLIST_PATH) as f:
        return json.load(f)


def get_all_handles(watchlist: dict) -> list[tuple[str, str]]:
    """Extract all (handle, category) pairs from watchlist."""
    handles = []
    for category, data in watchlist.get("accounts", {}).items():
        for handle in data.get("handles", []):
            handles.append((handle, category))
    return handles


def fetch_rss_feed(handle: str) -> Optional[str]:
    """Fetch RSS feed XML from RSSHub for a Twitter user."""
    url = f"{RSSHUB_BASE}/twitter/user/{handle}"
    try:
        req = Request(url, headers={"User-Agent": "BobAlphaCollector/1.0"})
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        logger.debug("rss_fetch_failed: %s — %s", handle, str(e)[:100])
        return None
    except Exception as e:
        logger.debug("rss_fetch_error: %s — %s", handle, str(e)[:100])
        return None


def parse_rss_items(xml_text: str) -> list[dict]:
    """Parse RSS XML into a list of post dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        # Handle both RSS 2.0 and Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            guid = (item.findtext("guid") or link or "").strip()

            # Extract post ID from link
            post_id = ""
            m = re.search(r"/status/(\d+)", link)
            if m:
                post_id = m.group(1)
            elif guid:
                post_id = hashlib.md5(guid.encode()).hexdigest()[:16]

            # Strip HTML from description
            clean_text = re.sub(r"<[^>]+>", " ", desc).strip()
            clean_text = re.sub(r"\s+", " ", clean_text)

            items.append({
                "post_id": post_id,
                "title": title,
                "text": clean_text,
                "link": link,
                "pub_date": pub_date,
            })

        # Atom fallback
        if not items:
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                content = (entry.findtext("atom:content", namespaces=ns) or "").strip()
                entry_id = (entry.findtext("atom:id", namespaces=ns) or link).strip()

                post_id = ""
                m = re.search(r"/status/(\d+)", link)
                if m:
                    post_id = m.group(1)
                else:
                    post_id = hashlib.md5(entry_id.encode()).hexdigest()[:16]

                clean_text = re.sub(r"<[^>]+>", " ", content).strip()
                clean_text = re.sub(r"\s+", " ", clean_text)

                items.append({
                    "post_id": post_id,
                    "title": title,
                    "text": clean_text,
                    "link": link,
                    "pub_date": "",
                })
    except ET.ParseError as e:
        logger.warning("rss_parse_error: %s", str(e)[:100])
    return items


def is_relevant(text: str, author: str) -> bool:
    """Check if a post is relevant enough to analyze."""
    # Always process posts from top traders
    if author.lower() in ALWAYS_PROCESS_AUTHORS:
        return True

    text_lower = text.lower()

    # Check for keyword matches
    matches = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text_lower)
    if matches >= 1:
        return True

    # Check for Polymarket URLs
    if "polymarket.com" in text_lower or "kalshi.com" in text_lower:
        return True

    # Check for price/probability patterns
    if re.search(r"\b\d+[%¢c]\b", text_lower):
        return True

    return False


async def send_to_x_intake(url: str) -> Optional[dict]:
    """Send a post URL to x-intake for full LLM analysis."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{X_INTAKE_URL}/analyze",
                json={"url": url},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("x_intake_error: status=%d", resp.status_code)
            return None
    except Exception as e:
        logger.warning("x_intake_request_failed: %s", str(e)[:200])
        return None


async def notify_matt(message: str) -> None:
    """Send a notification to Matt via iMessage bridge."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                IMESSAGE_BRIDGE_URL,
                json={"message": message},
            )
    except Exception:
        pass  # Non-critical


async def publish_to_redis(payload: dict) -> None:
    """Publish high-value finds directly to Redis for the bot."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await client.publish("polymarket:intel_signals", json.dumps(payload))
        await client.aclose()
    except Exception as exc:
        logger.debug("redis_publish_failed: %s", str(exc)[:100])


async def process_single_account(
    handle: str,
    category: str,
    seen_db: SeenPostDB,
    stats: dict,
) -> list[dict]:
    """Process a single account's RSS feed. Returns list of analyzed posts."""
    xml = await asyncio.to_thread(fetch_rss_feed, handle)
    if not xml:
        stats["feed_errors"] += 1
        return []

    items = parse_rss_items(xml)
    stats["posts_seen"] += len(items)
    results = []

    for item in items:
        post_id = item["post_id"]
        if not post_id or seen_db.is_seen(post_id):
            continue

        seen_db.mark_seen(post_id)

        text = item.get("text", "") or item.get("title", "")
        if not is_relevant(text, handle):
            stats["filtered_out"] += 1
            continue

        link = item.get("link", "")
        if not link or "x.com" not in link and "twitter.com" not in link:
            continue

        stats["sent_to_analysis"] += 1
        logger.info(
            "analyzing_post: @%s | %s | %s",
            handle,
            post_id,
            text[:80],
        )

        result = await send_to_x_intake(link)
        if result:
            result["author"] = handle
            result["category"] = category
            result["post_id"] = post_id
            results.append(result)
            stats["analyzed"] += 1

    return results


async def run_collection_cycle(seen_db: SeenPostDB) -> dict:
    """Run one full collection cycle across all watched accounts."""
    watchlist = load_watchlist()
    handles = get_all_handles(watchlist)

    if not handles:
        logger.error("no_handles_in_watchlist")
        return {}

    stats = {
        "accounts_checked": 0,
        "posts_seen": 0,
        "filtered_out": 0,
        "sent_to_analysis": 0,
        "analyzed": 0,
        "feed_errors": 0,
        "high_value": 0,
        "cycle_start": time.time(),
    }

    logger.info("collection_cycle_start: %d accounts", len(handles))

    # Process accounts in batches of 5 to avoid hammering RSSHub
    batch_size = 5
    all_results = []

    for i in range(0, len(handles), batch_size):
        batch = handles[i:i + batch_size]
        tasks = []
        for handle, category in batch:
            stats["accounts_checked"] += 1
            tasks.append(process_single_account(handle, category, seen_db, stats))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for br in batch_results:
            if isinstance(br, list):
                all_results.extend(br)
            elif isinstance(br, Exception):
                logger.warning("batch_error: %s", str(br)[:100])

        # Small delay between batches to be polite
        if i + batch_size < len(handles):
            await asyncio.sleep(2)

    stats["cycle_duration_s"] = round(time.time() - stats["cycle_start"], 1)

    logger.info(
        "collection_cycle_complete: accounts=%d posts=%d analyzed=%d high_value=%d duration=%.1fs",
        stats["accounts_checked"],
        stats["posts_seen"],
        stats["analyzed"],
        stats["high_value"],
        stats["cycle_duration_s"],
    )

    seen_db.flush()
    return stats


async def run_daemon():
    """Main daemon loop — runs collection cycles on interval."""
    logger.info(
        "x_alpha_collector_started: rsshub=%s x_intake=%s interval=%ds",
        RSSHUB_BASE,
        X_INTAKE_URL,
        POLL_INTERVAL,
    )

    seen_db = SeenPostDB()

    # Wait for RSSHub to be ready
    for attempt in range(10):
        try:
            req = Request(f"{RSSHUB_BASE}/", headers={"User-Agent": "BobAlphaCollector/1.0"})
            with urlopen(req, timeout=5):
                logger.info("rsshub_ready")
                break
        except Exception:
            logger.info("waiting_for_rsshub: attempt %d/10", attempt + 1)
            await asyncio.sleep(10)

    while True:
        try:
            await run_collection_cycle(seen_db)
        except Exception as e:
            logger.error("collection_cycle_error: %s", str(e)[:300])

        await asyncio.sleep(POLL_INTERVAL)


def main():
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
