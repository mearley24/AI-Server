#!/usr/bin/env python3
"""
dtool_cloud_client.py — D-Tools Cloud API Integration

Symphony Smart Homes' interface to D-Tools Cloud (portal.d-tools.com).
Operates via the HARPA AI browser automation bridge — there is no public
D-Tools Cloud REST API, so all commands are routed through the HARPA Grid.

Architecture:
    Bob (OpenClaw) → dtool_cloud_client.py → HARPA Bridge (port 3000) → D-Tools Cloud (Chrome)

Usage:
    from dtool_cloud_client import DToolsCloudClient
    client = DToolsCloudClient()
    project_id = await client.create_project("Smith", "Smith Residence", "123 Main St")
"""

import asyncio
import csv
import io
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DTOOLS_PHASES = [
    "Proposal",
    "Contract",
    "Work Order",
    "Installation",
    "Punch List",
    "Invoicing",
    "Closed",
]

VALID_DTOOLS_CATEGORIES = {
    "Audio", "Video", "Lighting", "Networking", "Control",
    "Security", "Climate", "Power", "Cabling", "Rack", "Labor",
}

# HARPA bridge endpoints
DEFAULT_PRIMARY_URL = "http://192.168.1.20:3000"
DEFAULT_FALLBACK_URL = "http://192.168.1.30:3000"

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0   # seconds; exponential backoff
REQUEST_TIMEOUT = 60.0     # seconds


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DTException(Exception):
    """Base class for D-Tools integration errors."""


class DTSessionExpired(DTException):
    """Chrome/browser session expired — requires manual re-login on HARPA node."""


class DTProjectNotFound(DTException):
    """Project ID does not exist in D-Tools Cloud."""


class DTImportError(DTException):
    """Equipment CSV import failed."""


class DTExportError(DTException):
    """Proposal PDF export failed."""


class DTPhaseError(DTException):
    """Invalid phase name or phase transition not allowed."""


class HARPANodeUnavailable(DTException):
    """All HARPA browser automation nodes are offline."""


class DTValidationError(DTException):
    """Equipment list or project data failed validation before submission."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class DTProject:
    project_id: str
    project_name: str
    client_name: str
    address: str
    phase: str
    created_date: str
    last_updated: str
    rooms: list[str] = field(default_factory=list)
    equipment_count: int = 0


@dataclass
class DTEquipmentItem:
    model: str
    manufacturer: str
    category: str
    quantity: int
    room: str
    notes: str = ""
    unit_price: Optional[float] = None    # None until D-Tools populates from catalog
    extended_price: Optional[float] = None
    price_source: str = "dtools"


@dataclass
class DTContact:
    contact_id: str
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    address: str = ""


@dataclass
class DTImportResult:
    success: bool
    items_imported: int
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    raw_response: Optional[dict] = None


# ---------------------------------------------------------------------------
# HARPA Bridge
# ---------------------------------------------------------------------------

class HARPABridge:
    """
    Routes commands to D-Tools Cloud via the HARPA AI browser automation bridge.

    HARPA operates as the logged-in Chrome browser session on Maestro/Stagehand.
    Primary node tried first; falls back to secondary if unreachable.
    """

    def __init__(
        self,
        primary_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.primary_url = primary_url or os.getenv("HARPA_PRIMARY_URL", DEFAULT_PRIMARY_URL)
        self.fallback_url = fallback_url or os.getenv("HARPA_FALLBACK_URL", DEFAULT_FALLBACK_URL)
        self.api_key = api_key or os.getenv("HARPA_GRID_API_KEY", "")
        self._node_status: dict[str, bool] = {}

    async def execute(self, command: str, params: dict, retries: int = MAX_RETRIES) -> dict:
        """
        Execute a D-Tools HARPA command with retry and failover.

        Args:
            command: HARPA command name (e.g. "create_project")
            params: Command parameters
            retries: Max retry attempts

        Returns:
            Command result dict

        Raises:
            HARPANodeUnavailable: If all nodes are unreachable after retries
            DTSessionExpired: If D-Tools browser session has expired
        """
        nodes = [self.primary_url, self.fallback_url]
        last_exception: Optional[Exception] = None

        for attempt in range(retries):
            for node_url in nodes:
                try:
                    result = await self._call_node(node_url, command, params)
                    self._node_status[node_url] = True
                    return result

                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.warning("HARPA node %s unreachable (attempt %d): %s", node_url, attempt + 1, e)
                    self._node_status[node_url] = False
                    last_exception = e
                    continue

                except DTSessionExpired:
                    raise  # Session expiry requires human intervention — don't retry

                except Exception as e:
                    logger.error("HARPA node %s error: %s", node_url, e)
                    last_exception = e
                    continue

            # Exponential backoff before next retry round
            if attempt < retries - 1:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.info("Retrying in %.1fs...", wait)
                await asyncio.sleep(wait)

        raise HARPANodeUnavailable(
            f"All HARPA nodes unreachable after {retries} attempt(s). Last error: {last_exception}"
        )

    async def _call_node(self, node_url: str, command: str, params: dict) -> dict:
        """Make a single HTTP request to a HARPA bridge node."""
        payload = {
            "command": command,
            "params": params,
            "api_key": self.api_key,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
            resp = await http.post(f"{node_url}/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Check for session expiry
        error_msg = str(data.get("error", "")).lower()
        if "session expired" in error_msg or "please log in" in error_msg or "login" in error_msg:
            raise DTSessionExpired(
                f"D-Tools browser session expired on {node_url}. "
                "Re-login required on Maestro or Stagehand."
            )

        return data

    async def health_check(self) -> dict[str, bool]:
        """Check which HARPA nodes are reachable."""
        results: dict[str, bool] = {}
        for node_url in [self.primary_url, self.fallback_url]:
            try:
                async with httpx.AsyncClient(timeout=5.0) as http:
                    resp = await http.get(f"{node_url}/health")
                    results[node_url] = resp.status_code == 200
            except Exception:
                results[node_url] = False
        self._node_status = results
        return results


# ---------------------------------------------------------------------------
# D-Tools Cloud Client
# ---------------------------------------------------------------------------

class DToolsCloudClient:
    """
    High-level client for D-Tools Cloud via HARPA browser automation.

    All methods are async. Instantiate once and reuse across the session.
    Session validity is checked before long workflows; re-login alerts are
    sent to owner via the notification hook if session has expired.
    """

    def __init__(
        self,
        harpa_primary_url: Optional[str] = None,
        harpa_fallback_url: Optional[str] = None,
        harpa_api_key: Optional[str] = None,
        notify_hook: Optional[callable] = None,
    ):
        self.bridge = HARPABridge(harpa_primary_url, harpa_fallback_url, harpa_api_key)
        self._notify_hook = notify_hook  # async callable for owner alerts
        logger.info("DToolsCloudClient initialized (primary: %s)", self.bridge.primary_url)

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    async def check_session(self) -> bool:
        """
        Verify D-Tools browser session is active.
        Sends owner notification if expired.

        Returns:
            True if session is valid, False if expired/unreachable
        """
        try:
            await self.bridge.execute("search_projects", {"query": "__session_check__"})
            logger.debug("D-Tools session check: OK")
            return True
        except DTSessionExpired as e:
            logger.error("D-Tools session expired: %s", e)
            if self._notify_hook:
                await self._notify_hook(
                    "⚠️ D-Tools Cloud session expired. Please re-login on Maestro or Stagehand "
                    "(open Chrome → portal.d-tools.com → log in)."
                )
            return False
        except HARPANodeUnavailable:
            logger.error("HARPA nodes unreachable during session check")
            return False

    # ------------------------------------------------------------------
    # Project Management
    # ------------------------------------------------------------------

    async def create_project(
        self,
        client_name: str,
        project_name: str,
        address: str,
    ) -> str:
        """
        Create a new project in D-Tools Cloud.

        Args:
            client_name: Client last name or company name (e.g. "Smith")
            project_name: Full project name (e.g. "Smith Residence")
            address: Full street address

        Returns:
            project_id (str) — use for all subsequent operations

        Raises:
            DTException: If project creation fails
        """
        logger.info("Creating D-Tools project: %s", project_name)

        result = await self.bridge.execute("create_project", {
            "client_name": client_name,
            "project_name": project_name,
            "address": address,
        })

        project_id = result.get("project_id")
        if not project_id:
            raise DTException(f"create_project returned no project_id: {result}")

        logger.info("D-Tools project created: %s → ID: %s", project_name, project_id)
        return project_id

    async def get_project(self, project_id: str) -> DTProject:
        """
        Retrieve full project details from D-Tools Cloud.

        Args:
            project_id: D-Tools project ID

        Returns:
            DTProject dataclass

        Raises:
            DTProjectNotFound: If project ID doesn't exist
        """
        result = await self.bridge.execute("get_project_status", {"project_id": project_id})

        if result.get("error", "").lower() == "not found":
            raise DTProjectNotFound(f"Project {project_id} not found in D-Tools Cloud")

        return DTProject(
            project_id=project_id,
            project_name=result.get("project_name", ""),
            client_name=result.get("client_name", ""),
            address=result.get("address", ""),
            phase=result.get("phase", "Proposal"),
            created_date=result.get("created_date", ""),
            last_updated=result.get("last_updated", ""),
            rooms=result.get("rooms", []),
            equipment_count=result.get("equipment_count", 0),
        )

    async def search_projects(self, query: str) -> list[dict]:
        """
        Search projects by client name or project name.

        Args:
            query: Search term (client name or project name)

        Returns:
            List of dicts: [{project_id, name, client, phase}]
        """
        logger.debug("Searching D-Tools projects: '%s'", query)
        result = await self.bridge.execute("search_projects", {"query": query})
        return result.get("projects", [])

    async def update_project_phase(self, project_id: str, new_phase: str) -> bool:
        """
        Advance a project to the next phase in D-Tools Cloud.

        Args:
            project_id: D-Tools project ID
            new_phase: Target phase — must be one of DTOOLS_PHASES exactly

        Returns:
            True on success

        Raises:
            DTPhaseError: If phase name is invalid
        """
        if new_phase not in DTOOLS_PHASES:
            raise DTPhaseError(
                f"Invalid phase '{new_phase}'. Must be one of: {', '.join(DTOOLS_PHASES)}"
            )

        logger.info("Updating project %s → phase: %s", project_id, new_phase)
        result = await self.bridge.execute("update_project_phase", {
            "project_id": project_id,
            "new_phase": new_phase,
        })

        success = result.get("success", False)
        if not success:
            raise DTException(f"Phase update failed: {result}")

        logger.info("Project %s phase updated to: %s", project_id, new_phase)
        return True

    # ------------------------------------------------------------------
    # Equipment / Line Items
    # ------------------------------------------------------------------

    async def import_equipment_csv(
        self,
        project_id: str,
        equipment: list[DTEquipmentItem],
    ) -> DTImportResult:
        """
        Import equipment list into a D-Tools Cloud project.

        Validates all items before submission. Equipment with invalid
        categories or missing room assignments are logged and skipped.

        Args:
            project_id: D-Tools project ID
            equipment: List of DTEquipmentItem objects

        Returns:
            DTImportResult with success status and item counts

        Raises:
            DTValidationError: If validation errors are critical
            DTImportError: If D-Tools import fails
        """
        # Validate before sending
        validated, errors = self._validate_equipment(equipment)

        if not validated:
            raise DTValidationError(
                f"Equipment list has {len(errors)} critical validation error(s): {errors[:3]}"
            )

        csv_content = self._generate_csv(validated)
        logger.info("Importing %d equipment items to project %s", len(validated), project_id)

        result = await self.bridge.execute("import_equipment_csv", {
            "project_id": project_id,
            "csv_content": csv_content,
        })

        if not result.get("success", False):
            raise DTImportError(f"D-Tools equipment import failed: {result}")

        import_result = DTImportResult(
            success=True,
            items_imported=result.get("items_imported", len(validated)),
            items_skipped=len(equipment) - len(validated),
            errors=errors,
            raw_response=result,
        )

        logger.info(
            "Equipment import complete: %d imported, %d skipped, %d errors",
            import_result.items_imported,
            import_result.items_skipped,
            len(import_result.errors),
        )
        return import_result

    async def import_equipment_from_csv_string(
        self,
        project_id: str,
        csv_content: str,
    ) -> DTImportResult:
        """
        Import equipment from a pre-generated CSV string (e.g. from ProposalEngine).

        Args:
            project_id: D-Tools project ID
            csv_content: CSV string with headers: Model,Manufacturer,Category,Quantity,Room,Notes

        Returns:
            DTImportResult
        """
        logger.info("Importing CSV to project %s (%d chars)", project_id, len(csv_content))

        result = await self.bridge.execute("import_equipment_csv", {
            "project_id": project_id,
            "csv_content": csv_content,
        })

        if not result.get("success", False):
            raise DTImportError(f"D-Tools CSV import failed: {result}")

        return DTImportResult(
            success=True,
            items_imported=result.get("items_imported", 0),
            raw_response=result,
        )

    # ------------------------------------------------------------------
    # Proposal / Quote Export
    # ------------------------------------------------------------------

    async def export_proposal_pdf(self, project_id: str) -> str:
        """
        Export proposal as PDF from D-Tools Cloud.

        Args:
            project_id: D-Tools project ID

        Returns:
            Download URL (temporary — download promptly)

        Raises:
            DTExportError: If export fails
        """
        logger.info("Exporting proposal PDF for project %s", project_id)

        result = await self.bridge.execute("export_proposal", {"project_id": project_id})
        url = result.get("download_url")

        if not url:
            raise DTExportError(f"No download URL in export response: {result}")

        logger.info("Proposal PDF export URL: %s", url)
        return url

    async def download_proposal_pdf(self, project_id: str, output_path: Path) -> Path:
        """
        Export and download proposal PDF to a local file.

        Args:
            project_id: D-Tools project ID
            output_path: Full path for the downloaded PDF

        Returns:
            Path to downloaded file
        """
        download_url = await self.export_proposal_pdf(project_id)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0) as http:
            resp = await http.get(download_url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

        logger.info("Proposal PDF downloaded: %s (%d bytes)", output_path, len(resp.content))
        return output_path

    # ------------------------------------------------------------------
    # Contact / Client Management
    # ------------------------------------------------------------------

    async def find_contact(self, name: str, email: str = "") -> Optional[DTContact]:
        """
        Search for an existing contact in D-Tools Cloud.

        Args:
            name: Client name (first + last, or company)
            email: Optional email for disambiguation

        Returns:
            DTContact if found, None otherwise
        """
        projects = await self.search_projects(name)
        if projects:
            # Extract contact info from first matching project
            p = projects[0]
            return DTContact(
                contact_id=p.get("client_id", ""),
                first_name=p.get("client_name", name).split()[0] if " " in name else name,
                last_name=p.get("client_name", name).split()[-1] if " " in name else "",
                email=email,
            )
        return None

    # ------------------------------------------------------------------
    # Full Workflow
    # ------------------------------------------------------------------

    async def create_project_with_equipment(
        self,
        client_name: str,
        project_name: str,
        address: str,
        equipment: list[DTEquipmentItem],
    ) -> tuple[str, DTImportResult]:
        """
        Full workflow: create project → import equipment.

        This is the standard path Bob uses when a new proposal is approved.

        Args:
            client_name: Client last name
            project_name: Full project name
            address: Property address
            equipment: Equipment list

        Returns:
            (project_id, DTImportResult)
        """
        logger.info("Starting full D-Tools project creation workflow: %s", project_name)

        # Step 1: Check session first
        session_ok = await self.check_session()
        if not session_ok:
            raise DTSessionExpired("D-Tools session must be active before creating projects")

        # Step 2: Create project
        project_id = await self.create_project(client_name, project_name, address)

        # Step 3: Import equipment
        import_result = await self.import_equipment_csv(project_id, equipment)

        logger.info(
            "D-Tools workflow complete: project=%s, imported=%d",
            project_id, import_result.items_imported
        )
        return project_id, import_result

    async def create_project_from_proposal(
        self,
        proposal_dict: dict,
    ) -> tuple[str, DTImportResult]:
        """
        Create a D-Tools project directly from a ProposalEngine output dict.

        Args:
            proposal_dict: dict from ProposalEngine.to_json() / asdict(proposal)

        Returns:
            (project_id, DTImportResult)
        """
        client = proposal_dict["client"]
        project_name = proposal_dict["project_name"]
        address = f"{client['address']}, {client['city']}, {client['state']} {client['zip_code']}"

        # Convert equipment list
        equipment = [
            DTEquipmentItem(
                model=item["model"],
                manufacturer=item["manufacturer"],
                category=item["category"],
                quantity=item["quantity"],
                room=item["room"],
                notes=item.get("notes", ""),
            )
            for item in proposal_dict.get("equipment_list", [])
        ]

        return await self.create_project_with_equipment(
            client_name=client["name"],
            project_name=project_name,
            address=address,
            equipment=equipment,
        )

    # ------------------------------------------------------------------
    # Product Catalog Search
    # ------------------------------------------------------------------

    async def search_catalog(self, query: str, category: Optional[str] = None) -> list[dict]:
        """
        Search the D-Tools product catalog.

        Note: Catalog search is limited by HARPA browser automation capabilities.
        Results include model numbers and current pricing from D-Tools database.

        Args:
            query: Search term (model number or product name)
            category: Optional D-Tools category filter

        Returns:
            List of product dicts: [{model, manufacturer, category, price}]
        """
        params: dict = {"query": query}
        if category:
            if category not in VALID_DTOOLS_CATEGORIES:
                raise DTValidationError(f"Invalid category: {category}")
            params["category"] = category

        try:
            result = await self.bridge.execute("search_catalog", params)
            return result.get("products", [])
        except Exception as e:
            logger.warning("Catalog search failed for '%s': %s", query, e)
            return []

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _validate_equipment(
        self, equipment: list[DTEquipmentItem]
    ) -> tuple[list[DTEquipmentItem], list[str]]:
        """
        Validate equipment list against D-Tools rules.

        Returns:
            (valid_items, error_messages)
        """
        valid: list[DTEquipmentItem] = []
        errors: list[str] = []

        for item in equipment:
            item_errors: list[str] = []

            if not item.model or not item.model.strip():
                item_errors.append(f"Empty model number")

            if item.category not in VALID_DTOOLS_CATEGORIES:
                item_errors.append(
                    f"'{item.model}': invalid category '{item.category}' — "
                    f"must be one of {', '.join(sorted(VALID_DTOOLS_CATEGORIES))}"
                )

            if not item.room or item.room.lower() in ("", "unassigned", "tbd", "none"):
                item_errors.append(f"'{item.model}': missing room assignment")

            if item.quantity != int(item.quantity) or item.quantity < 1:
                item_errors.append(f"'{item.model}': quantity must be a positive integer, got {item.quantity}")

            if item_errors:
                errors.extend(item_errors)
                logger.warning("Equipment validation failed: %s", "; ".join(item_errors))
            else:
                valid.append(item)

        return valid, errors

    def _generate_csv(self, equipment: list[DTEquipmentItem]) -> str:
        """Generate D-Tools CSV string from validated equipment list."""
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["Model", "Manufacturer", "Category", "Quantity", "Room", "Notes"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()

        for item in equipment:
            writer.writerow({
                "Model":        item.model,
                "Manufacturer": item.manufacturer,
                "Category":     item.category,
                "Quantity":     int(item.quantity),
                "Room":         item.room,
                "Notes":        item.notes or "",
            })

        return output.getvalue()


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def get_dtools_client(notify_hook: Optional[callable] = None) -> DToolsCloudClient:
    """
    Create a DToolsCloudClient with environment variable configuration.

    Args:
        notify_hook: Optional async callable for owner alerts (e.g. Telegram send)

    Returns:
        Configured DToolsCloudClient instance
    """
    return DToolsCloudClient(
        harpa_primary_url=os.getenv("HARPA_PRIMARY_URL"),
        harpa_fallback_url=os.getenv("HARPA_FALLBACK_URL"),
        harpa_api_key=os.getenv("HARPA_GRID_API_KEY"),
        notify_hook=notify_hook,
    )


# ---------------------------------------------------------------------------
# CLI / testing entry point
# ---------------------------------------------------------------------------

async def _smoke_test() -> None:
    """Quick smoke test for development — requires HARPA bridge running."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    client = get_dtools_client()

    # Check HARPA node health
    health = await client.bridge.health_check()
    for node, ok in health.items():
        status = "✓ online" if ok else "✗ offline"
        print(f"  HARPA node {node}: {status}")

    # Check D-Tools session
    session_ok = await client.check_session()
    print(f"  D-Tools session: {'✓ active' if session_ok else '✗ expired'}")

    if session_ok:
        # Search for test project
        results = await client.search_projects("test")
        print(f"  Search 'test': {len(results)} project(s) found")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
