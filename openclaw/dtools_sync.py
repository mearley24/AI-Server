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
                opp_count = len(opps.get("Data", [])) if isinstance(opps, dict) else 0
                proj_count = len(projs.get("Data", [])) if isinstance(projs, dict) else 0
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
                opps.extend(opps_data.get("Data", []) if isinstance(opps_data, dict) else [])
            existing_jobs = self._jobs.get_all_jobs()
            existing_clients = {j["client_name"].lower(): j for j in existing_jobs}

            for opp in opps:
                stats["opportunities_checked"] += 1
                client_name = opp.get("ClientName", opp.get("client_name", "")).strip()
                opp_name = opp.get("Name", opp.get("name", "")).strip()
                opp_id = str(opp.get("Id", opp.get("id", "")))

                if not client_name:
                    continue

                # Check for existing job match
                matched_job = existing_clients.get(client_name.lower())
                if not matched_job:
                    # Try fuzzy match on opportunity name
                    for job_client, job in existing_clients.items():
                        if job_client in client_name.lower() or client_name.lower() in job_client:
                            matched_job = job
                            break

                if matched_job:
                    # Link D-Tools ID if not already linked
                    if not matched_job.get("d_tools_id") and opp_id:
                        self._jobs.link_dtools(matched_job["job_id"], opp_id)
                        stats["jobs_linked"] += 1
                        logger.info("Linked D-Tools opp %s to job #%d (%s)", opp_id, matched_job["job_id"], client_name)
                else:
                    # Create new job from D-Tools opportunity
                    status = opp.get("Status", opp.get("status", ""))
                    job = self._jobs.create_job(
                        client_name=client_name,
                        project_name=opp_name,
                        phase="LEAD",
                        d_tools_id=opp_id,
                        notes=f"Source: D-Tools opportunity\nStatus: {status}",
                        metadata={"source": "dtools", "dtools_status": status},
                    )
                    stats["jobs_created"] += 1
                    logger.info("Created job #%d from D-Tools: %s — %s", job["job_id"], client_name, opp_name)
        except Exception as e:
            logger.warning("D-Tools opportunity sync failed: %s", e)

        # Sync projects (active + all)
        try:
            projs = []
            for key in ("active_projects", "all_projects"):
                projs_data = pipeline.get(key, {})
                projs.extend(projs_data.get("Data", []) if isinstance(projs_data, dict) else [])
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
            existing_clients = {j["client_name"].lower(): j for j in existing_jobs}

            for proj in projs:
                stats["projects_checked"] += 1
                client_name = proj.get("ClientName", proj.get("client_name", "")).strip()
                proj_name = proj.get("Name", proj.get("name", "")).strip()

                if not client_name:
                    continue

                matched_job = existing_clients.get(client_name.lower())
                if not matched_job:
                    for job_client, job in existing_clients.items():
                        if job_client in client_name.lower() or client_name.lower() in job_client:
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
            results = self._client.find_client_projects("Topletz")
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
