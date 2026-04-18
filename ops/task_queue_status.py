#!/usr/bin/env python3
"""
ops/task_queue_status.py — queue visibility for the Symphony Task Runner.

Scans ``ops/work_queue/{pending,completed,failed,rejected,blocked}`` (and the
parallel ``ops/workqueue/pending`` campaign-descriptor tree, when present) and
prints a concise status summary of what's queued, what's old, and what
completed/failed most recently.

This is a read-only forensic tool. It never moves, deletes, or rewrites queue
files. It's safe to run at any time by any agent or human.

Typical usage::

    # Human-readable summary (default)
    python3 ops/task_queue_status.py

    # Flag pending tasks older than 30 minutes
    python3 ops/task_queue_status.py --stale-minutes 30

    # Structured JSON (for other tools to consume)
    python3 ops/task_queue_status.py --json

    # Persist the summary as a verification artifact
    python3 ops/task_queue_status.py \
        --out ops/verification/$(date '+%Y%m%d-%H%M%S')-queue-status.txt

Exit codes:
    0 — summary produced
    2 — no queue directories exist (misconfigured repo)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_QUEUE = REPO_ROOT / "ops" / "work_queue"
# A parallel, newer campaign-descriptor tree (no-underscore variant). Not all
# installations have this — the tool treats it as optional.
ALT_WORK_QUEUE = REPO_ROOT / "ops" / "workqueue"
HEARTBEAT = REPO_ROOT / "data" / "task_runner" / "heartbeat.txt"

STATES = ("pending", "completed", "failed", "rejected", "blocked")


@dataclass
class TaskSummary:
    path: str  # repo-relative
    state: str
    task_id: str
    task_type: str
    created_by: str
    created_at: str  # ISO string from the JSON (may be empty)
    mtime: float  # filesystem mtime as epoch seconds
    age_seconds: float
    category: str  # metadata.category if present, else task_type
    notes: str  # metadata.notes if present
    requires_approval: bool
    approval_token: str
    dry_run: bool


@dataclass
class QueueSummary:
    generated_at: str
    repo_root: str
    heartbeat: str
    state_counts: dict = field(default_factory=dict)
    by_task_type: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    oldest_pending: dict | None = None
    stale_pending: list[dict] = field(default_factory=list)
    recent_completed: list[dict] = field(default_factory=list)
    recent_failed: list[dict] = field(default_factory=list)
    recent_rejected: list[dict] = field(default_factory=list)
    recent_blocked: list[dict] = field(default_factory=list)
    alt_queue_present: bool = False
    alt_queue_counts: dict = field(default_factory=dict)


# ---------- helpers ----------


def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def fmt_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def read_heartbeat() -> str:
    try:
        return HEARTBEAT.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "(no heartbeat file)"
    except Exception as exc:  # noqa: BLE001
        return f"(heartbeat read error: {exc})"


def _load_task_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def summarize_task(path: Path, state: str) -> TaskSummary:
    data = _load_task_json(path)
    try:
        st = path.stat()
        mtime = st.st_mtime
    except OSError:
        mtime = 0.0

    now = now_ts()
    age = max(0.0, now - mtime) if mtime else 0.0

    # The signed task_runner schema uses task_id/task_type/payload; the
    # alternate campaign schema uses id/type. Accept either.
    task_id = data.get("task_id") or data.get("id") or path.stem
    task_type = data.get("task_type") or data.get("type") or "unknown"
    created_by = data.get("created_by") or data.get("initiator") or "unknown"
    created_at = data.get("created_at") or ""

    payload = data.get("payload") or {}
    metadata = data.get("metadata") or {}
    category = (
        metadata.get("category")
        or payload.get("category")
        or task_type
    )
    notes = metadata.get("notes") or payload.get("notes") or ""

    # Approval + dry-run signals can live at the top level OR inside payload
    # (task_runner reads the top level; keep the tool tolerant).
    requires_approval = bool(
        data.get("requires_approval") or payload.get("requires_approval")
    )
    approval_token = str(
        data.get("approval_token") or payload.get("approval_token") or ""
    )
    dry_run = bool(data.get("dry_run") or payload.get("dry_run"))

    return TaskSummary(
        path=str(path.relative_to(REPO_ROOT)),
        state=state,
        task_id=task_id,
        task_type=task_type,
        created_by=created_by,
        created_at=created_at,
        mtime=mtime,
        age_seconds=age,
        category=str(category),
        notes=str(notes)[:200],
        requires_approval=requires_approval,
        approval_token=approval_token,
        dry_run=dry_run,
    )


def scan_state(root: Path, state: str) -> list[TaskSummary]:
    d = root / state
    if not d.is_dir():
        return []
    tasks: list[TaskSummary] = []
    for p in sorted(d.glob("*.json")):
        try:
            tasks.append(summarize_task(p, state))
        except Exception:  # noqa: BLE001
            # Never let one malformed file break the summary.
            continue
    return tasks


def as_display(tasks: Iterable[TaskSummary]) -> list[dict]:
    return [
        {
            "task_id": t.task_id,
            "task_type": t.task_type,
            "state": t.state,
            "path": t.path,
            "category": t.category,
            "age": fmt_age(t.age_seconds),
            "mtime_iso": datetime.fromtimestamp(t.mtime).isoformat(
                timespec="seconds"
            )
            if t.mtime
            else "",
            "requires_approval": t.requires_approval,
            "approval_token": t.approval_token,
            "dry_run": t.dry_run,
            "notes": t.notes,
        }
        for t in tasks
    ]


def build_summary(stale_minutes: int, recent_limit: int) -> QueueSummary:
    summary = QueueSummary(
        generated_at=datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        repo_root=str(REPO_ROOT),
        heartbeat=read_heartbeat(),
    )

    all_tasks: list[TaskSummary] = []
    for state in STATES:
        tasks = scan_state(WORK_QUEUE, state)
        summary.state_counts[state] = len(tasks)
        all_tasks.extend(tasks)

    # Aggregate counts by task_type and category.
    type_counter: Counter = Counter()
    cat_counter: Counter = Counter()
    for t in all_tasks:
        if t.state == "pending":
            type_counter[t.task_type] += 1
            cat_counter[t.category] += 1
    summary.by_task_type = dict(type_counter.most_common())
    summary.by_category = dict(cat_counter.most_common())

    # Oldest pending + stale pending.
    pending = [t for t in all_tasks if t.state == "pending"]
    if pending:
        pending_sorted = sorted(pending, key=lambda t: t.mtime)
        summary.oldest_pending = as_display([pending_sorted[0]])[0]
        threshold = stale_minutes * 60
        summary.stale_pending = as_display(
            [t for t in pending_sorted if t.age_seconds >= threshold]
        )

    # Recent N per terminal state (newest first).
    for state, bucket in (
        ("completed", "recent_completed"),
        ("failed", "recent_failed"),
        ("rejected", "recent_rejected"),
        ("blocked", "recent_blocked"),
    ):
        tasks = [t for t in all_tasks if t.state == state]
        tasks.sort(key=lambda t: t.mtime, reverse=True)
        setattr(summary, bucket, as_display(tasks[:recent_limit]))

    # Alternate campaign-descriptor tree.
    if ALT_WORK_QUEUE.is_dir():
        summary.alt_queue_present = True
        for state in ("pending", "completed", "failed", "rejected", "blocked"):
            tasks = scan_state(ALT_WORK_QUEUE, state)
            summary.alt_queue_counts[state] = len(tasks)

    return summary


# ---------- rendering ----------


def render_text(s: QueueSummary, stale_minutes: int) -> str:
    lines: list[str] = []
    lines.append("=== Symphony Task Runner — queue status ===")
    lines.append(f"generated_at: {s.generated_at}")
    lines.append(f"repo_root:    {s.repo_root}")
    lines.append(f"heartbeat:    {s.heartbeat}")
    lines.append("")

    lines.append("state_counts (ops/work_queue):")
    for state in STATES:
        count = s.state_counts.get(state, 0)
        lines.append(f"  {state:<10} {count}")
    lines.append("")

    if s.by_task_type:
        lines.append("pending by task_type:")
        for name, count in s.by_task_type.items():
            lines.append(f"  {count:>4}  {name}")
        lines.append("")

    if s.by_category and s.by_category != s.by_task_type:
        lines.append("pending by category (metadata.category):")
        for name, count in s.by_category.items():
            lines.append(f"  {count:>4}  {name}")
        lines.append("")

    if s.oldest_pending:
        op = s.oldest_pending
        lines.append(
            f"oldest_pending:    {op['task_id']}  age={op['age']}  "
            f"type={op['task_type']}  path={op['path']}"
        )
    else:
        lines.append("oldest_pending:    (none)")
    lines.append("")

    lines.append(f"stale_pending (age >= {stale_minutes}m): {len(s.stale_pending)}")
    for t in s.stale_pending:
        lines.append(
            f"  ! {t['task_id']}  age={t['age']}  type={t['task_type']}  "
            f"approval={t['requires_approval']}  dry_run={t['dry_run']}"
        )
    lines.append("")

    for label, bucket in (
        ("recent_completed", s.recent_completed),
        ("recent_failed", s.recent_failed),
        ("recent_rejected", s.recent_rejected),
        ("recent_blocked", s.recent_blocked),
    ):
        lines.append(f"{label} ({len(bucket)}):")
        if not bucket:
            lines.append("  (none)")
        for t in bucket:
            lines.append(
                f"  - {t['mtime_iso']}  {t['task_id']}  "
                f"type={t['task_type']}  age={t['age']}"
            )
        lines.append("")

    if s.alt_queue_present:
        lines.append("alt_queue (ops/workqueue) counts:")
        for state, count in s.alt_queue_counts.items():
            lines.append(f"  {state:<10} {count}")
        lines.append("")

    return "\n".join(lines)


def render_json(s: QueueSummary) -> str:
    return json.dumps(asdict(s), indent=2, sort_keys=True)


# ---------- entry point ----------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stale-minutes",
        type=int,
        default=60,
        help="pending tasks older than this many minutes are flagged as stale "
        "(default: 60)",
    )
    ap.add_argument(
        "--recent-limit",
        type=int,
        default=5,
        help="how many recent completed/failed/rejected/blocked tasks to show "
        "(default: 5)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of text",
    )
    ap.add_argument(
        "--out",
        help="also write the rendered output to this path (repo-relative paths "
        "are resolved against the repo root); useful for writing a verification "
        "artifact",
    )
    args = ap.parse_args(argv)

    if not WORK_QUEUE.is_dir():
        print(f"error: no work_queue at {WORK_QUEUE}", file=sys.stderr)
        return 2

    summary = build_summary(args.stale_minutes, args.recent_limit)
    rendered = render_json(summary) if args.json else render_text(
        summary, args.stale_minutes
    )
    print(rendered)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
