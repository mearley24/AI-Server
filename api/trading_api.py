#!/usr/bin/env python3
"""
trading_api.py - Trading-focused API process for Clawdbot/Polymarket/Crypto.

Run:
    python3 api/trading_api.py

Default:
    http://localhost:8421
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "api"))

try:
    from api.common_api_utils import run_command
except ModuleNotFoundError:
    from common_api_utils import run_command

API_PORT = int(os.environ.get("TRADING_API_PORT", "8421"))
CURATOR_DB = BASE_DIR / "data" / "cortex_curator.db"
TRADING_CORTEX_ROOT = BASE_DIR / "knowledge" / "cortex" / "trading"
TRADING_CATEGORIES = {"clawdbot", "polymarket", "crypto", "trading", "market-intel"}

app = FastAPI(
    title="Symphony Trading API",
    description="Trading-only API with shared Cortex tooling",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now().isoformat()


def read_json_file(path: Path, fallback: dict) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return fallback


def connect_curator_db() -> sqlite3.Connection:
    conn = sqlite3.connect(CURATOR_DB)
    conn.row_factory = sqlite3.Row
    return conn


def trading_source_where_clause() -> str:
    return "s.path LIKE 'knowledge/cortex/trading/%'"


def ensure_trading_category(category: str) -> str:
    clean = (category or "").strip().lower()
    if clean not in TRADING_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of: {', '.join(sorted(TRADING_CATEGORIES))}",
        )
    return clean


def ingest_trading_fact(text: str, category: str) -> dict:
    text = text.strip()
    if not text:
        return {"success": False, "error": "Empty text"}

    cat = ensure_trading_category(category)
    out_dir = TRADING_CORTEX_ROOT / cat
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"manual_{stamp}.md"
    out_path.write_text(
        f"# Trading fact - {cat}\n\n"
        f"*Ingested: {now_iso()}*\n\n"
        f"---\n\n"
        f"{text}\n",
        encoding="utf-8",
    )
    return {
        "success": True,
        "path": str(out_path.relative_to(BASE_DIR)),
        "category": cat,
        "chars": len(text),
    }


def list_trading_review_facts(limit: int = 50, offset: int = 0, status: str = "review") -> dict:
    if not CURATOR_DB.exists():
        return {"success": True, "total": 0, "items": [], "status_filter": status, "limit": limit, "offset": offset}

    status = status if status in {"review", "trusted"} else "review"
    conn = connect_curator_db()
    where_source = trading_source_where_clause()
    count_row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT f.id) AS c
        FROM facts f
        JOIN fact_sources fs ON fs.fact_id = f.id
        JOIN sources s ON s.id = fs.source_id
        WHERE {where_source} AND f.status = ?
        """,
        (status,),
    ).fetchone()
    total = int(count_row["c"]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT DISTINCT
            f.id,
            f.representative_text,
            f.subject_key,
            f.confidence,
            f.source_count,
            f.contradiction_count,
            f.domain_score,
            f.reasoning_score,
            f.troubleshooting_score,
            f.status,
            f.last_seen
        FROM facts f
        JOIN fact_sources fs ON fs.fact_id = f.id
        JOIN sources s ON s.id = fs.source_id
        WHERE {where_source} AND f.status = ?
        ORDER BY f.contradiction_count DESC, f.confidence ASC, f.id DESC
        LIMIT ? OFFSET ?
        """,
        (status, int(limit), int(offset)),
    ).fetchall()
    conn.close()
    return {
        "success": True,
        "status_filter": status,
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "items": [
            {
                "id": int(r["id"]),
                "fact": str(r["representative_text"]),
                "subject": str(r["subject_key"]),
                "confidence": float(r["confidence"]),
                "source_count": int(r["source_count"]),
                "contradictions": int(r["contradiction_count"]),
                "domain_score": float(r["domain_score"]),
                "reasoning_score": float(r["reasoning_score"]),
                "troubleshooting_score": float(r["troubleshooting_score"]),
                "professional_score": round(
                    float(r["domain_score"]) + float(r["reasoning_score"]) + float(r["troubleshooting_score"]),
                    3,
                ),
                "status": str(r["status"]),
                "last_seen": str(r["last_seen"]),
            }
            for r in rows
        ],
    }


def trading_curator_status() -> dict:
    if not CURATOR_DB.exists():
        return {
            "success": True,
            "timestamp": now_iso(),
            "scope": "trading",
            "root_path": str(TRADING_CORTEX_ROOT.relative_to(BASE_DIR)),
            "total_facts": 0,
            "trusted_facts": 0,
            "review_facts": 0,
            "contradiction_pairs": 0,
            "total_sources": 0,
            "last_indexed": None,
            "review_queue": [],
        }

    conn = connect_curator_db()
    where_source = trading_source_where_clause()
    totals = conn.execute(
        f"""
        SELECT
            COUNT(DISTINCT f.id) AS total_facts,
            COUNT(DISTINCT CASE WHEN f.status = 'trusted' THEN f.id END) AS trusted_facts,
            COUNT(DISTINCT CASE WHEN f.status = 'review' THEN f.id END) AS review_facts,
            COUNT(DISTINCT s.id) AS total_sources,
            MAX(s.last_indexed) AS last_indexed
        FROM facts f
        JOIN fact_sources fs ON fs.fact_id = f.id
        JOIN sources s ON s.id = fs.source_id
        WHERE {where_source}
        """
    ).fetchone()
    contradiction_row = conn.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM contradictions c
        WHERE c.fact_id_a IN (
            SELECT DISTINCT f.id
            FROM facts f
            JOIN fact_sources fs ON fs.fact_id = f.id
            JOIN sources s ON s.id = fs.source_id
            WHERE {where_source}
        )
        AND c.fact_id_b IN (
            SELECT DISTINCT f.id
            FROM facts f
            JOIN fact_sources fs ON fs.fact_id = f.id
            JOIN sources s ON s.id = fs.source_id
            WHERE {where_source}
        )
        """
    ).fetchone()
    conn.close()

    review_queue = list_trading_review_facts(limit=10, offset=0, status="review").get("items", [])
    return {
        "success": True,
        "timestamp": now_iso(),
        "scope": "trading",
        "root_path": str(TRADING_CORTEX_ROOT.relative_to(BASE_DIR)),
        "total_facts": int(totals["total_facts"]) if totals else 0,
        "trusted_facts": int(totals["trusted_facts"]) if totals else 0,
        "review_facts": int(totals["review_facts"]) if totals else 0,
        "contradiction_pairs": int(contradiction_row["c"]) if contradiction_row else 0,
        "total_sources": int(totals["total_sources"]) if totals else 0,
        "last_indexed": totals["last_indexed"] if totals else None,
        "review_queue": review_queue,
    }


class ResearchRequest(BaseModel):
    query: str


class TradingFactsLearnRequest(BaseModel):
    text: str
    category: str = "trading"
    curate_now: bool = True


class CuratorRunRequest(BaseModel):
    limit: int = 0
    force: bool = False


class CuratorFactStatusRequest(BaseModel):
    fact_ids: list[int]
    status: str = "review"


@app.get("/")
async def root():
    return {
        "name": "Symphony Trading API",
        "status": "running",
        "scope": ["clawdbot", "polymarket", "crypto", "trading", "market-intel"],
        "timestamp": now_iso(),
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": now_iso()}


@app.get("/portfolio")
async def get_portfolio():
    portfolio_file = BASE_DIR / "knowledge" / "portfolio.json"
    return read_json_file(portfolio_file, {"error": "No portfolio found"})


@app.get("/portfolio/goal")
async def get_portfolio_goal():
    goal_file = BASE_DIR / "knowledge" / "goals" / "beatrice_upgrade.json"
    fallback = {
        "goal": "Trading growth target",
        "target_amount": 3649,
        "current_amount": 0,
        "status": "in_progress",
    }
    data = read_json_file(goal_file, fallback)
    # Normalize legacy keys for iOS decoding compatibility.
    if "target" in data and "target_amount" not in data:
        data["target_amount"] = data["target"]
    if "current" in data and "current_amount" not in data:
        data["current_amount"] = data["current"]
    return data


@app.get("/invest/scan")
async def invest_scan():
    """Scan trading opportunities (Polymarket + trend view)."""
    result = run_command(
        ["python3", str(BASE_DIR / "tools" / "market_intel.py"), "--polymarket"],
        timeout=120,
        cwd=BASE_DIR,
    )
    return result


@app.post("/invest/research")
async def invest_research(request: ResearchRequest):
    result = run_command(
        ["python3", str(BASE_DIR / "tools" / "market_intel.py"), "--research", request.query],
        timeout=120,
        cwd=BASE_DIR,
    )
    return result


@app.get("/memory/categories")
async def memory_categories():
    return {"categories": sorted(TRADING_CATEGORIES)}


@app.post("/memory/facts/learn")
async def memory_facts_learn(request: TradingFactsLearnRequest):
    try:
        result = ingest_trading_fact(request.text, request.category)
        if result.get("success") and request.curate_now:
            from tools.cortex_curator import run_curator

            curated = run_curator(limit=1, contains="knowledge/cortex/trading", force=True)
            result["curator"] = {
                "indexed_files": curated.get("indexed_files", 0),
                "new_facts": curated.get("new_facts", 0),
                "updated_facts": curated.get("updated_facts", 0),
            }
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/curator/run")
async def memory_curator_run(request: CuratorRunRequest):
    try:
        from tools.cortex_curator import run_curator

        return run_curator(
            limit=request.limit if request.limit > 0 else None,
            force=request.force,
            contains="knowledge/cortex/trading",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/curator/status")
async def memory_curator_status():
    try:
        return trading_curator_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/curator/review")
async def memory_curator_review(
    status: str = "review",
    limit: int = 50,
    offset: int = 0,
):
    try:
        return list_trading_review_facts(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
            status=status,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/curator/facts/status")
async def memory_curator_set_status(request: CuratorFactStatusRequest):
    """Set status for trading-scoped fact IDs only."""
    status = request.status.strip().lower()
    if status not in {"review", "trusted"}:
        raise HTTPException(status_code=400, detail="status must be 'review' or 'trusted'")
    if not request.fact_ids:
        raise HTTPException(status_code=400, detail="No fact IDs provided")

    if not CURATOR_DB.exists():
        raise HTTPException(status_code=404, detail="Curator DB not found")

    conn = connect_curator_db()
    where_source = trading_source_where_clause()
    rows = conn.execute(
        f"""
        SELECT DISTINCT f.id
        FROM facts f
        JOIN fact_sources fs ON fs.fact_id = f.id
        JOIN sources s ON s.id = fs.source_id
        WHERE {where_source} AND f.id IN ({",".join("?" for _ in request.fact_ids)})
        """,
        [int(x) for x in request.fact_ids],
    ).fetchall()
    allowed_ids = {int(r["id"]) for r in rows}
    missing = [int(fid) for fid in request.fact_ids if int(fid) not in allowed_ids]
    updated = 0
    for fid in allowed_ids:
        conn.execute("UPDATE facts SET status = ? WHERE id = ?", (status, int(fid)))
        updated += 1
    conn.commit()
    conn.close()
    return {
        "success": True,
        "updated": updated,
        "missing_ids": missing,
        "status_set_to": status,
        "summary": trading_curator_status(),
    }


def main() -> None:
    print(
        f"""
╔══════════════════════════════════════════════════╗
║     Symphony Trading API                         ║
║     http://localhost:{API_PORT}                         ║
╠══════════════════════════════════════════════════╣
║  Trading endpoints:                              ║
║    GET  /portfolio                               ║
║    GET  /portfolio/goal                          ║
║    GET  /invest/scan                             ║
║    POST /invest/research                         ║
║  Trading memory endpoints:                       ║
║    POST /memory/facts/learn                      ║
║    GET  /memory/curator/status                   ║
║    GET  /memory/curator/review                   ║
╚══════════════════════════════════════════════════╝
"""
    )
    uvicorn.run(app, host="127.0.0.1", port=API_PORT)


if __name__ == "__main__":
    main()
