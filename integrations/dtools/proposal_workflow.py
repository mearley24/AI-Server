#!/usr/bin/env python3
"""
proposal_workflow.py — D-Tools proposal workflow helpers

Implements the required behaviors from .cursor/rules/dtools.mdc:
1. Search previous jobs before creating
2. Track current installs
3. Offer alternatives when no match
4. Control4 as fallback

Use this before creating projects or updating proposals.
"""

import os
import json
from pathlib import Path
from typing import Optional, Any

# Load .env from AI-Server root when run as script or from Telegram
_env_path = Path.home() / "AI-Server" / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

# Import from parent integrations/dtools
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtools_client import DToolsCloudClient


def get_client() -> Optional[DToolsCloudClient]:
    """Get D-Tools API client if DTOOLS_API_KEY is set."""
    if not os.getenv("DTOOLS_API_KEY"):
        return None
    try:
        return DToolsCloudClient()
    except ValueError:
        return None


def search_before_create(project_name: str, client_name: str) -> dict:
    """
    Search projects, opportunities, and clients before creating.
    Returns matches and alternatives for the user to choose from.
    """
    client = get_client()
    if not client:
        return {
            "status": "no_api_key",
            "message": "DTOOLS_API_KEY not set. Cannot search D-Tools.",
            "matches": [],
            "alternatives": ["Create new project anyway", "Set DTOOLS_API_KEY in .env"],
        }

    result = {
        "status": "ok",
        "project_name": project_name,
        "client_name": client_name,
        "matches": [],
        "similar_projects": [],
        "similar_clients": [],
        "alternatives": [],
    }

    try:
        # 1. Search projects (all statuses)
        proj_resp = client.get_projects(page_size=100)
        proj_list = proj_resp.get("Data", proj_resp.get("data", []))
        pn_lower = project_name.lower()
        cn_lower = client_name.lower()

        for p in proj_list:
            pname = (p.get("Name") or p.get("name") or "").lower()
            cname = (p.get("ClientName") or p.get("clientName") or "").lower()
            if pn_lower in pname or cn_lower in cname:
                result["matches"].append({
                    "type": "project",
                    "id": p.get("Id") or p.get("id"),
                    "name": p.get("Name") or p.get("name"),
                    "client": p.get("ClientName") or p.get("clientName"),
                    "status": p.get("Status") or p.get("status"),
                })
            elif pn_lower[:5] in pname or cn_lower[:5] in cname:
                result["similar_projects"].append({
                    "id": p.get("Id") or p.get("id"),
                    "name": p.get("Name") or p.get("name"),
                    "client": p.get("ClientName") or p.get("clientName"),
                })

        # 2. Search opportunities
        opp_resp = client.get_opportunities(page_size=100)
        opp_list = opp_resp.get("Data", opp_resp.get("data", []))
        for o in opp_list:
            oname = (o.get("Name") or o.get("name") or "").lower()
            if pn_lower in oname or cn_lower in (o.get("ClientName") or o.get("clientName") or "").lower():
                result["matches"].append({
                    "type": "opportunity",
                    "id": o.get("Id") or o.get("id"),
                    "name": o.get("Name") or o.get("name"),
                    "status": o.get("Status") or o.get("status"),
                })

        # 3. Build alternatives
        if result["matches"]:
            result["alternatives"] = [
                "Link to existing project/opportunity above",
                "Create new project (different name)",
                "Update existing instead of creating",
            ]
        elif result["similar_projects"]:
            result["alternatives"] = [
                "Create new (no exact match)",
                "Review similar projects above",
            ]
        else:
            result["alternatives"] = [
                "Create new project",
                "Double-check project/client name",
            ]

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["alternatives"] = ["Create new project anyway", "Check DTOOLS_API_KEY"]

    return result


def get_install_context() -> dict:
    """Get active pipeline: open opportunities + active projects."""
    client = get_client()
    if not client:
        return {"status": "no_api_key", "open_opportunities": [], "active_projects": []}
    try:
        return client.get_active_pipeline()
    except Exception as e:
        return {"status": "error", "error": str(e), "open_opportunities": [], "active_projects": []}


def format_search_result(result: dict) -> str:
    """Format search_before_create result for Telegram/CLI."""
    lines = []
    if result.get("status") == "no_api_key":
        return "⚠️ DTOOLS_API_KEY not set. Set it in .env to search before creating."
    if result.get("status") == "error":
        return f"⚠️ Search failed: {result.get('error', 'unknown')}"

    if result.get("matches"):
        lines.append("📋 *Existing matches:*")
        for m in result["matches"][:5]:
            lines.append(f"  • {m.get('name', '?')} ({m.get('type', '?')}) — {m.get('status', '')}")
    if result.get("similar_projects"):
        lines.append("\n🔍 *Similar projects:*")
        for p in result["similar_projects"][:3]:
            lines.append(f"  • {p.get('name', '?')} — {p.get('client', '')}")

    lines.append("\n✅ *Options:* " + ", ".join(result.get("alternatives", [])))
    return "\n".join(lines) if lines else "No matches. Safe to create new."


def prepare_proposal_for_dtools_import(proposal_id: str) -> dict:
    """
    Load symphony proposal, export D-Tools CSV, return data for browser import.
    Returns: {"ok": True, "project_name": str, "client_name": str, "address": str, "csv_path": str}
    or {"ok": False, "error": str}
    """
    import sys
    base = Path.home() / "AI-Server"
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    try:
        from symphony.proposals.database import Database
        from symphony.proposals.generator import ProposalGenerator

        db = Database()
        gen = ProposalGenerator()
        proposal = db.get_proposal(proposal_id)
        if not proposal:
            return {"ok": False, "error": f"Proposal {proposal_id} not found"}

        if not proposal.line_items:
            return {"ok": False, "error": f"Proposal {proposal_id} has no line items"}

        client = db.get_client(proposal.client_id)
        project_name = proposal.project_name
        client_name = client.name if client else "Unknown"
        address = client.full_address if client else ""

        csv_path = gen.export_dtools_csv(proposal)
        return {
            "ok": True,
            "project_name": project_name,
            "client_name": client_name,
            "address": address,
            "csv_path": str(csv_path),
            "item_count": len(proposal.line_items),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _proposal_items_to_dtools_items(line_items: list[Any]) -> list[dict[str, Any]]:
    """Map Symphony proposal line-items into a generic D-Tools import shape."""
    out: list[dict[str, Any]] = []
    for li in line_items:
        get = (lambda k, default=None: getattr(li, k, default))
        out.append(
            {
                "Manufacturer": get("manufacturer", "") or get("brand", ""),
                "Model": get("model", "") or get("sku", ""),
                "Description": get("description", ""),
                "Quantity": int(get("quantity", 1) or 1),
                "UnitPrice": float(get("unit_price", 0) or 0),
                "Room": get("room", ""),
                "Category": get("category", ""),
            }
        )
    return out


def import_proposal_api_first(proposal_id: str) -> dict:
    """
    API-first import orchestration.
    Uses env-configurable endpoints in dtools_client and falls back gracefully.
    """
    base = Path.home() / "AI-Server"
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    try:
        from symphony.proposals.database import Database
    except Exception as e:
        return {"ok": False, "mode": "api_first", "error": f"proposal db import failed: {e}"}

    client = get_client()
    if not client:
        return {"ok": False, "mode": "api_first", "error": "DTOOLS_API_KEY not set"}

    db = Database()
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "mode": "api_first", "error": f"Proposal {proposal_id} not found"}
    if not proposal.line_items:
        return {"ok": False, "mode": "api_first", "error": f"Proposal {proposal_id} has no line items"}
    client_row = db.get_client(proposal.client_id)
    client_name = client_row.name if client_row else "Unknown"

    create = client.create_project_api_first(
        project_name=proposal.project_name,
        client_name=client_name,
        address=(client_row.full_address if client_row else ""),
    )
    create_resp = create.get("response", {}) if isinstance(create, dict) else {}
    if not create.get("success"):
        return {
            "ok": False,
            "mode": "api_first",
            "phase": "create_project",
            "error": "Project create failed",
            "details": create_resp,
        }

    project_id = (
        create_resp.get("ProjectId")
        or create_resp.get("Id")
        or create_resp.get("id")
        or create_resp.get("Data", {}).get("Id")
        or create_resp.get("Data", {}).get("ProjectId")
    )
    if not project_id:
        return {
            "ok": False,
            "mode": "api_first",
            "phase": "create_project",
            "error": "Project created but no ProjectId in response",
            "details": create_resp,
        }

    items = _proposal_items_to_dtools_items(proposal.line_items)
    imported = client.import_proposal_items_api_first(
        project_id=str(project_id),
        items=items,
        source_proposal_id=proposal_id,
    )
    if not imported.get("success"):
        return {
            "ok": False,
            "mode": "api_first",
            "phase": "import_items",
            "error": "Import items failed",
            "details": imported.get("response", {}),
        }

    return {
        "ok": True,
        "mode": "api_first",
        "project_name": proposal.project_name,
        "client_name": client_name,
        "project_id": str(project_id),
        "item_count": len(items),
        "create_response": create_resp,
        "import_response": imported.get("response", {}),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", default="Mitchell")
    parser.add_argument("client", nargs="?", default="Mitchell Family")
    parser.add_argument("--prepare-import", metavar="P-XXXX", help="Prepare symphony proposal for D-Tools import")
    parser.add_argument("--api-import", metavar="P-XXXX", help="Run API-first import (project create + items)")
    args = parser.parse_args()

    if args.api_import:
        r = import_proposal_api_first(args.api_import)
        print(json.dumps(r, indent=2))
    elif args.prepare_import:
        r = prepare_proposal_for_dtools_import(args.prepare_import)
        print(json.dumps(r, indent=2))
    else:
        r = search_before_create(args.project, args.client)
        print(json.dumps(r, indent=2))
