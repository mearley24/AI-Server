#!/usr/bin/env python3
"""x_intake_recent.py — Bounded, read-only snapshot of the X-intake lane.

Reads the intake queue from the x-intake service and prints the N most
recent items with status, relevance, author, and URL. Useful to confirm
whether X links sent through iMessage are actually being analyzed.

Examples:
    python3 ops/tools/x_intake_recent.py              # last 10 items
    python3 ops/tools/x_intake_recent.py --limit 25   # last 25
    python3 ops/tools/x_intake_recent.py --status pending
    python3 ops/tools/x_intake_recent.py --json       # JSON output

Source of truth: x-intake's own queue SQLite (via the HTTP API). No
direct DB access is used, so this tool is safe across host/container
rebuilds and never mutates state.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8101"
TIMEOUT = 6


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Recent x-intake queue items")
    p.add_argument("--base", default=DEFAULT_URL, help="x-intake base URL")
    p.add_argument("--limit", type=int, default=10, help="max rows to show")
    p.add_argument("--status", default="", help="filter: pending/approved/rejected/...")
    p.add_argument("--json", action="store_true", help="emit raw JSON")
    args = p.parse_args()

    # 1. Health probe. If the endpoint isn't up, fail loudly.
    try:
        _get_json(f"{args.base}/health")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"ERROR: x-intake /health unreachable: {exc}", file=sys.stderr)
        return 2

    # 2. Queue stats summary
    try:
        stats = _get_json(f"{args.base}/queue/stats")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: /queue/stats failed: {exc}", file=sys.stderr)
        return 3

    # 3. Recent items
    qs = urllib.parse.urlencode({"status": args.status, "limit": max(1, min(200, args.limit))})
    try:
        payload = _get_json(f"{args.base}/queue?{qs}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: /queue failed: {exc}", file=sys.stderr)
        return 4

    items = payload.get("items", [])

    if args.json:
        print(json.dumps({"stats": stats, "items": items}, indent=2, default=str))
        return 0

    total = stats.get("total", "?")
    pending = stats.get("pending", "?")
    print(f"X-intake queue — total={total}  pending={pending}")
    print(f"Showing last {len(items)} rows"
          + (f" with status={args.status}" if args.status else ""))
    print("-" * 80)

    for row in items:
        rid = row.get("id", "?")
        status = row.get("status", "?")
        rel = row.get("relevance", "?")
        author = (row.get("author") or "")[:24]
        ts = row.get("created_at") or row.get("ts") or ""
        url = (row.get("url") or "")[:72]
        print(f"#{rid:>4} [{status:<15}] rel={str(rel):>3}% @{author:<24} {ts}")
        print(f"      {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
