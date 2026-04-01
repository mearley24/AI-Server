"""
Intel Feeds Runner
==================
Main entry point that starts all intelligence monitors concurrently.

Usage:
    python -m integrations.intel_feeds.runner [--log-level DEBUG]

Or via Docker:
    CMD python -m integrations.intel_feeds.runner

Health check:
    GET http://0.0.0.0:8765/health
    → { "status": "ok", "uptime_sec": 123, "monitors": {...} }

Sentiment query (used by the bot):
    GET http://0.0.0.0:8765/sentiment?topic=bitcoin
    → { "topic": "bitcoin", "verdict": "high_activity", ... }

Recent signals:
    GET http://0.0.0.0:8765/signals?hours=1&min_relevance=50
    GET http://0.0.0.0:8765/signals?category=weather

Daily briefing:
    GET http://0.0.0.0:8765/briefing
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlparse, parse_qs

from .reddit_monitor import RedditMonitor
from .news_monitor import NewsMonitor
from .polymarket_monitor import PolymarketMonitor
from .signal_aggregator import SignalAggregator

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://172.18.0.100:6379")
HEALTH_PORT = int(os.environ.get("INTEL_HEALTH_PORT", "8765"))

REDDIT_POLL_SEC = int(os.environ.get("REDDIT_POLL_SEC", str(15 * 60)))
NEWS_POLL_SEC = int(os.environ.get("NEWS_POLL_SEC", str(10 * 60)))
POLYMARKET_POLL_SEC = int(os.environ.get("POLYMARKET_POLL_SEC", str(5 * 60)))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=(
        '{"time":"%(asctime)s","level":"%(levelname)s",'
        '"logger":"%(name)s","msg":"%(message)s"}'
    ),
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("intel_feeds.runner")

# ---------------------------------------------------------------------------
# Global state (used by health check)
# ---------------------------------------------------------------------------

_start_time = time.time()
_monitor_status: dict[str, str] = {
    "reddit": "starting",
    "news": "starting",
    "polymarket": "starting",
    "aggregator": "starting",
}
_aggregator_ref: SignalAggregator | None = None

# ---------------------------------------------------------------------------
# HTTP Health / Query server (runs in a background thread)
# ---------------------------------------------------------------------------


class IntelHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for health checks and bot queries."""

    def log_message(self, fmt, *args):  # suppress default access logging
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._handle_health()
        elif path == "/sentiment":
            topic = qs.get("topic", [""])[0]
            self._handle_sentiment(topic)
        elif path == "/signals":
            hours = int(qs.get("hours", ["1"])[0])
            min_rel = int(qs.get("min_relevance", ["0"])[0])
            category = qs.get("category", [None])[0]
            self._handle_signals(hours, min_rel, category)
        elif path == "/briefing":
            self._handle_briefing()
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_health(self):
        self._send_json({
            "status": "ok",
            "uptime_sec": round(time.time() - _start_time),
            "monitors": _monitor_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _handle_sentiment(self, topic: str):
        if not topic:
            self._send_json({"error": "topic parameter required"}, 400)
            return
        if _aggregator_ref is None:
            self._send_json({"error": "aggregator not ready"}, 503)
            return
        # Run coroutine from sync context
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_aggregator_ref.query_sentiment(topic))
        finally:
            loop.close()
        self._send_json(result)

    def _handle_signals(self, hours: int, min_relevance: int, category: str | None):
        if _aggregator_ref is None:
            self._send_json({"error": "aggregator not ready"}, 503)
            return
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                _aggregator_ref.get_recent_signals(
                    hours=hours, min_relevance=min_relevance, category=category
                )
            )
        finally:
            loop.close()
        self._send_json({"signals": result, "count": len(result)})

    def _handle_briefing(self):
        if _aggregator_ref is None:
            self._send_json({"error": "aggregator not ready"}, 503)
            return
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_aggregator_ref.get_daily_briefing())
        finally:
            loop.close()
        self._send_json(result)


def start_health_server(port: int = HEALTH_PORT) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), IntelHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health/query server started on port %d", port)
    return server


# ---------------------------------------------------------------------------
# Task wrappers with status tracking
# ---------------------------------------------------------------------------


async def run_reddit(monitor: RedditMonitor) -> None:
    _monitor_status["reddit"] = "running"
    try:
        await monitor.run()
    except asyncio.CancelledError:
        _monitor_status["reddit"] = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001
        _monitor_status["reddit"] = f"error: {exc}"
        logger.error("RedditMonitor crashed: %s", exc, exc_info=True)
        raise


async def run_news(monitor: NewsMonitor) -> None:
    _monitor_status["news"] = "running"
    try:
        await monitor.run()
    except asyncio.CancelledError:
        _monitor_status["news"] = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001
        _monitor_status["news"] = f"error: {exc}"
        logger.error("NewsMonitor crashed: %s", exc, exc_info=True)
        raise


async def run_polymarket(monitor: PolymarketMonitor) -> None:
    _monitor_status["polymarket"] = "running"
    try:
        await monitor.run()
    except asyncio.CancelledError:
        _monitor_status["polymarket"] = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001
        _monitor_status["polymarket"] = f"error: {exc}"
        logger.error("PolymarketMonitor crashed: %s", exc, exc_info=True)
        raise


async def run_aggregator(agg: SignalAggregator) -> None:
    global _aggregator_ref
    _aggregator_ref = agg
    _monitor_status["aggregator"] = "running"
    try:
        await agg.run()
    except asyncio.CancelledError:
        _monitor_status["aggregator"] = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001
        _monitor_status["aggregator"] = f"error: {exc}"
        logger.error("SignalAggregator crashed: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_event: asyncio.Event | None = None


def _handle_os_signal(signum, frame):
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — initiating graceful shutdown", sig_name)
    if _shutdown_event:
        _shutdown_event.set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _main(args: argparse.Namespace) -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # Register OS signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_os_signal)

    logger.info("Intel Feeds starting up — Redis=%s", REDIS_URL)

    # Instantiate monitors
    reddit = RedditMonitor(
        redis_url=REDIS_URL,
        poll_interval=REDDIT_POLL_SEC,
    )
    news = NewsMonitor(
        redis_url=REDIS_URL,
        poll_interval=NEWS_POLL_SEC,
    )
    polymarket = PolymarketMonitor(
        redis_url=REDIS_URL,
        poll_interval=POLYMARKET_POLL_SEC,
    )
    aggregator = SignalAggregator(redis_url=REDIS_URL)

    # Start health server
    health_server = start_health_server(HEALTH_PORT)

    # Launch all tasks
    tasks = [
        asyncio.create_task(run_reddit(reddit), name="reddit"),
        asyncio.create_task(run_news(news), name="news"),
        asyncio.create_task(run_polymarket(polymarket), name="polymarket"),
        asyncio.create_task(run_aggregator(aggregator), name="aggregator"),
        asyncio.create_task(_shutdown_event.wait(), name="shutdown_watcher"),
    ]

    logger.info("All monitors started. Health endpoint: http://0.0.0.0:%d/health", HEALTH_PORT)

    # Wait for shutdown signal OR any task to finish (likely a crash)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in done:
        if task.get_name() != "shutdown_watcher":
            exc = task.exception() if not task.cancelled() else None
            if exc:
                logger.error("Task %s terminated with error: %s", task.get_name(), exc)
            else:
                logger.info("Task %s completed", task.get_name())

    # Graceful shutdown: cancel all remaining tasks
    logger.info("Shutting down remaining tasks...")
    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)

    # Stop monitors explicitly
    reddit.stop()
    news.stop()
    polymarket.stop()
    aggregator.stop()

    health_server.shutdown()
    logger.info("Intel Feeds shutdown complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Intel Feeds — Trading Intelligence Gathering Layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--log-level",
        default=LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: %(default)s)",
    )
    args = parser.parse_args()

    # Apply log level override
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
