#!/usr/bin/env python3
import csv
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

BASE = Path.home() / "AI-Server" / "knowledge"
REPORTS = BASE / "reports"
OUT = BASE / "proposal_library" / "room_packages"

OUT.mkdir(parents=True, exist_ok=True)

CSV_PATH = REPORTS / "SKU_Room_Map.csv"

rows = []
if CSV_PATH.exists():
    with CSV_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

archetype_counts = defaultdict(Counter)

for r in rows:
    archetype = r.get("archetype")
    sku = r.get("sku")
    if archetype and archetype != "Unknown" and sku:
        archetype_counts[archetype][sku] += 1

for archetype, counter in archetype_counts.items():
    if sum(counter.values()) < 3:
        continue

    lines = []
    lines.append(f"# {archetype} Package")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("| Count | SKU |")
    lines.append("|---:|---|")

    for sku, count in counter.most_common(20):
        lines.append(f"| {count} | {sku} |")

    (OUT / f"{archetype.replace('/', '_')}.md").write_text("\n".join(lines), encoding="utf-8")

print("Room packages built.")
