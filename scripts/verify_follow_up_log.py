"""One-shot verification script: run inside the openclaw container to confirm
the ``follow_up_engine._record_sent`` path writes a row to
``/data/follow_ups.db:follow_up_log``.

Usage (inside container):
    docker exec openclaw python3 /app/../scripts/verify_follow_up_log.py

This is read-only against live data: it only inserts a synthetic row with
``job_id=999999`` and ``interval_days=3`` that close-yellow-gaps.txt
documents. Re-running is idempotent (INSERT OR REPLACE on (job_id,
interval_days)).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from follow_up_engine import FollowUpEngine  # noqa: E402  (sys.path setup)


def main() -> None:
    jobs_db = "/data/jobs.db"
    emails_db = "/data/emails.db"
    follow_ups_db = "/data/follow_ups.db"

    # Sanity check: confirm follow_ups.db exists before writing.
    if not Path(follow_ups_db).exists():
        print(f"ERR: {follow_ups_db} missing", file=sys.stderr)
        sys.exit(2)

    engine = FollowUpEngine(
        jobs_db=jobs_db,
        emails_db=emails_db,
        follow_ups_db=follow_ups_db,
    )
    engine._record_sent(  # type: ignore[attr-defined]
        job_id=999999,
        interval_days=3,
        email_id="close-yellow-gaps-verify",
        template="verify_only",
    )

    conn = sqlite3.connect(follow_ups_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, job_id, interval_days, sent_at, email_id, template "
        "FROM follow_up_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) AS n FROM follow_up_log").fetchone()["n"]
    conn.close()

    if row is None:
        print("FAIL: follow_up_log has no rows after insert")
        sys.exit(1)

    print(
        "OK follow_up_log row: "
        f"id={row['id']} job_id={row['job_id']} "
        f"interval_days={row['interval_days']} "
        f"sent_at={row['sent_at']} email_id={row['email_id']}"
    )
    print(f"OK follow_up_log total rows = {count}")


if __name__ == "__main__":
    main()
