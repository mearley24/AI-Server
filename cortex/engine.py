"""CortexEngine — Bob's brain. FastAPI + background loops.

Startup: python -m cortex.engine
Health:  GET  http://localhost:8102/health
Query:   POST http://localhost:8102/query  {"question": "..."}
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from cortex.autonomy import register_autonomy_routes
from cortex.bluebubbles import register_bluebubbles_routes
from cortex.config import CORTEX_LOG_LEVEL, CORTEX_PORT, REDIS_URL
from cortex.dashboard import register_dashboard_routes, register_intel_briefing_routes
from cortex.digest import DigestBuilder
from cortex.goals import GoalTracker
from cortex.improvement import ImprovementLoop
from cortex.memory import MemoryStore
from cortex.migrate import run_migration
from cortex.opportunity import OpportunityScanner

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), CORTEX_LOG_LEVEL, 20)
    )
)
logger = structlog.get_logger(__name__)


def _local_now() -> datetime:
    """Return current time in Mountain Time (UTC-6 standard / UTC-7 MDT)."""
    import time as _time

    if _time.daylight and _time.localtime().tm_isdst:
        utc_offset = -_time.altzone
    else:
        utc_offset = -_time.timezone
    tz = timezone(timedelta(seconds=utc_offset))
    return datetime.now(tz)


# ── Engine ────────────────────────────────────────────────────────────────────


class CortexEngine:
    """Bob's brain — orchestrates memory, goals, improvement, and opportunities."""

    def __init__(self) -> None:
        self.memory = MemoryStore()
        self.goals = GoalTracker(self.memory)
        self.scanner = OpportunityScanner(self.memory)
        self.improver = ImprovementLoop(self.memory, self.goals, self.scanner)
        self.digest = DigestBuilder(self.memory, self.goals)

    async def start(self) -> None:
        """Start the cortex background loops."""
        # Run migration if brain.db is empty
        stats = self.memory.get_stats()
        if stats["total"] == 0:
            logger.info("cortex_migrating", reason="empty brain")
            await run_migration(self.memory)
            stats = self.memory.get_stats()

        # Start background tasks
        asyncio.create_task(self._hourly_loop(), name="cortex_hourly")
        asyncio.create_task(self._daily_loop(), name="cortex_daily")
        asyncio.create_task(self._weekly_loop(), name="cortex_weekly")
        asyncio.create_task(self._redis_listener(), name="cortex_redis")

        logger.info("cortex_started", memories=stats["total"], goals=stats["active_goals"])

    async def _hourly_loop(self) -> None:
        """Run hourly pulse."""
        await asyncio.sleep(60)  # Let startup settle
        while True:
            try:
                await self.improver.run_hourly_pulse()
            except Exception as exc:
                logger.error("cortex_hourly_error", error=str(exc))
            await asyncio.sleep(3600)

    async def _daily_loop(self) -> None:
        """Run daily improvement at 5:30 AM MT."""
        while True:
            now = _local_now()
            target = now.replace(hour=5, minute=30, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info("cortex_daily_scheduled", next_run_in_hours=round(wait_seconds / 3600, 1))
            await asyncio.sleep(wait_seconds)

            try:
                await self.improver.run_daily_improvement()
                await self.digest.build_daily_digest()
            except Exception as exc:
                logger.error("cortex_daily_error", error=str(exc))

    async def _weekly_loop(self) -> None:
        """Run weekly digest on Sunday at 6 AM MT."""
        while True:
            now = _local_now()
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0 and now.hour >= 6:
                days_until_sunday = 7
            target = (now + timedelta(days=days_until_sunday)).replace(
                hour=6, minute=0, second=0, microsecond=0
            )
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                await self.digest.build_weekly_digest()
            except Exception as exc:
                logger.error("cortex_weekly_error", error=str(exc))

    async def _redis_listener(self) -> None:
        """Listen for events from other services and update memory in real-time."""
        while True:
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(REDIS_URL)
                pubsub = r.pubsub()
                await pubsub.psubscribe(
                    "polymarket:*",
                    "intel:*",
                    "notifications:*",
                    "cortex:*",
                )
                logger.info("cortex_redis_subscribed")

                async for msg in pubsub.listen():
                    if msg["type"] not in ("pmessage",):
                        continue
                    try:
                        channel = (
                            msg["channel"].decode()
                            if isinstance(msg["channel"], bytes)
                            else msg["channel"]
                        )
                        raw_data = msg["data"]
                        data = (
                            json.loads(raw_data)
                            if isinstance(raw_data, (str, bytes))
                            else raw_data
                        )
                        await self._process_event(channel, data)
                    except Exception as exc:
                        logger.error(
                            "cortex_event_error",
                            channel=str(msg.get("channel", "")),
                            error=str(exc),
                        )
            except Exception as exc:
                logger.error("cortex_redis_listener_error", error=str(exc))
                await asyncio.sleep(15)  # Back off and reconnect

    async def _process_event(self, channel: str, data: Any) -> None:
        """Route incoming events to the appropriate memory/action."""
        if not isinstance(data, dict):
            return

        if "polymarket:intel_signals" in channel:
            # X intel arrived — store as memory
            self.memory.remember(
                category="x_intel",
                title=data.get("title", "X Signal"),
                content=json.dumps(data),
                source=data.get("url", "x_intake"),
                confidence=data.get("relevance", 50) / 100.0,
                importance=min(10, int(data.get("relevance", 50)) // 10),
                tags=data.get("market_keywords", []),
                ttl_days=7,
            )

        elif "polymarket:volume" in channel:
            # Volume spike — could indicate opportunity
            self.memory.remember(
                category="market_pattern",
                title=f"Volume spike: {data.get('market', 'unknown')}",
                content=json.dumps(data),
                source="volume_monitor",
                importance=6,
                ttl_days=7,
            )

        elif channel == "cortex:learn":
            # External service asking cortex to learn something
            self.memory.remember(
                category=data.get("category", "external_research"),
                title=data.get("title", "External Learning"),
                content=data.get("content", ""),
                source=data.get("source", "external"),
                confidence=data.get("confidence", 0.5),
                importance=data.get("importance", 5),
                tags=data.get("tags", []),
            )

        elif channel == "cortex:query":
            # Another service is querying the cortex — log but don't block
            question = data.get("question", "")
            request_id = data.get("request_id", "")
            if question:
                result = self.query(question, context=data.get("context"))
                # Publish response back (non-blocking best-effort)
                try:
                    import redis.asyncio as aioredis

                    r = aioredis.from_url(REDIS_URL)
                    await r.publish(
                        f"cortex:response:{request_id}",
                        json.dumps(result, default=str),
                    )
                    await r.aclose()
                except Exception:
                    pass

    def query(
        self, question: str, context: dict | None = None
    ) -> dict[str, Any]:
        """Other services call this to ask the cortex a question.

        Returns relevant memories and top rules.
        """
        memories = self.memory.recall(question, limit=10)
        rules = self.memory.get_rules(category="trading_rule", min_confidence=0.6)

        return {
            "question": question,
            "memories": memories[:5],
            "relevant_rules": rules[:5],
            "memory_count": len(memories),
        }


# ── FastAPI ───────────────────────────────────────────────────────────────────

engine: CortexEngine | None = None
app = FastAPI(title="Bob's Cortex", version="1.0.0")

# Register dashboard + operational routes (ported from Mission Control).
# Pass a callable so routes see the live engine after startup.
register_dashboard_routes(app, lambda: engine)
register_intel_briefing_routes(app)
register_bluebubbles_routes(app)
register_autonomy_routes(app)


@app.on_event("startup")
async def _startup() -> None:
    global engine
    engine = CortexEngine()
    await engine.start()
    # Start embedding worker if enabled (gated by CORTEX_EMBEDDINGS_ENABLED)
    from cortex.config import CORTEX_EMBEDDINGS_ENABLED
    if CORTEX_EMBEDDINGS_ENABLED:
        from cortex.embeddings import embed_worker
        from cortex.memory import set_embed_queue
        _eq: asyncio.Queue = asyncio.Queue(maxsize=500)
        set_embed_queue(_eq)
        asyncio.create_task(embed_worker(_eq, engine.memory))


@app.get("/health")
async def health() -> dict[str, Any]:
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    return {"status": "alive", "memories": engine.memory.get_stats()}


@app.post("/query")
async def query(request: dict) -> dict[str, Any]:
    """Ask the cortex a question."""
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    question = request.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    return engine.query(question, context=request.get("context"))


@app.post("/remember")
async def remember(request: dict) -> dict[str, Any]:
    """Tell the cortex to remember something."""
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    required = {"category", "title", "content"}
    missing = required - set(request.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")
    dedupe_hint = request.pop("dedupe_hint", "") or ""
    overwrite_content = bool(request.pop("overwrite_content", False))
    mem_id = engine.memory.store_or_update(
        **request, dedupe_hint=dedupe_hint, overwrite_content=overwrite_content
    )
    return {"id": mem_id}


@app.get("/goals")
async def get_goals() -> list[dict[str, Any]]:
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    return engine.goals.check_goals()


@app.get("/digest/today")
async def today_digest() -> dict[str, Any]:
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    return await engine.digest.build_daily_digest()


@app.get("/memories")
async def list_memories(
    category: str | None = None,
    limit: int = 20,
    q: str = "",
    semantic: int = 0,
) -> list[dict[str, Any]]:
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    keyword_results = engine.memory.recall(q, category=category, limit=limit)
    if not semantic or not q:
        return keyword_results
    # Blend keyword + semantic hits (union by memory_id, rank by weighted sum)
    try:
        sem_hits = await engine.memory.search_semantic(q, k=limit)
        sem_map = {h["memory_id"]: h["score"] for h in sem_hits}
        seen: set = set()
        merged: list[dict[str, Any]] = []
        for row in keyword_results:
            row["semantic_score"] = sem_map.get(row["id"], 0.0)
            seen.add(row["id"])
            merged.append(row)
        # Add semantic-only hits not already in keyword results
        for hit in sem_hits:
            if hit["memory_id"] not in seen:
                extra = engine.memory.conn.execute(
                    "SELECT * FROM memories WHERE id=?", (hit["memory_id"],)
                ).fetchone()
                if extra:
                    row = dict(extra)
                    row["semantic_score"] = hit["score"]
                    merged.append(row)
        merged.sort(key=lambda r: (r.get("importance", 0) * 0.5 + r.get("semantic_score", 0.0) * 5), reverse=True)
        return merged[:limit]
    except Exception:
        return keyword_results


@app.get("/rules")
async def list_rules(min_confidence: float = 0.6) -> list[dict[str, Any]]:
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    return engine.memory.get_rules(category="trading_rule", min_confidence=min_confidence)


@app.post("/improve/run")
async def run_improvement() -> dict[str, Any]:
    """Trigger an immediate improvement cycle (admin use)."""
    if engine is None:
        raise HTTPException(status_code=503, detail="cortex not initialized")
    result = await engine.improver.run_daily_improvement()
    return {
        "status": "complete",
        "lessons": len(result.get("lessons", [])),
        "proposals": len(result.get("proposals", [])),
        "opportunities": len(result.get("opportunities", [])),
    }


# ── Client intelligence (read-only) ───────────────────────────────────────────

_CLIENT_INTEL_DB = Path(os.environ.get("CLIENT_INTEL_DATA_DIR", "/data/client_intel")) / "message_thread_index.sqlite"


@app.get("/api/client-intel/threads", tags=["client-intel"])
async def client_intel_threads(
    category: str = "work",
    min_confidence: float = 0.5,
    limit: int = 50,
) -> dict[str, Any]:
    """Read-only view of classified message threads from the client intel index.

    category — filter by work / personal / mixed / unknown / all
    min_confidence — minimum work_confidence threshold (0.0–1.0)
    limit — max rows to return (capped at 200)
    """
    limit = min(limit, 200)
    db_path = _CLIENT_INTEL_DB
    if not db_path.is_file():
        return {
            "status": "unavailable",
            "message": "Thread index not yet built. Run: python3 scripts/client_intel_backfill.py --dry-run --limit 100",
            "threads": [],
            "count": 0,
        }
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        where = "WHERE work_confidence >= ?"
        params: list[Any] = [min_confidence]
        if category != "all":
            where += " AND category = ?"
            params.append(category)
        rows = conn.execute(
            f"SELECT thread_id, contact_handle, message_count, date_first, date_last, "
            f"category, work_confidence, reason_codes, is_reviewed, created_at "
            f"FROM threads {where} ORDER BY work_confidence DESC, date_last DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        conn.close()
        threads = []
        for r in rows:
            handle = r["contact_handle"]
            masked = handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"
            threads.append({
                "thread_id": r["thread_id"],
                "contact_masked": masked,
                "message_count": r["message_count"],
                "date_first": r["date_first"],
                "date_last": r["date_last"],
                "category": r["category"],
                "work_confidence": r["work_confidence"],
                "reason_codes": json.loads(r["reason_codes"] or "[]"),
                "is_reviewed": r["is_reviewed"],
            })
        return {"status": "ok", "count": len(threads), "threads": threads}
    except Exception as exc:
        logger.warning("client_intel_threads_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "threads": [], "count": 0}


# ── Entrypoint ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    uvicorn.run(
        "cortex.engine:app",
        host="0.0.0.0",
        port=CORTEX_PORT,
        log_level=CORTEX_LOG_LEVEL.lower(),
    )
