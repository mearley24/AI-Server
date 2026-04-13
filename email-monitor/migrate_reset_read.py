#!/usr/bin/env python3
"""
migrate_reset_read.py — One-time migration to fix the read=1 upstream bug.

Background
----------
All emails in emails.db were incorrectly marked read=1 because notifier.py
called mark_email_read() whenever a notification was dispatched.  That logic
was wrong: receiving a notification is not the same as Matt replying.

Correct rule (post-fix)
-----------------------
  read=1  iff  responded=1
  (i.e., _scan_sent_for_replies() found a Sent-folder message whose
   In-Reply-To header matches the tracked message_id)

What this script does
---------------------
  UPDATE emails SET read = 0 WHERE responded = 0 AND read = 1

This is safe to run multiple times (idempotent).  Emails where
responded=1 are left untouched — those were set correctly.

Usage
-----
  python3 email-monitor/migrate_reset_read.py [--db /path/to/emails.db] [--dry-run]
"""

import argparse
import sqlite3
import os
import sys


DEFAULT_DB = os.getenv("EMAIL_DB_PATH", "/data/emails.db")


def run_migration(db_path: str, dry_run: bool = False) -> None:
    if not os.path.exists(db_path):
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    # Count rows that will be affected
    count_row = conn.execute(
        "SELECT COUNT(*) FROM emails WHERE responded = 0 AND read = 1"
    ).fetchone()
    affected = count_row[0] if count_row else 0

    total_row = conn.execute("SELECT COUNT(*) FROM emails").fetchone()
    total = total_row[0] if total_row else 0

    responded_row = conn.execute(
        "SELECT COUNT(*) FROM emails WHERE responded = 1"
    ).fetchone()
    responded = responded_row[0] if responded_row else 0

    print(f"Database : {db_path}")
    print(f"Total emails      : {total}")
    print(f"responded=1       : {responded}  (will keep read=1)")
    print(f"responded=0,read=1: {affected}  (will reset to read=0)")

    if dry_run:
        print("DRY RUN — no changes written.")
        conn.close()
        return

    if affected == 0:
        print("Nothing to fix — all clean.")
        conn.close()
        return

    conn.execute(
        "UPDATE emails SET read = 0 WHERE responded = 0 AND read = 1"
    )
    conn.commit()

    # Verify
    remaining = conn.execute(
        "SELECT COUNT(*) FROM emails WHERE responded = 0 AND read = 1"
    ).fetchone()[0]
    conn.close()

    print(f"Fixed {affected} row(s).  Remaining bad rows: {remaining}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset incorrectly-set read=1 flags in emails.db")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to emails.db")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    run_migration(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
