#!/usr/bin/env python3
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE = Path.home() / "AI-Server" / "knowledge"
EXTRACTED = BASE / "Extracted_Knowledge"
REPORTS = BASE / "reports"
LOG = Path.home() / "AI-Server" / "logs" / "bob-roommap.log"

REPORTS.mkdir(parents=True, exist_ok=True)
LOG.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

# Room archetype normalization (tune over time; conservative defaults)
ARCHETYPE_RULES: List[Tuple[str, re.Pattern]] = [
    ("Bathroom", re.compile(r"\b(BATH|BATHROOM|POWDER|WC|W\.C\.|LAV)\b", re.I)),
    ("Bedroom", re.compile(r"\b(BED|BEDROOM|BUNK)\b", re.I)),
    ("Kitchen", re.compile(r"\b(KITCHEN|PANTRY|SCULLERY)\b", re.I)),
    ("Living/Great Room", re.compile(r"\b(LIVING|GREAT\s*ROOM|FAMILY\s*ROOM|DEN)\b", re.I)),
    ("Dining", re.compile(r"\b(DINING)\b", re.I)),
    ("Office", re.compile(r"\b(OFFICE|STUDY)\b", re.I)),
    ("Theater/Media", re.compile(r"\b(THEATER|CINEMA|MEDIA|GAME\s*ROOM)\b", re.I)),
    ("Laundry/Mud", re.compile(r"\b(LAUNDRY|MUD\s*ROOM|MUDROOM)\b", re.I)),
    ("Garage", re.compile(r"\b(GARAGE)\b", re.I)),
    ("Entry/Hall", re.compile(r"\b(ENTRY|FOYER|VESTIBULE|HALL|HALLWAY|STAIR)\b", re.I)),
    ("Outdoor", re.compile(r"\b(OUTDOOR|PATIO|DECK|BALCONY|HOT\s*TUB|POOL)\b", re.I)),
    ("Mechanical/Utility", re.compile(r"\b(MECH|MECHANICAL|UTILITY|ELECTRICAL|IDF|MDF|RACK)\b", re.I)),
    ("Common Area", re.compile(r"\b(COMMON|LOBBY|CORRIDOR|LOUNGE)\b", re.I)),
]

LEVEL_RULES: List[Tuple[str, re.Pattern]] = [
    ("Basement", re.compile(r"\b(BASEMENT|BSMT)\b", re.I)),
    ("Level 1", re.compile(r"\b(LEVEL\s*1|LVL\s*1|FIRST\s*FLOOR|MAIN\s*LEVEL)\b", re.I)),
    ("Level 2", re.compile(r"\b(LEVEL\s*2|LVL\s*2|SECOND\s*FLOOR|UPPER\s*LEVEL)\b", re.I)),
    ("Level 3", re.compile(r"\b(LEVEL\s*3|LVL\s*3|THIRD\s*FLOOR)\b", re.I)),
]

ROOM_LINE_HINT = re.compile(
    r"^\s*(ROOM|AREA|SPACE)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9 /&\-\']{2,60})\s*$",
    re.I
)

# These are common “not a room” words that show up as headings/notes
NOT_ROOM_EXACT = {
    "GENERAL", "NOTES", "NOTE", "SHEET", "SYMBOL", "SYMBOLS", "LEGEND",
    "DETAIL", "DETAILS", "SCHEDULE", "SPEC", "SPECIFICATIONS",
    "APPROVED", "APPROVAL", "APPLICATION", "APPLICABLE", "APPROPRIATE",
    "CAPACITY", "DIAGRAM", "DIAGRAMS", "GRAPHIC", "LANDSCAPE", "LANDSCAPING",
    "SWITCH", "SWITCHES", "TAPE", "BEAMS", "WRAP", "PAPER", "GAPS",
    "IAPMO", "ANSI", "ASTM", "NFPA", "NEC", "UL", "NEMA", "FCC", "IC",
    "CAT5", "CAT6", "CAT6A", "OM3", "OM4",
}

def classify_archetype(room_name: str) -> str:
    r = room_name.strip()
    for name, rx in ARCHETYPE_RULES:
        if rx.search(r):
            return name
    return "Unknown"

def classify_level(text: str) -> str:
    for name, rx in LEVEL_RULES:
        if rx.search(text):
            return name
    return ""

def clean_room_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(":-–—•\t ")
    return s

def is_roomish(s: str) -> bool:
    t = clean_room_name(s).upper()
    if len(t) < 3:
        return False
    if t in NOT_ROOM_EXACT:
        return False
    # reject if it looks like a pure SKU-ish token
    if re.fullmatch(r"[A-Z0-9\-]{4,40}", t) and re.search(r"\d", t):
        return False
    # accept if it contains a known room keyword
    for _, rx in ARCHETYPE_RULES:
        if rx.search(t):
            return True
    # accept if it has typical room-like formatting (two words, etc.)
    if " " in t and len(t) <= 40:
        return True
    return False

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def find_nearby_room(lines: List[str], hit_idx: int, window: int = 10) -> Tuple[str, str]:
    """
    Returns (room_name, level_name). Searches nearby lines for room-ish labels and level hints.
    """
    start = max(0, hit_idx - window)
    end = min(len(lines), hit_idx + window + 1)

    level_text = "\n".join(lines[start:end])
    level = classify_level(level_text)

    # Prefer the closest room-ish line by distance
    best_room = ""
    best_dist = 999

    for i in range(start, end):
        line = lines[i].strip()
        if not line:
            continue

        # If a line looks like "Room: MASTER BATH" capture the second group
        m = ROOM_LINE_HINT.match(line)
        candidate = ""
        if m:
            candidate = clean_room_name(m.group(2))
        else:
            candidate = clean_room_name(line)

        # Quick reject if too long
        if len(candidate) > 60:
            continue

        if is_roomish(candidate):
            dist = abs(i - hit_idx)
            if dist < best_dist:
                best_dist = dist
                best_room = candidate

    return best_room, level

def normalize_sku(s: str) -> str:
    s = s.strip()
    s = s.replace("_", "-").replace("/", "-")
    s = re.sub(r"-{2,}", "-", s)
    return s.upper()

def iter_txt_json_pairs() -> List[Tuple[Path, Path]]:
    pairs = []
    if not EXTRACTED.exists():
        return pairs
    for txt in EXTRACTED.rglob("*.txt"):
        js = txt.with_suffix(".json")
        if js.exists():
            pairs.append((txt, js))
    return sorted(pairs)

@dataclass
class MapRow:
    sku: str
    manufacturer_guess: str
    category_guess: str
    room_name: str
    archetype: str
    level: str
    source_txt: str
    hit_count_in_file: int

def guess_manufacturer(sku: str) -> str:
    s = sku.upper()
    if s.startswith("AN-"):
        return "Araknis"
    if s.startswith(("EA-", "CA-", "CORE", "IOX")):
        return "Control4"
    if s.startswith(("TS-", "AMS", "PAMP", "RSP-")):
        # TS is Snap One/Strong/“Triad/Snap” in your library; we keep TS as manufacturer bucket
        return "TS"
    if s.startswith(("HQP", "QSX", "RR-", "RA2", "RA3")):
        return "Lutron"
    return "Unknown"

def guess_category(sku: str) -> str:
    s = sku.upper()
    if s.startswith(("CORE", "EA-", "CA-")):
        return "Controller"
    if s.startswith(("AMS", "TS-AMS")):
        return "Audio Matrix"
    if s.startswith(("PAMP", "RSP-", "EA-DYN", "TS-PAMP")):
        return "Amplifier"
    if s.startswith("AN-"):
        return "Networking"
    if s.startswith(("HQP", "QSX", "RR-", "RA2", "RA3")):
        return "Lighting/Shades"
    return "Unknown"

def main() -> None:
    pairs = iter_txt_json_pairs()
    log(f"Room mapper: found {len(pairs)} txt/json pairs")

    rows: List[MapRow] = []
    # rollups
    sku_to_archetype_counts: Dict[str, Counter] = defaultdict(Counter)
    archetype_to_sku_counts: Dict[str, Counter] = defaultdict(Counter)

    for txt_path, js_path in pairs:
        data = load_json(js_path) or {}
        skus = data.get("models_or_skus_guess", []) or []
        if not skus:
            continue

        text = load_text(txt_path)
        lines = text.splitlines()

        for raw_sku in skus:
            if not isinstance(raw_sku, str):
                continue
            sku = normalize_sku(raw_sku)
            if not sku:
                continue

            # Find occurrences of SKU in text (case-insensitive)
            hit_lines = []
            rx = re.compile(re.escape(sku), re.I)
            for idx, line in enumerate(lines):
                if rx.search(line):
                    hit_lines.append(idx)

            if not hit_lines:
                continue

            # Use the first hit to assign room, but count total hits
            room, level = find_nearby_room(lines, hit_lines[0], window=12)
            if not room:
                room = "Unknown"
            archetype = classify_archetype(room) if room != "Unknown" else "Unknown"

            mfg = guess_manufacturer(sku)
            cat = guess_category(sku)

            rows.append(
                MapRow(
                    sku=sku,
                    manufacturer_guess=mfg,
                    category_guess=cat,
                    room_name=room,
                    archetype=archetype,
                    level=level,
                    source_txt=str(txt_path),
                    hit_count_in_file=len(hit_lines),
                )
            )

            sku_to_archetype_counts[sku][archetype] += 1
            archetype_to_sku_counts[archetype][sku] += 1

    # Write detailed CSV
    out_csv = REPORTS / "SKU_Room_Map.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "sku", "manufacturer_guess", "category_guess",
            "room_name", "archetype", "level",
            "hit_count_in_file", "source_txt"
        ])
        for r in rows:
            w.writerow([
                r.sku, r.manufacturer_guess, r.category_guess,
                r.room_name, r.archetype, r.level,
                r.hit_count_in_file, r.source_txt
            ])

    # Write rollup MD: for each archetype, top SKUs
    out_md = REPORTS / "Room_Archetype_Packages.md"
    lines_out: List[str] = []
    lines_out.append("# Room Archetype Packages")
    lines_out.append("")
    lines_out.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines_out.append("")
    lines_out.append("This report shows which devices/models commonly appear near room labels across your historical proposals/drawings.")
    lines_out.append("Use it to build repeatable per-room packages (Bathrooms, Bedrooms, Common Areas, etc.).")
    lines_out.append("")

    for archetype in sorted(archetype_to_sku_counts.keys()):
        cnt = archetype_to_sku_counts[archetype]
        total = sum(cnt.values())
        if total < 3:
            continue
        lines_out.append(f"## {archetype}")
        lines_out.append("")
        lines_out.append("| Count | Model/SKU |")
        lines_out.append("|---:|---|")
        for sku, c in cnt.most_common(30):
            lines_out.append(f"| {c} | {sku} |")
        lines_out.append("")

    out_md.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    log(f"Wrote {out_csv}")
    log(f"Wrote {out_md}")
    print(f"OK: wrote {out_csv} and {out_md}")

if __name__ == "__main__":
    main()
