"""Uses LLM to process raw search results into structured knowledge entries.

Routes to Ollama (free, on Maestro) first, falls back to Claude Haiku if unavailable.
"""

from __future__ import annotations

import json
import os

import httpx
import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.189:11434")

try:
    from openclaw.llm_router import completion as _router_completion
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False

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


def _parse_json_response(content: str) -> list[dict]:
    """Parse JSON from LLM response, handling markdown fences."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        content = "\n".join(lines).strip()

    insights = json.loads(content)
    if not isinstance(insights, list):
        insights = [insights]
    return insights[:MAX_INSIGHTS_PER_CYCLE]


async def _process_with_ollama(combined: str) -> list[dict] | None:
    """Try processing with Ollama (free). Returns None on failure."""
    if not OLLAMA_HOST:
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                f"{OLLAMA_HOST.rstrip('/')}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "qwen3:8b",
                    "messages": [
                        {"role": "system", "content": PROCESS_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"Extract actionable insights from these research results:\n\n{combined}",
                        },
                    ],
                    "temperature": 0.3,
                    "stream": False,
                },
            )
            if resp.status_code != 200:
                logger.warning("ollama_processor_error", status=resp.status_code)
                return None

            content = resp.json()["choices"][0]["message"]["content"]
            if not content:
                return None

            insights = _parse_json_response(content)
            logger.info("processing_complete_ollama", insights_extracted=len(insights))
            return insights

    except Exception as exc:
        logger.warning("ollama_processor_failed", error=str(exc))
        return None


async def _process_with_router(combined: str) -> list[dict]:
    """Fallback to central LLM router (Ollama first, cloud fallback, with caching + cost tracking)."""
    if not _HAS_ROUTER:
        logger.warning("llm_router_unavailable", reason="openclaw not mounted")
        return []
    logger.info("using_llm_router_for_processing")
    result = await _router_completion(
        prompt=f"Extract actionable insights from these research results:\n\n{combined}",
        system_prompt=PROCESS_SYSTEM_PROMPT,
        complexity="medium",
        max_tokens=2000,
    )
    content = result.get("content", "")
    if not content:
        logger.warning("processor_empty_response_router")
        return []
    insights = _parse_json_response(content)
    logger.info("processing_complete_router", insights_extracted=len(insights))
    return insights


async def process_results(raw_results: list[dict], api_key: str) -> list[dict]:
    """Process raw scan results through LLM to extract structured insights.

    Tries Ollama first (free, on Maestro), falls back to Claude Haiku.
    Returns list of knowledge entries ready for storage.
    """
    if not api_key and not OLLAMA_HOST:
        logger.warning("processing_disabled", reason="No LLM backend available")
        return []

    if not raw_results:
        return []

    # Combine all raw results into one processing batch
    combined = "\n\n---\n\n".join(
        f"[Category: {r['category']}]\n{r['response']}" for r in raw_results
    )

    try:
        # Try Ollama first (free — runs on Maestro)
        result = await _process_with_ollama(combined)
        if result is not None:
            return result

        # Fallback to central LLM router (caching + cost tracking)
        return await _process_with_router(combined)

    except json.JSONDecodeError as exc:
        logger.error("processor_json_error", error=str(exc))
        return []
    except Exception as exc:
        logger.error("processor_error", error=str(exc))
        return []
