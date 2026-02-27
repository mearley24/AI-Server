#!/usr/bin/env python3
"""
client_knowledge_builder.py — Generate a custom Ollama Modelfile from D-Tools data

Usage:
    python3 client_knowledge_builder.py \\
        --client "The Andersons" \\
        --dtools-csv /path/to/andersons_dtools.csv \\
        --templates ./troubleshooting_templates/ \\
        --output ./modelfiles/andersons.Modelfile
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {"audio", "video", "lighting", "networking", "cameras", "control", "unknown"}

BASE_MODEL = "llama3"  # Ollama base model

SYSTEM_PROMPT_TEMPLATE = """You are Symphony Concierge, the private home assistant for {client_name}.

You have complete knowledge of all AV, smart-home, and networking systems installed in this home.
You assist the homeowner with:
- Answering questions about their systems
- Guided troubleshooting (step-by-step)
- Explaining how to use features
- Reporting issues that need a Symphony technician

Installed Systems
-----------------
{systems_block}

Rules
-----
- Answer in plain, friendly English. No jargon unless asked.
- If a step requires physical access to equipment, describe exactly where to find it.
- If the issue needs a technician, say: "This needs a Symphony technician. I'll flag it for the team."
- Never guess serial numbers or model specs not listed above.
- Keep responses concise — 3 sentences max unless step-by-step instructions are needed.

Emergency
---------
If the caller mentions a safety issue (fire, flood, electrical), immediately say:
"Please call 911 first. Once you are safe, Symphony will send a technician to assess the damage."
"""

# ─── D-Tools CSV ingestion ────────────────────────────────────────────────────

def load_dtools_csv(csv_path: str) -> list[dict]:
    """Parse a D-Tools CSV export into a list of equipment dicts."""
    required_cols = {"Project", "Room", "Category", "Manufacturer", "Model"}
    rows = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not required_cols.issubset(set(reader.fieldnames or [])):
            missing = required_cols - set(reader.fieldnames or [])
            print(f"[ERROR] D-Tools CSV missing required columns: {missing}", file=sys.stderr)
            sys.exit(1)

        for i, row in enumerate(reader, start=2):  # row 1 = header
            project = row.get("Project", "").strip()
            model   = row.get("Model",   "").strip()

            if not project or not model:
                print(f"[WARN] Row {i}: skipping — missing Project or Model", file=sys.stderr)
                continue

            category = row.get("Category", "").strip().lower().replace(" ", "_")
            if category not in VALID_CATEGORIES:
                print(f"[WARN] Row {i}: unknown category '{category}' — stored as 'unknown'", file=sys.stderr)
                category = "unknown"

            # Parse install date
            raw_date = row.get("InstallDate", "").strip()
            try:
                installed_at = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
            except ValueError:
                installed_at = raw_date or "unknown"

            rows.append({
                "client_name":  project,
                "location":     row.get("Room", "").strip().lower().replace(" ", "_"),
                "system_type":  category,
                "make":         row.get("Manufacturer", "").strip(),
                "model":        model,
                "serial":       row.get("SerialNumber", "").strip(),
                "installed_at": installed_at,
                "notes":        row.get("Notes", "").strip(),
            })

    return rows


def build_systems_block(rows: list[dict]) -> str:
    """Format equipment list grouped by room."""
    by_room: dict[str, list[str]] = {}

    for r in rows:
        room = r["location"] or "unassigned"
        serial_str = f", s/n {r['serial']}" if r["serial"] else ""
        date_str   = f", installed {r['installed_at']}" if r["installed_at"] != "unknown" else ""
        notes_str  = f" — {r['notes']}" if r["notes"] else ""

        line = f"  [{r['system_type']}] {r['make']} {r['model']}{serial_str}{date_str}{notes_str}"
        by_room.setdefault(room, []).append(line)

    parts = []
    for room in sorted(by_room):
        parts.append(f"\n{room.replace('_', ' ').title()}:")
        parts.extend(by_room[room])

    return "\n".join(parts)


# ─── Template ingestion ───────────────────────────────────────────────────────

def load_templates(templates_dir: str) -> str:
    """Concatenate all Markdown troubleshooting templates."""
    p = Path(templates_dir)
    if not p.is_dir():
        print(f"[WARN] Templates directory not found: {templates_dir}", file=sys.stderr)
        return ""

    parts = []
    for md_file in sorted(p.glob("*.md")):
        parts.append(f"\n\n## {md_file.stem.replace('_', ' ').title()} Troubleshooting\n")
        parts.append(md_file.read_text(encoding="utf-8"))

    return "".join(parts)


# ─── Modelfile generation ─────────────────────────────────────────────────────

def generate_modelfile(client_name: str, systems_block: str, templates_text: str) -> str:
    """Produce an Ollama Modelfile string."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        client_name=client_name,
        systems_block=systems_block or "  (No equipment records found)",
    )

    if templates_text:
        system_prompt += "\nTroubleshooting Guides\n----------------------\n" + templates_text

    # Escape backslashes for Modelfile syntax
    escaped = system_prompt.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')

    return f"""FROM {BASE_MODEL}

SYSTEM \"\"\"
{escaped}
\"\"\"

PARAMETER temperature 0.3
PARAMETER num_ctx 8192
PARAMETER stop "</s>"
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build a custom Ollama Modelfile from D-Tools data.")
    parser.add_argument("--client",    required=True, help="Client name (must match D-Tools Project field)")
    parser.add_argument("--dtools-csv",required=True, help="Path to D-Tools CSV export")
    parser.add_argument("--templates", default="./troubleshooting_templates", help="Directory of Markdown troubleshooting templates")
    parser.add_argument("--output",    default=None,  help="Output Modelfile path (default: ./<client>.Modelfile)")
    args = parser.parse_args()

    print(f"[builder] Loading D-Tools data from {args.dtools_csv}")
    rows = load_dtools_csv(args.dtools_csv)
    print(f"[builder] {len(rows)} equipment records loaded")

    # Filter to this client only
    client_rows = [r for r in rows if r["client_name"].lower() == args.client.lower()]
    print(f"[builder] {len(client_rows)} records for client '{args.client}'")

    systems_block = build_systems_block(client_rows)
    templates_text = load_templates(args.templates)

    modelfile_content = generate_modelfile(args.client, systems_block, templates_text)

    output_path = args.output or f"./{args.client.replace(' ', '_')}.Modelfile"
    Path(output_path).write_text(modelfile_content, encoding="utf-8")
    print(f"[builder] Modelfile written to {output_path}")


if __name__ == "__main__":
    main()
