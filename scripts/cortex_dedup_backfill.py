#!/usr/bin/env python3
"""One-shot backfill: compute dedupe_key for historical memory rows and collapse duplicates.

Usage:
    python3 scripts/cortex_dedup_backfill.py [--db PATH] [--dry-run] [--apply]

Defaults to --dry-run. Pass --apply to write changes.
The script always prints the backup command; it does NOT run it.

Exit codes:
    0   success / nothing to do
    1   argument error
    2   DB busy (another process holds a write lock)
    3   unexpected error
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.memory import MemoryStore


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _resolve_db(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg)
    try:
        from cortex.config import DB_PATH
        return DB_PATH
    except Exception:
        return REPO_ROOT / "data" / "cortex" / "brain.db"


def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=2.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            print(f"ERROR: DB is locked by another process: {exc}", file=sys.stderr)
            sys.exit(2)
    return conn


def _compute_keys(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Return {derived_key: [row, ...]} for all rows without an existing dedupe_key."""
    rows = conn.execute(
        "SELECT id, category, source, subcategory, title, content,"
        " importance, access_count, tags, metadata, created_at"
        " FROM memories WHERE dedupe_key IS NULL"
    ).fetchall()

    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = MemoryStore._canonical_key(
            category=row["category"] or "",
            source=row["source"] or "",
            subcategory=row["subcategory"] or "",
            dedupe_hint="",
        )
        if key is None:
            continue
        groups.setdefault(key, []).append(dict(row))

    # Only keep groups with 2+ rows (actual duplicates)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def _merge_group(rows: list[dict]) -> dict:
    """Merge a duplicate group, keeping the oldest row as canonical."""
    rows_sorted = sorted(rows, key=lambda r: r["created_at"])
    canonical = dict(rows_sorted[0])
    for dup in rows_sorted[1:]:
        canonical["importance"] = max(canonical["importance"] or 0, dup["importance"] or 0)
        canonical["access_count"] = (canonical["access_count"] or 0) + (dup["access_count"] or 0)
        old_tags: list = json.loads(canonical["tags"] or "[]")
        new_tags: list = json.loads(dup["tags"] or "[]")
        canonical["tags"] = json.dumps(list(dict.fromkeys(old_tags + new_tags)))
        old_meta: dict = json.loads(canonical["metadata"] or "{}")
        new_meta: dict = json.loads(dup["metadata"] or "{}")
        canonical["metadata"] = json.dumps({**old_meta, **new_meta})
    return canonical


def run(db_path: Path, dry_run: bool) -> dict:
    stamp = _now_stamp()
    backup_cmd = f"cp {db_path} {db_path}.bak.{stamp}"
    print(f"\nBackup command (run manually before --apply):")
    print(f"  {backup_cmd}\n")

    conn = _open_db(db_path)

    groups = _compute_keys(conn)
    total_dups = sum(len(v) - 1 for v in groups.values())

    if not groups:
        print("No duplicate groups found. Nothing to do.")
        conn.close()
        return {"groups": 0, "duplicates_found": 0, "rows_deleted": 0, "dry_run": dry_run}

    print(f"Found {len(groups)} duplicate group(s), {total_dups} redundant row(s).")

    for i, (key, rows) in enumerate(sorted(groups.items()), 1):
        canonical = _merge_group(rows)
        dup_ids = [r["id"] for r in rows if r["id"] != canonical["id"]]
        print(f"\nGroup {i}: key={key[:16]}…")
        print(f"  Keep:   {canonical['id']}  ({canonical['created_at']}) — {canonical['title'][:60]!r}")
        for d in dup_ids:
            row = next(r for r in rows if r["id"] == d)
            print(f"  Delete: {d}  ({row['created_at']}) — {row['title'][:60]!r}")

    if dry_run:
        print(f"\nDRY RUN complete. Pass --apply to merge {total_dups} duplicate(s).")
        conn.close()
        return {"groups": len(groups), "duplicates_found": total_dups,
                "rows_deleted": 0, "dry_run": True}

    # Live apply
    now = datetime.now(timezone.utc).isoformat()
    rows_deleted = 0
    keys_set = 0

    conn.execute("BEGIN")
    try:
        for key, rows in groups.items():
            canonical = _merge_group(rows)
            dup_ids = [r["id"] for r in rows if r["id"] != canonical["id"]]

            # Update canonical row
            conn.execute(
                """UPDATE memories SET
                   importance = ?, access_count = ?, tags = ?, metadata = ?,
                   dedupe_key = ?, updated_at = ?
                   WHERE id = ?""",
                (canonical["importance"], canonical["access_count"],
                 canonical["tags"], canonical["metadata"],
                 key, now, canonical["id"]),
            )
            keys_set += 1

            # Delete duplicates
            for dup_id in dup_ids:
                conn.execute("DELETE FROM memories WHERE id = ?", (dup_id,))
                rows_deleted += 1

        conn.commit()
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise

    # Write verification JSON
    verif_dir = REPO_ROOT / "ops" / "verification"
    verif_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "timestamp": now, "db": str(db_path),
        "groups": len(groups), "duplicates_found": total_dups,
        "rows_deleted": rows_deleted, "keys_set": keys_set,
        "dry_run": False,
    }
    verif_path = verif_dir / f"{stamp}-cortex-dedup-backfill.json"
    verif_path.write_text(json.dumps(summary, indent=2))
    print(f"\nApplied: deleted {rows_deleted} duplicate(s) across {len(groups)} group(s).")
    print(f"Summary written to: {verif_path}")

    conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Cortex dedupe key backfill")
    parser.add_argument("--db", default=None, help="Path to brain.db (default: cortex.config.DB_PATH)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Print plan, no writes (default)")
    parser.add_argument("--apply", action="store_true", default=False, help="Write changes (requires backup first)")
    args = parser.parse_args()

    dry_run = not args.apply
    db_path = _resolve_db(args.db)

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        print("Pass --db /path/to/brain.db or set CORTEX_DATA_DIR.", file=sys.stderr)
        return 1

    try:
        run(db_path, dry_run=dry_run)
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
