#!/usr/bin/env python3
"""
ops/task_audit.py — minimal inspection utility for the Symphony Task Runner.

Given a task ID (or any substring), prints:

    * matching verification artifacts under ``ops/verification/``
    * queue files under ``ops/work_queue/{pending,completed,failed,rejected}``
    * a compact status summary (queue state + first/last lines of the
      newest verification file)

Intended for fast forensics from agents or humans: "what happened with
20260417-143719-verify-task-runner?"

Usage::

    python3 ops/task_audit.py 20260417-143719-verify-task-runner
    python3 ops/task_audit.py verify-task-runner           # substring
    python3 ops/task_audit.py --list                       # recent activity
    python3 ops/task_audit.py --json <query>               # machine output

The ``--out PATH`` flag writes the full report to ``PATH`` so audits can be
persisted under ``ops/verification/`` alongside other evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
WORK_QUEUE = REPO_ROOT / "ops" / "work_queue"
QUEUE_STATES = ("pending", "completed", "failed", "rejected")


def now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


@dataclass
class AuditMatch:
    path: str
    mtime: float
    size: int
    kind: str  # "verification" | "queue:<state>"


@dataclass
class AuditResult:
    query: str
    verification_matches: list[AuditMatch] = field(default_factory=list)
    queue_matches: list[AuditMatch] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _iter_matches(root: Path, query: str, kind: str) -> list[AuditMatch]:
    out: list[AuditMatch] = []
    if not root.exists():
        return out
    q = query.lower()
    for entry in sorted(root.rglob("*")):
        if not entry.is_file():
            continue
        if q and q not in entry.name.lower():
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        out.append(
            AuditMatch(
                path=str(entry.relative_to(REPO_ROOT)),
                mtime=st.st_mtime,
                size=st.st_size,
                kind=kind,
            )
        )
    return out


def _peek_file(path: Path, head_lines: int = 3, tail_lines: int = 5) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    lines = text.splitlines()
    return {
        "total_lines": len(lines),
        "head": lines[:head_lines],
        "tail": lines[-tail_lines:] if len(lines) > head_lines else [],
    }


def run_audit(query: str) -> AuditResult:
    result = AuditResult(query=query)

    # Verification matches.
    result.verification_matches = sorted(
        _iter_matches(VERIFICATION_DIR, query, "verification"),
        key=lambda m: m.mtime,
        reverse=True,
    )

    # Queue matches (pending/completed/failed/rejected).
    for state in QUEUE_STATES:
        result.queue_matches.extend(
            _iter_matches(WORK_QUEUE / state, query, f"queue:{state}")
        )
    result.queue_matches.sort(key=lambda m: m.mtime, reverse=True)

    # Summary.
    counts = {state: 0 for state in QUEUE_STATES}
    for m in result.queue_matches:
        state = m.kind.split(":", 1)[1]
        counts[state] = counts.get(state, 0) + 1

    newest_vpeek = {}
    if result.verification_matches:
        newest_v = REPO_ROOT / result.verification_matches[0].path
        newest_vpeek = _peek_file(newest_v)

    result.summary = {
        "verification_count": len(result.verification_matches),
        "queue_counts": counts,
        "newest_verification": (
            result.verification_matches[0].path
            if result.verification_matches
            else None
        ),
        "newest_verification_peek": newest_vpeek,
    }
    return result


def _format_match(m: AuditMatch) -> str:
    ts = datetime.fromtimestamp(m.mtime).isoformat(timespec="seconds")
    return f"  [{m.kind:>20}] {ts}  {m.size:>8}B  {m.path}"


def _render_text(result: AuditResult) -> str:
    lines: list[str] = []
    lines.append(f"=== task_audit query='{result.query}' ===")
    lines.append(f"generated: {now_stamp()}")
    lines.append("")
    lines.append(f"verification matches ({len(result.verification_matches)}):")
    if result.verification_matches:
        for m in result.verification_matches:
            lines.append(_format_match(m))
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"queue matches ({len(result.queue_matches)}):")
    if result.queue_matches:
        for m in result.queue_matches:
            lines.append(_format_match(m))
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("summary:")
    lines.append(f"  verification_count: {result.summary['verification_count']}")
    lines.append(f"  queue_counts: {result.summary['queue_counts']}")
    newest = result.summary.get("newest_verification")
    lines.append(f"  newest_verification: {newest}")
    peek = result.summary.get("newest_verification_peek") or {}
    if peek and "error" not in peek:
        lines.append(f"  newest_verification_peek.total_lines: {peek.get('total_lines')}")
        head = peek.get("head") or []
        tail = peek.get("tail") or []
        if head:
            lines.append("  head:")
            for ln in head:
                lines.append(f"    | {ln}")
        if tail:
            lines.append("  tail:")
            for ln in tail:
                lines.append(f"    | {ln}")
    elif peek and "error" in peek:
        lines.append(f"  newest_verification_peek.error: {peek['error']}")
    lines.append("")
    return "\n".join(lines)


def _render_json(result: AuditResult) -> str:
    return json.dumps(
        {
            "query": result.query,
            "verification_matches": [asdict(m) for m in result.verification_matches],
            "queue_matches": [asdict(m) for m in result.queue_matches],
            "summary": result.summary,
        },
        indent=2,
        sort_keys=True,
    )


def run_list(limit: int = 15) -> AuditResult:
    """Quick 'recent activity' view — no query, just the newest of everything."""
    return run_audit("")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "query",
        nargs="?",
        default="",
        help="task id or substring to search for (empty = list recent)",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="list recent verification + queue activity (same as empty query)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of text",
    )
    ap.add_argument(
        "--out",
        help="also write the report to this path (relative paths are resolved "
        "against the repo root)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=25,
        help="truncate verification + queue lists to this many entries",
    )
    args = ap.parse_args(argv)

    query = "" if args.list else args.query
    result = run_audit(query)

    # Truncate to the requested limit (post-sort).
    result.verification_matches = result.verification_matches[: args.limit]
    result.queue_matches = result.queue_matches[: args.limit]

    rendered = _render_json(result) if args.json else _render_text(result)
    print(rendered)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")

    # Exit 0 if we found at least one match OR the query was empty (list mode);
    # exit 1 for queries with no hits, so agents can detect "nothing to see here".
    if query and not (result.verification_matches or result.queue_matches):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
