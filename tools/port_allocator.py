#!/usr/bin/env python3
"""
Symphony switch / NVR port allocation — cameras on NVR PoE only, APs from port 1, 20% reserve.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("port_allocator")

REPO_ROOT = Path(__file__).resolve().parents[1]

ROOM_PHRASES: list[tuple[str, str]] = [
    ("living room", "LR"),
    ("great room", "LR"),
    ("hearth", "LR"),
    ("master bedroom", "MBR"),
    ("bedroom 2", "BR2"),
    ("bedroom 3", "BR3"),
    ("bedroom 4", "BR4"),
    ("kitchen", "KIT"),
    ("dining", "DR"),
    ("office", "OFF"),
    ("garage", "GAR"),
    ("outdoor", "OUT"),
    ("front entry", "FE"),
    ("rack", "RK"),
    ("equipment", "RK"),
    ("gym", "GYM"),
    ("theater", "THR"),
    ("laundry", "LAU"),
    ("utility", "UTL"),
    ("lower level", "LL"),
    ("driveway", "DRV"),
    ("rear", "OUT"),
]

DEVICE_TYPE_CODES: dict[str, str] = {
    "ap": "AP",
    "access_point": "AP",
    "camera": "CAM",
    "switch": "SW",
    "controller": "EA",
    "nvr": "NVR",
    "amplifier": "AMP",
    "audio_matrix": "AMS",
    "ipad": "IPD",
    "lutron": "LUT",
    "qolsys": "QOL",
    "wattbox": "WB",
    "tv": "TV",
    "streamer": "STB",
    "router": "RT",
    "other": "DEV",
}

DEFAULT_POE_W: dict[str, float] = {
    "ap": 15.0,
    "access_point": 15.0,
    "camera": 8.0,
    "controller": 12.0,
    "audio_matrix": 30.0,
    "ipad": 12.0,
    "nvr": 0.0,
    "switch": 0.0,
    "router": 0.0,
    "tv": 0.0,
    "other": 8.0,
}


def room_to_code(room: str) -> str:
    low = room.lower().strip()
    for phrase, code in ROOM_PHRASES:
        if phrase in low:
            return code
    parts = re.split(r"[\s/]+", low)
    tok = "".join(p[0] for p in parts if p)[:4].upper()
    return tok or "RK"


def device_type_code(category: str) -> str:
    return DEVICE_TYPE_CODES.get(category.lower(), "DEV")


def cable_label(room: str, category: str, seq: int) -> str:
    return f"{room_to_code(room)}-{device_type_code(category)}-{seq:02d}"


def max_assignable_switch_ports(port_count: int) -> int:
    """Leave 20% free — use floor(0.8 * n), at least 1."""
    return max(1, int(port_count * 0.8))


def load_switch_specs(
    model: str,
    networking_path: Path | None = None,
) -> dict[str, Any]:
    path = networking_path or (REPO_ROOT / "knowledge" / "hardware" / "networking.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    model_l = model.strip().lower()
    for c in data.get("components", []):
        m = str(c.get("model", "")).lower()
        if m == model_l or model_l in m or m in model_l:
            return dict(c.get("specs") or {})
    logger.warning("No specs for switch model %s — using 24p / 190W", model)
    return {"port_count": 24, "poe_budget_w": 190, "poe_port_count": 24}


def load_nvr_poe_count(
    nvr_model: str,
    networking_path: Path | None = None,
) -> int:
    path = networking_path or (REPO_ROOT / "knowledge" / "hardware" / "networking.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    nvr_l = nvr_model.strip().lower()
    for c in data.get("components", []):
        if c.get("component_type") != "NVR":
            continue
        m = str(c.get("model", "")).lower()
        if m == nvr_l or nvr_l in m:
            return int((c.get("specs") or {}).get("poe_port_count") or 8)
    return 16


@dataclass
class PortDevice:
    """Something that needs a switch port and/or NVR PoE."""

    name: str
    room: str
    category: str
    vlan: int | None = None
    poe_w: float | None = None
    is_camera: bool = False

    def effective_poe(self) -> float:
        if self.poe_w is not None:
            return float(self.poe_w)
        return float(DEFAULT_POE_W.get(self.category.lower(), DEFAULT_POE_W["other"]))


@dataclass
class PortPlan:
    switch_rows: list[dict[str, Any]] = field(default_factory=list)
    nvr_rows: list[dict[str, Any]] = field(default_factory=list)
    cable_labels: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    poe_used_w: float = 0.0
    poe_budget_w: float = 0.0


def allocate_ports(
    devices: list[PortDevice],
    main_switch_model: str,
    nvr_model: str = "Luma-NVR-16CH-POE",
    networking_path: Path | None = None,
) -> PortPlan:
    """
    Cameras → NVR PoE ports only (NVR-P1…). APs → main switch from port 1 upward.
    Other wired devices fill next switch ports. Enforces 20% port reserve on the switch.
    """
    specs = load_switch_specs(main_switch_model, networking_path)
    port_count = int(specs.get("port_count") or 24)
    poe_budget = float(specs.get("poe_budget_w") or 190)
    cap = max_assignable_switch_ports(port_count)
    nvr_slots = load_nvr_poe_count(nvr_model, networking_path)

    plan = PortPlan(poe_budget_w=poe_budget)
    cameras = [d for d in devices if d.is_camera or d.category.lower() == "camera"]
    aps = [d for d in devices if d.category.lower() in ("ap", "access_point")]
    switch_rest = [
        d
        for d in devices
        if d not in cameras and d.category.lower() not in ("ap", "access_point")
    ]

    ap_seq = 1
    sw_port = 1
    # Switch PoE budget applies only to devices powered by the main switch.
    poe_sum = 0.0
    nvr_port = 1

    for d in cameras:
        if nvr_port > nvr_slots:
            plan.warnings.append(
                f"NVR PoE exhausted ({nvr_slots} ports); camera {d.name} not placed on NVR"
            )
            continue
        label = cable_label(d.room, "camera", nvr_port)
        plan.nvr_rows.append(
            {
                "port": f"NVR-P{nvr_port}",
                "device": d.name,
                "vlan": d.vlan or 50,
                "poe": True,
                "cable_label": label,
            }
        )
        plan.cable_labels.append(
            {
                "label": label,
                "from_room": d.room,
                "to": f"Rack NVR-P{nvr_port}",
            }
        )
        nvr_port += 1

    for d in aps:
        if sw_port > cap:
            plan.warnings.append(f"Switch port cap ({cap}) reached; AP {d.name} unassigned")
            continue
        label = cable_label(d.room, "ap", ap_seq)
        ap_seq += 1
        plan.switch_rows.append(
            {
                "port": sw_port,
                "device": d.name,
                "vlan": d.vlan or 1,
                "poe": True,
                "cable_label": label,
            }
        )
        plan.cable_labels.append(
            {"label": label, "from_room": d.room, "to": f"Rack Sw1-P{sw_port}"}
        )
        poe_sum += d.effective_poe()
        sw_port += 1

    other_seq: dict[str, int] = {}
    for d in switch_rest:
        cat = d.category.lower()
        if sw_port > cap:
            plan.warnings.append(f"Switch port cap ({cap}) reached; {d.name} unassigned")
            continue
        other_seq[cat] = other_seq.get(cat, 0) + 1
        label = cable_label(d.room, cat, other_seq[cat])
        uses_poe = d.effective_poe() > 0
        plan.switch_rows.append(
            {
                "port": sw_port,
                "device": d.name,
                "vlan": d.vlan or 1,
                "poe": uses_poe,
                "cable_label": label,
            }
        )
        plan.cable_labels.append(
            {"label": label, "from_room": d.room, "to": f"Rack Sw1-P{sw_port}"}
        )
        poe_sum += d.effective_poe()
        sw_port += 1

    plan.poe_used_w = poe_sum
    if poe_budget > 0 and poe_sum > 0.8 * poe_budget:
        plan.warnings.append(
            f"PoE draw ~{poe_sum:.0f}W exceeds 80% of budget ({0.8 * poe_budget:.0f}W) — verify injectors / switch model"
        )

    free = cap - (sw_port - 1)
    if free < max(1, int(0.2 * port_count)):
        plan.warnings.append(
            f"Only {free} switch ports left below 20% reserve target — expand stack or add switch"
        )

    return plan


def export_labels_csv(plan: PortPlan, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["label", "from_room", "to"])
        w.writeheader()
        for row in plan.cable_labels:
            w.writerow(row)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Port allocator (Symphony rules)")
    ap.add_argument("--demo", action="store_true", help="Run a Topletz-sized demo and print tables")
    args = ap.parse_args()
    if not args.demo:
        ap.print_help()
        return 1
    demo = [
        PortDevice("Living Room AP", "Living Room", "ap", vlan=1),
        PortDevice("Master Bedroom AP", "Master Bedroom", "ap", vlan=1),
        PortDevice("Kitchen AP", "Kitchen", "ap", vlan=1),
        PortDevice("Front Entry Camera", "Front Entry", "camera", vlan=50, is_camera=True),
        PortDevice("Garage Camera", "Garage", "camera", vlan=50, is_camera=True),
        PortDevice("EA-5 Controller", "Rack", "controller", vlan=20),
        PortDevice("AMS-16", "Rack", "audio_matrix", vlan=20),
    ]
    plan = allocate_ports(demo, "AN-620-SW-R-24-POE")
    print("Switch ports:")
    for r in plan.switch_rows:
        print(r)
    print("NVR ports:")
    for r in plan.nvr_rows:
        print(r)
    for w in plan.warnings:
        print("WARN:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
