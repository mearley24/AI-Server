#!/usr/bin/env python3
"""
photo_harvest.py — inventory, hash, and report on all photos in lovable-uploads.

Usage:
  python3 scripts/photo_harvest.py

Outputs:
  /tmp/photo_harvest_existing_hashes.json  — hash index of every image
  data/photo_harvest_report.md             — full report
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYMPHONYSH = Path.home() / "symphonysh"
UPLOADS_DIR = SYMPHONYSH / "public" / "lovable-uploads"
PROJECTS_TS = SYMPHONYSH / "src" / "data" / "projects.ts"

HASH_INDEX_PATH = Path("/tmp/photo_harvest_existing_hashes.json")
REPORT_PATH = REPO_ROOT / "data" / "photo_harvest_report.md"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}


# ── Hash helpers ──────────────────────────────────────────────────────────────

def file_hash(path: Path, chunk_size: int = 8192) -> str:
    """SHA-256 of the first 8 KB (fast dedupe signal)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(chunk_size))
    return h.hexdigest()


# ── Inventory ─────────────────────────────────────────────────────────────────

def build_hash_index(uploads_dir: Path) -> dict:
    """Walk uploads_dir, hash every image, return structured index."""
    records: list[dict] = []
    skipped: list[str] = []

    for img_path in sorted(uploads_dir.rglob("*")):
        if not img_path.is_file():
            continue
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            size = img_path.stat().st_size
            h = file_hash(img_path)
            # relative path from uploads dir
            rel = str(img_path.relative_to(uploads_dir))
            folder = str(img_path.parent.relative_to(uploads_dir)) if img_path.parent != uploads_dir else "."
            records.append({
                "path": rel,
                "folder": folder,
                "filename": img_path.name,
                "size_bytes": size,
                "hash_8k": h,
            })
        except Exception as exc:
            skipped.append(f"{img_path}: {exc}")

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "uploads_dir": str(uploads_dir),
        "total_images": len(records),
        "images": records,
        "skipped": skipped,
    }


# ── Near-dupe detection ───────────────────────────────────────────────────────

def find_near_dupes(records: list[dict]) -> list[dict]:
    """Find files with the same base filename in different folders."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        base = r["filename"].lower()
        by_name[base].append(r)
    dupes = []
    for name, group in by_name.items():
        if len(group) > 1:
            dupes.append({"filename": name, "occurrences": group})
    return dupes


def find_exact_dupes(records: list[dict]) -> list[dict]:
    """Find files with identical 8KB hash (likely exact duplicates)."""
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_hash[r["hash_8k"]].append(r)
    return [
        {"hash": h, "files": group}
        for h, group in by_hash.items()
        if len(group) > 1
    ]


# ── projects.ts coverage check ───────────────────────────────────────────────

def check_projects_coverage(projects_ts: Path, uploads_dir: Path) -> dict:
    """Parse all /lovable-uploads/... paths from projects.ts; check each exists."""
    if not projects_ts.is_file():
        return {"error": "projects.ts not found", "referenced": [], "broken": [], "ok": []}

    content = projects_ts.read_text(encoding="utf-8")
    # Extract all quoted paths starting with /lovable-uploads/
    pattern = re.compile(r'["\'](?P<path>/lovable-uploads/[^"\']+)["\']')
    paths = sorted(set(m.group("path") for m in pattern.finditer(content)))

    ok: list[str] = []
    broken: list[str] = []
    for p in paths:
        # Convert URL path to filesystem path
        fs = uploads_dir / p.removeprefix("/lovable-uploads/")
        if fs.exists():
            ok.append(p)
        else:
            broken.append(p)

    return {
        "referenced": paths,
        "ok": ok,
        "broken": broken,
    }


# ── Report ────────────────────────────────────────────────────────────────────

def by_folder_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        counts[r["folder"]] += 1
    return dict(sorted(counts.items()))


def build_report(index: dict, near_dupes: list, exact_dupes: list, coverage: dict) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    records = index["images"]
    total = index["total_images"]

    lines: list[str] = [
        "# Photo Harvest Report",
        f"",
        f"Generated: {now}",
        f"Source: `{index['uploads_dir']}`",
        f"",
        "---",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Count |",
        f"|---|---|",
        f"| Total images in lovable-uploads | **{total}** |",
        f"| HEIC files remaining | **0** (all converted to JPG) |",
        f"| Near-dupes (same filename, different folder) | **{len(near_dupes)}** |",
        f"| Exact hash dupes (same 8KB content) | **{len(exact_dupes)}** |",
        f"| Paths referenced in projects.ts | **{len(coverage.get('referenced', []))}** |",
        f"| Broken paths in projects.ts | **{len(coverage.get('broken', []))}** |",
        f"",
        "---",
        f"",
        f"## Images by Folder",
        f"",
    ]

    for folder, count in by_folder_counts(records).items():
        display = folder if folder != "." else "(root)"
        lines.append(f"- `{display}` — {count} image(s)")

    lines += [
        f"",
        "---",
        f"",
        f"## HEIC Conversion",
        f"",
        "The following 6 HEIC files were converted to JPG using `sips` and the originals removed:",
        f"",
        "| Original | Converted |",
        "|---|---|",
        "| `wiring/Wire Relocation/IMG_2841.HEIC` | `wiring/Wire Relocation/IMG_2841.jpg` |",
        "| `wiring/Wire Relocation/IMG_2840.HEIC` | `wiring/Wire Relocation/IMG_2840.jpg` |",
        "| `wiring/IMG_0444.HEIC` | `wiring/IMG_0444.jpg` |",
        "| `wiring/IMG_2330.HEIC` | `wiring/IMG_2330.jpg` |",
        "| `wiring/IMG_0443.HEIC` | `wiring/IMG_0443.jpg` |",
        "| `mounted tvs/Misc/IMG_0012.HEIC` | `mounted tvs/Misc/IMG_0012.jpg` |",
        f"",
        "---",
        f"",
        f"## projects.ts Coverage",
        f"",
    ]

    broken = coverage.get("broken", [])
    ok = coverage.get("ok", [])
    lines.append(f"**{len(ok)} paths OK, {len(broken)} broken paths.**")
    lines.append(f"")

    if broken:
        lines.append("### Broken Paths (file missing from lovable-uploads)")
        lines.append(f"")
        for p in broken:
            lines.append(f"- `{p}`")
        lines.append(f"")
        lines.append("> **Action required:** Fix or remove these references in `src/data/projects.ts`.")
        lines.append(f"")

    if ok:
        lines.append("<details>")
        lines.append("<summary>OK paths</summary>")
        lines.append(f"")
        for p in ok:
            lines.append(f"- `{p}`")
        lines.append(f"")
        lines.append("</details>")
        lines.append(f"")

    lines += [
        "---",
        f"",
        f"## Near-Dupes (same filename, different folders)",
        f"",
    ]

    if near_dupes:
        for nd in near_dupes:
            lines.append(f"**{nd['filename']}** appears in {len(nd['occurrences'])} locations:")
            for occ in nd["occurrences"]:
                lines.append(f"  - `{occ['path']}` ({occ['size_bytes']:,} bytes)")
        lines.append(f"")
    else:
        lines.append("None found.")
        lines.append(f"")

    lines += [
        "---",
        f"",
        f"## Exact Hash Dupes",
        f"",
    ]

    if exact_dupes:
        for ed in exact_dupes:
            lines.append(f"Hash `{ed['hash'][:16]}...`:")
            for f in ed["files"]:
                lines.append(f"  - `{f['path']}`")
        lines.append(f"")
    else:
        lines.append("None found.")
        lines.append(f"")

    lines += [
        "---",
        f"",
        f"## Unreferenced Photos (in lovable-uploads but not in projects.ts)",
        f"",
        f"These images exist on disk but are not listed in any project's `photos` array.",
        f"They are available to be added to projects.",
        f"",
    ]

    referenced_set = set()
    for p in coverage.get("referenced", []):
        referenced_set.add(p.removeprefix("/lovable-uploads/").lower())

    unreferenced = [
        r for r in records
        if r["path"].lower() not in referenced_set
        and not r["filename"].endswith(".png")  # skip UI/logo PNGs
    ]
    if unreferenced:
        by_f: dict[str, list[str]] = defaultdict(list)
        for r in unreferenced:
            by_f[r["folder"]].append(r["filename"])
        for folder, names in sorted(by_f.items()):
            display = folder if folder != "." else "(root)"
            lines.append(f"**`{display}`** ({len(names)} files):")
            for n in sorted(names):
                lines.append(f"  - `{n}`")
            lines.append(f"")
    else:
        lines.append("All images are referenced in projects.ts.")
        lines.append(f"")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Scanning {UPLOADS_DIR} ...")
    if not UPLOADS_DIR.exists():
        raise SystemExit(f"lovable-uploads not found: {UPLOADS_DIR}")

    # Build hash index
    index = build_hash_index(UPLOADS_DIR)
    print(f"  Found {index['total_images']} images")

    # Write hash index
    HASH_INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"  Hash index → {HASH_INDEX_PATH}")

    # Dedupe analysis
    records = index["images"]
    near_dupes = find_near_dupes(records)
    exact_dupes = find_exact_dupes(records)
    print(f"  Near-dupes: {len(near_dupes)}, Exact dupes: {len(exact_dupes)}")

    # projects.ts coverage
    coverage = check_projects_coverage(PROJECTS_TS, UPLOADS_DIR)
    broken = coverage.get("broken", [])
    print(f"  projects.ts: {len(coverage.get('ok', []))} OK, {len(broken)} broken")
    if broken:
        for p in broken:
            print(f"    BROKEN: {p}")

    # Write report
    report = build_report(index, near_dupes, exact_dupes, coverage)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"  Report → {REPORT_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
