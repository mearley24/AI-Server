"""Offline / manual backlog import for x-intake.

Problem this solves
-------------------
When the x-intake service is down (Docker not running, listener crashed,
X/Twitter API quota expired, etc.) every tweet URL that hits the iMessage
bridge is effectively lost — there is no durable capture ahead of the live
pipeline. This module provides a side path that can preserve the raw URL
(and an optional human-written gist) directly into the queue DB so the item
is not dropped on the floor.

Two surfaces:

* CLI — `python manual_import.py --urls-file backlog.txt`
  (usable from the repo host before Docker is back up, as long as
   ``X_INTAKE_DB_PATH`` points at ``./data/x_intake/queue.db``)

* HTTP — ``POST /import`` on the running service, which calls the same
  ``import_url()`` helper.

Design goals:
* No live X/Twitter API call required — the raw URL + an optional gist
  are enough to remember the item for later enrichment.
* Idempotent: re-running with the same URLs never creates duplicates
  (dedup key is the canonical ``https://x.com/<handle>/status/<id>`` form).
* Status is recorded as ``pending`` so items surface in the review
  dashboard and can be replayed by the normal pipeline after recovery.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

try:
    from queue_db import (
        canonical_url,
        enqueue as _db_enqueue,
        extract_tweet_id,
        find_by_url,
    )
except ImportError:  # when imported as integrations.x_intake.manual_import
    from .queue_db import (  # type: ignore[no-redef]
        canonical_url,
        enqueue as _db_enqueue,
        extract_tweet_id,
        find_by_url,
    )


@dataclass
class ImportResult:
    """Outcome of importing a single URL."""

    url: str
    canonical: str
    row_id: int
    status: str  # "inserted" | "already_present" | "skipped"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "canonical_url": self.canonical,
            "row_id": self.row_id,
            "status": self.status,
            "reason": self.reason,
        }


def _author_from_url(url: str) -> str:
    """Best-effort handle extraction so a row has a non-empty author."""
    canon = canonical_url(url)
    # canon is https://x.com/<handle>/status/<id>
    parts = canon.split("/")
    if len(parts) >= 5 and parts[2] == "x.com":
        return parts[3]
    return ""


def import_url(
    url: str,
    note: str = "",
    source: str = "manual",
    relevance: int = 30,
) -> ImportResult:
    """Enqueue a single URL with an optional human-written gist.

    The row is created with status ``pending`` (relevance=30 by default) so
    it is visible in the review queue. Rerunning with the same URL returns
    ``already_present`` without creating a duplicate row.
    """
    url = (url or "").strip()
    if not url:
        return ImportResult(url="", canonical="", row_id=0, status="skipped", reason="empty url")

    if not extract_tweet_id(url):
        return ImportResult(
            url=url,
            canonical=canonical_url(url),
            row_id=0,
            status="skipped",
            reason="not a tweet url",
        )

    existing = find_by_url(url)
    if existing is not None:
        return ImportResult(
            url=url,
            canonical=canonical_url(url),
            row_id=int(existing.get("id", 0)),
            status="already_present",
        )

    summary = note.strip() or f"[manual import] {url}"
    row_id = _db_enqueue(
        url=url,
        author=_author_from_url(url),
        post_type="info",
        relevance=relevance,
        summary=summary,
        action="none",
        source=source,
        poly_signals={},
        has_transcript=False,
        transcript_path="",
    )
    if not row_id:
        return ImportResult(
            url=url,
            canonical=canonical_url(url),
            row_id=0,
            status="skipped",
            reason="db write failed",
        )
    return ImportResult(
        url=url,
        canonical=canonical_url(url),
        row_id=row_id,
        status="inserted",
    )


def import_many(
    urls: Iterable[str],
    notes: Optional[dict[str, str]] = None,
    source: str = "manual",
) -> list[ImportResult]:
    """Import a batch of URLs. ``notes`` maps url -> human-written gist."""
    notes = notes or {}
    results: list[ImportResult] = []
    for u in urls:
        u = u.strip()
        if not u or u.startswith("#"):
            continue
        results.append(import_url(u, note=notes.get(u, ""), source=source))
    return results


def _read_urls_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="x_intake.manual_import",
        description=(
            "Enqueue X/Twitter URLs into the x-intake review queue without "
            "calling any live X API. Idempotent: re-running is safe."
        ),
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        help="Path to a newline-separated list of X URLs (lines starting with # are ignored).",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="A single URL to enqueue. May be given multiple times.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional human-written gist applied to every URL in this run.",
    )
    parser.add_argument(
        "--source",
        default="manual",
        help="source tag to store on the queue row (default: manual).",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        help="Override the queue DB path (default: $X_INTAKE_DB_PATH or /data/x_intake/queue.db).",
    )
    args = parser.parse_args(argv)

    if args.db_path:
        os.environ["X_INTAKE_DB_PATH"] = str(args.db_path)
        # Reload module-level DB_PATH by reimporting queue_db on next call.
        import importlib

        import queue_db as _qdb  # type: ignore[import-not-found]

        importlib.reload(_qdb)

    urls: list[str] = list(args.url)
    if args.urls_file:
        if not args.urls_file.exists():
            print(f"error: {args.urls_file} not found", file=sys.stderr)
            return 2
        urls.extend(_read_urls_file(args.urls_file))

    if not urls:
        parser.print_help(sys.stderr)
        return 2

    notes = {u: args.note for u in urls} if args.note else {}
    results = import_many(urls, notes=notes, source=args.source)

    inserted = sum(1 for r in results if r.status == "inserted")
    existing = sum(1 for r in results if r.status == "already_present")
    skipped = sum(1 for r in results if r.status == "skipped")
    for r in results:
        print(f"  [{r.status:16s}] id={r.row_id:<6d} {r.url}  {r.reason}".rstrip())
    print(
        f"\nimport summary: inserted={inserted} already_present={existing} skipped={skipped}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.path.insert(0, os.path.dirname(__file__))
    raise SystemExit(_main(sys.argv[1:]))
