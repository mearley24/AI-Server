#!/usr/bin/env python3
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE = Path.home() / "AI-Server" / "knowledge"
EXTRACTED = BASE / "Extracted_Knowledge"
REPORTS = BASE / "reports"
VAULT = BASE / "manual_vault"
STATE = BASE / "state"
LOG = Path.home() / "AI-Server" / "logs" / "bob-inventory.log"

REPORTS.mkdir(parents=True, exist_ok=True)
VAULT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)
LOG.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

MANUFACTURER_HINTS = [
    ("Control4", re.compile(r"\b(C4|CORE|EA-|CA-|IOX|NEO)\b", re.I)),
    ("Triad", re.compile(r"\b(TRIAD|AMS|PAMP|RSP)\b", re.I)),
    ("Lutron", re.compile(r"\b(LUTRON|QSX|HQP|RR-|RA2|RA3|HWQS)\b", re.I)),
    ("Araknis", re.compile(r"\b(ARAKNIS|AN-)\b", re.I)),
    ("Pakedge", re.compile(r"\b(PAKEDGE)\b", re.I)),
    ("Snap One", re.compile(r"\b(SNAPAV|SNAP\s*ONE)\b", re.I)),
    ("Sony", re.compile(r"\b(SONY|STR-|ZA)\b", re.I)),
    ("Apple", re.compile(r"\b(APPLE|IPAD|IPHONE|MAC)\b", re.I)),
]

CATEGORY_HINTS = [
    ("Controller", re.compile(r"\b(CORE[135]|EA-[135]|CA-1|NEO)\b", re.I)),
    ("Audio Matrix", re.compile(r"\b(AMS\d+|TS-AMS\d+)\b", re.I)),
    ("Amplifier", re.compile(r"\b(PAMP\d+|RSP-\d+D-\d+|EA-DYN|AMP-)\b", re.I)),
    ("Keypad", re.compile(r"\b(KEYPAD|T3|T4)\b", re.I)),
    ("Lighting", re.compile(r"\b(DIMMER|SWITCH|QSX|RA2|RA3|HWQS|VANTAGE)\b", re.I)),
    ("Networking", re.compile(r"\b(AP|WAP|SW-|SWITCH|ROUTER|POE|VLAN|SFP)\b", re.I)),
    ("Camera/Security", re.compile(r"\b(CAM|NVR|ALARM|SENSOR|DOORBELL)\b", re.I)),
    ("Shade", re.compile(r"\b(SHADE|SIVOIA|PALLADIOM)\b", re.I)),
]

def normalize_sku(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    # common OCR-ish junk trimming
    s = s.strip(" ,.;:()[]{}<>\"'")
    # unify separators
    s = s.replace("_", "-").replace("/", "-")
    # collapse multiple dashes
    s = re.sub(r"-{2,}", "-", s)
    return s

def guess_manufacturer(sku: str) -> str:
    for name, rx in MANUFACTURER_HINTS:
        if rx.search(sku):
            return name
    # fallback: first token
    token = re.split(r"[-\s]", sku)[0]
    return token.upper() if token else "Unknown"

def guess_category(sku: str) -> str:
    for cat, rx in CATEGORY_HINTS:
        if rx.search(sku):
            return cat
    return "Unknown"

@dataclass
class Occurrence:
    source_json: str
    extracted_from: str  # proposal/manual/drawing/markup/file
    sku: str

@dataclass
class Item:
    sku_norm: str
    manufacturer: str
    category: str
    count: int
    first_seen: str
    last_seen: str
    examples: List[str]

def find_json_files() -> List[Path]:
    if not EXTRACTED.exists():
        return []
    return sorted(EXTRACTED.rglob("*.json"))

def read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def kind_from_path(p: Path) -> str:
    # .../Extracted_Knowledge/<bucket>/<slug>.json
    parts = p.parts
    try:
        idx = parts.index("Extracted_Knowledge")
        bucket = parts[idx + 1]
        if bucket in ("proposals", "manuals", "drawings", "markups"):
            return bucket[:-1]  # proposal/manual/drawing/markup
    except Exception:
        pass
    return "file"

def existing_vault_models() -> set:
    # expects VAULT/<Manufacturer>/<Model>/...
    models = set()
    if not VAULT.exists():
        return models
    for mfg_dir in VAULT.iterdir():
        if not mfg_dir.is_dir():
            continue
        for model_dir in mfg_dir.iterdir():
            if model_dir.is_dir():
                models.add(model_dir.name.upper())
    return models

def build_inventory() -> Tuple[Dict[str, Item], Dict[str, List[Occurrence]]]:
    json_files = find_json_files()
    log(f"Found {len(json_files)} extracted json files under {EXTRACTED}")
    occ: Dict[str, List[Occurrence]] = {}
    first_seen: Dict[str, str] = {}
    last_seen: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}

    for jf in json_files:
        data = read_json(jf)
        if not data:
            continue
        skus = data.get("models_or_skus_guess", []) or []
        kind = kind_from_path(jf)
        src = str(jf)
        for raw in skus:
            if not isinstance(raw, str):
                continue
            sku = normalize_sku(raw)
            if not sku:
                continue
            key = sku.upper()
            counts[key] = counts.get(key, 0) + 1
            occ.setdefault(key, []).append(Occurrence(source_json=src, extracted_from=kind, sku=sku))

            if key not in first_seen:
                first_seen[key] = now_iso()
            last_seen[key] = now_iso()

            ex = examples.setdefault(key, [])
            if len(ex) < 5 and sku not in ex:
                ex.append(sku)

    items: Dict[str, Item] = {}
    for key, c in counts.items():
        mfg = guess_manufacturer(key)
        cat = guess_category(key)
        items[key] = Item(
            sku_norm=key,
            manufacturer=mfg,
            category=cat,
            count=c,
            first_seen=first_seen.get(key, ""),
            last_seen=last_seen.get(key, ""),
            examples=examples.get(key, [])[:5],
        )
    return items, occ

def write_csv(items: Dict[str, Item], out_path: Path) -> None:
    rows = sorted(items.values(), key=lambda x: (-x.count, x.manufacturer, x.sku_norm))
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["manufacturer", "model_sku", "category", "count", "first_seen", "last_seen", "examples"])
        for it in rows:
            w.writerow([it.manufacturer, it.sku_norm, it.category, it.count, it.first_seen, it.last_seen, "; ".join(it.examples)])

def write_md(items: Dict[str, Item], out_path: Path) -> None:
    rows = sorted(items.values(), key=lambda x: (-x.count, x.manufacturer, x.sku_norm))
    lines = []
    lines.append("# SKU Frequency Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("This report is built from Bob’s extracted JSON signals. Higher count usually means repeated appearances across plans/proposals.")
    lines.append("")
    lines.append("| Count | Manufacturer | Category | Model/SKU |")
    lines.append("|---:|---|---|---|")
    for it in rows[:300]:
        lines.append(f"| {it.count} | {it.manufacturer} | {it.category} | {it.sku_norm} |")
    if len(rows) > 300:
        lines.append("")
        lines.append(f"Showing top 300 of {len(rows)} unique models/SKUs.")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_queue(items: Dict[str, Item], out_path: Path) -> None:
    vault_models = existing_vault_models()
    # choose top items not already in vault; prioritize known-ish manufacturers
    rows = sorted(items.values(), key=lambda x: (-x.count, x.manufacturer, x.sku_norm))
    queue = []
    for it in rows:
        model = it.sku_norm.upper()
        if model in vault_models:
            continue
        if it.count < 2:
            continue
        queue.append(it)
        if len(queue) >= 200:
            break

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["manufacturer_guess", "model_sku", "category_guess", "priority_score", "status", "notes"])
        for it in queue:
            # simple score = count (you can evolve later)
            w.writerow([it.manufacturer, it.sku_norm, it.category, it.count, "todo", ""])

def main() -> None:
    items, _occ = build_inventory()
    inv_csv = REPORTS / "SKU_Inventory.csv"
    freq_md = REPORTS / "SKU_Frequency_Report.md"
    queue_csv = REPORTS / "manual_fetch_queue.csv"

    write_csv(items, inv_csv)
    write_md(items, freq_md)
    write_queue(items, queue_csv)

    log(f"Wrote {inv_csv}")
    log(f"Wrote {freq_md}")
    log(f"Wrote {queue_csv}")
    print(f"OK: wrote reports to {REPORTS}")

if __name__ == "__main__":
    main()
