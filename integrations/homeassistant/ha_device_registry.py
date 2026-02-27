"""
ha_device_registry.py — Symphony Smart Homes
Device Registry for Bob the Conductor

Auto-discovers all Home Assistant entities and categorizes them by vendor:
- Control4 controllers and drivers
- Lutron switches, dimmers, and shades
- Araknis network devices
- Sonos speakers and groups
- Luma cameras and NVR
- Generic HA devices (lights, sensors, climate, etc.)

Maintains a local cached tree of the device topology, maps entity_ids to
friendly names and room locations, and can generate a system topology report.

Usage:
    registry = DeviceRegistry(ha_client)
    await registry.refresh()
    control4_devices = registry.get_by_vendor("control4")
    report = registry.generate_topology_report()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("symphony.ha_device_registry")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTRY_CACHE_FILE = "./cache/device_registry.json"
REGISTRY_REFRESH_INTERVAL = 300     # seconds between auto-refresh
CACHE_MAX_AGE = 600                 # seconds before cache is considered stale


# ---------------------------------------------------------------------------
# Vendor detection rules
# ---------------------------------------------------------------------------
# Maps vendor name → list of (field, match_strings) patterns
# 'field' is one of: entity_id, integration, model, manufacturer, friendly_name

VENDOR_SIGNATURES = {
    "control4": {
        "entity_id_prefixes": [],
        "integration_ids": ["control4"],
        "model_keywords": ["control4", "c4-"],
        "manufacturer_keywords": ["control4"],
        "entity_id_keywords": ["control4", "c4_"],
        "friendly_name_keywords": ["control4"],
    },
    "lutron": {
        "entity_id_prefixes": [],
        "integration_ids": ["lutron_caseta", "lutron"],
        "model_keywords": ["lutron", "caseta", "ra2", "ra3", "homeworks"],
        "manufacturer_keywords": ["lutron"],
        "entity_id_keywords": ["lutron", "caseta", "pico"],
        "friendly_name_keywords": ["lutron"],
    },
    "sonos": {
        "entity_id_prefixes": ["media_player.sonos"],
        "integration_ids": ["sonos"],
        "model_keywords": ["sonos"],
        "manufacturer_keywords": ["sonos"],
        "entity_id_keywords": ["sonos"],
        "friendly_name_keywords": ["sonos"],
    },
    "luma": {
        "entity_id_prefixes": ["camera.luma"],
        "integration_ids": ["luma"],
        "model_keywords": ["luma"],
        "manufacturer_keywords": ["luma"],
        "entity_id_keywords": ["luma"],
        "friendly_name_keywords": ["luma"],
    },
    "araknis": {
        "entity_id_prefixes": [],
        "integration_ids": ["araknis"],
        "model_keywords": ["araknis", "an-"],
        "manufacturer_keywords": ["araknis"],
        "entity_id_keywords": ["araknis"],
        "friendly_name_keywords": ["araknis"],
    },
    "snap_one": {
        "entity_id_prefixes": [],
        "integration_ids": ["snapone", "snap_one"],
        "model_keywords": ["snap one", "triad", "snapav"],
        "manufacturer_keywords": ["snap one", "triad", "snapav"],
        "entity_id_keywords": ["snapone", "snap_one", "triad"],
        "friendly_name_keywords": ["snap one", "triad"],
    },
}

# Room/location keywords for entity placement
ROOM_KEYWORDS = {
    "living_room": ["living", "lounge", "family", "great_room"],
    "kitchen": ["kitchen", "dinette", "breakfast"],
    "dining_room": ["dining"],
    "master_bedroom": ["master", "primary_bedroom", "master_bed"],
    "bedroom": ["bedroom", "bed_", "_bed"],
    "bathroom": ["bath", "powder", "restroom"],
    "office": ["office", "study", "den"],
    "garage": ["garage"],
    "basement": ["basement", "lower_level"],
    "backyard": ["backyard", "back_yard", "patio", "pool", "outdoor_back"],
    "front_yard": ["front_yard", "driveway", "entry", "front_door"],
    "hallway": ["hall", "corridor", "foyer", "entryway"],
    "media_room": ["media", "theater", "theatre", "home_theater"],
    "utility": ["utility", "laundry", "mechanical"],
    "attic": ["attic"],
    "outdoors": ["outdoor", "exterior", "yard", "garden"],
}

DOMAIN_CATEGORIES = {
    "light": "lighting",
    "switch": "switches",
    "cover": "shades_blinds",
    "climate": "hvac",
    "media_player": "audio_video",
    "camera": "cameras",
    "binary_sensor": "sensors",
    "sensor": "sensors",
    "lock": "security",
    "alarm_control_panel": "security",
    "person": "presence",
    "device_tracker": "presence",
    "scene": "scenes",
    "script": "scripts",
    "automation": "automations",
    "input_boolean": "helpers",
    "input_select": "helpers",
    "input_number": "helpers",
    "timer": "helpers",
    "counter": "helpers",
    "button": "controls",
    "number": "controls",
    "select": "controls",
    "weather": "environment",
    "sun": "environment",
    "zone": "zones",
    "update": "system",
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class DeviceEntry:
    entity_id: str
    friendly_name: str
    domain: str
    state: str
    vendor: str
    category: str
    room: Optional[str]
    attributes: dict = field(default_factory=dict)
    integration: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    area_id: Optional[str] = None
    area_name: Optional[str] = None
    device_id: Optional[str] = None
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "friendly_name": self.friendly_name,
            "domain": self.domain,
            "state": self.state,
            "vendor": self.vendor,
            "category": self.category,
            "room": self.room,
            "integration": self.integration,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "area_name": self.area_name,
        }


# ---------------------------------------------------------------------------
# Device Registry
# ---------------------------------------------------------------------------

class DeviceRegistry:
    """
    Maintains a vendor-aware catalog of all HA entities for Bob's agents.

    The registry auto-discovers and categorizes every entity by vendor,
    room, and function. It can generate a full topology report showing
    the smart home system structure.
    """

    def __init__(
        self,
        ha_client,
        cache_file: str = REGISTRY_CACHE_FILE,
        refresh_interval: float = REGISTRY_REFRESH_INTERVAL,
    ):
        self._ha = ha_client
        self._cache_file = Path(cache_file)
        self._refresh_interval = refresh_interval
        self._devices: Dict[str, DeviceEntry] = {}
        self._areas: Dict[str, str] = {}           # area_id → area_name
        self._last_refresh: float = 0.0
        self._refresh_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, auto_refresh: bool = True):
        """
        Start the device registry.
        Loads from cache if available, then fetches fresh data.
        """
        self._running = True
        # Try loading from cache first for fast startup
        self._load_cache()
        # Always do a fresh refresh on start
        await self.refresh()
        if auto_refresh:
            self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info(f"Device registry started: {len(self._devices)} entities catalogued")

    async def stop(self):
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()

    # ------------------------------------------------------------------
    # Core refresh
    # ------------------------------------------------------------------

    async def refresh(self):
        """
        Fetch all entity states from HA and rebuild the device catalog.
        Also fetches area/floor registry if available.
        """
        logger.info("Refreshing device registry...")
        try:
            # Fetch entity states
            states = await self._ha.get_states()

            # Try to get area registry
            await self._fetch_areas()

            # Rebuild device map
            new_devices: Dict[str, DeviceEntry] = {}
            for state in states:
                entry = self._build_entry(state)
                new_devices[entry.entity_id] = entry

            self._devices = new_devices
            self._last_refresh = time.time()
            self._save_cache()
            logger.info(f"Registry refreshed: {len(self._devices)} entities")

        except Exception as exc:
            logger.error(f"Registry refresh failed: {exc}")
            raise

    async def _fetch_areas(self):
        """Fetch area (room) assignments from HA."""
        try:
            # HA doesn't expose area registry via REST directly, but we can
            # infer from entity attributes or use HA's config/area endpoint
            result = await self._ha._post("/api/config/area_registry/list")
            if isinstance(result, list):
                self._areas = {a["area_id"]: a["name"] for a in result}
                logger.debug(f"Loaded {len(self._areas)} HA areas")
        except Exception:
            # Area registry not available via this endpoint; use keyword inference
            pass

    # ------------------------------------------------------------------
    # Entry building
    # ------------------------------------------------------------------

    def _build_entry(self, state) -> DeviceEntry:
        """Build a DeviceEntry from an HAState object."""
        entity_id = state.entity_id
        attrs = state.attributes
        domain = entity_id.split(".")[0]
        friendly_name = attrs.get("friendly_name", entity_id)

        vendor = self._detect_vendor(entity_id, attrs)
        category = DOMAIN_CATEGORIES.get(domain, "other")
        room = self._detect_room(entity_id, friendly_name, attrs)

        # Get area name from HA area registry
        area_id = attrs.get("area_id")
        area_name = self._areas.get(area_id) if area_id else None
        if area_name and not room:
            room = area_name

        return DeviceEntry(
            entity_id=entity_id,
            friendly_name=friendly_name,
            domain=domain,
            state=state.state,
            vendor=vendor,
            category=category,
            room=room,
            attributes=attrs,
            integration=attrs.get("integration"),
            model=attrs.get("model"),
            manufacturer=attrs.get("manufacturer"),
            area_id=area_id,
            area_name=area_name,
            device_id=attrs.get("device_id"),
        )

    # ------------------------------------------------------------------
    # Vendor detection
    # ------------------------------------------------------------------

    def _detect_vendor(self, entity_id: str, attrs: dict) -> str:
        """Classify an entity's vendor based on entity_id, attributes, and integration."""
        entity_lower = entity_id.lower()
        integration = str(attrs.get("integration", "")).lower()
        model = str(attrs.get("model", "")).lower()
        manufacturer = str(attrs.get("manufacturer", "")).lower()
        friendly = str(attrs.get("friendly_name", "")).lower()

        for vendor, rules in VENDOR_SIGNATURES.items():
            # Check entity_id prefixes
            for prefix in rules.get("entity_id_prefixes", []):
                if entity_lower.startswith(prefix):
                    return vendor
            # Check integration IDs
            for intg in rules.get("integration_ids", []):
                if intg in integration:
                    return vendor
            # Check model keywords
            for kw in rules.get("model_keywords", []):
                if kw in model:
                    return vendor
            # Check manufacturer keywords
            for kw in rules.get("manufacturer_keywords", []):
                if kw in manufacturer:
                    return vendor
            # Check entity_id keywords
            for kw in rules.get("entity_id_keywords", []):
                if kw in entity_lower:
                    return vendor
            # Check friendly name keywords
            for kw in rules.get("friendly_name_keywords", []):
                if kw in friendly:
                    return vendor

        return "home_assistant"

    # ------------------------------------------------------------------
    # Room detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_room(entity_id: str, friendly_name: str, attrs: dict) -> Optional[str]:
        """Infer the room/location from entity_id, name, and attributes."""
        combined = (entity_id + " " + friendly_name).lower().replace("-", "_")

        # Check area from attributes first
        area = attrs.get("area", attrs.get("room", ""))
        if area:
            return area.title()

        # Keyword scan — most specific first
        for room, keywords in ROOM_KEYWORDS.items():
            for kw in keywords:
                if kw in combined:
                    return room.replace("_", " ").title()
        return None

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_all(self) -> List[DeviceEntry]:
        """Return all known device entries."""
        return list(self._devices.values())

    def get(self, entity_id: str) -> Optional[DeviceEntry]:
        """Get a specific device entry by entity_id."""
        return self._devices.get(entity_id)

    def get_by_vendor(self, vendor: str) -> List[DeviceEntry]:
        """Get all devices for a specific vendor."""
        return [d for d in self._devices.values() if d.vendor == vendor]

    def get_by_domain(self, domain: str) -> List[DeviceEntry]:
        """Get all entities of a specific domain (light, switch, camera, etc.)."""
        return [d for d in self._devices.values() if d.domain == domain]

    def get_by_room(self, room: str) -> List[DeviceEntry]:
        """Get all entities in a specific room (case-insensitive)."""
        room_lower = room.lower()
        return [
            d for d in self._devices.values()
            if d.room and d.room.lower() == room_lower
        ]

    def get_by_category(self, category: str) -> List[DeviceEntry]:
        """Get all entities of a functional category (lighting, cameras, security, etc.)."""
        return [d for d in self._devices.values() if d.category == category]

    def search(self, query: str) -> List[DeviceEntry]:
        """Full-text search across entity_id, friendly_name, room, and vendor."""
        q = query.lower()
        return [
            d for d in self._devices.values()
            if q in d.entity_id.lower()
            or q in d.friendly_name.lower()
            or (d.room and q in d.room.lower())
            or q in d.vendor.lower()
        ]

    def get_cameras(self) -> List[DeviceEntry]:
        """Get all camera entities."""
        return self.get_by_domain("camera")

    def get_lights(self, room: Optional[str] = None) -> List[DeviceEntry]:
        """Get all lights, optionally filtered by room."""
        lights = self.get_by_domain("light")
        if room:
            lights = [l for l in lights if l.room and l.room.lower() == room.lower()]
        return lights

    def get_locks(self) -> List[DeviceEntry]:
        """Get all lock entities."""
        return self.get_by_domain("lock")

    def get_sonos_players(self) -> List[DeviceEntry]:
        """Get all Sonos media player entities."""
        return [d for d in self._devices.values() if d.vendor == "sonos"]

    def get_control4_devices(self) -> List[DeviceEntry]:
        """Get all Control4 devices."""
        return self.get_by_vendor("control4")

    def get_lutron_devices(self) -> List[DeviceEntry]:
        """Get all Lutron devices."""
        return self.get_by_vendor("lutron")

    def get_online_devices(self) -> List[DeviceEntry]:
        """Get all devices that are NOT in unavailable/unknown state."""
        return [d for d in self._devices.values() if d.state not in ("unavailable", "unknown")]

    def get_offline_devices(self) -> List[DeviceEntry]:
        """Get all devices in unavailable state."""
        return [d for d in self._devices.values() if d.state == "unavailable"]

    # ------------------------------------------------------------------
    # Topology report
    # ------------------------------------------------------------------

    def generate_topology_report(self) -> dict:
        """
        Generate a comprehensive system topology report showing the full
        smart home device tree organized by vendor and room.

        Returns:
            Dict suitable for JSON export or Bob's system awareness.
        """
        devices = list(self._devices.values())

        # --- By vendor ---
        by_vendor: Dict[str, List[dict]] = {}
        for d in devices:
            by_vendor.setdefault(d.vendor, []).append(d.to_dict())

        # --- By room ---
        by_room: Dict[str, List[dict]] = {}
        for d in devices:
            room_key = d.room or "Unassigned"
            by_room.setdefault(room_key, []).append(d.to_dict())

        # --- By category ---
        by_category: Dict[str, List[dict]] = {}
        for d in devices:
            by_category.setdefault(d.category, []).append(d.to_dict())

        # --- Summary stats ---
        vendors = set(d.vendor for d in devices)
        rooms = set(d.room for d in devices if d.room)
        offline = [d for d in devices if d.state == "unavailable"]

        vendor_counts = {v: len(by_vendor[v]) for v in sorted(vendors)}
        room_counts = {r: len(by_room[r]) for r in sorted(rooms)}

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_entities": len(devices),
                "total_vendors": len(vendors),
                "total_rooms": len(rooms),
                "offline_count": len(offline),
                "vendor_counts": vendor_counts,
                "room_counts": room_counts,
            },
            "by_vendor": {
                vendor: {
                    "count": len(entries),
                    "devices": entries,
                }
                for vendor, entries in sorted(by_vendor.items())
            },
            "by_room": {
                room: {
                    "count": len(entries),
                    "devices": sorted(entries, key=lambda e: e["category"]),
                }
                for room, entries in sorted(by_room.items())
            },
            "by_category": {
                cat: {
                    "count": len(entries),
                    "devices": entries,
                }
                for cat, entries in sorted(by_category.items())
            },
            "offline_devices": [d.to_dict() for d in offline],
        }

    def generate_ascii_topology(self) -> str:
        """
        Generate a human-readable ASCII topology tree of the smart home system.
        Useful for Bob's system awareness and log output.
        """
        lines = [
            "Symphony Smart Homes — System Topology",
            "=" * 50,
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Total entities: {len(self._devices)}",
            "",
        ]

        vendor_groups: Dict[str, List[DeviceEntry]] = {}
        for d in self._devices.values():
            vendor_groups.setdefault(d.vendor, []).append(d)

        for vendor in sorted(vendor_groups.keys()):
            entries = vendor_groups[vendor]
            lines.append(f"  [{vendor.upper().replace('_', ' ')}] ({len(entries)} devices)")

            # Group by category within vendor
            cat_groups: Dict[str, List[DeviceEntry]] = {}
            for d in entries:
                cat_groups.setdefault(d.category, []).append(d)

            for cat in sorted(cat_groups.keys()):
                cat_entries = cat_groups[cat]
                lines.append(f"    {cat} ({len(cat_entries)})")
                for d in sorted(cat_entries, key=lambda x: x.entity_id)[:5]:
                    room_str = f" [{d.room}]" if d.room else ""
                    state_str = f" — {d.state}" if d.state else ""
                    lines.append(f"      • {d.friendly_name}{room_str}{state_str}")
                if len(cat_entries) > 5:
                    lines.append(f"      ... and {len(cat_entries) - 5} more")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Entity → friendly name mapping
    # ------------------------------------------------------------------

    def entity_to_friendly(self, entity_id: str) -> str:
        """Map entity_id to friendly name."""
        d = self._devices.get(entity_id)
        return d.friendly_name if d else entity_id

    def friendly_to_entity(self, friendly_name: str) -> Optional[str]:
        """Reverse-lookup entity_id from friendly name (case-insensitive)."""
        fn_lower = friendly_name.lower()
        for d in self._devices.values():
            if d.friendly_name.lower() == fn_lower:
                return d.entity_id
        return None

    def get_room_entities(self, room: str, domain: Optional[str] = None) -> List[str]:
        """Get entity_ids for all devices in a room, optionally filtered by domain."""
        entries = self.get_by_room(room)
        if domain:
            entries = [e for e in entries if e.domain == domain]
        return [e.entity_id for e in entries]

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _save_cache(self):
        """Persist the device registry to disk."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "last_refresh": self._last_refresh,
                "devices": {eid: d.to_dict() for eid, d in self._devices.items()},
            }
            self._cache_file.write_text(json.dumps(cache_data, indent=2))
            logger.debug(f"Registry cache saved to {self._cache_file}")
        except Exception as exc:
            logger.warning(f"Could not save registry cache: {exc}")

    def _load_cache(self) -> bool:
        """Load the device registry from disk cache. Returns True if loaded."""
        try:
            if not self._cache_file.exists():
                return False
            cache_age = time.time() - self._cache_file.stat().st_mtime
            if cache_age > CACHE_MAX_AGE:
                logger.info(f"Registry cache is stale ({cache_age:.0f}s old), will refresh")
                return False

            data = json.loads(self._cache_file.read_text())
            self._last_refresh = data.get("last_refresh", 0.0)
            # Rebuild DeviceEntry objects from cached dicts
            for eid, d_dict in data.get("devices", {}).items():
                self._devices[eid] = DeviceEntry(
                    entity_id=d_dict["entity_id"],
                    friendly_name=d_dict["friendly_name"],
                    domain=d_dict["domain"],
                    state=d_dict["state"],
                    vendor=d_dict["vendor"],
                    category=d_dict["category"],
                    room=d_dict.get("room"),
                    integration=d_dict.get("integration"),
                    model=d_dict.get("model"),
                    manufacturer=d_dict.get("manufacturer"),
                    area_name=d_dict.get("area_name"),
                )
            logger.info(f"Loaded {len(self._devices)} devices from cache")
            return True
        except Exception as exc:
            logger.warning(f"Could not load registry cache: {exc}")
            return False

    async def _refresh_loop(self):
        """Periodically refresh the device registry in the background."""
        while self._running:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self.refresh()
            except Exception as exc:
                logger.warning(f"Background registry refresh failed: {exc}")

    @property
    def is_fresh(self) -> bool:
        """Returns True if the registry was refreshed recently."""
        return (time.time() - self._last_refresh) < CACHE_MAX_AGE
