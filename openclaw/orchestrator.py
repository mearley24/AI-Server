"""
OpenClaw Autonomous Orchestrator
Runs as a background task — checks email, calendar, pipeline, and sends daily briefings.

Cost optimization notes:
- Zero LLM calls on routine ticks. LLM only invoked when action required.
- All routine checks are just HTTP GETs to internal services (free).
- Response cache with 5-minute TTL prevents redundant service queries.
- When LLM IS needed (e.g. summarizing a new bid invite), use Haiku (budget tier).
"""

import asyncio
import logging
import os
import time
from datetime import datetime

import httpx

logger = logging.getLogger("openclaw.orchestrator")

# Internal service URLs (Docker networking)
SERVICES = {
    "email": os.getenv("EMAIL_MONITOR_URL", "http://email-monitor:8092"),
    "calendar": os.getenv("CALENDAR_AGENT_URL", "http://calendar-agent:8094"),
    "dtools": os.getenv("DTOOLS_BRIDGE_URL", "http://dtools-bridge:5050"),
    "proposals": os.getenv("PROPOSALS_URL", "http://proposals:8091"),
    "notifications": os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095"),
}


class ResponseCache:
    """In-memory cache with TTL for service responses.

    Prevents the orchestrator from re-querying email-monitor, calendar-agent,
    dtools-bridge every tick if data hasn't changed.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[float, object]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str):
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: object):
        self._cache[key] = (value, time.time())


class Orchestrator:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.last_briefing_date = None
        self.processed_emails = set()
        self._cache = ResponseCache(ttl_seconds=300)

    async def run_loop(self):
        """Main orchestration loop — runs every 5 minutes."""
        logger.info("Orchestrator starting autonomous loop")
        while True:
            try:
                await self.tick()
            except Exception as e:
                logger.error("Orchestrator tick failed: %s", e)
            await asyncio.sleep(300)  # 5 minutes

    async def tick(self):
        """Single orchestration cycle."""
        logger.info("Orchestrator tick at %s", datetime.now().isoformat())

        await self.check_emails()
        await self.check_calendar()
        await self.check_pipeline()
        await self.maybe_send_briefing()

    async def _cached_get(self, cache_key: str, url: str, params: dict | None = None):
        """HTTP GET with response caching. Returns parsed JSON or None."""
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("cache_hit key=%s", cache_key)
            return cached
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                self._cache.set(cache_key, data)
                return data
        except Exception as e:
            logger.debug("Service call failed (%s): %s", cache_key, e)
        return None

    async def check_emails(self):
        """Check for new urgent emails.

        Zero LLM calls — just HTTP GETs to email-monitor service.
        """
        try:
            # Bid invites
            data = await self._cached_get(
                "email_bid_invite",
                f"{SERVICES['email']}/emails",
                {"category": "BID_INVITE", "limit": 10},
            )
            if data:
                emails = data if isinstance(data, list) else data.get("emails", [])
                for email in emails:
                    email_id = email.get("id", "")
                    if email_id and email_id not in self.processed_emails:
                        logger.info("New bid invite: %s — %s", email.get("sender", "unknown"), email.get("subject", ""))
                        await self.notify("email", f"New bid invite from {email.get('sender', 'unknown')}: {email.get('subject', '')}")
                        self.processed_emails.add(email_id)

            # Client inquiries
            data = await self._cached_get(
                "email_client_inquiry",
                f"{SERVICES['email']}/emails",
                {"category": "CLIENT_INQUIRY", "limit": 10},
            )
            if data:
                emails = data if isinstance(data, list) else data.get("emails", [])
                for email in emails:
                    email_id = email.get("id", "")
                    if email_id and email_id not in self.processed_emails:
                        logger.info("Client inquiry: %s — %s", email.get("sender", "unknown"), email.get("subject", ""))
                        await self.notify("email", f"Client inquiry from {email.get('sender', 'unknown')}: {email.get('subject', '')}")
                        self.processed_emails.add(email_id)
        except Exception as e:
            logger.debug("Email check skipped: %s", e)

    async def check_calendar(self):
        """Check upcoming events and prep.

        Zero LLM calls — just HTTP GET to calendar-agent service.
        """
        try:
            data = await self._cached_get(
                "calendar_upcoming",
                f"{SERVICES['calendar']}/calendar/upcoming",
                {"hours": 4},
            )
            if data:
                events = data if isinstance(data, list) else data.get("events", [])
                for event in events:
                    title = event.get("title", event.get("summary", ""))
                    start = event.get("start", event.get("start_time", ""))
                    logger.info("Upcoming: %s at %s", title, start)
        except Exception as e:
            logger.debug("Calendar check skipped: %s", e)

    async def check_pipeline(self):
        """Check D-Tools pipeline for stale items.

        Zero LLM calls — just HTTP GET to dtools-bridge service.
        """
        try:
            data = await self._cached_get(
                "dtools_pipeline",
                f"{SERVICES['dtools']}/pipeline",
            )
            if data:
                opps = data.get("opportunities", [])
                projects = data.get("projects", [])
                logger.info("Pipeline: %d opportunities, %d projects", len(opps), len(projects))
        except Exception as e:
            logger.debug("Pipeline check skipped: %s", e)

    async def maybe_send_briefing(self):
        """Send daily briefing at 6 AM MT."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        if self.last_briefing_date == today:
            return

        # Check if it's between 6:00-6:10 AM (accounting for 5-min loop)
        if now.hour == 6 and now.minute < 10:
            logger.info("Generating daily briefing")

            briefing_parts = ["Good morning — here's your daily briefing:\n"]

            # Email summary
            try:
                resp = await self.http.get(f"{SERVICES['email']}/emails/summary")
                if resp.status_code == 200:
                    summary = resp.json()
                    briefing_parts.append(f"Emails: {summary}")
            except Exception:
                pass

            # Today's calendar
            try:
                resp = await self.http.get(f"{SERVICES['calendar']}/calendar/today")
                if resp.status_code == 200:
                    cal = resp.json()
                    events = cal if isinstance(cal, list) else cal.get("events", [])
                    briefing_parts.append(f"Calendar: {len(events)} events today")
                    for e in events[:5]:
                        title = e.get("title", e.get("summary", ""))
                        start = e.get("start", e.get("start_time", ""))
                        briefing_parts.append(f"  - {title} at {start}")
            except Exception:
                pass

            # Pipeline
            try:
                resp = await self.http.get(f"{SERVICES['dtools']}/pipeline")
                if resp.status_code == 200:
                    pipe = resp.json()
                    opps = pipe.get("opportunities", [])
                    briefing_parts.append(f"Pipeline: {len(opps)} open opportunities")
            except Exception:
                pass

            briefing = "\n".join(briefing_parts)
            await self.notify("briefing", briefing)
            self.last_briefing_date = today
            logger.info("Daily briefing sent")

    async def notify(self, channel: str, message: str):
        """Publish notification via notification-hub."""
        try:
            await self.http.post(
                f"{SERVICES['notifications']}/notify",
                json={"title": f"Bob [{channel}]", "body": message, "priority": "normal"},
            )
        except Exception as e:
            logger.debug("Notification send failed: %s", e)

    async def close(self):
        await self.http.aclose()
