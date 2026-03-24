"""Uses Claude to process raw search results into structured knowledge entries."""

from __future__ import annotations

import json
import os

import httpx
import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Max insights per scan cycle
MAX_INSIGHTS_PER_CYCLE = 20

PROCESS_SYSTEM_PROMPT = """You are a knowledge extraction assistant. Given raw search results, extract actionable insights.

For each distinct insight, return a JSON object with:
- "topic": short topic title (max 80 chars)
- "category": one of: trading, smart_home, iot, ai_tools, business, general
- "insight": the actionable insight (2-3 sentences)
- "source_summary": brief summary of where this info came from
- "relevance_score": 1-10 rating of relevance to a tech entrepreneur running a smart home integration business who also trades crypto and prediction markets

Return a JSON array of objects. Return ONLY valid JSON, no markdown."""


async def process_results(raw_results: list[dict], api_key: str) -> list[dict]:
    """Process raw scan results through Claude to extract structured insights.

    Returns list of knowledge entries ready for storage.
    """
    if not api_key:
        logger.warning("processing_disabled", reason="ANTHROPIC_API_KEY not set")
        return []

    if not raw_results:
        return []

    # Combine all raw results into one processing batch
    combined = "\n\n---\n\n".join(
        f"[Category: {r['category']}]\n{r['response']}" for r in raw_results
    )

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    # Use Haiku for knowledge extraction — it's just categorization,
                    # not creative reasoning. Saves ~90% vs Sonnet.
                    "model": "claude-haiku-3-5-20241022",
                    "max_tokens": 2000,
                    "system": [
                        {
                            "type": "text",
                            "text": PROCESS_SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Extract actionable insights from these research results:\n\n{combined}",
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content = block["text"]
                break

        if not content:
            logger.warning("processor_empty_response")
            return []

        # Parse JSON response — handle markdown wrapping
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines).strip()

        insights = json.loads(content)
        if not isinstance(insights, list):
            insights = [insights]

        # Cap at MAX_INSIGHTS_PER_CYCLE
        insights = insights[:MAX_INSIGHTS_PER_CYCLE]

        logger.info("processing_complete", insights_extracted=len(insights))
        return insights

    except json.JSONDecodeError as exc:
        logger.error("processor_json_error", error=str(exc))
        return []
    except Exception as exc:
        logger.error("processor_error", error=str(exc))
        return []
