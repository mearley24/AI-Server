"""System compatibility engine for Symphony hardware stacks."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HARDWARE_DIR = Path(__file__).resolve().parent


COMPONENT_TYPES = {
    "TV",
    "Mount",
    "Speaker",
    "Amplifier",
    "Switch",
    "Panel",
    "Camera",
    "iPad",
    "Network_Switch",
    "Access_Point",
    "Shade_Motor",
    "Conduit",
}


CONNECTION_TYPES = {
    "HDMI": {"fields": ["version", "length_ft", "arc"]},
    "Cat6": {"fields": ["poe_watts", "vlan"]},
    "Speaker_Wire": {"fields": ["gauge", "impedance_ohm", "run_ft"]},
    "IR": {"fields": ["line_of_sight", "flasher_required"]},
    "WiFi": {"fields": ["band", "coverage_sqft"]},
    "Power": {"fields": ["voltage", "amperage", "outlet_type"]},
    "Control_Protocol": {"fields": ["protocol"]},
}


@dataclass
class Component:
    id: str
    component_type: str
    model: str
    manufacturer: str
    specs: dict[str, Any] = field(default_factory=dict)
    location: str = ""
    project: str = ""


@dataclass
class ValidationReport:
    passes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = ["System Validation Report", "=" * 24]
        lines.append("")
        lines.append("Passes:")
        lines.extend([f"- {m}" for m in self.passes] or ["- None"])
        lines.append("")
        lines.append("Warnings:")
        lines.extend([f"- {m}" for m in self.warnings] or ["- None"])
        lines.append("")
        lines.append("Failures:")
        lines.extend([f"- {m}" for m in self.failures] or ["- None"])
        lines.append("")
        lines.append("Suggestions:")
        lines.extend([f"- {m}" for m in self.suggestions] or ["- None"])
        return "\n".join(lines)


class CompatibilityEngine:
    def __init__(self, hardware_dir: Path = HARDWARE_DIR) -> None:
        self.hardware_dir = hardware_dir
        self.catalog = self._load_catalogs()
        self.c4_reference = self._load_c4_reference()

    def _load_json(self, name: str) -> Any:
        path = self.hardware_dir / name
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def _load_catalogs(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "tvs": self._load_json("tvs.json").get("components", []),
            "mounts": self._load_json("mounts.json").get("components", []),
            "networking": self._load_json("networking.json").get("components", []),
        }

    def _load_c4_reference(self) -> list[dict[str, Any]]:
        data = self._load_json("c4_tv_driver_reference.json")
        out: list[dict[str, Any]] = []
        for brand_entry in data.get("brands", []):
            brand = brand_entry.get("brand", "")
            for model in brand_entry.get("models", []):
                out.append(
                    {
                        "brand": brand,
                        "model_line": model.get("model_line", ""),
                        "integration_level": model.get("integration_level"),
                        "integration_label": model.get("integration_label", ""),
                    }
                )
        return out

    def _find_c4_integration(self, tv: Component) -> str:
        model_lower = tv.model.lower()
        mfr_lower = tv.manufacturer.lower()
        for row in self.c4_reference:
            if row["brand"].lower() != mfr_lower:
                continue
            line = row["model_line"].split("(")[0].strip().lower()
            if line in model_lower:
                return row["integration_label"]
            tokens = [t for t in line.replace("/", " ").replace("-", " ").split() if len(t) >= 2]
            expanded_tokens: list[str] = []
            for token in tokens:
                expanded_tokens.append(token)
                stripped = token.rstrip("abcdefghijklmnopqrstuvwxyz")
                if stripped and stripped != token:
                    expanded_tokens.append(stripped)
            if any(t in model_lower for t in expanded_tokens):
                return row["integration_label"]
        return "UNKNOWN"

    def _alt_mounts(self, tv: Component) -> list[str]:
        tv_vesa = tv.specs.get("vesa", "")
        tv_weight = float(tv.specs.get("weight_lbs", 0) or 0)
        out: list[str] = []
        for m in self.catalog["mounts"]:
            specs = m.get("specs", {})
            supported = specs.get("supported_vesa", [])
            if tv_vesa and tv_vesa not in supported:
                continue
            if float(specs.get("weight_capacity_lbs", 0) or 0) < (tv_weight * 1.2):
                continue
            if float(specs.get("profile_in", 0) or 0) < 2.0:
                continue
            out.append(f"{m.get('manufacturer')} {m.get('model')}")
        return out[:3]

    def _alt_native_tvs(self, tv: Component) -> list[str]:
        out: list[str] = []
        for c in self.catalog["tvs"]:
            if c.get("manufacturer", "").lower() == tv.manufacturer.lower():
                continue
            if c.get("specs", {}).get("c4_integration", "").lower().startswith("native"):
                out.append(f"{c.get('manufacturer')} {c.get('model')}")
        return out[:3]

    def validate_system(self, components: list[Component]) -> ValidationReport:
        report = ValidationReport()
        tvs = [c for c in components if c.component_type == "TV"]
        mounts = [c for c in components if c.component_type == "Mount"]
        speakers = [c for c in components if c.component_type == "Speaker"]
        amps = [c for c in components if c.component_type == "Amplifier"]
        switches = [c for c in components if c.component_type == "Network_Switch"]

        mounts_by_location = {m.location: m for m in mounts}
        amps_by_location = {a.location: a for a in amps}
        switches_by_id = {s.id: s for s in switches}

        # Required pair checks + TV/Mount validation.
        for tv in tvs:
            mount = mounts_by_location.get(tv.location)
            if not mount:
                report.failures.append(f"TV at {tv.location} specified but no mount assigned.")
                report.suggestions.append("Add a compatible mount for every TV location.")
                continue

            tv_vesa = tv.specs.get("vesa", "")
            mount_vesa = mount.specs.get("supported_vesa", [])
            if tv_vesa in mount_vesa:
                report.passes.append(f"{tv.model} VESA {tv_vesa} matches {mount.model}.")
            else:
                report.failures.append(
                    f"TV: {tv.model} VESA {tv_vesa} — Mount: {mount.model} max VESA {mount_vesa} — FAIL: VESA pattern incompatible"
                )
                alts = self._alt_mounts(tv)
                if alts:
                    report.suggestions.append(f"Mount alternatives for {tv.model}: {', '.join(alts)}")

            tv_weight = float(tv.specs.get("weight_lbs", 0) or 0)
            mount_cap = float(mount.specs.get("weight_capacity_lbs", 0) or 0)
            if mount_cap >= (tv_weight * 1.2):
                report.passes.append(f"{mount.model} capacity {mount_cap} lbs clears {tv.model} load requirement.")
            else:
                report.failures.append(
                    f"Mount {mount.model} capacity {mount_cap} lbs insufficient for {tv.model} ({tv_weight} lbs + 20% margin)."
                )

            profile = float(mount.specs.get("profile_in", 0) or 0)
            plug_protrusion = float(tv.specs.get("plug_protrusion_in", 2.0) or 2.0)
            if profile > plug_protrusion:
                report.passes.append(
                    f"Mount {mount.model} profile {profile}\" clears plug protrusion {plug_protrusion}\"."
                )
            else:
                report.failures.append(
                    f"Mount {mount.model} profile {profile}\" fails clearance vs plug protrusion {plug_protrusion}\"."
                )
                report.suggestions.append("Use a tilt/articulating mount with >= 2.1\" profile (e.g. Sanus VLT7).")

            integration = self._find_c4_integration(tv)
            if integration == "UNKNOWN":
                report.failures.append(f"TV {tv.manufacturer} {tv.model} C4 integration method unknown.")
                alts = self._alt_native_tvs(tv)
                if alts:
                    report.suggestions.append(f"Native C4 TV alternatives: {', '.join(alts)}")
            else:
                report.passes.append(f"TV {tv.manufacturer} {tv.model} integration: {integration}.")

        # Speaker/amp impedance check.
        for sp in speakers:
            amp = amps_by_location.get(sp.location)
            if not amp:
                report.warnings.append(f"Speaker {sp.model} at {sp.location} has no mapped amplifier.")
                continue
            imp = float(sp.specs.get("impedance_ohm", 8) or 8)
            amp_min = float(amp.specs.get("impedance_min_ohm", 4) or 4)
            amp_max = float(amp.specs.get("impedance_max_ohm", 8) or 8)
            if amp_min <= imp <= amp_max:
                report.passes.append(f"Speaker impedance {imp} ohm matches amp zone at {sp.location}.")
            else:
                report.failures.append(
                    f"Speaker impedance {imp} ohm incompatible with amp {amp.model} range {amp_min}-{amp_max} ohm."
                )

        # PoE and VLAN checks.
        poe_draw_by_switch: dict[str, float] = {}
        for c in components:
            if c.component_type in {"Camera", "Access_Point", "Panel", "iPad"}:
                if not c.specs.get("vlan"):
                    report.failures.append(f"{c.component_type} {c.model} missing VLAN assignment.")
                if str(c.specs.get("power_type", "")).lower() == "poe":
                    switch_id = c.specs.get("connected_to_switch_id", "")
                    poe_draw = float(c.specs.get("power_draw_w", 0) or 0)
                    if not switch_id:
                        report.warnings.append(f"{c.component_type} {c.model} PoE draw defined but no switch mapping.")
                        continue
                    poe_draw_by_switch[switch_id] = poe_draw_by_switch.get(switch_id, 0.0) + poe_draw

            if c.component_type == "iPad":
                power_solution = str(c.specs.get("power_solution", "")).lower()
                if power_solution in {"poe", "in_wall", "in-wall"}:
                    report.passes.append(f"iPad {c.model} has acceptable power solution ({power_solution}).")
                else:
                    report.failures.append(f"iPad {c.model} missing PoE or in-wall power solution.")

        for switch_id, draw in poe_draw_by_switch.items():
            sw = switches_by_id.get(switch_id)
            if not sw:
                report.failures.append(f"PoE devices mapped to unknown switch id {switch_id}.")
                continue
            budget = float(sw.specs.get("poe_budget_w", 0) or 0)
            if draw <= budget:
                report.passes.append(f"Switch {sw.model} PoE draw {draw:.1f}W within budget {budget:.1f}W.")
            else:
                report.failures.append(f"Switch {sw.model} PoE draw {draw:.1f}W exceeds budget {budget:.1f}W.")

        return report


def _component_from_dict(row: dict[str, Any]) -> Component:
    ctype = row.get("component_type", "")
    if ctype not in COMPONENT_TYPES:
        raise ValueError(f"Unknown component type: {ctype}")
    return Component(
        id=row.get("id", ""),
        component_type=ctype,
        model=row.get("model", ""),
        manufacturer=row.get("manufacturer", ""),
        specs=row.get("specs", {}),
        location=row.get("location", ""),
        project=row.get("project", ""),
    )


def _project_template(name: str) -> list[Component]:
    name = name.lower().strip()
    if name != "topletz":
        return []
    raw = [
        {
            "id": "tv-great-1",
            "component_type": "TV",
            "model": "100 U8",
            "manufacturer": "Hisense",
            "location": "Great Room",
            "specs": {"vesa": "800x400", "weight_lbs": 160, "plug_protrusion_in": 2.0},
        },
        {
            "id": "mount-great-1",
            "component_type": "Mount",
            "model": "PLCM-2",
            "manufacturer": "Peerless",
            "location": "Great Room",
            "specs": {"supported_vesa": ["600x400"], "weight_capacity_lbs": 200, "profile_in": 1.8},
        },
        {
            "id": "tv-master-1",
            "component_type": "TV",
            "model": "QN90F",
            "manufacturer": "Samsung",
            "location": "Master Bedroom",
            "specs": {"vesa": "400x400", "weight_lbs": 75, "plug_protrusion_in": 2.0},
        },
        {
            "id": "spk-gr-1",
            "component_type": "Speaker",
            "model": "Episode Signature 6",
            "manufacturer": "Episode",
            "location": "Great Room",
            "specs": {"impedance_ohm": 8},
        },
        {
            "id": "amp-gr-1",
            "component_type": "Amplifier",
            "model": "Control4 Triad One",
            "manufacturer": "Control4",
            "location": "Great Room",
            "specs": {"impedance_min_ohm": 4, "impedance_max_ohm": 8},
        },
        {
            "id": "sw-core-1",
            "component_type": "Network_Switch",
            "model": "AN-820-24P",
            "manufacturer": "Araknis",
            "location": "Rack",
            "specs": {"poe_budget_w": 190, "vlan": 1},
        },
        {
            "id": "ap-main-1",
            "component_type": "Access_Point",
            "model": "AN-510-AP-I-AC",
            "manufacturer": "Araknis",
            "location": "Main Hall",
            "specs": {"power_type": "poe", "power_draw_w": 15, "connected_to_switch_id": "sw-core-1", "vlan": 20},
        },
        {
            "id": "cam-drive-1",
            "component_type": "Camera",
            "model": "Luma X20",
            "manufacturer": "Luma",
            "location": "Driveway",
            "specs": {"power_type": "poe", "power_draw_w": 14, "connected_to_switch_id": "sw-core-1", "vlan": 50},
        },
        {
            "id": "ipad-kitchen-1",
            "component_type": "iPad",
            "model": "iPad 10th Gen",
            "manufacturer": "Apple",
            "location": "Kitchen",
            "specs": {"power_type": "poe", "power_draw_w": 20, "connected_to_switch_id": "sw-core-1", "vlan": 20, "power_solution": "poe"},
        },
        {
            "id": "panel-main-1",
            "component_type": "Panel",
            "model": "Qolsys IQ Panel 4",
            "manufacturer": "Qolsys",
            "location": "Garage Entry",
            "specs": {"power_type": "poe", "power_draw_w": 18, "connected_to_switch_id": "sw-core-1", "vlan": 40},
        },
    ]
    return [_component_from_dict(r) for r in raw]


def _cli_validate(project: str) -> int:
    components = _project_template(project)
    if not components:
        print(f"Unknown project template: {project}")
        return 1
    engine = CompatibilityEngine()
    report = engine.validate_system(components)
    print(report.to_text())
    return 0 if not report.failures else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="System compatibility engine")
    sub = parser.add_subparsers(dest="cmd")

    v = sub.add_parser("validate", help="Validate a project template")
    v.add_argument("--project", required=True, help="Project name (e.g. topletz)")

    args = parser.parse_args()
    if args.cmd == "validate":
        raise SystemExit(_cli_validate(args.project))
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
