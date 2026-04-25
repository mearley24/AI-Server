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


# ── Relationship Profiles ──────────────────────────────────────────────────────

_PROFILES_DB     = _CLIENT_INTEL_DB.parent / "client_profiles.sqlite"
_FACTS_DB        = _CLIENT_INTEL_DB.parent / "proposed_facts.sqlite"


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


def _build_draft_with_context(
    profile: dict,
    accepted_by_type: dict[str, list[dict]],
    unverified_by_type: dict[str, list[dict]],
    recent_replies: list[dict],
    last_message: str = "",
) -> dict[str, Any]:
    """Build a draft reply with reasoning, confidence, and source_facts.

    Priority order:
      1. Accepted issue + equipment facts  → service-call draft
      2. Accepted request + equipment      → follow-up on request
      3. Open requests from profile        → generic follow-up
      4. Accepted equipment / system       → system check-in
      5. Unverified issue / request        → cautious follow-up
      6. Relationship-type fallback
    Never hallucinates: only references facts that are explicitly present.
    Rejected facts are already excluded upstream (is_rejected=0 SQL filter).
    Pending facts used only as secondary signal; confidence capped at 0.75.
    """
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
    #   - Diagnostic questions only when no history exists and cause is ambiguous.
    #   - Tone: confident, personal, direct — sounds like someone who knows the system.
    draft: str
    confidence: float

    repeat_issue = len(accepted_issues) > 1   # recurring pattern

    if accepted_issues and accepted_equip:
        issue = accepted_issues[0][:80]
        eq    = accepted_equip[0]
        if repeat_issue:
            # History shows this has happened before — acknowledge it directly.
            draft = (
                f"I see this has come up before with your {eq}. "
                f"I'll take a look and get to the bottom of it — "
                f"I'll let you know what I find."
            )
        else:
            # First reported issue — proactive, no diagnostic questions.
            draft = (
                f"On it — I'll check your {eq} and see what's going on. "
                f"I'll let you know what I find."
            )
        reasoning_parts += [
            f"{'Recurring' if repeat_issue else 'Active'} issue: '{issue}'",
            f"Equipment on file: '{eq}'",
        ]
        confidence = 0.90

    elif accepted_issues:
        # Issue known, equipment not yet identified — still proactive.
        draft = "Got it — I'll look into this and get back to you with what I find."
        reasoning_parts.append(f"Active issue: '{accepted_issues[0][:80]}'")
        confidence = 0.85

    elif accepted_requests and accepted_equip:
        req = accepted_requests[0][:70]
        eq  = accepted_equip[0]
        draft = (
            f"I'll take a look at your {eq} — "
            f"sounds like {req}. I'll reach out once I have an update."
        )
        reasoning_parts += [f"Request: '{req}'", f"Equipment: '{eq}'"]
        confidence = 0.85

    elif open_reqs:
        req = open_reqs[0][:80]
        draft = f"On it — I'll look into {req} and get back to you."
        reasoning_parts.append(f"Open request from profile: '{req}'")
        confidence = 0.75

    elif accepted_equip:
        # No current issues — short personal check-in, not a support-desk question.
        eq = accepted_equip[0]
        draft = f"Checking in on your {eq} — everything holding up okay?"
        reasoning_parts.append(f"Equipment on file: '{eq}'")
        confidence = 0.70

    elif systems:
        sys_name = systems[0]
        draft = f"Hey, checking in on your {sys_name} — anything I can help with?"
        reasoning_parts.append(f"System from profile: '{sys_name}'")
        confidence = 0.65

    elif unverified_issues:
        # Pending facts only — cautious tone, open-ended.
        issue = unverified_issues[0][:80]
        draft = (
            f"Hey, just checking in — still having trouble with {issue}? "
            f"Happy to take a look."
        )
        reasoning_parts.append(f"Unverified issue (pending approval): '{issue}'")
        confidence = 0.50

    elif rel_type == "client" and not (open_reqs or systems):
        # No history at all — only situation where a clarifying question is appropriate.
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

    return {
        "draft_reply":  draft,
        "reasoning":    "; ".join(reasoning_parts) or "No facts available.",
        "confidence":   round(confidence, 2),
        "source_facts": source_facts[:8],
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

    import secrets as _secrets
    receipts = _receipts_for_handle(handle)
    action   = _suggest_action(accepted_by_type, profile["relationship_type"])
    built    = _build_draft_with_context(
        profile=profile,
        accepted_by_type=accepted_by_type,
        unverified_by_type=unverified_by_type,
        recent_replies=receipts,
    )
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
        "draft_reply":           built["draft_reply"],
        "reasoning":             built["reasoning"],
        "confidence":            built["confidence"],
        "source_facts":          built["source_facts"],
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

    action_id     = str(body.get("action_id", "")).strip()
    draft_reply   = str(body.get("draft_reply", "")).strip()
    edited_reply  = str(body.get("edited_reply", "")).strip()
    contact_masked = str(body.get("contact_masked", "")).strip()
    reasoning     = str(body.get("reasoning", "")).strip()
    confidence    = float(body.get("confidence", 0.0))

    if not action_id:
        return {"status": "error", "error": "action_id required"}

    final_reply = edited_reply if edited_reply else draft_reply
    if not final_reply:
        return {"status": "error", "error": "draft_reply or edited_reply required"}

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

    receipts = _receipts_for_handle(handle)
    action   = _suggest_action(accepted_by_type, profile["relationship_type"])
    built    = _build_draft_with_context(
        profile=profile,
        accepted_by_type=accepted_by_type,
        unverified_by_type=unverified_by_type,
        recent_replies=receipts,
        last_message=last_message,
    )
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
        "draft_reply":           built["draft_reply"],
        "reasoning":             built["reasoning"],
        "confidence":            built["confidence"],
        "source_facts":          built["source_facts"],
        "simulated":             True,
        "last_message":          last_message or None,
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    uvicorn.run(
        "cortex.engine:app",
        host="0.0.0.0",
        port=CORTEX_PORT,
        log_level=CORTEX_LOG_LEVEL.lower(),
    )
