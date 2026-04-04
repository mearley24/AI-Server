#!/usr/bin/env python3
"""
System shell generator — pre-planned IPs (10.X.Y.Z), device registry, port plan, checklist.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = REPO_ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
import access_codes_md as _acm

from port_allocator import (
    PortDevice,
    allocate_ports,
    export_labels_csv,
)

logger = logging.getLogger("system_shell")

CHECKLIST_DEFAULT = [
    "Router configured, VLANs created",
    "Switch configured, port VLANs assigned",
    "All APs powered and adopted",
    "Controller online, rooms created",
    "All cameras visible in NVR",
    "Qolsys enrolled, C4 driver connected",
    "All audio zones tested",
    "Client WiFi networks active",
    "Remote access verified (Tailscale/VPN)",
    "Client walkthrough complete",
]


def load_client_registry(path: Path | None = None) -> dict[str, Any]:
    p = path or (REPO_ROOT / "knowledge" / "network" / "client_registry.json")
    return json.loads(p.read_text(encoding="utf-8"))


def lookup_client(registry: dict[str, Any], slug: str) -> tuple[str, dict[str, Any]]:
    slug_l = slug.lower().strip()
    for num, rec in registry.items():
        if str(rec.get("slug", "")).lower() == slug_l:
            return num, rec
    raise KeyError(f"No client_registry entry for slug={slug!r}")


def client_octet(client_num: str) -> int:
    return int(client_num, 10)


def ip_addr(client_octet_val: int, vlan: int, fourth: int) -> str:
    return f"10.{client_octet_val}.{vlan}.{fourth}"


def parse_equipment_rollup(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    in_totals = False
    for line in text.splitlines():
        if "## Device Totals" in line:
            in_totals = True
            continue
        if in_totals and line.startswith("##") and "Device Totals" not in line:
            break
        m = re.match(r"^-\s*([^:]+):\s*(\d+)\s*$", line.strip())
        if m:
            out[m.group(1).strip().lower()] = int(m.group(2))
    return out


def parse_kelly_skus(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|", line.strip())
        if not m:
            continue
        sku = m.group(2).strip()
        if sku.lower() == "sku" or re.match(r"^-+$", sku):
            continue
        counts[sku] = int(m.group(1))
    return counts


def merge_access_codes(project_slug: str) -> tuple[list[dict[str, Any]], str | None]:
    """Return (rows, source_tag). Checks projects/ and legacy knowledge/{slug}/."""
    paths = [
        REPO_ROOT / "knowledge" / "projects" / project_slug / "access_codes.md",
        REPO_ROOT / "knowledge" / project_slug / "access_codes.md",
    ]
    for p in paths:
        if p.is_file():
            rows = _acm.parse_access_codes_md(p)
            if rows:
                return rows, str(p.relative_to(REPO_ROOT))
    return [], None


def default_placeholder_codes(project_name: str, co: int) -> list[dict[str, str]]:
    return [
        {
            "system": "Router Admin",
            "username": "admin",
            "password": "[set on site]",
            "notes": ip_addr(co, 1, 1),
        },
        {
            "system": "WiFi - Trusted",
            "username": "[client SSID]",
            "password": "[set on site]",
            "notes": "VLAN 10",
        },
        {
            "system": "WiFi - Guest",
            "username": f"{project_name[:20]}-Guest",
            "password": "[set on site]",
            "notes": "VLAN 40",
        },
        {
            "system": "Luma NVR",
            "username": "admin",
            "password": "[set on site]",
            "notes": "VLAN 50",
        },
        {
            "system": "Control4 Composer",
            "username": project_name[:32],
            "password": "[set on site]",
            "notes": "HE license",
        },
    ]


def _vlan_overview_rows(
    co: int,
    has_iot: bool,
    has_guest: bool,
    cam_count: int,
) -> list[dict[str, str]]:
    rows = [
        {
            "vlan": "1",
            "subnet": f"10.{co}.1.0/24",
            "purpose": "Management",
            "devices": "Router, Switch, APs",
        },
        {
            "vlan": "20",
            "subnet": f"10.{co}.20.0/24",
            "purpose": "Control",
            "devices": "Controller, touchscreens, audio matrix, security",
        },
    ]
    if has_iot:
        rows.append(
            {
                "vlan": "30",
                "subnet": f"10.{co}.30.0/24",
                "purpose": "IoT",
                "devices": "TVs, streamers",
            }
        )
    if has_guest:
        rows.append(
            {
                "vlan": "40",
                "subnet": f"10.{co}.40.0/24",
                "purpose": "Guest",
                "devices": "DHCP only",
            }
        )
    if cam_count:
        rows.append(
            {
                "vlan": "50",
                "subnet": f"10.{co}.50.0/24",
                "purpose": "Surveillance",
                "devices": f"NVR, {cam_count}× Camera",
            }
        )
    return rows


def build_topletz_devices(co: int, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[PortDevice]]:
    proj = cfg.get("project") or {}
    name = proj.get("name", "Topletz Residence")
    scope = cfg.get("scope") or {}
    cams = scope.get("camera_locations") or []
    ipads = scope.get("ipad_locations") or []
    rows: list[dict[str, Any]] = []
    ports: list[PortDevice] = []

    rows.append(
        _dev("Rack", "Router", "AN-520-RT", co, 1, 1, "-", "-", "ap")
    )
    rows.append(
        _dev("Rack", "Switch", "AN-620-SW-R-24-POE", co, 1, 2, "-", "-", "switch")
    )

    ap_rooms = ["Great Room", "Master Bedroom", "Kitchen"]
    for i, rm in enumerate(ap_rooms, start=1):
        fourth = 15 + i
        dname = f"Access Point {i}"
        rows.append(
            _dev(rm, dname, "AN-820-AP-I", co, 1, fourth, "Sw1-P?", "?", "ap")
        )
        ports.append(PortDevice(dname, rm, "ap", vlan=1))

    rows.append(_dev("Rack", "NVR", "Luma NVR", co, 50, 2, "-", "RK-NVR-01", "nvr"))
    ports.append(PortDevice("NVR", "Rack", "nvr", vlan=50, poe_w=0))

    for i, loc in enumerate(cams, start=1):
        rm = loc.title()
        fourth = 15 + i
        dname = f"Camera {i}"
        rows.append(
            _dev(
                rm,
                dname,
                "Luma IP",
                co,
                50,
                fourth,
                f"NVR-P{i}",
                f"?-CAM-{i:02d}",
                "camera",
                is_camera=True,
            )
        )
        ports.append(PortDevice(dname, rm, "camera", vlan=50, is_camera=True))

    rows.append(_dev("Rack", "Controller", "C4-EA5", co, 20, 16, "Sw1-P?", "RK-EA-01", "controller"))
    ports.append(PortDevice("Controller", "Rack", "controller", vlan=20))

    rows.append(_dev("Rack", "Audio Matrix", "TS-AMS16", co, 20, 17, "Sw1-P?", "RK-AMS-01", "audio_matrix"))
    ports.append(PortDevice("Audio Matrix", "Rack", "audio_matrix", vlan=20))

    for i, loc in enumerate(ipads, start=1):
        fourth = 25 + i
        rows.append(
            _dev(
                loc,
                f"iPad {i}",
                "Apple iPad",
                co,
                20,
                fourth,
                "-",
                "-",
                "ipad",
                wireless=True,
            )
        )

    if scope.get("security_panel_prewire"):
        loc = scope.get("security_panel_location", "Garage")
        dname = "Security Panel"
        rows.append(
            _dev(
                loc.title(),
                dname,
                scope.get("security_panel_model", "Qolsys IQ Panel"),
                co,
                20,
                66,
                "Sw1-P?",
                "GR-QOL-01",
                "qolsys",
            )
        )
        ports.append(PortDevice(dname, loc.title(), "qolsys", vlan=20, poe_w=12.0))

    tv_path = REPO_ROOT / "knowledge" / "topletz" / "tv-schedule-client.md"
    tv_count = 9
    if tv_path.is_file():
        ttxt = tv_path.read_text(encoding="utf-8")
        mtot = re.search(r"Total:\s*(\d+)\s*TVs", ttxt, re.I)
        tv_count = int(mtot.group(1)) if mtot else 9
    if scope.get("network") and scope.get("control4"):
        for t in range(min(tv_count, 9)):
            fourth = 16 + t
            rows.append(
                _dev(
                    f"TV Zone {t + 1}",
                    "Smart TV",
                    "Client TV",
                    co,
                    30,
                    fourth,
                    "-",
                    "-",
                    "tv",
                    wireless=True,
                )
            )

    kp_est = 16
    rows.append(
        {
            "room": "Various",
            "device": f"Control4 Keypads (×{kp_est}, est.)",
            "model": "C4 / ZigBee",
            "ip": "—",
            "vlan": "—",
            "switch_port": "—",
            "cable_label": "—",
            "status": "⬜",
            "category": "keypad",
            "wireless": True,
        }
    )

    return rows, ports


def _dev(
    room: str,
    device: str,
    model: str,
    co: int,
    vlan: int,
    fourth: int,
    switch_port: str,
    cable: str,
    category: str,
    is_camera: bool = False,
    wireless: bool = False,
) -> dict[str, Any]:
    return {
        "room": room,
        "device": device,
        "model": model,
        "ip": ip_addr(co, vlan, fourth),
        "vlan": str(vlan),
        "switch_port": switch_port,
        "cable_label": cable,
        "status": "⬜",
        "category": category,
        "is_camera": is_camera,
        "wireless": wireless,
    }


def build_gates_devices(co: int, totals: dict[str, int]) -> tuple[list[dict[str, Any]], list[PortDevice]]:
    rows: list[dict[str, Any]] = []
    ports: list[PortDevice] = []
    rows.append(_dev("Rack", "Router", "AN-520-RT", co, 1, 1, "-", "-", "router"))
    rows.append(_dev("Rack", "Switch", "AN-820-24P", co, 1, 2, "-", "-", "switch"))
    rows.append(_dev("Rack", "NVR", "Luma NVR", co, 50, 2, "-", "RK-NVR-01", "nvr"))
    ports.append(PortDevice("NVR", "Rack", "nvr", vlan=50))

    n_ap = totals.get("access point drop", 3)
    for i in range(n_ap):
        dname = f"Access Point {i + 1}"
        rows.append(
            _dev(
                f"AP Zone {i + 1}",
                dname,
                "AN-820-AP-I",
                co,
                1,
                16 + i,
                "Sw1-P?",
                "?",
                "ap",
            )
        )
        ports.append(PortDevice(dname, f"Zone {i+1}", "ap", vlan=1))

    rows.append(_dev("Rack", "Controller", "Control4", co, 20, 16, "Sw1-P?", "RK-EA-01", "controller"))
    ports.append(PortDevice("Controller", "Rack", "controller", vlan=20))

    nk = totals.get("keypad", 21)
    rows.append(
        {
            "room": "Various",
            "device": f"Keypads (×{nk})",
            "model": "C4 (ZigBee)",
            "ip": "—",
            "vlan": "—",
            "switch_port": "—",
            "cable_label": "—",
            "status": "⬜",
            "category": "keypad",
            "wireless": True,
        }
    )

    nt = totals.get("tv", 4)
    for t in range(nt):
        rows.append(
            _dev(
                f"TV {t + 1}",
                "Display",
                "TV",
                co,
                30,
                16 + t,
                "-",
                "-",
                "tv",
                wireless=True,
            )
        )

    nc = totals.get("dome camera", 0) + totals.get("doorbell camera", 0)
    for i in range(nc):
        dname = f"Camera {i + 1}"
        rows.append(
            _dev(
                f"Cam {i + 1}",
                dname,
                "IP Camera",
                co,
                50,
                16 + i,
                f"NVR-P{i + 1}",
                f"CAM-{i + 1:02d}",
                "camera",
                is_camera=True,
            )
        )
        ports.append(PortDevice(dname, f"Cam {i+1}", "camera", vlan=50, is_camera=True))

    return rows, ports


def build_hernaiz_devices(co: int, totals: dict[str, int]) -> tuple[list[dict[str, Any]], list[PortDevice]]:
    rows, ports = build_gates_devices(co, {**totals, "dome camera": 0, "doorbell camera": 0})
    return rows, ports


def build_kelly_devices(co: int, skus: dict[str, int]) -> tuple[list[dict[str, Any]], list[PortDevice]]:
    """Kelly report lists qty per SKU; model as N parallel building racks (default 3)."""
    rows: list[dict[str, Any]] = []
    ports: list[PortDevice] = []

    def qty_for(part: str) -> int:
        for k, v in skus.items():
            if part.upper() in k.upper():
                return int(v)
        return 0

    sites = max(qty_for("AN-520"), 1)
    for s in range(sites):
        rk = f"Building {s + 1} Rack"
        rows.append(_dev(rk, "Router", "AN-520-RT", co, 1, 1, "-", "-", "router"))
        rows.append(_dev(rk, "Switch 8P", "AN-620-SW-R-8-POE", co, 1, 2, "-", "-", "switch"))
        rows.append(_dev(rk, "Switch 24P", "AN-420-SW-F-24-POE", co, 1, 3, "-", "-", "switch"))
        ap_name = f"Access Point B{s + 1}"
        rows.append(_dev(rk, ap_name, "AN-820-AP-I", co, 1, 16 + s, "Sw1-P?", "?", "ap"))
        ports.append(PortDevice(ap_name, rk, "ap", vlan=1))
        ams_name = f"Audio Matrix B{s + 1}"
        rows.append(_dev(rk, ams_name, "TS-AMS16", co, 20, 16 + s, "Sw1-P?", "?", "audio_matrix"))
        ports.append(PortDevice(ams_name, rk, "audio_matrix", vlan=20))
    return rows, ports


def apply_port_plan(
    devices: list[dict[str, Any]],
    plan,
) -> None:
    by_sw = {r["device"]: r for r in plan.switch_rows}
    by_nv = {r["device"]: r for r in plan.nvr_rows}
    for d in devices:
        if d.get("wireless"):
            continue
        name = d["device"]
        if name in by_sw:
            pr = by_sw[name]
            d["switch_port"] = f"Sw1-P{pr['port']}"
            d["cable_label"] = pr.get("cable_label", "-")
        elif name in by_nv:
            nr = by_nv[name]
            d["switch_port"] = nr["port"]
            d["cable_label"] = nr.get("cable_label", "-")


def render_markdown(
    project_name: str,
    address: str,
    version: int,
    vlan_rows: list[dict[str, str]],
    devices: list[dict[str, Any]],
    access_rows: list[dict[str, Any]],
    cable_rows: list[dict[str, str]],
    switch_rows: list[dict[str, Any]],
    nvr_rows: list[dict[str, Any]],
    checklist: list[dict[str, str]],
    codes_source: str | None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# System Shell — {project_name}",
        f"## {address}",
        "",
        f"Generated: {now} | Version: {version}",
        "",
        "### Network Overview",
        "| VLAN | Subnet | Purpose | Devices |",
        "|------|--------|---------|---------|",
    ]
    for vr in vlan_rows:
        lines.append(
            f"| {vr['vlan']} | {vr['subnet']} | {vr['purpose']} | {vr['devices']} |"
        )
    lines += [
        "",
        "### Device Registry",
        "| Room | Device | Model | IP | VLAN | Switch Port | Cable Label | Status |",
        "|------|--------|-------|-----|------|-------------|-------------|--------|",
    ]
    for d in devices:
        lines.append(
            f"| {d['room']} | {d['device']} | {d['model']} | {d['ip']} | {d['vlan']} | "
            f"{d['switch_port']} | {d['cable_label']} | {d['status']} |"
        )
    lines += ["", "### Access Codes & Credentials"]
    if codes_source:
        lines.append(f"_Source: `{codes_source}` (auto-extracted)_")
        lines.append("")
    lines += [
        "| System | Username | Password | Notes |",
        "|--------|----------|----------|-------|",
    ]
    for r in access_rows:
        user = r.get("username") or r.get("credential", "")
        pwd = r.get("password") or r.get("value", "")
        lines.append(
            f"| {r.get('system', '')} | {user} | {pwd} | {r.get('notes', '')} |"
        )
    lines += [
        "",
        "### Cable Label Schedule",
        "| Label | From | To | Cable Type | Length Est |",
        "|-------|------|-----|------------|------------|",
    ]
    for c in cable_rows:
        lines.append(
            f"| {c.get('label', '')} | {c.get('from_room', '')} | {c.get('to', '')} | Cat6 | TBD |"
        )
    lines += [
        "",
        "### Switch Port Allocation",
        "| Port | Device | VLAN | PoE | Cable Label |",
        "|------|--------|------|-----|-------------|",
    ]
    for r in switch_rows:
        poe = "✅" if r.get("poe") else "—"
        lines.append(
            f"| {r['port']} | {r['device']} | {r.get('vlan', '')} | {poe} | {r.get('cable_label', '')} |"
        )
    if nvr_rows:
        lines += [
            "",
            "### NVR PoE Ports (cameras only)",
            "| Port | Device | VLAN | PoE | Cable Label |",
            "|------|--------|------|-----|-------------|",
        ]
        for r in nvr_rows:
            lines.append(
                f"| {r['port']} | {r['device']} | {r.get('vlan', '')} | ✅ | {r.get('cable_label', '')} |"
            )
    lines += [
        "",
        "### Commissioning Checklist",
        "| # | Task | Status |",
        "|---|------|--------|",
    ]
    for i, item in enumerate(checklist, start=1):
        lines.append(f"| {i} | {item.get('task', '')} | {item.get('status', '⬜')} |")
    lines.append("")
    return "\n".join(lines)


def generate_shell(
    project_slug: str,
    config_path: Path | None = None,
    rollup_path: Path | None = None,
    repo_root: Path | None = None,
    main_switch_model: str = "AN-620-SW-R-24-POE",
    nvr_model: str = "Luma-NVR-16CH-POE",
) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    reg = load_client_registry(root / "knowledge" / "network" / "client_registry.json")
    client_num, rec = lookup_client(reg, project_slug)
    co = client_octet(client_num)
    name = rec.get("name", project_slug.title())
    address = rec.get("address", "")

    devices: list[dict[str, Any]] = []
    ports: list[PortDevice] = []
    cam_count = 0

    if config_path:
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        proj = cfg.get("project") or {}
        name = proj.get("name", name)
        address = proj.get("address", address)
        devices, ports = build_topletz_devices(co, cfg)
        scope = cfg.get("scope") or {}
        cam_count = len(scope.get("camera_locations") or [])
    elif rollup_path:
        rp = Path(rollup_path)
        rp_name = rp.name.lower()
        if project_slug.lower() == "kelly" or "kelly" in rp_name:
            skus = parse_kelly_skus(rp)
            devices, ports = build_kelly_devices(co, skus)
            cam_count = 0
        else:
            totals = parse_equipment_rollup(rp)
            if "gates" in rp_name:
                devices, ports = build_gates_devices(co, totals)
            else:
                devices, ports = build_hernaiz_devices(co, totals)
            cam_count = totals.get("dome camera", 0) + totals.get("doorbell camera", 0)
    elif project_slug.lower() == "kelly":
        kpath = root / "knowledge" / "reports" / "Kelly_Proposal_Intelligence.md"
        skus = parse_kelly_skus(kpath)
        devices, ports = build_kelly_devices(co, skus)
        cam_count = 0
    else:
        raise ValueError("Provide config_path, rollup_path, or use project_slug=kelly")

    plan = allocate_ports(ports, main_switch_model, nvr_model, root / "knowledge" / "hardware" / "networking.json")
    apply_port_plan(devices, plan)

    ac_rows, ac_src = merge_access_codes(project_slug)
    access_codes_source = "auto_extracted" if ac_src else None
    if not ac_rows:
        ac_rows = default_placeholder_codes(name, co)

    vlan_rows = _vlan_overview_rows(
        co,
        has_iot=any(d.get("vlan") == "30" for d in devices),
        has_guest=True,
        cam_count=cam_count or len(plan.nvr_rows),
    )

    checklist = [{"task": t, "status": "⬜"} for t in CHECKLIST_DEFAULT]

    out_dir = root / "knowledge" / "projects" / project_slug.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "system_shell.md"
    state_path = out_dir / "system_shell_data.json"

    payload = {
        "project_slug": project_slug.lower(),
        "project_name": name,
        "address": address,
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "access_codes_source": access_codes_source,
        "devices": devices,
        "checklist": checklist,
        "port_plan": {
            "switch_rows": plan.switch_rows,
            "nvr_rows": plan.nvr_rows,
            "warnings": plan.warnings,
        },
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = render_markdown(
        name,
        address,
        1,
        vlan_rows,
        devices,
        ac_rows,
        plan.cable_labels,
        plan.switch_rows,
        plan.nvr_rows,
        checklist,
        ac_src,
    )
    md_path.write_text(md, encoding="utf-8")
    for w in plan.warnings:
        logger.warning("%s", w)

    return {
        "markdown_path": str(md_path),
        "state_path": str(state_path),
        "summary": {"devices": len(devices), "warnings": plan.warnings},
    }


def export_markdown_to_pdf(markdown_path: Path, pdf_path: Path) -> bool:
    """
    Export markdown to PDF when pandoc is available.

    Returns True on success, False when export tool is unavailable/failed.
    """
    pandoc = shutil.which("pandoc")
    if not pandoc:
        logger.error("PDF export requires pandoc in PATH")
        return False
    try:
        subprocess.run(
            [pandoc, str(markdown_path), "-o", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return True
    except Exception as exc:
        logger.error("PDF export failed: %s", exc)
        return False


def cmd_show(slug: str) -> int:
    p = REPO_ROOT / "knowledge" / "projects" / slug.lower() / "system_shell.md"
    if not p.is_file():
        logger.error("Missing %s — run --generate first", p)
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


def cmd_update(slug: str, device: str, ip: str | None, status: str | None) -> int:
    state_path = REPO_ROOT / "knowledge" / "projects" / slug.lower() / "system_shell_data.json"
    if not state_path.is_file():
        logger.error("Missing state %s", state_path)
        return 1
    data = json.loads(state_path.read_text(encoding="utf-8"))
    found = False
    for d in data.get("devices", []):
        if device.lower() in d.get("device", "").lower():
            if ip:
                d["ip"] = ip
            if status:
                d["status"] = status
            found = True
    if not found:
        logger.error("No device matching %r", device)
        return 1
    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    reg = load_client_registry()
    client_num, rec = lookup_client(reg, slug)
    co = client_octet(client_num)
    name = data.get("project_name", slug)
    address = data.get("address", "")
    plan_data = data.get("port_plan") or {}
    pr = plan_data.get("switch_rows") or []
    nr = plan_data.get("nvr_rows") or []
    ac_rows, ac_src = merge_access_codes(slug)
    if not ac_rows:
        ac_rows = default_placeholder_codes(name, co)
    vlan_rows = _vlan_overview_rows(co, True, True, len(nr))
    md = render_markdown(
        name,
        address,
        int(data.get("version", 1)),
        vlan_rows,
        data["devices"],
        ac_rows,
        [],
        pr,
        nr,
        data.get("checklist") or [],
        ac_src,
    )
    out_md = REPO_ROOT / "knowledge" / "projects" / slug.lower() / "system_shell.md"
    out_md.write_text(md, encoding="utf-8")
    logger.info("Updated %s", out_md)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="System shell generator (Symphony IP scheme)")
    ap.add_argument("--generate", metavar="SLUG", help="Project slug (registry + output path)")
    ap.add_argument("--config", type=Path, help="project-config.yaml")
    ap.add_argument("--rollup", type=Path, help="Equipment rollup markdown")
    ap.add_argument("--show", metavar="SLUG")
    ap.add_argument("--update", metavar="SLUG")
    ap.add_argument("--device", help="Device name substring (with --update)")
    ap.add_argument("--ip", help="New IP (with --update)")
    ap.add_argument("--status", help="Status emoji/text (with --update)")
    ap.add_argument("--export", metavar="SLUG")
    ap.add_argument("--export-labels", metavar="SLUG")
    ap.add_argument("--format", default="md", choices=("md", "pdf", "csv"))
    args = ap.parse_args()

    if args.generate:
        try:
            res = generate_shell(
                args.generate,
                config_path=args.config,
                rollup_path=args.rollup,
            )
        except Exception as e:
            logger.error("%s", e)
            return 1
        print(json.dumps(res, indent=2))
        return 0

    if args.show:
        return cmd_show(args.show)

    if args.update:
        if not args.device:
            logger.error("--device required with --update")
            return 1
        return cmd_update(args.update, args.device, args.ip, args.status)

    if args.export_labels:
        state_path = (
            REPO_ROOT / "knowledge" / "projects" / args.export_labels.lower() / "system_shell_data.json"
        )
        if not state_path.is_file():
            logger.error("Generate shell first: %s", state_path)
            return 1
        data = json.loads(state_path.read_text(encoding="utf-8"))
        from port_allocator import PortPlan

        pr = data.get("port_plan") or {}
        plan = PortPlan(
            switch_rows=pr.get("switch_rows") or [],
            nvr_rows=pr.get("nvr_rows") or [],
            cable_labels=[],
        )
        for row in pr.get("switch_rows") or []:
            plan.cable_labels.append(
                {
                    "label": row.get("cable_label", ""),
                    "from_room": row.get("device", ""),
                    "to": f"Sw1-P{row.get('port')}",
                }
            )
        out = (
            REPO_ROOT
            / "knowledge"
            / "projects"
            / args.export_labels.lower()
            / "cable_labels.csv"
        )
        export_labels_csv(plan, out)
        print(out)
        return 0

    if args.export:
        p = REPO_ROOT / "knowledge" / "projects" / args.export.lower() / "system_shell.md"
        if not p.is_file():
            return 1
        if args.format == "pdf":
            out_pdf = p.with_suffix(".pdf")
            if not export_markdown_to_pdf(p, out_pdf):
                return 3
            print(out_pdf)
            return 0
        print(p.read_text(encoding="utf-8"))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
