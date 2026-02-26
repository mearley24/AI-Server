#!/usr/bin/env python3
import csv
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

BASE = Path.home() / "AI-Server" / "knowledge"
REPORTS = BASE / "reports"
VAULT = BASE / "manual_vault"
LOG = Path.home() / "AI-Server" / "logs" / "bob-manuals.log"

ICLOUD_BASE = Path("/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Bob_Library")
RAW_PROJECTS = ICLOUD_BASE / "Raw_Projects" / "Projects"
LIB_MANUALS = ICLOUD_BASE / "Manuals"

QUEUE = REPORTS / "manual_fetch_queue.csv"

LOG.parent.mkdir(parents=True, exist_ok=True)
VAULT.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def safe_dirname(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "_", s.strip())
    return re.sub(r"\s+", " ", s)[:120]

def model_key(model: str) -> str:
    return model.strip().upper()

def is_valid_model(model: str) -> bool:
    m = model_key(model)
    if not re.search(r"\d", m):
        return False
    if len(m) > 40:
        return False
    if m.count("-") >= 6:
        return False
    return True

def vault_path(mfg: str, model: str) -> Path:
    return VAULT / safe_dirname(mfg) / safe_dirname(model_key(model))

def already_done(mfg: str, model: str) -> bool:
    p = vault_path(mfg, model)
    return p.exists() and any(p.rglob("*.pdf"))

def search_local_for_pdfs(model: str, limit: int = 10) -> List[Path]:
    hits: List[Path] = []
    for root in (RAW_PROJECTS, LIB_MANUALS):
        if not root.exists():
            continue
        for p in root.rglob("*.pdf"):
            if model.lower() in p.name.lower():
                hits.append(p)
                if len(hits) >= limit:
                    return hits
    return hits

def copy_into_vault(mfg: str, model: str, pdfs: List[Path]) -> int:
    vp = vault_path(mfg, model)
    vp.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in pdfs:
        dest = vp / p.name
        if not dest.exists():
            shutil.copy2(p, dest)
            copied += 1
    return copied

def load_queue():
    if not QUEUE.exists():
        return []
    with QUEUE.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_queue(rows):
    with QUEUE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["manufacturer_guess","model_sku","category_guess","priority_score","status","notes"]
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)

def main():
    rows = load_queue()
    log(f"Loaded queue: {len(rows)} rows")

    processed = 0

    for row in rows:
        status = (row.get("status") or "").lower()
        if status in ("done", "skip"):
            continue

        mfg = (row.get("manufacturer_guess") or "Unknown").strip()
        model = (row.get("model_sku") or "").strip()

        if not model or not is_valid_model(model):
            row["status"] = "skip"
            row["notes"] = "invalid_model"
            continue

        if already_done(mfg, model):
            row["status"] = "done"
            row["notes"] = "already_in_vault"
            continue

        log(f"Manual hunt: {mfg} {model}")

        local_hits = search_local_for_pdfs(model)
        if local_hits:
            copied = copy_into_vault(mfg, model, local_hits)
            row["status"] = "done"
            row["notes"] = f"copied_local={copied}"
        else:
            row["status"] = "todo"
            row["notes"] = "not_found_locally"

        processed += 1
        if processed >= 100:
            break

    save_queue(rows)
    log(f"Run finished. processed={processed}")
    print("OK: manual fetch run finished")

if __name__ == "__main__":
    main()
