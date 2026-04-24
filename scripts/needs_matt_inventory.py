#!/usr/bin/env python3
"""Inventory [NEEDS_MATT] markers across the repo.

Advisory report — classifies every `[NEEDS_MATT]` hit into one of:

    active            — open gate in STATUS_REPORT.md (top-level bullet)
                        or a runbook Status: header
    strikethrough     — closed, wrapped in ~~...~~ with ✅
    doc_reference     — documentation/code-comment mention, not a gate
    prompt_reference  — prompt file text that mentions the tag
    runbook_header    — runbook file that is itself a [NEEDS_MATT] gate
    historical        — frozen receipt under ops/verification/*

Only `active` hits represent outstanding work. Active hits are further
checked for required metadata (Owner, Opened, Review-by, Evidence,
Next) and for staleness against a configurable window (default 14 days
from the Opened date, or from today if Opened is missing).

Exit code is always 0 — this script is a report, not a gate. See
docs/needs-matt-policy.md for the full policy.

Usage:

    python3 scripts/needs_matt_inventory.py
    python3 scripts/needs_matt_inventory.py --all
    python3 scripts/needs_matt_inventory.py --json
    python3 scripts/needs_matt_inventory.py --stale-days 21
    python3 scripts/needs_matt_inventory.py --write ops/verification/<stamp>-needs-matt-inventory.txt

Pure stdlib. No install step. Does not mutate any file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = "[NEEDS_MATT]"
MARKER_RE = re.compile(r"\[NEEDS_MATT\]")
STRIKE_RE = re.compile(r"~~[^~]*\[NEEDS_MATT\][^~]*~~")
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

DEFAULT_STALE_DAYS = 14
DEFAULT_EXCLUDE_DIRS = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "data",
    "ops/verification",
)

TEXT_SUFFIXES = (
    ".md", ".txt", ".py", ".sh", ".yml", ".yaml", ".json", ".toml",
    ".ini", ".cfg", ".env", ".example", ".plist", ".conf", ".tsv",
    ".tsx", ".ts", ".js", ".jsx", ".html", ".css", ".sql",
)


@dataclass
class Hit:
    path: str
    line: int
    raw: str
    classification: str
    stale: bool = False
    under_specified: bool = False
    missing_fields: list[str] = field(default_factory=list)
    opened: str | None = None
    review_by: str | None = None


def iter_candidate_files(
    root: Path, exclude_dirs: tuple[str, ...]
) -> Iterable[Path]:
    exclude_abs = {str((root / d).resolve()) for d in exclude_dirs}
    for dirpath, dirnames, filenames in os.walk(root):
        abs_dir = str(Path(dirpath).resolve())
        dirnames[:] = [
            d for d in dirnames
            if str((Path(dirpath) / d).resolve()) not in exclude_abs
        ]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in TEXT_SUFFIXES or name in (
                "STATUS_REPORT", "CLAUDE", "AGENTS",
            ):
                yield p


def classify(path: Path, line: str, repo_rel: str) -> str:
    if repo_rel.startswith("ops/verification/"):
        return "historical"
    if STRIKE_RE.search(line):
        return "strikethrough"
    if repo_rel.startswith("ops/runbooks/"):
        return "runbook_header"
    if repo_rel.startswith(".cursor/prompts/"):
        return "prompt_reference"

    if repo_rel == "STATUS_REPORT.md":
        stripped = line.lstrip()
        if stripped.startswith("- [NEEDS_MATT]") or stripped.startswith(
            "**- [NEEDS_MATT]"
        ):
            return "active"
        return "doc_reference"

    return "doc_reference"


def extract_metadata(
    all_lines: list[str], idx: int
) -> tuple[dict[str, str], list[str]]:
    """Look at idx+1..idx+5 for Owner/Opened/Review-by/Evidence/Next."""
    fields = {}
    required = ["owner", "opened", "review-by", "evidence", "next"]
    window = all_lines[idx + 1 : idx + 8]
    joined = "\n".join(window)
    for key in required:
        pattern = re.compile(
            rf"^\s*[-*]?\s*{re.escape(key)}\s*:\s*(.+?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        m = pattern.search(joined)
        if m:
            fields[key] = m.group(1).strip()
    missing = [k for k in required if k not in fields]
    return fields, missing


def is_stale(
    opened: str | None, review_by: str | None, stale_days: int, today: date
) -> bool:
    if review_by:
        try:
            rb = datetime.strptime(review_by[:10], "%Y-%m-%d").date()
            return today >= rb
        except ValueError:
            pass
    if opened:
        try:
            op = datetime.strptime(opened[:10], "%Y-%m-%d").date()
            return (today - op).days >= stale_days
        except ValueError:
            pass
    return False


def scan(
    root: Path,
    exclude_dirs: tuple[str, ...],
    stale_days: int,
    today: date,
) -> list[Hit]:
    hits: list[Hit] = []
    for path in iter_candidate_files(root, exclude_dirs):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        if MARKER not in text:
            continue
        lines = text.splitlines()
        rel = str(path.relative_to(root))
        for i, line in enumerate(lines):
            if not MARKER_RE.search(line):
                continue
            cls = classify(path, line, rel)
            hit = Hit(
                path=rel,
                line=i + 1,
                raw=line.rstrip()[:240],
                classification=cls,
            )
            if cls == "active":
                meta, missing = extract_metadata(lines, i)
                hit.opened = meta.get("opened")
                hit.review_by = meta.get("review-by")
                hit.missing_fields = missing
                hit.under_specified = bool(missing)
                hit.stale = is_stale(
                    hit.opened, hit.review_by, stale_days, today
                )
            hits.append(hit)
    return hits


def summarize(hits: list[Hit]) -> dict[str, int]:
    summary = {
        "total": len(hits),
        "active": 0,
        "strikethrough": 0,
        "doc_reference": 0,
        "prompt_reference": 0,
        "runbook_header": 0,
        "historical": 0,
        "stale": 0,
        "under_specified": 0,
    }
    for h in hits:
        summary[h.classification] = summary.get(h.classification, 0) + 1
        if h.classification == "active":
            if h.stale:
                summary["stale"] += 1
            if h.under_specified:
                summary["under_specified"] += 1
    return summary


def render_text(hits: list[Hit], summary: dict[str, int], include_all: bool) -> str:
    lines: list[str] = []
    lines.append("NEEDS_MATT inventory")
    lines.append("=" * 60)
    lines.append(f"Scanned repo: {REPO_ROOT}")
    lines.append(f"Timestamp:    {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Counts:")
    lines.append(f"  total hits                 : {summary['total']}")
    lines.append(f"  active (open gates)        : {summary['active']}")
    lines.append(f"    of which stale           : {summary['stale']}")
    lines.append(f"    of which under-specified : {summary['under_specified']}")
    lines.append(f"  strikethrough (closed)     : {summary['strikethrough']}")
    lines.append(f"  runbook-header             : {summary['runbook_header']}")
    lines.append(f"  doc-reference              : {summary['doc_reference']}")
    lines.append(f"  prompt-reference           : {summary['prompt_reference']}")
    lines.append(f"  historical (ops/verification): {summary['historical']}")
    lines.append("")

    active_hits = [h for h in hits if h.classification == "active"]
    stale_hits = [h for h in active_hits if h.stale]
    us_hits = [h for h in active_hits if h.under_specified]

    if stale_hits:
        lines.append("Stale active markers (review-by in the past, or opened > threshold):")
        for h in stale_hits[:20]:
            rb = h.review_by or f"opened={h.opened or '?'}"
            lines.append(f"  {h.path}:{h.line}  ({rb})")
            lines.append(f"    {h.raw}")
        if len(stale_hits) > 20:
            lines.append(f"  ... {len(stale_hits) - 20} more")
        lines.append("")

    if us_hits:
        lines.append("Under-specified active markers (missing required metadata):")
        for h in us_hits[:20]:
            lines.append(
                f"  {h.path}:{h.line}  missing: {', '.join(h.missing_fields)}"
            )
            lines.append(f"    {h.raw}")
        if len(us_hits) > 20:
            lines.append(f"  ... {len(us_hits) - 20} more")
        lines.append("")

    if active_hits and not stale_hits and not us_hits:
        lines.append("All active markers are fresh and fully specified.")
        lines.append("")

    if include_all:
        lines.append("All non-historical hits:")
        for h in hits:
            if h.classification == "historical":
                continue
            flags = []
            if h.stale:
                flags.append("STALE")
            if h.under_specified:
                flags.append("UNDER-SPECIFIED")
            suffix = f"  [{','.join(flags)}]" if flags else ""
            lines.append(f"  {h.classification:17s} {h.path}:{h.line}{suffix}")
        lines.append("")

    lines.append("Next actions:")
    if stale_hits or us_hits:
        lines.append(
            "  1. Open docs/needs-matt-policy.md for the metadata schema."
        )
        lines.append(
            "  2. For each stale hit: either close with evidence (wrap in"
        )
        lines.append(
            "     ~~...~~ + ✅ + date + evidence path) or extend review-by"
        )
        lines.append("     with a recorded reason.")
        lines.append(
            "  3. For each under-specified hit: add Owner/Opened/Review-by/"
        )
        lines.append("     Evidence/Next lines below the bullet.")
    else:
        lines.append("  None — surface is clean.")
    lines.append("")
    lines.append(
        "See docs/needs-matt-policy.md for the full policy and lifecycle."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="enumerate every non-historical hit")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"staleness window in days (default {DEFAULT_STALE_DAYS})",
    )
    ap.add_argument(
        "--include-history",
        action="store_true",
        help="also scan ops/verification/* (skipped by default)",
    )
    ap.add_argument(
        "--write",
        metavar="PATH",
        help="write the text report to PATH in addition to stdout",
    )
    args = ap.parse_args(argv)

    excludes = tuple(
        d for d in DEFAULT_EXCLUDE_DIRS
        if not (args.include_history and d == "ops/verification")
    )

    hits = scan(REPO_ROOT, excludes, args.stale_days, date.today())
    summary = summarize(hits)

    if args.json:
        payload = {
            "summary": summary,
            "hits": [asdict(h) for h in hits],
            "stale_days": args.stale_days,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        out = json.dumps(payload, indent=2)
    else:
        out = render_text(hits, summary, include_all=args.all)

    print(out, end="" if out.endswith("\n") else "\n")

    if args.write:
        dest = Path(args.write)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            out if not args.json else out + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
