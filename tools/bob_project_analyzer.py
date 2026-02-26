#!/usr/bin/env python3
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

BASE = Path.home() / "AI-Server" / "knowledge"
EXTRACTED = BASE / "Extracted_Knowledge"
REPORTS = BASE / "reports"
ROOM_PACKAGES = BASE / "proposal_library" / "room_packages"

def load_project_skus(project_name):
    skus = []
    for file in EXTRACTED.rglob("*.json"):
        if project_name.lower() in str(file).lower():
            import json
            data = json.loads(file.read_text())
            skus.extend(data.get("models_or_skus_guess", []))
    return skus

def load_room_packages():
    packages = {}
    for md in ROOM_PACKAGES.glob("*.md"):
        lines = md.read_text().splitlines()
        room_name = md.stem.replace("_", "/")
        skus = []
        for line in lines:
            if "|" in line and not line.startswith("|---"):
                parts = line.split("|")
                if len(parts) >= 3:
                    sku = parts[2].strip()
                    if sku and sku != "SKU":
                        skus.append(sku)
        packages[room_name] = skus
    return packages

def main():
    project_name = sys.argv[1]

    skus = load_project_skus(project_name)
    if not skus:
        print("No SKUs found for that project.")
        return

    sku_counts = Counter(skus)
    packages = load_room_packages()

    report_lines = []
    report_lines.append(f"# Proposal Intelligence: {project_name}")
    report_lines.append("")
    report_lines.append(f"Generated: {datetime.now()}")
    report_lines.append("")
    report_lines.append("## Detected Devices")
    report_lines.append("")
    report_lines.append("| Count | SKU |")
    report_lines.append("|---:|---|")

    for sku, count in sku_counts.most_common():
        report_lines.append(f"| {count} | {sku} |")

    report_lines.append("")
    report_lines.append("## Suggested Room Packages")

    for room, room_skus in packages.items():
        matches = [s for s in room_skus if s in sku_counts]
        if matches:
            report_lines.append(f"### {room}")
            for m in matches:
                report_lines.append(f"- {m}")
            report_lines.append("")

    out_file = REPORTS / f"{project_name}_Proposal_Intelligence.md"
    out_file.write_text("\n".join(report_lines))

    print(f"Proposal intelligence written to {out_file}")

if __name__ == "__main__":
    main()

