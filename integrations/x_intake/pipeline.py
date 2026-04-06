"""
pipeline.py
-----------
Main X/Twitter link intake pipeline for Bob.

Modes:
  1. Redis pub/sub daemon  — subscribes to incoming iMessage events,
                             detects tweet URLs, analyzes, and publishes
                             results to the notification-hub channel.
  2. iMessage bridge poll  — periodically polls http://host.docker.internal:8199
                             for new messages (fallback if Redis not available).
  3. CLI mode              — `python pipeline.py "https://x.com/user/status/123"`
                             for ad-hoc testing.

Architecture:
  iMessage → Redis channel:imessage-in → pipeline detects URL
  → PostFetcher → PostAnalyzer → format_response()
  → Redis channel:notification-hub → iMessage bridge → Matt

Configuration (environment variables):
  REDIS_HOST              Redis host (default: 172.18.0.100)
  REDIS_PORT              Redis port (default: 6379)
  REDIS_CHANNEL_IN        Channel to subscribe for incoming messages (default: imessage-in)
  REDIS_CHANNEL_OUT       Channel to publish responses (default: notification-hub)
  IMESSAGE_BRIDGE_URL     iMessage bridge base URL (default: http://host.docker.internal:8199)
  MATT_PHONE              Matt's phone/iMessage address (default: reads from bridge)
  OPEN_POSITIONS          Comma-separated tickers of open positions (e.g. BTC,ETH,SOL)
  WATCHED_MARKETS         Comma-separated Polymarket keyword categories to highlight
  POLL_INTERVAL           Bridge poll interval in seconds (default: 10)
  LOG_LEVEL               Logging level (default: INFO)
"""

import os
import sys
import json
import time
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin

# ---------------------------------------------------------------------------
# Bootstrap path so we can run as __main__ from any CWD
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_INTEGRATIONS_DIR = os.path.dirname(_THIS_DIR)
_ROOT_DIR = os.path.dirname(_INTEGRATIONS_DIR)
for _p in [_ROOT_DIR, _INTEGRATIONS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from integrations.x_intake.post_fetcher import PostFetcher, find_tweet_urls, FetchError
    from integrations.x_intake.analyzer import PostAnalyzer, AnalysisResult
except ImportError:
    from post_fetcher import PostFetcher, find_tweet_urls, FetchError
    from analyzer import PostAnalyzer, AnalysisResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "172.18.0.100")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL_IN = os.getenv("REDIS_CHANNEL_IN", "imessage-in")
REDIS_CHANNEL_OUT = os.getenv("REDIS_CHANNEL_OUT", "notification-hub")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")
MATT_PHONE = os.getenv("MATT_PHONE", "")
OPEN_POSITIONS = [p.strip().upper() for p in os.getenv("OPEN_POSITIONS", "").split(",") if p.strip()]
WATCHED_MARKETS = [m.strip() for m in os.getenv("WATCHED_MARKETS", "").split(",") if m.strip()]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("x_intake.pipeline")

# ---------------------------------------------------------------------------
# Response formatter
# ---------------------------------------------------------------------------

def format_response(url: str, post, result: AnalysisResult) -> str:
    """
    Build a concise iMessage response for Matt.

    Format:
      🐦 @author: "tweet text..."
      [Stats] [Media flag]

      📊 SENTIMENT | Assets: BTC, ETH
      [Position hits]
      [Whale alert]
      [Polymarket categories]

      ✅ What to do:
        • item 1
        • item 2

      Relevance: 73%
    """
    lines = []

    # Header
    author = post.author
    text = post.text
    if len(text) > 300:
        text = text[:297] + "..."

    lines.append(f"🐦 @{author}: \"{text}\"")

    # Thread context
    if post.thread_context:
        ctx = post.thread_context
        ctx_text = ctx.text[:120] + ("..." if len(ctx.text) > 120 else "")
        lines.append(f"↩ Replying to @{ctx.author}: \"{ctx_text}\"")

    # Stats
    stats_parts = []
    if post.like_count is not None:
        stats_parts.append(f"❤️ {post.like_count:,}")
    if post.retweet_count is not None:
        stats_parts.append(f"🔁 {post.retweet_count:,}")
    if post.view_count is not None:
        stats_parts.append(f"👁 {post.view_count:,}")
    if stats_parts:
        lines.append("  ".join(stats_parts))
    if post.media_urls:
        lines.append(f"📎 {len(post.media_urls)} media attachment(s)")

    lines.append("")

    # Analysis section
    analysis_parts = []
    if result.sentiment != "neutral":
        sentiment_icon = {"bullish": "🟢", "bearish": "🔴", "mixed": "🟡"}.get(result.sentiment, "⚪")
        analysis_parts.append(f"{sentiment_icon} {result.sentiment.upper()}")
    if result.assets_mentioned:
        analysis_parts.append(f"Assets: {', '.join(result.assets_mentioned[:6])}")
    if analysis_parts:
        lines.append(" | ".join(analysis_parts))

    if result.position_hits:
        hit_strs = [f"{h['position']} ({h['sentiment']})" for h in result.position_hits]
        lines.append(f"⚠️  Hits your positions: {', '.join(hit_strs)}")

    if result.whale_activity:
        lines.append("🐳 Whale activity mentioned")

    if result.prediction_market_relevant:
        lines.append("🎯 Prediction market relevant")

    if result.markets_mentioned:
        lines.append(f"📈 Polymarket: {', '.join(result.markets_mentioned)}")

    if result.signals:
        # Show price targets if present
        price_signals = [s for s in result.signals if s.startswith("price_targets")]
        if price_signals:
            lines.append(f"💰 {price_signals[0]}")

    # Actionable items
    if result.actionable_items:
        lines.append("")
        lines.append("✅ What to do:")
        for item in result.actionable_items[:4]:
            lines.append(f"  • {item}")

    # Relevance score
    lines.append("")
    score_bar = _score_bar(result.relevance_score)
    lines.append(f"Relevance: {int(result.relevance_score * 100)}% {score_bar}")
    lines.append(f"Source: {url}")

    return "\n".join(lines)


def _score_bar(score: float) -> str:
    """Visual relevance bar."""
    filled = round(score * 5)
    return "▓" * filled + "░" * (5 - filled)


def format_error_response(url: str, error: str) -> str:
    """Format a response for when a post can't be fetched."""
    return (
        f"❌ Couldn't fetch this X post.\n"
        f"URL: {url}\n"
        f"Reason: {error}\n"
        f"(Post may be deleted, private, or rate-limited.)"
    )


# ---------------------------------------------------------------------------
# iMessage bridge client
# ---------------------------------------------------------------------------

class IMessageBridge:
    """
    Thin client for the iMessage bridge HTTP API at host.docker.internal:8199.

    Expected API (adjust to match your bridge implementation):
      GET  /messages?since=<unix_timestamp>  → list of message objects
      POST /send                             → send message
        Body: {"to": "<address>", "text": "<message>"}
    """

    def __init__(self, base_url: str = IMESSAGE_BRIDGE_URL):
        self.base_url = base_url.rstrip("/")
        self._last_poll_ts: float = time.time()

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
        except (URLError, HTTPError) as e:
            logger.error(f"iMessage bridge request failed: {e}")
            return {}

    def poll_messages(self) -> list:
        """Fetch new messages since last poll. Returns list of message dicts."""
        since = int(self._last_poll_ts)
        result = self._request("GET", f"/messages?since={since}")
        self._last_poll_ts = time.time()
        messages = result.get("messages", [])
        if messages:
            logger.debug(f"Bridge returned {len(messages)} new message(s)")
        return messages

    def send(self, to: str, text: str) -> bool:
        """Send an iMessage. Returns True on success."""
        result = self._request("POST", "/send", {"to": to, "text": text})
        success = result.get("success", False) or result.get("status") == "ok"
        if success:
            logger.info(f"Sent iMessage to {to}")
        else:
            logger.error(f"Failed to send iMessage to {to}: {result}")
        return success

    def get_sender(self, message: dict) -> Optional[str]:
        """Extract sender address from a message dict."""
        return message.get("sender") or message.get("from") or message.get("address")

    def get_text(self, message: dict) -> str:
        """Extract text body from a message dict."""
        return message.get("text") or message.get("body") or message.get("content") or ""


# ---------------------------------------------------------------------------
# Redis pub/sub helpers
# ---------------------------------------------------------------------------

def _get_redis():
    """
    Lazily import redis and return a Redis client.
    Raises ImportError if redis-py is not installed,
    or ConnectionError if the server is unreachable.
    """
    try:
        import redis
    except ImportError:
        raise ImportError(
            "redis-py is not installed. Run: pip install redis"
        )
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    client.ping()  # Raises ConnectionError if unavailable
    return client


def publish_to_redis(client, channel: str, payload: dict) -> None:
    """Publish a JSON payload to a Redis channel."""
    client.publish(channel, json.dumps(payload))
    logger.debug(f"Published to Redis channel '{channel}': {payload}")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

class XIntakePipeline:
    """
    Main pipeline class. Orchestrates fetch → analyze → respond.
    """

    def __init__(
        self,
        open_positions: Optional[list] = None,
        watched_markets: Optional[list] = None,
    ):
        self.fetcher = PostFetcher(fetch_thread_context=True)
        self.analyzer = PostAnalyzer(
            open_positions=open_positions or OPEN_POSITIONS,
            watched_markets=watched_markets or WATCHED_MARKETS,
        )

    def process_url(self, url: str) -> tuple[bool, str]:
        """
        Process a single X/Twitter URL end-to-end.

        Returns:
            (success: bool, response_text: str)
        """
        logger.info(f"Processing URL: {url}")

        # Fetch
        try:
            post = self.fetcher.fetch(url)
        except FetchError as e:
            logger.warning(f"Fetch failed for {url}: {e}")
            return False, format_error_response(url, str(e))
        except Exception as e:
            logger.error(f"Unexpected fetch error for {url}: {traceback.format_exc()}")
            return False, format_error_response(url, f"Unexpected error: {e}")

        # Analyze
        try:
            result = self.analyzer.analyze(post)
        except Exception as e:
            logger.error(f"Analysis error: {traceback.format_exc()}")
            # Still return a basic response with post content
            result = AnalysisResult(
                relevance_score=0.0,
                summary=f"Analysis failed: {e}",
            )

        # Format
        response = format_response(url, post, result)
        return True, response

    def process_message(self, message_text: str) -> list[tuple[str, str]]:
        """
        Scan a message for X/Twitter URLs and process each one.

        Returns:
            list of (url, response_text) tuples
        """
        urls = find_tweet_urls(message_text)
        if not urls:
            return []

        logger.info(f"Found {len(urls)} tweet URL(s) in message")
        results = []
        for url in urls:
            success, response = self.process_url(url)
            results.append((url, response))

        return results

    # -----------------------------------------------------------------------
    # Daemon: Redis pub/sub mode
    # -----------------------------------------------------------------------

    def run_redis_subscriber(self) -> None:
        """
        Subscribe to REDIS_CHANNEL_IN for incoming iMessages.
        On receiving a message with a tweet URL, process and publish to
        REDIS_CHANNEL_OUT.

        Expected incoming message format (JSON):
          {
            "type": "imessage",
            "sender": "+1234567890",
            "text": "Check this out https://x.com/user/status/123",
            "timestamp": 1712345678
          }

        Published response format (JSON):
          {
            "type": "imessage_reply",
            "to": "+1234567890",
            "text": "<formatted analysis>",
            "source": "x_intake",
            "timestamp": 1712345678
          }
        """
        logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}")
        try:
            r = _get_redis()
        except ImportError as e:
            logger.error(str(e))
            sys.exit(1)
        except Exception as e:
            logger.error(f"Redis connection failed: {e}. Falling back to bridge polling.")
            self.run_bridge_poller()
            return

        pubsub = r.pubsub()
        pubsub.subscribe(REDIS_CHANNEL_IN)
        logger.info(f"Subscribed to Redis channel: {REDIS_CHANNEL_IN}")
        logger.info(f"Will publish responses to: {REDIS_CHANNEL_OUT}")

        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"Non-JSON message on {REDIS_CHANNEL_IN}, skipping")
                continue

            msg_text = data.get("text") or data.get("body") or data.get("content") or ""
            sender = data.get("sender") or data.get("from") or MATT_PHONE

            if not msg_text:
                continue

            results = self.process_message(msg_text)
            if not results:
                continue

            for url, response_text in results:
                payload = {
                    "type": "imessage_reply",
                    "to": sender,
                    "text": response_text,
                    "source": "x_intake",
                    "trigger_url": url,
                    "timestamp": int(time.time()),
                }
                publish_to_redis(r, REDIS_CHANNEL_OUT, payload)
                logger.info(f"Published analysis for {url} to {REDIS_CHANNEL_OUT}")

    # -----------------------------------------------------------------------
    # Daemon: Bridge polling mode
    # -----------------------------------------------------------------------

    def run_bridge_poller(self) -> None:
        """
        Poll the iMessage bridge for new messages and respond via POST /send.
        Used as a fallback when Redis is unavailable.
        """
        bridge = IMessageBridge()
        logger.info(
            f"Starting bridge polling mode: {IMESSAGE_BRIDGE_URL} "
            f"(interval: {POLL_INTERVAL}s)"
        )

        while True:
            try:
                messages = bridge.poll_messages()
                for msg in messages:
                    sender = bridge.get_sender(msg)
                    text = bridge.get_text(msg)

                    if not text:
                        continue

                    results = self.process_message(text)
                    if not results:
                        continue

                    for url, response_text in results:
                        reply_to = sender or MATT_PHONE
                        if reply_to:
                            bridge.send(reply_to, response_text)
                        else:
                            logger.warning(
                                f"No sender address for reply. Response:\n{response_text}"
                            )
            except KeyboardInterrupt:
                logger.info("Bridge poller stopped.")
                break
            except Exception as e:
                logger.error(f"Bridge polling error: {e}")

            time.sleep(POLL_INTERVAL)

    # -----------------------------------------------------------------------
    # CLI mode
    # -----------------------------------------------------------------------

    def run_cli(self, url: str) -> None:
        """Process a single URL from the command line and print the result."""
        print(f"\nProcessing: {url}\n{'─' * 60}")
        success, response = self.process_url(url)
        print(response)
        print('─' * 60)
        if not success:
            sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="X/Twitter intake pipeline for Bob",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # CLI mode — process a single tweet
  python pipeline.py "https://x.com/user/status/123456789"

  # Daemon mode — Redis pub/sub (default)
  python pipeline.py --daemon

  # Daemon mode — bridge polling fallback
  python pipeline.py --daemon --mode poll

  # Override open positions at runtime
  OPEN_POSITIONS=BTC,ETH,SOL python pipeline.py --daemon
        """,
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="X/Twitter URL to process (CLI mode)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon (Redis or polling mode)",
    )
    parser.add_argument(
        "--mode",
        choices=["redis", "poll"],
        default="redis",
        help="Daemon mode: redis (default) or poll (bridge polling)",
    )
    parser.add_argument(
        "--positions",
        help="Comma-separated open positions (overrides OPEN_POSITIONS env var)",
    )
    parser.add_argument(
        "--markets",
        help="Comma-separated Polymarket keywords (overrides WATCHED_MARKETS env var)",
    )

    args = parser.parse_args()

    positions = (
        [p.strip().upper() for p in args.positions.split(",") if p.strip()]
        if args.positions
        else OPEN_POSITIONS
    )
    markets = (
        [m.strip() for m in args.markets.split(",") if m.strip()]
        if args.markets
        else WATCHED_MARKETS
    )

    pipeline = XIntakePipeline(
        open_positions=positions,
        watched_markets=markets,
    )

    if args.url:
        # CLI mode
        pipeline.run_cli(args.url)

    elif args.daemon:
        if args.mode == "redis":
            pipeline.run_redis_subscriber()
        else:
            pipeline.run_bridge_poller()

    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
