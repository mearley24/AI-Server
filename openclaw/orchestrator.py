"""
OpenClaw Autonomous Orchestrator
Runs as a background task — checks email, calendar, pipeline, trading, health,
and consolidates memories. Sends daily briefings.

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
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("openclaw.orchestrator")

# Internal service URLs (Docker networking)
SERVICES = {
    "email": os.getenv("EMAIL_MONITOR_URL", "http://email-monitor:8092"),
    "calendar": os.getenv("CALENDAR_AGENT_URL", "http://calendar-agent:8094"),
    "dtools": os.getenv("DTOOLS_BRIDGE_URL", "http://dtools-bridge:5050"),
    "proposals": os.getenv("PROPOSALS_URL", "http://proposals:8091"),
    "notifications": os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095"),
    "polymarket-bot": os.getenv("POLYMARKET_BOT_URL", "http://vpn:8430"),
    "notification-hub": os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095"),
}

# Critical services that trigger alerts when down
CRITICAL_SERVICES = {"polymarket-bot", "notification-hub"}

# Path for live learnings export
LEARNINGS_PATH = Path(os.getenv("LEARNINGS_PATH", "/app/data/AGENT_LEARNINGS_LIVE.md"))


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
    def __init__(self, memory=None):
        self.http = httpx.AsyncClient(timeout=30.0)
        self.last_briefing_date = None
        self.processed_emails = set()
        self._cache = ResponseCache(ttl_seconds=300)
        self._memory = memory
        self._last_consolidation: float = 0
        self._health_failures: dict[str, int] = {}  # service -> consecutive failure count

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
        await self.check_trading()
        await self.check_health()
        await self.consolidate_memories()
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

    # ------------------------------------------------------------------
    # Email check
    # ------------------------------------------------------------------
    async def check_emails(self):
        """Check for new urgent emails. Zero LLM calls."""
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

    # ------------------------------------------------------------------
    # Calendar check
    # ------------------------------------------------------------------
    async def check_calendar(self):
        """Check upcoming events. Zero LLM calls."""
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

    # ------------------------------------------------------------------
    # Pipeline check
    # ------------------------------------------------------------------
    async def check_pipeline(self):
        """Check D-Tools pipeline for stale items. Zero LLM calls."""
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

    # ------------------------------------------------------------------
    # Trading intelligence check (NEW)
    # ------------------------------------------------------------------
    async def check_trading(self):
        """Check trading bot status and positions. Alert on significant losses."""
        bot_url = SERVICES["polymarket-bot"]

        # Get bot status
        try:
            resp = await self.http.get(f"{bot_url}/status")
            if resp.status_code != 200:
                logger.debug("Trading bot status check failed: %d", resp.status_code)
                return
            status_data = resp.json()
        except Exception as e:
            logger.debug("Trading bot unreachable: %s", e)
            return

        # Store status in memory
        if self._memory:
            try:
                copytrade = status_data.get("strategies", {}).get("copytrade", {})
                summary = (
                    f"positions={copytrade.get('open_positions', '?')}, "
                    f"daily_trades={copytrade.get('daily_trades', '?')}, "
                    f"bankroll=${copytrade.get('bankroll', '?'):.0f}"
                )
                self._memory.remember(
                    "trading_bot_status", summary,
                    category="trading_insight", source_agent="orchestrator",
                )
            except Exception as e:
                logger.debug("Failed to store trading status in memory: %s", e)

        # Get positions
        try:
            resp = await self.http.get(f"{bot_url}/positions")
            if resp.status_code != 200:
                return
            positions_data = resp.json()
        except Exception as e:
            logger.debug("Trading positions check failed: %s", e)
            return

        positions = positions_data if isinstance(positions_data, list) else positions_data.get("positions", [])

        # Check for significant unrealized losses
        for pos in positions:
            unrealized_pnl = pos.get("unrealized_pnl", 0)
            cost_basis = pos.get("cost_basis", pos.get("amount_invested", 1))
            if cost_basis > 0:
                loss_pct = (unrealized_pnl / cost_basis) * 100
                if loss_pct < -20:
                    market = pos.get("market", pos.get("condition_id", "unknown"))[:60]
                    msg = f"Position losing >{abs(loss_pct):.0f}%: {market} (unrealized: ${unrealized_pnl:.2f})"
                    logger.warning("trading_loss_alert: %s", msg)
                    if self._memory:
                        self._memory.remember(
                            f"loss_alert_{market[:30]}", msg,
                            category="trading_insight", source_agent="orchestrator",
                        )

        # Check daily P/L
        try:
            copytrade = status_data.get("strategies", {}).get("copytrade", {})
            daily_pnl = copytrade.get("daily_pnl", copytrade.get("realized_pnl_today", 0))
            if isinstance(daily_pnl, (int, float)) and daily_pnl < -20:
                msg = f"Daily P/L significantly negative: ${daily_pnl:.2f}"
                logger.warning("trading_daily_loss: %s", msg)
                await self.notify("trading", msg)
                if self._memory:
                    self._memory.remember(
                        "daily_pnl_alert", msg,
                        category="trading_insight", source_agent="orchestrator",
                    )
        except Exception as e:
            logger.debug("Daily P/L check error: %s", e)

        logger.info("Trading check completed: %d positions", len(positions))

    # ------------------------------------------------------------------
    # Memory consolidation (NEW) — runs once per hour
    # ------------------------------------------------------------------
    async def consolidate_memories(self):
        """Export recent trading insights to AGENT_LEARNINGS_LIVE.md.

        Runs once per hour (3600s). Creates the feedback loop:
        trading outcomes → memory → learnings file → better trades.
        """
        if not self._memory:
            return

        now = time.time()
        if now - self._last_consolidation < 3600:
            return

        self._last_consolidation = now
        logger.info("Consolidating memories to learnings file")

        try:
            # Get trading insights from the last 24 hours
            insights = self._memory.recall_recent(hours=24, category="trading_insight")
            learnings = self._memory.recall_recent(hours=168, category="agent_learning")  # 7 days

            if not insights and not learnings:
                logger.info("No recent memories to consolidate")
                return

            lines = [
                "# Agent Learnings — Live Feed",
                f"*Auto-generated by orchestrator at {datetime.now().isoformat()}*",
                f"*{len(insights)} trading insights (24h), {len(learnings)} agent learnings (7d)*\n",
            ]

            if insights:
                lines.append("## Recent Trading Insights\n")
                for m in insights[:30]:
                    lines.append(f"- **{m['key']}**: {m['value']}")
                    lines.append(f"  *(updated: {m['updated_at']})*")

            if learnings:
                lines.append("\n## Agent Learnings\n")
                for m in learnings[:20]:
                    lines.append(f"- **{m['key']}**: {m['value']}")

            content = "\n".join(lines) + "\n"

            LEARNINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEARNINGS_PATH.write_text(content)
            logger.info("Learnings exported to %s (%d bytes)", LEARNINGS_PATH, len(content))
        except Exception as e:
            logger.error("Memory consolidation failed: %s", e)

    # ------------------------------------------------------------------
    # Health self-check (NEW)
    # ------------------------------------------------------------------
    async def check_health(self):
        """Ping all services. Alert if critical services are down for >2 ticks."""
        for name, url in SERVICES.items():
            try:
                resp = await self.http.get(f"{url}/health", timeout=10.0)
                if resp.status_code == 200:
                    if name in self._health_failures:
                        logger.info("Service %s recovered after %d failed ticks", name, self._health_failures[name])
                        del self._health_failures[name]
                        if self._memory:
                            self._memory.remember(
                                f"health_{name}", f"{name} recovered at {datetime.now().isoformat()}",
                                category="project_context", source_agent="orchestrator",
                            )
                    continue
            except Exception:
                pass

            # Service is down — increment failure count
            self._health_failures[name] = self._health_failures.get(name, 0) + 1
            count = self._health_failures[name]
            logger.warning("Service %s down (%d consecutive ticks)", name, count)

            # Store in memory for trend analysis
            if self._memory:
                self._memory.remember(
                    f"health_{name}", f"{name} down — {count} consecutive failures as of {datetime.now().isoformat()}",
                    category="project_context", source_agent="orchestrator",
                )

            # Alert if critical service down for >2 ticks (>10 minutes)
            if name in CRITICAL_SERVICES and count > 2:
                msg = f"CRITICAL: {name} has been down for {count} consecutive ticks (~{count * 5} min)"
                logger.error(msg)
                await self.notify("health", msg)

    # ------------------------------------------------------------------
    # Daily briefing
    # ------------------------------------------------------------------
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

            # Trading summary from memory
            if self._memory:
                try:
                    trading_mem = self._memory.recall("trading_bot_status", category="trading_insight", limit=1)
                    if trading_mem:
                        briefing_parts.append(f"Trading: {trading_mem[0]['value']}")
                except Exception:
                    pass

            # Health summary
            if self._health_failures:
                down = [f"{k} ({v} ticks)" for k, v in self._health_failures.items()]
                briefing_parts.append(f"Services down: {', '.join(down)}")
            else:
                briefing_parts.append("All services healthy")

            briefing = "\n".join(briefing_parts)
            await self.notify("briefing", briefing)
            self.last_briefing_date = today
            logger.info("Daily briefing sent")

    # ------------------------------------------------------------------
    # Notification helper
    # ------------------------------------------------------------------
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
