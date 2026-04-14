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

BACKOFF_BASE_S = 60
BACKOFF_MAX_S = 900

app = FastAPI(title="Cortex Auto-Builder", version="1.0.0")

_questions_this_hour: int = 0
_hour_window_start: float = time.time()
_last_ollama_error: float = 0.0
_current_backoff: float = 0.0
_running = True


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
    stats = _get_stats()
    return {"status": "ok", "service": "cortex-autobuilder", "stats": stats}


@app.get("/stats")
async def stats_endpoint():
    return _get_stats()


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
    logger.info("cortex_autobuilder_started port=%d max_per_hour=%d", PORT, MAX_QUESTIONS_PER_HOUR)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
