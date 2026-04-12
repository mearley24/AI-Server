"""FastAPI routes for Calendar Agent."""

import json
import os
import logging
import httpx
from datetime import datetime, timedelta

import redis as sync_redis
from fastapi import APIRouter, HTTPException, Query

from calendar_client import ZohoCalendarClient
from scheduler import find_free_slots

logger = logging.getLogger(__name__)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.199:11434")


async def _ollama_meeting_prep(prompt: str) -> str | None:
    """Try Ollama /api/chat for meeting prep; return text or None."""
    if not OLLAMA_HOST.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen3:8b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
            )
        if r.status_code != 200:
            logger.warning("ollama_meeting_prep_http_%s", r.status_code)
            return None
        data = r.json()
        text = (data.get("message") or {}).get("content") or ""
        if text.strip():
            logger.info("meeting_prep_ollama_success")
        return text.strip() or None
    except Exception as e:
        logger.warning("ollama_meeting_prep_failed: %s", str(e)[:120])
        return None



def _publish_calendar_event(event_type: str, data: dict) -> None:
    """Publish calendar events to Redis for other services."""
    try:
        r = sync_redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
        r.publish("notifications:calendar", json.dumps({
            "type": event_type,
            **data,
            "timestamp": datetime.now().isoformat(),
        }))
        r.close()
    except Exception as e:
        logger.warning("redis_publish_failed: %s", e)


router = APIRouter(prefix="/calendar")


def get_client() -> ZohoCalendarClient:
    if not hasattr(get_client, "_instance"):
        get_client._instance = ZohoCalendarClient()
    return get_client._instance


def _require_configured(client: ZohoCalendarClient):
    if not client.configured:
        raise HTTPException(status_code=503, detail="Zoho Calendar credentials not configured")


@router.get("/today")
async def today_events():
    client = get_client()
    _require_configured(client)
    now = datetime.now()
    start = now.strftime("%Y-%m-%dT00:00:00+00:00")
    end = now.strftime("%Y-%m-%dT23:59:59+00:00")
    events = await client.list_events(start, end)
    return {"date": now.strftime("%Y-%m-%d"), "events": events, "count": len(events)}


@router.get("/week")
async def week_events():
    client = get_client()
    _require_configured(client)
    now = datetime.now()
    week_end = now + timedelta(days=7)
    events = await client.list_events(
        now.strftime("%Y-%m-%dT00:00:00+00:00"),
        week_end.strftime("%Y-%m-%dT23:59:59+00:00"),
    )
    return {"start": now.strftime("%Y-%m-%d"), "end": week_end.strftime("%Y-%m-%d"), "events": events, "count": len(events)}


@router.get("/free-slots")
async def free_slots(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), duration: int = Query(60, ge=15, le=480)):
    client = get_client()
    _require_configured(client)
    events = await client.list_events(f"{date}T00:00:00+00:00", f"{date}T23:59:59+00:00")
    slots = find_free_slots(events, date, duration)
    return {"date": date, "duration_minutes": duration, "slots": slots}


@router.post("/events")
async def create_event(body: dict):
    client = get_client()
    _require_configured(client)
    required = ["title", "start", "end"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    event_data = {
        "title": body["title"],
        "dateandtime": {"start": body["start"], "end": body["end"], "timezone": "America/Denver"},
    }
    if "attendees" in body:
        event_data["attendees"] = body["attendees"]
    if "notes" in body:
        event_data["description"] = body["notes"]
    result = await client.create_event(event_data)
    _publish_calendar_event("event_created", {
        "title": body.get("title", ""),
        "start": body.get("start", ""),
        "end": body.get("end", ""),
    })
    return result


@router.patch("/events/{event_id}")
async def update_event(event_id: str, body: dict):
    client = get_client()
    _require_configured(client)
    event_data = {}
    if "title" in body:
        event_data["title"] = body["title"]
    if "start" in body or "end" in body:
        event_data["dateandtime"] = {}
        if "start" in body:
            event_data["dateandtime"]["start"] = body["start"]
        if "end" in body:
            event_data["dateandtime"]["end"] = body["end"]
    result = await client.update_event(event_id, event_data)
    return result


@router.delete("/events/{event_id}")
async def delete_event(event_id: str):
    client = get_client()
    _require_configured(client)
    result = await client.delete_event(event_id)
    return result


@router.get("/upcoming")
async def upcoming(hours: int = Query(4, ge=1, le=24)):
    client = get_client()
    _require_configured(client)
    now = datetime.now()
    end = now + timedelta(hours=hours)
    # Use strftime (no microseconds) — Zoho rejects decimal seconds in the range param
    events = await client.list_events(
        now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        end.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    )
    return {"hours": hours, "events": events, "count": len(events)}


@router.get("/daily-briefing")
async def daily_briefing():
    """Generate today's schedule briefing for the morning digest."""
    client = get_client()
    _require_configured(client)

    now = datetime.now()
    events = await client.list_events(
        now.strftime("%Y-%m-%dT00:00:00+00:00"),
        now.strftime("%Y-%m-%dT23:59:59+00:00"),
    )

    if not events:
        return {"briefing": "No events scheduled today. Open calendar for the day.", "events": [], "count": 0}

    lines = [f"Today's Schedule — {now.strftime('%A, %B %d')}:", ""]
    for ev in events:
        title = ev.get("title", "Untitled")
        start_raw = ev.get("dateandtime", {}).get("start", "")
        try:
            start_dt = datetime.fromisoformat(start_raw)
            time_str = start_dt.strftime("%I:%M %p")
        except (ValueError, TypeError):
            time_str = "TBD"
        lines.append(f"- {time_str}: {title}")

    return {
        "briefing": "\n".join(lines),
        "events": events,
        "count": len(events),
    }


@router.post("/meeting-prep/{event_id}")
async def meeting_prep(event_id: str):
    """Generate AI meeting prep notes — Ollama first, OpenAI fallback."""
    client = get_client()
    _require_configured(client)

    # Fetch the event — use a broad range since we only have ID
    now = datetime.now()
    events = await client.list_events(
        (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00+00:00"),
        (now + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59+00:00"),
    )
    event = next((e for e in events if e.get("uid") == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    title = event.get("title", "Meeting")
    attendees = event.get("attendees", [])
    description = event.get("description", "")

    prompt = f"""Prepare brief meeting prep notes for: {title}
Attendees: {attendees}
Description: {description}
Include: key talking points, questions to ask, and any prep needed."""

    prep = await _ollama_meeting_prep(prompt)
    if prep:
        return {"event_id": event_id, "title": title, "prep_notes": prep, "source": "ollama"}

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(
            status_code=503,
            detail="Ollama unavailable and OPENAI_API_KEY not configured",
        )
    logger.warning("using_openai_for_meeting_prep — Ollama unavailable")

    from openai import AsyncOpenAI
    ai = AsyncOpenAI(api_key=openai_key)
    resp = await ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
    )

    return {
        "event_id": event_id,
        "title": title,
        "prep_notes": resp.choices[0].message.content,
        "source": "openai",
    }
