#!/usr/bin/env python3
"""
proposal_engine.py — Symphony Smart Homes Proposal Generation Engine

Main engine for generating professional AV/smart home proposals.
Takes client requirements, matches scope blocks, selects equipment,
calculates pricing, and produces structured proposal JSON.

Usage:
    from proposal_engine import ProposalEngine
    engine = ProposalEngine()
    proposal = engine.generate(requirements)
"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class ProposalTemplate(str, Enum):
    BASIC_AV = "basic_av"
    FULL_AUTOMATION = "full_automation"
    RETROFIT = "retrofit"
    COMMERCIAL = "commercial"
    MAINTENANCE = "maintenance_agreement"


class ClientTier(str, Enum):
    GOOD = "good"
    BETTER = "better"
    BEST = "best"


class ProjectPhase(str, Enum):
    PREWIRE = "Pre-Wire"
    ROUGH_IN = "Rough-In"
    TRIM = "Trim"
    PROGRAMMING = "Programming"
    COMMISSIONING = "Commissioning"


# D-Tools category taxonomy — must match exactly
VALID_DTOOLS_CATEGORIES = {
    "Audio", "Video", "Lighting", "Networking", "Control",
    "Security", "Climate", "Power", "Cabling", "Rack", "Labor"
}

# Required coverage gap checks per proposals.mdc
REQUIRED_CHECKS = [
    "every_ip_device_has_ethernet_drop",
    "amp_channel_count_matches_speaker_count",
    "theater_has_blackout_shades",
    "network_rack_has_ups",
    "all_fixtures_are_dimmer_compatible",
    "outdoor_devices_have_ip_ratings",
    "programming_hours_budgeted",
    "keypad_locations_on_floor_plan",
    "all_equipment_in_dtools_has_room_assignment",
    "control4_drivers_verified_for_third_party_devices",
]

# Template → systems in scope
TEMPLATE_SYSTEMS: dict[str, list[str]] = {
    ProposalTemplate.BASIC_AV: ["audio_video", "networking"],
    ProposalTemplate.FULL_AUTOMATION: [
        "lighting_shades", "audio_video", "networking",
        "security_surveillance", "control_automation", "climate"
    ],
    ProposalTemplate.RETROFIT: [
        "lighting_shades", "audio_video", "networking",
        "security_surveillance", "control_automation"
    ],
    ProposalTemplate.COMMERCIAL: [
        "audio_video", "networking", "security_surveillance", "control_automation"
    ],
    ProposalTemplate.MAINTENANCE: [],
}

# Standard project phases with typical durations (days)
PROJECT_PHASES: list[dict] = [
    {"phase": ProjectPhase.PREWIRE, "description": "Low-voltage rough-in before drywall", "typical_days": None},
    {"phase": ProjectPhase.ROUGH_IN, "description": "Head-end install, rack build, cable pull", "typical_days": "1–3"},
    {"phase": ProjectPhase.TRIM, "description": "Device install, terminations, speakers", "typical_days": "3–5"},
    {"phase": ProjectPhase.PROGRAMMING, "description": "Control4, Lutron, system integration", "typical_days": "1–2"},
    {"phase": ProjectPhase.COMMISSIONING, "description": "Testing, client walkthrough, punch-list", "typical_days": "1"},
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ClientInfo:
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    email: str = ""
    phone: str = ""
    contact_id: Optional[str] = None  # D-Tools contact ID


@dataclass
class RoomRequirement:
    name: str                               # e.g. "Master Bedroom"
    tier: ClientTier = ClientTier.BETTER
    systems: list[str] = field(default_factory=list)  # systems requested in this room
    notes: str = ""
    square_footage: Optional[int] = None


@dataclass
class ProjectRequirements:
    client: ClientInfo
    template: ProposalTemplate
    tier: ClientTier                        # default tier for all rooms
    rooms: list[RoomRequirement]
    budget_low: Optional[float] = None
    budget_high: Optional[float] = None
    preferences: list[str] = field(default_factory=list)
    special_notes: str = ""
    existing_systems: list[str] = field(default_factory=list)
    is_new_construction: bool = True
    square_footage: Optional[int] = None


@dataclass
class EquipmentItem:
    model: str
    manufacturer: str
    category: str
    quantity: int
    room: str
    notes: str = ""
    unit_price: Optional[float] = None     # None until D-Tools populates
    extended_price: Optional[float] = None
    price_source: str = "dtools"           # always dtools per rules


@dataclass
class ScopeSection:
    system_name: str                        # e.g. "3.1 Lighting & Shading"
    summary: str
    line_items: list[str] = field(default_factory=list)


@dataclass
class LaborPhase:
    phase: str
    description: str
    estimated_days: Optional[str] = None
    labor_hours: Optional[float] = None


@dataclass
class PricingSummary:
    equipment_subtotal: Optional[float] = None   # from D-Tools
    labor_total: Optional[float] = None
    programming_total: Optional[float] = None
    tax_total: Optional[float] = None
    project_total: Optional[float] = None
    markup_tier: str = "residential_standard"
    notes: str = "Pricing populated from D-Tools Cloud catalog"


@dataclass
class CoverageGapCheck:
    check_id: str
    passed: bool
    details: str = ""
    severity: str = "warning"               # "warning" | "error"


@dataclass
class Proposal:
    proposal_id: str
    version: int
    created_date: str
    last_updated: str
    template: str
    client: ClientInfo
    project_name: str
    executive_summary: str
    scope_sections: list[ScopeSection]
    equipment_list: list[EquipmentItem]
    labor_phases: list[LaborPhase]
    pricing: PricingSummary
    assumptions: list[str]
    exclusions: list[str]
    optional_upgrades: list[dict]
    payment_schedule: list[dict]
    terms_conditions: str
    coverage_gaps: list[CoverageGapCheck]
    dtools_project_id: Optional[str] = None
    dtools_csv: Optional[str] = None
    status: str = "draft"


# ---------------------------------------------------------------------------
# Knowledge Base Loader
# ---------------------------------------------------------------------------

class KnowledgeBaseLoader:
    """Loads scope blocks and room configs from the proposal library."""

    def __init__(self, kb_root: Optional[Path] = None):
        self.kb_root = kb_root or Path.home() / "AI-Server" / "knowledge" / "proposal_library"
        self._scope_cache: dict[str, str] = {}
        self._room_cache: dict[str, str] = {}

    def load_scope_block(self, system: str) -> str:
        """Load a scope block markdown file by system name."""
        if system in self._scope_cache:
            return self._scope_cache[system]

        path = self.kb_root / "scope_blocks" / f"{system}.md"
        if not path.exists():
            logger.warning("Scope block not found: %s", path)
            return f"# {system.replace('_', ' ').title()}\n\n[Scope block not yet defined]"

        content = path.read_text(encoding="utf-8")
        self._scope_cache[system] = content
        logger.debug("Loaded scope block: %s", system)
        return content

    def load_room_config(self, room_name: str) -> str:
        """Load a room config markdown file by normalized room name."""
        key = room_name.lower().replace(" ", "_").replace("/", "_")
        if key in self._room_cache:
            return self._room_cache[key]

        # Try exact match then fuzzy
        candidates = list((self.kb_root / "room_configs").glob("*.md")) if (self.kb_root / "room_configs").exists() else []
        matched = next((p for p in candidates if p.stem == key), None)
        if not matched:
            matched = next((p for p in candidates if key in p.stem or p.stem in key), None)

        if not matched:
            logger.warning("Room config not found for: %s", room_name)
            return f"# {room_name}\n\n[Room config not yet defined]"

        content = matched.read_text(encoding="utf-8")
        self._room_cache[key] = content
        logger.debug("Loaded room config: %s → %s", room_name, matched.name)
        return content

    def load_assumptions_exclusions(self) -> str:
        path = self.kb_root / "assumptions_exclusions.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def load_master_template(self) -> str:
        path = self.kb_root / "proposal_master_template.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Coverage Gap Checker
# ---------------------------------------------------------------------------

class CoverageGapChecker:
    """Validates a proposal for common integration pitfalls."""

    def run_all_checks(
        self,
        equipment: list[EquipmentItem],
        rooms: list[RoomRequirement],
        scope_systems: list[str],
    ) -> list[CoverageGapCheck]:
        results: list[CoverageGapCheck] = []

        results.append(self._check_ip_devices_have_ethernet(equipment))
        results.append(self._check_amp_channels_match_speakers(equipment))
        results.append(self._check_theater_blackout_shades(rooms, equipment))
        results.append(self._check_network_rack_ups(equipment))
        results.append(self._check_programming_hours(equipment, scope_systems))
        results.append(self._check_room_assignments(equipment))
        results.append(self._check_outdoor_ip_ratings(equipment))
        results.append(self._check_dimmer_compatibility(equipment))

        gap_count = sum(1 for r in results if not r.passed)
        if gap_count:
            logger.warning("%d coverage gap(s) detected — review before delivering proposal", gap_count)
        return results

    def _check_ip_devices_have_ethernet(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        ip_categories = {"Control", "Security", "Networking"}
        ip_devices = [e for e in equipment if e.category in ip_categories]
        # Look for cabling line items
        cabling_items = [e for e in equipment if e.category == "Cabling" and "cat6" in e.model.lower()]
        passed = len(ip_devices) == 0 or len(cabling_items) > 0
        return CoverageGapCheck(
            check_id="every_ip_device_has_ethernet_drop",
            passed=passed,
            details=f"{len(ip_devices)} IP device(s); {'Cat6 cabling present' if passed else 'No Cat6 cabling found — add network drops'}",
            severity="error" if not passed else "ok",
        )

    def _check_amp_channels_match_speakers(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        amps = [e for e in equipment if e.category == "Audio" and "amp" in e.model.lower()]
        speakers = [e for e in equipment if e.category == "Audio" and any(
            kw in e.model.lower() for kw in ("speaker", "in-ceiling", "outdoor", "subwoofer")
        )]
        # Rough check: each amp channel should serve ≤2 speakers
        total_speakers = sum(s.quantity for s in speakers)
        # PAMP-8 = 8ch, PAMP-4 = 4ch, Triad One = 1ch
        amp_channels = 0
        for a in amps:
            if "pamp-8" in a.model.lower() or "8-channel" in a.model.lower():
                amp_channels += 8 * a.quantity
            elif "pamp-4" in a.model.lower() or "4-channel" in a.model.lower():
                amp_channels += 4 * a.quantity
            else:
                amp_channels += 2 * a.quantity  # conservative default

        passed = amp_channels == 0 or amp_channels * 2 >= total_speakers
        return CoverageGapCheck(
            check_id="amp_channel_count_matches_speaker_count",
            passed=passed,
            details=f"{amp_channels} amp channels, {total_speakers} speakers — {'OK' if passed else 'UNDERSIZED — add amplification'}",
            severity="error" if not passed else "ok",
        )

    def _check_theater_blackout_shades(
        self, rooms: list[RoomRequirement], equipment: list[EquipmentItem]
    ) -> CoverageGapCheck:
        theater_rooms = [r for r in rooms if "theater" in r.name.lower() or "media" in r.name.lower()]
        if not theater_rooms:
            return CoverageGapCheck(
                check_id="theater_has_blackout_shades",
                passed=True,
                details="No theater/media room in project",
            )
        theater_names = {r.name for r in theater_rooms}
        has_shades = any(
            e.room in theater_names and "shade" in (e.model + e.notes).lower()
            for e in equipment
        )
        return CoverageGapCheck(
            check_id="theater_has_blackout_shades",
            passed=has_shades,
            details="Blackout shades present in theater" if has_shades else "MISSING: Theater requires blackout shades — projector image ruined by ambient light",
            severity="error" if not has_shades else "ok",
        )

    def _check_network_rack_ups(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        has_ups = any(
            e.category == "Power" and "ups" in (e.model + e.notes).lower()
            for e in equipment
        )
        return CoverageGapCheck(
            check_id="network_rack_has_ups",
            passed=has_ups,
            details="UPS on network rack present" if has_ups else "MISSING: UPS required on network rack — non-negotiable",
            severity="error" if not has_ups else "ok",
        )

    def _check_programming_hours(
        self, equipment: list[EquipmentItem], scope_systems: list[str]
    ) -> CoverageGapCheck:
        labor_items = [e for e in equipment if e.category == "Labor"]
        has_programming = any("program" in e.notes.lower() or "program" in e.model.lower() for e in labor_items)
        # Full automation requires dedicated programming line
        needs_programming = "control_automation" in scope_systems
        passed = not needs_programming or has_programming
        return CoverageGapCheck(
            check_id="programming_hours_budgeted",
            passed=passed,
            details="Programming hours included" if passed else "MISSING: Control4/Lutron programming hours not budgeted",
            severity="warning" if not passed else "ok",
        )

    def _check_room_assignments(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        unassigned = [e for e in equipment if not e.room or e.room.lower() in ("", "unassigned", "tbd")]
        passed = len(unassigned) == 0
        return CoverageGapCheck(
            check_id="all_equipment_in_dtools_has_room_assignment",
            passed=passed,
            details=f"All {len(equipment)} items assigned to rooms" if passed else f"{len(unassigned)} item(s) have no room assignment: {[e.model for e in unassigned[:3]]}",
            severity="error" if not passed else "ok",
        )

    def _check_outdoor_ip_ratings(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        outdoor_items = [e for e in equipment if "outdoor" in e.room.lower() or "exterior" in e.room.lower() or "patio" in e.room.lower()]
        unrated = [e for e in outdoor_items if "ip65" not in e.notes.lower() and "ip67" not in e.notes.lower() and "sunbrite" not in e.model.lower() and "outdoor" not in e.model.lower()]
        passed = len(unrated) == 0
        return CoverageGapCheck(
            check_id="outdoor_devices_have_ip_ratings",
            passed=passed,
            details="Outdoor equipment IP ratings verified" if passed else f"Verify IP65+ rating for: {[e.model for e in unrated[:3]]}",
            severity="warning" if not passed else "ok",
        )

    def _check_dimmer_compatibility(self, equipment: list[EquipmentItem]) -> CoverageGapCheck:
        dimmers = [e for e in equipment if e.category == "Lighting" and "dimmer" in e.model.lower()]
        passed = True  # Flag for manual review when dimmers are present
        details = (
            f"{len(dimmers)} dimmer(s) specified — confirm all fixtures are dimmer-compatible LEDs before ordering"
            if dimmers else "No dimmers specified"
        )
        return CoverageGapCheck(
            check_id="all_fixtures_are_dimmer_compatible",
            passed=True,  # advisory only — cannot auto-verify without fixture list
            details=details,
            severity="warning",
        )


# ---------------------------------------------------------------------------
# Executive Summary Builder
# ---------------------------------------------------------------------------

class ExecutiveSummaryBuilder:
    """Generates client-facing executive summary prose."""

    TEMPLATE_SUMMARIES: dict[str, str] = {
        ProposalTemplate.BASIC_AV: (
            "The {client_name} residence will be equipped with a professionally "
            "designed audio-visual system that transforms every room into an "
            "entertainment destination. Symphony Smart Homes will deliver crystal-clear "
            "sound, stunning visuals, and an intuitive experience — all seamlessly "
            "integrated so that the technology disappears and the experience takes center stage.\n\n"
            "From immersive home theater to whole-home distributed audio, every system "
            "will be installed to the highest professional standard, calibrated for your "
            "specific space, and backed by Symphony's dedicated support team."
        ),
        ProposalTemplate.FULL_AUTOMATION: (
            "The {client_name} residence will become a fully unified smart home where "
            "a single touch — or a simple voice command — orchestrates the entire living "
            "experience. From the moment you arrive home to the moment you retire for the "
            "evening, Symphony Smart Homes will design a system that feels intuitive, "
            "sounds exceptional, and adapts to your daily life.\n\n"
            "Lighting scenes will shift as the day progresses. Motorized shades will "
            "protect your privacy and manage natural light without a second thought. "
            "Security cameras and smart locks will give you eyes on every corner of the "
            "property from anywhere in the world. And the music — everywhere, always, "
            "exactly how you want it.\n\n"
            "This proposal details a comprehensive smart home system engineered for "
            "reliability, scalability, and the kind of effortless living that makes "
            "you wonder how you ever lived without it."
        ),
        ProposalTemplate.RETROFIT: (
            "Upgrading an existing home's technology doesn't mean starting from scratch "
            "— it means doing more with what's already in place while adding the capabilities "
            "that make the biggest difference in daily life. Symphony Smart Homes has "
            "designed this retrofit proposal specifically for the {client_name} residence, "
            "building on your existing infrastructure and investments.\n\n"
            "We've identified the highest-impact improvements: smarter lighting control, "
            "a unified audio experience, and a network backbone that can support every "
            "connected device you have today — and every one you'll add tomorrow. "
            "Installation will be clean, minimally invasive, and completed with zero "
            "disruption to your household routine."
        ),
        ProposalTemplate.COMMERCIAL: (
            "This proposal outlines a professional AV and technology solution for "
            "{client_name}, designed to elevate productivity, communication, and the "
            "experience of everyone who uses the space.\n\n"
            "Symphony Smart Homes brings residential-grade attention to detail into "
            "the commercial environment: conference rooms that connect flawlessly, "
            "background music that sets the right tone, and digital displays that "
            "communicate your brand with clarity. Every system is designed for reliability "
            "during business hours and ease of management by your team."
        ),
        ProposalTemplate.MAINTENANCE: (
            "This service agreement ensures that the {client_name} smart home system "
            "continues to perform at its best, year after year. Symphony Smart Homes' "
            "maintenance plan includes proactive monitoring, priority response, and "
            "the peace of mind that comes from knowing your investment is protected.\n\n"
            "Our team will remotely monitor your system health, push firmware updates, "
            "and address issues before they affect your daily routine — often before you "
            "even notice them."
        ),
    }

    def build(self, requirements: ProjectRequirements) -> str:
        template_text = self.TEMPLATE_SUMMARIES.get(
            requirements.template,
            self.TEMPLATE_SUMMARIES[ProposalTemplate.FULL_AUTOMATION]
        )
        return template_text.format(
            client_name=requirements.client.name,
            room_count=len(requirements.rooms),
        )


# ---------------------------------------------------------------------------
# Standard Assumptions & Exclusions
# ---------------------------------------------------------------------------

STANDARD_ASSUMPTIONS: list[str] = [
    "All low-voltage cabling will be installed before drywall (new construction) or through existing wall cavities (retrofit).",
    "Client will provide access to the property during all installation phases.",
    "Electrical circuits for dedicated AV/control equipment are provided by the electrical contractor.",
    "Internet service with a minimum 100 Mbps symmetrical connection is available and active at commissioning.",
    "Final equipment list is subject to change pending product availability; substitutions will be of equal or greater specification.",
    "Structural blocking for TV mounts, speakers, and keypads is provided by the general contractor.",
    "All pricing is based on current distributor pricing and is valid for 30 days from proposal date.",
    "Access to attic, basement, or crawl space for cable routing is assumed unless otherwise noted.",
    "Programming scope assumes standard configurations; custom automation sequences are subject to change-order pricing.",
]

STANDARD_EXCLUSIONS: list[str] = [
    "Line-voltage electrical work (outlets, breaker panel, conduit) — by licensed electrician.",
    "Structural modifications, patching, or painting after cable installation.",
    "Internet service provider (ISP) subscription or modem/gateway supplied by ISP.",
    "Furniture, cabinetry, or millwork to accommodate equipment.",
    "Control4 or Lutron dealer licensing fees (included in Symphony Smart Homes account).",
    "Extended warranty beyond manufacturer standard (available as add-on).",
    "Equipment stored off-site; delivery coordination is client's responsibility if required.",
    "Third-party service integrations not explicitly listed in scope of work.",
]

STANDARD_TERMS_CONDITIONS: str = """
**Payment Schedule:** Per the attached payment schedule — deposit due at contract execution, 
milestone payments tied to project phases, balance due at commissioning.

**Change Orders:** Any scope changes after contract execution will be documented via written 
change order, signed by client, before work proceeds. Change orders may affect schedule.

**Warranty:** All equipment carries manufacturer's warranty. Symphony Smart Homes provides 
90-day labor warranty on all installed systems. Extended service plans available separately.

**Cancellation:** Cancellation after material ordering forfeits deposit and reimbursement 
of ordered equipment at cost.

**Access:** Client or authorized representative must be available for commissioning walkthrough. 
System acceptance sign-off required before final invoice.
""".strip()


# ---------------------------------------------------------------------------
# Proposal Engine
# ---------------------------------------------------------------------------

class ProposalEngine:
    """
    Main proposal generation engine for Symphony Smart Homes.

    Workflow:
        1. Load applicable room configs (Good/Better/Best per client tier)
        2. Load scope blocks for each system in scope
        3. Run coverage gap checks
        4. Build executive summary
        5. Assemble full proposal JSON
        6. Generate D-Tools CSV
    """

    def __init__(self, kb_root: Optional[Path] = None):
        self.kb = KnowledgeBaseLoader(kb_root)
        self.gap_checker = CoverageGapChecker()
        self.summary_builder = ExecutiveSummaryBuilder()
        logger.info("ProposalEngine initialized (KB: %s)", self.kb.kb_root)

    def generate(
        self,
        requirements: ProjectRequirements,
        base_equipment: Optional[list[EquipmentItem]] = None,
    ) -> Proposal:
        """
        Generate a complete proposal from client requirements.

        Args:
            requirements: Full project requirements including client, rooms, budget
            base_equipment: Optional pre-populated equipment list (e.g. from scope_builder)

        Returns:
            Proposal dataclass with all sections populated
        """
        proposal_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        project_name = f"{requirements.client.name} {'Residence' if requirements.template != ProposalTemplate.COMMERCIAL else 'Project'}"

        logger.info("Generating proposal %s for %s (template: %s, tier: %s)",
                    proposal_id, project_name, requirements.template, requirements.tier)

        # Step 1: Determine systems in scope
        systems = TEMPLATE_SYSTEMS.get(requirements.template, [])
        logger.debug("Systems in scope: %s", systems)

        # Step 2: Load room configs
        room_configs: dict[str, str] = {}
        for room in requirements.rooms:
            room_configs[room.name] = self.kb.load_room_config(room.name)
        logger.debug("Loaded %d room configs", len(room_configs))

        # Step 3: Load scope blocks
        scope_blocks: dict[str, str] = {}
        for system in systems:
            scope_blocks[system] = self.kb.load_scope_block(system)
        logger.debug("Loaded %d scope blocks", len(scope_blocks))

        # Step 4: Build scope sections
        scope_sections = self._build_scope_sections(systems, scope_blocks, requirements)

        # Step 5: Equipment list
        equipment = base_equipment or self._build_baseline_equipment(requirements, systems)

        # Step 6: Labor phases
        labor_phases = self._build_labor_phases(requirements, systems, equipment)

        # Step 7: Pricing summary (prices from D-Tools — not hardcoded)
        pricing = PricingSummary(
            equipment_subtotal=None,
            labor_total=None,
            programming_total=None,
            tax_total=None,
            project_total=None,
            markup_tier=self._select_markup_tier(requirements),
            notes="All equipment pricing sourced from D-Tools Cloud product catalog. "
                  "Labor and programming rates per current Symphony Smart Homes rate card.",
        )

        # Step 8: Coverage gap checks
        coverage_gaps = self.gap_checker.run_all_checks(equipment, requirements.rooms, systems)

        # Step 9: Executive summary
        exec_summary = self.summary_builder.build(requirements)

        # Step 10: Assumptions & exclusions
        assumptions = list(STANDARD_ASSUMPTIONS)
        exclusions = list(STANDARD_EXCLUSIONS)
        # Customize for retrofit
        if requirements.template == ProposalTemplate.RETROFIT:
            assumptions.append(
                f"Existing systems ({', '.join(requirements.existing_systems) or 'TBD'}) "
                "have been surveyed and are compatible with proposed upgrades."
            )
            exclusions.append("Removal and disposal of legacy equipment not listed in scope.")

        # Step 11: Optional upgrades placeholder
        optional_upgrades = self._suggest_upgrades(requirements, systems)

        # Step 12: Payment schedule
        payment_schedule = self._build_payment_schedule(requirements)

        proposal = Proposal(
            proposal_id=proposal_id,
            version=1,
            created_date=now,
            last_updated=now,
            template=requirements.template,
            client=requirements.client,
            project_name=project_name,
            executive_summary=exec_summary,
            scope_sections=scope_sections,
            equipment_list=equipment,
            labor_phases=labor_phases,
            pricing=pricing,
            assumptions=assumptions,
            exclusions=exclusions,
            optional_upgrades=optional_upgrades,
            payment_schedule=payment_schedule,
            terms_conditions=STANDARD_TERMS_CONDITIONS,
            coverage_gaps=coverage_gaps,
        )

        logger.info("Proposal %s generated successfully — %d scope sections, %d equipment items, %d gap checks",
                    proposal_id, len(scope_sections), len(equipment), len(coverage_gaps))
        return proposal

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _build_scope_sections(
        self,
        systems: list[str],
        scope_blocks: dict[str, str],
        requirements: ProjectRequirements,
    ) -> list[ScopeSection]:
        sections: list[ScopeSection] = []
        section_numbers = {
            "lighting_shades": "3.1",
            "audio_video": "3.2",
            "networking": "3.3",
            "security_surveillance": "3.4",
            "control_automation": "3.5",
            "climate": "3.6",
        }
        display_names = {
            "lighting_shades": "Lighting & Shading",
            "audio_video": "Audio / Video",
            "networking": "Networking & Infrastructure",
            "security_surveillance": "Security & Surveillance",
            "control_automation": "Control & Automation",
            "climate": "Climate Control",
        }
        for system in systems:
            block = scope_blocks.get(system, "")
            # Extract summary line (first non-heading paragraph)
            lines = [l.strip() for l in block.splitlines() if l.strip() and not l.startswith("#")]
            summary = lines[0] if lines else f"{display_names.get(system, system)} scope"
            # Extract bullet line items
            line_items = [l.lstrip("- ").strip() for l in block.splitlines() if l.strip().startswith("-")]
            num = section_numbers.get(system, "3.x")
            name = display_names.get(system, system.replace("_", " ").title())
            sections.append(ScopeSection(
                system_name=f"{num} {name}",
                summary=summary,
                line_items=line_items,
            ))
        return sections

    def _build_baseline_equipment(
        self,
        requirements: ProjectRequirements,
        systems: list[str],
    ) -> list[EquipmentItem]:
        """
        Build a baseline equipment list.
        Actual models/prices will be finalized in D-Tools — this provides
        the structural skeleton so the proposal has something to validate against.
        """
        equipment: list[EquipmentItem] = []

        # Always include network infrastructure
        if "networking" in systems:
            equipment.extend([
                EquipmentItem(model="Araknis 310 Series Router", manufacturer="Snap One", category="Networking",
                              quantity=1, room="Network Rack", notes="Gigabit router with advanced QoS"),
                EquipmentItem(model="Araknis 310 Series 24-Port Switch", manufacturer="Snap One", category="Networking",
                              quantity=1, room="Network Rack", notes="Managed PoE switch"),
                EquipmentItem(model="OvrC Pro Hub", manufacturer="Snap One", category="Networking",
                              quantity=1, room="Network Rack", notes="Remote monitoring and management"),
                EquipmentItem(model="Cat6 Cable (1000ft)", manufacturer="Generic", category="Cabling",
                              quantity=2, room="Structured Wiring", notes="Plenum-rated"),
                EquipmentItem(model="CyberPower UPS 1500VA", manufacturer="CyberPower", category="Power",
                              quantity=1, room="Network Rack", notes="UPS battery backup — non-negotiable"),
            ])

        # Add WAPs based on square footage
        sq_ft = requirements.square_footage or 3000
        wap_count = max(1, sq_ft // 1500)
        if "networking" in systems:
            equipment.append(
                EquipmentItem(model="Araknis 810 Series WAP", manufacturer="Snap One", category="Networking",
                              quantity=wap_count, room="Various",
                              notes=f"Wireless access points — 1 per ~1,500 sq ft ({wap_count} units)"),
            )

        # Control4 controller for automation
        if "control_automation" in systems:
            equipment.extend([
                EquipmentItem(model="Control4 CA-10 Controller", manufacturer="Control4", category="Control",
                              quantity=1, room="Network Rack", notes="Primary automation controller"),
                EquipmentItem(model="Control4 T4 Series Touchscreen", manufacturer="Control4", category="Control",
                              quantity=len(requirements.rooms), room="Various",
                              notes="In-wall touchscreen per room"),
            ])

        # Lutron for lighting
        if "lighting_shades" in systems:
            equipment.extend([
                EquipmentItem(model="Lutron RadioRA 3 Processor", manufacturer="Lutron", category="Lighting",
                              quantity=1, room="Network Rack", notes="Lighting control processor"),
                EquipmentItem(model="Lutron Caseta Dimmer", manufacturer="Lutron", category="Lighting",
                              quantity=len(requirements.rooms) * 2, room="Various",
                              notes="Estimate 2 dimmers per room — confirm with lighting plan"),
                EquipmentItem(model="Lutron Ketra Keypad", manufacturer="Lutron", category="Lighting",
                              quantity=len(requirements.rooms), room="Various",
                              notes="Scene control keypad per room"),
            ])

        # Audio per room
        if "audio_video" in systems:
            for room in requirements.rooms:
                if room.tier in (ClientTier.BETTER, ClientTier.BEST):
                    equipment.append(
                        EquipmentItem(model="Polk Audio 70-RT In-Ceiling Speaker", manufacturer="Polk Audio",
                                      category="Audio", quantity=2, room=room.name,
                                      notes="Stereo pair in-ceiling speakers")
                    )
            # Amplification
            speaker_rooms = [r for r in requirements.rooms if r.tier in (ClientTier.BETTER, ClientTier.BEST)]
            if speaker_rooms:
                equipment.append(
                    EquipmentItem(model="Autonomic MMS-2E", manufacturer="Autonomic", category="Audio",
                                  quantity=1, room="Network Rack",
                                  notes="Whole-home audio distribution — 2 streams, expandable")
                )

        # Labor
        base_labor_hours = 40 + len(requirements.rooms) * 4
        if "control_automation" in systems:
            base_labor_hours += 16  # programming time
        equipment.extend([
            EquipmentItem(model="Installation Labor", manufacturer="Symphony Smart Homes", category="Labor",
                          quantity=1, room="All Rooms",
                          notes=f"Estimated {base_labor_hours} hours — final per time-and-materials or fixed bid"),
            EquipmentItem(model="Programming Labor", manufacturer="Symphony Smart Homes", category="Labor",
                          quantity=1, room="Network Rack",
                          notes="Control4/Lutron programming and commissioning"),
        ])

        return equipment

    def _build_labor_phases(
        self,
        requirements: ProjectRequirements,
        systems: list[str],
        equipment: list[EquipmentItem],
    ) -> list[LaborPhase]:
        phases = []
        for phase_def in PROJECT_PHASES:
            # Skip prewire for retrofit projects
            if not requirements.is_new_construction and phase_def["phase"] == ProjectPhase.PREWIRE:
                continue
            phases.append(LaborPhase(
                phase=phase_def["phase"],
                description=phase_def["description"],
                estimated_days=phase_def["typical_days"],
            ))
        return phases

    def _select_markup_tier(self, requirements: ProjectRequirements) -> str:
        if requirements.template == ProposalTemplate.COMMERCIAL:
            return "commercial_standard"
        if requirements.tier == ClientTier.BEST:
            return "residential_premium"
        return "residential_standard"

    def _suggest_upgrades(
        self,
        requirements: ProjectRequirements,
        systems: list[str],
    ) -> list[dict]:
        upgrades = []
        if "lighting_shades" not in systems:
            upgrades.append({
                "name": "Lutron RadioRA 3 Lighting Control",
                "description": "Add whole-home lighting scenes with motorized shade integration",
                "estimated_add": "TBD — see D-Tools pricing",
            })
        if "security_surveillance" not in systems:
            upgrades.append({
                "name": "Surveillance Camera Package",
                "description": "4K exterior cameras with NVR and mobile app access",
                "estimated_add": "TBD — see D-Tools pricing",
            })
        if "climate" not in systems:
            upgrades.append({
                "name": "Smart Thermostat Integration",
                "description": "Ecobee or Nest integration with Control4 for automated climate schedules",
                "estimated_add": "TBD — see D-Tools pricing",
            })
        if requirements.tier != ClientTier.BEST:
            upgrades.append({
                "name": f"Upgrade to {ClientTier.BEST.value.title()} Tier",
                "description": "Premium equipment selection — reference-grade audio, 4K laser projectors, Lutron Ketra tunable white lighting",
                "estimated_add": "TBD — see D-Tools pricing",
            })
        return upgrades

    def _build_payment_schedule(self, requirements: ProjectRequirements) -> list[dict]:
        schedule = [
            {"milestone": "Contract Execution", "percentage": 33, "description": "Deposit — reserves project slot and authorizes equipment ordering"},
            {"milestone": "Equipment Delivery / Pre-Wire Complete", "percentage": 33, "description": "Mid-project milestone payment"},
            {"milestone": "System Commissioning & Client Acceptance", "percentage": 34, "description": "Final payment upon sign-off"},
        ]
        return schedule

    def to_json(self, proposal: Proposal, indent: int = 2) -> str:
        """Serialize a Proposal to JSON string."""
        def _serialize(obj):
            if hasattr(obj, '__dict__'):
                return asdict(obj) if hasattr(obj, '__dataclass_fields__') else obj.__dict__
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        raw = asdict(proposal)

        def _clean_enums(d):
            if isinstance(d, dict):
                return {k: _clean_enums(v) for k, v in d.items()}
            if isinstance(d, list):
                return [_clean_enums(i) for i in d]
            if isinstance(d, Enum):
                return d.value
            return d

        return json.dumps(_clean_enums(raw), indent=indent, default=str)

    def generate_dtools_csv(self, proposal: Proposal) -> str:
        """
        Generate a D-Tools compatible CSV for import into D-Tools Cloud.
        Columns match D-Tools Cloud import template.
        """
        import csv
        import io

        output = io.StringIO()
        fieldnames = [
            "Room", "Category", "Manufacturer", "Model", "Description",
            "Quantity", "Unit Price", "Extended Price", "Notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for item in proposal.equipment_list:
            writer.writerow({
                "Room": item.room,
                "Category": item.category,
                "Manufacturer": item.manufacturer,
                "Model": item.model,
                "Description": "",
                "Quantity": item.quantity,
                "Unit Price": item.unit_price if item.unit_price is not None else "",
                "Extended Price": item.extended_price if item.extended_price is not None else "",
                "Notes": item.notes,
            })

        return output.getvalue()


# ---------------------------------------------------------------------------
# CLI / Demo
# ---------------------------------------------------------------------------

def _demo_run():
    """Quick smoke-test: generate a sample full-automation proposal."""
    logging.basicConfig(level=logging.DEBUG)

    client = ClientInfo(
        name="Anderson",
        address="4521 Ridgeline Drive",
        city="Park City",
        state="UT",
        zip_code="84060",
        email="anderson@example.com",
        phone="435-555-0100",
    )

    rooms = [
        RoomRequirement("Great Room", tier=ClientTier.BEST, systems=["audio_video", "lighting_shades"]),
        RoomRequirement("Home Theater", tier=ClientTier.BEST, systems=["audio_video", "lighting_shades"]),
        RoomRequirement("Master Bedroom", tier=ClientTier.BETTER, systems=["audio_video", "lighting_shades"]),
        RoomRequirement("Kitchen", tier=ClientTier.BETTER, systems=["audio_video", "lighting_shades"]),
        RoomRequirement("Office", tier=ClientTier.GOOD, systems=["audio_video", "networking"]),
        RoomRequirement("Patio", tier=ClientTier.BETTER, systems=["audio_video"]),
    ]

    requirements = ProjectRequirements(
        client=client,
        template=ProposalTemplate.FULL_AUTOMATION,
        tier=ClientTier.BEST,
        rooms=rooms,
        budget_low=150_000,
        budget_high=200_000,
        is_new_construction=True,
        square_footage=6500,
        preferences=["Control4", "Lutron RadioRA 3", "Snap One networking"],
    )

    engine = ProposalEngine()
    proposal = engine.generate(requirements)

    print("\n" + "=" * 60)
    print(f"PROPOSAL: {proposal.project_name}")
    print(f"ID: {proposal.proposal_id}")
    print(f"Template: {proposal.template}")
    print(f"Scope sections: {len(proposal.scope_sections)}")
    print(f"Equipment items: {len(proposal.equipment_list)}")
    print(f"Coverage gaps: {len(proposal.coverage_gaps)} checks")
    passed = sum(1 for g in proposal.coverage_gaps if g.passed)
    print(f"  Passed: {passed}/{len(proposal.coverage_gaps)}")
    print("\nD-Tools CSV preview (first 10 rows):")
    csv_data = engine.generate_dtools_csv(proposal)
    proposal.dtools_csv = csv_data
    print("\n".join(csv_data.splitlines()[:min(11, csv_data.count(chr(10)))} rows):"))
    print(proposal.dtools_csv[:500])


if __name__ == "__main__":
    _demo_run()
