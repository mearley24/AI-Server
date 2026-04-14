"""Daily knowledge digest — summarizes what Bob learned today."""

from __future__ import annotations

import logging
import os

from knowledge.ollama_local import ollama_chat
from strategies.llm_completion import completion as llm_complete
from knowledge.query import KnowledgeQuery

logger = logging.getLogger(__name__)


async def generate_daily_digest(anthropic_key: str = None) -> str:
    """Generate a summary of today's learning — Ollama first, Claude Sonnet fallback.

    Args:
        anthropic_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Formatted daily digest string.
    """
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

    logger.warning("using_llm_router_for_daily_digest — Ollama unavailable")
    result = await llm_complete(prompt=prompt, complexity="medium", max_tokens=1024)
    return result.get("content", result.get("text", "Daily digest unavailable — all LLM routes failed."))
