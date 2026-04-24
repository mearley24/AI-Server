#!/usr/bin/env python3
"""
Client Intelligence Backfill — Phase 1 (safe dry-run foundation).

Reads ~/Library/Messages/chat.db (read-only via temp copy) and classifies
threads as work/personal/mixed/unknown using Symphony Smart Homes signals.

Usage:
    python3 scripts/client_intel_backfill.py --dry-run --limit 100
    python3 scripts/client_intel_backfill.py --dry-run --limit 100 --output-summary

Phase 1 rules:
  - Dry-run mode only (no canonical client memory created).
  - No auto-reply, no profile writing in dry-run.
  - Read-only access to chat.db via temp file copy.
  - Writes thread index and run log only (proposed; not yet reviewed).
  - Never classifies as work from one weak signal alone.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "client_intel"
THREAD_INDEX_DB = DATA_DIR / "message_thread_index.sqlite"
PROFILES_DB = DATA_DIR / "client_profiles.sqlite"
PROPOSED_FACTS_DB = DATA_DIR / "proposed_facts.sqlite"
BACKFILL_LOG = DATA_DIR / "backfill_runs.ndjson"

# ── Classification signals ────────────────────────────────────────────────────

STRONG_SIGNALS: list[str] = [
    "symphony smart homes", "matt earley with symphony", "symphonysh",
    "control4", "composer", "c4",
    "keypad", "dimmer", "lighting control", "light scene", "lutron",
    "shade", "motorized shade", "roller shade",
    "audio", "sonos", "triad", "episode audio", "distributed audio",
    "theater", "home theater", "screening room",
    "surveillance", "camera system", "alarm system", "security system",
    "prewire", "pre-wire", "rough.in", "trim out", "finish",
    "equipment rack", "av rack",
    "network", "araknis", "pakedge", "access point",
    "proposal", "estimate", "quote sent", "contract",
    "invoice", "billing", "deposit",
    "site visit", "walkthrough", "punch list",
    "vantage", "wattbox", "snapav",
    "builder", "general contractor", "sub contractor",
    "project manager", "construction",
    "client", "homeowner", "new client", "potential client",
]

WEAK_SIGNALS: list[str] = [
    "quote", "bid", "install", "installation",
    "service call", "service visit", "warranty",
    "troubleshoot", "trouble shooting", "not working",
    "remote access", "remote support",
    "wifi down", "wi-fi down", "internet down", "no internet",
    "music not working", "tv not working", "tv is off",
    "can you come by", "can you come out", "when can you",
    "schedule", "appointment", "available",
    "address", "located at", "my house", "the house",
]

# Pre-compile for speed
_STRONG_RE = re.compile(
    "|".join(re.escape(s) for s in STRONG_SIGNALS), re.IGNORECASE
)
_WEAK_RE = re.compile(
    "|".join(re.escape(s) for s in WEAK_SIGNALS), re.IGNORECASE
)


def classify_text_sample(texts: list[str]) -> dict[str, Any]:
    """Classify a list of message texts. Returns classification dict."""
    combined = " ".join(t or "" for t in texts)
    strong_matches = _STRONG_RE.findall(combined)
    weak_matches = _WEAK_RE.findall(combined)

    strong_count = len(strong_matches)
    weak_count = len(weak_matches)
    unique_strong = list({m.lower() for m in strong_matches})[:10]
    unique_weak = list({m.lower() for m in weak_matches})[:10]

    if strong_count >= 1:
        confidence = min(0.95, 0.70 + 0.05 * min(strong_count, 6))
        category = "work"
    elif weak_count >= 2:
        confidence = min(0.75, 0.55 + 0.05 * min(weak_count, 4))
        category = "work"
    elif weak_count == 1:
        confidence = 0.30
        category = "mixed"
    else:
        confidence = 0.05
        category = "personal"

    reason_codes = []
    if unique_strong:
        reason_codes.append(f"strong:{','.join(unique_strong[:5])}")
    if unique_weak:
        reason_codes.append(f"weak:{','.join(unique_weak[:5])}")

    return {
        "category": category,
        "work_confidence": round(confidence, 3),
        "reason_codes": reason_codes,
        "strong_count": strong_count,
        "weak_count": weak_count,
    }


# ── Schema initialisation ─────────────────────────────────────────────────────

def init_schemas() -> None:
    """Create all three SQLite DBs with v1 schemas if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(THREAD_INDEX_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS threads (
                thread_id         TEXT PRIMARY KEY,
                chat_guid         TEXT NOT NULL,
                contact_handle    TEXT NOT NULL,
                message_count     INTEGER DEFAULT 0,
                sample_count      INTEGER DEFAULT 0,
                date_first        TEXT,
                date_last         TEXT,
                category          TEXT DEFAULT 'unknown',
                work_confidence   REAL DEFAULT 0.0,
                reason_codes      TEXT DEFAULT '[]',
                is_reviewed       INTEGER DEFAULT 0,
                relationship_type TEXT DEFAULT 'unknown',
                created_at        TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_threads_category ON threads(category);
            CREATE INDEX IF NOT EXISTS idx_threads_confidence ON threads(work_confidence DESC);
            -- Migration: add relationship_type to existing DBs
            -- SQLite ignores duplicate column errors with IF NOT EXISTS unavailable for columns,
            -- so we use a pragma check pattern instead.
        """)
        # Add column to existing tables that predate this schema version
        existing = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        if "relationship_type" not in existing:
            conn.execute("ALTER TABLE threads ADD COLUMN relationship_type TEXT DEFAULT 'unknown'")

    with sqlite3.connect(PROFILES_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id      TEXT PRIMARY KEY,
                contact_handle  TEXT NOT NULL UNIQUE,
                display_name    TEXT DEFAULT '',
                category        TEXT DEFAULT 'unknown',
                work_confidence REAL DEFAULT 0.0,
                project_signals TEXT DEFAULT '{}',
                thread_count    INTEGER DEFAULT 0,
                last_updated    TEXT NOT NULL,
                is_reviewed     INTEGER DEFAULT 0
            );
        """)

    with sqlite3.connect(PROPOSED_FACTS_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS proposed_facts (
                fact_id             TEXT PRIMARY KEY,
                thread_id           TEXT NOT NULL,
                contact_handle      TEXT NOT NULL,
                fact_type           TEXT NOT NULL,
                fact_value          TEXT NOT NULL,
                confidence          REAL DEFAULT 0.0,
                source_message_id   TEXT DEFAULT '',
                is_accepted         INTEGER DEFAULT 0,
                is_rejected         INTEGER DEFAULT 0,
                created_at          TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_facts_thread ON proposed_facts(thread_id);
            CREATE INDEX IF NOT EXISTS idx_facts_handle ON proposed_facts(contact_handle);
        """)


# ── Read from chat.db (read-only via temp copy) ───────────────────────────────

def _open_chat_db() -> tuple[sqlite3.Connection, str]:
    """Open chat.db read-only. Returns (conn, sentinel) — sentinel is "" for direct open."""
    if not CHAT_DB.exists():
        raise FileNotFoundError(f"chat.db not found: {CHAT_DB}")
    # Open directly in immutable read-only mode — safe alongside Messages.app.
    # Using ?immutable=1 avoids WAL header writes; the WAL is still readable.
    conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro&immutable=1", uri=True)
    return conn, ""


def _close_chat_db(conn: sqlite3.Connection, tmp: str) -> None:
    conn.close()
    # tmp is "" for direct opens; legacy temp-file cleanup kept for safety
    if tmp:
        for path in [tmp, tmp + "-wal", tmp + "-shm"]:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def _apple_epoch_to_iso(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        unix = ts / 1_000_000_000 + 978_307_200
        return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def fetch_threads(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Fetch the most-recently active 1:1 threads ordered by latest activity."""
    # Step 1: get threads sorted by most-recent message
    thread_query = """
        SELECT
            c.ROWID           AS chat_rowid,
            c.guid            AS chat_guid,
            c.chat_identifier AS contact_handle,
            COUNT(m.ROWID)    AS message_count,
            MIN(m.date)       AS date_first,
            MAX(m.date)       AS date_last
        FROM chat c
        JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
        JOIN message m             ON m.ROWID = cmj.message_id
        WHERE c.chat_identifier NOT LIKE 'chat%'
          AND c.chat_identifier != ''
          AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
          AND m.date > 0
        GROUP BY c.ROWID
        ORDER BY date_last DESC
        LIMIT ?
    """
    rows = conn.execute(thread_query, (limit,)).fetchall()
    return [
        {
            "chat_guid": r[1],
            "contact_handle": r[2] or r[1],
            "message_count": r[3],
            "date_first": _apple_epoch_to_iso(r[4]),
            "date_last": _apple_epoch_to_iso(r[5]),
        }
        for r in rows
    ]


def _decode_attributed_body(blob: bytes | None) -> str:
    """Extract plain text from an NSAttributedString binary plist blob."""
    if not blob:
        return ""
    try:
        import plistlib
        # attributedBody is a streamtyped NSAttributedString — extract the string value
        # by searching for the UTF-8 text after the plist prefix bytes.
        text = blob.decode("utf-8", errors="ignore")
        # Strip binary plist header noise — keep printable runs ≥ 4 chars
        cleaned = re.sub(r"[^\x20-\x7E -￿]+", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:500]
    except Exception:
        return ""


def fetch_sample_texts(conn: sqlite3.Connection, chat_guid: str, sample_size: int = 30) -> list[str]:
    """Fetch up to sample_size message texts from a thread (text + attributedBody)."""
    query = """
        SELECT m.text, m.attributedBody
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        JOIN chat c ON c.ROWID = cmj.chat_id
        WHERE c.guid = ?
          AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
          AND m.date > 0
        ORDER BY m.date DESC
        LIMIT ?
    """
    rows = conn.execute(query, (chat_guid, sample_size)).fetchall()
    texts = []
    for text, attr_body in rows:
        if text and len(text.strip()) > 0:
            texts.append(text)
        elif attr_body:
            decoded = _decode_attributed_body(attr_body)
            if decoded:
                texts.append(decoded)
    return texts


# ── Main backfill logic ───────────────────────────────────────────────────────

def _thread_id(chat_guid: str, handle: str) -> str:
    import hashlib
    return hashlib.sha256(f"{chat_guid}::{handle}".encode()).hexdigest()[:16]


def run_backfill(limit: int = 100, dry_run: bool = True, output_summary: bool = True) -> dict:
    """Run the backfill pipeline."""
    init_schemas()

    started_at = datetime.now(timezone.utc).isoformat()
    counters: dict[str, int] = {"work": 0, "personal": 0, "mixed": 0, "unknown": 0}
    thread_results: list[dict] = []

    chat_conn, _chat_tmp = _open_chat_db()
    try:
        threads = fetch_threads(chat_conn, limit)
        now_iso = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(THREAD_INDEX_DB) as idx_conn:
            for t in threads:
                texts = fetch_sample_texts(chat_conn, t["chat_guid"])
                classification = classify_text_sample(texts)
                cat = classification["category"]
                counters[cat] = counters.get(cat, 0) + 1

                tid = _thread_id(t["chat_guid"], t["contact_handle"])
                result = {
                    "thread_id": tid,
                    "chat_guid": t["chat_guid"],
                    "contact_handle": t["contact_handle"],
                    "message_count": t["message_count"],
                    "sample_count": len(texts),
                    "date_first": t["date_first"],
                    "date_last": t["date_last"],
                    **classification,
                }
                thread_results.append(result)

                if not dry_run:
                    idx_conn.execute("""
                        INSERT OR REPLACE INTO threads
                          (thread_id,chat_guid,contact_handle,message_count,sample_count,
                           date_first,date_last,category,work_confidence,reason_codes,
                           is_reviewed,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,0,?)
                    """, (
                        tid, t["chat_guid"], t["contact_handle"],
                        t["message_count"], len(texts),
                        t["date_first"], t["date_last"],
                        cat, classification["work_confidence"],
                        json.dumps(classification["reason_codes"]),
                        now_iso,
                    ))
                else:
                    # dry-run: upsert with is_reviewed=-1 to mark as dry-run proposal
                    idx_conn.execute("""
                        INSERT OR REPLACE INTO threads
                          (thread_id,chat_guid,contact_handle,message_count,sample_count,
                           date_first,date_last,category,work_confidence,reason_codes,
                           is_reviewed,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,-1,?)
                    """, (
                        tid, t["chat_guid"], t["contact_handle"],
                        t["message_count"], len(texts),
                        t["date_first"], t["date_last"],
                        cat, classification["work_confidence"],
                        json.dumps(classification["reason_codes"]),
                        now_iso,
                    ))

    finally:
        _close_chat_db(chat_conn, _chat_tmp)

    # Write run log
    run_entry = {
        "ts": started_at,
        "mode": "dry_run" if dry_run else "live",
        "limit": limit,
        "processed": len(thread_results),
        **counters,
    }
    with BACKFILL_LOG.open("a") as f:
        f.write(json.dumps(run_entry) + "\n")

    if output_summary:
        _print_summary(thread_results, counters, dry_run)

    return {"run": run_entry, "threads": thread_results}


def _print_summary(threads: list[dict], counters: dict, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n=== Client Intel Backfill — {mode} ===")
    print(f"Processed: {len(threads)} threads")
    print(f"  work:     {counters.get('work', 0)}")
    print(f"  mixed:    {counters.get('mixed', 0)}")
    print(f"  personal: {counters.get('personal', 0)}")
    print(f"  unknown:  {counters.get('unknown', 0)}")
    print()
    work_threads = sorted(
        [t for t in threads if t["category"] == "work"],
        key=lambda x: x["work_confidence"], reverse=True,
    )
    if work_threads:
        print("Top work threads:")
        for t in work_threads[:10]:
            handle = t["contact_handle"]
            masked = handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"
            codes = ", ".join(t["reason_codes"][:2])
            print(f"  {masked:20s}  conf={t['work_confidence']:.2f}  msgs={t['message_count']:4d}  {codes}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Client Intelligence Backfill")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry-run mode — no canonical facts written (default)")
    parser.add_argument("--live", action="store_true",
                        help="Live mode — writes to thread index (requires explicit flag)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max threads to process")
    parser.add_argument("--output-summary", action="store_true", default=True,
                        help="Print summary table (default on)")
    parser.add_argument("--init-only", action="store_true",
                        help="Only create schemas, do not run backfill")
    args = parser.parse_args()

    if args.init_only:
        init_schemas()
        print("Schemas initialised.")
    else:
        dry = not args.live
        run_backfill(limit=args.limit, dry_run=dry, output_summary=args.output_summary)
