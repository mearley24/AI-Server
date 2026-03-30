"""
Job Lifecycle Manager — tracks every Symphony Smart Homes job from lead to warranty.

Stores jobs in SQLite (/data/jobs.db) with full event timeline.
Each phase defines what Bob should do automatically, what triggers the
next phase, and what notifications to send to the owner.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.job_lifecycle")

DEFAULT_DB_PATH = "/app/data/jobs.db"


class Phase(str, Enum):
    LEAD = "LEAD"
    CONSULTATION = "CONSULTATION"
    QUOTE = "QUOTE"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    PROCUREMENT = "PROCUREMENT"
    SCHEDULING = "SCHEDULING"
    INSTALLATION = "INSTALLATION"
    PROGRAMMING = "PROGRAMMING"
    COMMISSIONING = "COMMISSIONING"
    COMPLETED = "COMPLETED"
    WARRANTY = "WARRANTY"


# Ordered list for advancing through phases
PHASE_ORDER = list(Phase)


# ---- Phase definitions: tasks, notifications, triggers, templates ----

PHASE_DEFS = {
    Phase.LEAD: {
        "tasks": [
            "Auto-create job record from email inquiry",
            "Extract client name, contact info, project type from email",
            "Notify owner of new lead",
        ],
        "notifications": [
            "New lead: {client_name} — {summary}. Next: schedule consultation",
        ],
        "triggers": [
            "Owner confirms consultation scheduled",
            "Calendar event created with client name",
        ],
        "templates": {
            "owner_alert": "New lead from {client_name}: {summary}\nAction items: {action_items}",
        },
    },
    Phase.CONSULTATION: {
        "tasks": [
            "Check calendar for scheduled site visit",
            "Prepare client background from D-Tools/email history",
            "Send pre-visit reminder to owner",
        ],
        "notifications": [
            "Consultation with {client_name} — check calendar for date",
        ],
        "triggers": [
            "Site visit completed (calendar event passed)",
            "Owner manually advances phase",
        ],
        "templates": {
            "reminder": "Reminder: site visit with {client_name} coming up. Review their inquiry notes.",
        },
    },
    Phase.QUOTE: {
        "tasks": [
            "Pull D-Tools opportunity data if linked",
            "Create D-Tools opportunity if not exists",
            "Attach opportunity to job record",
        ],
        "notifications": [
            "Quote phase for {client_name} — D-Tools opportunity {d_tools_id}",
        ],
        "triggers": [
            "D-Tools opportunity status changes to 'Quoted'",
            "Owner manually advances",
        ],
        "templates": {},
    },
    Phase.PROPOSAL: {
        "tasks": [
            "Check if proposal email was sent",
            "Track follow-up timing",
            "Suggest 3-day follow-up if no response",
            "Suggest 7-day follow-up if still no response",
        ],
        "notifications": [
            "Proposal sent to {client_name} — tracking follow-up",
            "3-day follow-up due for {client_name}",
            "7-day follow-up due for {client_name} — no response yet",
        ],
        "triggers": [
            "Client responds to proposal email",
            "Owner manually advances",
        ],
        "templates": {
            "followup_3d": "Hi {client_name}, just checking in on the proposal we sent over. Happy to answer any questions.",
            "followup_7d": "Hi {client_name}, wanted to circle back on the proposal. Let me know if you'd like to discuss or adjust anything.",
        },
    },
    Phase.NEGOTIATION: {
        "tasks": [
            "Track client email responses about revisions",
            "Flag pricing discussions to owner",
            "Update D-Tools opportunity with revision notes",
        ],
        "notifications": [
            "{client_name} responded to proposal — review needed",
        ],
        "triggers": [
            "Client accepts proposal",
            "D-Tools opportunity status changes to 'Won'",
            "Owner manually advances",
        ],
        "templates": {},
    },
    Phase.WON: {
        "tasks": [
            "Send celebration notification",
            "Create D-Tools project if not exists",
            "Start procurement checklist",
            "Generate initial equipment list from proposal",
        ],
        "notifications": [
            "Job WON: {client_name} — {project_name}! Creating project and starting procurement.",
        ],
        "triggers": [
            "Equipment ordering begins",
            "Owner manually advances",
        ],
        "templates": {
            "celebration": "We won the {project_name} job with {client_name}! Time to order equipment and schedule the install.",
        },
    },
    Phase.PROCUREMENT: {
        "tasks": [
            "Track vendor emails (Snap One, etc.) for order confirmations",
            "Flag shipping notifications",
            "Monitor for backorder alerts",
            "Update job notes with shipment tracking",
        ],
        "notifications": [
            "Equipment shipped for {project_name}: {details}",
            "Backorder alert for {project_name}: {details}",
        ],
        "triggers": [
            "All equipment received",
            "Owner manually advances to scheduling",
        ],
        "templates": {},
    },
    Phase.SCHEDULING: {
        "tasks": [
            "Check calendar for install dates",
            "Confirm crew availability",
            "Send install date confirmation to client",
        ],
        "notifications": [
            "Install scheduled for {project_name}: {details}",
        ],
        "triggers": [
            "Install date arrives",
            "Owner manually advances",
        ],
        "templates": {
            "client_confirm": "Hi {client_name}, your installation is scheduled for {install_date}. Our team will arrive at {time}.",
        },
    },
    Phase.INSTALLATION: {
        "tasks": [
            "Track install progress",
            "Prompt owner for daily progress photos",
            "Flag any issues or delays",
        ],
        "notifications": [
            "Install day {day} for {project_name} — any updates?",
        ],
        "triggers": [
            "Physical install complete",
            "Owner manually advances to programming",
        ],
        "templates": {},
    },
    Phase.PROGRAMMING: {
        "tasks": [
            "Track programming tasks (Control4, Lutron, Crestron, Sonos)",
            "Note completed subsystems",
        ],
        "notifications": [
            "Programming in progress for {project_name}",
        ],
        "triggers": [
            "All systems programmed",
            "Owner manually advances",
        ],
        "templates": {},
    },
    Phase.COMMISSIONING: {
        "tasks": [
            "Schedule client walkthrough",
            "Generate punch list from notes",
            "Track punch list items to completion",
        ],
        "notifications": [
            "Commissioning: {project_name} walkthrough with {client_name}",
            "Punch list items remaining: {count}",
        ],
        "triggers": [
            "Client signs off",
            "All punch list items resolved",
            "Owner manually advances",
        ],
        "templates": {},
    },
    Phase.COMPLETED: {
        "tasks": [
            "Generate completion report",
            "Send final invoice",
            "Archive project documentation",
            "Request client review/testimonial",
        ],
        "notifications": [
            "Job COMPLETED: {project_name} for {client_name}. Final invoice sent.",
        ],
        "triggers": [
            "Warranty period begins (auto after 7 days)",
            "Owner manually advances",
        ],
        "templates": {
            "completion": "Hi {client_name}, the {project_name} project is complete! Here's your final invoice. We hope you love the new system.",
        },
    },
    Phase.WARRANTY: {
        "tasks": [
            "Monitor for client support emails",
            "Track warranty service requests",
            "Schedule follow-up check-in at 30, 60, 90 days",
        ],
        "notifications": [
            "Warranty support request from {client_name}: {details}",
            "{days}-day check-in due for {client_name}",
        ],
        "triggers": [
            "Warranty period expires (typically 1 year)",
        ],
        "templates": {
            "checkin": "Hi {client_name}, just checking in on your {project_name} system. Everything working well? Let us know if you need anything.",
        },
    },
}


class JobLifecycleManager:
    """Manages job records and phase transitions in SQLite."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("job_lifecycle_init db=%s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                project_name TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT 'LEAD',
                d_tools_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notes TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                phase_from TEXT DEFAULT '',
                phase_to TEXT DEFAULT '',
                details TEXT DEFAULT '',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_phase ON jobs(phase)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_client ON jobs(client_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON job_events(timestamp)")
        conn.commit()
        logger.info("job_db_ready")

    def create_job(
        self,
        client_name: str,
        project_name: str = "",
        phase: str = "LEAD",
        d_tools_id: str = "",
        notes: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Create a new job. Returns the job record."""
        now = datetime.utcnow().isoformat()
        meta_json = json.dumps(metadata or {})
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO jobs (client_name, project_name, phase, d_tools_id, created_at, updated_at, notes, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (client_name, project_name, phase, d_tools_id, now, now, notes, meta_json),
        )
        job_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO job_events (job_id, event_type, phase_from, phase_to, details, timestamp)
            VALUES (?, 'created', '', ?, ?, ?)
            """,
            (job_id, phase, f"Job created: {client_name} — {project_name}", now),
        )
        conn.commit()
        logger.info("job_created id=%d client=%s project=%s phase=%s", job_id, client_name, project_name, phase)
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> Optional[dict]:
        """Get a single job by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        try:
            job["metadata"] = json.loads(job.get("metadata", "{}"))
        except (json.JSONDecodeError, TypeError):
            job["metadata"] = {}
        return job

    def get_active_jobs(self) -> list[dict]:
        """Get all jobs not in COMPLETED or WARRANTY phase."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM jobs WHERE phase NOT IN ('COMPLETED', 'WARRANTY') ORDER BY updated_at DESC"
        ).fetchall()
        jobs = []
        for row in rows:
            job = dict(row)
            try:
                job["metadata"] = json.loads(job.get("metadata", "{}"))
            except (json.JSONDecodeError, TypeError):
                job["metadata"] = {}
            jobs.append(job)
        return jobs

    def get_all_jobs(self) -> list[dict]:
        """Get all jobs."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
        jobs = []
        for row in rows:
            job = dict(row)
            try:
                job["metadata"] = json.loads(job.get("metadata", "{}"))
            except (json.JSONDecodeError, TypeError):
                job["metadata"] = {}
            jobs.append(job)
        return jobs

    def search_jobs(self, query: str) -> list[dict]:
        """Search jobs by client name or project name."""
        conn = self._get_conn()
        pattern = f"%{query}%"
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE client_name LIKE ? OR project_name LIKE ? OR notes LIKE ?
            ORDER BY updated_at DESC
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        jobs = []
        for row in rows:
            job = dict(row)
            try:
                job["metadata"] = json.loads(job.get("metadata", "{}"))
            except (json.JSONDecodeError, TypeError):
                job["metadata"] = {}
            jobs.append(job)
        return jobs

    def advance_phase(self, job_id: int, details: str = "") -> Optional[dict]:
        """Advance a job to the next phase. Returns dict with job + tasks for new phase."""
        job = self.get_job(job_id)
        if not job:
            return None

        current = job["phase"]
        try:
            current_idx = PHASE_ORDER.index(Phase(current))
        except (ValueError, KeyError):
            logger.error("invalid_phase job_id=%d phase=%s", job_id, current)
            return None

        if current_idx >= len(PHASE_ORDER) - 1:
            logger.info("job_already_final job_id=%d phase=%s", job_id, current)
            return {"job": job, "tasks": [], "message": "Job is already in final phase"}

        new_phase = PHASE_ORDER[current_idx + 1]
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET phase = ?, updated_at = ? WHERE job_id = ?",
            (new_phase.value, now, job_id),
        )
        conn.execute(
            """
            INSERT INTO job_events (job_id, event_type, phase_from, phase_to, details, timestamp)
            VALUES (?, 'phase_change', ?, ?, ?, ?)
            """,
            (job_id, current, new_phase.value, details or f"Advanced from {current} to {new_phase.value}", now),
        )
        conn.commit()
        logger.info("job_advanced id=%d from=%s to=%s", job_id, current, new_phase.value)

        updated_job = self.get_job(job_id)
        phase_tasks = self.get_phase_tasks(new_phase.value)
        return {
            "job": updated_job,
            "tasks": phase_tasks.get("tasks", []),
            "notifications": phase_tasks.get("notifications", []),
            "phase_from": current,
            "phase_to": new_phase.value,
        }

    def rename_job(self, job_id: int, client_name: str = None, project_name: str = None) -> Optional[dict]:
        """Rename a job's client or project name."""
        job = self.get_job(job_id)
        if not job:
            return None

        now = datetime.utcnow().isoformat()
        updates = []
        params = []
        details_parts = []

        if client_name:
            updates.append("client_name = ?")
            params.append(client_name)
            details_parts.append(f"client: {job['client_name']} -> {client_name}")
        if project_name:
            updates.append("project_name = ?")
            params.append(project_name)
            details_parts.append(f"project: {job['project_name']} -> {project_name}")

        if not updates:
            return job

        updates.append("updated_at = ?")
        params.append(now)
        params.append(job_id)

        conn = self._get_conn()
        conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?",
            params,
        )
        conn.execute(
            """INSERT INTO job_events (job_id, event_type, phase_from, phase_to, details, timestamp)
               VALUES (?, 'rename', ?, ?, ?, ?)""",
            (job_id, job["phase"], job["phase"], "Renamed: " + ", ".join(details_parts), now),
        )
        conn.commit()
        logger.info("job_renamed id=%d %s", job_id, ", ".join(details_parts))
        return self.get_job(job_id)

    def add_note(self, job_id: int, note: str) -> Optional[dict]:
        """Add a note to a job. Appends to existing notes and logs event."""
        job = self.get_job(job_id)
        if not job:
            return None

        now = datetime.utcnow().isoformat()
        existing = job.get("notes", "")
        timestamp_note = f"[{now}] {note}"
        updated_notes = f"{existing}\n{timestamp_note}" if existing else timestamp_note

        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET notes = ?, updated_at = ? WHERE job_id = ?",
            (updated_notes, now, job_id),
        )
        conn.execute(
            """
            INSERT INTO job_events (job_id, event_type, phase_from, phase_to, details, timestamp)
            VALUES (?, 'note', ?, ?, ?, ?)
            """,
            (job_id, job["phase"], job["phase"], note, now),
        )
        conn.commit()
        logger.info("job_note_added id=%d", job_id)
        return self.get_job(job_id)

    def update_metadata(self, job_id: int, updates: dict) -> Optional[dict]:
        """Merge updates into job metadata."""
        job = self.get_job(job_id)
        if not job:
            return None

        meta = job.get("metadata", {})
        meta.update(updates)
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET metadata = ?, updated_at = ? WHERE job_id = ?",
            (json.dumps(meta), now, job_id),
        )
        conn.commit()
        return self.get_job(job_id)

    def link_dtools(self, job_id: int, d_tools_id: str) -> Optional[dict]:
        """Link a D-Tools opportunity/project ID to a job."""
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET d_tools_id = ?, updated_at = ? WHERE job_id = ?",
            (d_tools_id, now, job_id),
        )
        conn.execute(
            """
            INSERT INTO job_events (job_id, event_type, phase_from, phase_to, details, timestamp)
            VALUES (?, 'linked_dtools', '', '', ?, ?)
            """,
            (job_id, f"Linked D-Tools ID: {d_tools_id}", now),
        )
        conn.commit()
        logger.info("job_linked_dtools id=%d dtools=%s", job_id, d_tools_id)
        return self.get_job(job_id)

    def get_job_timeline(self, job_id: int) -> list[dict]:
        """Get the full event timeline for a job."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY timestamp ASC",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_phase_tasks(phase: str) -> dict:
        """Get the task/notification/trigger definitions for a phase."""
        try:
            phase_enum = Phase(phase)
        except ValueError:
            return {"tasks": [], "notifications": [], "triggers": [], "templates": {}}
        defn = PHASE_DEFS.get(phase_enum, {})
        return {
            "tasks": defn.get("tasks", []),
            "notifications": defn.get("notifications", []),
            "triggers": defn.get("triggers", []),
            "templates": defn.get("templates", {}),
        }

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
