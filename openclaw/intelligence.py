"""HTTP API for decision journal, patterns, and design validation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from decision_journal import get_journal
from event_bus import LOG_KEY as EVENTS_LOG_KEY
from pattern_engine import load_patterns

logger = logging.getLogger("openclaw.intelligence")

router = APIRouter(tags=["intelligence"])


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "/app/data"))


@router.get("/intelligence/summary")
async def intelligence_summary():
    data = _data_dir()
    j = get_journal(data)
    return {
        "decisions": j.stats(),
        "weekly": j.get_weekly_summary(),
        "avg_confidence_24h": j.avg_confidence_24h(),
        "patterns": load_patterns(data),
    }


@router.get("/intelligence/decisions/recent")
async def decisions_recent(hours: int = 48, limit: int = 20):
    data = _data_dir()
    j = get_journal(data)
    return {"decisions": j.get_recent(hours=hours, limit=limit)}


@router.get("/intelligence/accuracy")
async def decisions_accuracy(category: str | None = None, days: int = 7):
    data = _data_dir()
    j = get_journal(data)
    return j.get_accuracy(category=category, days=days)


@router.get("/intelligence/events-log")
async def intelligence_events_log(limit: int = Query(30, ge=1, le=200)):
    """Recent durable audit lines from Redis ``events:log`` (LPUSH from orchestrator)."""
    url = os.getenv("REDIS_URL", "")
    if not url:
        return {"key": EVENTS_LOG_KEY, "events": [], "count": 0, "error": "REDIS_URL not set"}

    def _read() -> list[str]:
        import redis as redis_sync

        r = redis_sync.from_url(url, decode_responses=True)
        try:
            return r.lrange(EVENTS_LOG_KEY, 0, limit - 1)
        finally:
            r.close()

    try:
        raw = await asyncio.to_thread(_read)
    except Exception as e:
        logger.debug("events-log: %s", e)
        return {"key": EVENTS_LOG_KEY, "events": [], "count": 0, "error": str(e)[:200]}

    out: list[dict[str, Any]] = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_unparsed": (line or "")[:500]})
    return {"key": EVENTS_LOG_KEY, "events": out, "count": len(out)}


class ValidateBody(BaseModel):
    components: list[dict[str, Any]] = []


@router.post("/intelligence/validate-design")
async def validate_design(body: ValidateBody):
    try:
        from design_validator import DesignValidator

        dv = DesignValidator()
        return dv.validate_components(body.components)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/intelligence/recommend-tv")
async def recommend_tv(budget: float = 5000, min_inches: float = 55):
    try:
        from product_recommender import recommend_tv_room

        return {"recommendations": recommend_tv_room(budget, min_inches)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
