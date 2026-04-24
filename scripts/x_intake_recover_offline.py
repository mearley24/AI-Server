#!/usr/bin/env python3
"""Recover the X/Twitter links Matt sent while Docker/x-intake was down.

Usage (from repo root)::

    python3 scripts/x_intake_recover_offline.py
    # or against a specific DB path:
    X_INTAKE_DB_PATH=./data/x_intake/queue.db \
        python3 scripts/x_intake_recover_offline.py

This is safe to run multiple times — the queue is deduped by canonical
tweet URL, so re-runs will report ``already_present`` instead of creating
duplicate rows. No X/Twitter API key, Redis, or Docker is required.

After running, the four items will surface in the review dashboard with
status ``pending``. Once the pipeline is back up, you can either:

  * Let the human reviewer approve/reject them from the dashboard, or
  * Fire ``POST /analyze`` for each URL from the x-intake container to
    re-enrich with LLM analysis and transcripts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "integrations" / "x_intake"))

# Default to the host-mounted path used by the x-intake container so that
# host-side recovery writes land on the same DB the container reads. The
# user can still override with X_INTAKE_DB_PATH before invoking.
os.environ.setdefault("X_INTAKE_DB_PATH", str(ROOT / "data" / "x_intake" / "queue.db"))

from manual_import import import_many  # noqa: E402


# Known backlog — the four links sent while Docker was down, plus the
# search-visible gist for each so the row is meaningful even before the
# live pipeline re-enriches it.
BACKLOG: list[tuple[str, str]] = [
    (
        "https://x.com/openswarm_/status/2047034226806292493?s=42",
        "Open Swarm (@OpenSwarm_): Introducing Open Swarm One Canvas — an army "
        "of AI agents. Be the boss. (t.co/cwiYsfEkKn)",
    ),
    (
        "https://x.com/nousresearch/status/2047495677651918885?s=42",
        "Nous Research (@NousResearch): Hermes Agent v0.11.0 — The Interface "
        "Release. Full changelog in thread.",
    ),
    (
        "https://x.com/jameszmsun/status/2047522852854026378?s=42",
        "James Sun (@JamesZmSun): Launched browser use inside Codex to further "
        "close the build & verify loop.",
    ),
    (
        "https://x.com/datachaz/status/2047245316391670042?s=42",
        "Charly Wargnier (@DataChaz): Commentary on Google's competitive "
        "posture re: Anthropic.",
    ),
]


def main() -> int:
    urls = [u for (u, _) in BACKLOG]
    notes = {u: note for (u, note) in BACKLOG}
    results = import_many(urls, notes=notes, source="offline_recovery")

    print("x-intake offline recovery")
    print("-" * 60)
    for r in results:
        print(f"  [{r.status:16s}] id={r.row_id:<6d} {r.url}")
        if r.reason:
            print(f"    └── {r.reason}")
    inserted = sum(1 for r in results if r.status == "inserted")
    existing = sum(1 for r in results if r.status == "already_present")
    skipped = sum(1 for r in results if r.status == "skipped")
    print("-" * 60)
    print(
        f"inserted={inserted}  already_present={existing}  skipped={skipped}"
    )
    print(
        "\nNext step: once x-intake is up, confirm in the dashboard or run\n"
        "  curl -s http://127.0.0.1:8101/queue?status=pending | jq\n"
        "to see the recovered items."
    )
    return 0 if (inserted + existing) == len(BACKLOG) else 1


if __name__ == "__main__":
    raise SystemExit(main())
