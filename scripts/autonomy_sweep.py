#!/usr/bin/env python3
"""
Symphony Autonomy Sweep — run one safe, low-risk "look around and log"
pass over the AI-Server repo, then write a timestamped verification
report under ops/verification/.

A sweep is deliberately bounded: it only runs checks that are safe to
execute on any tick, with no side effects on production data. It is the
autonomous complement to the human-driven prompt set: every time a
realized change is detected (a commit, a STATUS_REPORT edit, a new file
in ops/realized_changes/), a sweep fires and logs the current state.

What a sweep does:

    1. Identifies the change that triggered it (if any) so future
       agents can see *why* this sweep exists.
    2. Regenerates `.cursor/prompts/INDEX.md` via
       `scripts/build_prompt_index.py` so the prompt index stays in
       sync with the prompt files on disk.
    3. Runs a shallow repo-state dump: HEAD, dirty working tree,
       `ops/work_queue/{pending,blocked}` counts, last 5 verification
       files.
    4. Optionally runs `ops/task_runner_health.py` and
       `ops/status_report_summarizer.py` if they are present.
    5. Writes everything to
       ops/verification/<stamp>-autonomy-sweep-<slug>.txt

A sweep NEVER:

    - deletes or migrates data
    - pushes commits
    - touches production services
    - executes anything from ops/approvals/ or from the high-risk gate

This script is pure stdlib + subprocess to a few repo-local helpers, so
it can run under `/opt/homebrew/bin/python3` without any additional
dependencies. It is safe to invoke by hand, from launchd, or from the
Symphony Task Runner via the `run_autonomy_sweep` task type.

Exit codes:
    0   success — report written
    2   invalid arguments
    3   repo layout unexpected (missing ops/verification or scripts/)
    4   --check mode found a problem
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

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
REALIZED_CHANGES_DIR = REPO_ROOT / "ops" / "realized_changes"
PROMPT_INDEX_SCRIPT = REPO_ROOT / "scripts" / "build_prompt_index.py"
TASK_RUNNER_HEALTH = REPO_ROOT / "ops" / "task_runner_health.py"
STATUS_REPORT_SUMMARIZER = REPO_ROOT / "ops" / "status_report_summarizer.py"


# --- helpers ----------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def _run(
    argv: list[str],
    timeout: int = 60,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Run a bounded subprocess, returning (rc, combined_output)."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd or REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        return 124, f"TIMEOUT after {timeout}s\n{exc.output or ''}"
    except FileNotFoundError as exc:
        return 127, f"NOT FOUND: {exc}\n"
    except Exception as exc:  # noqa: BLE001
        return 1, f"ERROR: {exc}\n"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "sweep") -> str:
    """Lowercase alphanumeric slug with dashes, bounded to 40 chars."""
    cleaned = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (cleaned or fallback)[:40]


# --- section builders -------------------------------------------------


@dataclass
class SweepResult:
    stamp: str
    slug: str
    trigger: str
    report_path: Path
    ok: bool = True
    sections: list[tuple[str, str]] = field(default_factory=list)

    def add(self, title: str, body: str) -> None:
        self.sections.append((title, body))

    def render(self) -> str:
        lines: list[str] = []
        lines.append("=" * 78)
        lines.append(f"AUTONOMY SWEEP — {self.stamp}")
        lines.append("=" * 78)
        lines.append(f"trigger: {self.trigger}")
        lines.append(f"host:    {os.uname().nodename}")
        lines.append(f"repo:    {REPO_ROOT}")
        lines.append(f"python:  {sys.executable}")
        lines.append("")
        for title, body in self.sections:
            lines.append(f"=== {title} ===")
            lines.append(body.rstrip())
            lines.append("")
        lines.append(f"### sweep finished {now_iso()} ok={self.ok}")
        lines.append("")
        return "\n".join(lines)


def section_git_state() -> str:
    rc1, head = _run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"])
    rc2, branch = _run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    rc3, status = _run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"], timeout=20
    )
    rc4, last = _run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "log",
            "-5",
            "--pretty=format:%h %ad %s",
            "--date=iso",
        ],
        timeout=20,
    )
    dirty_count = len([ln for ln in status.splitlines() if ln.strip()])
    lines = [
        f"head:   {head.strip() or '(unknown)'}",
        f"branch: {branch.strip() or '(unknown)'}",
        f"dirty:  {dirty_count} changed files",
        "last 5 commits:",
    ]
    for ln in last.strip().splitlines():
        lines.append(f"  {ln}")
    if dirty_count:
        lines.append("")
        lines.append("dirty files:")
        for ln in status.strip().splitlines():
            lines.append(f"  {ln}")
    return "\n".join(lines)


def section_prompt_index(dry_run: bool) -> str:
    if not PROMPT_INDEX_SCRIPT.exists():
        return f"skipped: {PROMPT_INDEX_SCRIPT} not found"
    argv = [sys.executable, str(PROMPT_INDEX_SCRIPT)]
    if dry_run:
        argv.append("--check")
    rc, out = _run(argv, timeout=30)
    return f"exit={rc}\n{out.rstrip()}"


def section_work_queue() -> str:
    base = REPO_ROOT / "ops" / "work_queue"
    if not base.exists():
        return "skipped: ops/work_queue not present"
    parts: list[str] = []
    for name in ("pending", "completed", "rejected", "failed", "blocked"):
        d = base / name
        if not d.exists():
            parts.append(f"{name:10s} 0 (missing)")
            continue
        jsons = sorted(d.glob("*.json"))
        parts.append(f"{name:10s} {len(jsons)}")
        if name in ("pending", "blocked"):
            for p in jsons[-3:]:
                parts.append(f"           {p.name}")
    return "\n".join(parts)


def section_recent_verification(limit: int = 8) -> str:
    if not VERIFICATION_DIR.exists():
        return "skipped: ops/verification not present"
    files = sorted(VERIFICATION_DIR.glob("*.txt"))[-limit:]
    lines = [f"last {len(files)} files (of {len(list(VERIFICATION_DIR.glob('*.txt')))}):"]
    for p in files:
        size = p.stat().st_size
        mtime = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        lines.append(f"  {mtime}  {size:>8}  {p.name}")
    return "\n".join(lines)


def section_task_runner_health() -> str:
    if not TASK_RUNNER_HEALTH.exists():
        return "skipped: ops/task_runner_health.py not found"
    rc, out = _run([sys.executable, str(TASK_RUNNER_HEALTH)], timeout=30)
    return f"exit={rc}\n{out.rstrip()}"


def section_status_report_summary() -> str:
    if not STATUS_REPORT_SUMMARIZER.exists():
        return "skipped: ops/status_report_summarizer.py not found"
    rc, out = _run(
        [sys.executable, str(STATUS_REPORT_SUMMARIZER), "--no-snapshot"],
        timeout=30,
    )
    return f"exit={rc}\n{out.rstrip()}"


def section_realized_change(trigger_path: Path | None) -> str:
    if trigger_path is None:
        return "no explicit trigger path (manual or scheduled sweep)"
    if not trigger_path.exists():
        return f"trigger path missing: {trigger_path}"
    try:
        body = trigger_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"could not read trigger {trigger_path}: {exc}"
    if len(body) > 4000:
        body = body[:4000] + "\n... (truncated)"
    return (
        f"trigger file: {trigger_path.relative_to(REPO_ROOT)}\n"
        f"---\n{body.rstrip()}\n---"
    )


# --- sweep entry point ------------------------------------------------


def _validate_repo_layout() -> None:
    if not VERIFICATION_DIR.exists():
        VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    if not (REPO_ROOT / "scripts").exists():
        print(f"error: {REPO_ROOT / 'scripts'} missing", file=sys.stderr)
        sys.exit(3)


def run_sweep(
    trigger: str,
    trigger_path: Path | None = None,
    slug: str | None = None,
    dry_run: bool = False,
) -> SweepResult:
    _validate_repo_layout()
    stamp = now_stamp()
    slug_val = slugify(slug or trigger, fallback="sweep")
    report_name = f"{stamp}-autonomy-sweep-{slug_val}.txt"
    report_path = VERIFICATION_DIR / report_name

    result = SweepResult(
        stamp=stamp,
        slug=slug_val,
        trigger=trigger,
        report_path=report_path,
    )

    result.add("trigger", section_realized_change(trigger_path))
    result.add("git state", section_git_state())
    result.add("prompt index", section_prompt_index(dry_run=dry_run))
    result.add("work queue", section_work_queue())
    result.add("recent verification", section_recent_verification())
    result.add("task runner health", section_task_runner_health())
    result.add("status report summary", section_status_report_summary())

    rendered = result.render()
    if not dry_run:
        report_path.write_text(rendered, encoding="utf-8")
    return result


# --- argparse + main --------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--trigger",
        default="manual",
        help="Human-readable reason for this sweep (e.g. 'STATUS_REPORT edit').",
    )
    ap.add_argument(
        "--trigger-path",
        help="Path to a realized-change sentinel file to embed in the report.",
    )
    ap.add_argument(
        "--slug",
        help="Slug to use in the report filename (default: derived from trigger).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the report and print it to stdout without writing to disk.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable summary to stdout after the sweep.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Run sweep sections that support a check mode; exit 4 if any fail.",
    )
    args = ap.parse_args()

    trigger_path = None
    if args.trigger_path:
        p = Path(args.trigger_path)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        trigger_path = p

    result = run_sweep(
        trigger=args.trigger,
        trigger_path=trigger_path,
        slug=args.slug,
        dry_run=args.dry_run or args.check,
    )

    rendered = result.render()
    if args.dry_run:
        sys.stdout.write(rendered)

    if args.check:
        # In check mode we exit non-zero if the prompt index is stale so
        # CI / sweep tasks can catch drift quickly.
        problems: list[str] = []
        for title, body in result.sections:
            if title == "prompt index" and "stale" in body.lower():
                problems.append("prompt index is stale")
            if title == "git state" and "dirty:  0 changed files" not in body:
                # Informational only — we do not fail on a dirty tree
                pass
        if problems:
            sys.stderr.write("\n".join(problems) + "\n")
            return 4

    if args.json:
        summary = {
            "stamp": result.stamp,
            "slug": result.slug,
            "trigger": result.trigger,
            "report_path": str(result.report_path.relative_to(REPO_ROOT))
            if result.report_path.is_relative_to(REPO_ROOT)
            else str(result.report_path),
            "sections": [title for title, _ in result.sections],
            "dry_run": bool(args.dry_run),
        }
        print(json.dumps(summary, indent=2))
    else:
        if not args.dry_run:
            print(f"wrote {result.report_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
