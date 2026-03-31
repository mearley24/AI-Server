#!/usr/bin/env python3
"""
SOW Assembler — Reads a project config and assembles a complete Scope of Work
from modular building blocks in knowledge/sow-blocks/.

Usage:
    python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml
    python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml --output sow-output.md
    python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml --format dtools
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


def load_sow_blocks(blocks_dir):
    """Load all SOW building blocks from the blocks directory."""
    blocks = []
    blocks_path = Path(blocks_dir)

    if not blocks_path.exists():
        print(f"ERROR: SOW blocks directory not found: {blocks_dir}", file=sys.stderr)
        sys.exit(1)

    for md_file in sorted(blocks_path.glob("*.md")):
        metadata, body = load_yaml_frontmatter(md_file)
        if metadata:
            blocks.append({
                "file": md_file.name,
                "metadata": metadata,
                "body": body,
            })

    # Sort by order field
    blocks.sort(key=lambda b: b["metadata"].get("order", 999))
    return blocks


def should_include_block(block, config):
    """Determine if a block should be included based on project scope."""
    meta = block["metadata"]

    if meta.get("always_include", False):
        return True

    trigger = meta.get("trigger")
    if not trigger:
        return False

    scope = config.get("scope", {})

    # Map triggers to scope flags
    trigger_map = {
        "shade_prewire": scope.get("shade_prewire", False),
        "camera_prewire": scope.get("camera_prewire", False),
        "security_panel_prewire": scope.get("security_panel_prewire", False),
        "security_sensor_prewire": scope.get("security_sensor_prewire", False),
        "conduit_future": scope.get("conduit_future", False),
        "control4": scope.get("control4", False),
        "qolsys_integration": scope.get("qolsys_integration", False),
        "distributed_audio": scope.get("distributed_audio", False),
        "ipad": scope.get("touchscreen_type") == "ipad",
        "t5": scope.get("touchscreen_type") == "t5",
    }

    return trigger_map.get(trigger, False)


def apply_template_vars(text, config):
    """Replace {{variable}} placeholders with project config values."""
    project = config.get("project", {})
    scope = config.get("scope", {})

    replacements = {
        "project_name": project.get("name", ""),
        "address": project.get("address", ""),
        "client": project.get("client", ""),
        "quote": project.get("quote", ""),
        "gc": project.get("gc", ""),
        "architect": project.get("architect", ""),
        "security_provider": scope.get("security_provider", ""),
        "security_panel_model": scope.get("security_panel_model", "Qolsys IQ Panel 4"),
        "security_panel_location": scope.get("security_panel_location", ""),
        "security_keypad_location": scope.get("security_keypad_location", ""),
    }

    # List-type replacements
    camera_locations = scope.get("camera_locations", [])
    replacements["camera_locations"] = ", ".join(camera_locations)

    ipad_locations = scope.get("ipad_locations", [])
    replacements["ipad_locations"] = " and ".join(ipad_locations)

    t5_locations = scope.get("t5_locations", [])
    replacements["t5_locations"] = " and ".join(t5_locations)

    # Build dynamic exclusions
    exclusions = config.get("exclusions", [])
    if exclusions:
        # Items with enhanced descriptions get special handling
        enhanced = {"CORE5", "10G switching"}
        standard = [e for e in exclusions if e not in enhanced]

        parts = []
        # Combine standard exclusions into a readable sentence
        if len(standard) >= 4:
            items = [e.lower() for e in standard[:4]]
            combined = "No " + ", no ".join(items) + " are included."
            parts.append(combined)
            for e in standard[4:]:
                parts.append(f"{e} is excluded.")
        elif standard:
            items = [e.lower() for e in standard]
            combined = "No " + ", no ".join(items) + " are included."
            parts.append(combined)

        # Add enhanced exclusion lines
        if "CORE5" in exclusions:
            parts.append("CORE5 is excluded, with CORE3 platform only.")
        if "10G switching" in exclusions:
            parts.append("10G switching and backbone architecture are excluded, with 1G backbone architecture only.")

        replacements["dynamic_exclusions"] = "\n\n".join(parts)
    else:
        replacements["dynamic_exclusions"] = ""

    # Pending items note for security sensor prewire
    if not scope.get("security_sensor_prewire", False):
        sensor_note = "Security sensor prewire (Cat6 to individual sensor locations) is not included in this base scope. This will be added via change order once the {{security_provider}} sensor plan is finalized."
        sensor_note = sensor_note.replace("{{security_provider}}", scope.get("security_provider", ""))
        replacements["dynamic_exclusions"] += f"\n\n{sensor_note}"

    # Apply all replacements
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", str(value))

    return text


def load_change_log(project_dir):
    """Load scope change log from confirmed-decisions files."""
    changes = []
    project_path = Path(project_dir)

    for f in sorted(project_path.glob("confirmed-decisions*.md")):
        text = f.read_text(encoding="utf-8")
        # Extract table rows (skip header rows)
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("|") and not line.startswith("| #") and not line.startswith("|--"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 4:
                    changes.append({
                        "item": parts[1] if len(parts) > 1 else "",
                        "decision": parts[2] if len(parts) > 2 else "",
                        "notes": parts[3] if len(parts) > 3 else "",
                    })

    return changes


def assemble_sow(config_path, output_format="markdown"):
    """Assemble the complete SOW from project config and building blocks."""
    config = load_project_config(config_path)
    project = config.get("project", {})

    # Resolve paths relative to repo root
    repo_root = Path(config_path).resolve().parent.parent.parent
    if not (repo_root / "knowledge" / "sow-blocks").exists():
        repo_root = Path(config_path).resolve().parent.parent

    blocks_dir = repo_root / "knowledge" / "sow-blocks"
    project_dir = Path(config_path).resolve().parent

    blocks = load_sow_blocks(blocks_dir)

    # Filter and assemble
    included_blocks = [b for b in blocks if should_include_block(b, config)]

    # Group blocks by section for clean output
    sections = {}
    for block in included_blocks:
        section = block["metadata"].get("section", "GENERAL")
        if section not in sections:
            sections[section] = []
        sections[section].append(block)

    # Build the SOW document
    today = datetime.date.today().strftime("%B %d, %Y")
    lines = []

    lines.append(f"# {project.get('name', 'Project')} — Scope of Work")
    lines.append(f"## {project.get('address', '')}")
    lines.append(f"### {project.get('quote', '')} | Generated {today}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for section_name, section_blocks in sections.items():
        lines.append(f"## {section_name}")
        lines.append("")
        for block in section_blocks:
            body = apply_template_vars(block["body"], config)
            lines.append(body)
            lines.append("")

    # Add scope change log
    changes = load_change_log(project_dir)
    if changes:
        lines.append("---")
        lines.append("")
        lines.append("## SCOPE CHANGE LOG")
        lines.append("")
        lines.append("| # | Item | Decision | Notes |")
        lines.append("|---|------|----------|-------|")
        for i, change in enumerate(changes, 1):
            lines.append(f"| {i} | {change['item']} | {change['decision']} | {change['notes']} |")
        lines.append("")

    sow_text = "\n".join(lines)

    if output_format == "dtools":
        # Strip markdown formatting for plain text paste into D-Tools
        # Process from most hashes to fewest to avoid partial matches
        sow_text = re.sub(r"^#{1,6}\s+", "", sow_text, flags=re.MULTILINE)
        sow_text = sow_text.replace("---", "")
        sow_text = re.sub(r"\*\*(.*?)\*\*", r"\1", sow_text)
        sow_text = re.sub(r"\*(.*?)\*", r"\1", sow_text)
        # Clean up excessive blank lines
        sow_text = re.sub(r"\n{3,}", "\n\n", sow_text)

    return sow_text


def main():
    parser = argparse.ArgumentParser(
        description="Assemble a Scope of Work from project config and SOW building blocks."
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
    parser.add_argument(
        "--format", "-f",
        choices=["markdown", "dtools"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    sow = assemble_sow(args.config, output_format=args.format)

    if args.output:
        Path(args.output).write_text(sow, encoding="utf-8")
        print(f"SOW written to: {args.output}")
    else:
        print(sow)


if __name__ == "__main__":
    main()
