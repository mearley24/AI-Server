#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime

BASE = Path.home() / "AI-Server" / "knowledge"
EXTRACTED = BASE / "Extracted_Knowledge"
LOG = Path.home() / "AI-Server" / "logs" / "bob-regen-signals.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

OK_PREFIX = re.compile(r"^(CORE|EA-|CA-|IOX|TS-|AMS|PAMP|RSP-|AN-|HQP|QSX|RR-|RA2|RA3|T3|T4|LUT-|LUTRON)", re.I)
BAD_EXACT = re.compile(r"^(CAT[0-9]+|OM[0-9]+|IP[0-9]+|DIN|NEMA|UL|IAPMO|ANSI|ASTM|NFPA|NEC|FCC|IC|LED|HDMI|USB|RJ45|POE|VLAN|TCP|UDP|HTTP|HTTPS|WIFI|SSID)$", re.I)

def extract_models(text: str):
    # token-ish strings with dashes, must include a digit
    tokens = re.findall(r"\b[A-Z0-9][A-Z0-9\-]{3,40}\b", text)
    out = []
    seen = set()
    for t in tokens:
        if not re.search(r"\d", t):
            continue
        if BAD_EXACT.fullmatch(t):
            continue
        if len(t) > 40:
            continue
        if t.count("-") >= 6:
            continue
        if not OK_PREFIX.match(t):
            continue
        key = t.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:400]

def extract_headings(text: str):
    lines = text.splitlines()
    keep = []
    for ln in lines:
        s = ln.strip()
        if re.match(r"^(Scope|SCOPE|Assumptions|ASSUMPTIONS|Exclusions|EXCLUSIONS|Networking|NETWORKING|Audio|AUDIO|Video|VIDEO|Lighting|LIGHTING|Shades|SHADES|Security|SECURITY|Cameras|CAMERAS|Warranty|WARRANTY)\b", s):
            keep.append(s)
        if len(keep) >= 200:
            break
    return keep

def main():
    if not EXTRACTED.exists():
        print("No extracted knowledge folder found.")
        return

    txt_files = sorted(EXTRACTED.rglob("*.txt"))
    log(f"Found {len(txt_files)} txt files")
    updated = 0

    for txt in txt_files:
        try:
            text = txt.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        models = extract_models(text)
        headings = extract_headings(text)
        data = {
            "models_or_skus_guess": models,
            "headings_guess": headings,
            "regen": True,
            "regen_ts": datetime.now().isoformat(timespec="seconds"),
            "source_txt": str(txt),
        }

        js = txt.with_suffix(".json")
        try:
            js.write_text(json.dumps(data, indent=2), encoding="utf-8")
            updated += 1
        except Exception:
            continue

    log(f"Rewrote {updated} json files")
    print(f"OK: rewrote {updated} signal JSON files")

if __name__ == "__main__":
    main()
