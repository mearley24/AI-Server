"""Knowledge Scanner — FastAPI app + background scanner service."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, Query

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

# Config from environment
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
SCAN_INTERVAL_HOURS = float(os.environ.get("SCAN_INTERVAL_HOURS", "6"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "knowledge.db"

_scanner_task: asyncio.Task | None = None


def _init_db() -> None:
    """Create the knowledge database if it doesn't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            category TEXT NOT NULL,
            insight TEXT NOT NULL,
            source_summary TEXT,
            relevance_score INTEGER DEFAULT 5,
            created_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_relevance ON knowledge(relevance_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge(created_at)")
    conn.commit()
    conn.close()


def _store_insights(insights: list[dict]) -> int:
    """Store processed insights in SQLite. Returns count stored."""
    if not insights:
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now(timezone.utc).isoformat()
    stored = 0
    for entry in insights:
        try:
            conn.execute(
                "INSERT INTO knowledge (topic, category, insight, source_summary, relevance_score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.get("topic", "Unknown"),
                    entry.get("category", "general"),
                    entry.get("insight", ""),
                    entry.get("source_summary", ""),
                    int(entry.get("relevance_score", 5)),
                    now,
                ),
            )
            stored += 1
        except Exception as exc:
            logger.error("store_insight_error", error=str(exc))
    conn.commit()
    conn.close()
    return stored


async def _publish_high_relevance(insights: list[dict]) -> None:
    """Publish high-relevance findings (score >= 7) to Redis notifications."""
    high_relevance = [i for i in insights if int(i.get("relevance_score", 0)) >= 7]
    if not high_relevance:
        return

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        for item in high_relevance:
            await client.publish(
                "notifications:knowledge",
                json.dumps({
                    "topic": item.get("topic", ""),
                    "category": item.get("category", ""),
                    "insight": item.get("insight", ""),
                    "relevance_score": item.get("relevance_score", 0),
                }),
            )
        await client.aclose()
        logger.info("redis_published", count=len(high_relevance))
    except ImportError:
        logger.debug("redis_not_available", reason="redis package not installed")
    except Exception as exc:
        logger.debug("redis_publish_error", error=str(exc))


async def _run_scan() -> dict[str, Any]:
    """Execute a single scan cycle."""
    from scanner import scan_topics
    from processor import process_results

    logger.info("scan_starting")

    raw_results = await scan_topics(PERPLEXITY_API_KEY)
    if not raw_results:
        logger.info("scan_no_results")
        return {"raw": 0, "processed": 0, "stored": 0}

    insights = await process_results(raw_results, ANTHROPIC_API_KEY)
    stored = _store_insights(insights)
    await _publish_high_relevance(insights)

    logger.info("scan_complete", raw=len(raw_results), processed=len(insights), stored=stored)
    return {"raw": len(raw_results), "processed": len(insights), "stored": stored}


async def _scanner_loop() -> None:
    """Background loop that runs scans on the configured interval."""
    interval = SCAN_INTERVAL_HOURS * 3600
    while True:
        try:
            await _run_scan()
        except Exception as exc:
            logger.error("scanner_loop_error", error=str(exc))
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background scanner on app startup."""
    global _scanner_task
    _init_db()

    if PERPLEXITY_API_KEY and ANTHROPIC_API_KEY:
        logger.info("scanner_enabled", interval_hours=SCAN_INTERVAL_HOURS)
        _scanner_task = asyncio.create_task(_scanner_loop())
    else:
        missing = []
        if not PERPLEXITY_API_KEY:
            missing.append("PERPLEXITY_API_KEY")
        if not ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        logger.warning("scanning_disabled", missing_keys=missing)

    yield

    if _scanner_task:
        _scanner_task.cancel()
        try:
            await _scanner_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Knowledge Scanner", lifespan=lifespan)


@app.get("/health")
async def health():
    scanning = bool(PERPLEXITY_API_KEY and ANTHROPIC_API_KEY)
    return {"status": "healthy", "service": "knowledge-scanner", "scanning_enabled": scanning}


@app.get("/knowledge")
async def list_knowledge(
    category: str | None = Query(None, description="Filter by category"),
    min_relevance: int = Query(1, ge=1, le=10, description="Minimum relevance score"),
    limit: int = Query(50, ge=1, le=200),
):
    """List recent knowledge entries."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM knowledge WHERE relevance_score >= ?"
    params: list[Any] = [min_relevance]

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return {"entries": [dict(r) for r in rows], "count": len(rows)}


@app.get("/knowledge/summary")
async def knowledge_summary():
    """Today's intelligence summary."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM knowledge WHERE created_at >= ? ORDER BY relevance_score DESC",
        (today,),
    ).fetchall()
    conn.close()

    entries = [dict(r) for r in rows]
    categories: dict[str, int] = {}
    for e in entries:
        cat = e.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "date": today,
        "total_entries": len(entries),
        "by_category": categories,
        "top_insights": entries[:10],
    }


@app.post("/scan")
async def trigger_scan():
    """Trigger an immediate scan cycle (for testing)."""
    if not PERPLEXITY_API_KEY:
        return {"status": "skipped", "reason": "PERPLEXITY_API_KEY not set"}
    result = await _run_scan()
    return {"status": "complete", **result}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
