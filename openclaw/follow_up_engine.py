"""
Follow-Up Engine — automatically sends timed follow-up emails when no client
response is received after a proposal is sent.

On each orchestrator tick this module:
  1. Queries jobs.db for all PROPOSAL and NEGOTIATION phase jobs.
  2. For each job, determines how many days have elapsed since the last
     inbound email from that client (using emails.db).
  3. Fires the appropriate follow-up at the 3-, 7-, and 14-day intervals,
     never sending more than one follow-up per interval per job.
  4. Logs every sent follow-up in the `follow_up_log` table (jobs.db).
  5. At the 14-day milestone, also creates a Linear comment noting the
     lack of response.

Integration points
------------------
- jobs.db     : JOBS_DB_PATH  env  (default /data/jobs.db)
- emails.db   : EMAIL_DB_PATH env  (default /data/emails.db)
- Notification: HTTP POST http://notification-hub:8095/api/send
- Zoho draft  : same endpoint, channel="zoho_draft"
- Linear      : LinearSync instance (optional, injected)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("openclaw.follow_up_engine")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_JOBS_DB = os.environ.get("JOBS_DB_PATH", "/data/jobs.db")
DEFAULT_EMAILS_DB = os.environ.get("EMAIL_DB_PATH", "/data/emails.db")
# follow_up_log lives in follow_ups.db (canonical follow-up store), not jobs.db.
# Derive path from FOLLOW_UPS_DB_PATH env or compute from the jobs_db directory
# at runtime so it always resolves correctly regardless of container paths.
DEFAULT_FOLLOW_UPS_DB = os.environ.get("FOLLOW_UPS_DB_PATH", "")
NOTIFICATION_HUB_URL = os.environ.get(
    "NOTIFICATION_HUB_URL", "http://notification-hub:8095"
)

# Phases that require follow-up monitoring
TRACKED_PHASES = {"PROPOSAL", "NEGOTIATION"}

# Follow-up intervals (days without a client response → send template)
FOLLOW_UP_INTERVALS = [3, 7, 14]

# ── Email templates ────────────────────────────────────────────────────────────
# Sourced from job_lifecycle.PHASE_DEFS[PROPOSAL]["templates"] plus followup_14d.
TEMPLATES: dict[int, str] = {
    3: (
        "Hi {client_name}, just checking in on the proposal we sent over. "
        "Happy to answer any questions."
    ),
    7: (
        "Hi {client_name}, wanted to circle back on the proposal. "
        "Let me know if you'd like to discuss or adjust anything."
    ),
    14: (
        "Hi {client_name}, I wanted to reach out one more time regarding the "
        "proposal for {project_name}. If the timing isn't right or you have "
        "questions, I'm happy to discuss. Just let me know."
    ),
}

TEMPLATE_NAMES: dict[int, str] = {
    3: "followup_3d",
    7: "followup_7d",
    14: "followup_14d",
}


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_conn(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and row_factory."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_follow_up_log(conn: sqlite3.Connection) -> None:
    """Create the follow_up_log table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_up_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       INTEGER NOT NULL,
            interval_days INTEGER NOT NULL,
            sent_at      TEXT    NOT NULL,
            email_id     TEXT    DEFAULT '',
            template     TEXT    DEFAULT '',
            UNIQUE (job_id, interval_days)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ful_job ON follow_up_log(job_id)"
    )
    conn.commit()


# ── Main class ─────────────────────────────────────────────────────────────────

class FollowUpEngine:
    """
    Scheduled follow-up engine.

    Parameters
    ----------
    jobs_db:
        Path to jobs.db SQLite database.
    emails_db:
        Path to emails.db SQLite database (email monitor output).
    http:
        Shared httpx.AsyncClient for outbound HTTP calls.
    linear_sync:
        Optional LinearSync instance; used to create comments on 14-day fire.
    """

    def __init__(
        self,
        jobs_db: str = DEFAULT_JOBS_DB,
        emails_db: str = DEFAULT_EMAILS_DB,
        follow_ups_db: str = DEFAULT_FOLLOW_UPS_DB,
        http: Optional[httpx.AsyncClient] = None,
        linear_sync=None,
    ) -> None:
        self._jobs_db = jobs_db
        self._emails_db = emails_db
        # follow_up_log lives in follow_ups.db (canonical store).
        # If follow_ups_db is not specified, derive it from the jobs_db directory.
        if not follow_ups_db:
            follow_ups_db = str(Path(jobs_db).parent / "follow_ups.db")
        self._follow_ups_db = follow_ups_db
        self._http = http or httpx.AsyncClient(timeout=15.0)
        self._linear = linear_sync

        # Initialise the follow_up_log table in follow_ups.db
        with _get_conn(self._follow_ups_db) as conn:
            _ensure_follow_up_log(conn)

        logger.info(
            "follow_up_engine_init jobs_db=%s emails_db=%s follow_ups_db=%s",
            jobs_db, emails_db, follow_ups_db,
        )

    # ── Public interface ───────────────────────────────────────────────────────

    async def tick(self) -> int:
        """
        Run one engine cycle.

        Returns
        -------
        int
            Number of follow-up emails sent during this tick.
        """
        sent_count = 0

        jobs = self._get_tracked_jobs()
        logger.debug("follow_up_engine.tick: %d tracked jobs", len(jobs))

        for job in jobs:
            for interval in FOLLOW_UP_INTERVALS:
                try:
                    if await self._should_follow_up(job, interval):
                        ok = await self._send_follow_up(job, interval)
                        if ok:
                            sent_count += 1
                            # Once the 14-day follow-up fires, stop checking
                            # shorter intervals for this job (they were already sent).
                            if interval == 14:
                                break
                except Exception as exc:
                    logger.warning(
                        "follow_up error job_id=%s interval=%d: %s",
                        job.get("job_id"),
                        interval,
                        exc,
                    )

        logger.info("follow_up_engine.tick: sent %d follow-ups", sent_count)
        return sent_count

    async def _should_follow_up(self, job: dict, interval_days: int) -> bool:
        """
        Determine whether a follow-up at *interval_days* should be sent.

        Rules
        -----
        - Days since last inbound client email >= interval_days.
        - That specific interval has not already been logged for this job.
        """
        job_id = job["job_id"]
        client_name = job.get("client_name", "")
        client_email = self._resolve_client_email(job)

        days_since = await self._get_days_since_last_client_email(
            client_name, client_email
        )
        if days_since < interval_days:
            return False

        # Check whether this interval was already sent
        if self._already_sent(job_id, interval_days):
            return False

        # Also ensure the previous interval was sent (enforce ordering)
        prev_intervals = [i for i in FOLLOW_UP_INTERVALS if i < interval_days]
        for prev in prev_intervals:
            if not self._already_sent(job_id, prev):
                # Previous interval not sent yet; skip this one
                return False

        return True

    async def _send_follow_up(self, job: dict, interval_days: int) -> bool:
        """
        Compose and send a follow-up email for *job* at *interval_days*.

        Side-effects
        ------------
        - POSTs to notification-hub (email channel).
        - POSTs to notification-hub (zoho_draft channel) for owner review.
        - On 14-day interval: creates a Linear comment.
        - Records the send in follow_up_log.

        Returns True on success.
        """
        job_id = job["job_id"]
        client_name = job.get("client_name", "Unknown")
        project_name = job.get("project_name", "your project")
        client_email = self._resolve_client_email(job)

        template_body = TEMPLATES[interval_days].format(
            client_name=client_name,
            project_name=project_name,
        )
        template_name = TEMPLATE_NAMES[interval_days]

        logger.info(
            "follow_up_sending job_id=%d interval=%d client=%s template=%s",
            job_id,
            interval_days,
            client_name,
            template_name,
        )

        # ── 1. Send email via notification-hub ───────────────────────────────
        email_id = ""
        try:
            resp = await self._http.post(
                f"{NOTIFICATION_HUB_URL}/api/send",
                json={
                    "message": template_body,
                    "channel": "email",
                    "to": client_email,
                    "priority": "normal",
                    "subject": self._build_subject(interval_days, project_name),
                    "metadata": {
                        "job_id": job_id,
                        "template": template_name,
                        "interval_days": interval_days,
                    },
                },
                timeout=15.0,
            )
            if resp.status_code in (200, 201, 202):
                try:
                    email_id = resp.json().get("email_id", "")
                except Exception:
                    pass
                logger.info(
                    "follow_up_sent job_id=%d interval=%d email_id=%s",
                    job_id,
                    interval_days,
                    email_id,
                )
            else:
                logger.warning(
                    "follow_up_send_failed job_id=%d interval=%d status=%d body=%s",
                    job_id,
                    interval_days,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.warning(
                "follow_up_send_error job_id=%d interval=%d: %s",
                job_id,
                interval_days,
                exc,
            )
            return False

        # ── 2. Publish Zoho draft for owner review ────────────────────────────
        try:
            await self._http.post(
                f"{NOTIFICATION_HUB_URL}/api/send",
                json={
                    "message": template_body,
                    "channel": "zoho_draft",
                    "to": client_email,
                    "priority": "normal",
                    "subject": self._build_subject(interval_days, project_name),
                    "metadata": {
                        "job_id": job_id,
                        "template": template_name,
                        "interval_days": interval_days,
                        "draft_reason": f"{interval_days}-day follow-up for review",
                    },
                },
                timeout=15.0,
            )
        except Exception as exc:
            logger.debug("zoho_draft_publish_error job_id=%d: %s", job_id, exc)

        # ── 3. 14-day: create a Linear comment ───────────────────────────────
        if interval_days == 14 and self._linear:
            await self._create_linear_no_response_comment(job, template_body)

        # ── 4. Log in follow_up_log ───────────────────────────────────────────
        self._record_sent(job_id, interval_days, email_id, template_name)
        return True

    async def _get_days_since_last_client_email(
        self, client_name: str, client_email: str
    ) -> int:
        """
        Query emails.db to find the most recent inbound email from the client
        and return the number of whole days elapsed since that timestamp.

        Falls back to a very large number (999) if no email is found, which
        causes all intervals to fire — safe for newly-created jobs.

        Matching strategy (in order):
        1. Exact sender address match (if client_email is known and non-placeholder).
        2. Sender name LIKE match (case-insensitive).
        """
        if not os.path.exists(self._emails_db):
            logger.debug("emails.db not found at %s", self._emails_db)
            return 999

        try:
            conn = sqlite3.connect(self._emails_db)
            conn.row_factory = sqlite3.Row

            last_ts: Optional[str] = None

            # Strategy 1: exact email address match (skip placeholder addresses)
            if client_email and "@symphony.placeholder" not in client_email:
                row = conn.execute(
                    """
                    SELECT received_at FROM emails
                    WHERE LOWER(sender) = LOWER(?)
                    ORDER BY received_at DESC
                    LIMIT 1
                    """,
                    (client_email.strip(),),
                ).fetchone()
                if row:
                    last_ts = row["received_at"]

            # Strategy 2: sender name match
            if not last_ts and client_name:
                # Use each token of the client name for better recall
                tokens = [t for t in client_name.split() if len(t) >= 3]
                for token in tokens:
                    row = conn.execute(
                        """
                        SELECT received_at FROM emails
                        WHERE LOWER(sender_name) LIKE LOWER(?)
                        ORDER BY received_at DESC
                        LIMIT 1
                        """,
                        (f"%{token}%",),
                    ).fetchone()
                    if row:
                        last_ts = row["received_at"]
                        break

            conn.close()

            if not last_ts:
                return 999  # No email found — treat as very old

            last_dt = _parse_iso(last_ts)
            if last_dt is None:
                return 999

            now = datetime.now(timezone.utc)
            delta = now - last_dt
            return max(0, delta.days)

        except Exception as exc:
            logger.warning(
                "_get_days_since_last_client_email error client=%s: %s",
                client_name,
                exc,
            )
            return 999

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_tracked_jobs(self) -> list[dict]:
        """Return all jobs in PROPOSAL or NEGOTIATION phase."""
        try:
            conn = _get_conn(self._jobs_db)
            phases_sql = ", ".join(f"'{p}'" for p in TRACKED_PHASES)
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE phase IN ({phases_sql}) ORDER BY updated_at DESC"
            ).fetchall()
            jobs = []
            for row in rows:
                j = dict(row)
                try:
                    j["metadata"] = json.loads(j.get("metadata") or "{}")
                except (json.JSONDecodeError, TypeError):
                    j["metadata"] = {}
                jobs.append(j)
            conn.close()
            return jobs
        except Exception as exc:
            logger.warning("_get_tracked_jobs error: %s", exc)
            return []

    def _resolve_client_email(self, job: dict) -> str:
        """
        Extract the client email for a job.

        Checks (in order):
        1. job.metadata["client_email"]
        2. jobs.db `clients` table join by client_name
        3. Placeholder address (used for name-only matching)
        """
        meta = job.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        email = meta.get("client_email", "")
        if email:
            return email

        # Try clients table
        try:
            conn = _get_conn(self._jobs_db)
            row = conn.execute(
                "SELECT email FROM clients WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (job.get("client_name", ""),),
            ).fetchone()
            conn.close()
            if row and row["email"]:
                return row["email"].strip()
        except Exception:
            pass  # clients table may not exist

        # Placeholder — name-based matching will be used in _get_days_since_last_client_email
        slug = (job.get("client_name") or "unknown").lower().replace(" ", "_").replace("'", "")
        return f"pending+{slug}@symphony.placeholder"

    def _already_sent(self, job_id: int, interval_days: int) -> bool:
        """Return True if this interval was already logged for the job."""
        try:
            conn = _get_conn(self._follow_ups_db)
            _ensure_follow_up_log(conn)
            row = conn.execute(
                "SELECT id FROM follow_up_log WHERE job_id = ? AND interval_days = ?",
                (job_id, interval_days),
            ).fetchone()
            conn.close()
            return row is not None
        except Exception as exc:
            logger.warning("_already_sent check error: %s", exc)
            return False

    def _record_sent(
        self, job_id: int, interval_days: int, email_id: str, template: str
    ) -> None:
        """Insert or replace a row in follow_up_log."""
        try:
            conn = _get_conn(self._follow_ups_db)
            _ensure_follow_up_log(conn)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO follow_up_log
                    (job_id, interval_days, sent_at, email_id, template)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, interval_days, now, email_id or "", template),
            )
            conn.commit()
            conn.close()
            logger.debug(
                "follow_up_logged job_id=%d interval=%d", job_id, interval_days
            )
        except Exception as exc:
            logger.warning("_record_sent error: %s", exc)

    @staticmethod
    def _build_subject(interval_days: int, project_name: str) -> str:
        """Build a concise email subject line for the follow-up."""
        labels = {3: "Checking in", 7: "Following up", 14: "Final follow-up"}
        label = labels.get(interval_days, "Follow-up")
        if project_name:
            return f"{label} — {project_name}"
        return label

    async def _create_linear_no_response_comment(
        self, job: dict, message_body: str
    ) -> None:
        """
        Create a Linear comment on the relevant project issue noting that
        the 14-day follow-up has fired with no client response.
        """
        if not self._linear:
            return

        job_id = job["job_id"]
        client_name = job.get("client_name", "")
        project_name = job.get("project_name", "")

        comment = (
            f"**No-response alert — 14-day follow-up sent**\n\n"
            f"Client **{client_name}** has not responded to the proposal for "
            f"**{project_name or 'this project'}** in 14+ days. "
            f"A final follow-up email has been dispatched.\n\n"
            f"> {message_body}\n\n"
            f"Consider calling the client directly or marking the opportunity inactive."
        )

        try:
            # Attempt to find the project in Linear and add a comment to the
            # most relevant open issue; fall back to creating a new issue.
            project_id = await self._linear.ensure_project(
                job_id, client_name, project_name
            )
            if project_id:
                # Find best open issue
                issue_id = await self._linear._find_best_issue(
                    project_id, "FOLLOW_UP_NEEDED", "no response proposal"
                )
                if issue_id:
                    await self._linear._add_comment(issue_id, comment)
                    logger.info(
                        "linear_no_response_comment job_id=%d issue=%s",
                        job_id,
                        issue_id,
                    )
                    return

            # Fallback: create a new issue
            await self._linear.create_doc_regeneration_issue(
                title=f"No response — {client_name} proposal (14 days)",
                description=comment,
                client_name=client_name,
            )
        except Exception as exc:
            logger.warning(
                "linear_no_response_comment failed job_id=%d: %s", job_id, exc
            )


# ── Utility ────────────────────────────────────────────────────────────────────

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string, returning a UTC-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None
