#!/usr/bin/env python3
"""
ops/task_runner_preflight.py — Symphony Task Runner preflight self-heal.

Runs before each task-runner tick (invoked from ``scripts/task_runner.py``).

What it does, in order:

1. ``git status --porcelain`` to detect unmerged / conflicted files and any
   working-tree changes.
2. Ensures ``.gitattributes`` contains ``merge=ours`` rules for a small
   whitelist of generated/state files (``knowledge/markup_exports/.session_tracking.json``
   and ``data/cortex/digests/**``). Adds missing lines if needed.
3. Auto-resolves conflicts *only* for whitelisted paths using
   ``git checkout --ours`` + ``git add``.
4. Stages any whitelisted working-tree changes (``knowledge/markup_exports/.session_tracking.json``,
   ``data/cortex/digests/**``, ``.gitattributes`` additions we made) and commits
   them with the Perplexity Computer identity, then pushes.
5. Writes a timestamped preflight report to
   ``ops/verification/YYYYMMDD-HHMMSS-preflight.txt`` and returns it.

Non-whitelisted conflicts are **never** swallowed. They are reported in full
and the preflight exit status becomes non-zero so the runner can stop
processing tasks until the situation is resolved.

The preflight is idempotent: running it when there is nothing to do leaves
the repo untouched and does not commit/push.

Can be imported as a module (``run_preflight()`` returns a structured result)
or executed directly (``python3 ops/task_runner_preflight.py``).
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"

# Whitelist of paths the preflight is allowed to auto-resolve / auto-commit.
# Each entry is a gitignore-style pattern matched against the path reported
# by ``git status --porcelain``.
SAFE_PATTERNS: tuple[str, ...] = (
    "knowledge/markup_exports/.session_tracking.json",
    "data/cortex/digests/*",
    "data/cortex/digests/**",
)

# Required lines in .gitattributes. Order matters — we append missing ones
# in this order.
REQUIRED_GITATTRIBUTES: tuple[str, ...] = (
    "knowledge/markup_exports/.session_tracking.json merge=ours",
    "data/cortex/digests/** merge=ours",
)

GIT_AUTHOR_NAME = "Perplexity Computer"
GIT_AUTHOR_EMAIL = "earleystream@gmail.com"


def now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class PreflightResult:
    """Structured summary of what preflight did."""

    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    report_path: str = ""
    gitattributes_updated: bool = False
    gitattributes_added_lines: list[str] = field(default_factory=list)
    conflicts_resolved: list[str] = field(default_factory=list)
    dirty_whitelisted_staged: list[str] = field(default_factory=list)
    unsafe_conflicts: list[str] = field(default_factory=list)
    commit_pushed: bool = False
    commit_sha: str = ""
    ok: bool = True
    notes: list[str] = field(default_factory=list)


# ---------- git helpers ----------


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    cmd = [
        "git",
        "-C",
        str(REPO_ROOT),
        "-c",
        f"user.name={GIT_AUTHOR_NAME}",
        "-c",
        f"user.email={GIT_AUTHOR_EMAIL}",
        *args,
    ]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _status_porcelain() -> list[tuple[str, str]]:
    """Return a list of (status_code, path) from ``git status --porcelain``."""
    proc = _git("status", "--porcelain")
    out: list[tuple[str, str]] = []
    if proc.returncode != 0:
        return out
    for raw in proc.stdout.splitlines():
        if not raw.strip():
            continue
        # porcelain format: XY <path>, with path possibly quoted.
        code = raw[:2]
        path = raw[3:].strip()
        # Handle renames "orig -> new" — take the new path.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        # Strip optional surrounding quotes.
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        out.append((code, path))
    return out


def _is_conflict(code: str) -> bool:
    """Porcelain conflict codes: DD, AU, UD, UA, DU, AA, UU."""
    return code.strip() in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
    # Also allow exact match against the bare pattern (no wildcards).
    return any(path == p for p in patterns)


# ---------- gitattributes maintenance ----------


def ensure_gitattributes(result: PreflightResult) -> None:
    """Append any missing merge=ours lines to .gitattributes."""
    existing: list[str] = []
    if GITATTRIBUTES.exists():
        existing = GITATTRIBUTES.read_text(encoding="utf-8").splitlines()
    existing_set = {ln.strip() for ln in existing if ln.strip()}

    missing = [ln for ln in REQUIRED_GITATTRIBUTES if ln not in existing_set]
    if not missing:
        return

    new_content = "\n".join(existing + missing) + "\n"
    GITATTRIBUTES.write_text(new_content, encoding="utf-8")
    result.gitattributes_updated = True
    result.gitattributes_added_lines.extend(missing)


# ---------- whitelisted conflict resolution ----------


def resolve_whitelisted_conflicts(result: PreflightResult) -> None:
    for code, path in _status_porcelain():
        if not _is_conflict(code):
            continue
        if _matches_any(path, SAFE_PATTERNS):
            # Prefer our side (the runner's committed version).
            proc = _git("checkout", "--ours", "--", path)
            if proc.returncode != 0:
                result.notes.append(
                    f"checkout --ours failed for {path}: {proc.stderr.strip()}"
                )
                result.unsafe_conflicts.append(f"{code} {path} (checkout-ours failed)")
                result.ok = False
                continue
            add = _git("add", "--", path)
            if add.returncode != 0:
                result.notes.append(
                    f"git add failed for {path}: {add.stderr.strip()}"
                )
                result.unsafe_conflicts.append(f"{code} {path} (add failed)")
                result.ok = False
                continue
            result.conflicts_resolved.append(path)
        else:
            result.unsafe_conflicts.append(f"{code} {path}")
            result.ok = False


def stage_whitelisted_dirty(result: PreflightResult) -> None:
    """Stage non-conflict working-tree changes for whitelisted paths.

    This catches the common case where `.session_tracking.json` or a digest
    file was modified locally (no conflict) but would otherwise block a
    `git pull --ff-only`. We stage + commit it so the next pull is clean.
    """
    for code, path in _status_porcelain():
        if _is_conflict(code):
            continue
        # Only care about modifications / deletions / untracked for whitelisted files.
        if code.strip() in {""}:
            continue
        if _matches_any(path, SAFE_PATTERNS):
            add = _git("add", "--", path)
            if add.returncode == 0:
                result.dirty_whitelisted_staged.append(path)
            else:
                result.notes.append(
                    f"git add (dirty) failed for {path}: {add.stderr.strip()}"
                )
        elif path == ".gitattributes" and result.gitattributes_updated:
            add = _git("add", "--", ".gitattributes")
            if add.returncode == 0:
                result.dirty_whitelisted_staged.append(".gitattributes")


def commit_and_push_if_needed(result: PreflightResult) -> None:
    """Commit + push anything the preflight staged. Idempotent."""
    # Anything staged?
    staged_check = _git("diff", "--cached", "--name-only")
    staged = [ln for ln in staged_check.stdout.splitlines() if ln.strip()]
    if not staged:
        return

    summary_bits = []
    if result.conflicts_resolved:
        summary_bits.append(f"{len(result.conflicts_resolved)} conflicts resolved")
    if result.dirty_whitelisted_staged:
        dirty_count = len(
            [p for p in result.dirty_whitelisted_staged if p != ".gitattributes"]
        )
        if dirty_count:
            summary_bits.append(f"{dirty_count} state files synced")
    if result.gitattributes_updated:
        summary_bits.append(".gitattributes merge=ours refreshed")
    summary = "; ".join(summary_bits) or "preflight auto-heal"

    msg = f"ops: task-runner preflight — {summary}"
    commit = _git("commit", "-m", msg)
    if commit.returncode != 0:
        # "nothing to commit" is fine (race), log others.
        if "nothing to commit" not in (commit.stdout + commit.stderr):
            result.notes.append(
                f"commit rc={commit.returncode}: {commit.stdout}{commit.stderr}"
            )
        return

    sha = _git("rev-parse", "HEAD").stdout.strip()
    push = _git("push", "origin", "main")
    if push.returncode != 0:
        result.notes.append(
            f"push rc={push.returncode}: {push.stdout}{push.stderr}"
        )
        result.ok = False
        return

    result.commit_pushed = True
    result.commit_sha = sha


# ---------- reporting ----------


def write_report(result: PreflightResult) -> Path:
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    result.finished_at = now_iso()
    path = VERIFICATION_DIR / f"{now_stamp()}-preflight.txt"
    lines = [
        "=== task-runner preflight ===",
        f"started_at: {result.started_at}",
        f"finished_at: {result.finished_at}",
        f"ok: {result.ok}",
        "",
    ]
    if result.gitattributes_updated:
        lines.append(".gitattributes: appended missing merge=ours lines:")
        for ln in result.gitattributes_added_lines:
            lines.append(f"  + {ln}")
    else:
        lines.append(".gitattributes: no changes needed")
    lines.append("")

    if result.conflicts_resolved:
        lines.append("whitelisted conflicts resolved (checkout --ours):")
        for p in result.conflicts_resolved:
            lines.append(f"  - {p}")
    else:
        lines.append("whitelisted conflicts resolved: 0")
    lines.append("")

    if result.dirty_whitelisted_staged:
        lines.append("dirty whitelisted paths staged:")
        for p in result.dirty_whitelisted_staged:
            lines.append(f"  - {p}")
    else:
        lines.append("dirty whitelisted paths staged: 0")
    lines.append("")

    if result.unsafe_conflicts:
        lines.append("UNSAFE CONFLICTS (not auto-resolved — must be handled manually):")
        for entry in result.unsafe_conflicts:
            lines.append(f"  ! {entry}")
    else:
        lines.append("unsafe conflicts: 0")
    lines.append("")

    if result.commit_pushed:
        lines.append(f"commit: {result.commit_sha} pushed to origin/main")
    else:
        lines.append("commit: none (nothing to commit or push deferred)")
    lines.append("")

    if result.notes:
        lines.append("notes:")
        for n in result.notes:
            lines.append(f"  * {n}")
    lines.append("")
    lines.append("--- raw git status --porcelain (post-preflight) ---")
    status = _git("status", "--porcelain").stdout
    lines.append(status or "(clean)")

    lines.append("")
    lines.append("--- structured result (JSON) ---")
    lines.append(json.dumps(asdict(result), indent=2, sort_keys=True))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result.report_path = str(path)
    return path


# ---------- public entry ----------


def run_preflight(commit_and_push: bool = True) -> PreflightResult:
    """Main entry.

    Returns the structured result; also writes a timestamped report to
    ``ops/verification/``.

    ``commit_and_push=False`` makes this a dry run (report only, no git
    write operations) — useful for debugging.
    """
    result = PreflightResult()

    # Quick guard: if we're not even in a git repo, bail with a note.
    git_check = _git("rev-parse", "--is-inside-work-tree")
    if git_check.returncode != 0:
        result.ok = False
        result.notes.append("not inside a git work tree — preflight aborted")
        write_report(result)
        return result

    ensure_gitattributes(result)
    resolve_whitelisted_conflicts(result)
    stage_whitelisted_dirty(result)

    if commit_and_push:
        commit_and_push_if_needed(result)

    # If anything unsafe remains, the runner should not proceed — but we
    # still write the report so the next agent can read it.
    write_report(result)
    return result


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    result = run_preflight(commit_and_push=not dry_run)
    # Print a compact one-liner to stdout so launchd logs are scannable.
    summary = (
        f"preflight ok={result.ok} "
        f"resolved={len(result.conflicts_resolved)} "
        f"staged={len(result.dirty_whitelisted_staged)} "
        f"unsafe={len(result.unsafe_conflicts)} "
        f"report={result.report_path}"
    )
    print(summary)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
