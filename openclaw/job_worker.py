"""
Job Worker — runs on each orchestrator tick (5 minutes).

Scans emails for job-related messages, checks D-Tools for status changes,
evaluates phase transition triggers, and sends notifications about progress.
Lightweight — no LLM calls on routine ticks.
"""

import json
import logging
from pathlib import Path
import os
import re
from datetime import datetime, timedelta

import httpx

from job_lifecycle import JobLifecycleManager, Phase, PHASE_DEFS

logger = logging.getLogger("openclaw.job_worker")

SERVICES = {
    "email": os.getenv("EMAIL_MONITOR_URL", "http://email-monitor:8092"),
    "dtools": os.getenv("DTOOLS_BRIDGE_URL", "http://dtools-bridge:5050"),
    "notifications": os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095"),
    "calendar": os.getenv("CALENDAR_AGENT_URL", "http://calendar-agent:8094"),
}

_ROUTING_CFG_CACHE: dict | None = None


def _email_routing_config_path() -> str:
    return os.getenv(
        "EMAIL_ROUTING_CONFIG",
        str(Path(__file__).resolve().parents[1] / "email-monitor" / "routing_config.json"),
    )


def _load_routing_cfg() -> dict:
    global _ROUTING_CFG_CACHE
    if _ROUTING_CFG_CACHE is not None:
        return _ROUTING_CFG_CACHE
    try:
        with open(_email_routing_config_path(), encoding="utf-8") as f:
            _ROUTING_CFG_CACHE = json.load(f)
    except Exception:
        _ROUTING_CFG_CACHE = {}
    return _ROUTING_CFG_CACHE


# Sender prefixes / domains that are never leads
_SKIP_SENDER_PREFIXES = (
    "no-reply", "noreply", "no_reply", "do-not-reply", "donotreply",
    "notifications@", "notification@", "updates@", "news@",
    "newsletter@", "marketing@", "info@symphonysh", "bob@symphonysh",
    "mailer@", "bounce@", "postmaster@", "support@", "hello@",
    "billing@", "invoices@", "receipts@", "orders@",
)
_SKIP_SENDER_DOMAINS = (
    "thefuturist.co", "vyde.io", "dtools.com", "d-tools.com",
    "snapone.com", "control4.com", "lutron.com",
    "paypal.com", "stripe.com", "square.com",
    "quickbooks.com", "intuit.com",
    "mailchimp.com", "constantcontact.com", "hubspot.com",
    "linkedin.com", "facebook.com", "twitter.com",
    "amazon.com", "fedex.com", "ups.com", "usps.com",
)


def _lead_scan_skip_sender(sender_addr: str) -> bool:
    """Return True if sender should never be treated as a potential lead."""
    if not (sender_addr or "").strip():
        return True  # blank sender = skip
    em  = sender_addr.strip().lower()
    dom = em.split("@", 1)[-1] if "@" in em else em

    # Built-in skip lists
    if any(em.startswith(p) for p in _SKIP_SENDER_PREFIXES):
        return True
    if dom in _SKIP_SENDER_DOMAINS:
        return True

    # Routing config skip (vendor/marketing already categorised)
    cfg = _load_routing_cfg()
    cat = cfg.get("category_routes") or {}
    if any(k.lower() == em for k in cat):
        return True
    dr = cfg.get("domain_routes") or {}
    if em in dr or dom in dr:
        return True

    return False



# Vendor keywords for procurement tracking
VENDOR_KEYWORDS = [
    "snap one", "snapav", "control4", "lutron", "crestron", "sonos",
    "pakedge", "wattbox", "triad", "episode", "binary", "araknis",
    "shipped", "tracking", "delivery", "order confirmation", "backorder",
]


class JobWorker:
    """Background worker that checks job state on each orchestrator tick."""

    def __init__(self, job_mgr: JobLifecycleManager, http: httpx.AsyncClient = None, linear_sync=None):
        self._jobs = job_mgr
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._last_proposal_check: dict[int, str] = {}  # job_id -> last check timestamp
        self._linear_sync = linear_sync

    async def tick(self):
        """Run one check cycle across all active jobs."""
        active_jobs = self._jobs.get_active_jobs()
        if not active_jobs:
            return

        logger.info("job_worker_tick active_jobs=%d", len(active_jobs))

        for job in active_jobs:
            try:
                await self._check_job(job)
            except Exception as e:
                logger.error("job_worker_error job_id=%d error=%s", job["job_id"], e)

    async def _check_job(self, job: dict):
        """Check a single job based on its current phase."""
        phase = job["phase"]
        job_id = job["job_id"]

        if phase == Phase.LEAD.value:
            # LEAD jobs are created by scan_emails_for_leads — nothing to check here
            pass

        elif phase == Phase.QUOTE.value:
            await self._check_quote_phase(job)

        elif phase == Phase.PROPOSAL.value:
            await self._check_proposal_followup(job)

        elif phase in (Phase.NEGOTIATION.value, Phase.WON.value):
            await self._check_dtools_status(job)

        elif phase == Phase.PROCUREMENT.value:
            await self._check_procurement(job)

        elif phase == Phase.SCHEDULING.value:
            await self._check_scheduling(job)

        elif phase in (Phase.INSTALLATION.value, Phase.PROGRAMMING.value, Phase.COMMISSIONING.value):
            await self._check_active_install(job)

    # ------------------------------------------------------------------
    # Email scanning for new leads
    # ------------------------------------------------------------------

    async def scan_emails_for_leads(self):
        """Scan recent client inquiry emails. Notifies owner but does NOT auto-create jobs.

        Jobs should be created manually ('new job <name>') to avoid spam from
        miscategorized emails. Bob notifies about potential leads so the owner
        can decide which ones to track.
        """
        try:
            resp = await self._http.get(
                f"{SERVICES['email']}/emails",
                params={"category": "CLIENT_INQUIRY", "limit": 10},
            )
            if resp.status_code != 200:
                return
            emails = resp.json()
            if isinstance(emails, dict):
                emails = emails.get("emails", [])
        except Exception as e:
            logger.debug("lead_scan_failed: %s", e)
            return

        existing_jobs = self._jobs.get_all_jobs()
        existing_clients = {j["client_name"].lower() for j in existing_jobs}

        for email in emails:
            sender_name = email.get("sender_name", "").strip()
            sender_addr = email.get("sender", "").strip()
            subject = email.get("subject", "")
            summary = email.get("summary", "")

            if _lead_scan_skip_sender(sender_addr):
                continue
            subjl = (subject or "").lower()
            if any(h in subjl for h in ("newsletter", "unsubscribe", "digest")):
                continue

            if not sender_name:
                sender_name = sender_addr.split("@")[0].replace(".", " ").title()

            # Skip if we already have a job for this client
            if sender_name.lower() in existing_clients:
                continue

            # Log it and notify — don't auto-create jobs.
            # Owner creates jobs manually with 'new job <name>'.
            logger.info("potential_lead client=%s subject=%s", sender_name, subject[:60])

    # ------------------------------------------------------------------
    # Phase-specific checks
    # ------------------------------------------------------------------

    async def _check_quote_phase(self, job: dict):
        """QUOTE: Pull D-Tools opportunity data if linked."""
        d_tools_id = job.get("d_tools_id", "")
        if not d_tools_id:
            # Try to find matching opportunity in D-Tools
            await self._try_link_dtools(job)
            return

        try:
            resp = await self._http.get(f"{SERVICES['dtools']}/pipeline")
            if resp.status_code != 200:
                return
            data = resp.json()
            opps = data.get("opportunities", data.get("open_opportunities", {}).get("Data", []))
            for opp in opps if isinstance(opps, list) else []:
                opp_id = str(opp.get("Id", opp.get("id", "")))
                if opp_id == d_tools_id:
                    status = opp.get("Status", opp.get("status", ""))
                    if status.lower() in ("quoted", "sent"):
                        self._jobs.add_note(job["job_id"], f"D-Tools opportunity status: {status}")
        except Exception as e:
            logger.debug("quote_check_failed job_id=%d: %s", job["job_id"], e)

    async def _check_proposal_followup(self, job: dict):
        """PROPOSAL: Track follow-up timing."""
        job_id = job["job_id"]
        timeline = self._jobs.get_job_timeline(job_id)

        # Find when the job entered PROPOSAL phase
        proposal_start = None
        for event in timeline:
            if event["event_type"] == "phase_change" and event["phase_to"] == "PROPOSAL":
                proposal_start = event["timestamp"]
                break

        if not proposal_start:
            return

        try:
            entered = datetime.fromisoformat(proposal_start)
        except (ValueError, TypeError):
            return

        now = datetime.utcnow()
        days_in_phase = (now - entered).days

        # Check if we already notified recently
        last_check = self._last_proposal_check.get(job_id, "")
        today = now.strftime("%Y-%m-%d")
        if last_check == today:
            return
        self._last_proposal_check[job_id] = today

        client = job["client_name"]
        if days_in_phase == 3:
            await self._notify("jobs", f"3-day follow-up due for {client} — proposal sent 3 days ago. Time to check in.")
            self._jobs.add_note(job_id, "3-day follow-up reminder sent")
        elif days_in_phase == 7:
            await self._notify("jobs", f"7-day follow-up due for {client} — no response to proposal yet. Consider calling.")
            self._jobs.add_note(job_id, "7-day follow-up reminder sent")
        elif days_in_phase == 14:
            await self._notify("jobs", f"14 days since proposal sent to {client} — may need to re-engage or close out.")
            self._jobs.add_note(job_id, "14-day follow-up reminder sent")

    async def _check_dtools_status(self, job: dict):
        """Check D-Tools for status changes (NEGOTIATION, WON phases)."""
        d_tools_id = job.get("d_tools_id", "")
        if not d_tools_id:
            return

        try:
            resp = await self._http.get(f"{SERVICES['dtools']}/pipeline")
            if resp.status_code != 200:
                return
            data = resp.json()
            opps = data.get("opportunities", data.get("open_opportunities", {}).get("Data", []))
            for opp in opps if isinstance(opps, list) else []:
                opp_id = str(opp.get("Id", opp.get("id", "")))
                if opp_id == d_tools_id:
                    status = opp.get("Status", opp.get("status", ""))
                    if status.lower() == "won" and job["phase"] != Phase.WON.value:
                        old_phase = job["phase"]
                        result = self._jobs.advance_phase(job["job_id"], f"D-Tools opportunity marked as Won")
                        if result:
                            new_phase = result.get("job", {}).get("phase", Phase.WON.value)
                            await self._sync_linear_phase(job, old_phase, new_phase)
                            await self._notify(
                                "jobs",
                                f"Job WON: {job['client_name']} — {job['project_name']}! "
                                f"Creating project and starting procurement."
                            )
        except Exception as e:
            logger.debug("dtools_status_check_failed job_id=%d: %s", job["job_id"], e)

    async def _check_procurement(self, job: dict):
        """PROCUREMENT: Track vendor emails for shipping/order updates."""
        client = job["client_name"]
        project = job["project_name"]

        try:
            # Search for vendor-related emails mentioning the project or client
            search_terms = [client]
            if project:
                search_terms.append(project)

            for term in search_terms:
                resp = await self._http.get(
                    f"{SERVICES['email']}/emails/search",
                    params={"q": term, "limit": 5},
                )
                if resp.status_code != 200:
                    continue

                emails = resp.json()
                if isinstance(emails, dict):
                    emails = emails.get("emails", [])

                for email in emails:
                    subject = (email.get("subject", "") + " " + email.get("snippet", "")).lower()
                    if any(kw in subject for kw in VENDOR_KEYWORDS):
                        sender = email.get("sender_name") or email.get("sender", "?")
                        subj = email.get("subject", "")
                        # Check if already noted
                        msg_id = email.get("message_id", email.get("id", ""))
                        meta = job.get("metadata", {})
                        noted = meta.get("noted_emails", [])
                        if msg_id and msg_id not in noted:
                            self._jobs.add_note(
                                job["job_id"],
                                f"Vendor update from {sender}: {subj}",
                            )
                            noted.append(msg_id)
                            self._jobs.update_metadata(job["job_id"], {"noted_emails": noted})
                            await self._notify(
                                "jobs",
                                f"Equipment update for {project or client}: {sender} — {subj}",
                            )
        except Exception as e:
            logger.debug("procurement_check_failed job_id=%d: %s", job["job_id"], e)

    async def _check_scheduling(self, job: dict):
        """SCHEDULING: Check calendar for install dates."""
        client = job["client_name"]
        try:
            resp = await self._http.get(
                f"{SERVICES['calendar']}/calendar/upcoming",
                params={"hours": 168},  # 7 days
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            events = data if isinstance(data, list) else data.get("events", [])
            for event in events:
                title = (event.get("title", "") + " " + event.get("summary", "")).lower()
                if client.lower() in title or "install" in title:
                    start = event.get("start", event.get("start_time", ""))
                    self._jobs.add_note(
                        job["job_id"],
                        f"Install event found: {event.get('title', '')} at {start}",
                    )
        except Exception as e:
            logger.debug("scheduling_check_failed job_id=%d: %s", job["job_id"], e)

    async def _check_active_install(self, job: dict):
        """INSTALLATION/PROGRAMMING/COMMISSIONING: Track progress via emails."""
        client = job["client_name"]
        try:
            resp = await self._http.get(
                f"{SERVICES['email']}/emails/search",
                params={"q": client, "limit": 3},
            )
            if resp.status_code != 200:
                return
            # Just log — no action unless significant
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _try_link_dtools(self, job: dict):
        """Try to find and link a D-Tools opportunity matching this job's client."""
        client = job["client_name"]
        try:
            resp = await self._http.get(f"{SERVICES['dtools']}/pipeline")
            if resp.status_code != 200:
                return
            data = resp.json()
            opps = data.get("opportunities", data.get("open_opportunities", {}).get("Data", []))
            for opp in opps if isinstance(opps, list) else []:
                name = opp.get("Name", opp.get("name", ""))
                client_name = opp.get("ClientName", opp.get("client_name", ""))
                if client.lower() in name.lower() or client.lower() in client_name.lower():
                    opp_id = str(opp.get("Id", opp.get("id", "")))
                    self._jobs.link_dtools(job["job_id"], opp_id)
                    logger.info("auto_linked_dtools job_id=%d opp_id=%s", job["job_id"], opp_id)
                    return
        except Exception as e:
            logger.debug("dtools_link_failed job_id=%d: %s", job["job_id"], e)

    async def _notify(self, channel: str, message: str):
        """Send notification via notification-hub."""
        try:
            await self._http.post(
                f"{SERVICES['notifications']}/notify",
                json={"title": f"Bob [{channel}]", "body": message, "priority": "normal"},
            )
        except Exception as e:
            logger.debug("job_notify_failed: %s", e)

    async def _sync_linear_phase(self, job: dict, old_phase: str, new_phase: str):
        """Notify Linear sync when a job advances phase."""
        if not self._linear_sync:
            return
        try:
            await self._linear_sync.on_phase_advance(
                job["job_id"], old_phase, new_phase,
                job["client_name"], job.get("project_name", ""),
            )
        except Exception as e:
            logger.debug("linear_sync_failed job_id=%d: %s", job["job_id"], e)

    async def close(self):
        await self._http.aclose()
