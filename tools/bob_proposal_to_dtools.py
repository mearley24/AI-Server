#!/usr/bin/env python3
"""
Convert proposal intelligence for a project into a D-Tools importable CSV.

D-Tools SI expects: Model (required), Manufacturer, Category.
We add Quantity and Room for proposal context when building line items.

Usage: python bob_proposal_to_dtools.py <project_name>
"""
import csv
import sys
from pathlib import Path
from collections import Counter

BASE = Path.home() / "AI-Server" / "knowledge"
EXTRACTED = BASE / "Extracted_Knowledge"
REPORTS = BASE / "reports"
ROOM_MAP = REPORTS / "SKU_Room_Map.csv"
ROOM_PACKAGES = BASE / "proposal_library" / "room_packages"


def load_project_skus(project_name: str) -> list[str]:
    skus = []
    for f in EXTRACTED.rglob("*.json"):
        if project_name.lower() in str(f).lower():
            import json
            data = json.loads(f.read_text())
            skus.extend(data.get("models_or_skus_guess", []))
    return skus


def load_sku_metadata() -> dict[str, dict]:
    """Load manufacturer/category from SKU_Room_Map, preferring non-Unknown."""
    meta = {}
    if not ROOM_MAP.exists():
        return meta
    with ROOM_MAP.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            sku = row.get("sku", "").strip()
            if not sku or sku == "sku":
                continue
            if sku in meta:
                # Prefer non-Unknown
                m, c = meta[sku]["manufacturer"], meta[sku]["category"]
                nm, nc = row.get("manufacturer_guess", "Unknown"), row.get("category_guess", "Unknown")
                if (nm and nm != "Unknown") or (nc and nc != "Unknown"):
                    meta[sku] = {
                        "manufacturer": nm if nm != "Unknown" else m,
                        "category": nc if nc != "Unknown" else c,
                    }
            else:
                meta[sku] = {
                    "manufacturer": row.get("manufacturer_guess", "Unknown"),
                    "category": row.get("category_guess", "Unknown"),
                }
    return meta


def load_room_for_sku() -> dict[str, str]:
    """Map SKU -> primary room from room packages."""
    sku_to_room = {}
    for md in ROOM_PACKAGES.glob("*.md"):
        room_name = md.stem.replace("_", "/")
        lines = md.read_text().splitlines()
        for line in lines:
            if "|" in line and not line.startswith("|---"):
                parts = line.split("|")
                if len(parts) >= 3:
                    sku = parts[2].strip()
                    if sku and sku != "SKU" and sku not in sku_to_room:
                        sku_to_room[sku] = room_name
    return sku_to_room


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: bob_proposal_to_dtools.py <project_name>")
        sys.exit(1)

    project_name = sys.argv[1]
    skus = load_project_skus(project_name)
    if not skus:
        print(f"No SKUs found for project '{project_name}'.")
        sys.exit(1)

    sku_counts = Counter(skus)
    meta = load_sku_metadata()
    sku_to_room = load_room_for_sku()

    # D-Tools SI import: Model (required), Manufacturer, Category
    # Extras: Quantity, Room for proposal context
    rows = []
    for sku, qty in sku_counts.most_common():
        m = meta.get(sku, {})
        rows.append({
            "Model": sku,
            "Manufacturer": m.get("manufacturer", "Unknown"),
            "Category": m.get("category", "Unknown"),
            "Quantity": str(qty),
            "Room": sku_to_room.get(sku, ""),
        })

    out_file = REPORTS / f"{project_name}_D-Tools_Import.csv"
    with out_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Model", "Manufacturer", "Category", "Quantity", "Room"])
        w.writeheader()
        w.writerows(rows)

    print(f"D-Tools import file written to {out_file}")


if __name__ == "__main__":
    main()
