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


# ── Client intelligence ────────────────────────────────────────────────────────
# is_reviewed values:
#   -1 → not yet reviewed (dry-run proposal)
#    0 → rejected (not a client/work thread)
#    1 → approved (confirmed client thread, eligible for profile extraction)

_CLIENT_INTEL_DB = Path(
    os.environ.get("CLIENT_INTEL_DATA_DIR", "/data/client_intel")
) / "message_thread_index.sqlite"

# Host-side fallback (for direct cortex API calls without Docker bind mount)
if not _CLIENT_INTEL_DB.parent.is_dir():
    _CLIENT_INTEL_DB = Path("/Users/bob/AI-Server/data/client_intel") / "message_thread_index.sqlite"


def _client_intel_db_rw() -> sqlite3.Connection | None:
    """Open thread index for read-write. Returns None if DB missing."""
    if not _CLIENT_INTEL_DB.is_file():
        return None
    conn = sqlite3.connect(str(_CLIENT_INTEL_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _client_intel_db_ro() -> sqlite3.Connection | None:
    """Open thread index for read-only. Returns None if DB missing."""
    if not _CLIENT_INTEL_DB.is_file():
        return None
    conn = sqlite3.connect(f"file:{_CLIENT_INTEL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _mask_handle(handle: str) -> str:
    return handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"


VALID_RELATIONSHIP_TYPES = frozenset({
    "client", "vendor", "builder", "trade_partner",
    "internal_team", "personal_work_related", "unknown",
})


def _row_to_thread(r: sqlite3.Row) -> dict[str, Any]:
    keys = {d[0] for d in r.description} if hasattr(r, "description") else set(r.keys())
    return {
        "thread_id": r["thread_id"],
        "contact_masked": _mask_handle(r["contact_handle"]),
        "message_count": r["message_count"],
        "sample_count": r["sample_count"],
        "date_first": r["date_first"],
        "date_last": r["date_last"],
        "category": r["category"],
        "work_confidence": r["work_confidence"],
        "reason_codes": json.loads(r["reason_codes"] or "[]"),
        "is_reviewed": r["is_reviewed"],
        "review_status": {-1: "pending", 0: "rejected", 1: "approved"}.get(
            r["is_reviewed"], "unknown"
        ),
        "relationship_type": r["relationship_type"] if "relationship_type" in keys else "unknown",
    }


@app.get("/api/client-intel/threads", tags=["client-intel"])
async def client_intel_threads(
    category: str = "work",
    min_confidence: float = 0.5,
    reviewed: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """List classified message threads.

    category     — work / personal / mixed / unknown / all
    min_confidence — 0.0–1.0
    reviewed     — all / false (pending, is_reviewed=-1) / true (approved, is_reviewed=1) / rejected
    limit        — capped at 200
    """
    limit = min(limit, 200)
    conn = _client_intel_db_ro()
    if conn is None:
        return {
            "status": "unavailable",
            "message": "Thread index not yet built. Run: python3 scripts/client_intel_backfill.py --dry-run --limit 100",
            "threads": [], "count": 0,
        }
    try:
        clauses: list[str] = ["work_confidence >= ?"]
        params: list[Any] = [min_confidence]
        if category != "all":
            clauses.append("category = ?")
            params.append(category)
        if reviewed == "false":
            clauses.append("is_reviewed = -1")
        elif reviewed == "true":
            clauses.append("is_reviewed = 1")
        elif reviewed == "rejected":
            clauses.append("is_reviewed = 0")
        where = "WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT thread_id, contact_handle, message_count, sample_count, date_first, date_last, "
            f"category, work_confidence, reason_codes, is_reviewed, "
            f"coalesce(relationship_type,'unknown') as relationship_type, created_at "
            f"FROM threads {where} ORDER BY work_confidence DESC, date_last DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        threads = [_row_to_thread(r) for r in rows]
        return {"status": "ok", "count": len(threads), "threads": threads}
    except Exception as exc:
        logger.warning("client_intel_threads_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "threads": [], "count": 0}
    finally:
        conn.close()


@app.post("/api/client-intel/approve-thread", tags=["client-intel"])
async def client_intel_approve_thread(body: dict[str, Any]) -> dict[str, Any]:
    """Approve or reject a classified thread for client profile extraction.

    Body: { "thread_id": "...", "approved": true|false }

    approved=true  → is_reviewed=1 (confirmed client thread)
    approved=false → is_reviewed=0 (rejected, excluded from future processing)

    All approvals are explicit — nothing is auto-approved.
    """
    thread_id = (body or {}).get("thread_id", "").strip()
    approved = (body or {}).get("approved")
    if not thread_id:
        return {"status": "error", "error": "thread_id required"}
    if approved is None:
        return {"status": "error", "error": "approved (true|false) required"}

    conn = _client_intel_db_rw()
    if conn is None:
        return {"status": "error", "error": "Thread index not found"}
    try:
        row = conn.execute(
            "SELECT thread_id, contact_handle, category, work_confidence, is_reviewed, "
            "coalesce(relationship_type,'unknown') as relationship_type "
            "FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return {"status": "error", "error": f"thread_id '{thread_id}' not found"}

        new_status = 1 if approved else 0
        label = "approved" if approved else "rejected"
        conn.execute(
            "UPDATE threads SET is_reviewed = ? WHERE thread_id = ?",
            (new_status, thread_id),
        )
        conn.commit()

        logger.info(
            "client_intel_thread_reviewed",
            thread_id=thread_id,
            contact=_mask_handle(row["contact_handle"]),
            action=label,
            category=row["category"],
            confidence=row["work_confidence"],
        )
        return {
            "status": "ok",
            "thread_id": thread_id,
            "action": label,
            "contact_masked": _mask_handle(row["contact_handle"]),
            "category": row["category"],
            "work_confidence": row["work_confidence"],
            "relationship_type": row["relationship_type"],
            "message": f"Thread {label}. {'Eligible for profile extraction.' if approved else 'Excluded from future processing.'}",
        }
    except Exception as exc:
        logger.warning("client_intel_approve_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


@app.post("/api/client-intel/set-relationship", tags=["client-intel"])
async def client_intel_set_relationship(body: dict[str, Any]) -> dict[str, Any]:
    """Set relationship_type for an approved thread.

    Body: { "thread_id": "...", "relationship_type": "client" }

    Valid types: client | vendor | builder | trade_partner |
                 internal_team | personal_work_related | unknown

    Only applies to approved threads (is_reviewed=1).
    Does not change approval status.
    """
    thread_id = (body or {}).get("thread_id", "").strip()
    rel_type  = (body or {}).get("relationship_type", "").strip().lower()
    if not thread_id:
        return {"status": "error", "error": "thread_id required"}
    if rel_type not in VALID_RELATIONSHIP_TYPES:
        return {
            "status": "error",
            "error": f"Invalid relationship_type '{rel_type}'. "
                     f"Valid: {sorted(VALID_RELATIONSHIP_TYPES)}",
        }
    conn = _client_intel_db_rw()
    if conn is None:
        return {"status": "error", "error": "Thread index not found"}
    try:
        row = conn.execute(
            "SELECT thread_id, contact_handle, is_reviewed FROM threads WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "error": f"thread_id '{thread_id}' not found"}
        if row["is_reviewed"] != 1:
            return {
                "status": "error",
                "error": "relationship_type can only be set on approved threads (is_reviewed=1). "
                         "Approve the thread first via /api/client-intel/approve-thread.",
            }
        conn.execute(
            "UPDATE threads SET relationship_type=? WHERE thread_id=?",
            (rel_type, thread_id),
        )
        conn.commit()
        logger.info(
            "client_intel_relationship_set",
            thread_id=thread_id,
            contact=_mask_handle(row["contact_handle"]),
            relationship_type=rel_type,
        )
        return {
            "status": "ok",
            "thread_id": thread_id,
            "relationship_type": rel_type,
            "contact_masked": _mask_handle(row["contact_handle"]),
        }
    except Exception as exc:
        logger.warning("client_intel_set_relationship_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


@app.get("/api/client-intel/summary", tags=["client-intel"])
async def client_intel_summary() -> dict[str, Any]:
    """Review progress summary — counts by category and review status."""
    conn = _client_intel_db_ro()
    if conn is None:
        return {"status": "unavailable", "counts": {}}
    try:
        rows = conn.execute(
            "SELECT category, is_reviewed, COUNT(*) as n FROM threads GROUP BY category, is_reviewed"
        ).fetchall()
        counts: dict[str, Any] = {}
        for r in rows:
            cat = r["category"]
            rev = {-1: "pending", 0: "rejected", 1: "approved"}.get(r["is_reviewed"], "unknown")
            counts.setdefault(cat, {})[rev] = r["n"]
        pending_work = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE category='work' AND is_reviewed=-1"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=1"
        ).fetchone()[0]
        return {
            "status": "ok",
            "pending_work_review": pending_work,
            "approved_total": approved,
            "counts_by_category": counts,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


# ── Entrypoint ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    uvicorn.run(
        "cortex.engine:app",
        host="0.0.0.0",
        port=CORTEX_PORT,
        log_level=CORTEX_LOG_LEVEL.lower(),
    )
