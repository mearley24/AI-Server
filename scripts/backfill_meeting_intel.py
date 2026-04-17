#!/usr/bin/env python3
"""Backfill meeting_intel for transcripts whose analyze_meeting() failed.

Reads markdown paths on stdin (one per line) — the driver shell script passes
the output of a `find` over the meetings transcript directory. For each file:

  1. Extract the embedded transcript + original source name + date
  2. Re-run audio_intake_worker.analyze_meeting() with working Ollama/OpenAI
  3. Write a new properly-analyzed markdown alongside
  4. Post a fresh meeting_intel cortex memory (tagged `backfill`)
  5. Delete the old (failed) markdown on success

The old cortex memory is left in place — cortex has no supersedes API — but
the backfill memory carries metadata.supersedes_markdown pointing at the
original file so a future cleanup pass can dedupe.

Designed to be safe to re-run: only files whose name still ends with
`-llm-analysis-failed-raw-transcript-saved.md` are picked up, so once a file
is successfully backfilled (and its old .md deleted), it won't be touched.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import from the worker module. The shell script guarantees we run with
# the repo's scripts/ dir on PYTHONPATH via sys.path manipulation below.
ROOT = Path("/Users/bob/AI-Server")
sys.path.insert(0, str(ROOT / "scripts"))

from audio_intake_worker import (  # noqa: E402
    analyze_meeting,
    post_to_cortex,
    slugify,
    TRANSCRIPTS,
)


def process_one(md_path: Path) -> int:
    """Return 0 on success/skip, nonzero on fail."""
    if not md_path.exists():
        print(f"  SKIP missing: {md_path}")
        return 0

    body = md_path.read_text(encoding="utf-8", errors="replace")

    m = re.match(r"(\d{4}-\d{2}-\d{2})__", md_path.name)
    source_date = m.group(1) if m else datetime.now().strftime("%Y-%m-%d")

    m = re.search(r"\*\*Source file:\*\*\s+`([^`]+)`", body)
    original_name = m.group(1) if m else md_path.name

    m = re.search(r"^## Transcript\s*\n\s*\n([\s\S]+?)\s*\Z", body, re.M)
    if not m:
        print(f"  FAIL no ## Transcript section: {md_path.name}")
        return 2
    transcript_text = m.group(1).strip()
    print(f"  transcript: {len(transcript_text)} chars")

    analysis = analyze_meeting(transcript_text)
    summary = (analysis.get("summary") or "").strip()
    print(f"  summary: {summary[:120]}")

    if summary.startswith("(LLM analysis failed"):
        print("  FAIL analyze_meeting still failing — leaving file in place")
        return 3
    if summary.startswith("(transcript too short"):
        print("  SKIP transcript too short")
        return 0

    # New markdown next to the old.
    topic = (summary or original_name)[:60]
    new_fname = f"{source_date}__{slugify(topic)}.md"
    new_path = TRANSCRIPTS / new_fname
    if new_path.exists() and new_path.resolve() != md_path.resolve():
        new_path = TRANSCRIPTS / f"{source_date}__{slugify(topic)}-backfill.md"

    lines = [
        f"# Meeting — {source_date}",
        "",
        f"**Source file:** `{original_name}`",
        f"**Backfilled:** {datetime.now(tz=timezone.utc).isoformat()}",
        f"**Original (failed) analysis:** `{md_path.name}`",
        "",
        "## Summary",
        summary or "(no summary)",
        "",
    ]
    for key in ("participants", "clients", "projects", "decisions",
                "action_items", "dollar_amounts", "topics"):
        vals = analysis.get(key) or []
        if vals:
            lines.append(f"## {key.replace('_', ' ').title()}")
            for v in vals:
                lines.append(f"- {v}")
            lines.append("")
    lines.append("## Transcript")
    lines.append("")
    lines.append(transcript_text)
    lines.append("")
    new_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote: {new_path.name}")

    # Cortex memory.
    decisions = analysis.get("decisions", []) or []
    action_items = analysis.get("action_items", []) or []
    content_parts = [
        f"Meeting on {source_date}",
        f"Source: {original_name}",
        "",
        f"Summary: {summary}",
        "",
    ]
    if decisions:
        content_parts.append("Decisions:")
        content_parts.extend(f"- {d}" for d in decisions)
        content_parts.append("")
    if action_items:
        content_parts.append("Action items:")
        content_parts.extend(f"- {a}" for a in action_items)
        content_parts.append("")
    content_parts.append(f"Transcript: {new_path.name}")

    payload = {
        "category": "meeting_intel",
        "title": f"Meeting {source_date}: {summary[:70]}",
        "content": "\n".join(content_parts),
        "source": f"audio_intake_backfill:{original_name}",
        "confidence": 0.8,
        "importance": 7,
        "tags": (
            ["meeting_audio", "backfill"]
            + list(analysis.get("clients", []) or [])[:3]
            + list(analysis.get("projects", []) or [])[:3]
        ),
        "metadata": {
            "date": source_date,
            "original_file": original_name,
            "transcript_path": str(new_path),
            "participants": analysis.get("participants", []) or [],
            "clients": analysis.get("clients", []) or [],
            "projects": analysis.get("projects", []) or [],
            "action_items": action_items,
            "dollar_amounts": analysis.get("dollar_amounts", []) or [],
            "topics": analysis.get("topics", []) or [],
            "analyzed_by": "audio_intake_backfill",
            "supersedes_markdown": md_path.name,
        },
        "ttl_days": 365,
    }
    cortex_id = post_to_cortex(payload)
    print(f"  cortex: {cortex_id or 'FAILED'}")

    if cortex_id:
        md_path.unlink()
        print(f"  removed old: {md_path.name}")
        return 0
    # Markdown written but cortex failed — leave both in place for retry.
    print("  cortex post failed; leaving old markdown for retry")
    return 4


def main() -> int:
    targets = [Path(line.strip()) for line in sys.stdin if line.strip()]
    print(f"candidates: {len(targets)}")
    for t in targets:
        print(f"  - {t.name}")
    print()
    worst = 0
    for md in targets:
        print(f"=== processing: {md.name} ===")
        rc = process_one(md)
        print(f"  rc={rc}")
        print()
        worst = max(worst, rc)
    print(f"ok: backfill complete, worst_rc={worst}")
    # Never fail the task-runner over individual file failures; log and move on.
    return 0


if __name__ == "__main__":
    sys.exit(main())
