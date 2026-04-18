#!/usr/bin/env python3
"""
ops/task_audit_index.py — link a task to every artifact it touched.

Given a task id (or any substring), resolves the complete audit chain:

    1. The task JSON file (wherever it lives: pending/completed/failed/
       rejected/blocked under ``ops/work_queue`` or ``ops/workqueue``).
    2. The prompt file(s) referenced by ``payload.prompt_file`` or
       ``payload.prompt_files`` (for ``run_cline_prompt`` /
       ``run_cline_campaign`` tasks) and the ``prompt_files`` top-level
       field used by campaign descriptors.
    3. The verification artifact(s) produced by the runner, including the
       runner's ``<task_id>-result.txt`` plus launcher logs matching
       ``*-cline-run-<prompt-stem>*.log`` and
       ``*-cline-campaign*.log``.
    4. Relevant git commit hashes — commits that touched the task JSON,
       its prompt files, or its verification artifacts.

This is a superset of ``ops/task_audit.py`` (which does path-substring
matching across the verification + queue trees). ``task_audit_index.py``
actually loads the task JSON and follows its references to produce a
coherent "here is everything that went into this task" summary.

Usage::

    python3 ops/task_audit_index.py 20260417-143719-verify-task-runner
    python3 ops/task_audit_index.py verify-task-runner     # substring OK
    python3 ops/task_audit_index.py --json <query>         # machine output
    python3 ops/task_audit_index.py --out FILE <query>     # persist

Exit codes:
    0  task(s) matched
    1  nothing matched
    2  bad args
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_QUEUES = [REPO_ROOT / "ops" / "work_queue", REPO_ROOT / "ops" / "workqueue"]
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
QUEUE_STATES = ("pending", "completed", "failed", "rejected", "blocked")


# ---------- data model ----------


@dataclass
class TaskLocation:
    path: str
    state: str  # pending|completed|failed|rejected|blocked
    queue: str  # work_queue|workqueue
    task_id: str
    task_type: str
    created_by: str
    created_at: str
    requires_approval: bool
    approval_token: str
    dry_run: bool
    metadata_category: str
    metadata_notes: str


@dataclass
class ArtifactLink:
    path: str
    exists: bool
    kind: str  # task_json|prompt_file|verification|launcher_log|campaign_log
    size_bytes: int = 0
    mtime_iso: str = ""


@dataclass
class AuditChain:
    query: str
    task: TaskLocation
    artifacts: list[ArtifactLink] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------- helpers ----------


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _stat_art(path: Path, kind: str) -> ArtifactLink:
    exists = path.exists()
    size = 0
    mtime_iso = ""
    if exists:
        try:
            st = path.stat()
            size = st.st_size
            mtime_iso = datetime.fromtimestamp(st.st_mtime).isoformat(
                timespec="seconds"
            )
        except OSError:
            pass
    rel = str(path.relative_to(REPO_ROOT)) if path.is_absolute() else str(path)
    return ArtifactLink(
        path=rel,
        exists=exists,
        kind=kind,
        size_bytes=size,
        mtime_iso=mtime_iso,
    )


def _locate_tasks(query: str) -> list[TaskLocation]:
    """Return every task JSON whose filename contains ``query`` (case-insensitive).

    Scans both ``ops/work_queue`` and ``ops/workqueue`` across all known
    states.
    """
    q = query.lower()
    found: list[TaskLocation] = []
    for queue_root in WORK_QUEUES:
        if not queue_root.is_dir():
            continue
        queue_name = queue_root.name
        for state in QUEUE_STATES:
            d = queue_root / state
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.json")):
                if q and q not in p.name.lower():
                    continue
                data = _read_json(p)
                payload = data.get("payload") or {}
                metadata = data.get("metadata") or {}
                found.append(
                    TaskLocation(
                        path=str(p.relative_to(REPO_ROOT)),
                        state=state,
                        queue=queue_name,
                        task_id=data.get("task_id")
                        or data.get("id")
                        or p.stem,
                        task_type=data.get("task_type")
                        or data.get("type")
                        or "unknown",
                        created_by=data.get("created_by")
                        or data.get("initiator")
                        or "unknown",
                        created_at=data.get("created_at") or "",
                        requires_approval=bool(
                            data.get("requires_approval")
                            or payload.get("requires_approval")
                        ),
                        approval_token=str(
                            data.get("approval_token")
                            or payload.get("approval_token")
                            or ""
                        ),
                        dry_run=bool(
                            data.get("dry_run") or payload.get("dry_run")
                        ),
                        metadata_category=str(
                            metadata.get("category")
                            or payload.get("category")
                            or ""
                        ),
                        metadata_notes=str(
                            metadata.get("notes")
                            or payload.get("notes")
                            or ""
                        )[:400],
                    )
                )
    return found


def _prompt_paths_from_task(task_json: dict) -> list[str]:
    """Extract every prompt_file / prompt_files reference from a task JSON."""
    payload = task_json.get("payload") or {}
    out: list[str] = []
    # Signed-task schema.
    pf = payload.get("prompt_file")
    if isinstance(pf, str) and pf.strip():
        out.append(pf.strip())
    pfs = payload.get("prompt_files")
    if isinstance(pfs, list):
        out.extend(str(x).strip() for x in pfs if isinstance(x, str) and x.strip())
    # Campaign-descriptor schema (top-level prompt_files).
    top_pfs = task_json.get("prompt_files")
    if isinstance(top_pfs, list):
        out.extend(
            str(x).strip() for x in top_pfs if isinstance(x, str) and x.strip()
        )
    # Deduplicate while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _verification_for_task(task_id: str, prompt_paths: list[str]) -> list[Path]:
    """Find verification artifacts associated with a task id.

    Rules:
      * Exact runner result file: ``<task_id>-result.txt``.
      * Any file under ``ops/verification`` whose name contains the task id.
      * For each prompt file referenced, any
        ``*-cline-run-<prompt-stem>*.log`` under ``ops/verification``.
      * All ``*-cline-campaign*.log`` entries (campaign logs don't embed
        the task id; we include them so humans can correlate by mtime).
    """
    hits: list[Path] = []
    if not VERIFICATION_DIR.is_dir():
        return hits

    task_id_lower = task_id.lower()
    for entry in VERIFICATION_DIR.rglob("*"):
        if not entry.is_file():
            continue
        name_lower = entry.name.lower()
        if task_id_lower and task_id_lower in name_lower:
            hits.append(entry)
            continue
        for pp in prompt_paths:
            stem = Path(pp).stem.lower()
            # Match the sanitized stem used by the launcher.
            safe_stem = "".join(
                c if c.isalnum() or c in "._-" else "-" for c in stem
            )
            if (
                f"cline-run-{safe_stem}" in name_lower
                or f"cline-run-{stem}" in name_lower
            ):
                hits.append(entry)
                break
    # Deduplicate.
    seen_paths: set[Path] = set()
    dedup: list[Path] = []
    for h in hits:
        if h not in seen_paths:
            seen_paths.add(h)
            dedup.append(h)
    # Sort by mtime desc for stable output.
    dedup.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return dedup


def _git_commits_for_paths(paths: list[str], limit: int = 20) -> list[dict]:
    """Return the most recent commits that touched any of ``paths``.

    Uses ``git log --follow`` over the union of paths. Returns a list of
    dicts with ``hash``, ``short``, ``date``, ``subject``. Swallows errors
    and returns an empty list if git isn't available.
    """
    if not paths:
        return []
    try:
        # --- "-- path1 path2 ..." limits the log to commits touching those.
        argv = [
            "git",
            "-C",
            str(REPO_ROOT),
            "log",
            f"-n{limit}",
            "--pretty=format:%H%x09%h%x09%ad%x09%s",
            "--date=iso-strict",
            "--",
        ] + paths
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            return []
        out: list[dict] = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t", 3)
            if len(parts) < 4:
                continue
            out.append(
                {
                    "hash": parts[0],
                    "short": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


# ---------- chain construction ----------


def build_chain(task_loc: TaskLocation) -> AuditChain:
    task_path = REPO_ROOT / task_loc.path
    task_json = _read_json(task_path)
    chain = AuditChain(query=task_loc.task_id, task=task_loc)

    # Task JSON artifact.
    chain.artifacts.append(_stat_art(task_path, "task_json"))

    # Prompt files (exist-check).
    prompt_rels = _prompt_paths_from_task(task_json)
    for pr in prompt_rels:
        prompt_path = (REPO_ROOT / pr).resolve()
        # Guard against .. traversal.
        try:
            prompt_path.relative_to(REPO_ROOT.resolve())
        except ValueError:
            chain.notes.append(f"prompt path escapes repo root: {pr}")
            continue
        chain.artifacts.append(_stat_art(prompt_path, "prompt_file"))

    # Verification artifacts.
    verif_paths = _verification_for_task(task_loc.task_id, prompt_rels)
    for vp in verif_paths:
        kind = "verification"
        name = vp.name.lower()
        if "cline-run-" in name:
            kind = "launcher_log"
        elif "cline-campaign" in name:
            kind = "campaign_log"
        chain.artifacts.append(_stat_art(vp, kind))

    # Commits touching any of these paths.
    commit_targets = [a.path for a in chain.artifacts if a.exists]
    chain.commits = _git_commits_for_paths(commit_targets)

    if task_loc.requires_approval:
        if not task_loc.approval_token:
            chain.notes.append(
                "task declares requires_approval but has no approval_token"
            )
        else:
            chain.notes.append(
                f"approval_token present: {task_loc.approval_token}"
            )
    if task_loc.dry_run:
        chain.notes.append("task has dry_run=true — no write side-effects expected")

    return chain


# ---------- rendering ----------


def _render_text(chains: list[AuditChain]) -> str:
    lines: list[str] = []
    lines.append("=== task_audit_index ===")
    lines.append(f"chains: {len(chains)}")
    lines.append("")
    for chain in chains:
        t = chain.task
        lines.append(f"--- {t.task_id} ---")
        lines.append(f"  path:            {t.path}")
        lines.append(f"  queue/state:     {t.queue}/{t.state}")
        lines.append(f"  task_type:       {t.task_type}")
        lines.append(f"  created_by:      {t.created_by}")
        lines.append(f"  created_at:      {t.created_at}")
        if t.metadata_category:
            lines.append(f"  category:        {t.metadata_category}")
        if t.metadata_notes:
            lines.append(f"  notes:           {t.metadata_notes}")
        lines.append(f"  requires_approval: {t.requires_approval}")
        if t.approval_token:
            lines.append(f"  approval_token:  {t.approval_token}")
        lines.append(f"  dry_run:         {t.dry_run}")
        lines.append("")
        lines.append(f"  artifacts ({len(chain.artifacts)}):")
        for a in chain.artifacts:
            status = "OK " if a.exists else "MISS"
            lines.append(
                f"    [{status}] [{a.kind:<14}] {a.mtime_iso or '-':<25}  "
                f"{a.size_bytes:>8}B  {a.path}"
            )
        lines.append("")
        lines.append(f"  commits ({len(chain.commits)}):")
        if not chain.commits:
            lines.append("    (none / git unavailable)")
        for c in chain.commits:
            lines.append(
                f"    {c['short']}  {c['date']}  {c['subject']}"
            )
        if chain.notes:
            lines.append("")
            lines.append("  notes:")
            for n in chain.notes:
                lines.append(f"    * {n}")
        lines.append("")
    return "\n".join(lines)


def _render_json(chains: list[AuditChain]) -> str:
    return json.dumps(
        {"chains": [asdict(c) for c in chains]},
        indent=2,
        sort_keys=True,
    )


# ---------- entry point ----------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "query",
        help="task_id or substring (e.g. 'verify-task-runner', "
        "'20260417-143719')",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of text",
    )
    ap.add_argument(
        "--out",
        help="also write the rendered output to this path (repo-relative "
        "paths are resolved against the repo root)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=10,
        help="maximum number of matching task chains to render (default: 10)",
    )
    args = ap.parse_args(argv)

    if not args.query:
        print("error: query is required", file=sys.stderr)
        return 2

    locs = _locate_tasks(args.query)
    if not locs:
        print(f"no tasks matched query: {args.query}", file=sys.stderr)
        # Give the caller a clean empty render so pipelines can still capture
        # output without branching.
        empty = _render_json([]) if args.json else "=== task_audit_index ===\nchains: 0\n"
        print(empty)
        if args.out:
            out_path = Path(args.out)
            if not out_path.is_absolute():
                out_path = REPO_ROOT / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(empty + "\n", encoding="utf-8")
        return 1

    locs = locs[: args.limit]
    chains = [build_chain(loc) for loc in locs]
    rendered = _render_json(chains) if args.json else _render_text(chains)
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
