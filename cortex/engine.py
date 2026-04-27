"""CortexEngine — Bob's brain. FastAPI + background loops.

Startup: python -m cortex.engine
Health:  GET  http://localhost:8102/health
Query:   POST http://localhost:8102/query  {"question": "..."}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
from cortex.dashboard import (
    register_dashboard_routes,
    register_intel_briefing_routes,
    register_process_routes,
)
from cortex.digest import DigestBuilder
from cortex.goals import GoalTracker
from cortex.improvement import ImprovementLoop
from cortex.memory import MemoryStore
from cortex.migrate import run_migration
from cortex.opportunity import OpportunityScanner
from cortex import self_improvement_engine as _si_engine

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
register_process_routes(app)
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

_TRIAGE_STATS_PATH = _CLIENT_INTEL_DB.parent / "triage_stats.json"


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


# ── Relationship Profiles ──────────────────────────────────────────────────────

_PROFILES_DB     = _CLIENT_INTEL_DB.parent / "client_profiles.sqlite"
_FACTS_DB        = _CLIENT_INTEL_DB.parent / "proposed_facts.sqlite"
_BACKFILL_LOG    = _CLIENT_INTEL_DB.parent / "backfill_runs.ndjson"


def _profiles_db_ro() -> sqlite3.Connection | None:
    if not _PROFILES_DB.is_file():
        return None
    conn = sqlite3.connect(f"file:{_PROFILES_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _facts_db_rw() -> sqlite3.Connection | None:
    if not _FACTS_DB.is_file():
        return None
    conn = sqlite3.connect(str(_FACTS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _facts_db_ro() -> sqlite3.Connection | None:
    if not _FACTS_DB.is_file():
        return None
    conn = sqlite3.connect(f"file:{_FACTS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/client-intel/backfill-status", tags=["client-intel"])
async def client_intel_backfill_status() -> dict[str, Any]:
    """Backfill pipeline status — thread counts, review progress, proposed facts."""
    result: dict[str, Any] = {
        "status": "ok",
        "total_indexed": 0,
        "work": 0,
        "mixed": 0,
        "personal": 0,
        "unknown": 0,
        "reviewed": 0,
        "approved_profiles": 0,
        "proposed_facts": 0,
        "last_run": None,
    }

    # Thread index counts
    t_conn = _client_intel_db_ro()
    if t_conn is not None:
        try:
            for row in t_conn.execute(
                "SELECT category, COUNT(*) FROM threads GROUP BY category"
            ).fetchall():
                cat = row[0] or "unknown"
                if cat in result:
                    result[cat] = int(result[cat]) + int(row[1])
                result["total_indexed"] = int(result["total_indexed"]) + int(row[1])
            result["reviewed"] = t_conn.execute(
                "SELECT COUNT(*) FROM threads WHERE is_reviewed=1"
            ).fetchone()[0]
        except Exception as exc:
            result["status"] = "partial"
            result["thread_error"] = str(exc)[:100]
        finally:
            t_conn.close()

    # Approved profiles
    p_conn = _profiles_db_ro()
    if p_conn is not None:
        try:
            result["approved_profiles"] = p_conn.execute(
                "SELECT COUNT(*) FROM profiles WHERE status='approved'"
            ).fetchone()[0]
        except Exception:
            pass
        finally:
            p_conn.close()

    # Pending proposed facts
    f_conn = _facts_db_ro()
    if f_conn is not None:
        try:
            result["proposed_facts"] = f_conn.execute(
                "SELECT COUNT(*) FROM proposed_facts WHERE is_accepted=0 AND is_rejected=0"
            ).fetchone()[0]
        except Exception:
            pass
        finally:
            f_conn.close()

    # Last run timestamp from backfill log
    if _BACKFILL_LOG.is_file():
        try:
            lines = _BACKFILL_LOG.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last = json.loads(lines[-1])
                result["last_run"] = last.get("ts")
        except Exception:
            pass

    return result


# ── Triage endpoints ──────────────────────────────────────────────────────────

_TRIAGE_BUCKETS = frozenset({"high_value", "ambiguous", "low_priority", "hidden_personal"})


def _triage_cols_exist(conn: sqlite3.Connection) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
    return "triage_bucket" in cols


@app.get("/api/client-intel/triage-summary", tags=["client-intel"])
async def client_intel_triage_summary() -> dict[str, Any]:
    """Bucket counts for pending threads. Returns zeros if triage has not been run."""
    conn = _client_intel_db_ro()
    if conn is None:
        return {"status": "unavailable"}
    try:
        result: dict[str, Any] = {
            "status": "ok",
            "high_value": 0, "ambiguous": 0, "low_priority": 0, "hidden_personal": 0,
            "untriaged": 0, "last_triaged": None,
        }
        if not _triage_cols_exist(conn):
            result["untriaged"] = conn.execute(
                "SELECT COUNT(*) FROM threads WHERE is_reviewed=-1"
            ).fetchone()[0]
            return result
        for r in conn.execute(
            "SELECT triage_bucket, COUNT(*) FROM threads "
            "WHERE is_reviewed=-1 AND triage_bucket IS NOT NULL GROUP BY triage_bucket"
        ).fetchall():
            if r[0] in _TRIAGE_BUCKETS:
                result[r[0]] = r[1]
        result["untriaged"] = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=-1 AND triage_bucket IS NULL"
        ).fetchone()[0]
        result["last_triaged"] = conn.execute(
            "SELECT MAX(triaged_at) FROM threads WHERE triaged_at IS NOT NULL"
        ).fetchone()[0]
        # Merge snapshot health stats from sidecar file written by auto_triage
        try:
            if _TRIAGE_STATS_PATH.is_file():
                stats = json.loads(_TRIAGE_STATS_PATH.read_text())
                result["snapshot_used"]          = stats.get("snapshot_used")
                result["snapshot_message_count"] = stats.get("snapshot_message_count")
                result["attributed_body_count"]  = stats.get("attributed_body_count")
                result["readable_sample_count"]  = stats.get("readable_sample_count")
        except Exception:
            pass
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


@app.get("/api/client-intel/review-queue", tags=["client-intel"])
async def client_intel_review_queue(
    bucket: str = "all",
    limit: int = 100,
) -> dict[str, Any]:
    """Triaged pending threads grouped by bucket. Phone numbers are always masked."""
    limit = min(limit, 200)
    if bucket != "all" and bucket not in _TRIAGE_BUCKETS:
        return {"status": "error", "error": f"Unknown bucket: {bucket}. Valid: {sorted(_TRIAGE_BUCKETS)}", "threads": [], "count": 0}
    conn = _client_intel_db_ro()
    if conn is None:
        return {"status": "unavailable", "threads": [], "count": 0}
    try:
        if not _triage_cols_exist(conn):
            return {
                "status": "ok",
                "message": "Triage not yet run. Execute: python3 scripts/auto_triage_client_threads.py --apply",
                "threads": [], "count": 0,
            }
        where_parts = ["is_reviewed = -1", "triage_bucket IS NOT NULL"]
        params: list[Any] = []
        if bucket != "all":
            where_parts.append("triage_bucket = ?")
            params.append(bucket)
        params.append(limit)
        rows = conn.execute(
            "SELECT thread_id, contact_handle, message_count, date_last, category, "
            "work_confidence, triage_bucket, triage_reason, triage_confidence, "
            "review_value_score, "
            "review_reason_summary, review_next_action, evidence_categories, matched_terms, "
            "project_hint, project_confidence, repeat_contact, "
            "previous_thread_count, last_interaction_date, known_relationship, "
            "triage_suggested_relationship, triage_inferred_domain, "
            "triage_risk_flags, triage_contact_display, triaged_at "
            f"FROM threads WHERE {' AND '.join(where_parts)} "
            "ORDER BY review_value_score DESC, triage_confidence DESC LIMIT ?",
            params,
        ).fetchall()
        threads = []
        for r in rows:
            threads.append({
                "thread_id":              r["thread_id"],
                "contact_display":        r["triage_contact_display"] or _mask_handle(r["contact_handle"]),
                "contact_masked":         _mask_handle(r["contact_handle"]),
                "message_count":          r["message_count"],
                "date_last":              (r["date_last"] or "")[:10],
                "category":               r["category"],
                "work_confidence":        r["work_confidence"],
                "triage_bucket":          r["triage_bucket"],
                "triage_reason":          r["triage_reason"],
                "triage_confidence":      r["triage_confidence"],
                "review_value_score":     r["review_value_score"],
                "review_reason_summary":  r["review_reason_summary"],
                "review_next_action":     r["review_next_action"],
                "evidence_categories":    json.loads(r["evidence_categories"] or "[]"),
                "matched_terms":          json.loads(r["matched_terms"] or "[]"),
                "project_hint":           r["project_hint"] or "",
                "project_confidence":     r["project_confidence"] or 0.0,
                "repeat_contact":         bool(r["repeat_contact"]),
                "previous_thread_count":  r["previous_thread_count"] or 0,
                "last_interaction_date":  r["last_interaction_date"] or "",
                "known_relationship":     r["known_relationship"] or "",
                "suggested_relationship": r["triage_suggested_relationship"],
                "inferred_domain":        r["triage_inferred_domain"],
                "risk_flags":             json.loads(r["triage_risk_flags"] or "[]"),
            })
        return {
            "status":                "ok",
            "count":                 len(threads),
            "threads":               threads,
            "active_rules_applied":  _active_rules_summary("triage_scoring"),
        }
    except Exception as exc:
        logger.warning("client_intel_review_queue_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "threads": [], "count": 0}
    finally:
        conn.close()


@app.get("/api/client-intel/profiles", tags=["client-intel"])
async def client_intel_profiles(
    relationship_type: str = "all",
    status: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """List relationship profiles.

    relationship_type — client / vendor / builder / trade_partner /
                        internal_team / personal_work_related / all
    status            — proposed / approved / archived / all
    """
    limit = min(limit, 200)
    conn = _profiles_db_ro()
    if conn is None:
        return {
            "status": "unavailable",
            "message": "Profiles DB not built yet. Run: python3 scripts/extract_relationship_profiles.py --apply-approved",
            "profiles": [], "count": 0,
        }
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if relationship_type != "all":
            clauses.append("relationship_type = ?")
            params.append(relationship_type)
        if status != "all":
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT profile_id, relationship_type, display_name, contact_handle, "
            f"thread_ids, first_seen, last_seen, summary, open_requests, follow_ups, "
            f"systems_or_topics, project_refs, dtools_project_refs, confidence, status, last_updated "
            f"FROM profiles {where} ORDER BY confidence DESC, last_seen DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        profiles = []
        for r in rows:
            profiles.append({
                "profile_id":          r["profile_id"],
                "relationship_type":   r["relationship_type"],
                "display_name":        r["display_name"],
                "contact_masked":      _mask_handle(r["contact_handle"]),
                "thread_ids":          json.loads(r["thread_ids"] or "[]"),
                "first_seen":          r["first_seen"],
                "last_seen":           r["last_seen"],
                "summary":             r["summary"],
                "open_requests":       json.loads(r["open_requests"] or "[]"),
                "follow_ups":          json.loads(r["follow_ups"] or "[]"),
                "systems_or_topics":   json.loads(r["systems_or_topics"] or "[]"),
                "project_refs":        json.loads(r["project_refs"] or "[]"),
                "dtools_project_refs": json.loads(r["dtools_project_refs"] or "[]"),
                "confidence":          r["confidence"],
                "status":              r["status"],
                "last_updated":        r["last_updated"],
            })
        return {"status": "ok", "count": len(profiles), "profiles": profiles}
    except Exception as exc:
        logger.warning("client_intel_profiles_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "profiles": [], "count": 0}
    finally:
        conn.close()


@app.get("/api/client-intel/proposed-facts", tags=["client-intel"])
async def client_intel_proposed_facts(
    profile_id: str = "",
    fact_type: str = "all",
    accepted: str = "pending",
    limit: int = 100,
) -> dict[str, Any]:
    """List proposed facts awaiting approval.

    profile_id — filter by profile (empty = all profiles)
    fact_type  — filter by type (system/request/issue/project_ref/etc) or 'all'
    accepted   — pending (neither accepted nor rejected) / accepted / rejected / all
    """
    limit = min(limit, 500)
    conn = _facts_db_rw()
    if conn is None:
        return {"status": "unavailable", "facts": [], "count": 0}
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if profile_id:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        if fact_type != "all":
            clauses.append("fact_type = ?")
            params.append(fact_type)
        if accepted == "pending":
            clauses.append("is_accepted=0 AND is_rejected=0")
        elif accepted == "accepted":
            clauses.append("is_accepted=1")
        elif accepted == "rejected":
            clauses.append("is_rejected=1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT fact_id, profile_id, thread_id, contact_handle, fact_type, "
            f"fact_value, confidence, source_excerpt, source_timestamp, "
            f"is_accepted, is_rejected, created_at "
            f"FROM proposed_facts {where} "
            f"ORDER BY confidence DESC, created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        facts = [dict(r) for r in rows]
        return {"status": "ok", "count": len(facts), "facts": facts}
    except Exception as exc:
        logger.warning("client_intel_proposed_facts_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "facts": [], "count": 0}
    finally:
        conn.close()


@app.post("/api/client-intel/approve-fact", tags=["client-intel"])
async def client_intel_approve_fact(body: dict[str, Any]) -> dict[str, Any]:
    """Accept a proposed fact — marks it as canonical."""
    fact_id = (body or {}).get("fact_id", "").strip()
    if not fact_id:
        return {"status": "error", "error": "fact_id required"}
    conn = _facts_db_rw()
    if conn is None:
        return {"status": "error", "error": "Facts DB not found"}
    try:
        row = conn.execute("SELECT fact_id, fact_type, fact_value FROM proposed_facts WHERE fact_id=?", (fact_id,)).fetchone()
        if row is None:
            return {"status": "error", "error": f"fact_id '{fact_id}' not found"}
        conn.execute("UPDATE proposed_facts SET is_accepted=1, is_rejected=0 WHERE fact_id=?", (fact_id,))
        conn.commit()
        logger.info("client_intel_fact_accepted fact_id=%s type=%s", fact_id, row["fact_type"])
        return {"status": "ok", "fact_id": fact_id, "fact_type": row["fact_type"], "fact_value": row["fact_value"], "action": "accepted"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


@app.post("/api/client-intel/reject-fact", tags=["client-intel"])
async def client_intel_reject_fact(body: dict[str, Any]) -> dict[str, Any]:
    """Reject a proposed fact — excludes it from canonical profile."""
    fact_id = (body or {}).get("fact_id", "").strip()
    if not fact_id:
        return {"status": "error", "error": "fact_id required"}
    conn = _facts_db_rw()
    if conn is None:
        return {"status": "error", "error": "Facts DB not found"}
    try:
        row = conn.execute("SELECT fact_id, fact_type, fact_value FROM proposed_facts WHERE fact_id=?", (fact_id,)).fetchone()
        if row is None:
            return {"status": "error", "error": f"fact_id '{fact_id}' not found"}
        conn.execute("UPDATE proposed_facts SET is_rejected=1, is_accepted=0 WHERE fact_id=?", (fact_id,))
        conn.commit()
        logger.info("client_intel_fact_rejected fact_id=%s type=%s", fact_id, row["fact_type"])
        return {"status": "ok", "fact_id": fact_id, "fact_type": row["fact_type"], "fact_value": row["fact_value"], "action": "rejected"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        conn.close()


@app.get("/api/client-intel/profiles/{profile_id}", tags=["client-intel"])
async def client_intel_profile_detail(profile_id: str) -> dict[str, Any]:
    """Return a single profile with its proposed facts grouped by fact_type.

    Includes all facts (pending, accepted, rejected) so the operator can review
    the full picture. Each fact includes value, confidence, source_excerpt,
    source_timestamp, and review state.
    """
    p_conn = _profiles_db_ro()
    if p_conn is None:
        return {"status": "unavailable", "message": "Profiles DB not built yet.", "profile": None, "facts_by_type": {}}
    f_conn = None
    try:
        f_conn = _facts_db_ro()
        row = p_conn.execute(
            "SELECT profile_id, relationship_type, display_name, contact_handle, "
            "thread_ids, first_seen, last_seen, summary, open_requests, follow_ups, "
            "systems_or_topics, project_refs, dtools_project_refs, confidence, status, last_updated "
            "FROM profiles WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "error": f"profile '{profile_id}' not found", "profile": None, "facts_by_type": {}}

        profile = {
            "profile_id":          row["profile_id"],
            "relationship_type":   row["relationship_type"],
            "display_name":        row["display_name"],
            "contact_masked":      _mask_handle(row["contact_handle"]),
            "thread_ids":          json.loads(row["thread_ids"] or "[]"),
            "first_seen":          row["first_seen"],
            "last_seen":           row["last_seen"],
            "summary":             row["summary"],
            "open_requests":       json.loads(row["open_requests"] or "[]"),
            "follow_ups":          json.loads(row["follow_ups"] or "[]"),
            "systems_or_topics":   json.loads(row["systems_or_topics"] or "[]"),
            "project_refs":        json.loads(row["project_refs"] or "[]"),
            "dtools_project_refs": json.loads(row["dtools_project_refs"] or "[]"),
            "confidence":          row["confidence"],
            "status":              row["status"],
            "last_updated":        row["last_updated"],
        }

        facts_by_type: dict[str, list[dict]] = {}
        if f_conn is not None:
            fact_rows = f_conn.execute(
                "SELECT fact_id, thread_id, fact_type, fact_value, confidence, "
                "source_excerpt, source_timestamp, is_accepted, is_rejected, created_at "
                "FROM proposed_facts WHERE profile_id=? "
                "ORDER BY fact_type, confidence DESC, created_at DESC",
                (profile_id,),
            ).fetchall()
            for fr in fact_rows:
                ftype = fr["fact_type"]
                facts_by_type.setdefault(ftype, []).append({
                    "fact_id":          fr["fact_id"],
                    "thread_id":        fr["thread_id"],
                    "fact_type":        ftype,
                    "fact_value":       fr["fact_value"],
                    "confidence":       fr["confidence"],
                    "source_excerpt":   fr["source_excerpt"],
                    "source_timestamp": fr["source_timestamp"],
                    "is_accepted":      fr["is_accepted"],
                    "is_rejected":      fr["is_rejected"],
                    "created_at":       fr["created_at"],
                })

        return {"status": "ok", "profile": profile, "facts_by_type": facts_by_type}
    except Exception as exc:
        logger.warning("client_intel_profile_detail_error profile_id=%s err=%s", profile_id, exc)
        return {"status": "error", "error": str(exc)[:200], "profile": None, "facts_by_type": {}}
    finally:
        p_conn.close()
        if f_conn is not None:
            f_conn.close()


# ── Context card helpers ───────────────────────────────────────────────────────

_X_INTAKE_DATA_DIR = Path(os.environ.get("X_INTAKE_DATA_DIR", "/data/x_intake"))
if not _X_INTAKE_DATA_DIR.is_dir():
    _X_INTAKE_DATA_DIR = Path("/Users/bob/AI-Server/data/x_intake")

_TASK_RUNNER_DIR = Path(os.environ.get("TASK_RUNNER_DATA_DIR", "/data/task_runner"))
if not _TASK_RUNNER_DIR.is_dir():
    _TASK_RUNNER_DIR = Path("/Users/bob/AI-Server/data/task_runner")

_WATCHDOG_STATE_DIR = _TASK_RUNNER_DIR / "bob-watchdog-state"
_WATCHDOG_HEARTBEAT  = _TASK_RUNNER_DIR / "bob_watchdog_heartbeat.txt"

# Cortex reads receipts from x_intake (read-only mount); must not write there.
_RECEIPT_LOG = _X_INTAKE_DATA_DIR / "reply_receipts.ndjson"

# Cortex-owned writable data dir for approval records and dry-run receipts.
# /data/cortex is bind-mounted rw; /data/x_intake is ro for this container.
_CORTEX_DATA_DIR = Path(os.environ.get("CORTEX_DATA_DIR", "/data/cortex"))
if not _CORTEX_DATA_DIR.is_dir():
    _CORTEX_DATA_DIR = Path("/Users/bob/AI-Server/data/cortex")

_APPROVAL_LOG_PATH   = _CORTEX_DATA_DIR / "reply_approvals.ndjson"
_DRY_RUN_RECEIPT_LOG = _CORTEX_DATA_DIR / "reply_receipts_dry_run.ndjson"


def _handle_from_guid(guid: str) -> str:
    """Extract E.164 phone from 'any;-;+13035257532' or 'iMessage;-;+13035257532'."""
    import re as _re
    m = _re.search(r"(\+?1?\d{10,15})$", guid)
    return m.group(1) if m else ""


def _normalize_handle(raw: str) -> str:
    """Strip whitespace; add leading + if missing from a digit string."""
    h = raw.strip()
    if h and h[0].isdigit():
        h = "+" + h
    return h


def _lookup_contact_handle(thread_guid: str, contact_handle: str) -> str:
    """Resolve the canonical E.164 contact handle from either input.

    Priority: explicit contact_handle > thread_guid extraction > thread_index lookup.
    Returns empty string if nothing found.
    """
    if contact_handle:
        return _normalize_handle(contact_handle)
    if thread_guid:
        extracted = _handle_from_guid(thread_guid)
        if extracted:
            return _normalize_handle(extracted)
        # Fall back to thread index lookup by chat_guid
        conn = _client_intel_db_ro()
        if conn:
            try:
                row = conn.execute(
                    "SELECT contact_handle FROM threads WHERE chat_guid=? LIMIT 1",
                    (thread_guid,),
                ).fetchone()
                if row:
                    return _normalize_handle(row["contact_handle"])
            except Exception:
                pass
            finally:
                conn.close()
    return ""


def _profile_by_handle(handle: str) -> dict | None:
    """Look up the best matching profile for a contact handle. Returns None if not found."""
    conn = _profiles_db_ro()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT profile_id, relationship_type, display_name, contact_handle, "
            "thread_ids, first_seen, last_seen, summary, open_requests, follow_ups, "
            "systems_or_topics, project_refs, dtools_project_refs, confidence, status, last_updated "
            "FROM profiles WHERE contact_handle=? "
            "ORDER BY confidence DESC LIMIT 1",
            (handle,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _facts_for_profile(profile_id: str) -> list[dict]:
    """Return all (non-rejected) proposed facts for a profile."""
    conn = _facts_db_ro()
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT fact_id, thread_id, fact_type, fact_value, confidence, "
            "source_excerpt, source_timestamp, is_accepted, is_rejected "
            "FROM proposed_facts WHERE profile_id=? AND is_rejected=0 "
            "ORDER BY is_accepted DESC, confidence DESC",
            (profile_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _receipts_for_handle(handle: str, limit: int = 5) -> list[dict]:
    """Return recent reply receipts matching this contact (by last-4 digits).

    Receipts are already redacted; we match on phone_last4 only.
    Never raises — caller must not crash on missing receipt log.
    """
    if not _RECEIPT_LOG.is_file():
        return []
    last4 = handle[-4:] if len(handle) >= 4 else ""
    if not last4:
        return []
    results: list[dict] = []
    try:
        lines = _RECEIPT_LOG.read_text(errors="replace").splitlines()
        for line in reversed(lines[-200:]):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if last4 in entry.get("phone_last4", ""):
                # Re-mask: strip any residual thread_guid that may have been logged
                entry.pop("thread_guid", None)
                results.append(entry)
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


# ── Reply quality helpers ──────────────────────────────────────────────────────

# Safe fallback used whenever source facts are too messy to produce clean text.
SAFE_FALLBACK_REPLY = "Thanks for the heads up — I'll take a look and get back to you shortly."

# Speech-fragment patterns that disqualify a fact value from direct injection.
# These indicate the value is a raw client transcript, not a clean descriptor.
_SPEECH_FRAGMENT_RE = re.compile(
    r"""
    \bgive\s+me\b   |   # "give me call"
    \bcall\s+me\b   |   # "call me back"
    \bas\s+am\b     |   # "as am trying"
    \bam\s+trying\b |   # "I am trying to"
    \bas\s+soon\s+as\b |
    \bneed\s+to\s+reach\b |
    \btrying\s+to\s+setup\b |
    \btrying\s+to\s+get\b |
    \bI\s+am\b      |   # first-person client fragment
    \bI'll\b        |   # client writing "I'll ..."
    \bI\s+need\b    |   # "I need..."
    \bI\s+want\b    |   # "I want..."
    \bwe\s+need\b
    """,
    re.I | re.VERBOSE,
)

# Post-generation quality checks: patterns that should never appear in a
# client-facing draft reply.
_DRAFT_QUALITY_CHECKS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sounds\s+like\s+give\b", re.I),          "fragment: 'sounds like give...'"),
    (re.compile(r"sounds\s+like\s+call\b", re.I),          "fragment: 'sounds like call...'"),
    (re.compile(r"sounds\s+like\s+get\b", re.I),           "fragment: 'sounds like get...'"),
    (re.compile(r"sounds\s+like\s+\w+\s+me\b", re.I),      "fragment: 'sounds like {verb} me'"),
    (re.compile(r"\bgive\s+me\s+call\b", re.I),            "speech fragment: 'give me call'"),
    (re.compile(r"\bas\s+am\s+trying\b", re.I),            "speech fragment: 'as am trying'"),
    (re.compile(r"\bam\s+trying\s+to\b", re.I),            "speech fragment: 'am trying to'"),
    (re.compile(r"\bas\s+soon\s+as\s+you\s+can\b", re.I),  "speech fragment: 'as soon as you can'"),
    (re.compile(r"\bneed\s+to\s+reach\b", re.I),           "speech fragment: 'need to reach'"),
    (re.compile(r"\bI'll\s+take\s+a\s+look.*sounds\s+like\s+[a-z]", re.I),
                                                            "stitched: verb fragment after 'sounds like'"),
]


def _is_clean_for_injection(text: str) -> bool:
    """Return True if a fact value is safe to use verbatim in a client-facing reply.

    Fact values extracted from iMessage content are often raw speech fragments
    ("give me call as soon as you can...") rather than clean descriptors.
    Equipment and system names (Sonos, WiFi, Lutron) are always safe.
    Short action phrases under 8 words with no speech-fragment markers are safe.
    """
    t = text.strip()
    if not t:
        return False
    # Equipment/brand names are always clean even when short
    if re.match(
        r"^(sonos|lutron|control4|araknis|wattbox|episode|triad|pakedge|snapav|vantage|"
        r"wifi|wi-fi|network|theater|alarm|camera|shade|keypad|dimmer|lighting|audio|rack)$",
        t, re.I,
    ):
        return True
    # Too many words → likely a speech transcript
    if len(t.split()) > 8:
        return False
    # Known speech-fragment patterns
    if _SPEECH_FRAGMENT_RE.search(t):
        return False
    # OCR/decoder artifacts
    if re.search(r"\b(iI|lI|Il|Ii|oO|O0|0O)\b", t):
        return False
    return True


def _check_draft_quality(draft: str) -> tuple[str, list[str]]:
    """Post-generation quality check.

    Returns (status, reasons):
      status  — 'pass' | 'blocked'
      reasons — list of quality issues found
    """
    reasons: list[str] = []
    for pattern, reason in _DRAFT_QUALITY_CHECKS:
        if pattern.search(draft):
            reasons.append(reason)
    # Repeated consecutive words (decoder artifact)
    words = re.findall(r"\b\w{4,}\b", draft.lower())
    for i in range(len(words) - 1):
        if words[i] == words[i + 1]:
            reasons.append(f"repeated word: '{words[i]}'")
            break
    return ("blocked" if reasons else "pass"), reasons


# ── System capability map ──────────────────────────────────────────────────────
# Maps normalised equipment/system names to what kind of help is appropriate.
#   self_fix : str | None  — one safe client-side step (power cycle, reboot)
#   remote   : bool        — can Bob check/fix this without being on-site?
#   on_site  : bool        — does this typically require a visit?
#
# Rules for self_fix entries:
#   - Must be safe for any client to do (no wiring, no admin passwords required)
#   - One step only — no lists
#   - Plain English, no jargon
_SYSTEM_CAPABILITY: dict[str, dict] = {
    "sonos":       {"self_fix": "try unplugging it for about 10 seconds and plugging it back in",
                    "remote": False, "on_site": True},
    "audio":       {"self_fix": "try unplugging it for about 10 seconds and plugging it back in",
                    "remote": False, "on_site": True},
    "wifi":        {"self_fix": "try rebooting your router real quick",
                    "remote": True,  "on_site": True},
    "wif":         {"self_fix": "try rebooting your router real quick",     # "wi-fi" normalised
                    "remote": True,  "on_site": True},
    "network":     {"self_fix": "try rebooting your router real quick",
                    "remote": True,  "on_site": True},
    "araknis":     {"self_fix": "try rebooting the router",
                    "remote": True,  "on_site": True},
    "pakedge":     {"self_fix": "try rebooting the router",
                    "remote": True,  "on_site": True},
    "wattbox":     {"self_fix": None,
                    "remote": True,  "on_site": True},
    "control4":    {"self_fix": None,
                    "remote": True,  "on_site": True},
    "lutron":      {"self_fix": None,
                    "remote": True,  "on_site": True},
    "vantage":     {"self_fix": None,
                    "remote": True,  "on_site": True},
    "snapav":      {"self_fix": None,
                    "remote": True,  "on_site": True},
    "camera":      {"self_fix": "try power cycling the camera",
                    "remote": True,  "on_site": True},
    "alarm":       {"self_fix": None,
                    "remote": True,  "on_site": True},
    "theater":     {"self_fix": "try turning everything off and back on",
                    "remote": False, "on_site": True},
    "lighting":    {"self_fix": None,
                    "remote": True,  "on_site": True},
    "shade":       {"self_fix": None,
                    "remote": True,  "on_site": True},
}


def _system_cap(eq_name: str) -> dict:
    """Return capability entry for an equipment/system name.

    Matches by substring: 'Sonos Arc' → 'sonos' entry, 'Wi-Fi' → 'wifi' entry.
    Returns a neutral no-assumption entry when nothing matches.
    """
    key = re.sub(r"[\s\-_]", "", eq_name.lower())   # "wi-fi" → "wifi"
    for name, cap in _SYSTEM_CAPABILITY.items():
        if name in key or key.startswith(name):
            return cap
    # Unknown system — neutral defaults
    return {"self_fix": None, "remote": False, "on_site": True}


def _personalise_fix(fix: str, eq: str) -> str:
    """Replace the first 'it' in a self-fix phrase with 'your {eq}'.

    'try unplugging it for 10 seconds' → 'try unplugging your Sonos for 10 seconds'
    Phrases that don't contain standalone 'it' are returned unchanged.
    """
    return re.sub(r"\bit\b", f"your {eq}", fix, count=1)


def _build_draft_with_context(
    profile: dict,
    accepted_by_type: dict[str, list[dict]],
    unverified_by_type: dict[str, list[dict]],
    recent_replies: list[dict],
    last_message: str = "",
    behavior_hints: "dict | None" = None,
) -> dict[str, Any]:
    """Build a draft reply with reasoning, confidence, source_facts, and quality status.

    Priority order:
      1. Accepted issue + equipment facts  → proactive service draft
      2. Accepted issue only               → generic proactive draft
      3. Accepted request + equipment      → equipment check-in (req goes to reasoning only)
      4. Open requests from profile        → safe draft using system name if clean
      5. Accepted equipment / system       → personal check-in
      6. Unverified issue / request        → cautious draft
      7. Relationship-type fallback
    Quality gates:
      - _is_clean_for_injection() applied before any fact value enters draft text
      - _check_draft_quality() run on final draft; blocked drafts replaced with SAFE_FALLBACK_REPLY
      - confidence downgraded when source facts are messy
    behavior_hints — optional dict from _si_engine.apply_reply_hints(); influences
      draft selection. Silently ignored if missing or malformed.
    """
    _hints = behavior_hints or {}
    rel_type = profile.get("relationship_type", "unknown")
    open_reqs = profile.get("open_requests", [])
    systems   = profile.get("systems_or_topics", [])

    accepted_issues   = [f["fact_value"] for f in accepted_by_type.get("issue", [])]
    accepted_requests = [f["fact_value"] for f in accepted_by_type.get("request", [])]
    accepted_equip    = [
        f["fact_value"]
        for f in accepted_by_type.get("equipment", []) + accepted_by_type.get("system", [])
    ]
    unverified_issues   = [f["fact_value"] for f in unverified_by_type.get("issue", [])]
    unverified_requests = [f["fact_value"] for f in unverified_by_type.get("request", [])]

    source_facts: list[dict] = []
    reasoning_parts: list[str] = []

    def _record(ftype: str, val: str, verified: bool) -> None:
        source_facts.append({"fact_type": ftype, "fact_value": val[:80], "verified": verified})

    for f in accepted_by_type.get("issue", [])[:2]:
        _record("issue", f["fact_value"], True)
    for f in accepted_by_type.get("request", [])[:2]:
        _record("request", f["fact_value"], True)
    for f in (accepted_by_type.get("equipment", []) + accepted_by_type.get("system", []))[:3]:
        _record(f["fact_type"], f["fact_value"], True)
    for f in (unverified_by_type.get("issue", []) + unverified_by_type.get("request", []))[:2]:
        _record(f["fact_type"], f["fact_value"], False)

    # ── Draft selection ───────────────────────────────────────────────────────
    # Rules:
    #   - With prior issue history → acknowledge it, propose proactive action.
    #     Do NOT ask "when did it start" or "let me know your availability."
    #   - Fact values are NEVER injected verbatim unless _is_clean_for_injection()
    #     returns True. Messy fragments go into reasoning only.
    #   - Diagnostic questions only when no history exists and cause is ambiguous.
    #   - Tone: confident, personal, direct — sounds like someone who knows the system.
    draft: str
    confidence: float
    quality_downgraded = False  # set True when source facts are too messy to use

    repeat_issue = len(accepted_issues) > 1   # recurring pattern

    if accepted_issues and accepted_equip:
        # Equipment name is always safe. Issue text goes to reasoning only.
        eq    = accepted_equip[0]
        issue = accepted_issues[0][:80]
        cap   = _system_cap(eq)
        fix   = cap["self_fix"]
        can_remote = cap["remote"]

        if repeat_issue:
            if fix:
                _p = _personalise_fix(fix, eq)
                _p = _p[0].upper() + _p[1:]   # capitalise first letter only
                draft = (
                    f"I see this has come up a couple times now with your {eq}. "
                    f"{_p} — if that doesn't do it this time, I'll swing by."
                )
            else:
                draft = (
                    f"I see this has happened before with your {eq}. "
                    f"I'll dig in and get to the bottom of it — I'll let you know what I find."
                )
        else:
            # First reported issue — suggest the simplest fix first, then next step.
            if fix and can_remote:
                draft = (
                    f"Got it — {_personalise_fix(fix, eq)}. "
                    f"If that doesn't sort it, I'll check remotely and let you know."
                )
            elif fix:
                draft = (
                    f"Got it — {_personalise_fix(fix, eq)}. "
                    f"If it's still acting up after that, I can swing by and take a look."
                )
            elif can_remote:
                draft = (
                    f"Got it — I'll check on your {eq} remotely. "
                    f"Give me a few minutes and I'll let you know what I find."
                )
            else:
                draft = (
                    f"On it — I'll check your {eq} and see what's going on. "
                    f"I'll let you know what I find."
                )
        reasoning_parts += [
            f"{'Recurring' if repeat_issue else 'Active'} issue: '{issue}'",
            f"Equipment on file: '{eq}'",
            f"Self-fix available: {bool(fix)}",
            f"Remote access: {can_remote}",
        ]
        confidence = 0.90

    elif accepted_issues:
        draft = "Got it — I'll look into this and get back to you with what I find."
        reasoning_parts.append(f"Active issue: '{accepted_issues[0][:80]}'")
        confidence = 0.85

    elif accepted_requests and accepted_equip:
        # Raw request text may be a speech fragment — never inject directly.
        # Equipment name is clean; request context goes to reasoning only.
        # Even with a messy request, apply the capability map so equipment-specific
        # wording (self-fix, remote) is used rather than a generic fallback.
        req = accepted_requests[0][:70]
        eq  = accepted_equip[0]
        cap = _system_cap(eq)
        fix = cap["self_fix"]
        can_remote = cap["remote"]
        if not _is_clean_for_injection(req):
            quality_downgraded = True
            reasoning_parts.append(f"Request (messy, not injected): '{req}'")
        else:
            reasoning_parts.append(f"Request: '{req}'")
        reasoning_parts.append(f"Equipment: '{eq}'")
        # Pick wording based on capability, not on whether the request was clean.
        # Mirror the issue-branch logic: self-fix + remote → try then remote;
        # self-fix only → try then on-site; remote only → remote; neutral fallback.
        if fix and can_remote:
            draft = (
                f"Got it — {_personalise_fix(fix, eq)}. "
                f"If that doesn't sort it, I'll check remotely and let you know."
            )
        elif fix:
            draft = (
                f"Got it — {_personalise_fix(fix, eq)}. "
                f"If it's still acting up after that, I can swing by and take a look."
            )
        elif can_remote:
            draft = f"Got it — I'll take a look at your {eq} remotely and let you know what I find."
        else:
            draft = f"On it — I'll check your {eq} and let you know what I find."
        confidence = 0.85 if not quality_downgraded else 0.65

    elif open_reqs:
        # open_reqs values are accepted request facts — check before injecting.
        req = open_reqs[0][:80]
        if _is_clean_for_injection(req):
            # Use system name if available rather than injecting the req text.
            if systems:
                draft = f"I'm on it — I'll check on your {systems[0]} and sort this out."
            else:
                draft = "I'm on it — I'll sort this out and get back to you."
            reasoning_parts.append(f"Open request: '{req}'")
        else:
            draft = SAFE_FALLBACK_REPLY
            quality_downgraded = True
            reasoning_parts.append(f"Open request (messy, not injected): '{req}'")
        confidence = 0.75 if not quality_downgraded else 0.55

    elif accepted_equip:
        # Equipment on file but no accepted issue or request.
        # Apply the same capability-aware wording as the issue/request branches
        # so Sonos → self-fix, network → remote, unknown → neutral check-in.
        eq  = accepted_equip[0]
        cap = _system_cap(eq)
        fix = cap["self_fix"]
        can_remote = cap["remote"]
        if fix and can_remote:
            draft = (
                f"Got it — {_personalise_fix(fix, eq)}. "
                f"If that doesn't sort it, I'll check remotely and let you know."
            )
        elif fix:
            draft = (
                f"Got it — {_personalise_fix(fix, eq)}. "
                f"If it's still acting up after that, I can swing by and take a look."
            )
        elif can_remote:
            draft = (
                f"Got it — I'll check on your {eq} remotely. "
                f"Give me a few minutes and I'll let you know what I find."
            )
        else:
            draft = f"Checking in on your {eq} — everything holding up okay?"
        reasoning_parts.append(f"Equipment on file: '{eq}'")
        confidence = 0.70

    elif systems:
        sys_name = systems[0]
        draft = f"Hey, checking in on your {sys_name} — anything I can help with?"
        reasoning_parts.append(f"System from profile: '{sys_name}'")
        confidence = 0.65

    elif unverified_issues:
        # Unverified facts — cautious, check before injecting issue text.
        issue = unverified_issues[0][:80]
        if _is_clean_for_injection(issue):
            draft = (
                f"Hey, just checking in — still having trouble with {issue}? "
                f"Happy to take a look."
            )
        else:
            draft = "Hey, checking in — everything going okay with your system?"
            quality_downgraded = True
            reasoning_parts.append(f"Unverified issue (messy, not injected): '{issue}'")
        if not quality_downgraded:
            reasoning_parts.append(f"Unverified issue (pending approval): '{issue}'")
        confidence = 0.50

    elif rel_type == "client" and not (open_reqs or systems):
        # No history — only situation where a clarifying question is appropriate.
        draft = "Hi, thanks for reaching out — what's going on?"
        reasoning_parts.append("No prior facts — open question appropriate")
        confidence = 0.30

    elif rel_type == "vendor":
        draft = "Hey, following up — what's the latest on availability and lead time?"
        reasoning_parts.append("Vendor relationship — follow-up")
        confidence = 0.45

    elif rel_type in ("builder", "trade_partner"):
        draft = "Just checking in on scheduling — where are things at on your end?"
        reasoning_parts.append(f"Relationship type: {rel_type}")
        confidence = 0.45

    else:
        draft = "Hi, thanks for reaching out — what can I help you with?"
        reasoning_parts.append("No specific facts — open question")
        confidence = 0.30

    # Last-message context as reasoning annotation only (never injected into draft)
    if last_message and len(last_message) > 10:
        reasoning_parts.append(f"Last message: \"{last_message[:80].strip()}\"")

    # Recent-reply annotation
    if recent_replies:
        ts = recent_replies[0].get("ts", "")[:10]
        reasoning_parts.append(f"Last reply logged: {ts}")

    # Cap confidence when unverified facts are the primary signal
    if unverified_by_type and not accepted_by_type and confidence > 0.55:
        confidence = 0.55

    # ── Post-generation quality gate ──────────────────────────────────────────
    quality_status, quality_reasons = _check_draft_quality(draft)
    if quality_status == "blocked":
        # Something slipped through the injection guards — use safe fallback.
        quality_reasons.append("post-generation check caught fragment; replaced with safe fallback")
        draft = SAFE_FALLBACK_REPLY
        quality_status = "fallback"
        quality_downgraded = True
    elif quality_downgraded:
        quality_status = "fallback"

    if quality_downgraded:
        confidence = round(min(confidence, 0.60), 2)

    # Log applied rules if any behavior hints came from the rule engine
    if _hints.get("_rule_id"):
        _si_engine.log_applied_rules([_hints["_rule_id"]], context="reply_draft")

    return {
        "draft_reply":           draft,
        "reasoning":             "; ".join(reasoning_parts) or "No facts available.",
        "confidence":            round(confidence, 2),
        "source_facts":          source_facts[:8],
        "draft_quality_status":  quality_status,
        "draft_quality_reasons": quality_reasons,
        "active_rule_hints":     {k: v for k, v in _hints.items() if not k.startswith("_")},
    }


def _suggest_action(facts_by_type: dict[str, list[dict]], rel_type: str) -> str:
    """Suggest the most relevant next action based on accepted fact types."""
    if "issue" in facts_by_type:
        return "Schedule service call — active issue reported"
    if "request" in facts_by_type:
        issues = [f["fact_value"] for f in facts_by_type.get("request", [])]
        if issues:
            return f"Follow up on open request: {issues[0][:80]}"
        return "Follow up on open request"
    if "follow_up" in facts_by_type:
        return "Send follow-up message — past follow-up noted"
    if "equipment" in facts_by_type or "system" in facts_by_type:
        names = [f["fact_value"] for f in facts_by_type.get("equipment", []) + facts_by_type.get("system", [])]
        label = names[0] if names else "system"
        return f"Check on {label} status and reply with update"
    if rel_type in ("vendor", "order"):
        return "Check order/lead-time status and reply"
    return "Review profile history and reply to message"


# ── Incoming message context card ─────────────────────────────────────────────

@app.get("/api/x-intake/context-card", tags=["x-intake"])
async def x_intake_context_card(
    thread_guid: str = "",
    contact_handle: str = "",
) -> dict[str, Any]:
    """Return a context card for an incoming iMessage thread or contact handle.

    Aggregates the relationship profile, accepted facts, pending (unverified)
    facts, recent reply receipts, a rule-based suggested next action, and a
    draft reply. Rejected facts are excluded. Contact numbers are always masked.
    Nothing is sent automatically — draft_reply is display-only.

    Lookup order:
      1. contact_handle (explicit, normalised to E.164)
      2. thread_guid  → extract phone suffix → thread_index lookup
    """
    handle = _lookup_contact_handle(thread_guid.strip(), contact_handle.strip())
    if not handle:
        return {
            "status": "no_handle",
            "message": "Provide thread_guid or contact_handle",
            "profile": None,
            "accepted_facts": {},
            "unverified_facts": {},
            "recent_replies": [],
            "suggested_next_action": "",
            "draft_reply": "",
            "confidence": 0.0,
        }

    masked = _mask_handle(handle)
    profile_row = _profile_by_handle(handle)

    if profile_row is None:
        import secrets as _secrets
        return {
            "status":                "no_profile",
            "action_id":             _secrets.token_hex(6),
            "contact_masked":        masked,
            "message":               "No relationship profile found for this contact.",
            "profile":               None,
            "accepted_facts":        {},
            "unverified_facts":      {},
            "recent_replies":        _receipts_for_handle(handle),
            "suggested_next_action": "No profile — consider reviewing this contact",
            "draft_reply":           "Hi, thanks for reaching out. I'll get back to you shortly.",
            "reasoning":             "No relationship profile on file — generic safe reply.",
            "confidence":            0.25,
            "source_facts":          [],
        }

    # Build profile dict (masked)
    profile = {
        "profile_id":        profile_row["profile_id"],
        "relationship_type": profile_row["relationship_type"],
        "display_name":      profile_row["display_name"],
        "contact_masked":    masked,
        "first_seen":        profile_row["first_seen"],
        "last_seen":         profile_row["last_seen"],
        "summary":           profile_row["summary"],
        "open_requests":     json.loads(profile_row["open_requests"] or "[]"),
        "follow_ups":        json.loads(profile_row["follow_ups"] or "[]"),
        "systems_or_topics": json.loads(profile_row["systems_or_topics"] or "[]"),
        "project_refs":      json.loads(profile_row["project_refs"] or "[]"),
        "status":            profile_row["status"],
        "confidence":        profile_row["confidence"],
    }

    # Split facts: accepted vs pending (unverified); rejected already excluded by query
    facts = _facts_for_profile(profile_row["profile_id"])
    accepted_by_type: dict[str, list[dict]] = {}
    unverified_by_type: dict[str, list[dict]] = {}

    for f in facts:
        entry = {
            "fact_id":          f["fact_id"],
            "fact_type":        f["fact_type"],
            "fact_value":       f["fact_value"],
            "confidence":       f["confidence"],
            "source_excerpt":   f["source_excerpt"],
            "source_timestamp": f["source_timestamp"],
        }
        if f["is_accepted"]:
            accepted_by_type.setdefault(f["fact_type"], []).append(entry)
        else:
            unverified_by_type.setdefault(f["fact_type"], []).append(entry)

    # Override stale profile summary columns with values derived from CURRENT
    # accepted facts only.  The profiles table was written at extraction time
    # and may include fact values that have since been rejected by the quality
    # audit (e.g. speech fragments, generic "Let me know").
    profile["open_requests"] = [
        f["fact_value"] for f in facts
        if f["is_accepted"] and f["fact_type"] == "request"
    ][:5]
    profile["follow_ups"] = [
        f["fact_value"] for f in facts
        if f["is_accepted"] and f["fact_type"] == "follow_up"
    ][:5]

    import secrets as _secrets
    receipts = _receipts_for_handle(handle)
    action   = _suggest_action(accepted_by_type, profile["relationship_type"])
    try:
        _reply_hints = _si_engine.apply_reply_hints(_si_engine.get_active_rules())
    except Exception:
        _reply_hints = {}
    built    = _build_draft_with_context(
        profile=profile,
        accepted_by_type=accepted_by_type,
        unverified_by_type=unverified_by_type,
        recent_replies=receipts,
        behavior_hints=_reply_hints,
    )
    # Apply Matt's reply style — falls back silently if style engine unavailable
    try:
        from cortex.style_engine import apply_style as _apply_style
        styled_draft, style_applied, style_confidence = _apply_style(
            built["draft_reply"],
            context={"relationship_type": profile.get("relationship_type", "")},
        )
    except Exception:
        styled_draft, style_applied, style_confidence = built["draft_reply"], False, 0.0

    action_id = _secrets.token_hex(6)  # fresh per request; used by approve-reply

    return {
        "status":                "ok",
        "action_id":             action_id,
        "contact_masked":        masked,
        "profile":               profile,
        "accepted_facts":        accepted_by_type,
        "unverified_facts":      unverified_by_type,
        "recent_replies":        receipts,
        "suggested_next_action": action,
        "draft_reply":           styled_draft,
        "reasoning":             built["reasoning"],
        "confidence":            built["confidence"],
        "source_facts":          built["source_facts"],
        "draft_quality_status":  built["draft_quality_status"],
        "draft_quality_reasons": built["draft_quality_reasons"],
        "style_applied":         style_applied,
        "style_confidence":      style_confidence,
        "active_rule_hints":     built["active_rule_hints"],
        "active_rules_applied":  _active_rules_summary("reply_phrasing"),
    }


# ── Reply approval flow ────────────────────────────────────────────────────────
# Write to _CORTEX_DATA_DIR (/data/cortex), NOT _X_INTAKE_DATA_DIR (/data/x_intake).
# The x_intake dir is mounted read-only in this container.

# Keep a module-level alias so tests can patch it easily.
_APPROVAL_LOG = _APPROVAL_LOG_PATH


def _write_approval_record(record: dict[str, Any]) -> None:
    """Append an approval record to reply_approvals.ndjson. Never raises."""
    try:
        _APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _APPROVAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("reply_approval_write_failed err=%s", str(exc)[:100])


def _write_dry_run_receipt(
    approval_id: str,
    contact_masked: str,
    final_reply: str,
    action_type: str = "approve_reply",
) -> None:
    """Write a dry-run send receipt to reply_receipts_dry_run.ndjson.

    Stored in the Cortex data dir (rw) not the x_intake dir (ro).
    Mirrors the field schema of x_intake/reply_actions/ack.py receipts
    for consistency.  Always dry_run=True — the approval flow never
    initiates a live send without an explicit separate enable step.
    """
    import re as _re
    # Extract the last visible digits from the masked handle for traceability.
    # e.g. "+13***32" → "...32".  We never store the raw phone.
    digits = _re.sub(r"[^0-9]", "", contact_masked)
    phone_last4 = f"...{digits[-4:]}" if len(digits) >= 2 else "...????"

    receipt: dict[str, Any] = {
        "ts":                datetime.now(timezone.utc).isoformat(),
        "action_id":         approval_id,
        "action_type":       action_type,
        "dry_run":           True,
        "success":           True,
        "path":              "dry_run",
        "phone_last4":       phone_last4,
        "recipient_hash":    "",          # no raw thread_guid at approval time
        "text":              final_reply[:500],
        "error":             "",
        "fallback_used":     False,
        "bridge_status_code": None,
        "contact_masked":    contact_masked,
    }
    try:
        _DRY_RUN_RECEIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _DRY_RUN_RECEIPT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt) + "\n")
        logger.info(
            "dry_run_receipt_written approval_id=%s contact=%s",
            approval_id, contact_masked,
        )
    except Exception as exc:
        logger.warning("dry_run_receipt_write_failed err=%s", str(exc)[:100])


@app.post("/api/x-intake/approve-reply", tags=["x-intake"])
async def x_intake_approve_reply(body: dict[str, Any]) -> dict[str, Any]:
    """Log an operator approval of a draft reply. Does NOT send.

    Body:
      action_id     — from context-card response (used as correlation key)
      approved      — must be true to store; false is a no-op
      edited_reply  — optional override; if omitted, draft_reply is used
      draft_reply   — the original draft (for logging / diffing)
      contact_masked — already-masked contact reference (never raw phone)
      reasoning     — why the draft was generated (for audit trail)
      confidence    — 0–1 float from context-card

    Behaviour:
      - Validates that approved=true.
      - Stores final_reply (edited_reply if present, else draft_reply) to
        reply_approvals.ndjson — never to any live send path.
      - Returns approval_id and stored record (masked).
    """
    import secrets as _secrets
    import time as _time

    body = body or {}
    if not body.get("approved"):
        return {"status": "not_approved", "message": "approved must be true to store an approval."}

    action_id            = str(body.get("action_id", "")).strip()
    draft_reply          = str(body.get("draft_reply", "")).strip()
    edited_reply         = str(body.get("edited_reply", "")).strip()
    contact_masked       = str(body.get("contact_masked", "")).strip()
    reasoning            = str(body.get("reasoning", "")).strip()
    confidence           = float(body.get("confidence", 0.0))
    draft_quality_status = str(body.get("draft_quality_status", "pass")).strip()
    draft_quality_reasons = list(body.get("draft_quality_reasons") or [])

    if not action_id:
        return {"status": "error", "error": "action_id required"}

    # Refuse approvals for drafts flagged as blocked — operator must edit first.
    if draft_quality_status == "blocked":
        return {
            "status": "blocked",
            "error": "Draft has quality issues and cannot be approved without editing.",
            "draft_quality_reasons": draft_quality_reasons,
        }

    final_reply = edited_reply if edited_reply else draft_reply
    if not final_reply:
        return {"status": "error", "error": "draft_reply or edited_reply required"}

    # Post-approve quality check on the final reply (catches edits that reintroduce fragments).
    final_quality, final_quality_reasons = _check_draft_quality(final_reply)
    if final_quality == "blocked" and not edited_reply:
        return {
            "status": "blocked",
            "error": "Draft failed quality check — edit the reply before approving.",
            "draft_quality_reasons": final_quality_reasons,
        }

    # Sanity-check: contact_masked must not contain raw digits run > 6 chars
    # (a belt-and-suspenders guard; the UI already masks before sending).
    import re as _re
    if _re.search(r"\d{7,}", contact_masked):
        contact_masked = _mask_handle(contact_masked)

    approval_id = _secrets.token_hex(6)
    record = {
        "approval_id":    approval_id,
        "action_id":      action_id,
        "contact_masked": contact_masked,
        "draft_reply":    draft_reply[:500],
        "final_reply":    final_reply[:500],
        "edited":         bool(edited_reply and edited_reply != draft_reply),
        "reasoning":      reasoning[:300],
        "confidence":     round(confidence, 3),
        "approved_at":    datetime.now(timezone.utc).isoformat(),
        "status":         "approved",
    }
    _write_approval_record(record)
    _write_dry_run_receipt(approval_id, contact_masked, final_reply)
    logger.info(
        "reply_approved approval_id=%s action_id=%s contact=%s edited=%s",
        approval_id, action_id, contact_masked, record["edited"],
    )
    return {
        "status":             "ok",
        "approval_id":        approval_id,
        "action_id":          action_id,
        "contact_masked":     contact_masked,
        "final_reply":        final_reply,
        "edited":             record["edited"],
        "stored":             True,
        "send_action_created": True,
        "send_dry_run":       True,
        "send_triggered":     False,
    }


@app.post("/api/x-intake/simulate-incoming", tags=["x-intake"])
async def x_intake_simulate_incoming(body: dict[str, Any]) -> dict[str, Any]:
    """Simulate an inbound iMessage for testing the context-card + approval flow.

    Body:
      contact_handle — E.164 phone (e.g. '+13035257532'); OR
      thread_guid    — 'any;-;+13035257532' format
      message_text   — optional last message content (used in reasoning)

    Returns the same shape as GET /api/x-intake/context-card plus action_id.
    No real messages are touched; no sends occur.
    """
    import secrets as _secrets

    body = body or {}
    thread_guid    = str(body.get("thread_guid", "")).strip()
    contact_handle = str(body.get("contact_handle", "")).strip()
    last_message   = str(body.get("message_text", "")).strip()[:200]

    handle = _lookup_contact_handle(thread_guid, contact_handle)
    if not handle:
        return {
            "status":  "no_handle",
            "message": "Provide thread_guid or contact_handle",
            "simulated": True,
        }

    masked = _mask_handle(handle)
    profile_row = _profile_by_handle(handle)

    if profile_row is None:
        return {
            "status":                "no_profile",
            "action_id":             _secrets.token_hex(6),
            "contact_masked":        masked,
            "message":               "No relationship profile found for this contact.",
            "profile":               None,
            "accepted_facts":        {},
            "unverified_facts":      {},
            "recent_replies":        _receipts_for_handle(handle),
            "suggested_next_action": "No profile — consider reviewing this contact",
            "draft_reply":           "Hi, thanks for reaching out. I'll get back to you shortly.",
            "reasoning":             "No relationship profile on file — generic safe reply.",
            "confidence":            0.25,
            "source_facts":          [],
            "simulated":             True,
        }

    profile = {
        "profile_id":        profile_row["profile_id"],
        "relationship_type": profile_row["relationship_type"],
        "display_name":      profile_row["display_name"],
        "contact_masked":    masked,
        "first_seen":        profile_row["first_seen"],
        "last_seen":         profile_row["last_seen"],
        "summary":           profile_row["summary"],
        "open_requests":     json.loads(profile_row["open_requests"] or "[]"),
        "follow_ups":        json.loads(profile_row["follow_ups"] or "[]"),
        "systems_or_topics": json.loads(profile_row["systems_or_topics"] or "[]"),
        "project_refs":      json.loads(profile_row["project_refs"] or "[]"),
        "status":            profile_row["status"],
        "confidence":        profile_row["confidence"],
    }

    facts = _facts_for_profile(profile_row["profile_id"])
    accepted_by_type: dict[str, list[dict]] = {}
    unverified_by_type: dict[str, list[dict]] = {}
    for f in facts:
        entry = {
            "fact_id":          f["fact_id"],
            "fact_type":        f["fact_type"],
            "fact_value":       f["fact_value"],
            "confidence":       f["confidence"],
            "source_excerpt":   f["source_excerpt"],
            "source_timestamp": f["source_timestamp"],
        }
        (accepted_by_type if f["is_accepted"] else unverified_by_type).setdefault(
            f["fact_type"], []
        ).append(entry)

    # Refresh stale profile summary columns from current accepted facts only.
    profile["open_requests"] = [
        f["fact_value"] for f in facts
        if f["is_accepted"] and f["fact_type"] == "request"
    ][:5]
    profile["follow_ups"] = [
        f["fact_value"] for f in facts
        if f["is_accepted"] and f["fact_type"] == "follow_up"
    ][:5]

    receipts = _receipts_for_handle(handle)
    action   = _suggest_action(accepted_by_type, profile["relationship_type"])
    try:
        _reply_hints2 = _si_engine.apply_reply_hints(_si_engine.get_active_rules())
    except Exception:
        _reply_hints2 = {}
    built    = _build_draft_with_context(
        profile=profile,
        accepted_by_type=accepted_by_type,
        unverified_by_type=unverified_by_type,
        recent_replies=receipts,
        last_message=last_message,
        behavior_hints=_reply_hints2,
    )
    try:
        from cortex.style_engine import apply_style as _apply_style
        styled_draft, style_applied, style_confidence = _apply_style(
            built["draft_reply"],
            context={"relationship_type": profile.get("relationship_type", "")},
        )
    except Exception:
        styled_draft, style_applied, style_confidence = built["draft_reply"], False, 0.0

    action_id = _secrets.token_hex(6)

    return {
        "status":                "ok",
        "action_id":             action_id,
        "contact_masked":        masked,
        "profile":               profile,
        "accepted_facts":        accepted_by_type,
        "unverified_facts":      unverified_by_type,
        "recent_replies":        receipts,
        "suggested_next_action": action,
        "draft_reply":           styled_draft,
        "reasoning":             built["reasoning"],
        "confidence":            built["confidence"],
        "source_facts":          built["source_facts"],
        "draft_quality_status":  built["draft_quality_status"],
        "draft_quality_reasons": built["draft_quality_reasons"],
        "style_applied":         style_applied,
        "style_confidence":      style_confidence,
        "simulated":             True,
        "last_message":          last_message or None,
    }


# ── Follow-up engine ───────────────────────────────────────────────────────────

import time as _time
import datetime as _dt

_X_INTAKE_QUEUE_DB = _X_INTAKE_DATA_DIR / "queue.db"


def _queue_rows_with_context(limit: int = 500) -> list[dict]:
    """Return x_intake_queue rows that have sender_guid + non-trivial context_json.

    The queue DB is mounted read-only in this container.
    Returns an empty list silently if unavailable.
    """
    if not _X_INTAKE_QUEUE_DB.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{_X_INTAKE_QUEUE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, sender_guid, context_json, created_at "
            "FROM x_intake_queue "
            "WHERE sender_guid != '' "
            "  AND context_json IS NOT NULL "
            "  AND context_json NOT IN ('', '{}') "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _approvals_index() -> dict[str, float]:
    """Return {contact_masked → latest_approval_unix_ts} from reply_approvals.ndjson."""
    if not _APPROVAL_LOG.is_file():
        return {}
    index: dict[str, float] = {}
    try:
        for line in _APPROVAL_LOG.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
            except Exception:
                continue
            masked = a.get("contact_masked", "")
            if not masked:
                continue
            try:
                ts = _dt.datetime.fromisoformat(
                    a.get("approved_at", "").replace("Z", "+00:00")
                ).timestamp()
            except Exception:
                continue
            if index.get(masked, 0.0) < ts:
                index[masked] = ts
    except Exception:
        pass
    return index


# ── Follow-up priority table ──────────────────────────────────────────────────
# (relationship_type → (threshold_hours, priority_label, priority_rank))
# priority_rank: lower number = higher urgency (used for sort key)
_FOLLOW_UP_PRIORITY: dict[str, tuple[float, str, int]] = {
    "client":               (2.0,  "urgent",  0),
    "builder":              (3.0,  "high",    1),
    "trade_partner":        (4.0,  "medium",  2),
    "vendor":               (6.0,  "medium",  2),
    "personal_work_related":(12.0, "low",     3),
    "unknown":              (8.0,  "review",  4),
    "internal_team":        (None, "ignore",  9),  # ignored by default
}
_DEFAULT_PRIORITY = (8.0, "review", 4)  # fallback for unrecognised types


def _rel_priority(rel_type: str) -> tuple[float, str, int]:
    """Return (threshold_hours, priority_label, priority_rank) for a relationship type."""
    return _FOLLOW_UP_PRIORITY.get(rel_type, _DEFAULT_PRIORITY)


def _compute_follow_ups(
    threshold_hours: float = -1.0,
    include_internal: bool = False,
) -> list[dict]:
    """Return all overdue follow-up items, sorted by priority then overdue age.

    Includes the internal ``priority_rank`` field so callers can slice/sort.
    Callers that return to the API must pop ``priority_rank`` before responding.
    """
    now = _time.time()
    override = threshold_hours if threshold_hours >= 0 else None

    rows = _queue_rows_with_context(limit=500)
    if not rows:
        return []

    # Parse context JSON; skip rows without a valid contact
    enriched: list[dict] = []
    for row in rows:
        try:
            ctx = json.loads(row["context_json"] or "{}")
        except Exception:
            continue
        contact_masked = ctx.get("contact_masked", "")
        if not contact_masked or ctx.get("status") == "no_handle":
            continue
        profile = ctx.get("profile") or {}
        rel_type = profile.get("relationship_type", "unknown") or "unknown"
        enriched.append({
            "queue_item_id":         row["id"],
            "contact_masked":        contact_masked,
            "created_at":            row["created_at"],
            "relationship_type":     rel_type,
            "has_context_card":      ctx.get("status") in ("ok", "no_profile"),
            "has_draft_reply":       bool((ctx.get("draft_reply") or "").strip()),
            "draft_reply":           ctx.get("draft_reply", ""),
            "confidence":            ctx.get("confidence", 0.0),
            "draft_quality_status":  ctx.get("draft_quality_status", ""),
            "profile":               profile,
            "suggested_next_action": ctx.get("suggested_next_action", ""),
        })

    # Keep only the most-recent row per contact
    by_contact: dict[str, dict] = {}
    for item in enriched:
        c = item["contact_masked"]
        if c not in by_contact or item["created_at"] > by_contact[c]["created_at"]:
            by_contact[c] = item

    approvals = _approvals_index()

    # Load follow-up adjustments from approved self-improvement rules (safe fallback)
    try:
        _fu_adjustments = _si_engine.apply_followup_adjustments(_si_engine.get_active_rules())
    except Exception:
        _fu_adjustments = {}

    follow_ups: list[dict] = []
    for item in by_contact.values():
        rel = item["relationship_type"]
        default_threshold_h, priority_label, priority_rank = _rel_priority(rel)

        # Skip internal_team unless explicitly requested
        if priority_label == "ignore" and not include_internal:
            continue

        # Apply per-type threshold (or test override)
        threshold_h = override if override is not None else (
            default_threshold_h if default_threshold_h is not None else 24.0
        )
        # Apply rule-engine multiplier if present (e.g. lower threshold for urgency)
        if _fu_adjustments.get("urgent_threshold_hours_multiplier") and priority_label == "urgent":
            threshold_h *= _fu_adjustments["urgent_threshold_hours_multiplier"]
        elapsed = now - item["created_at"]
        if elapsed < threshold_h * 3600:
            continue                                # Not yet overdue

        latest_approved_at = approvals.get(item["contact_masked"], 0.0)
        if latest_approved_at > item["created_at"]:
            continue                                # Already replied

        overdue_s = elapsed - threshold_h * 3600
        item["has_approved_reply"]   = False
        item["elapsed_seconds"]      = round(elapsed)
        item["elapsed_hours"]        = round(elapsed / 3600, 1)
        item["threshold_hours_used"] = threshold_h
        item["overdue_by_hours"]     = round(overdue_s / 3600, 1)
        item["priority"]             = priority_label
        item["priority_rank"]        = priority_rank
        follow_ups.append(item)

    # Sort: priority rank (urgent first), then oldest overdue first
    follow_ups.sort(key=lambda x: (x["priority_rank"], -x["overdue_by_hours"]))
    return follow_ups


@app.get("/api/x-intake/follow-ups", tags=["x-intake"])
async def x_intake_follow_ups(
    threshold_hours: float = -1.0,
    include_internal: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """Return inbound messages that need a follow-up reply, prioritised by relationship.

    Priority thresholds (relationship-aware defaults):
      client          → urgent  after 2 h
      builder         → high    after 3 h
      trade_partner   → medium  after 4 h
      vendor          → medium  after 6 h
      personal_work   → low     after 12 h
      unknown         → review  after 8 h
      internal_team   → ignored (unless include_internal=true, uses 24 h)

    Sorted: priority rank first (urgent → low), then oldest overdue first.

    threshold_hours  — override per-type defaults when >= 0 (useful for testing)
    include_internal — surface internal_team follow-ups (default false)
    limit            — max items returned (default 20)

    Returns only internal Cortex data — no messages are sent.
    """
    override = threshold_hours if threshold_hours >= 0 else None
    follow_ups = _compute_follow_ups(threshold_hours=threshold_hours,
                                     include_internal=include_internal)
    follow_ups = follow_ups[:limit]
    for f in follow_ups:
        f.pop("priority_rank", None)
    return {
        "status":                   "ok",
        "count":                    len(follow_ups),
        "threshold_hours_override": override,
        "follow_ups":               follow_ups,
    }


@app.get("/api/x-intake/follow-up-count", tags=["x-intake"])
async def x_intake_follow_up_count(
    threshold_hours: float = -1.0,
    include_internal: bool = False,
) -> dict[str, Any]:
    """Return prioritized follow-up counts for the header alert badge.

    Returns only internal Cortex data — no messages are sent.
    """
    items = _compute_follow_ups(threshold_hours=threshold_hours,
                                include_internal=include_internal)
    urgent = sum(1 for i in items if i["priority"] == "urgent")
    high   = sum(1 for i in items if i["priority"] == "high")
    return {"total": len(items), "urgent": urgent, "high": high}


# ── Self-Improvement Card Promotion ────────────────────────────────────────────

_PROMOTED_RULES_PATH = _CORTEX_DATA_DIR / "promoted_rules.json"


def _active_rules_summary(category: str | None = None) -> list[dict[str, Any]]:
    """Compact list of approved rules for inclusion in API responses.

    Only status=approved rules are returned.  Proposed and rejected rules are
    always excluded so callers never surface unapproved behaviour.

    Args:
        category: optional behavior_category filter (e.g. "triage_scoring").
                  Pass None to return all active rules.
    """
    try:
        rules = _si_engine.get_active_rules()  # already filters to approved only
        if category:
            rules = [r for r in rules if r.get("behavior_category") == category]
        return [
            {
                "rule_id":           r["rule_id"],
                "behavior_category": r.get("behavior_category", "general"),
                "summary":           r.get("summary", ""),
                "approved_by":       r.get("approved_by") or "",
                "approved_at":       (r.get("approved_at") or "")[:10],
            }
            for r in rules
        ]
    except Exception:
        return []


@app.get("/api/self-improvement/promoted-rules", tags=["self-improvement"])
async def self_improvement_promoted_rules(status: str = "all") -> dict[str, Any]:
    """Promoted self-improvement rules, optionally filtered by status."""
    if not _PROMOTED_RULES_PATH.exists():
        return {
            "status": "ok",
            "message": "No promoted rules yet. Run: python3 scripts/promote_self_improvement_cards.py --apply",
            "rules": [],
            "count": 0,
        }
    try:
        data = json.loads(_PROMOTED_RULES_PATH.read_text())
        rules = data.get("rules", [])
        if status != "all":
            rules = [r for r in rules if r.get("status") == status]
        return {
            "status": "ok",
            "count": len(rules),
            "updated_at": data.get("updated_at", ""),
            "rules": rules,
        }
    except Exception as exc:
        logger.warning("promoted_rules_read_error err=%s", exc)
        return {"status": "error", "error": str(exc)[:200], "rules": [], "count": 0}


@app.post("/api/self-improvement/promoted-rules/{rule_id}/approve", tags=["self-improvement"])
async def self_improvement_approve_rule(
    rule_id: str,
    body: dict[str, Any] = None,
) -> dict[str, Any]:
    """Approve a promoted rule. Approved rules actively influence system behavior.

    Body (optional): {"approved_by": "matt"}
    All status changes are permanent until explicitly rejected.
    """
    approved_by = (body or {}).get("approved_by", "matt")
    result = _si_engine.approve_rule(rule_id, approved_by=approved_by)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    logger.info("rule_approved rule_id=%s by=%s", rule_id, approved_by)
    return {"status": "ok", "rule": result}


@app.post("/api/self-improvement/promoted-rules/{rule_id}/reject", tags=["self-improvement"])
async def self_improvement_reject_rule(
    rule_id: str,
    body: dict[str, Any] = None,
) -> dict[str, Any]:
    """Reject a promoted rule. Rejected rules are excluded from active behavior.

    Body (optional): {"reason": "not relevant"}
    """
    reason = (body or {}).get("reason", "")
    result = _si_engine.reject_rule(rule_id, reason=reason)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    logger.info("rule_rejected rule_id=%s reason=%s", rule_id, reason[:80])
    return {"status": "ok", "rule": result}


# ── Reply Suggestion Engine ────────────────────────────────────────────────────

from cortex import reply_suggest as _reply_suggest
from cortex.config import OLLAMA_HOST, OLLAMA_MODEL


@app.post("/api/reply/suggest", tags=["reply"])
async def reply_suggest_endpoint(body: dict[str, Any] = None) -> dict[str, Any]:
    """Generate a suggested reply draft via local Ollama.

    Input:
      {"contact_handle": "+1...", "message_text": "incoming text"}

    Output:
      {"status": "ok", "draft": "...", "confidence": 0.0–1.0,
       "applied_rules": [...], "reasoning": "..."}

    Never auto-sends. Draft requires manual review and approval.
    Only calls local Ollama — no external API usage.
    """
    payload = body or {}
    raw_handle  = payload.get("contact_handle", "").strip()
    message_text = payload.get("message_text", "").strip()

    if not raw_handle:
        return {"status": "error", "error": "contact_handle is required", "draft": "", "confidence": 0.0}

    handle = _normalize_handle(raw_handle)
    if not handle:
        return {"status": "error", "error": f"Cannot parse handle: {raw_handle!r}", "draft": "", "confidence": 0.0}

    # Build profile + facts using existing helpers
    profile_row = _profile_by_handle(handle)
    profile: dict | None = None
    accepted_by_type: dict[str, list[dict]] = {}

    if profile_row is not None:
        profile = {
            "profile_id":        profile_row["profile_id"],
            "relationship_type": profile_row["relationship_type"],
            "display_name":      profile_row["display_name"],
            "summary":           profile_row["summary"],
            "open_requests":     json.loads(profile_row["open_requests"] or "[]"),
            "systems_or_topics": json.loads(profile_row["systems_or_topics"] or "[]"),
        }
        facts = _facts_for_profile(profile_row["profile_id"])
        for f in facts:
            if f.get("is_accepted"):
                accepted_by_type.setdefault(f["fact_type"], []).append(f)

    recent_replies = _receipts_for_handle(handle, limit=5)

    # Active rules — get_active_rules() already filters to approved only
    try:
        active_rules   = _si_engine.get_active_rules()
        behavior_hints = _si_engine.apply_reply_hints(active_rules)
    except Exception:
        active_rules, behavior_hints = [], {}

    result = await _reply_suggest.build_suggestion(
        contact_handle=handle,
        message_text=message_text,
        profile=profile,
        accepted_by_type=accepted_by_type,
        recent_replies=recent_replies,
        active_rules=active_rules,
        behavior_hints=behavior_hints,
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
    )

    logger.info(
        "reply_suggest handle=%s confidence=%.2f rules=%d",
        _mask_handle(handle), result.get("confidence", 0), len(result.get("applied_rules", [])),
    )
    return result


# ── Reply Suggestion Inbox ────────────────────────────────────────────────────


@app.get("/api/reply/suggestions/pending", tags=["reply"])
async def reply_suggestions_pending(limit: int = 10) -> dict[str, Any]:
    """Return pending reply candidates from the follow-up engine.

    Sources contacts from the overdue follow-up queue, enriches each with the
    context-card draft and active rules, and returns suggestion cards for the
    dashboard inbox. Never sends messages.

    Returns status=ok with count=0 and suggestions=[] when the queue is empty.
    """
    import secrets as _secrets

    follow_ups = _compute_follow_ups()[:limit]

    if not follow_ups:
        return {"status": "ok", "count": 0, "suggestions": []}

    active_rules = _active_rules_summary("reply_phrasing")

    suggestions: list[dict[str, Any]] = []
    for item in follow_ups:
        item.pop("priority_rank", None)
        profile = item.get("profile") or {}
        draft_quality_reasons: list[str] = []

        # Derive last_message from open_requests or follow_ups on profile
        last_message = ""
        open_reqs = profile.get("open_requests") or []
        if open_reqs:
            last_message = open_reqs[-1] if isinstance(open_reqs, list) else ""

        suggestions.append({
            "action_id":             _secrets.token_hex(6),
            "queue_item_id":         item.get("queue_item_id"),
            "contact_masked":        item["contact_masked"],
            "relationship_type":     item["relationship_type"],
            "display_name":          profile.get("display_name", ""),
            "systems_or_topics":     profile.get("systems_or_topics", []),
            "last_message":          last_message,
            "suggested_reply":       item.get("draft_reply", ""),
            "confidence":            round(float(item.get("confidence", 0.0)), 3),
            "draft_quality_status":  item.get("draft_quality_status", "pass") or "pass",
            "draft_quality_reasons": draft_quality_reasons,
            "active_rules_applied":  active_rules,
            "suggested_next_action": item.get("suggested_next_action", ""),
            "created_at":            item.get("created_at", ""),
            "follow_up_priority":    item.get("priority", "review"),
            "overdue_by_hours":      item.get("overdue_by_hours", 0.0),
            "elapsed_hours":         item.get("elapsed_hours", 0.0),
        })

    return {"status": "ok", "count": len(suggestions), "suggestions": suggestions}


@app.post("/api/reply/regenerate", tags=["reply"])
async def reply_regenerate(body: dict[str, Any]) -> dict[str, Any]:
    """Regenerate a reply suggestion for a pending queue item.

    Body:
      queue_item_id — integer row ID from x_intake_queue (never raw phone)
      message_text  — optional incoming message text for context

    Looks up sender_guid from the queue DB internally — the raw contact handle
    never leaves the server. Returns same shape as /api/reply/suggest.
    """
    body = body or {}
    queue_item_id = body.get("queue_item_id")
    message_text  = str(body.get("message_text", "")).strip()[:500]

    if queue_item_id is None:
        return {"status": "error", "error": "queue_item_id required", "draft": "", "confidence": 0.0}

    # Look up sender_guid from the queue DB (read-only mount)
    sender_guid = ""
    if _X_INTAKE_QUEUE_DB.is_file():
        try:
            conn = sqlite3.connect(f"file:{_X_INTAKE_QUEUE_DB}?mode=ro", uri=True)
            row = conn.execute(
                "SELECT sender_guid FROM x_intake_queue WHERE id = ?", (int(queue_item_id),)
            ).fetchone()
            conn.close()
            if row:
                sender_guid = row[0] or ""
        except Exception:
            pass

    if not sender_guid:
        return {
            "status": "error",
            "error": f"queue_item_id {queue_item_id} not found or has no sender_guid",
            "draft": "", "confidence": 0.0,
        }

    # Derive handle from sender_guid (format: "any;-;+13035257532")
    handle = _normalize_handle(sender_guid.split(";")[-1].strip())
    if not handle:
        return {"status": "error", "error": "Cannot parse handle from sender_guid", "draft": "", "confidence": 0.0}

    profile_row = _profile_by_handle(handle)
    profile: dict | None = None
    accepted_by_type: dict[str, list[dict]] = {}

    if profile_row is not None:
        profile = {
            "profile_id":        profile_row["profile_id"],
            "relationship_type": profile_row["relationship_type"],
            "display_name":      profile_row["display_name"],
            "summary":           profile_row["summary"],
            "open_requests":     json.loads(profile_row["open_requests"] or "[]"),
            "systems_or_topics": json.loads(profile_row["systems_or_topics"] or "[]"),
        }
        for f in _facts_for_profile(profile_row["profile_id"]):
            if f.get("is_accepted"):
                accepted_by_type.setdefault(f["fact_type"], []).append(f)

    recent_replies = _receipts_for_handle(handle, limit=5)

    try:
        active_rules   = _si_engine.get_active_rules()
        behavior_hints = _si_engine.apply_reply_hints(active_rules)
    except Exception:
        active_rules, behavior_hints = [], {}

    result = await _reply_suggest.build_suggestion(
        contact_handle=handle,
        message_text=message_text,
        profile=profile,
        accepted_by_type=accepted_by_type,
        recent_replies=recent_replies,
        active_rules=active_rules,
        behavior_hints=behavior_hints,
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
    )

    logger.info(
        "reply_regenerate queue_item_id=%s confidence=%.2f",
        queue_item_id, result.get("confidence", 0),
    )
    return result


# ── X API Intake ───────────────────────────────────────────────────────────────

_X_API_DB_CONTAINER = Path("/data/x_api/x_items.sqlite")
_X_API_DB_HOST      = Path("/Users/bob/AI-Server/data/x_api/x_items.sqlite")


def _x_api_db_path() -> Path | None:
    """Return the x_api DB path if it exists, else None."""
    if _X_API_DB_CONTAINER.is_file():
        return _X_API_DB_CONTAINER
    if _X_API_DB_HOST.is_file():
        return _X_API_DB_HOST
    return None


def _x_api_creds_summary() -> dict[str, bool]:
    """Return credential presence dict — never exposes actual values."""
    return {
        "bearer_token":        bool(os.environ.get("X_API_BEARER_TOKEN")),
        "client_id":           bool(os.environ.get("X_API_CLIENT_ID")),
        "client_secret":       bool(os.environ.get("X_API_CLIENT_SECRET")),
        "access_token":        bool(os.environ.get("X_API_ACCESS_TOKEN")),
        "refresh_token":       bool(os.environ.get("X_API_REFRESH_TOKEN")),
        "user_id_configured":  bool(os.environ.get("X_USER_ID")),
    }


@app.get("/api/x-api/status", tags=["x-api"])
async def x_api_status() -> dict[str, Any]:
    """Return X API intake status — credential presence (masked), DB stats, usage.

    Never exposes actual API keys or tokens.
    """
    enabled = os.environ.get("X_ENABLED", "0").strip() == "1"
    creds   = _x_api_creds_summary()
    db_path = _x_api_db_path()

    if db_path is None:
        return {
            "status":            "no_db",
            "enabled":           enabled,
            "credentials":       creds,
            "daily_reads_used":  0,
            "daily_reads_limit": int(os.environ.get("X_DAILY_READ_LIMIT", "100")),
            "total_items":       0,
            "last_run":          None,
            "warning":           "No X API DB found. Run scripts/x_api_intake.py --apply to initialise.",
        }

    import sqlite3 as _sqlite3
    daily_limit = int(os.environ.get("X_DAILY_READ_LIMIT", "100"))
    base = {
        "status":            "ok" if enabled else "disabled",
        "enabled":           enabled,
        "credentials":       creds,
        "daily_reads_limit": daily_limit,
    }

    try:
        conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = _sqlite3.Row
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_used = conn.execute(
            "SELECT COALESCE(SUM(request_count),0) FROM x_api_usage WHERE ts LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        total_items = conn.execute("SELECT COUNT(*) FROM x_items").fetchone()[0]
        last_run_row = conn.execute(
            "SELECT ts, endpoint, status FROM x_api_usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
        status_counts_rows = conn.execute(
            "SELECT processed_status, COUNT(*) FROM x_items GROUP BY processed_status"
        ).fetchall()
        status_counts = {r[0]: r[1] for r in status_counts_rows}
        conn.close()
    except _sqlite3.OperationalError as exc:
        return {
            **base,
            "status":           "degraded",
            "daily_reads_used": 0,
            "within_limit":     True,
            "total_items":      0,
            "eligible_items":   0,
            "pending_items":    0,
            "blocked_items":    0,
            "last_run":         None,
            "last_run_endpoint": None,
            "last_run_status":  None,
            "warning": (
                f"DB exists but tables are not initialised ({exc}). "
                "Run: python3 scripts/x_api_intake.py --apply to initialise."
            ),
        }

    return {
        **base,
        "daily_reads_used":  int(daily_used),
        "within_limit":      int(daily_used) < daily_limit,
        "total_items":       total_items,
        "eligible_items":    status_counts.get("eligible", 0),
        "pending_items":     status_counts.get("pending", 0),
        "blocked_items":     status_counts.get("blocked", 0),
        "last_run":          last_run_row["ts"] if last_run_row else None,
        "last_run_endpoint": last_run_row["endpoint"] if last_run_row else None,
        "last_run_status":   last_run_row["status"] if last_run_row else None,
    }


@app.get("/api/x-api/items", tags=["x-api"])
async def x_api_items(
    limit: int = 50,
    item_type: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Return recent X API items from local DB.

    Does not call X API — reads local DB only.
    Blocked items are hidden by default; use ?status=blocked to see them.
    ?status= filters by processed_status (eligible|pending|blocked).
    If status is omitted, blocked items are excluded.
    """
    db_path = _x_api_db_path()
    if db_path is None:
        return {"status": "no_db", "items": [], "count": 0}

    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = _sqlite3.Row

    # Build WHERE conditions
    conditions: list[str] = []
    params: list[Any] = []

    if item_type:
        conditions.append("item_type=?")
        params.append(item_type)

    if status:
        conditions.append("processed_status=?")
        params.append(status)
    else:
        # Default: exclude blocked items from all Cortex views
        conditions.append("processed_status != 'blocked'")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(min(limit, 200))

    try:
        rows = conn.execute(
            f"SELECT * FROM x_items {where} ORDER BY fetched_at DESC LIMIT ?",
            params,
        ).fetchall()
    except _sqlite3.OperationalError:
        conn.close()
        return {"status": "no_db", "items": [], "count": 0}
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        item = {
            "x_item_id":               d["x_item_id"],
            "item_type":               d["item_type"],
            "author_handle":           d["author_handle"],
            "author_name":             d["author_name"],
            "text":                    (d["text"] or "")[:280],
            "url":                     d["url"],
            "created_at":              d["created_at"],
            "fetched_at":              d["fetched_at"],
            "processed_status":        d["processed_status"],
            "source":                  d["source"],
            "category":                d.get("category"),
            "work_relevance_score":    d.get("work_relevance_score"),
            "quality_flags":           d.get("quality_flags", "[]"),
            "classification_reason":   d.get("classification_reason"),
        }
        items.append(item)

    return {"status": "ok", "items": items, "count": len(items)}


_X_INSIGHTS_DB_CONTAINER = Path("/data/x_api/x_insights.sqlite")
_X_INSIGHTS_DB_HOST      = Path("/Users/bob/AI-Server/data/x_api/x_insights.sqlite")


def _x_insights_db_path() -> Path | None:
    if _X_INSIGHTS_DB_CONTAINER.exists():
        return _X_INSIGHTS_DB_CONTAINER
    if _X_INSIGHTS_DB_HOST.exists():
        return _X_INSIGHTS_DB_HOST
    return None


@app.get("/api/x-api/insights", tags=["x-api"])
async def x_api_insights(
    limit: int = 50,
    topic: str = "",
    insight_type: str = "",
) -> dict[str, Any]:
    """Return extracted X insights from local DB.

    Insights are derived from eligible x_items only — blocked/pending items
    are never sourced here.

    Query params:
      ?limit=       max results (default 50, max 200)
      ?topic=       filter by topic (smart_home|av|ai_ml|engineering|business|general)
      ?insight_type= filter by type (troubleshooting_tip|workflow_improvement|
                    product_idea|general_knowledge)
    """
    db_path = _x_insights_db_path()
    if db_path is None:
        return {"status": "no_db", "insights": [], "count": 0}

    import sqlite3 as _sqlite3
    import json as _json

    try:
        conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = _sqlite3.Row

        conditions: list[str] = []
        params: list[Any] = []
        if topic:
            conditions.append("topic=?")
            params.append(topic)
        if insight_type:
            conditions.append("insight_type=?")
            params.append(insight_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(min(limit, 200))

        rows = conn.execute(
            f"SELECT * FROM x_insights {where} "
            f"ORDER BY relevance_score DESC, extracted_at DESC LIMIT ?",
            params,
        ).fetchall()
        conn.close()
    except _sqlite3.OperationalError:
        return {"status": "no_db", "insights": [], "count": 0}

    insights = []
    for r in rows:
        d = dict(r)
        insights.append({
            "x_item_id":       d["x_item_id"],
            "topic":           d["topic"],
            "insight_type":    d["insight_type"],
            "summary":         d["summary"],
            "key_points":      _json.loads(d.get("key_points") or "[]"),
            "relevance_score": d["relevance_score"],
            "source_url":      d.get("source_url"),
            "author_handle":   d.get("author_handle"),
            "created_at":      d.get("created_at"),
            "extracted_at":    d["extracted_at"],
        })

    return {"status": "ok", "insights": insights, "count": len(insights)}


@app.post("/api/x-api/intake/dry-run", tags=["x-api"])
async def x_api_intake_dry_run(body: dict[str, Any] = {}) -> dict[str, Any]:
    """Preview what a live intake run would fetch — does not call X API or write to DB.

    Returns credential status, limit status, and a preview message.
    Actual intake runs via: python3 scripts/x_api_intake.py --apply
    """
    enabled  = os.environ.get("X_ENABLED", "0").strip() == "1"
    creds    = _x_api_creds_summary()
    db_path  = _x_api_db_path()
    limit    = int(os.environ.get("X_DAILY_READ_LIMIT", "100"))

    daily_used = 0
    if db_path:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_used = conn.execute(
            "SELECT COALESCE(SUM(request_count),0) FROM x_api_usage WHERE ts LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        conn.close()

    issues = []
    if not enabled:
        issues.append("X_ENABLED=0 — set X_ENABLED=1 to enable intake")
    if not creds["bearer_token"]:
        issues.append("X_API_BEARER_TOKEN not set")
    if not creds["user_id_configured"]:
        issues.append("X_USER_ID not set")
    if int(daily_used) >= limit:
        issues.append(f"Daily limit reached ({daily_used}/{limit})")

    return {
        "status":          "preview",
        "would_run":       len(issues) == 0,
        "issues":          issues,
        "enabled":         enabled,
        "credentials":     creds,
        "daily_reads_used": int(daily_used),
        "daily_reads_limit": limit,
        "run_command":     "python3 scripts/x_api_intake.py --apply --limit 25",
        "dry_run_command": "python3 scripts/x_api_intake.py --dry-run --limit 25",
        "should_auto_run": False,
    }


# ── Vault (metadata-only — no decryption in container) ────────────────────────

_VAULT_DB_CONTAINER = Path("/data/vault/vault.sqlite")
_VAULT_DB_HOST      = Path("/Users/bob/AI-Server/data/vault/vault.sqlite")


def _vault_db_path() -> Path | None:
    if _VAULT_DB_CONTAINER.is_file():
        return _VAULT_DB_CONTAINER
    if _VAULT_DB_HOST.is_file():
        return _VAULT_DB_HOST
    return None


def _vault_conn():
    """Return a read-only sqlite3 connection to the vault DB, or None."""
    import sqlite3
    p = _vault_db_path()
    if not p:
        return None
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/vault/secrets", tags=["vault"])
async def vault_secrets(category: str = "") -> dict[str, Any]:
    """List vault secrets — metadata only, never encrypted_value or plaintext."""
    conn = _vault_conn()
    if conn is None:
        return {
            "status":  "unavailable",
            "secrets": [],
            "warning": "Vault DB not found. Run: python3 scripts/vault_set_secret.py --init",
        }
    _debug = os.environ.get("CORTEX_DEBUG", "").lower() in {"1", "true", "yes"}
    try:
        query = (
            "SELECT name, category, sha256_fingerprint, access_policy, "
            "created_at, updated_at, last_accessed_at, notes "
            "FROM secrets"
        )
        params: tuple = ()
        if category:
            query += " WHERE category=?"
            params = (category,)
        query += " ORDER BY name"
        rows = conn.execute(query, params).fetchall()
        secrets = [dict(r) for r in rows]
    finally:
        conn.close()

    # Hide synthetic test entries in production; visible only with CORTEX_DEBUG=true.
    if not _debug:
        secrets = [s for s in secrets if not s.get("name", "").upper().startswith("TEST_")]

    return {
        "status":  "ok",
        "count":   len(secrets),
        "secrets": secrets,
    }


@app.get("/api/vault/secret/{name}", tags=["vault"])
async def vault_secret_meta(name: str) -> dict[str, Any]:
    """Return metadata for a single secret — no encrypted_value."""
    conn = _vault_conn()
    if conn is None:
        return {"status": "unavailable", "warning": "Vault DB not found."}
    try:
        row = conn.execute(
            "SELECT name, category, sha256_fingerprint, access_policy, "
            "created_at, updated_at, last_accessed_at, notes "
            "FROM secrets WHERE name=?",
            (name,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found.")
    return {"status": "ok", "secret": dict(row)}


@app.post("/api/vault/request-secret", tags=["vault"])
async def vault_request_secret(body: dict[str, Any] = {}) -> dict[str, Any]:
    """Log a pending access request to the vault audit log.

    The request must be approved and fulfilled by a human via vault_get_secret.py.
    This endpoint never returns decrypted values.
    """
    name      = str(body.get("name", "")).strip()
    requester = str(body.get("requester", "cortex")).strip()
    purpose   = str(body.get("purpose", "")).strip()

    if not name:
        return {"status": "error", "detail": "name is required"}

    conn = _vault_conn()
    if conn is None:
        return {"status": "unavailable", "warning": "Vault DB not found."}

    try:
        row = conn.execute(
            "SELECT secret_id, sha256_fingerprint FROM secrets WHERE name=?", (name,)
        ).fetchone()
        secret_exists = row is not None
        fp = row["sha256_fingerprint"] if row else None
    finally:
        conn.close()

    if not secret_exists:
        return {"status": "error", "detail": f"Secret '{name}' not found in vault."}

    # Append audit entry via the audit module (host-compatible path)
    try:
        from integrations.vault.audit import log as _audit_log
        _audit_log(
            event_type="request",
            secret_name=name,
            requester=requester,
            purpose=purpose or None,
            approved=None,
            fingerprint=fp,
        )
        logged = True
    except Exception as exc:
        logger.warning("vault request-secret audit log failed: %s", exc)
        logged = False

    return {
        "status":    "pending",
        "name":      name,
        "requester": requester,
        "purpose":   purpose,
        "logged":    logged,
        "fulfill":   f"python3 scripts/vault_get_secret.py --name {name} --reveal",
    }


# ── Watchdog Status ────────────────────────────────────────────────────────────

# Maps state-file basename → friendly service name.
# uh_{key} files mean the watchdog restarted that container; others are events.
_WD_SERVICE_NAMES: dict[str, str] = {
    "openclaw":           "OpenClaw",
    "polymarket-bot":     "Polymarket Bot",
    "vpn":                "VPN",
    "x-alpha-collector":  "X Alpha Collector",
    "docker":             "Docker engine",
    "x_intake":           "X Intake",
    "tailscale":          "Tailscale",
    "containers":         "Containers",
}

# Service dependency map — embedded so it's available inside the container
# without a separate volume mount. Mirrors ops/service_dependency_map.json.
# Keys use canonical service names (hyphens). State-file keys normalise
# underscore→hyphen before lookup (e.g. x_intake → x-intake).
_SERVICE_DEP_MAP: dict[str, dict] = {
    "redis": {
        "depends_on":       [],
        "impacts":          ["cortex", "x-intake", "openclaw", "clawwork", "notification-hub",
                             "polymarket-bot", "x-alpha-collector", "intel-feeds",
                             "client-portal", "proposals", "email-monitor",
                             "calendar-agent", "voice-receptionist", "dtools-bridge"],
        "impact_summary":   "All containers lose cache/queue; services reconnect automatically",
        "safe_check_command":    "docker compose ps redis",
        "safe_recovery_command": "scripts/safe-service-restart.sh redis",
        "risk_level":       "medium",
        "notes":            "Brief interruption to all dependents; they reconnect automatically.",
    },
    "cortex": {
        "depends_on":       ["redis", "ollama"],
        "impacts":          ["x-intake", "notification-hub", "client-portal",
                             "cortex-autobuilder", "proposals", "email-monitor", "calendar-agent"],
        "impact_summary":   "Reply drafting, client intel, and dashboard unavailable",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8102/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh cortex",
        "risk_level":       "low",
        "notes":            "Stateless — restarts cleanly.",
    },
    "x-intake": {
        "depends_on":       ["redis", "cortex", "bluebubbles"],
        "impacts":          ["reply suggestions", "message routing", "X.com ingestion"],
        "impact_summary":   "Incoming iMessages not processed; reply suggestions go stale",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8101/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh x-intake",
        "risk_level":       "low",
        "notes":            "Queue persisted in SQLite; messages not lost while down.",
    },
    "openclaw": {
        "depends_on":       ["redis", "clawwork", "bluebubbles"],
        "impacts":          ["voice-receptionist", "clawwork", "iMessage auto-response", "daily briefings"],
        "impact_summary":   "AI agents offline; auto-responder and briefings paused",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8099/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh openclaw",
        "risk_level":       "low",
        "notes":            "Stateless agent runner. Briefing state persisted.",
    },
    "clawwork": {
        "depends_on":       ["openclaw", "redis"],
        "impacts":          ["openclaw agents", "workflow automation"],
        "impact_summary":   "OpenClaw agents cannot execute multi-step workflows",
        "safe_check_command":    "docker compose ps clawwork",
        "safe_recovery_command": "scripts/safe-service-restart.sh clawwork",
        "risk_level":       "low",
        "notes":            "OpenClaw reconnects automatically after restart.",
    },
    "bluebubbles": {
        "depends_on":       [],
        "impacts":          ["x-intake", "openclaw", "voice-receptionist", "all iMessage I/O"],
        "impact_summary":   "All iMessage send/receive stops; Bob goes dark on iMessage",
        "safe_check_command":    "curl -fsS http://127.0.0.1:1234/api/v1/ping 2>/dev/null || echo 'BlueBubbles unreachable'",
        "safe_recovery_command": "open -a BlueBubbles",
        "risk_level":       "medium",
        "notes":            "Mac app — not a Docker container. Check Activity Monitor.",
    },
    "ollama": {
        "depends_on":       [],
        "impacts":          ["cortex LLM drafts", "x-intake analysis", "reply suggestions"],
        "impact_summary":   "AI draft generation falls back to templates; analysis degrades",
        "safe_check_command":    "curl -fsS http://127.0.0.1:11434/api/tags",
        "safe_recovery_command": "open -a Ollama",
        "risk_level":       "low",
        "notes":            "Cortex degrades gracefully to template replies when Ollama offline.",
    },
    "docker": {
        "depends_on":       [],
        "impacts":          ["ALL containers"],
        "impact_summary":   "All Docker services offline — complete system shutdown",
        "safe_check_command":    "docker ps",
        "safe_recovery_command": "scripts/docker-recover.sh",
        "risk_level":       "high",
        "notes":            "Only run docker-recover.sh if docker ps fails for 30+ seconds.",
    },
    "vpn": {
        "depends_on":       [],
        "impacts":          ["polymarket-bot"],
        "impact_summary":   "Polymarket trading paused (VPN-gated API unreachable)",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8430/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh vpn",
        "risk_level":       "low",
        "notes":            "Container-level WireGuard. Restart reconnects in seconds.",
    },
    "polymarket-bot": {
        "depends_on":       ["redis", "vpn"],
        "impacts":          ["prediction market positions"],
        "impact_summary":   "Polymarket trading paused; open positions maintained by exchange",
        "safe_check_command":    "docker compose ps polymarket-bot",
        "safe_recovery_command": "scripts/safe-service-restart.sh polymarket-bot",
        "risk_level":       "low",
        "notes":            "Positions held by Polymarket, not the bot.",
    },
    "notification-hub": {
        "depends_on":       ["redis", "cortex"],
        "impacts":          ["alert delivery", "system notifications"],
        "impact_summary":   "System alerts not delivered; silent failures possible",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8095/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh notification-hub",
        "risk_level":       "low",
        "notes":            None,
    },
    "voice-receptionist": {
        "depends_on":       ["openclaw", "redis"],
        "impacts":          ["inbound call handling", "voicemail"],
        "impact_summary":   "Inbound calls unanswered or go to default voicemail",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8093/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh voice-receptionist",
        "risk_level":       "low",
        "notes":            None,
    },
    "email-monitor": {
        "depends_on":       ["cortex"],
        "impacts":          ["email dashboard", "email alerts"],
        "impact_summary":   "Email dashboard goes stale; no new email alerts",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8092/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh email-monitor",
        "risk_level":       "low",
        "notes":            None,
    },
    "calendar-agent": {
        "depends_on":       ["cortex"],
        "impacts":          ["calendar dashboard", "meeting prep"],
        "impact_summary":   "Calendar dashboard goes stale",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8094/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh calendar-agent",
        "risk_level":       "low",
        "notes":            None,
    },
    "proposals": {
        "depends_on":       ["redis", "cortex"],
        "impacts":          ["client proposal generation"],
        "impact_summary":   "Proposal generation offline",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8091/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh proposals",
        "risk_level":       "low",
        "notes":            None,
    },
    "intel-feeds": {
        "depends_on":       ["redis", "rsshub"],
        "impacts":          ["market intelligence", "news feed dashboard"],
        "impact_summary":   "Intelligence feed goes stale",
        "safe_check_command":    "curl -fsS http://127.0.0.1:8765/health",
        "safe_recovery_command": "scripts/safe-service-restart.sh intel-feeds",
        "risk_level":       "low",
        "notes":            None,
    },
    "x-alpha-collector": {
        "depends_on":       ["redis"],
        "impacts":          ["X.com intelligence collection"],
        "impact_summary":   "X.com data collection paused; feed goes stale",
        "safe_check_command":    "docker compose ps x-alpha-collector",
        "safe_recovery_command": "scripts/safe-service-restart.sh x-alpha-collector",
        "risk_level":       "low",
        "notes":            None,
    },
    "tailscale": {
        "depends_on":       [],
        "impacts":          ["remote dashboard access", "remote SSH"],
        "impact_summary":   "Remote access to Bob unavailable (local access unaffected)",
        "safe_check_command":    "tailscale status",
        "safe_recovery_command": "sudo tailscale up",
        "risk_level":       "medium",
        "notes":            "Check 'tailscale status' before running 'tailscale up'.",
    },
    "containers": {
        "depends_on":       ["docker"],
        "impacts":          ["all containers affected by last recovery event"],
        "impact_summary":   "Watchdog performed a bulk container recovery",
        "safe_check_command":    "docker ps --format 'table {{.Names}}\\t{{.Status}}'",
        "safe_recovery_command": "docker compose up -d",
        "risk_level":       "medium",
        "notes":            "Reflects a watchdog-level recovery event, not a single service.",
    },
    "task-runner": {
        "depends_on":       ["docker"],
        "impacts":          ["scheduled tasks", "self-improvement loop", "state file updates"],
        "impact_summary":   "Automated tasks paused; state files go stale",
        "safe_check_command":    "cat data/task_runner/bob_watchdog_heartbeat.txt",
        "safe_recovery_command": "launchctl start com.bob.task-runner",
        "risk_level":       "low",
        "notes":            "Host-level LaunchDaemon. Check heartbeat file age.",
    },
    "bob-watchdog": {
        "depends_on":       ["docker", "task-runner"],
        "impacts":          ["auto-recovery", "container monitoring"],
        "impact_summary":   "No automatic container recovery while watchdog is offline",
        "safe_check_command":    "cat data/task_runner/watchdog_heartbeat.txt",
        "safe_recovery_command": "launchctl start com.bob.watchdog",
        "risk_level":       "low",
        "notes":            "Host-level LaunchDaemon.",
    },
}

# How many seconds after a watchdog intervention before we consider it resolved.
# 1 hour: if a service was restarted and has been running since, it's recovered.
_WD_STALE_SECS = 1 * 3600


def _dep_map_lookup(key: str) -> dict | None:
    """Look up a service in _SERVICE_DEP_MAP, normalising state-file key format.

    State files use underscores (x_intake) while the dep map uses hyphens
    (x-intake). Also tries the key as-is.
    """
    canonical = key.replace("_", "-")
    return _SERVICE_DEP_MAP.get(canonical) or _SERVICE_DEP_MAP.get(key)


def _enrich_with_deps(services: list[dict]) -> list[dict]:
    """Add dependency/impact/recovery fields to each degraded service record.

    For ok services, fields are omitted to keep the payload small.
    Recovery actions are suggestions only — should_auto_run is always False.
    """
    enriched = []
    for svc in services:
        rec = dict(svc)
        if svc["state"] == "degraded":
            info = _dep_map_lookup(svc["key"])
            if info:
                rec["dependencies"]        = info.get("depends_on", [])
                rec["downstream_impacts"]  = info.get("impacts", [])
                rec["impact_summary"]      = info.get("impact_summary", "")
                rec["suggested_checks"]    = [info["safe_check_command"]] if info.get("safe_check_command") else []
                rec["suggested_recovery"]  = info.get("safe_recovery_command", "")
                rec["recovery_risk"]       = info.get("risk_level", "unknown")
                rec["recovery_notes"]      = info.get("notes") or ""
                rec["should_auto_run"]     = False
            else:
                rec["dependencies"]        = []
                rec["downstream_impacts"]  = []
                rec["impact_summary"]      = ""
                rec["suggested_checks"]    = []
                rec["suggested_recovery"]  = ""
                rec["recovery_risk"]       = "unknown"
                rec["recovery_notes"]      = ""
                rec["should_auto_run"]     = False
        enriched.append(rec)
    return enriched


def _read_watchdog_state() -> dict[str, Any]:
    """Parse bob-watchdog-state/* into a list of service records.

    Files named uh_{service} contain Unix epoch timestamps of the last
    unhealthy+restart event for that service.  Other files (docker, x_intake,
    tailscale, containers) log recovery events.  required_source is metadata.

    Returns {"services": [...], "degraded_count": int, "updated_at": str|None,
             "warning": str|None}.
    """
    import time as _time

    now = _time.time()
    services: list[dict[str, Any]] = []
    warning: str | None = None

    if not _WATCHDOG_STATE_DIR.is_dir():
        warning = "No watchdog state directory found."
        return {"services": [], "degraded_count": 0, "updated_at": None, "warning": warning}

    state_files = [p for p in _WATCHDOG_STATE_DIR.iterdir() if p.is_file()]
    if not state_files:
        warning = "No watchdog state files found."
        return {"services": [], "degraded_count": 0, "updated_at": None, "warning": warning}

    for path in sorted(state_files):
        name = path.name
        if name == "required_source":
            continue  # metadata file, not a service

        raw = path.read_text(encoding="utf-8").strip()
        try:
            ts = float(raw)
        except (ValueError, OSError):
            continue  # malformed — skip silently

        age_secs = now - ts
        is_recent = age_secs < _WD_STALE_SECS

        # Resolve service key and display name
        if name.startswith("uh_"):
            key = name[3:]  # strip "uh_"
            event_type = "restart"
        else:
            key = name
            event_type = "recovery"

        display_name = _WD_SERVICE_NAMES.get(key, key)
        last_seen_iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        age_h = age_secs / 3600

        if is_recent:
            state = "degraded"
            severity = "high" if age_h < 0.5 else "medium"
            details = f"Watchdog {event_type} {age_h:.1f}h ago"
        else:
            state = "ok"
            severity = "low"
            details = f"Last watchdog action {age_h:.0f}h ago"

        services.append({
            "name":       display_name,
            "key":        key,
            "state":      state,
            "severity":   severity,
            "event_type": event_type,
            "last_seen":  last_seen_iso,
            "details":    details,
        })

    degraded_count = sum(1 for s in services if s["state"] == "degraded")

    # Read heartbeat for updated_at
    updated_at: str | None = None
    if _WATCHDOG_HEARTBEAT.is_file():
        try:
            updated_at = _WATCHDOG_HEARTBEAT.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    return {
        "services":       services,
        "degraded_count": degraded_count,
        "updated_at":     updated_at,
        "warning":        warning,
    }


@app.get("/api/watchdog/status", tags=["watchdog"])
async def watchdog_status() -> dict[str, Any]:
    """Return current watchdog service states from state files.

    Reads data/task_runner/bob-watchdog-state/* (mounted read-only in
    container).  Does not run Docker commands or modify any state.
    Returns status=ok even when degraded; degraded_count signals UI severity.
    """
    try:
        state = _read_watchdog_state()
    except Exception as exc:
        logger.exception("watchdog_status failed: %s", exc)
        return {
            "status":         "error",
            "services":       [],
            "degraded_count": 0,
            "updated_at":     None,
            "warning":        f"Failed to read watchdog state: {exc}",
        }

    overall = "degraded" if state["degraded_count"] > 0 else "ok"
    return {
        "status":         overall,
        "services":       _enrich_with_deps(state["services"]),
        "degraded_count": state["degraded_count"],
        "updated_at":     state["updated_at"],
        "warning":        state["warning"],
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    uvicorn.run(
        "cortex.engine:app",
        host="0.0.0.0",
        port=CORTEX_PORT,
        log_level=CORTEX_LOG_LEVEL.lower(),
    )
