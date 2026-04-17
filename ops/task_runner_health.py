#!/usr/bin/env python3
"""
ops/task_runner_health.py — Symphony Task Runner health check.

Reports whether the runner is alive and progressing. Writes a timestamped
report to ``ops/verification/<stamp>-task-runner-health.txt`` and exits
non-zero on unhealthy state.

Checks performed:

1. **launchd**: is ``com.symphony.task-runner`` loaded? (``launchctl print``
   gui/<uid>/com.symphony.task-runner is the source of truth; we also accept
   ``launchctl list`` output as a fallback.)
2. **Heartbeat**: ``data/task_runner/heartbeat.txt`` should be less than
   ``--max-heartbeat-age`` seconds old (default 900s = 15 min).
3. **Pending queue**: not stuck — any task in ``ops/work_queue/pending/``
   older than ``--max-pending-age`` seconds (default 3600s = 1 hour) is a
   red flag.
4. **Recent verification activity**: at least one file has been written to
   ``ops/verification/`` in the last ``--max-verification-age`` seconds
   (default 3600s). We don't require *every* tick to produce output — the
   runner is throttled — but an hour of silence suggests something is off.
5. **Preflight artifact presence**: the most recent preflight report (if
   any) is surfaced. Missing preflight is a warning, not a failure, because
   the preflight only writes on actionable ticks.

Usage::

    python3 ops/task_runner_health.py                 # write report + exit
    python3 ops/task_runner_health.py --dry-run       # print, don't write
    python3 ops/task_runner_health.py --quiet         # only exit status

Exit codes:
    0  healthy
    1  unhealthy (at least one check failed)
    2  internal error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
WORK_QUEUE = REPO_ROOT / "ops" / "work_queue"
PENDING_DIR = WORK_QUEUE / "pending"
DATA_DIR = REPO_ROOT / "data" / "task_runner"
HEARTBEAT_PATH = DATA_DIR / "heartbeat.txt"

LAUNCHD_LABEL = "com.symphony.task-runner"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class HealthResult:
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    ok: bool = True
    checks: list[HealthCheck] = field(default_factory=list)
    report_path: str = ""


def _check_launchd() -> HealthCheck:
    """Try a few strategies to detect the launchd job."""
    # Prefer `launchctl list`; fall back to `launchctl print`.
    try:
        proc = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if LAUNCHD_LABEL in line:
                    return HealthCheck(
                        name="launchd.loaded",
                        ok=True,
                        detail=f"launchctl list: {line.strip()}",
                    )
    except Exception as exc:  # noqa: BLE001
        return HealthCheck(
            name="launchd.loaded",
            ok=False,
            detail=f"launchctl list failed: {exc}",
        )

    # Not in `list`; try `print` targeting the current GUI user.
    uid = os.getuid()
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{LAUNCHD_LABEL}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return HealthCheck(
                name="launchd.loaded",
                ok=True,
                detail=f"launchctl print gui/{uid}/{LAUNCHD_LABEL} succeeded",
            )
    except Exception:  # noqa: BLE001
        pass

    # Fall back to just reporting the plist file is installed.
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    if plist_path.exists():
        return HealthCheck(
            name="launchd.loaded",
            ok=False,
            detail=(
                f"plist installed at {plist_path} but launchctl did not "
                f"list {LAUNCHD_LABEL} — run `launchctl load` or `kickstart`."
            ),
        )

    return HealthCheck(
        name="launchd.loaded",
        ok=False,
        detail=f"no plist at {plist_path} and launchctl has no {LAUNCHD_LABEL}",
    )


def _check_heartbeat(max_age: int) -> HealthCheck:
    if not HEARTBEAT_PATH.exists():
        return HealthCheck(
            name="heartbeat.present",
            ok=False,
            detail=f"missing {HEARTBEAT_PATH}",
        )
    age = time.time() - HEARTBEAT_PATH.stat().st_mtime
    content = HEARTBEAT_PATH.read_text(encoding="utf-8", errors="replace").strip()
    if age > max_age:
        return HealthCheck(
            name="heartbeat.fresh",
            ok=False,
            detail=f"heartbeat is {age:.0f}s old (>{max_age}s); content='{content}'",
        )
    return HealthCheck(
        name="heartbeat.fresh",
        ok=True,
        detail=f"heartbeat age={age:.0f}s; content='{content}'",
    )


def _check_pending_queue(max_age: int) -> HealthCheck:
    if not PENDING_DIR.exists():
        return HealthCheck(
            name="queue.not_stuck",
            ok=False,
            detail=f"missing {PENDING_DIR}",
        )
    stuck: list[tuple[str, float]] = []
    newest_age: float | None = None
    for p in sorted(PENDING_DIR.glob("*.json")):
        age = time.time() - p.stat().st_mtime
        if age > max_age:
            stuck.append((p.name, age))
        if newest_age is None or age < newest_age:
            newest_age = age
    if stuck:
        detail = "; ".join(f"{n} age={a:.0f}s" for n, a in stuck)
        return HealthCheck(
            name="queue.not_stuck",
            ok=False,
            detail=f"{len(stuck)} pending task(s) older than {max_age}s: {detail}",
        )
    total = len(list(PENDING_DIR.glob("*.json")))
    return HealthCheck(
        name="queue.not_stuck",
        ok=True,
        detail=(
            f"pending={total}, "
            f"newest_age={newest_age:.0f}s" if newest_age is not None
            else "pending=0"
        ),
    )


_VERIFY_FILE_RE = re.compile(r"^\d{8}-\d{6}")


def _check_recent_verification(max_age: int) -> HealthCheck:
    if not VERIFICATION_DIR.exists():
        return HealthCheck(
            name="verification.recent",
            ok=False,
            detail=f"missing {VERIFICATION_DIR}",
        )
    newest: Path | None = None
    newest_mtime: float = 0.0
    for entry in VERIFICATION_DIR.iterdir():
        if not _VERIFY_FILE_RE.match(entry.name):
            continue
        mtime = entry.stat().st_mtime
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = entry
    if newest is None:
        return HealthCheck(
            name="verification.recent",
            ok=False,
            detail="no timestamped artifacts in ops/verification/",
        )
    age = time.time() - newest_mtime
    if age > max_age:
        return HealthCheck(
            name="verification.recent",
            ok=False,
            detail=f"newest artifact {newest.name} is {age:.0f}s old (>{max_age}s)",
        )
    return HealthCheck(
        name="verification.recent",
        ok=True,
        detail=f"newest={newest.name} age={age:.0f}s",
    )


def _check_preflight_presence() -> HealthCheck:
    """Warn-level check — not a failure if no preflight report exists yet."""
    if not VERIFICATION_DIR.exists():
        return HealthCheck(
            name="preflight.seen",
            ok=True,
            detail="verification dir missing (skipped)",
        )
    newest: Path | None = None
    newest_mtime = 0.0
    for entry in VERIFICATION_DIR.glob("*-preflight.txt"):
        m = entry.stat().st_mtime
        if m > newest_mtime:
            newest_mtime = m
            newest = entry
    if newest is None:
        return HealthCheck(
            name="preflight.seen",
            ok=True,
            detail="no preflight reports yet (runner may not have needed to heal)",
        )
    age = time.time() - newest_mtime
    return HealthCheck(
        name="preflight.seen",
        ok=True,
        detail=f"newest preflight={newest.name} age={age:.0f}s",
    )


def run_health(
    max_heartbeat_age: int = 900,
    max_pending_age: int = 3600,
    max_verification_age: int = 3600,
) -> HealthResult:
    result = HealthResult()
    result.checks.append(_check_launchd())
    result.checks.append(_check_heartbeat(max_heartbeat_age))
    result.checks.append(_check_pending_queue(max_pending_age))
    result.checks.append(_check_recent_verification(max_verification_age))
    result.checks.append(_check_preflight_presence())
    result.ok = all(c.ok for c in result.checks)
    result.finished_at = now_iso()
    return result


def write_report(result: HealthResult, out_dir: Path = VERIFICATION_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now_stamp()}-task-runner-health.txt"
    lines = [
        "=== task-runner health check ===",
        f"started_at: {result.started_at}",
        f"finished_at: {result.finished_at}",
        f"overall_ok: {result.ok}",
        "",
        "checks:",
    ]
    for c in result.checks:
        mark = "OK " if c.ok else "FAIL"
        lines.append(f"  [{mark}] {c.name}: {c.detail}")
    lines.append("")
    lines.append("--- environment ---")
    lines.append(f"LAUNCHD_LABEL: {LAUNCHD_LABEL}")
    lines.append(f"HEARTBEAT_PATH: {HEARTBEAT_PATH}")
    lines.append(f"PENDING_DIR: {PENDING_DIR}")
    lines.append(f"VERIFICATION_DIR: {VERIFICATION_DIR}")
    lines.append("")
    lines.append("--- structured result (JSON) ---")
    lines.append(
        json.dumps(
            {
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "ok": result.ok,
                "checks": [asdict(c) for c in result.checks],
            },
            indent=2,
            sort_keys=True,
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result.report_path = str(path)
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-heartbeat-age", type=int, default=900)
    ap.add_argument("--max-pending-age", type=int, default=3600)
    ap.add_argument("--max-verification-age", type=int, default=3600)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print summary without writing a verification report",
    )
    ap.add_argument("--quiet", action="store_true", help="suppress stdout summary")
    args = ap.parse_args(argv)

    try:
        result = run_health(
            max_heartbeat_age=args.max_heartbeat_age,
            max_pending_age=args.max_pending_age,
            max_verification_age=args.max_verification_age,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"health check crashed: {exc}", file=sys.stderr)
        return 2

    if not args.dry_run:
        write_report(result)

    if not args.quiet:
        tag = "healthy" if result.ok else "UNHEALTHY"
        print(f"task-runner: {tag} (report={result.report_path or '<dry-run>'})")
        for c in result.checks:
            mark = "OK " if c.ok else "!! "
            print(f"  {mark}{c.name}: {c.detail}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
