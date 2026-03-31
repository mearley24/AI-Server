#!/usr/bin/env python3
"""
Pre-Flight Checker — Validates a project SOW against confirmed decisions
and the product knowledge base before an agreement goes out.

Usage:
    python3 openclaw/preflight_check.py knowledge/topletz/project-config.yaml
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import yaml


def load_yaml_frontmatter(filepath):
    """Parse a markdown file with YAML frontmatter, returning (metadata, body)."""
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        metadata = {}

    body = parts[2].strip()
    return metadata, body


def load_project_config(config_path):
    """Load the project configuration YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_confirmed_decisions(project_dir):
    """Load all confirmed decisions from the project directory."""
    decisions = []
    project_path = Path(project_dir)

    for f in sorted(project_path.glob("confirmed-decisions*.md")):
        text = f.read_text(encoding="utf-8")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("|") and not line.startswith("| #") and not line.startswith("|--"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 3:
                    decisions.append({
                        "item": parts[1] if len(parts) > 1 else "",
                        "decision": parts[2] if len(parts) > 2 else "",
                        "notes": parts[3] if len(parts) > 3 else "",
                    })

    return decisions


def load_sow_blocks(blocks_dir):
    """Load all SOW building blocks."""
    blocks = []
    blocks_path = Path(blocks_dir)

    if not blocks_path.exists():
        return blocks

    for md_file in sorted(blocks_path.glob("*.md")):
        metadata, body = load_yaml_frontmatter(md_file)
        if metadata:
            blocks.append({
                "file": md_file.name,
                "metadata": metadata,
                "body": body,
            })

    return blocks


def load_products(products_dir):
    """Load all product knowledge base files."""
    products = []
    products_path = Path(products_dir)

    if not products_path.exists():
        return products

    for md_file in sorted(products_path.glob("*.md")):
        metadata, body = load_yaml_frontmatter(md_file)
        if metadata:
            products.append({
                "file": md_file.name,
                "metadata": metadata,
                "body": body,
            })

    return products


def check_decision_in_sow(decision, blocks, config):
    """Check if a confirmed decision is reflected in the SOW blocks."""
    item = decision["item"].lower()
    decision_text = decision["decision"].lower()
    scope = config.get("scope", {})

    # Map decision items to SOW block triggers and sections
    decision_map = {
        "lighting": {
            "check": scope.get("control4", False),
            "section": "LIGHTING CONTROL SYSTEM",
            "block_id": "control4-lighting",
        },
        "shade prewire": {
            "check": scope.get("shade_prewire", False),
            "section": "SHADE PREWIRE",
            "block_id": "prewire-shade",
        },
        "security prewire": {
            "check": scope.get("security_panel_prewire", False),
            "section": "SECURITY PANEL PREWIRE",
            "block_id": "prewire-security-panel",
        },
        "cameras": {
            "check": scope.get("camera_prewire", False),
            "section": "CAMERA PREWIRE",
            "block_id": "prewire-camera",
        },
        "camera": {
            "check": scope.get("camera_prewire", False),
            "section": "CAMERA PREWIRE",
            "block_id": "prewire-camera",
        },
        "touchscreens": {
            "check": scope.get("touchscreen_type") == "ipad",
            "section": "CONTROL4 AUTOMATION",
            "block_id": "ipad-interfaces",
        },
        "tuning period": {
            "check": True,
            "section": "COMMISSIONING",
            "block_id": "commissioning",
        },
        "security panel": {
            "check": scope.get("security_panel_prewire", False),
            "section": "SECURITY PANEL PREWIRE",
            "block_id": "prewire-security-panel",
        },
        "panel location": {
            "check": scope.get("security_panel_prewire", False),
            "section": "SECURITY PANEL PREWIRE",
            "block_id": "prewire-security-panel",
        },
        "qolsys": {
            "check": scope.get("qolsys_integration", False),
            "section": "QOLSYS INTEGRATION",
            "block_id": "qolsys-integration",
        },
        "qolysys": {
            "check": scope.get("qolsys_integration", False),
            "section": "QOLSYS INTEGRATION",
            "block_id": "qolsys-integration",
        },
        "superior sensors": {
            "check": scope.get("security_sensor_prewire", False),
            "section": "SECURITY SENSOR PREWIRE",
            "block_id": "prewire-security-sensors",
        },
    }

    # Find the best match
    for key, mapping in decision_map.items():
        if key in item:
            return mapping

    return None


def run_preflight(config_path):
    """Run the full pre-flight check and return the report."""
    config = load_project_config(config_path)
    project = config.get("project", {})
    scope = config.get("scope", {})

    # Resolve paths
    project_dir = Path(config_path).resolve().parent
    repo_root = project_dir.parent.parent
    if not (repo_root / "knowledge" / "sow-blocks").exists():
        repo_root = project_dir.parent

    blocks_dir = repo_root / "knowledge" / "sow-blocks"
    products_dir = repo_root / "knowledge" / "products"

    # Load everything
    decisions = load_confirmed_decisions(project_dir)
    blocks = load_sow_blocks(blocks_dir)
    products = load_products(products_dir)

    today = datetime.date.today().strftime("%Y-%m-%d")
    results = {
        "pass": [],
        "warn": [],
        "fail": [],
        "info": [],
    }

    report = []
    report.append(f"PRE-FLIGHT CHECK: {project.get('name', 'Unknown')} ({project.get('quote', '')})")
    report.append(f"Date: {today}")
    report.append("")

    # --- Check 1: Confirmed decisions vs SOW ---
    report.append("CONFIRMED DECISIONS vs SOW:")

    for decision in decisions:
        mapping = check_decision_in_sow(decision, blocks, config)
        item_desc = f"{decision['item']} — {decision['decision']}"

        if mapping is None:
            results["warn"].append(item_desc)
            report.append(f"[WARN] {item_desc} — no matching SOW section found")
            continue

        if mapping["check"]:
            results["pass"].append(item_desc)
            report.append(f"[PASS] {item_desc} — in SOW Section: {mapping['section']}")
        else:
            # Check if it's explicitly deferred or pending external input
            notes = decision.get("notes", "").lower()
            decision_lower = decision.get("decision", "").lower()
            if any(kw in notes or kw in decision_lower for kw in
                   ["pending", "change order", "deferred", "coming from", "tbd", "future"]):
                results["warn"].append(item_desc)
                report.append(f"[WARN] {item_desc} — marked as change order (pending)")
            else:
                results["fail"].append(item_desc)
                report.append(f"[FAIL] {item_desc} — decision confirmed but NOT in scope config")

    report.append("")

    # --- Check 2: Products ---
    report.append("PRODUCTS:")

    # Check if all known product references exist in knowledge base
    product_names = [p["metadata"].get("name", "").lower() for p in products]
    product_skus = [p["metadata"].get("sku", "").lower() for p in products]

    if products:
        results["pass"].append("Product knowledge base loaded")
        report.append(f"[PASS] Product knowledge base: {len(products)} products found")
    else:
        results["fail"].append("No product knowledge base")
        report.append("[FAIL] No product knowledge base found")

    # Check D-Tools status
    not_in_dtools = [
        p for p in products
        if not p["metadata"].get("in_d_tools", True)
    ]
    for p in not_in_dtools:
        name = p["metadata"].get("name", p["file"])
        results["warn"].append(f"{name} not in D-Tools")
        report.append(f"[WARN] {name} not yet in D-Tools (in_d_tools: false)")

    if not not_in_dtools and products:
        results["pass"].append("All products in D-Tools")
        report.append("[PASS] All products marked as in D-Tools")

    report.append("")

    # --- Check 3: Scope consistency ---
    report.append("SCOPE CONSISTENCY:")

    # Check that triggered blocks have matching scope flags
    if scope.get("control4") and scope.get("lighting_platform") != "control4":
        results["warn"].append("Control4 enabled but lighting platform mismatch")
        report.append("[WARN] Control4 enabled but lighting_platform is not 'control4'")
    else:
        results["pass"].append("Lighting platform consistent")
        report.append("[PASS] Lighting platform matches control system")

    if scope.get("qolsys_integration") and not scope.get("security_panel_prewire"):
        results["warn"].append("Qolsys integration without panel prewire")
        report.append("[WARN] Qolsys integration enabled but security panel prewire is off")
    elif scope.get("qolsys_integration"):
        results["pass"].append("Qolsys integration with panel prewire")
        report.append("[PASS] Qolsys integration and security panel prewire both enabled")

    if scope.get("touchscreen_type") == "ipad" and not scope.get("ipad_locations"):
        results["warn"].append("iPad type selected but no locations specified")
        report.append("[WARN] Touchscreen type is 'ipad' but no ipad_locations specified")
    elif scope.get("touchscreen_type") == "ipad":
        locs = ", ".join(scope.get("ipad_locations", []))
        results["pass"].append("iPad locations specified")
        report.append(f"[PASS] iPad locations: {locs}")

    if scope.get("camera_prewire") and not scope.get("camera_locations"):
        results["warn"].append("Camera prewire on but no locations")
        report.append("[WARN] Camera prewire enabled but no camera_locations specified")
    elif scope.get("camera_prewire"):
        locs = ", ".join(scope.get("camera_locations", []))
        results["pass"].append("Camera locations specified")
        report.append(f"[PASS] Camera prewire locations: {locs}")

    report.append("")

    # --- Check 4: Pricing ---
    report.append("PRICING:")
    results["info"].append("Pricing section has placeholders — pending D-Tools V4 export")
    report.append("[INFO] Pricing section has placeholders — pending D-Tools V4 export")
    report.append("")

    # --- Summary ---
    total_pass = len(results["pass"])
    total_warn = len(results["warn"])
    total_fail = len(results["fail"])

    status = "Ready for review" if total_fail == 0 else "REQUIRES ATTENTION"
    report.append(f"RESULT: {total_pass} PASS, {total_warn} WARN, {total_fail} FAIL — {status}")

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="Run pre-flight checks on a project before agreement goes out."
    )
    parser.add_argument(
        "config",
        help="Path to project-config.yaml",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
        default=None,
    )

    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    report = run_preflight(args.config)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Pre-flight report written to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
