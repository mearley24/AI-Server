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
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

import confidence
import event_bus
from decision_journal import get_journal

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


def _polymarket_bot_url() -> str:
    """Trading bot HTTP base. Host .env often uses 127.0.0.1:8430; in Docker that points at OpenClaw itself."""
    u = (os.getenv("POLYMARKET_BOT_URL") or "http://vpn:8430").strip()
    if "://127.0.0.1" in u or "://localhost" in u or "://[::1]" in u:
        return "http://vpn:8430"
    return u


def _polymarket_bot_url_candidates() -> list[str]:
    """Try vpn first, then host-published port (Docker Desktop) — bridge to vpn:8430 can fail."""
    primary = _polymarket_bot_url()
    out: list[str] = []
    for u in (primary, "http://host.docker.internal:8430", "http://vpn:8430"):
        if u not in out:
            out.append(u)
    return out


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
    MAX_PROCESSED_EMAILS = 500

    def __init__(
        self,
        memory=None,
        job_mgr=None,
        dtools_sync=None,
        knowledge_base=None,
        linear_sync=None,
        client_tracker=None,
        data_dir: Optional[Path] = None,
        redis_url: str = "",
        token_tracker: Any = None,
    ):
        # trust_env=False: HTTP(S)_PROXY must not apply to Docker service names (vpn, redis, …);
        # proxies often cause "Server disconnected without sending a response" on internal URLs.
        self.http = httpx.AsyncClient(
            timeout=30.0,
            trust_env=False,
            http2=False,
        )
        self.last_briefing_date = None
        self.processed_emails: set[str] = set()
        self._processed_emails_order: list[str] = []  # FIFO for eviction
        self._cache = ResponseCache(ttl_seconds=300)
        self._memory = memory
        self._last_consolidation: float = 0
        self._last_knowledge_scan: float = 0
        self._health_failures: dict[str, int] = {}  # service -> consecutive failure count
        self._job_worker = None
        self._dtools_sync = dtools_sync
        self._knowledge_base = knowledge_base
        self._client_tracker = client_tracker
        self._job_mgr = job_mgr
        self._data_dir = data_dir or Path(os.getenv("DATA_DIR", "/app/data"))
        self._redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._token_tracker = token_tracker
        self._silent_alert_at: dict[str, float] = {}  # source -> last alert time (epoch)
        self._last_pattern_run: float = 0.0
        if job_mgr:
            from job_worker import JobWorker
            self._job_worker = JobWorker(job_mgr, self.http, linear_sync=linear_sync)

    def _journal(self):
        return get_journal(self._data_dir)

    def _match_email_to_active_client(self, em: dict) -> Optional[str]:
        if not self._client_tracker or not self._job_mgr:
            return None
        active_jobs = self._job_mgr.get_active_jobs()
        client_names = {j["client_name"].lower(): j["client_name"] for j in active_jobs}
        sender_name = (em.get("sender_name") or "").strip().lower()
        sender_addr = (em.get("sender") or "").strip().lower().split("@")[0]
        for client_lower, client_orig in client_names.items():
            if client_lower in sender_name or sender_name in client_lower:
                return client_orig
            if client_lower in sender_addr or sender_addr in client_lower:
                return client_orig
        return None

    async def _redis_publish(self, channel: str, payload: dict) -> None:
        if not self._redis_url:
            return

        def _pub() -> None:
            event_bus.publish_and_log(self._redis_url, channel, payload)

        try:
            await asyncio.to_thread(_pub)
        except Exception as e:
            logger.debug("redis_publish %s: %s", channel, e)

    async def _redis_log_only(self, entry: dict) -> None:
        if not self._redis_url:
            return

        def _log() -> None:
            event_bus.log_only(self._redis_url, entry)

        try:
            await asyncio.to_thread(_log)
        except Exception as e:
            logger.debug("redis_log_only: %s", e)

    async def run_loop(self):
        """Main orchestration loop — runs every 5 minutes."""
        logger.info("Orchestrator starting autonomous loop")

        # One-time: scan ALL existing emails for client preferences
        await self._backfill_client_preferences()

        while True:
            try:
                await self.tick()
            except Exception as e:
                logger.error("Orchestrator tick failed: %s", e)
            await asyncio.sleep(300)  # 5 minutes

    async def tick(self):
        """Single orchestration cycle."""
        logger.info("Orchestrator tick at %s", datetime.now().isoformat())

        try:
            confidence.calibrate_from_journal(self._journal())
        except Exception as e:
            logger.debug("confidence calibrate: %s", e)

        await self.check_emails()
        await self.check_calendar()
        await self.check_pipeline()
        await self.check_trading()
        await self.check_jobs()
        await self.sync_dtools()
        await self.scan_knowledge()
        await self.check_health()
        await self.check_silent_services()
        await self._maybe_run_weekly_patterns()
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

    def _track_processed_email(self, email_id: str) -> None:
        """Add email ID to processed set, evicting oldest if over cap."""
        self.processed_emails.add(email_id)
        self._processed_emails_order.append(email_id)
        while len(self.processed_emails) > self.MAX_PROCESSED_EMAILS:
            oldest = self._processed_emails_order.pop(0)
            self.processed_emails.discard(oldest)

    async def check_emails(self):
        """Check for ALL new unread emails and send a summary. Zero LLM calls.

        Uses direct HTTP (no response cache) to ensure fresh data every tick.
        """
        try:
            # Fetch all recent emails directly (bypass cache for freshness)
            try:
                resp = await self.http.get(
                    f"{SERVICES['email']}/emails",
                    params={"limit": 25},
                )
                if resp.status_code != 200:
                    logger.debug("Email service returned %d", resp.status_code)
                    return
                data = resp.json()
            except Exception as e:
                logger.debug("Email check skipped (fetch failed): %s", e)
                return

            await self._redis_log_only({"source": "email_monitor", "kind": "heartbeat", "via": "orchestrator"})

            all_emails = data if isinstance(data, list) else data.get("emails", [])

            # Filter to only new (unprocessed) emails
            new_emails = []
            for em in all_emails:
                email_id = em.get("id", em.get("message_id", ""))
                if email_id and email_id not in self.processed_emails:
                    new_emails.append(em)
                    self._track_processed_email(email_id)

            if not new_emails:
                return

            logger.info("Found %d new email(s) this tick", len(new_emails))

            for em in new_emails:
                try:
                    cat = em.get("category", "GENERAL")
                    known = self._match_email_to_active_client(em) is not None
                    conf = float(confidence.score_email_action(em, cat, known_client=known))
                    dec_id = self._journal().log_decision(
                        "email",
                        "bob",
                        f"Classified as {cat}",
                        {
                            "subject": em.get("subject", ""),
                            "id": em.get("id", em.get("message_id", "")),
                            "sender": em.get("sender", ""),
                        },
                        confidence=conf,
                    )
                    if confidence.should_act(conf) == "flag_for_approval":
                        subj = (em.get("subject") or "")[:120]
                        ctx = {
                            "subject": subj,
                            "classification": cat,
                            "confidence": conf,
                            "email_id": em.get("id", em.get("message_id", "")),
                        }
                        self._journal().add_pending(dec_id, "email_classification", ctx)
                        try:
                            (self._data_dir / "last_approval_decision.txt").write_text(
                                str(dec_id), encoding="utf-8"
                            )
                        except Exception as e:
                            logger.debug("last_approval_decision write: %s", e)
                        body = (
                            f"Low confidence ({conf:.0f}%) — review: {subj}\n"
                            f"Decision ID: {dec_id}\n"
                            f"Reply YES to acknowledge, NO to dismiss (include ID if not the latest)."
                        )
                        await self.notify("needs_approval", body)
                        await self._redis_publish(
                            "events:system",
                            {
                                "type": "needs_approval",
                                "data": {
                                    "decision_id": dec_id,
                                    "subject": subj,
                                    "classification": cat,
                                    "confidence": conf,
                                },
                            },
                        )
                except Exception as e:
                    logger.debug("email decision log: %s", e)

            # Send individual alerts for high-priority and medium-priority emails
            high_priority_cats = {"BID_INVITE", "CLIENT_INQUIRY"}
            medium_priority_cats = {"FOLLOW_UP_NEEDED", "SCHEDULING"}

            for em in new_emails:
                category = em.get("category", "GENERAL")
                priority = em.get("priority", "low")
                sender = em.get("sender_name") or em.get("sender", "unknown")
                subject = em.get("subject", "(no subject)")

                if category in high_priority_cats or priority == "high":
                    label = "New bid invite" if category == "BID_INVITE" else \
                            "Client inquiry" if category == "CLIENT_INQUIRY" else \
                            f"High-priority email ({category})"
                    await self.notify("email", f"{label} from {sender}: {subject}")

                elif category in medium_priority_cats or priority == "medium":
                    label = "Follow-up needed" if category == "FOLLOW_UP_NEEDED" else \
                            "Scheduling" if category == "SCHEDULING" else \
                            f"Email ({category})"
                    await self.notify("email", f"{label} from {sender}: {subject}")

            # Send a summary digest of ALL new emails
            summary_lines = [f"You have {len(new_emails)} new email(s):"]
            for em in new_emails:
                sender = em.get("sender_name") or em.get("sender", "unknown")
                subject = em.get("subject", "(no subject)")
                category = em.get("category", "GENERAL")
                summary_lines.append(f"  - [{category}] {sender}: {subject}")

            await self.notify("email", "\n".join(summary_lines))

            # Extract client preferences from emails matching active jobs
            await self._extract_client_preferences(new_emails)

        except Exception as e:
            logger.debug("Email check skipped: %s", e)

    async def _backfill_client_preferences(self):
        """One-time scan of all stored emails to extract client preferences for active jobs."""
        if not self._client_tracker or not self._job_mgr:
            return

        try:
            resp = await self.http.get(
                f"{SERVICES['email']}/emails",
                params={"limit": 200},
            )
            if resp.status_code != 200:
                return
            all_emails = resp.json()
            if isinstance(all_emails, dict):
                all_emails = all_emails.get("emails", [])

            logger.info("Backfilling client preferences from %d stored emails", len(all_emails))
            active_jobs = self._job_mgr.get_active_jobs()
            logger.info("Active jobs for backfill: %s", [(j['job_id'], j['client_name']) for j in active_jobs])
            await self._extract_client_preferences(all_emails)
            logger.info("Client preference backfill complete")
        except Exception as e:
            logger.error("Client preference backfill failed: %s", e, exc_info=True)

    async def _extract_client_preferences(self, emails: list):
        """Match emails to active job clients and extract preferences."""
        if not self._client_tracker or not self._job_mgr:
            return

        try:
            active_jobs = self._job_mgr.get_active_jobs()
            client_names = {j["client_name"].lower(): j["client_name"] for j in active_jobs}

            for em in emails:
                sender_name = (em.get("sender_name") or "").strip()
                sender_addr = (em.get("sender") or "").strip()
                subject = em.get("subject", "")
                snippet = em.get("snippet", "")
                summary = em.get("summary", "")

                # Match sender to a known client (fuzzy + alias)
                # Aliases handle stopletz1 -> Topletz etc.
                _ALIASES = {
                    "topletz": ["toplets", "topletz", "stopletz", "stopletz1", "steve toplets", "steve topletz"],
                }
                matched_client = None
                s_name = sender_name.lower()
                s_addr = sender_addr.lower().split("@")[0]  # just the username part
                for client_lower, client_orig in client_names.items():
                    # Direct match
                    if (client_lower in s_name or s_name in client_lower
                            or client_lower in s_addr or s_addr in client_lower):
                        matched_client = client_orig
                        break
                    # Alias match
                    for alias_key, aliases in _ALIASES.items():
                        if alias_key in client_lower or any(a in client_lower for a in aliases):
                            if any(a in s_name or a in s_addr for a in aliases):
                                matched_client = client_orig
                                break
                    if matched_client:
                        break

                if matched_client:
                    # Auto-capture contact info from email
                    self._client_tracker.update_client_from_email(
                        matched_client, sender_addr, sender_name
                    )
                    await self._redis_publish(
                        "events:email",
                        {
                            "type": "email.client_reply",
                            "data": {
                                "client_name": matched_client,
                                "subject": subject,
                                "sentiment": "positive",
                            },
                        },
                    )
                    # Extract preferences via LLM
                    logger.info("Extracting preferences for client %s from: %s", matched_client, subject[:60])
                    self._client_tracker.extract_preferences_from_analysis(
                        client_name=matched_client,
                        sender_name=sender_name,
                        subject=subject,
                        snippet=snippet,
                        analysis_summary=summary,
                    )
        except Exception as e:
            logger.debug("Client preference extraction error: %s", e)

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
            if data is not None:
                await self._redis_log_only({"source": "calendar_agent", "kind": "heartbeat", "via": "orchestrator"})
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
        status_data = None
        bot_url = ""
        last_err: Exception | None = None
        candidates = _polymarket_bot_url_candidates()
        for base in candidates:
            try:
                resp = await self.http.get(f"{base}/status")
                if resp.status_code == 200:
                    status_data = resp.json()
                    bot_url = base
                    break
                last_err = RuntimeError(f"HTTP {resp.status_code}")
            except Exception as e:
                last_err = e
                continue
        if status_data is None:
            logger.warning(
                "Trading bot unreachable (tried %s): %s",
                candidates,
                last_err,
            )
            return

        await self._redis_log_only(
            {"source": "polymarket_bot", "kind": "heartbeat", "via": "orchestrator", "base_url": bot_url}
        )

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
    # Job lifecycle check
    # ------------------------------------------------------------------
    async def check_jobs(self):
        """Run the job worker tick — scans emails for leads, checks active jobs."""
        if not self._job_worker:
            return
        try:
            await self._job_worker.scan_emails_for_leads()
            await self._job_worker.tick()
        except Exception as e:
            logger.debug("Job worker tick failed: %s", e)

    # ------------------------------------------------------------------
    # D-Tools sync
    # ------------------------------------------------------------------
    async def sync_dtools(self):
        """Sync D-Tools opportunities/projects into job lifecycle."""
        if not self._dtools_sync:
            return
        try:
            result = await self._dtools_sync.sync()
            if result.get("status") == "ok":
                created = result.get("jobs_created", 0)
                linked = result.get("jobs_linked", 0)
                if created or linked:
                    logger.info("D-Tools sync: %d created, %d linked", created, linked)
                try:
                    self._journal().log_decision(
                        "jobs",
                        "bob",
                        f"D-Tools sync: created={created}, linked={linked}",
                        dict(result),
                        confidence=88.0,
                    )
                except Exception as e:
                    logger.debug("journal dtools: %s", e)
        except Exception as e:
            logger.debug("D-Tools sync failed: %s", e)

    # ------------------------------------------------------------------
    # Knowledge base scan — runs once per hour
    # ------------------------------------------------------------------
    async def scan_knowledge(self):
        """Scan iCloud docs folder for new/changed files. Runs once per hour."""
        if not self._knowledge_base:
            return

        now = time.time()
        if now - self._last_knowledge_scan < 3600:
            return

        self._last_knowledge_scan = now
        try:
            result = self._knowledge_base.scan()
            if result.get("status") == "ok":
                added = result.get("added", 0)
                if added:
                    logger.info("Knowledge scan: %d new documents indexed", added)
        except Exception as e:
            logger.debug("Knowledge scan failed: %s", e)

    # ------------------------------------------------------------------
    # Weekly patterns (decision journal + email timestamps)
    # ------------------------------------------------------------------
    async def _maybe_run_weekly_patterns(self) -> None:
        """Refresh data/patterns.json at most once per 7 days per process."""
        now = time.time()
        week = 604800.0
        if self._last_pattern_run and (now - self._last_pattern_run) < week:
            return
        try:
            from pattern_engine import run_weekly

            run_weekly(self._data_dir, self._journal())
            self._last_pattern_run = now
        except Exception as e:
            logger.debug("weekly patterns: %s", e)

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
            urls_to_try = _polymarket_bot_url_candidates() if name == "polymarket-bot" else [url]
            ok = False
            for u in urls_to_try:
                try:
                    resp = await self.http.get(f"{u}/health", timeout=10.0)
                    if resp.status_code == 200:
                        ok = True
                        break
                except Exception:
                    pass
            if ok:
                if name in self._health_failures:
                    logger.info("Service %s recovered after %d failed ticks", name, self._health_failures[name])
                    del self._health_failures[name]
                    if self._memory:
                        self._memory.remember(
                            f"health_{name}", f"{name} recovered at {datetime.now().isoformat()}",
                            category="project_context", source_agent="orchestrator",
                        )
                continue

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

            # Active jobs summary
            if self._job_worker:
                try:
                    active = self._job_worker._jobs.get_active_jobs()
                    if active:
                        briefing_parts.append(f"Active jobs: {len(active)}")
                        for j in active[:5]:
                            briefing_parts.append(f"  - {j['client_name']}: {j['project_name'] or '(unnamed)'} [{j['phase']}]")
                except Exception:
                    pass

            # Health summary
            if self._health_failures:
                down = [f"{k} ({v} ticks)" for k, v in self._health_failures.items()]
                briefing_parts.append(f"Services down: {', '.join(down)}")
            else:
                briefing_parts.append("All services healthy")

            try:
                briefing_parts.append("\n— This week (decisions) —")
                briefing_parts.append(self._journal().weekly_digest_text())
            except Exception:
                pass
            if self._token_tracker:
                try:
                    ts = self._token_tracker.summary()
                    briefing_parts.append(
                        "Tokens today: %(tokens_used)d / %(budget)d (remaining %(remaining)d)"
                        % ts
                    )
                except Exception:
                    pass
            try:
                from cost_tracker import CostTracker

                ws = CostTracker(self._data_dir).get_weekly_summary()
                if ws:
                    briefing_parts.append("Costs (7d) by category: " + ", ".join(f"{k}=${v:.2f}" for k, v in ws.items()))
            except Exception:
                pass

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

    async def resolve_approval(self, decision_id: int, granted: bool, edit_note: str = "") -> None:
        """Complete a pending approval from iMessage or Redis (outcome_listener)."""
        j = self._journal()
        row = j.get_pending(decision_id)
        if not row or row.get("status") != "pending":
            logger.warning("resolve_approval: no pending row for id=%s", decision_id)
            return
        outcome = "approval_granted" if granted else "approval_denied"
        score = 0.4 if granted else -0.3
        j.update_outcome(decision_id, outcome, score)
        j.close_pending(decision_id, "granted" if granted else "denied")
        note = (edit_note or "").strip()
        msg = (
            f"Decision {decision_id}: {'APPROVED' if granted else 'DENIED'}"
            + (f" — note: {note[:200]}" if note else "")
        )
        await self.notify("approval", msg)
        await self._redis_publish(
            "events:system",
            {
                "type": "approval.resolved",
                "data": {
                    "decision_id": decision_id,
                    "granted": granted,
                    "edit_note": note,
                },
            },
        )
        logger.info("resolve_approval id=%s granted=%s", decision_id, granted)

    async def check_silent_services(self) -> None:
        """Alert if heartbeats in events:log are older than ~2 hours."""
        if not self._redis_url:
            return

        def _read_log() -> list[str]:
            import redis as redis_sync

            r = redis_sync.from_url(self._redis_url, decode_responses=True)
            try:
                return r.lrange(event_bus.LOG_KEY, 0, 400)
            finally:
                r.close()

        try:
            raw_lines = await asyncio.to_thread(_read_log)
        except Exception as e:
            logger.debug("check_silent_services lrange: %s", e)
            return

        sources = ("email_monitor", "calendar_agent", "polymarket_bot")
        latest_ts: dict[str, float] = {}
        now = datetime.now(timezone.utc).timestamp()
        stale_after = 7200.0  # 2 hours
        cooldown = 1800.0  # re-alert at most every 30 min per source

        for line in raw_lines:
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            src = obj.get("source") or ""
            if src not in sources:
                continue
            ts_raw = obj.get("ts") or ""
            try:
                ts_clean = ts_raw.replace("Z", "+00:00") if ts_raw.endswith("Z") else ts_raw
                t = datetime.fromisoformat(ts_clean)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                sec = t.timestamp()
            except Exception:
                continue
            if src not in latest_ts or sec > latest_ts[src]:
                latest_ts[src] = sec

        for src in sources:
            last = latest_ts.get(src)
            if last is None or (now - last) <= stale_after:
                continue
            prev_alert = self._silent_alert_at.get(src, 0.0)
            if now - prev_alert < cooldown:
                continue
            self._silent_alert_at[src] = now
            mins = int((now - last) / 60) if last else -1
            msg = f"No {src} heartbeat in events:log for ~{mins} min (threshold {int(stale_after/60)} min)"
            logger.warning("silent_service %s", msg)
            await self.notify("health", msg)
            await self._redis_publish(
                "events:system",
                {"type": "service_quiet", "data": {"source": src, "minutes_silent": mins}},
            )

    async def close(self):
        await self.http.aclose()
