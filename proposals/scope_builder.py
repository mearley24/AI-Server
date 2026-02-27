#!/usr/bin/env python3
"""
scope_builder.py — Intelligent Scope of Work Builder

Generates room-by-room scope of work for Symphony Smart Homes proposals.
Cross-references the knowledge base, detects dependencies, suggests upsells,
and estimates labor hours per room type.

Usage:
    from scope_builder import ScopeBuilder
    builder = ScopeBuilder()
    scope = builder.build(rooms, tier=ClientTier.BETTER, systems=["lighting_shades", "audio_video"])
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class ClientTier(str, Enum):
    GOOD = "good"
    BETTER = "better"
    BEST = "best"


# Valid D-Tools categories (must match exactly)
VALID_CATEGORIES = {
    "Audio", "Video", "Lighting", "Networking", "Control",
    "Security", "Climate", "Power", "Cabling", "Rack", "Labor"
}

# Labor hours by room type and tier (base estimates — adjusted for scope)
ROOM_LABOR_HOURS: dict[str, dict[str, float]] = {
    "mechanical_room":    {"good": 8.0,  "better": 12.0, "best": 16.0},
    "living_great_room":  {"good": 6.0,  "better": 9.0,  "best": 14.0},
    "master_bedroom":     {"good": 5.0,  "better": 7.0,  "best": 10.0},
    "bedroom":            {"good": 3.0,  "better": 5.0,  "best": 7.0},
    "kitchen":            {"good": 3.0,  "better": 4.0,  "best": 6.0},
    "theater_media_room": {"good": 10.0, "better": 16.0, "best": 24.0},
    "office_study":       {"good": 4.0,  "better": 6.0,  "best": 8.0},
    "outdoor_patio":      {"good": 4.0,  "better": 7.0,  "best": 10.0},
    "entry_hallway":      {"good": 2.0,  "better": 3.0,  "best": 5.0},
    "dining_room":        {"good": 2.0,  "better": 3.0,  "best": 5.0},
    "bathroom":           {"good": 1.5,  "better": 2.0,  "best": 3.0},
    "garage":             {"good": 2.0,  "better": 3.0,  "best": 4.0},
    "laundry_mud_room":   {"good": 1.5,  "better": 2.0,  "best": 3.0},
    "default":            {"good": 3.0,  "better": 5.0,  "best": 7.0},
}

# Known dependencies: if system A is included, system B is required
SYSTEM_DEPENDENCIES: dict[str, list[dict]] = {
    "security_surveillance": [
        {
            "requires": "networking",
            "reason": "IP cameras require Ethernet drops and PoE switch",
            "items": ["Cat6 drops to all camera locations", "PoE-capable managed switch"],
        }
    ],
    "control_automation": [
        {
            "requires": "networking",
            "reason": "Control4 controller and devices communicate via IP",
            "items": ["Ethernet drop to Control4 controller location", "Managed network switch"],
        }
    ],
    "audio_video": [
        {
            "requires": "networking",
            "reason": "IP-based audio distribution (Triad, Sonos) requires network infrastructure",
            "items": ["Network drops to amplifier locations", "Managed switch for AV network segment"],
        }
    ],
    "climate": [
        {
            "requires": "control_automation",
            "reason": "HVAC integration is driven through Control4 drivers",
            "items": ["Control4 thermostat driver license", "IP or serial connection to HVAC system"],
        }
    ],
}

# Room-specific dependency rules
ROOM_DEPENDENCIES: dict[str, list[str]] = {
    "theater_media_room": [
        "Dedicated 20A circuit for AV equipment",
        "Blackout shades REQUIRED — projector performance depends on light control",
        "HDMI or HDBaseT cabling for video distribution",
        "Acoustic treatment not included — coordinate with GC or interior designer",
    ],
    "outdoor_patio": [
        "IP65 or higher rating required for all outdoor equipment",
        "Weatherproof conduit for cable protection — coordinate with electrician",
        "UV-resistant speaker wire for exposed outdoor runs",
    ],
    "mechanical_room": [
        "Dedicated 20A circuit for network rack UPS",
        "Climate control in rack room — 65–75°F operating range for equipment longevity",
        "UPS on network rack — non-negotiable",
    ],
}

# Upsell recommendations by tier
UPSELL_MATRIX: dict[str, list[dict]] = {
    "good": [
        {
            "system": "lighting_shades",
            "upgrade": "Add Lutron motorized shade integration",
            "value": "Scene-triggered shades transform AV and lighting experiences",
            "tier_target": "better",
        },
        {
            "system": "audio_video",
            "upgrade": "Upgrade to Triad multi-room amplification",
            "value": "Whole-home audio from a single app or Control4 interface",
            "tier_target": "better",
        },
    ],
    "better": [
        {
            "system": "security_surveillance",
            "upgrade": "Add Luma x30 4K cameras with license plate recognition",
            "value": "Enhanced detail at property entry points",
            "tier_target": "best",
        },
        {
            "system": "control_automation",
            "upgrade": "Control4 T4 10\" touchscreens in primary rooms",
            "value": "Premium UI experience and always-on room displays",
            "tier_target": "best",
        },
        {
            "system": "lighting_shades",
            "upgrade": "Lutron Palladiom keypads (brushed metal aesthetic)",
            "value": "Architectural-grade finish for high-design interiors",
            "tier_target": "best",
        },
    ],
    "best": [
        {
            "system": "audio_video",
            "upgrade": "Savant or Snap AV premium video matrix",
            "value": "4K/HDR video distribution to unlimited rooms with instant switching",
            "tier_target": "beyond_best",
        },
    ],
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RoomScopeItem:
    category: str                       # D-Tools category
    description: str                    # Human-readable scope line
    quantity: Optional[int] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: str = ""
    is_dependency: bool = False         # True if added to satisfy a dependency


@dataclass
class RoomScope:
    room_name: str
    tier: ClientTier
    systems: list[str]                  # systems active in this room
    scope_items: list[RoomScopeItem] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # flagged dependencies
    labor_hours: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class Dependency:
    source_system: str
    required_system: str
    reason: str
    required_items: list[str]


@dataclass
class UpsellSuggestion:
    current_tier: str
    system: str
    suggestion: str
    value_proposition: str
    target_tier: str


@dataclass
class ExclusionItem:
    category: str
    description: str
    note: str = ""


@dataclass
class ScopePackage:
    rooms: list[RoomScope]
    detected_dependencies: list[Dependency]
    upsell_suggestions: list[UpsellSuggestion]
    exclusions: list[ExclusionItem]
    assumptions: list[str]
    total_labor_hours: float
    total_rooms: int
    systems_in_scope: list[str]


# ---------------------------------------------------------------------------
# Scope Builder
# ---------------------------------------------------------------------------

class ScopeBuilder:
    """
    Generates detailed, room-by-room scope of work for Symphony Smart Homes proposals.

    Key capabilities:
    - Tier-aware scope generation (Good/Better/Best)
    - Automatic dependency detection (e.g., IP cameras → network drops)
    - Budget-based upsell suggestions
    - Labor hour estimation per room type
    - Standard exclusions and assumptions
    - Knowledge base integration for scope block text
    """

    def __init__(self, kb_root: Optional[Path] = None):
        self.kb_root = kb_root or Path.home() / "AI-Server" / "knowledge" / "proposal_library"
        self._scope_block_cache: dict[str, str] = {}
        self._room_config_cache: dict[str, str] = {}
        logger.info("ScopeBuilder initialized (KB: %s)", self.kb_root)

    def build(
        self,
        rooms: list[dict],
        tier: ClientTier,
        systems: list[str],
        budget: Optional[float] = None,
        preferences: Optional[list[str]] = None,
    ) -> ScopePackage:
        """
        Build a complete scope package for a project.

        Args:
            rooms: List of dicts with 'name', optional 'tier', optional 'systems', optional 'notes'
            tier: Default tier for all rooms (overridden by room-level tier)
            systems: Systems in scope for the project
            budget: Optional budget hint for upsell logic
            preferences: Optional client preference keywords

        Returns:
            ScopePackage with all rooms, dependencies, upsells, exclusions
        """
        logger.info("Building scope for %d rooms, tier=%s, systems=%s", len(rooms), tier.value, systems)

        # Step 1: Build room scopes
        room_scopes: list[RoomScope] = []
        for room_def in rooms:
            room_name = room_def.get("name", "Unknown Room")
            room_tier = ClientTier(room_def.get("tier", tier.value))
            room_systems = room_def.get("systems", systems)
            room_scope = self._build_room_scope(room_name, room_tier, room_systems)
            room_scopes.append(room_scope)

        # Step 2: Detect dependencies
        dependencies = self._detect_dependencies(systems)

        # Step 3: Inject dependency items into mechanical room / infrastructure
        room_scopes = self._inject_dependency_items(room_scopes, dependencies)

        # Step 4: Generate upsell suggestions
        upsells = self._generate_upsells(tier, systems, budget, preferences or [])

        # Step 5: Build exclusions
        exclusions = self._build_exclusions(systems)

        # Step 6: Build assumptions
        assumptions = self._build_assumptions(systems, rooms)

        # Step 7: Total labor
        total_hours = sum(r.labor_hours for r in room_scopes)

        package = ScopePackage(
            rooms=room_scopes,
            detected_dependencies=dependencies,
            upsell_suggestions=upsells,
            exclusions=exclusions,
            assumptions=assumptions,
            total_labor_hours=round(total_hours, 1),
            total_rooms=len(room_scopes),
            systems_in_scope=systems,
        )

        logger.info(
            "Scope built: %d rooms, %.1f labor hours, %d dependencies, %d upsells",
            len(room_scopes), total_hours, len(dependencies), len(upsells)
        )
        return package

    # ------------------------------------------------------------------
    # Room Scope Builder
    # ------------------------------------------------------------------

    def _build_room_scope(
        self,
        room_name: str,
        tier: ClientTier,
        systems: list[str],
    ) -> RoomScope:
        """Generate scope items for a single room."""
        scope_items: list[RoomScopeItem] = []
        room_key = self._normalize_room_key(room_name)

        # Load room config from knowledge base (if available)
        room_config = self._load_room_config(room_key)

        # Load room-specific dependency notes
        room_deps = ROOM_DEPENDENCIES.get(room_key, [])

        # Build scope items per system
        for system in systems:
            items = self._get_room_items_for_system(room_name, room_key, system, tier)
            scope_items.extend(items)

        # Calculate labor hours
        labor = self._estimate_labor(room_key, tier)

        return RoomScope(
            room_name=room_name,
            tier=tier,
            systems=systems,
            scope_items=scope_items,
            dependencies=room_deps,
            labor_hours=labor,
            notes=self._extract_room_notes(room_config) if room_config else [],
        )

    def _get_room_items_for_system(
        self,
        room_name: str,
        room_key: str,
        system: str,
        tier: ClientTier,
    ) -> list[RoomScopeItem]:
        """Return standard scope items for a system in a specific room."""
        items: list[RoomScopeItem] = []

        is_theater = "theater" in room_key or "media" in room_key
        is_outdoor = "outdoor" in room_key or "patio" in room_key
        is_entry = "entry" in room_key or "foyer" in room_key
        is_mechanical = "mechanical" in room_key
        is_master = "master" in room_key
        is_kitchen = "kitchen" in room_key
        is_garage = "garage" in room_key

        # ---- LIGHTING & SHADES ----
        if system == "lighting_shades":
            if is_mechanical:
                pass  # No lighting control in mechanical room
            elif is_theater:
                items += [
                    RoomScopeItem("Lighting", f"Lutron RadioRA 3 scene keypads — theater lighting zones",
                                  model="Lutron RRD-6ND-WH", manufacturer="Lutron",
                                  notes="Minimum: Entry, Dim, Blackout, House scenes"),
                    RoomScopeItem("Lighting",
                                  "Lutron motorized blackout shades — REQUIRED for all window/door openings",
                                  notes="Projector performance depends on complete light block"),
                ]
            elif is_outdoor:
                items.append(RoomScopeItem("Lighting",
                                           "Lutron RadioRA 3 outdoor-rated dimmers for landscape/patio lighting",
                                           model="Lutron RRD-6ND-WH", manufacturer="Lutron"))
            else:
                items.append(RoomScopeItem(
                    "Lighting",
                    f"Lutron RadioRA 3 dimmers — {'3 zones' if tier != ClientTier.GOOD else '2 zones'}",
                    model="Lutron RRD-6ND-WH", manufacturer="Lutron",
                    notes=f"{'Includes scene keypad' if tier != ClientTier.GOOD else 'App control only at Good tier'}",
                ))
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem(
                        "Lighting", "Motorized solar shade integration" if not is_master else "Motorized blackout shade",
                        notes="Programmed with lighting scenes for day/evening automation",
                    ))

        # ---- AUDIO / VIDEO ----
        elif system == "audio_video":
            if is_theater:
                items += [
                    RoomScopeItem("Audio", "In-ceiling front L/C/R speaker installation",
                                  quantity=3 if tier != ClientTier.GOOD else 2,
                                  model="Triad Bronze In-Ceiling 6.5\"", manufacturer="Triad"),
                    RoomScopeItem("Audio", "In-ceiling surround speaker installation",
                                  quantity=2, model="Triad Bronze In-Ceiling 6.5\"", manufacturer="Triad"),
                    RoomScopeItem("Video", "4K projector installation and calibration"
                                  if tier == ClientTier.BEST else "Large-format display installation"),
                    RoomScopeItem("Audio", "Subwoofer installation and placement",
                                  notes="In-wall or in-floor sub at Best tier"),
                ]
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem("Audio", "Atmos height speaker channels (2–4 overhead)",
                                               quantity=2, notes="Dolby Atmos height layer"))
            elif is_outdoor:
                items += [
                    RoomScopeItem("Audio", "Outdoor weatherproof speaker installation",
                                  quantity=2, notes="IP65 rated; landscape-grade mounting"),
                ]
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem("Video", "Outdoor weatherproof display installation",
                                               model="SunBrite SB-V-55-XT4K-BL",
                                               manufacturer="SunBrite",
                                               notes="Veranda series — direct sun rated"))
            elif is_garage:
                items.append(RoomScopeItem("Audio", "Surface-mount or in-ceiling speaker installation",
                                           quantity=2, notes="Standard audio zone"))
            elif is_mechanical:
                pass  # Mechanical room handles amplification, not listening
            else:
                items.append(RoomScopeItem(
                    "Audio",
                    "In-ceiling speaker installation" + (" — stereo pair" if tier != ClientTier.BEST else " — premium pair"),
                    quantity=2,
                    model="Triad Bronze In-Ceiling 6.5\"" if tier != ClientTier.BEST else "Triad Silver In-Ceiling 6.5\"",
                    manufacturer="Triad",
                ))
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem(
                        "Video",
                        "Display mount and installation" + (" with cable concealment" if tier == ClientTier.BEST else ""),
                        notes="TV/display supplied by client or separate line item",
                    ))

        # ---- NETWORKING ----
        elif system == "networking":
            if is_mechanical:
                items += [
                    RoomScopeItem("Networking", "Araknis managed router installation",
                                  model="AN-310-RT", manufacturer="Araknis",
                                  notes="Managed router with QoS for AV/IoT prioritization"),
                    RoomScopeItem("Networking", "Araknis managed PoE switch installation",
                                  model="AN-310-SW-8-2P", manufacturer="Araknis",
                                  notes="PoE for cameras, Control4 devices, WAPs"),
                    RoomScopeItem("Networking", "OvrC Pro cloud management enrollment",
                                  notes="Remote monitoring and reboot — mandatory on every project"),
                ]
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem("Networking", "Additional PoE switch for expanded device count",
                                               model="AN-310-SW-8-2P", manufacturer="Araknis",
                                               notes="Second switch for AV equipment isolation"))
            elif is_outdoor:
                items.append(RoomScopeItem("Networking", "Outdoor wireless access point installation",
                                           model="AN-710-AP-O", manufacturer="Araknis",
                                           notes="Weatherproof WAP — extends indoor network coverage outdoors"))
            else:
                # Standard rooms get a WAP and drops counted in cabling
                items.append(RoomScopeItem("Networking", "Wireless coverage verified — indoor WAP deployment",
                                           notes="1 Araknis WAP per 1,500 sq ft per floor"))

        # ---- SECURITY / SURVEILLANCE ----
        elif system == "security_surveillance":
            if is_entry or is_garage or is_outdoor:
                items += [
                    RoomScopeItem("Security", "Luma IP camera installation",
                                  model="Luma x20 4MP Dome",
                                  manufacturer="Luma",
                                  notes="PoE — IP65 rated for exterior locations"),
                ]
                if is_entry and tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem("Security", "DoorBird IP video door station installation",
                                               model="DoorBird D2101V",
                                               manufacturer="DoorBird",
                                               notes="Control4 driver included — 2-way video intercom"))
            elif is_mechanical:
                items.append(RoomScopeItem("Security", "Luma NVR installation with storage",
                                           model="Luma NVR-16",
                                           manufacturer="Luma",
                                           notes="16-channel NVR, 4TB — 30-day retention at 1080p"))

        # ---- CONTROL & AUTOMATION ----
        elif system == "control_automation":
            if is_mechanical:
                items += [
                    RoomScopeItem("Control", "Control4 CORE 3 home controller installation",
                                  model="Control4 CORE 3",
                                  manufacturer="Control4",
                                  notes="Primary controller — rack-mount"),
                ]
            elif is_entry or room_key in ("living_great_room", "master_bedroom"):
                items.append(RoomScopeItem(
                    "Control",
                    "Control4 touchscreen installation" if tier == ClientTier.BEST else "Control4 keypad installation",
                    model="Control4 T4 Series 7\" Touchscreen" if tier == ClientTier.BEST else "Control4 SR-260 Remote",
                    manufacturer="Control4",
                    notes="Primary user interface for room scenes and AV control",
                ))
            else:
                if tier in (ClientTier.BETTER, ClientTier.BEST):
                    items.append(RoomScopeItem("Control", "Control4 SR-260 wireless remote",
                                               model="Control4 SR-260",
                                               manufacturer="Control4",
                                               notes="Handheld AV remote for this room"))

        # ---- CLIMATE ----
        elif system == "climate":
            if "bedroom" in room_key or room_key in ("living_great_room", "office_study"):
                items.append(RoomScopeItem(
                    "Climate", "Thermostat integration via Control4 driver",
                    notes="Schedule and scene-based temperature control; existing thermostat must be IP or serial capable",
                ))

        return items

    # ------------------------------------------------------------------
    # Dependency Detection
    # ------------------------------------------------------------------

    def _detect_dependencies(self, systems: list[str]) -> list[Dependency]:
        """Detect required system dependencies based on what's in scope."""
        deps: list[Dependency] = []
        systems_set = set(systems)

        for system, requirements in SYSTEM_DEPENDENCIES.items():
            if system in systems_set:
                for req in requirements:
                    required = req["requires"]
                    if required not in systems_set:
                        deps.append(Dependency(
                            source_system=system,
                            required_system=required,
                            reason=req["reason"],
                            required_items=req["items"],
                        ))
                        logger.info(
                            "Dependency detected: %s requires %s — %s",
                            system, required, req["reason"]
                        )

        return deps

    def _inject_dependency_items(
        self,
        room_scopes: list[RoomScope],
        dependencies: list[Dependency],
    ) -> list[RoomScope]:
        """Add dependency-required items to the mechanical room scope."""
        if not dependencies:
            return room_scopes

        # Find the mechanical room or infrastructure room
        mech_room = next(
            (r for r in room_scopes if "mechanical" in r.room_name.lower()),
            None
        )

        if not mech_room:
            # If no mechanical room, create a note on the first room
            logger.warning("No mechanical room found — dependency items need manual placement")
            return room_scopes

        for dep in dependencies:
            dep_note = f"[AUTO-DETECTED] {dep.source_system} requires {dep.required_system}: {dep.reason}"
            mech_room.dependencies.append(dep_note)

            for item_desc in dep.required_items:
                mech_room.scope_items.append(RoomScopeItem(
                    category="Networking" if dep.required_system == "networking" else "Control",
                    description=item_desc,
                    is_dependency=True,
                    notes=f"Required by: {dep.source_system}",
                ))

        return room_scopes

    # ------------------------------------------------------------------
    # Upsell Suggestions
    # ------------------------------------------------------------------

    def _generate_upsells(
        self,
        tier: ClientTier,
        systems: list[str],
        budget: Optional[float],
        preferences: list[str],
    ) -> list[UpsellSuggestion]:
        """Generate upsell recommendations based on tier and systems."""
        suggestions: list[UpsellSuggestion] = []
        tier_matrix = UPSELL_MATRIX.get(tier.value, [])

        for upsell in tier_matrix:
            # Only suggest upsells for systems in scope or missing adjacent systems
            if upsell["system"] in systems or (
                budget and budget > 50_000  # higher budget = suggest adjacent systems
            ):
                suggestions.append(UpsellSuggestion(
                    current_tier=tier.value,
                    system=upsell["system"],
                    suggestion=upsell["upgrade"],
                    value_proposition=upsell["value"],
                    target_tier=upsell["tier_target"],
                ))

        # Budget-aware: suggest missing systems
        if "security_surveillance" not in systems and budget and budget > 40_000:
            suggestions.append(UpsellSuggestion(
                current_tier=tier.value,
                system="security_surveillance",
                suggestion="Add Luma IP camera system (4–8 cameras + NVR)",
                value_proposition="Remote monitoring, package theft deterrence, integration with DoorBird and smart locks",
                target_tier="better",
            ))

        if "lighting_shades" not in systems:
            suggestions.append(UpsellSuggestion(
                current_tier=tier.value,
                system="lighting_shades",
                suggestion="Add Lutron RadioRA 3 lighting control and motorized shades",
                value_proposition="The single highest-impact upgrade in a smart home — transforms every room scene",
                target_tier="better",
            ))

        return suggestions

    # ------------------------------------------------------------------
    # Exclusions & Assumptions
    # ------------------------------------------------------------------

    def _build_exclusions(self, systems: list[str]) -> list[ExclusionItem]:
        """Generate standard exclusions list, with system-specific additions."""
        exclusions: list[ExclusionItem] = [
            ExclusionItem("Electrical", "Line-voltage electrical work (outlets, circuits, breaker panel)"),
            ExclusionItem("Construction", "Structural modifications, patching, painting, or carpentry"),
            ExclusionItem("Networking", "ISP modem/gateway or internet service subscription"),
            ExclusionItem("Furniture", "Furniture, cabinetry, or custom millwork for equipment placement"),
            ExclusionItem("Software", "Extended manufacturer warranties beyond standard included coverage"),
            ExclusionItem("Programming", "Third-party integration drivers not explicitly listed in scope"),
        ]

        if "audio_video" in systems:
            exclusions.append(ExclusionItem(
                "Video",
                "Client-supplied televisions and displays (unless explicitly listed as Symphony-supplied)",
                note="Display procurement is client responsibility unless in scope",
            ))

        if "security_surveillance" in systems:
            exclusions.append(ExclusionItem(
                "Security",
                "Professional monitoring subscription (third-party service — not included)",
                note="System supports self-monitoring via mobile app",
            ))

        if "control_automation" in systems:
            exclusions.append(ExclusionItem(
                "Programming",
                "Custom macro programming beyond standard scene-based automation",
                note="Change orders required for complex multi-system sequences",
            ))

        return exclusions

    def _build_assumptions(self, systems: list[str], rooms: list[dict]) -> list[str]:
        """Generate standard and system-specific assumptions."""
        assumptions = [
            "All low-voltage cabling installed during pre-wire phase before drywall.",
            "Client-supplied internet service with minimum 100 Mbps symmetrical available at commissioning.",
            "Electrical contractor provides dedicated circuits for AV equipment as specified.",
            "Structural blocking for TV mounts, speaker locations, and keypads is by the general contractor.",
            "Final equipment quantities subject to change pending site measurement and room count confirmation.",
            "All pricing valid for 30 days from proposal date; subject to distributor price changes.",
        ]

        room_names = [r.get("name", "") for r in rooms]
        has_theater = any("theater" in n.lower() or "media" in n.lower() for n in room_names)
        has_outdoor = any("outdoor" in n.lower() or "patio" in n.lower() for n in room_names)

        if has_theater:
            assumptions.append("Theater room has dedicated 20A circuit and HVAC; acoustic treatment by others.")
            assumptions.append("Projector screen and acoustic panels are not in scope unless explicitly listed.")

        if has_outdoor:
            assumptions.append("Outdoor conduit and weatherproof electrical boxes are by licensed electrician.")

        if "control_automation" in systems:
            assumptions.append(
                "Control4 programming scope covers standard scenes, AV routing, and lighting presets. "
                "Custom sequences are change-order items."
            )

        if "networking" in systems:
            assumptions.append(
                "ISP will provide a modem/gateway device. Symphony Smart Homes installs behind ISP gateway."
            )

        return assumptions

    # ------------------------------------------------------------------
    # Knowledge Base Helpers
    # ------------------------------------------------------------------

    def _load_room_config(self, room_key: str) -> Optional[str]:
        """Load room config markdown from KB (graceful degradation if missing)."""
        if room_key in self._room_config_cache:
            return self._room_config_cache[room_key]

        path = self.kb_root / "room_configs" / f"{room_key}.md"
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        self._room_config_cache[room_key] = content
        return content

    def _load_scope_block(self, system: str) -> Optional[str]:
        """Load scope block markdown from KB."""
        if system in self._scope_block_cache:
            return self._scope_block_cache[system]

        path = self.kb_root / "scope_blocks" / f"{system}.md"
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        self._scope_block_cache[system] = content
        return content

    def _extract_room_notes(self, room_config: str) -> list[str]:
        """Extract bullet-point notes from a room config markdown."""
        lines = room_config.splitlines()
        notes = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                notes.append(stripped[2:].strip())
        return notes[:5]  # Cap at 5 notes per room

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _normalize_room_key(self, room_name: str) -> str:
        """Normalize room name to a snake_case key matching KB filenames."""
        key = room_name.lower().strip()
        # Normalize common variants
        key = key.replace(" room", "").replace("/", "_").replace(" ", "_")
        key = key.replace("-", "_")

        # Map common names to canonical keys
        mapping = {
            "great_room": "living_great_room",
            "living": "living_great_room",
            "living_great": "living_great_room",
            "theater": "theater_media_room",
            "media": "theater_media_room",
            "home_theater": "theater_media_room",
            "master": "master_bedroom",
            "master_bed": "master_bedroom",
            "primary_bedroom": "master_bedroom",
            "office": "office_study",
            "study": "office_study",
            "patio": "outdoor_patio",
            "outdoor": "outdoor_patio",
            "exterior": "outdoor_patio",
            "entry": "entry_hallway",
            "foyer": "entry_hallway",
            "hallway": "entry_hallway",
            "dining": "dining_room",
            "mechanical": "mechanical_room",
            "utility": "mechanical_room",
            "laundry": "laundry_mud_room",
            "mud": "laundry_mud_room",
        }

        return mapping.get(key, key)

    def _estimate_labor(self, room_key: str, tier: ClientTier) -> float:
        """Estimate labor hours for a room at the given tier."""
        hours_map = ROOM_LABOR_HOURS.get(room_key, ROOM_LABOR_HOURS["default"])
        return hours_map.get(tier.value, hours_map.get("better", 5.0))


# ---------------------------------------------------------------------------
# CLI / Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    builder = ScopeBuilder()

    rooms = [
        {"name": "Mechanical Room", "tier": "best"},
        {"name": "Great Room",       "tier": "best"},
        {"name": "Home Theater",     "tier": "best"},
        {"name": "Master Bedroom",   "tier": "better"},
        {"name": "Kitchen",          "tier": "better"},
        {"name": "Office",           "tier": "good"},
        {"name": "Patio",            "tier": "better"},
        {"name": "Entry",            "tier": "better"},
    ]

    systems = [
        "lighting_shades", "audio_video", "networking",
        "security_surveillance", "control_automation", "climate",
    ]

    scope = builder.build(
        rooms=rooms,
        tier=ClientTier.BETTER,
        systems=systems,
        budget=175_000,
        preferences=["Control4", "Lutron"],
    )

    print(f"\n{'='*60}")
    print(f"SCOPE PACKAGE: {scope.total_rooms} rooms, {scope.total_labor_hours}h labor")
    print(f"Systems: {', '.join(scope.systems_in_scope)}")
    print(f"Dependencies detected: {len(scope.detected_dependencies)}")
    print(f"Upsell suggestions: {len(scope.upsell_suggestions)}")
    print(f"Exclusions: {len(scope.exclusions)}")

    for room in scope.rooms:
        print(f"\n  {room.room_name} [{room.tier.value}]: {len(room.scope_items)} items, {room.labor_hours}h")


if __name__ == "__main__":
    _demo()
