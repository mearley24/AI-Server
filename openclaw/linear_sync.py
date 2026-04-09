"""
Linear Integration — syncs job lifecycle phases to Linear projects and issues.

Creates a Linear project for each active job, creates issues for phase tasks,
and updates issue status as tasks complete. Uses the Linear GraphQL API via httpx.

Requires LINEAR_API_KEY from env. Gracefully skips if not set.
"""

import logging
import os
from typing import Optional

import httpx

from job_lifecycle import JobLifecycleManager, Phase, PHASE_DEFS

logger = logging.getLogger("openclaw.linear_sync")

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TEAM_ID = "b1ba685a-0eff-43fe-bec9-023e3c455672"
LINEAR_TEAM_KEY = "SYM"

# Linear workflow state IDs (from team config)
LINEAR_STATES = {
    "Backlog": "f2a1d2c1-1234-0000-0000-000000000001",
    "Todo": "f2a1d2c1-1234-0000-0000-000000000002",
    "In Progress": "f2a1d2c1-1234-0000-0000-000000000003",
    "In Review": "f2a1d2c1-1234-0000-0000-000000000004",
    "Done": "f2a1d2c1-1234-0000-0000-000000000005",
    "Canceled": "f2a1d2c1-1234-0000-0000-000000000006",
}

# Map job phases to Linear project states
PHASE_TO_LINEAR_STATE = {
    Phase.LEAD.value: "Backlog",
    Phase.CONSULTATION.value: "Todo",
    Phase.QUOTE.value: "In Progress",
    Phase.PROPOSAL.value: "In Progress",
    Phase.NEGOTIATION.value: "In Progress",
    Phase.WON.value: "In Progress",
    Phase.PROCUREMENT.value: "In Progress",
    Phase.SCHEDULING.value: "In Progress",
    Phase.INSTALLATION.value: "In Progress",
    Phase.PROGRAMMING.value: "In Progress",
    Phase.COMMISSIONING.value: "In Review",
    Phase.COMPLETED.value: "Done",
    Phase.WARRANTY.value: "Done",
}


class LinearSync:
    """Syncs job lifecycle to Linear projects and issues."""

    def __init__(self, job_mgr: JobLifecycleManager):
        self._jobs = job_mgr
        self._api_key = os.getenv("LINEAR_API_KEY", "")
        self._available = bool(self._api_key)
        self._http = httpx.AsyncClient(timeout=30.0)
        # Cache: job_id -> linear_project_id
        self._project_cache: dict[int, str] = {}
        # Cache: (job_id, task_title) -> linear_issue_id
        self._issue_cache: dict[tuple[int, str], str] = {}

        if not self._available:
            logger.warning("LINEAR_API_KEY not set — Linear sync disabled")
        else:
            logger.info("Linear sync initialized (team: %s)", LINEAR_TEAM_KEY)

    async def _graphql(self, query: str, variables: dict = None) -> dict:
        """Execute a Linear GraphQL query/mutation."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        resp = await self._http.post(
            LINEAR_API_URL,
            headers={
                "Authorization": self._api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if resp.status_code != 200:
            logger.warning("Linear API error %d: %s", resp.status_code, resp.text[:300])
            return {}

        data = resp.json()
        if "errors" in data:
            logger.warning("Linear GraphQL errors: %s", data["errors"])
        return data.get("data", {})

    async def _fetch_workflow_states(self):
        """Fetch actual workflow state IDs from Linear (run once on first use)."""
        global LINEAR_STATES
        data = await self._graphql("""
            query {
                workflowStates(filter: { team: { id: { eq: "%s" } } }) {
                    nodes { id name }
                }
            }
        """ % LINEAR_TEAM_ID)

        nodes = data.get("workflowStates", {}).get("nodes", [])
        if nodes:
            LINEAR_STATES.update({n["name"]: n["id"] for n in nodes})
            logger.info("Fetched %d Linear workflow states", len(nodes))

    async def ensure_project(self, job_id: int, client_name: str, project_name: str) -> Optional[str]:
        """Create a Linear project for a job if not already created. Returns project ID."""
        if not self._available:
            return None

        if job_id in self._project_cache:
            return self._project_cache[job_id]

        # Fetch workflow states on first use
        if all(v.startswith("f2a1d2c1") for v in LINEAR_STATES.values()):
            await self._fetch_workflow_states()

        # Search for existing project
        title = f"{client_name} — {project_name or 'Job'}"
        data = await self._graphql("""
            query($filter: ProjectFilter) {
                projects(filter: $filter) {
                    nodes { id name }
                }
            }
        """, {"filter": {"name": {"containsIgnoreCase": client_name}}})

        nodes = data.get("projects", {}).get("nodes", [])
        if nodes:
            project_id = nodes[0]["id"]
            self._project_cache[job_id] = project_id
            logger.info("Found existing Linear project for job #%d: %s", job_id, project_id)
            return project_id

        # Create new project
        data = await self._graphql("""
            mutation($input: ProjectCreateInput!) {
                projectCreate(input: $input) {
                    success
                    project { id name }
                }
            }
        """, {"input": {
            "name": title,
            "teamIds": [LINEAR_TEAM_ID],
        }})

        result = data.get("projectCreate", {})
        if result.get("success"):
            project_id = result["project"]["id"]
            self._project_cache[job_id] = project_id
            logger.info("Created Linear project for job #%d: %s (%s)", job_id, title, project_id)
            return project_id

        logger.warning("Failed to create Linear project for job #%d", job_id)
        return None

    async def create_phase_issues(self, job_id: int, phase: str, client_name: str, project_name: str):
        """Create Linear issues for the tasks defined in a job phase."""
        if not self._available:
            return

        project_id = await self.ensure_project(job_id, client_name, project_name)
        phase_def = PHASE_DEFS.get(Phase(phase), {})
        tasks = phase_def.get("tasks", [])

        if not tasks:
            return

        state_name = PHASE_TO_LINEAR_STATE.get(phase, "Todo")
        state_id = LINEAR_STATES.get(state_name, LINEAR_STATES.get("Todo", ""))

        for task in tasks:
            cache_key = (job_id, task)
            if cache_key in self._issue_cache:
                continue

            title = f"[{LINEAR_TEAM_KEY}-{job_id}] {task}"
            input_data = {
                "title": title,
                "teamId": LINEAR_TEAM_ID,
                "stateId": state_id,
            }
            if project_id:
                input_data["projectId"] = project_id

            data = await self._graphql("""
                mutation($input: IssueCreateInput!) {
                    issueCreate(input: $input) {
                        success
                        issue { id identifier title }
                    }
                }
            """, {"input": input_data})

            result = data.get("issueCreate", {})
            if result.get("success"):
                issue_id = result["issue"]["id"]
                self._issue_cache[cache_key] = issue_id
                logger.info("Created Linear issue: %s — %s", result["issue"].get("identifier", ""), task[:60])

    async def update_phase_status(self, job_id: int, old_phase: str, new_phase: str):
        """Mark old phase issues as Done and create new phase issues."""
        if not self._available:
            return

        done_state_id = LINEAR_STATES.get("Done", "")

        # Mark old phase issues as Done
        if done_state_id:
            old_phase_def = PHASE_DEFS.get(Phase(old_phase), {})
            for task in old_phase_def.get("tasks", []):
                cache_key = (job_id, task)
                issue_id = self._issue_cache.get(cache_key)
                if issue_id:
                    await self._graphql("""
                        mutation($input: IssueUpdateInput!, $id: String!) {
                            issueUpdate(id: $id, input: $input) {
                                success
                            }
                        }
                    """, {"id": issue_id, "input": {"stateId": done_state_id}})

    async def on_phase_advance(self, job_id: int, old_phase: str, new_phase: str,
                                client_name: str, project_name: str):
        """Called when a job advances phase. Updates Linear accordingly."""
        if not self._available:
            return

        try:
            await self.update_phase_status(job_id, old_phase, new_phase)
            await self.create_phase_issues(job_id, new_phase, client_name, project_name)
        except Exception as e:
            logger.warning("Linear phase advance failed for job #%d: %s", job_id, e)


    async def create_doc_regeneration_issue(
        self,
        *,
        title: str,
        description: str,
        client_name: str = "",
    ) -> Optional[str]:
        """Create a one-off Linear issue when client docs need regeneration (pricing/scope)."""
        if not self._available:
            return None
        if all(v.startswith("f2a1d2c1") for v in LINEAR_STATES.values()):
            await self._fetch_workflow_states()
        state_id = LINEAR_STATES.get("Todo", LINEAR_STATES.get("Backlog", ""))
        full_title = f"[Docs] {title}"
        if client_name:
            full_title = f"{client_name}: {full_title}"[:255]
        desc = description
        if client_name:
            desc = f"Client: {client_name}\n\n{desc}"
        data = await self._graphql("""
            mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) {
                    success
                    issue { id identifier title }
                }
            }
        """, {"input": {
            "title": full_title[:255],
            "description": desc[:4000],
            "teamId": LINEAR_TEAM_ID,
            "stateId": state_id,
        }})
        result = data.get("issueCreate", {})
        if result.get("success"):
            ident = result.get("issue", {}).get("identifier", "")
            logger.info("Linear doc issue created: %s", ident)
            return result.get("issue", {}).get("id")
        logger.warning("Linear doc issue create failed")
        return None

    async def close(self):
        await self._http.aclose()


# ── Autonomous Email → Linear Pipeline ───────────────────────────────────────

import json
import re
import sqlite3
from datetime import datetime, timezone


# Signal patterns → Linear action
_SIGNAL_PATTERNS = {
    "signed":       ["signed", "signature", "sign the", "agreed", "agreement signed"],
    "deposit":      ["deposit", "payment sent", "paid", "wire sent", "check in the mail"],
    "approved":     ["approved", "looks good", "approve", "go ahead", "green light", "let's do it"],
    "scheduling":   ["schedule", "when can", "availability", "install date", "timeline"],
    "scope_change": ["can we add", "what about adding", "change order", "scope change",
                     "also want", "add to the", "remove the", "swap the"],
    "rejection":    ["not moving forward", "going another direction", "cancel", "hold off",
                     "not interested", "pass on this"],
}

# Email category → relevant Linear issue title keywords
_CATEGORY_ISSUE_KEYWORDS = {
    "CLIENT_INQUIRY":   ["client review", "proposal", "deliverables", "scope"],
    "FOLLOW_UP_NEEDED": ["follow-up", "finalize", "pending", "waiting"],
    "SCHEDULING":       ["schedule", "install", "walk", "site visit"],
    "INVOICE":          ["invoice", "payment", "deposit", "billing"],
    "BID_INVITE":       ["lead", "consultation", "inquiry"],
    "ACTIVE_CLIENT":    ["finalize", "agreement", "contract", "install"],
}


def _detect_signals(subject: str, body_snippet: str) -> list[str]:
    """Return list of detected signal types from email subject + snippet."""
    combined = (subject + " " + body_snippet).lower()
    found = []
    for signal, patterns in _SIGNAL_PATTERNS.items():
        if any(p in combined for p in patterns):
            found.append(signal)
    return found


def _match_job_to_sender(
    sender_name: str,
    sender_addr: str,
    jobs_db_path: str,
) -> Optional[dict]:
    """Find the best matching job for a sender. Returns job dict or None."""
    try:
        conn = sqlite3.connect(jobs_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs WHERE phase NOT IN ('COMPLETED', 'CANCELLED') ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    name_lower = (sender_name or "").lower()
    addr_lower = (sender_addr or "").lower()
    addr_domain = addr_lower.split("@")[-1] if "@" in addr_lower else ""

    best = None
    best_score = 0

    for row in rows:
        client_lower = row["client_name"].lower()
        score = 0

        # Exact name match
        if client_lower and client_lower in name_lower:
            score += 10
        elif name_lower and name_lower in client_lower:
            score += 8
        # Domain match (e.g., "topletz.com")
        if addr_domain and addr_domain in client_lower.replace(" ", ""):
            score += 6
        # Token match — any word from client name in sender name
        tokens = [t for t in re.split(r"\W+", client_lower) if len(t) >= 4]
        matches = sum(1 for t in tokens if t in name_lower or t in addr_lower)
        score += matches * 3

        if score > best_score:
            best_score = score
            best = dict(row)

    return best if best_score >= 3 else None


class LinearEmailSync:
    """
    Autonomous email → Linear pipeline.

    For every important email from an active client:
    1. Match sender → job → Linear project
    2. Find the most relevant open issue
    3. Add a comment: summary + action items + signals detected
    4. On strong signals → advance or create issues
    5. New leads → create lead ticket in Linear
    """

    def __init__(self, linear_sync: "LinearSync", jobs_db_path: str):
        self._ls = linear_sync
        self._jobs_db = jobs_db_path
        # Track which emails we've already synced (message_id → issue_id)
        self._synced: dict[str, str] = {}

    async def sync_email(self, email: dict) -> None:
        """
        Main entry point. Called for each important email from the orchestrator.
        email dict keys: message_id, sender, sender_name, subject, category,
                         summary, action_items, snippet, priority
        """
        if not self._ls._available:
            return

        msg_id  = email.get("message_id", "")
        subject = email.get("subject", "")
        sender  = email.get("sender", "")
        sname   = email.get("sender_name", "")
        cat     = email.get("category", "GENERAL")
        summary = email.get("summary", "")
        actions = email.get("action_items", "")
        snippet = email.get("snippet", "")

        if msg_id and msg_id in self._synced:
            return  # already processed this session

        signals = _detect_signals(subject, snippet)

        # ── 1. New lead → create lead ticket ─────────────────────────────────
        if cat == "BID_INVITE" and "rejection" not in signals:
            await self._handle_lead(sname or sender, subject, summary)
            if msg_id:
                self._synced[msg_id] = "lead"
            return

        # ── 2. Match sender to active job ─────────────────────────────────────
        job = _match_job_to_sender(sname, sender, self._jobs_db)
        if not job:
            logger.debug("linear_email_sync: no job match for %s <%s>", sname, sender)
            return

        job_id      = job["job_id"]
        client_name = job["client_name"]
        proj_name   = job["project_name"]

        # ── 3. Get or create Linear project ──────────────────────────────────
        project_id = await self._ls.ensure_project(job_id, client_name, proj_name)
        if not project_id:
            return

        # ── 4. Find the best open issue to comment on ─────────────────────────
        issue_id = await self._find_best_issue(project_id, cat, subject)

        # ── 5. Build comment body ─────────────────────────────────────────────
        ts    = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
        lines = [f"**Email received** — {ts}"]
        lines.append(f"**From:** {sname or sender}")
        lines.append(f"**Subject:** {subject}")
        if summary:
            lines.append(f"\n**Summary:** {summary}")
        if actions:
            lines.append(f"**Action items:** {actions}")
        if signals:
            lines.append(f"\n🔔 **Signals detected:** {', '.join(signals)}")
        comment_body = "\n".join(lines)

        # ── 6. Comment on the issue ───────────────────────────────────────────
        if issue_id:
            await self._add_comment(issue_id, comment_body)
        else:
            # No existing issue — create a new one for this email
            issue_id = await self._create_email_issue(
                project_id, client_name, cat, subject, comment_body
            )

        # ── 7. Act on signals ─────────────────────────────────────────────────
        if signals and issue_id:
            await self._act_on_signals(signals, project_id, issue_id, job_id,
                                        client_name, proj_name, comment_body)

        if msg_id:
            self._synced[msg_id] = issue_id or "processed"

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _handle_lead(self, client_name: str, subject: str, summary: str) -> None:
        """Create a Linear lead issue for a new potential client."""
        title = f"Lead: {client_name}"
        desc  = f"**Source:** Email — {subject}\n\n{summary}"
        await self._ls.create_doc_regeneration_issue(
            title=title, description=desc, client_name=client_name
        )
        logger.info("linear_email_sync: created lead issue for %s", client_name)

    async def _find_best_issue(
        self, project_id: str, category: str, subject: str
    ) -> Optional[str]:
        """Find the most relevant In Progress issue in the project."""
        data = await self._ls._graphql("""
            query($projectId: String!) {
                issues(filter: {
                    project: { id: { eq: $projectId } }
                    state: { type: { in: ["started", "unstarted"] } }
                }) {
                    nodes { id identifier title state { name type } }
                }
            }
        """, {"projectId": project_id})

        issues = data.get("issues", {}).get("nodes", [])
        if not issues:
            return None

        keywords = _CATEGORY_ISSUE_KEYWORDS.get(category, [])
        subj_lower = subject.lower()

        # Score each issue by keyword match
        best_id    = None
        best_score = 0

        for iss in issues:
            title_lower = iss["title"].lower()
            score = 0
            # Subject match
            for word in re.split(r"\W+", subj_lower):
                if len(word) >= 4 and word in title_lower:
                    score += 3
            # Category keyword match
            for kw in keywords:
                if kw in title_lower:
                    score += 2
            # Prefer In Progress over Todo
            if iss.get("state", {}).get("type") == "started":
                score += 1
            if score > best_score:
                best_score = score
                best_id = iss["id"]

        # Fall back to most recent In Progress issue
        if not best_id and issues:
            started = [i for i in issues if i.get("state", {}).get("type") == "started"]
            best_id = started[0]["id"] if started else issues[0]["id"]

        return best_id

    async def _add_comment(self, issue_id: str, body: str) -> None:
        """Add a comment to a Linear issue."""
        data = await self._ls._graphql("""
            mutation($input: CommentCreateInput!) {
                commentCreate(input: $input) { success comment { id } }
            }
        """, {"input": {"issueId": issue_id, "body": body}})
        if data.get("commentCreate", {}).get("success"):
            logger.info("linear_email_sync: comment added to issue %s", issue_id)
        else:
            logger.warning("linear_email_sync: comment failed for issue %s", issue_id)

    async def _create_email_issue(
        self, project_id: str, client_name: str, category: str,
        subject: str, body: str
    ) -> Optional[str]:
        """Create a new Linear issue for an email that doesn't match an existing one."""
        state_id = LINEAR_STATES.get("In Progress",
                   LINEAR_STATES.get("Todo", ""))
        title = f"{client_name}: {subject}"[:255]
        data = await self._ls._graphql("""
            mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) { success issue { id identifier } }
            }
        """, {"input": {
            "title": title,
            "description": body,
            "teamId": LINEAR_TEAM_ID,
            "projectId": project_id,
            "stateId": state_id,
        }})
        result = data.get("issueCreate", {})
        if result.get("success"):
            ident = result.get("issue", {}).get("identifier", "")
            logger.info("linear_email_sync: created issue %s for email", ident)
            return result["issue"]["id"]
        return None

    async def _act_on_signals(
        self, signals: list[str], project_id: str, issue_id: str,
        job_id: int, client_name: str, proj_name: str, context: str
    ) -> None:
        """Advance or create issues based on detected signals."""
        done_id = LINEAR_STATES.get("Done", "")
        inprog_id = LINEAR_STATES.get("In Progress", "")

        if "signed" in signals or "approved" in signals:
            # Advance the current issue to Done
            if done_id:
                await self._ls._graphql("""
                    mutation($id: String!, $input: IssueUpdateInput!) {
                        issueUpdate(id: $id, input: $input) { success }
                    }
                """, {"id": issue_id, "input": {"stateId": done_id}})
                logger.info("linear_email_sync: advanced issue %s to Done (signal: %s)",
                            issue_id, signals)

        if "deposit" in signals:
            # Create a procurement issue
            await self._ls.create_phase_issues(job_id, "WON", client_name, proj_name)

        if "scope_change" in signals:
            # Create a dedicated scope change issue
            await self._create_email_issue(
                project_id, client_name, "SCOPE_CHANGE",
                f"[Scope Change] {client_name}",
                f"**Scope change detected from email.**\n\n{context}\n\n"
                f"Review and create a formal change order."
            )

        if "rejection" in signals:
            cancelled_id = LINEAR_STATES.get("Canceled", "")
            if cancelled_id:
                await self._ls._graphql("""
                    mutation($id: String!, $input: IssueUpdateInput!) {
                        issueUpdate(id: $id, input: $input) { success }
                    }
                """, {"id": issue_id, "input": {"stateId": cancelled_id}})
                logger.info("linear_email_sync: issue %s cancelled (rejection signal)", issue_id)
