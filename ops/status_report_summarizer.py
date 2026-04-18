#!/usr/bin/env python3
"""STATUS_REPORT.md summarizer — owner-readable digest of repo status.

Reads ``STATUS_REPORT.md`` at the repo root, parses its major sections
(``Now`` / ``Next`` / ``Later`` / ``Done`` / ``Reference: ...``), classifies
each bullet (open / done / followup / needs_matt), and writes a compact
summary aimed at Matt to ``ops/verification/``.

Conventions (see ``ops/AGENT_VERIFICATION_PROTOCOL.md``):

- Bullets starting with ``- [FOLLOWUP]`` are rendered under a dedicated
  "Follow-ups" block.
- Bullets starting with ``- [NEEDS_MATT]`` are rendered under a dedicated
  "Needs Matt" block — these are items that require a real-world decision
  from Matt (pricing, funding, testimonials, credentials, approvals).
- Legacy prose markers (``[Matt]``, ``Needs Matt``, ``Awaiting Matt``,
  ``Fund ... wallet``, ``KRAKEN_SECRET``, etc.) are also picked up so the
  summarizer works on today's STATUS_REPORT.md without requiring a
  tagging pass first.
- Bullets starting with ``✅`` or wrapped in ``~~strikethrough~~`` are
  treated as done.

The summarizer also persists a snapshot JSON at
``data/status_report_summarizer/last_snapshot.json`` so the next run can
produce a "what changed since last summary" block. Snapshot is cheap and
repo-gitignored via the ``data/`` tree.

Usage::

    python3 ops/status_report_summarizer.py --print       # stdout only
    python3 ops/status_report_summarizer.py --write       # also write to ops/verification/
    python3 ops/status_report_summarizer.py --write --out ops/verification/custom.md
    python3 ops/status_report_summarizer.py --no-snapshot # skip snapshot update
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_REPORT = REPO_ROOT / "STATUS_REPORT.md"
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
SNAPSHOT_DIR = REPO_ROOT / "data" / "status_report_summarizer"
SNAPSHOT_PATH = SNAPSHOT_DIR / "last_snapshot.json"

# Sections we actively summarize. Reference sections are counted but not
# enumerated — they are historical.
ACTIONABLE_SECTIONS = ("Now", "Next", "Later")
DONE_SECTION = "Done"

# Tagging markers.
TAG_FOLLOWUP = "[FOLLOWUP]"
TAG_NEEDS_MATT = "[NEEDS_MATT]"

# Regex patterns for legacy / implicit flags.
NEEDS_MATT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(re.escape(TAG_NEEDS_MATT), re.IGNORECASE),
    re.compile(r"\[\s*matt\s*\]", re.IGNORECASE),
    re.compile(r"\bneeds?\s+matt\b", re.IGNORECASE),
    re.compile(r"\bawaiting\s+matt\b", re.IGNORECASE),
    re.compile(r"\brequires?\s+matt\b", re.IGNORECASE),
    re.compile(r"\bpending\s+matt\b", re.IGNORECASE),
    re.compile(r"\bmatt\s+action\b", re.IGNORECASE),
    re.compile(r"\bfund\s+\S+\s+wallet\b", re.IGNORECASE),
    re.compile(r"\bkraken_secret\b", re.IGNORECASE),
    re.compile(r"\brequires?\s+approval\b", re.IGNORECASE),
    re.compile(r"\bexplicit\s+approval\b", re.IGNORECASE),
)

FOLLOWUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(re.escape(TAG_FOLLOWUP), re.IGNORECASE),
    re.compile(r"\bfollow[\s-]*up\b", re.IGNORECASE),
    re.compile(r"\brecommended\s+next\s+action\b", re.IGNORECASE),
    re.compile(r"\bremaining\s+follow[\s-]*up\b", re.IGNORECASE),
)

DONE_MARKERS = ("✅", "done ", "complete", "resolved")
STRIKE_RE = re.compile(r"~~[^~]+~~")

HEADING_RE = re.compile(r"^(?P<hashes>#{2,4})\s+(?P<title>.+?)\s*$")


@dataclass
class Bullet:
    """One parsed bullet from the STATUS_REPORT."""

    section: str
    raw: str
    text: str
    is_done: bool = False
    is_followup: bool = False
    is_needs_matt: bool = False
    tags: list[str] = field(default_factory=list)

    def key(self) -> str:
        """Stable key for diffing across runs (normalized, truncated)."""
        k = re.sub(r"\s+", " ", self.text).strip().lower()
        k = re.sub(r"[`*_]+", "", k)
        k = re.sub(r"\d{4}-\d{2}-\d{2}", "", k)
        k = re.sub(r"\d{1,2}:\d{2}", "", k)
        return k[:160].strip()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "section": self.section,
            "text": self.text,
            "is_done": self.is_done,
            "is_followup": self.is_followup,
            "is_needs_matt": self.is_needs_matt,
            "tags": list(self.tags),
            "key": self.key(),
        }


@dataclass
class ParsedReport:
    sections: list[str] = field(default_factory=list)
    bullets_by_section: dict[str, list[Bullet]] = field(default_factory=dict)


# --- parsing ----------------------------------------------------------------


def parse_status_report(text: str) -> ParsedReport:
    """Parse STATUS_REPORT.md into bullets keyed by top-level section name."""
    report = ParsedReport()
    current_section: str | None = None
    # We only capture bullets at the top level of a ``##`` section. Bullets
    # under ``###`` sub-headings are included under the parent ``##``
    # section so the summarizer sees a flat per-section view.
    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        m = HEADING_RE.match(line)
        if m:
            hashes = m.group("hashes")
            title = m.group("title").strip()
            if len(hashes) == 2:
                # Stop at the first "## Reference:" heading for actionable
                # parsing, but keep the section so reference counts work.
                current_section = title
                if title not in report.bullets_by_section:
                    report.sections.append(title)
                    report.bullets_by_section[title] = []
            # ``###`` / ``####`` headings do not reset current_section.
            continue

        if current_section is None:
            continue

        if not line.lstrip().startswith("-"):
            continue

        # Only top-level bullets (2 leading spaces or less). Nested list
        # items are contextual detail, not first-class follow-ups.
        leading_ws = len(line) - len(line.lstrip(" "))
        if leading_ws > 2:
            continue

        bullet_text = line.lstrip()[1:].strip()
        if not bullet_text:
            continue
        # Skip markdown horizontal rules rendered as bullets ("---", "--").
        if set(bullet_text) <= {"-", " "}:
            continue
        # Skip pure italic descriptor lines inside bullets.
        if bullet_text.startswith("_") and bullet_text.endswith("_"):
            continue

        bullet = classify_bullet(current_section, bullet_text)
        report.bullets_by_section[current_section].append(bullet)
    return report



def classify_bullet(section: str, raw: str) -> Bullet:
    """Decide whether a bullet is done / followup / needs_matt."""
    text = raw
    is_done = False
    # Strikethrough title at the start of the bullet is the most common
    # "done" marker in this repo's STATUS_REPORT: a bullet whose leading
    # ~~...~~ title has been crossed out. That almost always precedes a
    # "✅ Done ..." / "✅ Resolved ..." phrase.
    if raw.lstrip().startswith("~~"):
        is_done = True
    if raw.lstrip().startswith("✅"):
        is_done = True
    if re.search(
        r"(?:✅|:white_check_mark:)\s*\*{0,2}\s*(done|complete|completed|resolved|fixed)",
        text,
        re.IGNORECASE,
    ):
        is_done = True
    # Fallback: if the strikethrough covers most of the bullet, treat as done.
    strike_spans = STRIKE_RE.findall(text)
    stripped = STRIKE_RE.sub("", text).strip()
    if strike_spans and len(stripped) < len(text) * 0.5:
        is_done = True


    tags: list[str] = []
    is_followup = False
    is_needs_matt = False

    if TAG_FOLLOWUP.lower() in text.lower():
        is_followup = True
        tags.append("FOLLOWUP")
    if TAG_NEEDS_MATT.lower() in text.lower():
        is_needs_matt = True
        tags.append("NEEDS_MATT")

    # Infer needs_matt from legacy prose. Only flag when the bullet is
    # NOT already marked done — a resolved item is no longer pending.
    if not is_done:
        for pat in NEEDS_MATT_PATTERNS:
            if pat.search(text):
                is_needs_matt = True
                break
        if not is_followup:
            for pat in FOLLOWUP_PATTERNS:
                if pat.search(text):
                    is_followup = True
                    break

    # Items in the "Later" section are implicit follow-ups unless
    # explicitly marked otherwise.
    if section == "Later" and not is_done and not is_followup:
        is_followup = True

    # Items in the "Now" section are implicit needs_matt / blocker.
    if section == "Now" and not is_done and not is_needs_matt:
        # Don't auto-tag as needs_matt without a keyword — but mark as a
        # high-priority follow-up so it surfaces in the summary.
        is_followup = True

    return Bullet(
        section=section,
        raw=raw,
        text=text.strip(),
        is_done=is_done,
        is_followup=is_followup,
        is_needs_matt=is_needs_matt,
        tags=tags,
    )


# --- helpers ----------------------------------------------------------------


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""
    return ""


def current_commit_hash() -> str:
    return _git("rev-parse", "--short=12", "HEAD") or "unknown"


def status_report_last_touched() -> str:
    commit_date = _git("log", "-1", "--format=%cs", "--", str(STATUS_REPORT))
    return commit_date or ""


def truncate(text: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_snapshot(report: ParsedReport, commit: str) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit,
        "sections": {
            name: [b.to_snapshot() for b in bullets]
            for name, bullets in report.bullets_by_section.items()
        },
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Sections we report diffs for. Reference narrative sections are excluded
# so incident writeups don't flood the "what changed" block.
DIFF_SECTIONS = set(ACTIONABLE_SECTIONS) | {DONE_SECTION}


def diff_against_snapshot(report: ParsedReport, snap: dict) -> dict:
    """Return a dict of per-section added/removed keys + done transitions.

    Only bullets in Now / Next / Later / Done are diffed. Reference
    sections carry historical prose and would otherwise dominate the diff.
    When no prior snapshot exists the result is empty so the summary can
    render a friendly 'first run' message.
    """
    out: dict[str, dict] = {}
    if not snap:
        return {"added": [], "removed": [], "moved_to_done": [], "reopened": []}

    prev_sections: dict[str, list[dict]] = snap.get("sections", {}) if snap else {}

    # Build previous key-state maps for open-vs-done transitions.
    prev_all: dict[str, dict] = {}
    for sec, items in prev_sections.items():
        if sec not in DIFF_SECTIONS:
            continue
        for item in items:
            key = item.get("key")
            if not key:
                continue
            prev_all[key] = {"section": sec, **item}

    cur_all: dict[str, dict] = {}
    for sec, bullets in report.bullets_by_section.items():
        if sec not in DIFF_SECTIONS:
            continue
        for b in bullets:
            key = b.key()
            if not key:
                continue
            cur_all[key] = {"section": sec, **b.to_snapshot()}


    # Items that disappeared or moved to Done.
    moved_to_done: list[tuple[str, str]] = []
    removed: list[tuple[str, str]] = []
    added: list[tuple[str, str]] = []
    now_open_was_done: list[tuple[str, str]] = []

    for key, cur in cur_all.items():
        prev = prev_all.get(key)
        if prev is None:
            added.append((cur["section"], cur["text"]))
        else:
            # Transition: open → done
            if cur.get("is_done") and not prev.get("is_done"):
                moved_to_done.append((cur["section"], cur["text"]))
            elif prev.get("is_done") and not cur.get("is_done"):
                now_open_was_done.append((cur["section"], cur["text"]))

    for key, prev in prev_all.items():
        if key not in cur_all:
            removed.append((prev["section"], prev["text"]))

    out["added"] = added
    out["removed"] = removed
    out["moved_to_done"] = moved_to_done
    out["reopened"] = now_open_was_done
    return out


# --- summary rendering -------------------------------------------------------


def render_summary(report: ParsedReport, diff: dict, commit: str) -> str:
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    report_date = status_report_last_touched() or "unknown"

    out: list[str] = []
    out.append("# STATUS_REPORT summary")
    out.append("")
    out.append(f"_Generated: {stamp} · repo commit: `{commit}` · "
               f"STATUS_REPORT last touched: {report_date}_")
    out.append("")
    out.append(
        "This digest is produced by `ops/status_report_summarizer.py` from "
        "`STATUS_REPORT.md`. See `ops/AGENT_VERIFICATION_PROTOCOL.md` for the "
        "tagging conventions (`[FOLLOWUP]`, `[NEEDS_MATT]`)."
    )
    out.append("")

    # --- headline stats ---
    open_items = collect_open_items(report)
    done_items = collect_done_items(report)
    followups = [b for b in open_items if b.is_followup]
    needs_matt = [b for b in open_items if b.is_needs_matt]

    out.append("## Headline")
    out.append("")
    out.append(f"- **Open items:** {len(open_items)} across "
               f"{sum(1 for s in ACTIONABLE_SECTIONS if report.bullets_by_section.get(s))} "
               f"actionable sections")
    out.append(f"- **Follow-ups:** {len(followups)}")
    out.append(f"- **Needs Matt:** {len(needs_matt)}")
    out.append(f"- **Completed (in Done section):** {len(done_items)}")
    out.append("")

    # --- what changed since last summary ---
    out.append("## What changed since last summary")
    out.append("")
    if not diff or all(not diff.get(k) for k in ("added", "removed", "moved_to_done", "reopened")):
        out.append("_No prior snapshot or no detectable changes._")
    else:
        for label, key in (
            ("🟢 Newly added", "added"),
            ("✅ Moved to done", "moved_to_done"),
            ("⚠️ Reopened", "reopened"),
            ("🗑 Removed", "removed"),
        ):
            items = diff.get(key, [])
            if not items:
                continue
            out.append(f"**{label}:** {len(items)}")
            for sec, text in items[:6]:
                out.append(f"- _{sec}_: {truncate(text, 140)}")
            if len(items) > 6:
                out.append(f"- …and {len(items) - 6} more")
            out.append("")
    out.append("")

    # --- per-category blocks ---
    out.append("## Current open items by category")
    out.append("")
    for sec in ACTIONABLE_SECTIONS:
        bullets = report.bullets_by_section.get(sec, [])
        open_bullets = [b for b in bullets if not b.is_done]
        if not open_bullets:
            out.append(f"### {sec}")
            out.append("")
            out.append("_Nothing open._")
            out.append("")
            continue
        out.append(f"### {sec} ({len(open_bullets)})")
        out.append("")
        for b in open_bullets[:10]:
            marker = ""
            if b.is_needs_matt:
                marker = "🧑 "
            elif b.is_followup:
                marker = "🔁 "
            out.append(f"- {marker}{truncate(b.text, 180)}")
        if len(open_bullets) > 10:
            out.append(f"- …and {len(open_bullets) - 10} more")
        out.append("")

    # --- follow-ups block ---
    out.append("## Follow-ups")
    out.append("")
    if followups:
        for b in followups[:15]:
            out.append(f"- _{b.section}_: {truncate(b.text, 180)}")
        if len(followups) > 15:
            out.append(f"- …and {len(followups) - 15} more")
    else:
        out.append("_No open follow-ups identified._")
    out.append("")

    # --- needs matt block ---
    out.append("## Needs Matt")
    out.append("")
    if needs_matt:
        out.append("_Items that require Matt's real-world decision or input._")
        out.append("")
        for b in needs_matt:
            out.append(f"- _{b.section}_: {truncate(b.text, 220)}")
    else:
        out.append("_No outstanding items require Matt's input this pass._")
    out.append("")

    # --- top 3 next actions ---
    top3 = pick_top_three(report)
    out.append("## Top 3 next actions")
    out.append("")
    if top3:
        for i, b in enumerate(top3, start=1):
            marker = ""
            if b.is_needs_matt:
                marker = " (🧑 needs Matt)"
            elif b.is_followup:
                marker = " (🔁 follow-up)"
            out.append(f"{i}. _{b.section}_{marker}: {truncate(b.text, 200)}")
    else:
        out.append("_No open items. System is caught up._")
    out.append("")

    # --- reference sections count ---
    ref_sections = [
        s for s in report.sections if s.lower().startswith("reference")
    ]
    out.append("## Reference sections (historical)")
    out.append("")
    if ref_sections:
        out.append(
            f"STATUS_REPORT.md contains {len(ref_sections)} reference "
            "sections (detailed incident reports / historical snapshots). "
            "They are not enumerated here; run `grep '^## Reference' "
            "STATUS_REPORT.md` to list them."
        )
    else:
        out.append("_No reference sections present._")
    out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_Produced by `ops/status_report_summarizer.py`. Snapshot written "
        "to `data/status_report_summarizer/last_snapshot.json`; next run "
        "will diff against it._"
    )
    out.append("")
    return "\n".join(out)


def collect_open_items(report: ParsedReport) -> list[Bullet]:
    items: list[Bullet] = []
    for sec in ACTIONABLE_SECTIONS:
        for b in report.bullets_by_section.get(sec, []):
            if not b.is_done:
                items.append(b)
    return items


def collect_done_items(report: ParsedReport) -> list[Bullet]:
    return list(report.bullets_by_section.get(DONE_SECTION, []))


def pick_top_three(report: ParsedReport) -> list[Bullet]:
    """Prioritize Now → Next → Later; prefer Needs Matt, then follow-ups."""
    pool: list[Bullet] = []
    for sec in ACTIONABLE_SECTIONS:
        for b in report.bullets_by_section.get(sec, []):
            if b.is_done:
                continue
            pool.append(b)

    def score(b: Bullet) -> tuple[int, int, int]:
        sec_rank = {"Now": 0, "Next": 1, "Later": 2}.get(b.section, 3)
        matt_rank = 0 if b.is_needs_matt else 1
        followup_rank = 0 if b.is_followup else 1
        return (sec_rank, matt_rank, followup_rank)

    pool.sort(key=score)
    return pool[:3]


# --- main --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize STATUS_REPORT.md into an owner-readable digest."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the summary to ops/verification/<stamp>-status-report-summary.md",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Explicit output path (overrides the default filename).",
    )
    parser.add_argument(
        "--print",
        dest="print_stdout",
        action="store_true",
        help="Print the summary to stdout (default when --write is absent).",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Skip writing the last_snapshot.json file.",
    )
    parser.add_argument(
        "--status-report",
        type=str,
        default=str(STATUS_REPORT),
        help="Path to STATUS_REPORT.md (default: repo root).",
    )
    args = parser.parse_args(argv)

    status_path = Path(args.status_report)
    if not status_path.exists():
        print(f"ERROR: STATUS_REPORT not found at {status_path}", file=sys.stderr)
        return 2

    text = status_path.read_text(encoding="utf-8", errors="replace")
    report = parse_status_report(text)
    commit = current_commit_hash()
    snap = load_snapshot()
    diff = diff_against_snapshot(report, snap)
    summary = render_summary(report, diff, commit)

    wrote_any = False
    if args.write or args.out:
        if args.out:
            out_path = Path(args.out)
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_path = VERIFICATION_DIR / f"{stamp}-status-report-summary.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(summary, encoding="utf-8")
        print(f"wrote: {out_path.relative_to(REPO_ROOT)}")
        wrote_any = True

    if args.print_stdout or not wrote_any:
        sys.stdout.write(summary)

    if not args.no_snapshot:
        save_snapshot(report, commit)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
