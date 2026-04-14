"""Cortex Auto-Builder daemon — runs question generation hourly, research continuously."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, "/app")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CORTEX_URL = os.getenv("CORTEX_URL", "http://cortex:8102")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
PORT = int(os.getenv("AUTOBUILDER_PORT", "8115"))
MAX_QUESTIONS_PER_HOUR = int(os.getenv("MAX_QUESTIONS_PER_HOUR", "30"))
GENERATION_INTERVAL_MINUTES = int(os.getenv("GENERATION_INTERVAL_MINUTES", "60"))
SCANNER_ENABLED = os.getenv("SCANNER_ENABLED", "true").lower() not in ("false", "0", "no")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.199:11434")

BACKOFF_BASE_S = 60
BACKOFF_MAX_S = 900

app = FastAPI(title="Cortex Auto-Builder", version="1.0.0")

_questions_this_hour: int = 0
_hour_window_start: float = time.time()
_last_ollama_error: float = 0.0
_current_backoff: float = 0.0
_running = True

# Topic scanner state — last_scanned_at per topic index (epoch 0 = never scanned)
_topic_last_scanned: dict[int, float] = {}
_topic_scan_trigger: asyncio.Event = asyncio.Event()


def _get_redis():
    import redis as _redis
    return _redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3, socket_timeout=5)


def _get_stats() -> dict:
    """Read stats from Redis hash."""
    try:
        r = _get_redis()
        raw = r.hgetall("cortex:autobuilder:stats") or {}
        queue_len = r.llen("cortex:research_queue")
        return {
            "questions_asked": int(raw.get("questions_asked", 0)),
            "questions_answered": int(raw.get("questions_answered", 0)),
            "knowledge_stored": int(raw.get("knowledge_stored", 0)),
            "ollama_calls": int(raw.get("ollama_calls", 0)),
            "errors": int(raw.get("errors", 0)),
            "queue_depth": queue_len,
            "questions_this_hour": _questions_this_hour,
            "max_per_hour": MAX_QUESTIONS_PER_HOUR,
            "current_backoff_s": _current_backoff,
        }
    except Exception as exc:
        return {"error": str(exc)[:100]}


@app.get("/health")
async def health():
    from integrations.cortex_autobuilder.scan_topics import SCAN_TOPICS
    stats = _get_stats()
    topic_schedule = {
        t["query"][:60]: {
            "category": t["category"],
            "frequency_hours": t["frequency_hours"],
            "last_scanned_at": _topic_last_scanned.get(i, 0),
        }
        for i, t in enumerate(SCAN_TOPICS)
    }
    return {
        "status": "ok",
        "service": "cortex-autobuilder",
        "stats": stats,
        "scanning_enabled": SCANNER_ENABLED,
        "topic_schedule": topic_schedule,
    }


@app.get("/stats")
async def stats_endpoint():
    return _get_stats()


@app.get("/scan/topics")
async def scan_topics_endpoint():
    """Return the current topic list with frequency and last-scanned info."""
    from integrations.cortex_autobuilder.scan_topics import SCAN_TOPICS
    return {
        "topics": [
            {
                "index": i,
                "query": t["query"],
                "category": t["category"],
                "frequency_hours": t["frequency_hours"],
                "last_scanned_at": _topic_last_scanned.get(i, 0),
            }
            for i, t in enumerate(SCAN_TOPICS)
        ],
        "scanner_enabled": SCANNER_ENABLED,
    }


@app.post("/scan")
async def scan_endpoint():
    """Manually trigger an immediate scan of all due topics."""
    _topic_scan_trigger.set()
    return {"ok": True, "message": "scan triggered"}


@app.post("/ask")
async def ask_endpoint(body: dict):
    """Manually inject a question into the research queue."""
    question = body.get("question", "").strip()
    if not question:
        return {"error": "question required"}
    category = body.get("category", "trading_strategy")
    priority = min(int(body.get("priority", 8)), 10)
    payload = {
        "question": question,
        "category": category,
        "context": "Manually injected via API",
        "priority": priority,
        "source": "manual_api",
    }
    try:
        r = _get_redis()
        r.lpush("cortex:research_queue", json.dumps(payload))
        return {"ok": True, "queued": payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:100]}


def _rate_limit_ok() -> bool:
    """Check whether we're under the per-hour question limit."""
    global _questions_this_hour, _hour_window_start
    now = time.time()
    if now - _hour_window_start >= 3600:
        _questions_this_hour = 0
        _hour_window_start = now
    return _questions_this_hour < MAX_QUESTIONS_PER_HOUR


def _record_question_asked() -> None:
    global _questions_this_hour
    _questions_this_hour += 1


async def _generation_loop() -> None:
    """Run question generation every GENERATION_INTERVAL_MINUTES."""
    from integrations.cortex_autobuilder.question_generator import QuestionGenerator

    generator = QuestionGenerator(CORTEX_URL, REDIS_URL)
    while _running:
        try:
            logger.info("question_generation_starting")
            questions = await generator.generate_questions()
            logger.info("question_generation_done count=%d", len(questions))
            for _ in questions:
                _record_question_asked()
        except Exception as exc:
            logger.error("question_generation_error error=%s", str(exc)[:200])

        await asyncio.sleep(GENERATION_INTERVAL_MINUTES * 60)


async def _topic_scanner_loop() -> None:
    """Wake every 30 minutes; query each topic whose interval has elapsed."""
    import json as _json
    import httpx as _httpx

    from integrations.cortex_autobuilder.scan_topics import SCAN_TOPICS, SCAN_PROCESS_PROMPT

    async def _query_perplexity(query: str) -> str:
        """Query OpenRouter for a Perplexity search result."""
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            logger.warning("scanner_no_openrouter_key query=%s", query[:60])
            return ""
        try:
            async with _httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "perplexity/llama-3.1-sonar-small-128k-online",
                        "messages": [{"role": "user", "content": query}],
                        "max_tokens": 1024,
                    },
                )
                r.raise_for_status()
                data = r.json()
                return (data["choices"][0]["message"].get("content") or "").strip()
        except Exception as exc:
            logger.warning("scanner_perplexity_error error=%s", str(exc)[:100])
            return ""

    async def _call_ollama_local(prompt: str) -> str:
        """Process text through local Ollama — free, always preferred."""
        try:
            async with _httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                    json={
                        "model": "qwen3:8b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 1024},
                    },
                )
                r.raise_for_status()
                return (r.json().get("response") or "").strip()
        except Exception as exc:
            logger.warning("scanner_ollama_error error=%s", str(exc)[:100])
            return ""

    async def _store_to_cortex(payload: dict) -> bool:
        try:
            async with _httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"{CORTEX_URL}/remember", json=payload)
                return r.status_code in (200, 201)
        except Exception as exc:
            logger.warning("scanner_cortex_store_error error=%s", str(exc)[:100])
            return False

    async def _publish_high_relevance(insight: dict) -> None:
        try:
            r = _get_redis()
            r.publish(
                "notifications:knowledge",
                _json.dumps({
                    "topic": insight.get("topic", ""),
                    "category": insight.get("category", ""),
                    "insight": insight.get("insight", ""),
                    "relevance_score": insight.get("relevance_score", 0),
                }),
            )
        except Exception:
            pass

    while _running:
        if not SCANNER_ENABLED:
            await asyncio.sleep(30)
            continue

        try:
            # Wait up to 30 minutes, but allow early trigger via /scan
            try:
                await asyncio.wait_for(_topic_scan_trigger.wait(), timeout=1800)
                _topic_scan_trigger.clear()
            except asyncio.TimeoutError:
                pass

            now = time.time()
            for i, topic in enumerate(SCAN_TOPICS):
                if not _running:
                    break
                last = _topic_last_scanned.get(i, 0)
                interval_s = topic["frequency_hours"] * 3600
                if now - last < interval_s:
                    continue

                logger.info("scanner_querying topic=%s", topic["query"][:60])

                # 1. Fetch raw search results via Perplexity / OpenRouter
                raw = await _query_perplexity(topic["query"])
                if not raw:
                    logger.warning("scanner_empty_raw topic=%s", topic["query"][:60])
                    _topic_last_scanned[i] = time.time()
                    await asyncio.sleep(5)
                    continue

                # 2. Process through Ollama (free) first; no cloud fallback needed
                process_prompt = f"{SCAN_PROCESS_PROMPT}\n\nRaw search results:\n{raw}"
                processed = await _call_ollama_local(process_prompt)

                if not processed:
                    logger.warning("scanner_ollama_empty topic=%s", topic["query"][:60])
                    _topic_last_scanned[i] = time.time()
                    await asyncio.sleep(5)
                    continue

                # 3. Parse insights JSON
                try:
                    # Strip markdown fences if present
                    cleaned = processed.strip()
                    if cleaned.startswith("```"):
                        cleaned = "\n".join(cleaned.split("\n")[1:])
                    if cleaned.endswith("```"):
                        cleaned = cleaned[: cleaned.rfind("```")]
                    insights = _json.loads(cleaned.strip())
                    if not isinstance(insights, list):
                        insights = [insights]
                except Exception as parse_exc:
                    logger.warning("scanner_parse_error error=%s", str(parse_exc)[:100])
                    insights = []

                # 4. Store each insight in Cortex; publish high-relevance ones
                for insight in insights:
                    relevance = int(insight.get("relevance_score", 0))
                    payload = {
                        "category": insight.get("category", topic["category"]),
                        "title": insight.get("topic", topic["query"])[:80],
                        "content": (
                            f"Insight: {insight.get('insight', '')}\n\n"
                            f"Source: {insight.get('source_summary', '')}\n\n"
                            f"Relevance: {relevance}/10"
                        ),
                        "source": "topic_scanner",
                        "importance": min(relevance, 10),
                        "tags": ["topic_scan", topic["category"]],
                        "confidence": relevance / 10.0,
                    }
                    await _store_to_cortex(payload)
                    if relevance >= 7:
                        await _publish_high_relevance(insight)

                _topic_last_scanned[i] = time.time()
                logger.info(
                    "scanner_done topic=%s insights=%d",
                    topic["query"][:60],
                    len(insights),
                )
                # Rate-limit between queries
                await asyncio.sleep(5)

        except Exception as exc:
            logger.error("topic_scanner_loop_error error=%s", str(exc)[:200])
            await asyncio.sleep(60)


async def _research_loop() -> None:
    """Continuously pop questions from queue and research them."""
    global _last_ollama_error, _current_backoff
    from integrations.cortex_autobuilder.researcher import BettyResearcher

    researcher = BettyResearcher(CORTEX_URL, REDIS_URL)

    while _running:
        if _current_backoff > 0:
            wait = _current_backoff
            logger.info("backoff_sleeping seconds=%.0f", wait)
            await asyncio.sleep(wait)
            _current_backoff = 0.0

        if not _rate_limit_ok():
            logger.info("rate_limit_reached sleeping=60s")
            await asyncio.sleep(60)
            continue

        question = await asyncio.to_thread(researcher.pop_question_sync, 30)
        if question is None:
            continue

        try:
            result = await researcher.research_question(question)
            if result.get("error"):
                err_msg = result["error"]
                if "ollama" in str(err_msg).lower() or "connect" in str(err_msg).lower() or "timeout" in str(err_msg).lower():
                    elapsed = time.time() - _last_ollama_error
                    if elapsed < 300:
                        _current_backoff = min(_current_backoff * 2 if _current_backoff > 0 else BACKOFF_BASE_S, BACKOFF_MAX_S)
                    else:
                        _current_backoff = BACKOFF_BASE_S
                    _last_ollama_error = time.time()
                    logger.warning("ollama_error backoff=%.0f", _current_backoff)
            else:
                _current_backoff = 0.0
                _last_ollama_error = 0.0
                logger.info("research_done question=%s model=%s",
                            result.get("question", "")[:60], result.get("model", ""))
        except Exception as exc:
            logger.error("research_loop_error error=%s", str(exc)[:200])
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_generation_loop())
    asyncio.create_task(_research_loop())
    asyncio.create_task(_topic_scanner_loop())
    logger.info(
        "cortex_autobuilder_started port=%d max_per_hour=%d scanner_enabled=%s",
        PORT, MAX_QUESTIONS_PER_HOUR, SCANNER_ENABLED,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
