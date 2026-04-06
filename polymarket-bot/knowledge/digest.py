"""Daily knowledge digest — summarizes what Bob learned today."""

from __future__ import annotations

import logging
import os

import httpx

from knowledge.ollama_local import ollama_chat
from knowledge.query import KnowledgeQuery

logger = logging.getLogger(__name__)


async def generate_daily_digest(anthropic_key: str = None) -> str:
    """Generate a summary of today's learning — Ollama first, Claude Sonnet fallback.

    Args:
        anthropic_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Formatted daily digest string.
    """
    api_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    query = KnowledgeQuery()
    recent = query.get_recent_learnings(days=1)

    if not recent.strip():
        return "No new knowledge ingested today."

    prompt = f"""Summarize today's trading intelligence learnings into a brief daily digest.
Focus on: actionable insights, new patterns discovered, strategy improvements, risk alerts.

Today's learning log:
{recent[:3000]}

Format as a brief daily briefing with sections:
- Key Insights
- Strategy Updates
- Risk Alerts (if any)
- Action Items"""

    local = await ollama_chat(prompt, timeout=90.0)
    if local:
        return local

    if not api_key:
        return "Daily digest unavailable — Ollama unreachable and ANTHROPIC_API_KEY not set."

    logger.warning("using_anthropic_for_daily_digest — Ollama unavailable")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        data = resp.json()
        return data["content"][0]["text"]
