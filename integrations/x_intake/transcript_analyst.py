"""
transcript_analyst.py
--------------------
Deep AI analysis pipeline for saved video transcripts.

Reads .md transcript files written by video_transcriber.save_transcript(),
runs a broader multi-angle analysis to extract hidden gems and actionable
insights, then POSTs structured results to Cortex memory via POST /remember.

Tracks which transcripts have been processed in the x_intake queue DB
(analyzed column) to avoid duplicate reprocessing.

Usage:
  - Called automatically from main.py after each new successful transcription.
  - POST /transcripts/backfill  triggers a scan of all unanalyzed transcripts.
  - GET  /transcripts/stats     returns discovered/analyzed/failed counts.

Ollama is tried first (free, local); GPT-4o-mini is the fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

TRANSCRIPT_DIR = Path(os.environ.get("TRANSCRIPT_DIR", "/data/transcripts"))
CORTEX_URL = os.environ.get("CORTEX_URL", "http://cortex:8102")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434")
OLLAMA_ANALYSIS_MODEL = os.environ.get("OLLAMA_ANALYSIS_MODEL", "qwen3:8b")

_ANALYSIS_DB_PATH = Path(os.environ.get("X_INTAKE_DB", "/data/x_intake/queue.db"))

# ── Analysis prompt ───────────────────────────────────────────────────────────

_DEEP_PROMPT = """You are analyzing a video transcript for Matt Earley, owner of Symphony Smart Homes in the Vail Valley, CO.

Matt's interests: AI agents, autonomous systems, LLMs, MCP/tool-calling, Docker/self-hosting, home automation (Control4/Lutron/Crestron), trading bots, Polymarket prediction markets, business automation, proposal generation, revenue automation, Cursor IDE, coding agents.

Analyze this content and return ONLY valid JSON with these exact keys:

{
  "summary": "3-5 sentence summary of what this content is TRULY about — the real message beyond the surface topic",
  "key_topics": ["list of 3-8 specific topics, techniques, or concepts covered"],
  "hidden_gems": [
    {"insight": "surprising or counterintuitive finding most people would miss", "why_it_matters": "why this is specifically valuable to Matt"}
  ],
  "actionable_tasks": [
    {"task": "specific thing Matt could build, implement, or investigate", "category": "build|research|implement|investigate|warning", "priority": "high|medium|low"}
  ],
  "content_ideas": ["angle or hook for an X post or client education piece based on this content"],
  "tags": ["3-8 topic tags"],
  "usefulness_score": 0,
  "confidence": 0.0
}

Rules:
- hidden_gems: focus on insights NOT obvious from the headline. What would a sharp operator extract that most viewers miss?
- actionable_tasks: be specific. Not "look into AI" but "implement the [specific technique] from this video using [specific approach]"
- usefulness_score: integer 0-100. How useful to Matt specifically? 80+ = high priority, 50-79 = worth reading, below 50 = low value
- confidence: float 0.0-1.0. How complete and usable was the transcript?
- If transcript is too short or garbled (e.g. only "🎵"), set usefulness_score=0 and note in summary.

Content from @{author}:
{body}
"""

# ── Markdown parser ───────────────────────────────────────────────────────────


def _parse_transcript_md(md_path: Path) -> dict:
    """Parse a transcript .md file into structured data."""
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("transcript_read_failed: %s %s", md_path.name, str(exc)[:80])
        return {}

    result: dict = {
        "author": "",
        "post_id": "",
        "summary": "",
        "flags": [],
        "strategies": [],
        "key_quotes": [],
        "transcript": "",
        "raw_content": content,
    }

    # Author from filename: "@author — topic — date.md"
    author_match = re.match(r"@(\w+)", md_path.stem)
    if author_match:
        result["author"] = author_match.group(1)

    pid_match = re.search(r"Post ID:\s*(\d+)", content)
    if pid_match:
        result["post_id"] = pid_match.group(1)

    sum_match = re.search(r"## Summary\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if sum_match:
        result["summary"] = sum_match.group(1).strip()

    trans_match = re.search(r"## Full Transcript\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if trans_match:
        result["transcript"] = trans_match.group(1).strip()

    flags_match = re.search(r"## Flags\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if flags_match:
        for line in flags_match.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("-"):
                result["flags"].append(line[1:].strip())

    strat_match = re.search(r"## Strategies\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if strat_match:
        result["strategies"] = strat_match.group(1).strip()

    quotes_match = re.search(r"## Key Quotes\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if quotes_match:
        for line in quotes_match.group(1).strip().splitlines():
            line = line.strip().lstrip(">").strip()
            if line:
                result["key_quotes"].append(line)

    return result


def _build_prompt(data: dict) -> str:
    """Build the deep analysis prompt from parsed transcript data."""
    author = data.get("author", "unknown")
    transcript = data.get("transcript", "").strip()
    existing_summary = data.get("summary", "")
    flags = data.get("flags", [])
    quotes = data.get("key_quotes", [])
    strategies = data.get("strategies", "")

    parts = []
    if existing_summary:
        parts.append(f"Existing summary (from first-pass analysis):\n{existing_summary}")
    if flags:
        parts.append("First-pass flags:\n" + "\n".join(f"  - {f}" for f in flags[:6]))
    if quotes:
        parts.append("Key quotes:\n" + "\n".join(f'  > "{q}"' for q in quotes[:4]))
    if strategies:
        parts.append(f"Strategies noted:\n{strategies[:800]}")
    if len(transcript) > 20:
        parts.append(f"Full transcript text:\n{transcript[:14000]}")
    else:
        parts.append("[NOTE: Full transcript text not available — analyze from summary and flags only]")

    body = "\n\n".join(parts)
    return _DEEP_PROMPT.format(author=author, body=body)


# ── LLM callers ───────────────────────────────────────────────────────────────


def _ollama_analyze(prompt: str) -> Optional[dict]:
    """Try Ollama for deep analysis. Returns parsed dict or None."""
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": OLLAMA_ANALYSIS_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
        content = raw.get("message", {}).get("content", "")
        if not content:
            return None
        # Strip qwen3-style <think>…</think> reasoning tokens before JSON parse.
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    pass
        return None
    except Exception as exc:
        logger.info("transcript_ollama_failed: %s", str(exc)[:100])
        return None


def _openai_analyze(prompt: str) -> Optional[dict]:
    """Try GPT-4o-mini for deep analysis. Returns parsed dict or None."""
    api_key = OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=1400,
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("transcript_openai_failed: %s", str(exc)[:200])
        return None


# ── Cortex writer ─────────────────────────────────────────────────────────────


def _post_to_cortex(payload: dict) -> bool:
    """POST a memory to Cortex /remember. Returns True on success."""
    try:
        url = f"{CORTEX_URL.rstrip('/')}/remember"
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        logger.info("transcript_cortex_posted: id=%s", result.get("id", "?"))
        return True
    except Exception as exc:
        logger.warning("transcript_cortex_failed: %s", str(exc)[:200])
        return False


def _write_to_cortex(md_path: Path, data: dict, analysis: dict) -> int:
    """Write analysis outputs to Cortex memory. Returns count of memories written."""
    author = data.get("author", "unknown")
    post_id = data.get("post_id", "")
    fname = md_path.name
    source_ref = f"x_intake:@{author}:{post_id}" if post_id else f"x_intake:@{author}:{fname}"

    usefulness = int(analysis.get("usefulness_score", 0) or 0)
    confidence = float(analysis.get("confidence", 0.5) or 0.5)
    importance = min(10, max(1, usefulness // 10))
    tags = list(analysis.get("tags", []))
    if author and author not in tags:
        tags = [author] + tags
    tags = tags[:8]
    written = 0

    # 1 — Main insight memory (x_intel): summary + hidden gems
    summary_text = analysis.get("summary", "")
    topics = ", ".join(str(t) for t in analysis.get("key_topics", [])[:6])
    gems = analysis.get("hidden_gems", [])
    gem_lines = []
    for g in gems[:5]:
        if isinstance(g, dict):
            insight = g.get("insight", "")
            why = g.get("why_it_matters", "")
            gem_lines.append(f"• {insight}" + (f" — {why}" if why else ""))
        elif isinstance(g, str):
            gem_lines.append(f"• {g}")

    content_body = f"Video analysis: @{author}\n\nSummary: {summary_text}"
    if topics:
        content_body += f"\n\nKey topics: {topics}"
    if gem_lines:
        content_body += "\n\nHidden gems:\n" + "\n".join(gem_lines)

    content_ideas = analysis.get("content_ideas", [])
    if content_ideas:
        content_body += "\n\nContent ideas:\n" + "\n".join(
            f"• {c}" for c in content_ideas[:3]
        )

    if usefulness >= 20:
        if _post_to_cortex({
            "category": "x_intel",
            "title": f"@{author}: {summary_text[:70]}",
            "content": content_body,
            "source": source_ref,
            "confidence": confidence,
            "importance": importance,
            "tags": tags,
            "metadata": {
                "author": author,
                "post_id": post_id,
                "usefulness_score": usefulness,
                "transcript_file": fname,
                "hidden_gems_count": len(gems),
                "analyzed_by": "transcript_analyst",
            },
            "ttl_days": 30,
        }):
            written += 1

    # 2 — Strategy/task memories for high-priority actionable items
    tasks = analysis.get("actionable_tasks", [])
    cat_map = {
        "build": "strategy_idea",
        "implement": "strategy_idea",
        "research": "external_research",
        "investigate": "external_research",
        "warning": "x_intel",
    }
    for task in tasks:
        if not isinstance(task, dict):
            continue
        priority = task.get("priority", "low")
        if priority not in ("high", "medium"):
            continue
        task_text = task.get("task", "")
        if not task_text:
            continue
        mem_cat = cat_map.get(task.get("category", "research"), "external_research")
        task_importance = 8 if priority == "high" else 6
        if _post_to_cortex({
            "category": mem_cat,
            "title": f"[Task/@{author}] {task_text[:70]}",
            "content": (
                f"Source: @{author} video transcript\n"
                f"Task: {task_text}\n"
                f"Type: {task.get('category', '')}\n"
                f"Priority: {priority}"
            ),
            "source": source_ref,
            "confidence": confidence,
            "importance": task_importance,
            "tags": [author, "transcript_task"] + tags[:4],
            "ttl_days": 60,
        }):
            written += 1

    return written


# ── Queue DB helpers ──────────────────────────────────────────────────────────


def _mark_analyzed(db_path: Path, transcript_path: str, success: bool) -> None:
    """Mark a transcript's queue row as analyzed (1=ok, 2=failed)."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE x_intake_queue SET analyzed = ? WHERE transcript_path = ?",
            (1 if success else 2, transcript_path),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("transcript_mark_analyzed_failed: %s", str(exc)[:100])


def _get_unanalyzed_from_db(db_path: Path) -> list[dict]:
    """Return queue rows where has_transcript=1 and analyzed=0 with a file path set."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, url, author, transcript_path, summary FROM x_intake_queue "
            "WHERE has_transcript = 1 AND (analyzed IS NULL OR analyzed = 0) "
            "AND transcript_path IS NOT NULL AND transcript_path != '' "
            "ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("transcript_db_query_failed: %s", str(exc)[:100])
        return []


def _get_known_paths(db_path: Path) -> set[str]:
    """Return all transcript_path values already in the queue DB."""
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT transcript_path FROM x_intake_queue "
            "WHERE transcript_path IS NOT NULL AND transcript_path != ''"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ── Core analyzer ─────────────────────────────────────────────────────────────


def analyze_transcript_file(md_path: Path) -> dict:
    """
    Analyze a single transcript .md file.

    Returns:
        {
            "success": bool,
            "memories_written": int,
            "usefulness_score": int,
            "error": str (on failure only),
        }
    """
    logger.info("transcript_analyst_start: %s", md_path.name)

    data = _parse_transcript_md(md_path)
    if not data:
        return {"success": False, "error": "failed to parse .md file", "memories_written": 0}

    transcript_text = data.get("transcript", "").strip()
    existing_summary = data.get("summary", "")

    # Require at least some content to analyze
    if not transcript_text and not existing_summary:
        return {"success": False, "error": "no transcript text or summary", "memories_written": 0}

    # Skip obviously empty/garbled transcripts (just emoji / punctuation)
    content_check = (transcript_text or existing_summary)
    if len(re.sub(r"[^\w\s]", "", content_check).strip()) < 20:
        logger.info("transcript_too_sparse: %s", md_path.name)
        return {"success": False, "error": "transcript too sparse", "memories_written": 0}

    prompt = _build_prompt(data)

    analysis = _ollama_analyze(prompt)
    if not analysis:
        logger.info("transcript_ollama_miss — trying openai: %s", md_path.name)
        analysis = _openai_analyze(prompt)

    if not analysis:
        logger.warning("transcript_analysis_failed: %s", md_path.name)
        return {"success": False, "error": "both Ollama and OpenAI failed", "memories_written": 0}

    usefulness = int(analysis.get("usefulness_score", 0) or 0)
    logger.info(
        "transcript_analyzed: file=%s score=%d gems=%d tasks=%d",
        md_path.name,
        usefulness,
        len(analysis.get("hidden_gems", [])),
        len(analysis.get("actionable_tasks", [])),
    )

    written = _write_to_cortex(md_path, data, analysis)
    logger.info("transcript_cortex_written: %s memories=%d", md_path.name, written)

    return {
        "success": True,
        "memories_written": written,
        "usefulness_score": usefulness,
        "summary": analysis.get("summary", ""),
        "hidden_gems": len(analysis.get("hidden_gems", [])),
        "actionable_tasks": len(analysis.get("actionable_tasks", [])),
    }


# ── Backfill runner ───────────────────────────────────────────────────────────


def run_backfill(limit: int = 50) -> dict:
    """
    Process all unanalyzed transcripts — two sources:

    1. Queue DB rows with has_transcript=1, analyzed=0, transcript_path set.
    2. Orphaned .md files in TRANSCRIPT_DIR not indexed in the queue DB
       (written by the host-side imessage-server path before the volume was mounted).

    Returns a stats dict with processed/succeeded/failed/skipped counts.
    """
    db_path = _ANALYSIS_DB_PATH
    stats: dict = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "outputs": [],
    }

    # Source 1: queue DB rows
    queue_rows = _get_unanalyzed_from_db(db_path)
    logger.info("transcript_backfill_queue: %d rows", len(queue_rows))

    for row in queue_rows[:limit]:
        tp = row.get("transcript_path", "")
        if not tp:
            stats["skipped"] += 1
            continue
        md_path = Path(tp)
        if not md_path.exists():
            logger.warning("transcript_file_missing: %s", tp)
            stats["skipped"] += 1
            continue
        result = analyze_transcript_file(md_path)
        stats["processed"] += 1
        success = result.get("success", False)
        _mark_analyzed(db_path, tp, success)
        if success:
            stats["succeeded"] += 1
            stats["outputs"].append({
                "file": md_path.name,
                "memories": result.get("memories_written", 0),
                "score": result.get("usefulness_score", 0),
            })
        else:
            stats["failed"] += 1

    # Source 2: orphaned .md files on disk
    if TRANSCRIPT_DIR.exists():
        known = _get_known_paths(db_path)
        orphans = [
            f for f in sorted(TRANSCRIPT_DIR.glob("*.md"))
            if str(f) not in known and f.name != "_master_summary.md"
        ]
        logger.info("transcript_backfill_orphans: %d files", len(orphans))
        remaining = max(0, limit - stats["processed"])
        for md_path in orphans[:remaining]:
            result = analyze_transcript_file(md_path)
            stats["processed"] += 1
            if result.get("success"):
                stats["succeeded"] += 1
                stats["outputs"].append({
                    "file": md_path.name,
                    "memories": result.get("memories_written", 0),
                    "score": result.get("usefulness_score", 0),
                    "orphan": True,
                })
            else:
                stats["failed"] += 1

    logger.info(
        "transcript_backfill_complete: processed=%d succeeded=%d failed=%d",
        stats["processed"],
        stats["succeeded"],
        stats["failed"],
    )
    return stats


# ── Stats ─────────────────────────────────────────────────────────────────────


def get_stats() -> dict:
    """Return current transcript analysis statistics."""
    db_path = _ANALYSIS_DB_PATH
    result: dict = {
        "files_on_disk": 0,
        "total_with_transcript": 0,
        "pending_analysis": 0,
        "analyzed": 0,
        "failed": 0,
        "transcript_dir": str(TRANSCRIPT_DIR),
    }

    # Files on disk
    try:
        if TRANSCRIPT_DIR.exists():
            result["files_on_disk"] = len([
                f for f in TRANSCRIPT_DIR.glob("*.md")
                if f.name != "_master_summary.md"
            ])
    except Exception:
        pass

    # Queue DB counts
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT COUNT(*) AS n FROM x_intake_queue WHERE has_transcript = 1"
        ).fetchone()
        result["total_with_transcript"] = row["n"] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) AS n FROM x_intake_queue "
            "WHERE has_transcript = 1 AND analyzed = 1"
        ).fetchone()
        result["analyzed"] = row["n"] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) AS n FROM x_intake_queue "
            "WHERE has_transcript = 1 "
            "AND (analyzed IS NULL OR analyzed = 0) "
            "AND transcript_path IS NOT NULL AND transcript_path != ''"
        ).fetchone()
        result["pending_analysis"] = row["n"] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) AS n FROM x_intake_queue WHERE analyzed = 2"
        ).fetchone()
        result["failed"] = row["n"] if row else 0

        conn.close()
    except Exception as exc:
        result["db_error"] = str(exc)[:100]

    return result
