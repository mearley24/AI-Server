#!/usr/bin/env python3
"""
Interactive CLI for reviewing detected work threads from the client intel backfill.

Usage:
    python3 scripts/review_client_threads.py
    python3 scripts/review_client_threads.py --limit 10
    python3 scripts/review_client_threads.py --min-confidence 0.7
    python3 scripts/review_client_threads.py --summary

Contacts are shown masked (first 3 chars + *** + last 2 chars).
No personal information is displayed.
All approvals are explicit — nothing is auto-approved.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"

# Review state values
PENDING  = -1
REJECTED =  0
APPROVED =  1

STATUS_LABEL = {PENDING: "pending", REJECTED: "rejected", APPROVED: "approved"}
STATUS_ICON  = {PENDING: "⬜", REJECTED: "✗", APPROVED: "✓"}


def _mask(handle: str) -> str:
    return handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"


def _open_db() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        print(f"\n[error] Thread index not found: {DB_PATH}")
        print("Run first:  python3 scripts/client_intel_backfill.py --dry-run --limit 100")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def print_summary(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT category, is_reviewed, COUNT(*) as n FROM threads GROUP BY category, is_reviewed"
    ).fetchall()
    print("\n=== Client Thread Review Summary ===")
    cats: dict[str, dict[str, int]] = {}
    for r in rows:
        cats.setdefault(r["category"], {})[STATUS_LABEL[r["is_reviewed"]]] = r["n"]
    for cat, statuses in sorted(cats.items()):
        total = sum(statuses.values())
        parts = "  ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
        print(f"  {cat:10s}  total={total:3d}  {parts}")
    pending = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE category='work' AND is_reviewed=-1"
    ).fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE is_reviewed=1"
    ).fetchone()[0]
    print(f"\n  Pending work review : {pending}")
    print(f"  Approved total      : {approved}")
    print()


def set_reviewed(conn: sqlite3.Connection, thread_id: str, status: int) -> None:
    conn.execute("UPDATE threads SET is_reviewed=? WHERE thread_id=?", (status, thread_id))
    conn.commit()


def run_review(
    conn: sqlite3.Connection,
    limit: int = 50,
    min_confidence: float = 0.5,
    category: str = "work",
) -> None:
    rows = conn.execute(
        "SELECT thread_id, contact_handle, message_count, date_first, date_last, "
        "category, work_confidence, reason_codes, is_reviewed "
        "FROM threads "
        "WHERE is_reviewed = ? AND category = ? AND work_confidence >= ? "
        "ORDER BY work_confidence DESC, date_last DESC "
        "LIMIT ?",
        (PENDING, category, min_confidence, limit),
    ).fetchall()

    if not rows:
        print(f"\n✓ No pending {category} threads to review (confidence ≥ {min_confidence}).")
        return

    print(f"\n=== Review {len(rows)} pending {category} threads ===")
    print("  [y] approve  [n] reject  [s] skip  [q] quit\n")

    approved_count = rejected_count = skipped_count = 0

    for i, r in enumerate(rows, 1):
        masked = _mask(r["contact_handle"])
        codes = json.loads(r["reason_codes"] or "[]")
        codes_str = ", ".join(codes[:3]) if codes else "(none)"
        date_range = f"{(r['date_first'] or '')[:10]} → {(r['date_last'] or '')[:10]}"

        print(f"[{i}/{len(rows)}] {masked}")
        print(f"       msgs={r['message_count']}  conf={r['work_confidence']:.2f}  {date_range}")
        print(f"       signals: {codes_str}")

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                _print_session_summary(approved_count, rejected_count, skipped_count)
                return

            if choice in ("y", "yes"):
                set_reviewed(conn, r["thread_id"], APPROVED)
                print(f"       ✓ Approved — eligible for profile extraction.\n")
                approved_count += 1
                break
            elif choice in ("n", "no"):
                set_reviewed(conn, r["thread_id"], REJECTED)
                print(f"       ✗ Rejected — excluded from future processing.\n")
                rejected_count += 1
                break
            elif choice in ("s", "skip", ""):
                print(f"       ⬜ Skipped.\n")
                skipped_count += 1
                break
            elif choice in ("q", "quit", "exit"):
                _print_session_summary(approved_count, rejected_count, skipped_count)
                return
            else:
                print("       ? Enter y / n / s / q")

    _print_session_summary(approved_count, rejected_count, skipped_count)


def _print_session_summary(approved: int, rejected: int, skipped: int) -> None:
    total = approved + rejected + skipped
    print(f"Session: reviewed {total}  →  approved={approved}  rejected={rejected}  skipped={skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive client thread review")
    parser.add_argument("--limit", type=int, default=50, help="Max threads to review")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                        help="Minimum work_confidence to show")
    parser.add_argument("--category", default="work",
                        help="Category to review (default: work)")
    parser.add_argument("--summary", action="store_true",
                        help="Show summary only, do not enter review loop")
    args = parser.parse_args()

    conn = _open_db()
    try:
        print_summary(conn)
        if not args.summary:
            run_review(conn, limit=args.limit,
                       min_confidence=args.min_confidence,
                       category=args.category)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
