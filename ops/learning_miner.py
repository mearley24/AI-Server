#!/usr/bin/env python3
"""Learning miner for the Symphony AI-Server lessons registry.

Scans recent verification artifacts under ``ops/verification/`` and extracts
candidate lessons (failures, fixes, workflow gaps, TODOs, approval patterns),
then upserts them into the Markdown table in ``ops/LESSONS_REGISTRY.md``.

This is intentionally a first-version miner: heuristics are simple regexes +
section sniffing.  The goal is to surface real patterns, not to be clever.

Design rules honored:
 - Pure stdlib (no new deps).
 - Idempotent: stable ``lesson_id`` based on normalized summary, so re-runs
   update ``last_seen_at`` instead of creating duplicates.
 - Agent-safe edits: it reads the existing Markdown table between the
   ``<!-- LESSONS_TABLE_START -->`` / ``<!-- LESSONS_TABLE_END -->`` markers
   and rewrites only the rows inside that fence.
 - Respects hand-edited ``status`` / ``impact_hint`` columns: if a row with a
   given ``lesson_id`` already has a non-default value, the miner keeps it.

Usage::

    python3 ops/learning_miner.py --days 7               # dry-run summary
    python3 ops/learning_miner.py --days 7 --update      # write the registry
    python3 ops/learning_miner.py --days 7 --update --out ops/verification/...
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
REGISTRY_PATH = REPO_ROOT / "ops" / "LESSONS_REGISTRY.md"

TABLE_START = "<!-- LESSONS_TABLE_START -->"
TABLE_END = "<!-- LESSONS_TABLE_END -->"

DEFAULT_DAYS = 7
MAX_SUMMARY = 240
MAX_EVIDENCE_REFS = 6

# --- Heuristic patterns ------------------------------------------------------

# We look for lines that mark causes, fixes, or follow-ups.  These tags are
# consistent with how verification reports in this repo are already written.
HEADING_RE = re.compile(
    r"""
    ^\s*
    (?:\#+\s*|===\s*|---\s*)?
    (?P<label>
        root[\s_-]*cause
      | cause
      | fix(?:\s+applied)?
      | minimal\s+fix(?:\s+applied)?
      | exact\s+fix(?:\s+made)?
      | remaining(?:\s+blocker)?
      | next(?:\s+action|s)?
      | todo
      | follow[\s_-]*up
      | limitations?
      | gap(?:s)?
      | recommended(?:\s+next\s+action)?
      | approval\s+pattern
      | known\s+limitations?
      | workflow\s+gap
      | blocker
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Map heading label -> pattern_type
PATTERN_TYPE_MAP: dict[str, str] = {
    "root cause": "failure",
    "cause": "failure",
    "blocker": "blocker",
    "remaining blocker": "blocker",
    "remaining": "blocker",
    "fix": "fix",
    "fix applied": "fix",
    "minimal fix": "fix",
    "minimal fix applied": "fix",
    "exact fix": "fix",
    "exact fix made": "fix",
    "todo": "todo",
    "follow up": "todo",
    "follow-up": "todo",
    "next": "workflow_gap",
    "next action": "workflow_gap",
    "next actions": "workflow_gap",
    "recommended next action": "workflow_gap",
    "limitations": "workflow_gap",
    "limitation": "workflow_gap",
    "known limitations": "workflow_gap",
    "gap": "workflow_gap",
    "gaps": "workflow_gap",
    "workflow gap": "workflow_gap",
    "approval pattern": "approval_pattern",
}

IMPACT_KEYWORDS: list[tuple[str, str]] = [
    (r"\b(redis|docker|compose|healthcheck|launchd|preflight|runner|loop|watchdog)\b", "reliability"),
    (r"\b(kraken|polymarket|wallet|usdc|trade|trading|kalshi|redeem)\b", "business_impact"),
    (r"\b(timeout|slow|hang|stuck|throttle)\b", "speed"),
    (r"\b(leak|secret|token|password|auth|credential)\b", "safety"),
    (r"\b(cost|spend|credit|budget)\b", "cost"),
]

SKIP_FILES = {
    "INDEX.txt",
}

# Substring filter: files whose name matches any of these are skipped by
# default because they are generated heartbeat / noise artifacts that would
# overwhelm the lesson heuristics without adding signal.
SKIP_SUBSTRINGS = (
    "-preflight",
    "preflight-",
)

MIN_SUMMARY_LEN = 30


@dataclass
class LessonRow:
    lesson_id: str
    first_seen_at: str
    last_seen_at: str
    source: str
    pattern_type: str
    summary: str
    evidence_refs: str
    status: str = "new"
    impact_hint: str = "unknown"


@dataclass
class MinerStats:
    files_scanned: int = 0
    candidates_found: int = 0
    lessons_created: int = 0
    lessons_updated: int = 0
    lessons_unchanged: int = 0
    examples: list[str] = field(default_factory=list)


# --- Registry I/O ------------------------------------------------------------


def parse_registry(text: str) -> dict[str, LessonRow]:
    """Parse the Markdown table between the fence markers."""
    start = text.find(TABLE_START)
    end = text.find(TABLE_END)
    if start == -1 or end == -1 or end < start:
        return {}
    body = text[start + len(TABLE_START) : end]
    rows: dict[str, LessonRow] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # skip header / separator
        if line.startswith("| lesson_id") or set(line) <= {"|", "-", " ", ":"}:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 9:
            continue
        (
            lesson_id,
            first_seen_at,
            last_seen_at,
            source,
            pattern_type,
            summary,
            evidence_refs,
            status,
            impact_hint,
        ) = cells[:9]
        if not lesson_id:
            continue
        rows[lesson_id] = LessonRow(
            lesson_id=lesson_id,
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            source=source,
            pattern_type=pattern_type,
            summary=summary,
            evidence_refs=evidence_refs,
            status=status or "new",
            impact_hint=impact_hint or "unknown",
        )
    return rows


def render_registry(text: str, rows: dict[str, LessonRow]) -> str:
    """Rebuild the registry Markdown with the supplied rows (sorted)."""
    lines: list[str] = [
        TABLE_START,
        "| lesson_id | first_seen_at | last_seen_at | source | pattern_type | summary | evidence_refs | status | impact_hint |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    sorted_rows = sorted(
        rows.values(),
        key=lambda r: (r.last_seen_at or "", r.lesson_id),
        reverse=True,
    )
    for row in sorted_rows:
        lines.append(
            "| "
            + " | ".join(
                _md_escape(v)
                for v in (
                    row.lesson_id,
                    row.first_seen_at,
                    row.last_seen_at,
                    row.source,
                    row.pattern_type,
                    row.summary,
                    row.evidence_refs,
                    row.status,
                    row.impact_hint,
                )
            )
            + " |"
        )
    lines.append(TABLE_END)

    block = "\n".join(lines) + "\n"

    start = text.find(TABLE_START)
    end = text.find(TABLE_END)
    if start == -1 or end == -1:
        # append if markers are missing (shouldn't happen)
        return text.rstrip() + "\n\n" + block
    return text[:start] + block + text[end + len(TABLE_END) :].lstrip("\n")


def _md_escape(value: str) -> str:
    if value is None:
        return ""
    return value.replace("|", "\\|").replace("\n", " ").strip()


# --- Miner -------------------------------------------------------------------


def _normalize_summary(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip().lower()
    # strip timestamps / file paths / hashes that cause spurious new IDs
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}(?::\d{2})?(?:z|[+-]\d{2}:?\d{2})?)?\b", "", s)
    s = re.sub(r"\b\d{8}-\d{6}\b", "", s)
    s = re.sub(r"\b[0-9a-f]{8,40}\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def compute_lesson_id(summary: str) -> str:
    digest = hashlib.sha1(_normalize_summary(summary).encode("utf-8")).hexdigest()
    return f"L-{digest[:8]}"


def classify_pattern_type(label: str) -> str:
    key = re.sub(r"[\s_-]+", " ", label.strip().lower())
    return PATTERN_TYPE_MAP.get(key, "workflow_gap")


def guess_impact(summary: str) -> str:
    for pattern, impact in IMPACT_KEYWORDS:
        if re.search(pattern, summary, re.IGNORECASE):
            return impact
    return "unknown"


def _iter_candidate_files(days: int) -> Iterable[Path]:
    if not VERIFICATION_DIR.is_dir():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results: list[Path] = []
    for p in VERIFICATION_DIR.iterdir():
        if not p.is_file():
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix.lower() not in {".txt", ".md"}:
            continue
        if any(sub in p.name for sub in SKIP_SUBSTRINGS):
            # preflight self-heal artifacts are heartbeat noise; skip by default.
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        results.append(p)
    results.sort(key=lambda p: p.stat().st_mtime)
    return results


def extract_candidates(path: Path) -> list[tuple[str, str]]:
    """Return (pattern_type, summary) pairs extracted from a verification file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        label = match.group("label")
        pattern_type = classify_pattern_type(label)

        # Collect up to the next blank line, heading, or 6 lines of body.
        body_parts: list[str] = []
        # if the heading line itself has content after a colon, keep it
        after = re.sub(r"^.*?%s\b[: ]*" % re.escape(label), "", line, count=1, flags=re.IGNORECASE).strip(": -#")
        if after and after.lower() != label.lower():
            body_parts.append(after)
        for j in range(idx + 1, min(idx + 8, len(lines))):
            peek = lines[j].strip()
            if not peek:
                if body_parts:
                    break
                continue
            if HEADING_RE.match(peek) or peek.startswith(("===", "---", "###", "##", "# ")):
                break
            body_parts.append(peek.lstrip("-*• ").strip())
            if sum(len(p) for p in body_parts) > MAX_SUMMARY:
                break
        summary = " ".join(body_parts).strip()
        if not summary:
            continue
        if len(summary) < MIN_SUMMARY_LEN:
            # too short to be a useful lesson; usually a dangling label like
            # "Remaining blocker" on its own line.
            continue
        if summary.startswith("```") or summary.startswith("$ "):
            # code-block fragment; unlikely to produce a stable summary.
            continue
        if len(summary) > MAX_SUMMARY:
            summary = summary[: MAX_SUMMARY - 1].rstrip() + "…"
        out.append((pattern_type, summary))
    return out


def mine(days: int) -> tuple[dict[str, LessonRow], MinerStats, list[str]]:
    stats = MinerStats()
    registry_text = REGISTRY_PATH.read_text(encoding="utf-8") if REGISTRY_PATH.exists() else ""
    existing = parse_registry(registry_text)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_ids_this_run: set[str] = set()
    scanned_files: list[str] = []

    for path in _iter_candidate_files(days):
        stats.files_scanned += 1
        scanned_files.append(path.name)
        candidates = extract_candidates(path)
        stats.candidates_found += len(candidates)
        for pattern_type, summary in candidates:
            lesson_id = compute_lesson_id(f"{pattern_type}:{summary}")
            if lesson_id in existing:
                row = existing[lesson_id]
                row.last_seen_at = now_iso
                refs = _dedupe_refs(row.evidence_refs, path.name)
                if refs != row.evidence_refs:
                    row.evidence_refs = refs
                    if lesson_id not in seen_ids_this_run:
                        stats.lessons_updated += 1
                elif lesson_id not in seen_ids_this_run:
                    stats.lessons_unchanged += 1
                # if previous pattern_type was workflow_gap but we found a more
                # specific label (failure/fix/blocker), prefer the more specific
                if row.pattern_type == "workflow_gap" and pattern_type != "workflow_gap":
                    row.pattern_type = pattern_type
                seen_ids_this_run.add(lesson_id)
            else:
                row = LessonRow(
                    lesson_id=lesson_id,
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                    source=f"ops/verification/{path.name}",
                    pattern_type=pattern_type,
                    summary=summary,
                    evidence_refs=path.name,
                    status="new",
                    impact_hint=guess_impact(summary),
                )
                existing[lesson_id] = row
                stats.lessons_created += 1
                seen_ids_this_run.add(lesson_id)
                if len(stats.examples) < 5:
                    stats.examples.append(f"{lesson_id} [{pattern_type}] {summary[:120]}")
    return existing, stats, scanned_files


def _dedupe_refs(existing_refs: str, new_ref: str) -> str:
    refs = [r.strip() for r in existing_refs.split("|") if r.strip()]
    if new_ref not in refs:
        refs.append(new_ref)
    # keep newest MAX_EVIDENCE_REFS entries
    refs = refs[-MAX_EVIDENCE_REFS:]
    return " | ".join(refs)


# --- CLI ---------------------------------------------------------------------


def _format_stats(stats: MinerStats, scanned: list[str]) -> str:
    lines = [
        "=== learning_miner ===",
        f"generated_at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"files_scanned: {stats.files_scanned}",
        f"candidates_found: {stats.candidates_found}",
        f"lessons_created: {stats.lessons_created}",
        f"lessons_updated: {stats.lessons_updated}",
        f"lessons_unchanged: {stats.lessons_unchanged}",
        "",
        "--- example new lessons ---",
    ]
    if stats.examples:
        lines.extend(stats.examples)
    else:
        lines.append("(none — no new rows this run)")
    if scanned:
        lines.append("")
        lines.append("--- recent files scanned ---")
        lines.extend(scanned[-20:])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mine lessons from ops/verification/")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="How many days back to scan (default 7)")
    parser.add_argument("--update", action="store_true", help="Write updates to LESSONS_REGISTRY.md")
    parser.add_argument("--dry-run", action="store_true", help="Alias for not passing --update")
    parser.add_argument("--out", type=str, default=None, help="Optional path to write a summary report")
    args = parser.parse_args(argv)

    existing, stats, scanned = mine(args.days)

    if args.update and not args.dry_run:
        registry_text = REGISTRY_PATH.read_text(encoding="utf-8") if REGISTRY_PATH.exists() else ""
        new_text = render_registry(registry_text, existing)
        REGISTRY_PATH.write_text(new_text, encoding="utf-8")

    report = _format_stats(stats, scanned)
    sys.stdout.write(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
