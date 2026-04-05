"""X/Twitter Intake — FastAPI service that analyzes tweet links from iMessage."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys

import httpx
import structlog
import uvicorn
from fastapi import FastAPI

# Ensure package-relative imports work when running as __main__
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = structlog.get_logger(__name__)

PORT = int(os.getenv("PORT", "8101"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")

_TWEET_RE = re.compile(r"https?://(?:x\.com|twitter\.com)/\S+/status/\d+\S*", re.I)

app = FastAPI(title="X Intake", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "x-intake"}


async def _analyze_url(url: str) -> dict:
    """Run the existing pipeline on a single tweet URL."""
    try:
        from post_fetcher import PostFetcher
        from analyzer import PostAnalyzer
    except ImportError:
        try:
            from integrations.x_intake.post_fetcher import PostFetcher
            from integrations.x_intake.analyzer import PostAnalyzer
        except ImportError:
            return {"error": "pipeline modules not importable", "url": url}

    try:
        fetcher = PostFetcher()
        post = fetcher.fetch(url)
        if post is None:
            return {"url": url, "error": "fetch_failed"}
        analyzer = PostAnalyzer()
        result = analyzer.analyze(post)
        return {
            "url": url,
            "author": getattr(post, "author", ""),
            "text": getattr(post, "text", "")[:1000],
            "analysis": {
                "summary": getattr(result, "summary", ""),
                "signals": getattr(result, "signals", []),
                "sentiment": getattr(result, "sentiment", ""),
                "relevance": getattr(result, "relevance_score", 0),
            },
        }
    except Exception as exc:
        logger.warning("analyze_failed", url=url, error=str(exc))
        return {"url": url, "error": str(exc)}


@app.post("/analyze")
async def analyze_endpoint(body: dict):
    """Analyze a single X/Twitter URL."""
    url = body.get("url", "")
    if not url:
        return {"error": "url required"}
    result = await asyncio.to_thread(lambda: asyncio.run(_analyze_url(url)))
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def _send_reply(text: str) -> None:
    """Send analysis result back via iMessage bridge."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{IMESSAGE_BRIDGE_URL}/send", json={"text": text})
    except Exception as exc:
        logger.warning("imessage_send_failed", error=str(exc))


async def _redis_listener() -> None:
    """Subscribe to Redis events:imessage for incoming X/Twitter links."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis not installed — listener disabled")
        return

    while True:
        try:
            client = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe("events:imessage")
            logger.info("redis_listener_started", channel="events:imessage")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"]) if isinstance(message["data"], str) else message["data"]
                    text = data.get("text", "") if isinstance(data, dict) else str(data)
                    urls = _TWEET_RE.findall(text)
                    for url in urls:
                        logger.info("tweet_detected", url=url)
                        result = await _analyze_url(url)
                        summary = result.get("analysis", {}).get("summary", "") if isinstance(result, dict) else ""
                        if summary:
                            await _send_reply(f"X Analysis: {summary}")
                        elif result.get("error"):
                            await _send_reply(f"X Intake error: {result['error']}")
                except Exception as exc:
                    logger.warning("message_process_error", error=str(exc))
        except Exception as exc:
            logger.warning("redis_reconnecting", error=str(exc))
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_redis_listener())
    logger.info("x_intake_started", port=PORT)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
