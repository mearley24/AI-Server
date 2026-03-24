#!/usr/bin/env python3
"""
api_server.py — FastAPI wrapper for the Symphony Smart Homes Proposal Engine.

Exposes the existing proposal_engine, pricing_calculator, and scope_builder
as an HTTP API. Stores proposals in a local SQLite DB at /data.
"""

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from proposal_engine import ProposalEngine, ProposalTemplate
from pricing_calculator import PricingCalculator, MarkupTier
from scope_builder import ScopeBuilder, ClientTier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("proposals-api")

app = FastAPI(title="Proposals API", version="1.0.0")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "proposals.db"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            client_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            template TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


_init_db()


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class RoomDef(BaseModel):
    name: str
    tier: Optional[str] = None
    systems: Optional[list[str]] = None
    notes: Optional[str] = None


class GenerateRequest(BaseModel):
    client_name: str
    project_name: str
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    email: str = ""
    phone: str = ""
    template: str = Field(default="full_automation", description="Proposal template key")
    tier: str = Field(default="better", description="Client tier: good, better, best")
    rooms: list[RoomDef] = Field(default_factory=list)
    systems: list[str] = Field(
        default_factory=lambda: ["lighting_shades", "audio_video", "networking",
                                  "control_automation"]
    )
    budget_low: Optional[float] = None
    budget_high: Optional[float] = None
    tax_rate: float = 0.0
    notes: str = ""


class ReviseRequest(BaseModel):
    proposal_id: str
    changes: dict = Field(default_factory=dict, description="Fields to update")
    notes: str = ""


class SendEmailRequest(BaseModel):
    proposal_id: str
    recipient_email: str
    template: str = Field(default="proposal_cover", description="Email template key")
    subject: Optional[str] = None


class ProposalResponse(BaseModel):
    id: str
    client_name: str
    project_name: str
    template: str
    status: str
    created_at: str
    updated_at: str
    data: dict


# ---------------------------------------------------------------------------
# Engine Instances
# ---------------------------------------------------------------------------

engine = ProposalEngine()
scope_builder = ScopeBuilder()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "proposals"}


@app.post("/proposals/generate", response_model=ProposalResponse)
async def generate_proposal(req: GenerateRequest):
    """Generate a new proposal from client requirements."""
    proposal_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()

    # Build scope
    rooms_dicts = [
        {"name": r.name, "tier": r.tier or req.tier, "systems": r.systems}
        for r in req.rooms
    ]

    tier = ClientTier(req.tier) if req.tier in [t.value for t in ClientTier] else ClientTier.BETTER

    scope = None
    if rooms_dicts:
        scope = scope_builder.build(
            rooms=rooms_dicts,
            tier=tier,
            systems=req.systems,
            budget=req.budget_high,
        )

    # Calculate pricing if scope available
    pricing = None
    if scope:
        calc = PricingCalculator(
            markup_tier=MarkupTier.RESIDENTIAL_STANDARD,
            tax_rate=req.tax_rate,
        )
        labor_phases = [
            {"phase": "Installation", "labor_hours": scope.total_labor_hours * 0.7},
            {"phase": "Programming", "labor_hours": scope.total_labor_hours * 0.2},
            {"phase": "Commissioning", "labor_hours": scope.total_labor_hours * 0.1},
        ]
        pricing = calc.calculate(
            equipment=[],
            labor_phases=labor_phases,
            budget_low=req.budget_low,
            budget_high=req.budget_high,
        )

    # Assemble proposal data
    proposal_data = {
        "id": proposal_id,
        "client": {
            "name": req.client_name,
            "address": req.address,
            "city": req.city,
            "state": req.state,
            "zip_code": req.zip_code,
            "email": req.email,
            "phone": req.phone,
        },
        "project_name": req.project_name,
        "template": req.template,
        "tier": req.tier,
        "systems": req.systems,
        "scope": asdict(scope) if scope else None,
        "pricing": asdict(pricing) if pricing else None,
        "notes": req.notes,
    }

    # Store in DB
    conn = _get_db()
    conn.execute(
        """INSERT INTO proposals (id, client_name, project_name, template, status, created_at, updated_at, data)
           VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)""",
        (proposal_id, req.client_name, req.project_name, req.template, now, now,
         json.dumps(proposal_data)),
    )
    conn.commit()
    conn.close()

    logger.info("Proposal generated: %s for %s", proposal_id, req.client_name)

    return ProposalResponse(
        id=proposal_id,
        client_name=req.client_name,
        project_name=req.project_name,
        template=req.template,
        status="draft",
        created_at=now,
        updated_at=now,
        data=proposal_data,
    )


@app.post("/proposals/revise", response_model=ProposalResponse)
async def revise_proposal(req: ReviseRequest):
    """Revise an existing proposal."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (req.proposal_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Proposal {req.proposal_id} not found")

    data = json.loads(row["data"])
    data.update(req.changes)
    if req.notes:
        data["notes"] = req.notes

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE proposals SET data = ?, updated_at = ?, status = 'revised' WHERE id = ?",
        (json.dumps(data), now, req.proposal_id),
    )
    conn.commit()
    conn.close()

    logger.info("Proposal revised: %s", req.proposal_id)

    return ProposalResponse(
        id=req.proposal_id,
        client_name=data.get("client", {}).get("name", ""),
        project_name=data.get("project_name", ""),
        template=data.get("template", ""),
        status="revised",
        created_at=row["created_at"],
        updated_at=now,
        data=data,
    )


@app.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(proposal_id: str):
    """Get a proposal by ID."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")

    data = json.loads(row["data"])
    return ProposalResponse(
        id=row["id"],
        client_name=row["client_name"],
        project_name=row["project_name"],
        template=row["template"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        data=data,
    )


@app.post("/proposals/send-email")
async def send_email(req: SendEmailRequest):
    """Trigger email send for a proposal (placeholder — requires SMTP config)."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (req.proposal_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Proposal {req.proposal_id} not found")

    # TODO: Implement actual SMTP send via Zoho
    logger.info(
        "Email send requested: proposal=%s, to=%s, template=%s",
        req.proposal_id, req.recipient_email, req.template,
    )

    return {
        "status": "queued",
        "proposal_id": req.proposal_id,
        "recipient": req.recipient_email,
        "template": req.template,
        "note": "Email sending not yet implemented — SMTP integration pending",
    }


@app.get("/proposals/templates/list")
async def list_templates():
    """List available proposal and email templates."""
    proposal_templates_dir = Path(__file__).parent / "proposal_templates"
    email_templates_dir = Path(__file__).parent / "email_templates"

    proposal_templates = []
    if proposal_templates_dir.exists():
        proposal_templates = [f.stem for f in proposal_templates_dir.glob("*.md")]

    email_templates = []
    if email_templates_dir.exists():
        email_templates = [f.stem for f in email_templates_dir.glob("*.md")]

    return {
        "proposal_templates": sorted(proposal_templates),
        "email_templates": sorted(email_templates),
    }
