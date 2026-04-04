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
