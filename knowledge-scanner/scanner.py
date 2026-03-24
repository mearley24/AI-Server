"""Web search logic using Perplexity API via OpenRouter."""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

PERPLEXITY_API_URL = "https://api.openrouter.ai/api/v1/chat/completions"

# Rate limit: max 10 queries per scan cycle, 5-second delay between queries
MAX_QUERIES_PER_CYCLE = 10
QUERY_DELAY_SECONDS = 5

SCAN_TOPICS = [
    {
        "query": "latest Polymarket prediction market trading strategies edges techniques Reddit",
        "category": "trading",
        "schedule": "every_6h",
    },
    {
        "query": "latest crypto market making strategies DeFi automated trading bots Reddit",
        "category": "trading",
        "schedule": "every_6h",
    },
    {
        "query": "latest smart home automation Control4 Savant Crestron trends innovations 2026",
        "category": "smart_home",
        "schedule": "daily",
    },
    {
        "query": "latest RFID NFC IoT tracking innovations real-time location systems",
        "category": "iot",
        "schedule": "weekly",
    },
    {
        "query": "latest AI agent orchestration frameworks tools multi-agent systems",
        "category": "ai_tools",
        "schedule": "daily",
    },
]


async def scan_topics(api_key: str) -> list[dict]:
    """Run Perplexity queries for all configured topics.

    Returns a list of raw results: [{"query": ..., "category": ..., "response": ...}]
    """
    if not api_key:
        logger.warning("scanning_disabled", reason="PERPLEXITY_API_KEY not set")
        return []

    results: list[dict] = []
    queries_run = 0

    async with httpx.AsyncClient(timeout=30) as http:
        for topic in SCAN_TOPICS:
            if queries_run >= MAX_QUERIES_PER_CYCLE:
                logger.info("scan_rate_limit_reached", queries_run=queries_run)
                break

            if queries_run > 0:
                await asyncio.sleep(QUERY_DELAY_SECONDS)

            try:
                resp = await http.post(
                    PERPLEXITY_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "perplexity/sonar",
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a research assistant scanning for the latest strategies, "
                                    "techniques, and innovations. Provide detailed, actionable findings "
                                    "with specific examples. Focus on what's new in the past 7 days."
                                ),
                            },
                            {"role": "user", "content": topic["query"]},
                        ],
                        "max_tokens": 500,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                queries_run += 1

                content = ""
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")

                if content:
                    results.append({
                        "query": topic["query"],
                        "category": topic["category"],
                        "response": content,
                    })
                    logger.info("scan_topic_complete", category=topic["category"], length=len(content))
                else:
                    logger.warning("scan_topic_empty", category=topic["category"])

            except Exception as exc:
                logger.error("scan_topic_error", category=topic["category"], error=str(exc))

    logger.info("scan_cycle_complete", topics_scanned=queries_run, results=len(results))
    return results
