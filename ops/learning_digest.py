#!/usr/bin/env python3
"""Learning digest — "teach Matt" summary of recent system learning.

Reads ``ops/LESSONS_REGISTRY.md`` + ``ops/GUARDRAILS.md``, scans recent
``ops/verification/`` artifacts, and produces a short plain-language digest
aimed at the owner.  Intentionally simple: no LLM calls, no network, all
stdlib.

Output: ``ops/verification/YYYYMMDD-HHMMSS-learning-digest.md``.

Usage::

    python3 ops/learning_digest.py --days 7                # stdout only
    python3 ops/learning_digest.py --days 7 --write        # also write to ops/verification/
    python3 ops/learning_digest.py --days 1 --write        # daily digest
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
LESSONS_PATH = REPO_ROOT / "ops" / "LESSONS_REGISTRY.md"
GUARDRAILS_PATH = REPO_ROOT / "ops" / "GUARDRAILS.md"

MAX_NEW_LESSONS_IN_DIGEST = 8
MAX_ACTIVE_GUARDRAILS_IN_DIGEST = 8
MAX_VERIFICATION_HIGHLIGHTS = 6

# Verification files that usually contain "Matt, please do X" content.
NEEDS_MATT_KEYWORDS = (
    "[matt]",
    "needs matt",
    "blocker",
    "awaiting matt",
    "requires approval",
    "explicit approval",
    "fund wallet",
    "kraken_secret",
)


def _parse_md_table(path: Path, start_marker: str | None, end_marker: str | None) -> list[dict[str, str]]:
    """Parse a Markdown pipe-table into a list of dicts keyed by header cell."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")

    if start_marker and end_marker:
        start = text.find(start_marker)
        end = text.find(end_marker)
        if start != -1 and end != -1 and end > start:
            text = text[start + len(start_marker) : end]

    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    for line in lines:
        if set(line) <= {"|", "-", " ", ":"}:
            # separator row — the previous line was the header
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        looks_like_header = all(_looks_like_header_cell(c) for c in cells) and len(cells) >= 2
        if headers is None or looks_like_header:
            headers = cells
            continue
        if len(cells) < len(headers):
            continue
        rows.append({headers[i]: cells[i] for i in range(len(headers))})
    return rows


def _looks_like_header_cell(cell: str) -> bool:
    if not cell:
        return False
    lowered = cell.lower()
    # Markdown table headers are usually short, lowercase-or-snake_case tokens
    # or column names in backticks.
    if lowered.startswith("`") and lowered.endswith("`"):
        return True
    if re.fullmatch(r"[a-z][a-z0-9_ ]{1,40}", lowered):
        return True
    return False


def _iso_parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _collect_new_lessons(lessons: list[dict[str, str]], cutoff: datetime) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in lessons:
        ts = _iso_parse(row.get("first_seen_at", ""))
        if ts and ts >= cutoff:
            out.append(row)
    out.sort(key=lambda r: r.get("first_seen_at", ""), reverse=True)
    return out


def _collect_updated_lessons(lessons: list[dict[str, str]], cutoff: datetime) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in lessons:
        first = _iso_parse(row.get("first_seen_at", ""))
        last = _iso_parse(row.get("last_seen_at", ""))
        if last and last >= cutoff and (first is None or first < cutoff):
            out.append(row)
    out.sort(key=lambda r: r.get("last_seen_at", ""), reverse=True)
    return out


def _collect_active_guardrails(guardrails: list[dict[str, str]]) -> list[dict[str, str]]:
    active = [g for g in guardrails if g.get("status", "").lower() == "active"]
    active.sort(key=lambda g: g.get("guardrail_id", ""))
    return active


def _collect_verification_highlights(cutoff: datetime) -> tuple[list[str], list[str]]:
    """Return (recent_files, needs_matt_hits)."""
    if not VERIFICATION_DIR.is_dir():
        return [], []
    recent: list[Path] = []
    for p in VERIFICATION_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in {".txt", ".md"}:
            continue
        if "preflight" in p.name:
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if mtime >= cutoff:
            recent.append(p)
    recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    files = [p.name for p in recent[:MAX_VERIFICATION_HIGHLIGHTS]]
    matt_hits: list[str] = []
    for p in recent:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:8000].lower()
        except OSError:
            continue
        if any(kw in head for kw in NEEDS_MATT_KEYWORDS):
            matt_hits.append(p.name)
    return files, matt_hits[:MAX_VERIFICATION_HIGHLIGHTS]


def _format_lesson(row: dict[str, str]) -> str:
    lesson_id = row.get("lesson_id", "?")
    pattern = row.get("pattern_type", "?")
    summary = row.get("summary", "").strip()
    impact = row.get("impact_hint", "") or "unknown"
    src = row.get("source", "")
    # trim to 160 chars for readability
    if len(summary) > 160:
        summary = summary[:159].rstrip() + "…"
    return f"- **{lesson_id}** _{pattern}_ ({impact}): {summary}  \n  source: `{src}`"


def _format_guardrail(row: dict[str, str]) -> str:
    gid = row.get("guardrail_id", "?")
    scope = row.get("scope", "?")
    tier = row.get("risk_tier", "?")
    desc = row.get("description", "").strip()
    if len(desc) > 220:
        desc = desc[:219].rstrip() + "…"
    return f"- **{gid}** _{scope}_ (risk tier {tier}): {desc}"


def build_digest(days: int) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    lessons = _parse_md_table(LESSONS_PATH, "<!-- LESSONS_TABLE_START -->", "<!-- LESSONS_TABLE_END -->")
    guardrails = _parse_md_table(GUARDRAILS_PATH, None, None)
    # filter guardrails to just the active-guardrails table (skip the schema + deprecated tables
    # by requiring the `guardrail_id` cell to match G-NN).
    guardrails = [g for g in guardrails if re.match(r"^G-\d{2,}$", g.get("guardrail_id", ""))]

    new_lessons = _collect_new_lessons(lessons, cutoff)
    updated_lessons = _collect_updated_lessons(lessons, cutoff)
    active_guardrails = _collect_active_guardrails(guardrails)
    recent_files, matt_hits = _collect_verification_highlights(cutoff)

    total_lessons = len(lessons)
    total_guardrails = len(guardrails)
    window_label = "last 24 hours" if days <= 1 else f"last {days} days"

    lines: list[str] = [
        f"# Learning digest — {window_label}",
        "",
        f"_generated: {now.strftime('%Y-%m-%d %H:%M UTC')} · window: {days}d · "
        f"lessons in registry: {total_lessons} · active guardrails: {len(active_guardrails)} / {total_guardrails}_",
        "",
        "## Summary",
        "",
        f"- New lessons in window: **{len(new_lessons)}**",
        f"- Lessons updated in window (seen again with fresh evidence): **{len(updated_lessons)}**",
        f"- Verification files written in window: **{len(recent_files)}** (preflight heartbeat excluded)",
        f"- Items flagged as needing Matt's real-world input: **{len(matt_hits)}**",
        "",
    ]

    lines.append("## New lessons")
    lines.append("")
    if new_lessons:
        for row in new_lessons[:MAX_NEW_LESSONS_IN_DIGEST]:
            lines.append(_format_lesson(row))
        if len(new_lessons) > MAX_NEW_LESSONS_IN_DIGEST:
            lines.append(f"- …plus {len(new_lessons) - MAX_NEW_LESSONS_IN_DIGEST} more in `ops/LESSONS_REGISTRY.md`.")
    else:
        lines.append("_None._ The system didn't observe anything new enough to turn into a lesson in this window.")
    lines.append("")

    lines.append("## Updated lessons (same pattern, more evidence)")
    lines.append("")
    if updated_lessons:
        for row in updated_lessons[:MAX_NEW_LESSONS_IN_DIGEST]:
            lines.append(_format_lesson(row))
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Active guardrails")
    lines.append("")
    if active_guardrails:
        for row in active_guardrails[:MAX_ACTIVE_GUARDRAILS_IN_DIGEST]:
            lines.append(_format_guardrail(row))
    else:
        lines.append("_None yet._ Promote stable lessons from the registry into `ops/GUARDRAILS.md`.")
    lines.append("")

    lines.append("## Verification activity")
    lines.append("")
    if recent_files:
        lines.append("Most recent reports:")
        for name in recent_files:
            lines.append(f"- `ops/verification/{name}`")
    else:
        lines.append("_No recent verification artifacts._ That is unusual — check `scripts/task_runner.py` status.")
    lines.append("")

    lines.append("## Needs Matt")
    lines.append("")
    if matt_hits:
        lines.append("These verification reports contain items explicitly flagged for the owner:")
        for name in matt_hits:
            lines.append(f"- `ops/verification/{name}`")
    else:
        lines.append("_No items this window._ The system reported nothing that requires real-world business input.")
    lines.append("")

    lines.append("## How this was produced")
    lines.append("")
    lines.append("- Sources: `ops/LESSONS_REGISTRY.md`, `ops/GUARDRAILS.md`, `ops/verification/*`")
    lines.append("- Generator: `python3 ops/learning_digest.py --days N --write`")
    lines.append("- Miner that feeds the registry: `python3 ops/learning_miner.py --days N --update`")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Teach-Matt learning digest")
    parser.add_argument("--days", type=int, default=7, help="Window size (default 7)")
    parser.add_argument("--write", action="store_true", help="Also write the digest to ops/verification/")
    parser.add_argument("--out", type=str, default=None, help="Explicit output path (overrides default name)")
    args = parser.parse_args(argv)

    digest = build_digest(args.days)
    sys.stdout.write(digest)

    if args.write or args.out:
        if args.out:
            out_path = Path(args.out)
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_path = VERIFICATION_DIR / f"{stamp}-learning-digest.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(digest, encoding="utf-8")
        sys.stdout.write(f"\nwrote: {out_path.relative_to(REPO_ROOT)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
