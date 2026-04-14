"""X/Twitter Intake — FastAPI service that analyzes tweet links from iMessage.

Pipeline:
  1. Receive X link via Redis (events:imessage channel)
  2. Fetch post text via API fallback chain (fxtwitter → vxtwitter → nitter → direct)
  3. If media/video detected → download audio via yt-dlp → transcribe via Whisper
  4. Analyze with LLM (OpenAI) using Matt's relevance profile
  5. Reply via iMessage bridge with emoji-flagged summary
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import traceback

import httpx
import structlog
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(__file__))

try:
    from queue_db import (
        enqueue as _db_enqueue,
        get_queue as _db_get_queue,
        update_status as _db_update_status,
        get_stats as _db_get_stats,
    )
except ImportError:
    _db_enqueue = _db_get_queue = _db_update_status = _db_get_stats = None  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = structlog.get_logger(__name__)

PORT = int(os.getenv("PORT", "8101"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CORTEX_URL = os.getenv("CORTEX_URL", "http://cortex:8102")

_TWEET_RE = re.compile(r"https?://(?:x\.com|twitter\.com)/\S+/status/\d+\S*", re.I)

MATT_PROFILE = """You are analyzing X/Twitter posts for Matt Earley, owner of Symphony Smart Homes.

Matt's interests and what he finds relevant (score HIGH):
- AI agents, autonomous systems, AI infrastructure, LLMs, agent frameworks
- Home automation, smart home technology, Control4, Lutron, Crestron
- Trading bots, algorithmic trading, Polymarket, prediction markets
- Docker, self-hosting, Mac Mini servers, local-first architecture
- Business automation, CRM pipelines, autonomous workflows
- MCP (Model Context Protocol), tool-calling, AI orchestration
- Cursor IDE, coding agents, autonomous coding
- Revenue automation, proposal generation, e-signatures
- Any tool, framework, or strategy Matt could implement in his AI-Server stack

What Matt does NOT care about (score LOW):
- Generic crypto price predictions or moon calls
- Celebrity gossip, sports, mainstream politics
- Basic marketing tips or generic business advice
- Motivational quotes or engagement bait with no substance

When analyzing, focus on:
1. Is there something Matt can BUILD or IMPLEMENT?
2. Is there a STRATEGY or EDGE he can use?
3. Is there a TOOL or FRAMEWORK worth investigating?
4. Is there DATA or a STAT that changes a decision?
5. Is there a WARNING about something he uses?
"""

app = FastAPI(title="X Intake", version="2.0.0")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "x-intake"}


def _analyze_with_llm(text: str, author: str, has_video: bool, transcript: str = "") -> dict:
    """Use OpenAI to analyze the post content with Matt's relevance profile."""
    api_key = OPENAI_API_KEY
    if not api_key:
        logger.warning("no_openai_key_for_analysis")
        return _analyze_keyword_fallback(text, author)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        content_parts = []
        content_parts.append(f"Post by @{author}:\n{text}")
        if transcript:
            content_parts.append(f"\n\nVideo transcript ({len(transcript)} chars):\n{transcript[:8000]}")

        prompt = f"""{MATT_PROFILE}

Analyze this post and respond in EXACTLY this format (no markdown, no extra text):

RELEVANCE: [0-100]
TYPE: [build|alpha|stat|tool|warn|info]
SUMMARY: [2-3 sentence summary of what matters and why]
ACTION: [one concrete thing Matt should do, or "none"]
FLAGS: [comma-separated emoji flags from: build, alpha, stat, tool, warn, info]

Post content:
{chr(10).join(content_parts)}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )

        reply = response.choices[0].message.content.strip()
        return _parse_llm_response(reply, author, text, has_video, transcript)

    except Exception as e:
        logger.warning("llm_analysis_failed", error=str(e)[:200])
        return _analyze_keyword_fallback(text, author)


def _parse_llm_response(reply: str, author: str, text: str, has_video: bool, transcript: str) -> dict:
    """Parse structured LLM response into analysis dict."""
    lines = reply.strip().split("\n")
    parsed = {}
    for line in lines:
        if ":" in line:
            key, _, val = line.partition(":")
            parsed[key.strip().upper()] = val.strip()

    relevance = 0
    try:
        relevance = int(parsed.get("RELEVANCE", "0"))
    except ValueError:
        pass

    flag_map = {
        "build": "\U0001f528",
        "alpha": "\U0001f4a1",
        "stat": "\U0001f4ca",
        "tool": "\U0001f527",
        "warn": "\u26a0\ufe0f",
        "info": "\u2139\ufe0f",
    }

    post_type = parsed.get("TYPE", "info").lower()
    emoji = flag_map.get(post_type, "\u2139\ufe0f")
    summary_text = parsed.get("SUMMARY", text[:200])
    action = parsed.get("ACTION", "none")

    imessage_lines = []
    imessage_lines.append(f"{emoji} @{author}")
    if has_video:
        imessage_lines.append("\U0001f3ac Video transcribed")
    imessage_lines.append("")
    imessage_lines.append(summary_text)
    if action and action.lower() != "none":
        imessage_lines.append("")
        imessage_lines.append(f"Action: {action}")
    imessage_lines.append("")
    imessage_lines.append(f"Relevance: {relevance}%")

    return {
        "summary": "\n".join(imessage_lines),
        "relevance": relevance,
        "type": post_type,
        "action": action,
        "has_transcript": bool(transcript),
    }


def _analyze_keyword_fallback(text: str, author: str) -> dict:
    """Fallback keyword analysis when no OpenAI key is available."""
    text_lower = text.lower()
    score = 0

    high_value = [
        "agent", "autonomous", "ai server", "docker", "self-host", "local-first",
        "mcp", "cursor", "polymarket", "prediction market", "smart home",
        "control4", "lutron", "crestron", "orchestrat", "pipeline", "webhook",
        "framework", "open source", "github", "trading bot", "algorithmic",
    ]
    for kw in high_value:
        if kw in text_lower:
            score += 15

    return {
        "summary": f"@{author}: {text[:280]}\n\nRelevance: {min(score, 100)}%",
        "relevance": min(score, 100),
        "type": "info",
        "action": "none",
        "has_transcript": False,
    }


async def _analyze_url(url: str) -> dict:
    """Full pipeline: fetch post → check for video → transcribe → analyze with LLM."""
    logger.info("pipeline_start", url=url)

    post_text = ""
    author = ""
    has_video = False
    transcript = ""
    media_urls = []
    result: dict = {}

    try:
        from post_fetcher import PostFetcher
        fetcher = PostFetcher()
        post = fetcher.fetch(url)
        if post:
            post_text = post.text or ""
            author = post.author or ""
            media_urls = getattr(post, "media_urls", []) or []

            if post.thread_context:
                post_text = f"[Thread parent by @{post.thread_context.author}]: {post.thread_context.text}\n\n[Reply by @{author}]: {post_text}"

            logger.info("post_fetched", author=author, text_len=len(post_text), media_count=len(media_urls))
    except Exception as e:
        logger.warning("post_fetch_failed", url=url, error=str(e)[:200])

    if not post_text:
        author_match = re.search(r"(?:x\.com|twitter\.com)/([^/]+)/status/", url)
        author = author_match.group(1) if author_match else "unknown"
        post_text = f"(Could not fetch post text from {url})"

    try:
        from video_transcriber import process_x_video
        logger.info("trying_video_transcription", url=url)
        result = process_x_video(
            url,
            author=author,
            post_text=post_text,
            openai_api_key=OPENAI_API_KEY,
        )
        # Normalize: if somehow a string was returned, wrap it in a dict
        if isinstance(result, str):
            result = {"summary": result, "has_video": False, "has_images": True}
        if "error" not in result and result.get("summary"):
            # Only flag has_video for actual video transcriptions (not image-only mode)
            if result.get("mode") != "image_vision":
                has_video = True
            transcript = ""
            if result.get("transcript_length", 0) > 0 and result.get("analysis"):
                analysis = result["analysis"]
                if isinstance(analysis, dict):
                    transcript = analysis.get("transcript", "")
                    if not transcript:
                        for k in ("raw_transcript", "full_transcript", "text"):
                            if analysis.get(k):
                                transcript = analysis[k]
                                break
            logger.info("video_transcribed", author=author, transcript_len=len(transcript))
        else:
            error_msg = result.get("error", "unknown")
            if "Failed to download" not in str(error_msg):
                logger.info("video_transcription_skipped", reason=str(error_msg)[:100])
    except Exception as e:
        logger.info("video_transcription_unavailable", error=str(e)[:200])

    # Image-only path: vision analysis already produced a summary; return directly
    if not has_video and isinstance(result, dict) and result.get("mode") == "image_vision" and result.get("summary"):
        image_summary = result["summary"]
        llm = _analyze_with_llm(post_text, author, False, "")
        if llm.get("action", "none").lower() != "none":
            image_summary += f"\n\nAction: {llm['action']}"
        image_summary += f"\nRelevance: {llm.get('relevance', 0)}%"
        return {
            "url": url,
            "author": author,
            "analysis": {"summary": image_summary},
            "relevance": llm.get("relevance", 0),
            "post_type": llm.get("type", "info"),
            "action": llm.get("action", "none"),
            "has_transcript": False,
        }

    if has_video and result.get("summary"):
        analysis = _analyze_with_llm(post_text, author, has_video, transcript)
        video_summary = result.get("summary", "")
        combined = video_summary
        if analysis.get("action", "none").lower() != "none":
            combined += f"\n\nAction: {analysis['action']}"
        combined += f"\nRelevance: {analysis.get('relevance', 0)}%"
        return {
            "url": url,
            "author": author,
            "analysis": {"summary": combined},
            "relevance": analysis.get("relevance", 0),
            "post_type": analysis.get("type", "info"),
            "action": analysis.get("action", "none"),
            "has_transcript": True,
            "transcript_path": result.get("transcript_path", "") if isinstance(result, dict) else "",
        }

    analysis = _analyze_with_llm(post_text, author, has_video, transcript)
    return {
        "url": url,
        "author": author,
        "analysis": {"summary": analysis.get("summary", "")},
        "relevance": analysis.get("relevance", 0),
        "post_type": analysis.get("type", "info"),
        "action": analysis.get("action", "none"),
        "has_transcript": analysis.get("has_transcript", False),
        "transcript_path": "",
    }


@app.post("/analyze")
async def analyze_endpoint(body: dict):
    """Analyze a single X/Twitter URL."""
    url = body.get("url", "")
    if not url:
        return {"error": "url required"}
    source = body.get("source", "api")
    result = await asyncio.to_thread(lambda: _analyze_url_sync(url))
    if _db_enqueue is not None and isinstance(result, dict):
        try:
            analysis = result.get("analysis", {})
            summary = analysis.get("summary", "") if isinstance(analysis, dict) else ""
            transcript_path = result.get("transcript_path", "")
            _db_enqueue(
                url=url,
                author=result.get("author", ""),
                post_type=result.get("post_type", "info"),
                relevance=result.get("relevance", 0),
                summary=summary,
                action=result.get("action", "none"),
                source=source,
                poly_signals={},
                has_transcript=bool(result.get("has_transcript")),
                transcript_path=transcript_path,
            )
            if transcript_path:
                asyncio.create_task(_analyze_transcript_background(transcript_path))
        except Exception as _qexc:
            logger.warning("analyze_enqueue_failed", error=str(_qexc)[:100])
    return result


def _analyze_url_sync(url: str) -> dict:
    """Sync wrapper for the async analyze pipeline."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_analyze_url(url))
    finally:
        loop.close()


def _extract_polymarket_signals(text: str, author: str, transcript: str = "") -> dict:
    """Extract Polymarket-specific trading signals from analyzed content."""
    api_key = OPENAI_API_KEY
    if not api_key:
        return {"signals": [], "strategies": [], "market_keywords": []}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        content = f"Post by @{author}:\n{text}"
        if transcript:
            content += f"\n\nVideo transcript:\n{transcript[:6000]}"

        prompt = f"""You are a Polymarket trading signal extractor. Analyze this X post for actionable Polymarket trading intelligence.

{content}

Extract in this exact JSON format:
{{
    "signals": [
        {{
            "market_keyword": "search term to find this market on Polymarket",
            "direction": "yes|no",
            "confidence": 0.0-1.0,
            "reasoning": "why this signal matters",
            "timeframe": "hours|days|weeks",
            "source_credibility": "high|medium|low"
        }}
    ],
    "strategies": [
        {{
            "name": "strategy name",
            "description": "what to implement",
            "parameters": {{}},
            "applicable_to": ["weather_trader", "copytrade", "spread_arb", "mean_reversion", "presolution_scalp"]
        }}
    ],
    "market_keywords": ["keywords to search Polymarket API for related markets"],
    "risk_warnings": ["any warnings about current positions or market conditions"],
    "alpha_insights": ["specific edges or inefficiencies mentioned"]
}}

Rules:
- Only include signals with genuine predictive value for Polymarket outcomes
- market_keyword should match how Polymarket titles their markets (e.g. "Will Bitcoin reach $100k", "Fed rate cut", "Trump win")
- If the post discusses a strategy that could improve our bot, include it in strategies
- applicable_to should reference our actual strategy names
- Be conservative with confidence scores
- If the post has no Polymarket relevance, return empty arrays"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=800,
            temperature=0.2,
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        logger.warning("polymarket_signal_extraction_failed", error=str(e)[:200])
        return {"signals": [], "strategies": [], "market_keywords": []}


async def _publish_to_bot(url: str, author: str, analysis: dict, poly_signals: dict) -> None:
    """Publish trading signals to polymarket-bot via Redis."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True)

        relevance = analysis.get("relevance", 0)

        # Publish to polymarket:intel_signals (bot already listens here)
        intel_payload = {
            "source": "x_intake",
            "author": author,
            "url": url,
            "relevance": relevance,
            "summary": analysis.get("summary", "")[:500],
            "type": analysis.get("type", "info"),
            "action": analysis.get("action", "none"),
            "signals": poly_signals.get("signals", []),
            "market_keywords": poly_signals.get("market_keywords", []),
            "risk_warnings": poly_signals.get("risk_warnings", []),
            "alpha_insights": poly_signals.get("alpha_insights", []),
            "timestamp": int(__import__("time").time()),
        }

        # Only publish to bot if relevance >= 40 (avoid noise)
        if relevance >= 40 or poly_signals.get("signals"):
            await client.publish("polymarket:intel_signals", json.dumps(intel_payload))
            logger.info("published_to_bot_intel", author=author, relevance=relevance)

        # Publish strategy suggestions to dedicated channel
        if poly_signals.get("strategies"):
            strat_payload = {
                "source": "x_intake",
                "author": author,
                "url": url,
                "strategies": poly_signals["strategies"],
                "timestamp": int(__import__("time").time()),
            }
            await client.publish("polymarket:x_strategies", json.dumps(strat_payload))
            logger.info("published_strategy_suggestions", count=len(poly_signals["strategies"]))

        await client.aclose()

    except Exception as exc:
        logger.warning("redis_publish_to_bot_failed", error=str(exc)[:200])


async def _ingest_to_knowledge(url: str, author: str, summary: str, poly_signals: dict) -> None:
    """Ingest X post analysis into the polymarket-bot knowledge graph via Redis."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True)

        # Build a structured knowledge payload
        knowledge_text = f"X Intel from @{author}:\n{summary}\n\n"

        if poly_signals.get("alpha_insights"):
            knowledge_text += "Alpha Insights:\n"
            for insight in poly_signals["alpha_insights"]:
                knowledge_text += f"- {insight}\n"

        if poly_signals.get("strategies"):
            knowledge_text += "\nStrategy Suggestions:\n"
            for strat in poly_signals["strategies"]:
                if isinstance(strat, dict):
                    knowledge_text += f"- {strat.get('name', '')}: {strat.get('description', '')}\n"
                    if strat.get("parameters"):
                        knowledge_text += f"  Parameters: {json.dumps(strat['parameters'])}\n"

        if poly_signals.get("risk_warnings"):
            knowledge_text += "\nRisk Warnings:\n"
            for warning in poly_signals["risk_warnings"]:
                knowledge_text += f"- {warning}\n"

        payload = {
            "action": "ingest",
            "source_url": url,
            "source_type": "x_intake",
            "author": author,
            "text": knowledge_text,
            "signals": poly_signals.get("signals", []),
            "market_keywords": poly_signals.get("market_keywords", []),
            "timestamp": int(__import__("time").time()),
        }

        await client.publish("polymarket:knowledge_ingest", json.dumps(payload))
        logger.info("knowledge_ingest_published", author=author)
        await client.aclose()

    except Exception as exc:
        logger.warning("knowledge_ingest_failed", error=str(exc)[:200])


async def _send_reply(text: str) -> None:
    """Send analysis result back via iMessage bridge."""
    try:
        base = IMESSAGE_BRIDGE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(base, json={"message": text})
            logger.info("imessage_reply_sent", length=len(text))
    except Exception as exc:
        logger.warning("imessage_send_failed", error=str(exc)[:200])


async def _process_url_and_reply(url: str, source: str = "imessage") -> None:
    """Analyze a tweet URL, queue for review, publish signals, send iMessage reply."""
    try:
        result = await asyncio.to_thread(_analyze_url_sync, url)
        summary = ""
        author = ""
        transcript = ""

        if isinstance(result, dict):
            analysis = result.get("analysis", {})
            author = result.get("author", "")
            if isinstance(analysis, dict):
                summary = analysis.get("summary", "")

            # Extract Polymarket-specific signals
            post_text = summary
            poly_signals = await asyncio.to_thread(
                _extract_polymarket_signals, post_text, author, transcript
            )

            # Use structured relevance from result; fall back to text parse
            relevance = result.get("relevance", 0)
            if not relevance and summary:
                import re as _re
                rel_match = _re.search(r"Relevance:\s*(\d+)%", summary)
                if rel_match:
                    relevance = int(rel_match.group(1))

            # Persist to review queue for dashboard visibility
            transcript_path = result.get("transcript_path", "")
            if _db_enqueue is not None:
                try:
                    _db_enqueue(
                        url=url,
                        author=author,
                        post_type=result.get("post_type", "info"),
                        relevance=relevance,
                        summary=summary,
                        action=result.get("action", "none"),
                        source=source,
                        poly_signals=poly_signals,
                        has_transcript=bool(result.get("has_transcript")),
                        transcript_path=transcript_path,
                    )
                except Exception as _qexc:
                    logger.warning("queue_enqueue_failed", error=str(_qexc)[:100])

            # Kick off deep transcript analysis in the background
            if transcript_path:
                asyncio.create_task(_analyze_transcript_background(transcript_path))

            await _publish_to_bot(url, author, {
                "summary": summary,
                "relevance": relevance,
                "type": result.get("post_type", "info"),
                "action": result.get("action", "none"),
            }, poly_signals)

            # Ingest into knowledge graph if high relevance
            if relevance >= 50 or poly_signals.get("signals"):
                await _ingest_to_knowledge(url, author, summary, poly_signals)

        if summary:
            await _send_reply(f"X Analysis:\n{summary}")
        elif isinstance(result, dict) and result.get("error"):
            logger.warning("analysis_error", url=url, error=result["error"])
    except Exception as exc:
        logger.warning("url_analysis_failed", url=url, error=str(exc)[:200])
        tb = traceback.format_exc()
        logger.debug("url_analysis_traceback", traceback=tb[:500])


async def _redis_listener() -> None:
    """Subscribe to Redis events:imessage for incoming X/Twitter links."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis not installed — listener disabled")
        return

    while True:
        try:
            client = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe("events:imessage")
            logger.info("redis_listener_started", channel="events:imessage")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"]) if isinstance(message["data"], str) else message["data"]
                    text = data.get("text", "") if isinstance(data, dict) else str(data)
                    urls = _TWEET_RE.findall(text)
                    for url in urls:
                        logger.info("tweet_detected_from_redis", url=url)
                        # Spawn as background task so the event loop stays responsive
                        # to health checks during long transcriptions (Bug 1 fix)
                        asyncio.create_task(_process_url_and_reply(url))
                except Exception as exc:
                    logger.warning("message_process_error", error=str(exc)[:200])
        except Exception as exc:
            logger.warning("redis_reconnecting", error=str(exc)[:200])
            await asyncio.sleep(5)


# ── Transcript background analysis ───────────────────────────────────────────

async def _analyze_transcript_background(transcript_path: str) -> None:
    """Run deep transcript analysis in a background task after a new file is saved.

    Calls transcript_analyst.analyze_transcript_file() then marks the queue row
    as analyzed (1=success, 2=failed).  Never raises — must not crash the caller.
    """
    try:
        import transcript_analyst as _ta
        from pathlib import Path as _Path
        result = await asyncio.to_thread(_ta.analyze_transcript_file, _Path(transcript_path))
        success = result.get("success", False)
        logger.info(
            "transcript_bg_analysis",
            path=transcript_path,
            success=success,
            memories=result.get("memories_written", 0),
            score=result.get("usefulness_score", 0),
        )
        _ta._mark_analyzed(_ta._ANALYSIS_DB_PATH, transcript_path, success)
    except Exception as exc:
        logger.warning("transcript_bg_analysis_failed", path=transcript_path, error=str(exc)[:200])


# ── Listener watchdog (§Z14 durable fix) ─────────────────────────────────────

_listener_task: asyncio.Task | None = None


async def _listener_watchdog() -> None:
    """Keep the Redis listener Task alive.  Restarts it if it dies."""
    global _listener_task
    while True:
        if _listener_task is None or _listener_task.done():
            logger.warning("redis_listener_restarting")
            _listener_task = asyncio.create_task(_redis_listener())
        await asyncio.sleep(10)


# ── Review queue API ─────────────────────────────────────────────────────────

@app.get("/queue/stats")
async def queue_stats_endpoint():
    """Return intake queue counts by status (used by Cortex dashboard)."""
    if _db_get_stats is None:
        return {"error": "db not available", "pending": 0, "auto_approved": 0,
                "auto_rejected": 0, "approved": 0, "rejected": 0, "total": 0}
    try:
        return _db_get_stats()
    except Exception as exc:
        return {"error": str(exc)[:100]}


@app.get("/queue")
async def queue_list_endpoint(status: str = "", limit: int = 50):
    """List intake queue items, optionally filtered by status."""
    if _db_get_queue is None:
        return {"items": [], "count": 0, "error": "db not available"}
    try:
        items = _db_get_queue(status=status or None, limit=min(limit, 200))
        return {"items": items, "count": len(items)}
    except Exception as exc:
        return {"items": [], "count": 0, "error": str(exc)[:100]}


@app.post("/queue/{item_id}/approve")
async def queue_approve_endpoint(item_id: int, body: dict = {}):
    """Mark an item as approved — records human feedback for learning."""
    if _db_update_status is None:
        return {"ok": False, "error": "db not available"}
    try:
        note = (body or {}).get("note", "")
        changed = _db_update_status(item_id, "approved", note)
        logger.info("queue_item_approved", id=item_id)
        return {"ok": changed, "id": item_id, "status": "approved"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:100]}


@app.post("/queue/{item_id}/reject")
async def queue_reject_endpoint(item_id: int, body: dict = {}):
    """Mark an item as rejected — records human feedback for learning."""
    if _db_update_status is None:
        return {"ok": False, "error": "db not available"}
    try:
        note = (body or {}).get("note", "")
        changed = _db_update_status(item_id, "rejected", note)
        logger.info("queue_item_rejected", id=item_id)
        return {"ok": changed, "id": item_id, "status": "rejected"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:100]}


# ── Transcript analysis API ───────────────────────────────────────────────────

@app.get("/transcripts/stats")
async def transcripts_stats_endpoint():
    """Return transcript analysis counts: files on disk, analyzed, pending, failed."""
    try:
        import transcript_analyst as _ta
        return _ta.get_stats()
    except Exception as exc:
        return {"error": str(exc)[:100]}


@app.post("/transcripts/backfill")
async def transcripts_backfill_endpoint(body: dict = {}):
    """Trigger deep analysis of all unanalyzed transcripts (queue DB + orphaned .md files).

    Optional body: {"limit": 50}  (default 50, max 200)
    Returns immediately with a task_started=True; analysis runs in the background.
    """
    limit = min(int((body or {}).get("limit", 50)), 200)
    try:
        import transcript_analyst as _ta
        asyncio.create_task(asyncio.to_thread(_ta.run_backfill, limit))
        return {"task_started": True, "limit": limit}
    except Exception as exc:
        return {"task_started": False, "error": str(exc)[:100]}


# ── Bookmark Organizer ───────────────────────────────────────────────────────

@app.post("/organize-bookmarks")
async def organize_bookmarks(request: dict):
    """Organize and ingest bookmarks into Cortex."""
    try:
        from bookmark_organizer import BookmarkOrganizer
    except ImportError:
        from integrations.x_intake.bookmark_organizer import BookmarkOrganizer

    bookmarks_path = request.get("path", "/data/bookmarks.json")
    organizer = BookmarkOrganizer(CORTEX_URL, bookmarks_path)
    categorized = await organizer.categorize_all()
    if not categorized:
        return {"ok": False, "error": "no bookmarks found or file missing", "path": bookmarks_path}
    result = await organizer.ingest_to_cortex(categorized)
    result["ok"] = True
    return result


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # Start the listener watchdog — restarts _redis_listener if it dies (§Z14 fix).
    asyncio.create_task(_listener_watchdog())
    logger.info("x_intake_started", port=PORT, openai_key_set=bool(OPENAI_API_KEY))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
