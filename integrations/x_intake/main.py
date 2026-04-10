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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = structlog.get_logger(__name__)

PORT = int(os.getenv("PORT", "8101"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
IMESSAGE_BRIDGE_URL = os.getenv("IMESSAGE_BRIDGE_URL", "http://host.docker.internal:8199")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

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
        if "error" not in result and result.get("summary"):
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

    if has_video and result.get("summary"):
        analysis = _analyze_with_llm(post_text, author, has_video, transcript)
        video_summary = result.get("summary", "")
        if analysis.get("relevance", 0) > 30 or True:
            combined = video_summary
            if analysis.get("action", "none").lower() != "none":
                combined += f"\n\nAction: {analysis['action']}"
            combined += f"\nRelevance: {analysis.get('relevance', 0)}%"
            return {"url": url, "analysis": {"summary": combined}}
        return {"url": url, "analysis": {"summary": video_summary}}

    analysis = _analyze_with_llm(post_text, author, has_video, transcript)
    return {
        "url": url,
        "author": author,
        "analysis": {"summary": analysis.get("summary", "")},
    }


@app.post("/analyze")
async def analyze_endpoint(body: dict):
    """Analyze a single X/Twitter URL."""
    url = body.get("url", "")
    if not url:
        return {"error": "url required"}
    result = await asyncio.to_thread(lambda: _analyze_url_sync(url))
    return result


def _analyze_url_sync(url: str) -> dict:
    """Sync wrapper for the async analyze pipeline."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_analyze_url(url))
    finally:
        loop.close()


async def _send_reply(text: str) -> None:
    """Send analysis result back via iMessage bridge."""
    try:
        base = IMESSAGE_BRIDGE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(base, json={"message": text})
            logger.info("imessage_reply_sent", length=len(text))
    except Exception as exc:
        logger.warning("imessage_send_failed", error=str(exc)[:200])


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
                        try:
                            result = await _analyze_url(url)
                            summary = ""
                            if isinstance(result, dict):
                                analysis = result.get("analysis", {})
                                if isinstance(analysis, dict):
                                    summary = analysis.get("summary", "")
                            if summary:
                                await _send_reply(f"X Analysis:\n{summary}")
                            elif isinstance(result, dict) and result.get("error"):
                                logger.warning("analysis_error", url=url, error=result["error"])
                        except Exception as exc:
                            logger.warning("url_analysis_failed", url=url, error=str(exc)[:200])
                            tb = traceback.format_exc()
                            logger.debug("url_analysis_traceback", traceback=tb[:500])
                except Exception as exc:
                    logger.warning("message_process_error", error=str(exc)[:200])
        except Exception as exc:
            logger.warning("redis_reconnecting", error=str(exc)[:200])
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_redis_listener())
    logger.info("x_intake_started", port=PORT, openai_key_set=bool(OPENAI_API_KEY))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
