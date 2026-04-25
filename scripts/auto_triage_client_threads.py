#!/usr/bin/env python3
"""
Auto-triage pending client intelligence threads.

Classifies is_reviewed=-1 threads into triage buckets without changing
is_reviewed or creating profiles. Human approval is still required before
any thread becomes an approved profile source.

Usage:
    python3 scripts/auto_triage_client_threads.py                   # dry-run, live chat.db
    python3 scripts/auto_triage_client_threads.py --apply
    python3 scripts/auto_triage_client_threads.py --summary
    python3 scripts/auto_triage_client_threads.py --bucket high_value
    python3 scripts/auto_triage_client_threads.py --limit 500 --verbose
    python3 scripts/auto_triage_client_threads.py --chat-db data/client_intel/chatdb_snapshot/chat.db --apply

Triage buckets:
    high_value       Named contacts or strong smart_home signals
    ambiguous        GC suffix, restaurant_work, builder, mixed signals
    low_priority     Unnamed + weak/no tech signals, few messages
    hidden_personal  category == personal

Safety rules enforced:
    - is_reviewed is NEVER modified
    - No profiles are auto-created or auto-approved
    - No messages are sent
    - Phone numbers are masked in all output / logs
    - Personal threads are isolated (hidden_personal bucket only)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.review_client_threads as _rct

DB_PATH = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"

TRIAGE_BUCKETS = frozenset({"high_value", "ambiguous", "low_priority", "hidden_personal"})

_TRIAGE_COLS = [
    ("triage_bucket",                "TEXT"),
    ("triage_reason",                "TEXT"),
    ("triage_confidence",            "REAL"),
    ("triage_suggested_relationship","TEXT"),
    ("triage_inferred_domain",       "TEXT"),
    ("triage_risk_flags",            "TEXT DEFAULT '[]'"),
    ("triage_contact_display",       "TEXT"),
    ("triaged_at",                   "TEXT"),
]


# ── Schema migration (idempotent) ─────────────────────────────────────────────

def _ensure_triage_columns(conn: sqlite3.Connection) -> None:
    """Add triage columns to threads table if not already present."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
    for col, dtype in _TRIAGE_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE threads ADD COLUMN {col} {dtype}")
    conn.commit()


# ── Bucket determination (pure, no I/O) ──────────────────────────────────────

def _determine_triage_bucket(
    category: str,
    work_confidence: float,
    message_count: int,
    date_last: str,
    name: str,
    assist: dict[str, Any],
) -> tuple[str, str, float]:
    """Return (bucket, reason, triage_confidence).

    Priority waterfall:
      hidden_personal → high_value → ambiguous → low_priority → ambiguous (default).
    Pure function — never touches the database or makes network calls.
    """
    risk_flags  = assist.get("risk_flags", [])
    assist_conf = assist.get("confidence", 0.0)
    domain      = assist.get("inferred_domain", "smart_home_work")

    # 1. Personal threads always hidden
    if category == "personal":
        return (
            "hidden_personal",
            "personal category — excluded from client profiles",
            0.95,
        )

    # 2. GC suffix always needs human disambiguation
    if "gc_suffix_ambiguous" in risk_flags:
        return (
            "ambiguous",
            "GC suffix — may be Game Creek (venue) or General Contractor; manual review required",
            0.80,
        )

    # 3. Named contact with strong signals
    if name:
        if assist_conf >= 0.65:
            return (
                "high_value",
                f"named contact with strong {domain} signals (confidence={assist_conf:.0%})",
                assist_conf,
            )
        if work_confidence >= 0.80:
            return (
                "high_value",
                f"named contact with high classifier confidence ({work_confidence:.0%})",
                work_confidence,
            )
        if message_count >= 20 and assist_conf >= 0.45:
            return (
                "high_value",
                f"named contact with {message_count} messages and moderate signals",
                max(assist_conf, 0.55),
            )

    # 4. Very strong signals regardless of name
    if assist_conf >= 0.80:
        return (
            "high_value",
            f"strong {domain} signals (confidence={assist_conf:.0%})",
            assist_conf,
        )

    # 5. Restaurant domain — ambiguous (AV client or venue?)
    if domain == "restaurant_work":
        return (
            "ambiguous",
            "restaurant_work signals — verify if AV client or venue contact",
            0.65,
        )

    # 6. Builder coordination — ambiguous (builder or client?)
    if domain == "builder_coordination":
        return (
            "ambiguous",
            "builder coordination signals — verify builder vs client role",
            0.60,
        )

    # 7. Mixed work/personal category
    if category == "mixed":
        return (
            "ambiguous",
            "mixed work/personal signals — manual review needed",
            0.65,
        )

    # 8. Old thread with any signals — may be stale relationship
    try:
        year = int((date_last or "")[:4])
        if year < 2022 and assist_conf >= 0.30:
            dl = (date_last or "")[:10]
            return (
                "ambiguous",
                f"older thread (last: {dl}) with work signals — may be stale relationship",
                0.55,
            )
    except (ValueError, TypeError):
        pass

    # 9. Large thread with uncertain classification
    if message_count >= 50 and assist_conf < 0.50:
        return (
            "ambiguous",
            f"large thread ({message_count} msgs) with uncertain classification",
            0.60,
        )

    # 10. Unnamed with weak signals
    if not name:
        if assist_conf < 0.40:
            return (
                "low_priority",
                f"unnamed contact with low classification confidence ({assist_conf:.0%})",
                0.80,
            )
        if message_count < 5:
            return (
                "low_priority",
                f"unnamed contact with few messages ({message_count}) — likely one-off",
                0.75,
            )
        if work_confidence < 0.55:
            return (
                "low_priority",
                f"unnamed contact below work confidence threshold ({work_confidence:.0%})",
                0.70,
            )

    # 11. Unknown category
    if category == "unknown":
        return (
            "low_priority",
            "unknown category — insufficient signals for classification",
            0.75,
        )

    # 12. Default fallback
    return (
        "ambiguous",
        "signals present but insufficient for automatic classification",
        0.45,
    )


# ── Triage runner ─────────────────────────────────────────────────────────────

def run_triage(
    conn: sqlite3.Connection,
    limit: int = 500,
    dry_run: bool = True,
    bucket_filter: "str | None" = None,
    chat_db_path: "Path | None" = None,
) -> dict[str, Any]:
    """Classify pending threads into triage buckets.

    Only processes is_reviewed=-1 threads.
    is_reviewed is never modified.
    Returns {dry_run, processed, counts, results}.

    chat_db_path — when provided, read message texts from this SQLite file
    instead of the live ~/Library/Messages/chat.db. Useful when Messages.app
    holds a write lock on the live DB. WAL/SHM files alongside the snapshot
    are handled transparently by SQLite.
    """
    _ensure_triage_columns(conn)

    # Temporarily redirect _fetch_sample_texts to the snapshot if provided.
    _orig_chat_db = _rct.CHAT_DB
    if chat_db_path is not None:
        _rct.CHAT_DB = Path(chat_db_path)

    rows = conn.execute(
        "SELECT thread_id, chat_guid, contact_handle, message_count, "
        "date_first, date_last, category, work_confidence, reason_codes "
        "FROM threads WHERE is_reviewed = -1 "
        "ORDER BY work_confidence DESC, message_count DESC "
        "LIMIT ?",
        (limit,),
    ).fetchall()

    now_iso = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {b: 0 for b in TRIAGE_BUCKETS}
    results: list[dict[str, Any]] = []

    try:
        for r in rows:
            handle = r["contact_handle"]
            name   = _rct._lookup_contact_name(handle)
            codes  = json.loads(r["reason_codes"] or "[]")
            texts  = _rct._fetch_sample_texts(r["chat_guid"])
            assist = _rct.analyze_thread_assist(name, texts, codes)

            bucket, reason, triage_conf = _determine_triage_bucket(
                category        = r["category"],
                work_confidence = r["work_confidence"],
                message_count   = r["message_count"],
                date_last       = r["date_last"] or "",
                name            = name,
                assist          = assist,
            )

            if bucket_filter and bucket != bucket_filter:
                continue

            counts[bucket] += 1
            contact_display = name if name else _rct._mask(handle)
            entry: dict[str, Any] = {
                "thread_id":                     r["thread_id"],
                "contact_masked":                _rct._mask(handle),
                "triage_bucket":                 bucket,
                "triage_reason":                 reason,
                "triage_confidence":             round(triage_conf, 3),
                "triage_suggested_relationship": assist["suggested_relationship_type"],
                "triage_inferred_domain":        assist["inferred_domain"],
                "triage_risk_flags":             json.dumps(assist["risk_flags"]),
                "triage_contact_display":        contact_display,
                "triaged_at":                    now_iso,
            }
            results.append(entry)

            if not dry_run:
                conn.execute(
                    "UPDATE threads SET "
                    "triage_bucket=?, triage_reason=?, triage_confidence=?, "
                    "triage_suggested_relationship=?, triage_inferred_domain=?, "
                    "triage_risk_flags=?, triage_contact_display=?, triaged_at=? "
                    "WHERE thread_id=?",
                    (
                        entry["triage_bucket"],
                        entry["triage_reason"],
                        entry["triage_confidence"],
                        entry["triage_suggested_relationship"],
                        entry["triage_inferred_domain"],
                        entry["triage_risk_flags"],
                        entry["triage_contact_display"],
                        entry["triaged_at"],
                        r["thread_id"],
                    ),
                )

        if not dry_run:
            conn.commit()

    finally:
        _rct.CHAT_DB = _orig_chat_db

    return {
        "dry_run":   dry_run,
        "processed": len(rows),
        "counts":    counts,
        "results":   results,
    }


def get_triage_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return bucket counts and last triage timestamp from the DB."""
    try:
        _ensure_triage_columns(conn)
        summary: dict[str, Any] = {b: 0 for b in TRIAGE_BUCKETS}
        for r in conn.execute(
            "SELECT triage_bucket, COUNT(*) FROM threads "
            "WHERE is_reviewed=-1 AND triage_bucket IS NOT NULL "
            "GROUP BY triage_bucket"
        ).fetchall():
            if r[0] in TRIAGE_BUCKETS:
                summary[r[0]] = r[1]
        summary["untriaged"] = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE is_reviewed=-1 AND triage_bucket IS NULL"
        ).fetchone()[0]
        summary["last_triaged"] = conn.execute(
            "SELECT MAX(triaged_at) FROM threads WHERE triaged_at IS NOT NULL"
        ).fetchone()[0]
        return summary
    except Exception as exc:
        return {"error": str(exc)[:200]}


def get_review_queue(
    conn: sqlite3.Connection,
    bucket: "str | None" = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return triaged threads for dashboard display. Phone numbers are masked."""
    try:
        _ensure_triage_columns(conn)
        where_parts = ["is_reviewed = -1", "triage_bucket IS NOT NULL"]
        params: list[Any] = []
        if bucket:
            where_parts.append("triage_bucket = ?")
            params.append(bucket)
        where = " AND ".join(where_parts)
        params.append(limit)
        rows = conn.execute(
            f"SELECT thread_id, contact_handle, message_count, date_last, "
            f"category, work_confidence, reason_codes, "
            f"triage_bucket, triage_reason, triage_confidence, "
            f"triage_suggested_relationship, triage_inferred_domain, "
            f"triage_risk_flags, triage_contact_display, triaged_at "
            f"FROM threads WHERE {where} "
            f"ORDER BY triage_confidence DESC, work_confidence DESC "
            f"LIMIT ?",
            params,
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "thread_id":              r["thread_id"],
                "contact_display":        r["triage_contact_display"] or _rct._mask(r["contact_handle"]),
                "contact_masked":         _rct._mask(r["contact_handle"]),
                "message_count":          r["message_count"],
                "date_last":              (r["date_last"] or "")[:10],
                "category":               r["category"],
                "work_confidence":        r["work_confidence"],
                "triage_bucket":          r["triage_bucket"],
                "triage_reason":          r["triage_reason"],
                "triage_confidence":      r["triage_confidence"],
                "suggested_relationship": r["triage_suggested_relationship"],
                "inferred_domain":        r["triage_inferred_domain"],
                "risk_flags":             json.loads(r["triage_risk_flags"] or "[]"),
            })
        return out
    except Exception:
        return []


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        print(f"[error] Thread index not found: {DB_PATH}")
        print("Run first: python3 scripts/client_intel_backfill.py --dry-run --limit 100")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _print_run_summary(result: dict[str, Any], verbose: bool = False) -> None:
    mode = "DRY RUN" if result.get("dry_run") else "APPLIED"
    print(f"\n=== Auto-Triage Client Threads [{mode}] ===")
    print(f"  Processed : {result['processed']}")
    for bucket in ("high_value", "ambiguous", "low_priority", "hidden_personal"):
        n = result["counts"].get(bucket, 0)
        print(f"  {bucket:20s}: {n}")
    if verbose and result.get("results"):
        print("\n--- Examples (up to 2 per bucket) ---")
        seen: dict[str, int] = {}
        for r in result["results"]:
            b = r["triage_bucket"]
            if seen.get(b, 0) >= 2:
                continue
            seen[b] = seen.get(b, 0) + 1
            flags = json.loads(r.get("triage_risk_flags", "[]"))
            print(
                f"  [{b}] {r['contact_masked']}  "
                f"domain={r['triage_inferred_domain']}  "
                f"suggested={r['triage_suggested_relationship']}  "
                f"conf={r['triage_confidence']:.2f}"
            )
            print(f"         {r['triage_reason']}")
            if flags:
                print(f"         risk_flags: {', '.join(flags)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-triage pending client intelligence threads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python3 scripts/auto_triage_client_threads.py --limit 200 --verbose
  python3 scripts/auto_triage_client_threads.py --apply
  python3 scripts/auto_triage_client_threads.py --summary
  python3 scripts/auto_triage_client_threads.py --bucket high_value --verbose
  python3 scripts/auto_triage_client_threads.py --chat-db data/client_intel/chatdb_snapshot/chat.db --apply --verbose
""",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write triage fields to DB (default is dry-run, no changes)")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max threads to process (default 500)")
    parser.add_argument("--bucket", choices=sorted(TRIAGE_BUCKETS),
                        help="Only show/apply threads in this bucket")
    parser.add_argument("--summary", action="store_true",
                        help="Show DB bucket counts only; no processing")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print example entries from each bucket")
    parser.add_argument("--chat-db", metavar="PATH",
                        help="Path to a chat.db snapshot to use instead of the live "
                             "~/Library/Messages/chat.db (useful when Messages.app holds a lock). "
                             "WAL/SHM files alongside the snapshot are handled transparently.")
    args = parser.parse_args()

    chat_db_path: "Path | None" = None
    if args.chat_db:
        chat_db_path = Path(args.chat_db)
        if not chat_db_path.is_absolute():
            chat_db_path = REPO_ROOT / chat_db_path
        if not chat_db_path.is_file():
            print(f"[error] --chat-db path not found: {chat_db_path}")
            sys.exit(1)
        print(f"  Using chat.db snapshot: {chat_db_path}")

    conn = _open_db()
    try:
        if args.summary:
            s = get_triage_summary(conn)
            print("\n=== Triage Summary (from DB) ===")
            for k, v in s.items():
                print(f"  {k:25s}: {v}")
            return

        result = run_triage(
            conn,
            limit=args.limit,
            dry_run=not args.apply,
            bucket_filter=args.bucket,
            chat_db_path=chat_db_path,
        )
        _print_run_summary(result, verbose=args.verbose)
        if result.get("dry_run"):
            print("\n  (dry-run — re-run with --apply to persist triage fields)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
