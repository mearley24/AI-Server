"""
D-Tools Auto-Sync — pulls data from D-Tools Cloud API and syncs into the job lifecycle.

On each orchestrator tick (or on demand), pulls opportunities and projects from D-Tools,
matches them to existing jobs by client name, and creates new jobs for unmatched entries.
Stores D-Tools snapshots in memory for quick recall.

Requires DTOOLS_API_KEY from env. Gracefully skips if not set.
"""

import logging
import os
import sys
from typing import Optional

import httpx

from job_lifecycle import JobLifecycleManager

logger = logging.getLogger("openclaw.dtools_sync")

# D-Tools client is at /app/integrations/dtools/ in Docker
DTOOLS_CLIENT_PATH = "/app/integrations/dtools"
if DTOOLS_CLIENT_PATH not in sys.path:
    sys.path.insert(0, DTOOLS_CLIENT_PATH)


# Client name aliases — maps job names to D-Tools names when they differ
CLIENT_ALIASES = {
    "topletz": ["toplets", "topletz", "stopletz", "stopletz1", "steve toplets", "steve topletz"],
}


def _names_match(job_name: str, dtools_name: str) -> bool:
    """Fuzzy client name matching with alias support."""
    j = job_name.lower().strip()
    d = dtools_name.lower().strip()

    # Direct match
    if j in d or d in j:
        return True

    # Alias match
    for alias_key, aliases in CLIENT_ALIASES.items():
        if any(a in j for a in aliases) or alias_key in j:
            if any(a in d for a in aliases) or alias_key in d:
                return True

    return False


class DToolsSync:
    """Syncs D-Tools opportunities/projects into the job lifecycle system."""

    def __init__(self, job_mgr: JobLifecycleManager, memory=None):
        self._jobs = job_mgr
        self._memory = memory
        self._client = None
        self._available = False
        self._init_client()

    def _init_client(self):
        """Initialize D-Tools client if API key is available."""
        api_key = os.getenv("DTOOLS_API_KEY", "")
        if not api_key:
            logger.warning("DTOOLS_API_KEY not set — D-Tools sync disabled")
            return

        try:
            from dtools_client import DToolsCloudClient
            self._client = DToolsCloudClient(api_key=api_key)
            self._available = True
            logger.info("D-Tools sync initialized")
        except Exception as e:
            logger.warning("D-Tools client init failed: %s — sync disabled", e)

    async def sync(self) -> dict:
        """Pull D-Tools data and sync into job lifecycle. Returns sync stats."""
        if not self._available or not self._client:
            return {"status": "skipped", "reason": "dtools_not_configured"}

        stats = {"opportunities_checked": 0, "projects_checked": 0, "jobs_created": 0, "jobs_linked": 0}

        try:
            # Fetch both open AND won opportunities, plus all projects
            pipeline = {
                "timestamp": "",
                "open_opportunities": self._client.get_opportunities(status="Open"),
                "won_opportunities": self._client.get_opportunities(status="Won"),
                "active_projects": self._client.get_projects(status="Active"),
                "all_projects": self._client.get_projects(),
            }
        except Exception as e:
            logger.warning("D-Tools pipeline fetch failed: %s", e)
            return {"status": "error", "error": str(e)}

        # Store snapshot in memory
        if self._memory:
            try:
                opps = pipeline.get("open_opportunities", {})
                projs = pipeline.get("active_projects", {})
                opp_list = opps.get("Data", opps.get("opportunities", [])) if isinstance(opps, dict) else []
                proj_list = projs.get("Data", projs.get("projects", [])) if isinstance(projs, dict) else []
                opp_count = len(opp_list)
                proj_count = len(proj_list)
                self._memory.remember(
                    "dtools_pipeline_snapshot",
                    f"opportunities={opp_count}, projects={proj_count}, synced={pipeline.get('timestamp', '')}",
                    category="project_context",
                    source_agent="dtools_sync",
                )
            except Exception:
                pass

        # Sync opportunities (open + won)
        try:
            opps = []
            for key in ("open_opportunities", "won_opportunities"):
                opps_data = pipeline.get(key, {})
                # Handle both {"Data": [...]} and {"opportunities": [...]} formats
                if isinstance(opps_data, dict):
                    opps.extend(opps_data.get("Data", opps_data.get("opportunities", [])))
            existing_jobs = self._jobs.get_all_jobs()

            for opp in opps:
                stats["opportunities_checked"] += 1
                client_name = opp.get("clientName", opp.get("ClientName", opp.get("client_name", ""))).strip()
                opp_name = opp.get("name", opp.get("Name", "")).strip()
                opp_id = str(opp.get("id", opp.get("Id", "")))

                if not client_name:
                    continue

                # Check for existing job match using alias-aware matching
                matched_job = None
                for job in existing_jobs:
                    if _names_match(job["client_name"], client_name):
                        matched_job = job
                        break

                if matched_job:
                    # Link D-Tools ID if not already linked
                    if not matched_job.get("d_tools_id") and opp_id:
                        self._jobs.link_dtools(matched_job["job_id"], opp_id)
                        stats["jobs_linked"] += 1
                        logger.info("Linked D-Tools opp %s to job #%d (%s)", opp_id, matched_job["job_id"], client_name)
                # No existing job match — log for pipeline visibility
                # Full jobs are created manually. D-Tools entries go to Linear
                # backlog as pipeline opportunities for the owner to review.
                opp_status = opp.get("systemState", opp.get("status", ""))
                opp_price = opp.get("price", 0)
                logger.info(
                    "D-Tools pipeline: %s — %s (%s, $%.0f) — no active job",
                    client_name, opp_name, opp_status, opp_price or 0,
                )
                stats["pipeline_logged"] = stats.get("pipeline_logged", 0) + 1
        except Exception as e:
            logger.warning("D-Tools opportunity sync failed: %s", e)

        # Sync projects (active + all)
        try:
            projs = []
            for key in ("active_projects", "all_projects"):
                projs_data = pipeline.get(key, {})
                if isinstance(projs_data, dict):
                    projs.extend(projs_data.get("Data", projs_data.get("projects", [])))
            # Deduplicate by ID
            seen_ids = set()
            unique_projs = []
            for p in projs:
                pid = str(p.get("Id", p.get("id", "")))
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    unique_projs.append(p)
            projs = unique_projs
            # Refresh after possible job creation
            existing_jobs = self._jobs.get_all_jobs()

            for proj in projs:
                stats["projects_checked"] += 1
                client_name = proj.get("clientName", proj.get("ClientName", proj.get("client_name", ""))).strip()
                proj_name = proj.get("name", proj.get("Name", "")).strip()

                if not client_name:
                    continue

                matched_job = None
                for job in existing_jobs:
                    if _names_match(job["client_name"], client_name):
                        matched_job = job
                        break

                if matched_job and not matched_job.get("d_tools_id"):
                    proj_id = str(proj.get("Id", proj.get("id", "")))
                    if proj_id:
                        self._jobs.link_dtools(matched_job["job_id"], proj_id)
                        stats["jobs_linked"] += 1
        except Exception as e:
            logger.warning("D-Tools project sync failed: %s", e)

        # Specifically look for Topletz
        await self._search_topletz()

        logger.info("D-Tools sync complete: %s", stats)
        return {"status": "ok", **stats}

    async def _search_topletz(self):
        """Search D-Tools for any Topletz-related data and link to job."""
        if not self._available or not self._client:
            return

        try:
            # Search all spelling variations
            results = None
            for search_term in ["Steve Toplets", "Toplets", "Topletz", "Steve Topletz"]:
                r = self._client.find_client_projects(search_term)
                if r.get("matches"):
                    results = r
                    break
            if not results:
                results = r  # keep last result even if empty
            if results and self._memory:
                self._memory.remember(
                    "dtools_topletz",
                    f"D-Tools Topletz data: {str(results)[:500]}",
                    category="project_context",
                    source_agent="dtools_sync",
                )

            # Link any found projects/opportunities
            existing_jobs = self._jobs.get_all_jobs()
            topletz_jobs = [j for j in existing_jobs if "topletz" in j["client_name"].lower()]
            if topletz_jobs and results:
                job = topletz_jobs[0]
                projects = results.get("projects", [])
                if projects and not job.get("d_tools_id"):
                    proj_id = str(projects[0].get("Id", projects[0].get("id", "")))
                    if proj_id:
                        self._jobs.link_dtools(job["job_id"], proj_id)
                        logger.info("Linked Topletz job #%d to D-Tools project %s", job["job_id"], proj_id)
        except Exception as e:
            logger.debug("Topletz D-Tools search: %s", e)
