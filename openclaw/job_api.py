"""
Job API — FastAPI routes for job lifecycle management.

Included as a router in the OpenClaw main app.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from job_lifecycle import JobLifecycleManager, PHASE_ORDER

logger = logging.getLogger("openclaw.job_api")

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Module-level reference — set by main.py on startup
_job_mgr: Optional[JobLifecycleManager] = None


def init(job_mgr: JobLifecycleManager):
    """Called by main.py to inject the JobLifecycleManager instance."""
    global _job_mgr
    _job_mgr = job_mgr


def _mgr() -> JobLifecycleManager:
    if not _job_mgr:
        raise HTTPException(status_code=503, detail="Job lifecycle manager not initialized")
    return _job_mgr


# ---- Request models ----

class CreateJobRequest(BaseModel):
    client_name: str
    project_name: str = ""
    phase: str = "LEAD"
    d_tools_id: str = ""
    notes: str = ""
    metadata: Optional[dict] = None


class AdvanceRequest(BaseModel):
    details: str = ""


class NoteRequest(BaseModel):
    note: str


# ---- Endpoints ----

@router.get("")
async def list_jobs(
    active_only: bool = Query(default=True),
):
    """List jobs. By default returns only active (non-completed/warranty) jobs."""
    mgr = _mgr()
    if active_only:
        jobs = mgr.get_active_jobs()
    else:
        jobs = mgr.get_all_jobs()
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/search")
async def search_jobs(q: str = Query(..., min_length=1)):
    """Search jobs by client name, project name, or notes."""
    mgr = _mgr()
    jobs = mgr.search_jobs(q)
    return {"jobs": jobs, "count": len(jobs), "query": q}


@router.get("/phases")
async def list_phases():
    """List all phases in order."""
    return {
        "phases": [p.value for p in PHASE_ORDER],
    }


@router.get("/{job_id}")
async def get_job(job_id: int):
    """Get job details."""
    mgr = _mgr()
    job = mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.post("")
async def create_job(req: CreateJobRequest):
    """Create a new job."""
    mgr = _mgr()
    job = mgr.create_job(
        client_name=req.client_name,
        project_name=req.project_name,
        phase=req.phase,
        d_tools_id=req.d_tools_id,
        notes=req.notes,
        metadata=req.metadata,
    )
    return job


@router.post("/{job_id}/advance")
async def advance_phase(job_id: int, req: AdvanceRequest = None):
    """Advance a job to the next phase."""
    mgr = _mgr()
    details = req.details if req else ""
    result = mgr.advance_phase(job_id, details=details)
    if not result:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return result


@router.post("/{job_id}/note")
async def add_note(job_id: int, req: NoteRequest):
    """Add a note to a job."""
    mgr = _mgr()
    job = mgr.add_note(job_id, req.note)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.get("/{job_id}/timeline")
async def get_timeline(job_id: int):
    """Get full event timeline for a job."""
    mgr = _mgr()
    job = mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    events = mgr.get_job_timeline(job_id)
    return {"job_id": job_id, "events": events, "count": len(events)}
