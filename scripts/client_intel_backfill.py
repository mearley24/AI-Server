#!/usr/bin/env python3
"""
Client Intelligence Backfill — v2 (batch + checkpoint + fact extraction).

Reads ~/Library/Messages/chat.db (read-only via immutable open) and classifies
threads as work/personal/mixed/unknown using Symphony Smart Homes signals.

Usage:
    python3 scripts/client_intel_backfill.py --dry-run --limit 1000
    python3 scripts/client_intel_backfill.py --apply  --limit 1000

Rules:
  - Personal threads are indexed only — no facts extracted, no profiles.
  - Work/mixed threads get proposed facts (pending Matt approval).
  - Facts remain proposed until approved via Cortex UI / approve-fact endpoint.
  - Checkpoint: already-indexed threads are skipped so re-runs are safe.
  - In apply mode, dry-run-only entries (is_reviewed=-1) are re-processed
    to extract facts; already-applied entries (is_reviewed>=0) are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
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

# ── Fact extraction signals ───────────────────────────────────────────────────

# Systems we track as individual facts
_SYSTEM_SIGNALS: list[str] = [
    "sonos", "control4", "lutron", "araknis", "wattbox", "pakedge",
    "vantage", "snapav", "triad", "episode audio", "composer", "c4",
    "home theater", "theater", "lighting control", "distributed audio",
    "alarm system", "camera system", "surveillance",
]
_SYSTEM_RE = re.compile(
    "|".join(re.escape(s) for s in _SYSTEM_SIGNALS), re.IGNORECASE
)

# Signal sets for relationship-type inference
_BUILDER_SIGNALS: frozenset[str] = frozenset({
    "builder", "general contractor", "sub contractor", "construction",
    "prewire", "pre-wire", "rough.in", "project manager",
})
_CLIENT_SIGNALS: frozenset[str] = frozenset({
    "client", "homeowner", "new client", "potential client",
    "invoice", "billing", "deposit",
})


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
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        if "relationship_type" not in existing:
            conn.execute("ALTER TABLE threads ADD COLUMN relationship_type TEXT DEFAULT 'unknown'")

    with sqlite3.connect(PROFILES_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id          TEXT PRIMARY KEY,
                relationship_type   TEXT NOT NULL DEFAULT 'unknown',
                display_name        TEXT DEFAULT '',
                contact_handle      TEXT NOT NULL,
                thread_ids          TEXT DEFAULT '[]',
                first_seen          TEXT DEFAULT '',
                last_seen           TEXT DEFAULT '',
                summary             TEXT DEFAULT '',
                open_requests       TEXT DEFAULT '[]',
                follow_ups          TEXT DEFAULT '[]',
                systems_or_topics   TEXT DEFAULT '[]',
                project_refs        TEXT DEFAULT '[]',
                dtools_project_refs TEXT DEFAULT '[]',
                confidence          REAL DEFAULT 0.0,
                status              TEXT DEFAULT 'proposed',
                last_updated        TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_profiles_handle ON profiles(contact_handle);
            CREATE INDEX IF NOT EXISTS idx_profiles_type   ON profiles(relationship_type);
            CREATE INDEX IF NOT EXISTS idx_profiles_status ON profiles(status);
        """)

    with sqlite3.connect(PROPOSED_FACTS_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS proposed_facts (
                fact_id          TEXT PRIMARY KEY,
                profile_id       TEXT NOT NULL DEFAULT '',
                thread_id        TEXT NOT NULL,
                contact_handle   TEXT NOT NULL,
                fact_type        TEXT NOT NULL,
                fact_value       TEXT NOT NULL,
                confidence       REAL DEFAULT 0.0,
                source_excerpt   TEXT DEFAULT '',
                source_timestamp TEXT DEFAULT '',
                is_accepted      INTEGER DEFAULT 0,
                is_rejected      INTEGER DEFAULT 0,
                created_at       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_facts_profile ON proposed_facts(profile_id);
            CREATE INDEX IF NOT EXISTS idx_facts_thread  ON proposed_facts(thread_id);
            CREATE INDEX IF NOT EXISTS idx_facts_handle  ON proposed_facts(contact_handle);
            CREATE INDEX IF NOT EXISTS idx_facts_type    ON proposed_facts(fact_type);
        """)


# ── Read from chat.db (read-only via immutable open) ─────────────────────────

def _open_chat_db() -> tuple[sqlite3.Connection, str]:
    """Open chat.db read-only. Returns (conn, sentinel)."""
    if not CHAT_DB.exists():
        raise FileNotFoundError(f"chat.db not found: {CHAT_DB}")
    conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro&immutable=1", uri=True)
    return conn, ""


def _close_chat_db(conn: sqlite3.Connection, tmp: str) -> None:
    conn.close()
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
        text = blob.decode("utf-8", errors="ignore")
        cleaned = re.sub(r"[^\x20-\x7E -￿]+", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:500]
    except Exception:
        return ""


def fetch_sample_texts(conn: sqlite3.Connection, chat_guid: str, sample_size: int = 30) -> list[str]:
    """Fetch up to sample_size message texts from a thread."""
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


# ── Checkpoint support ────────────────────────────────────────────────────────

def _load_checkpoint(db_path: Path, apply_mode: bool = False) -> set[str]:
    """Return thread_ids that should be skipped this run.

    apply_mode=False (dry-run): skip any already-indexed thread.
    apply_mode=True (apply): skip only threads already live-indexed
      (is_reviewed >= 0), allowing dry-run proposals to be upgraded.
    """
    if not db_path.is_file():
        return set()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        if apply_mode:
            rows = conn.execute(
                "SELECT thread_id FROM threads WHERE is_reviewed >= 0"
            ).fetchall()
        else:
            rows = conn.execute("SELECT thread_id FROM threads").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ── Fact extraction ───────────────────────────────────────────────────────────

def _thread_id(chat_guid: str, handle: str) -> str:
    return hashlib.sha256(f"{chat_guid}::{handle}".encode()).hexdigest()[:16]


def _infer_relationship_type(reason_codes: list[str]) -> str:
    """Infer relationship type from classifier reason codes."""
    signals_text = " ".join(reason_codes).lower()
    for sig in _BUILDER_SIGNALS:
        if sig in signals_text:
            return "builder"
    for sig in _CLIENT_SIGNALS:
        if sig in signals_text:
            return "client"
    return "unknown"


def _extract_facts_for_thread(
    thread_id: str,
    contact_handle: str,
    texts: list[str],
    classification: dict,
    now_iso: str,
) -> list[dict]:
    """Extract proposed facts from a work/mixed thread.

    Extracts one relationship_type fact and one fact per distinct system signal.
    All facts remain proposed (is_accepted=0) until Matt approves via the UI.
    """
    facts: list[dict] = []
    combined = " ".join(t or "" for t in texts)
    base = f"{thread_id}::"

    # Relationship type inference
    rel_type = _infer_relationship_type(classification["reason_codes"])
    facts.append({
        "fact_id": hashlib.sha256((base + "rel_type").encode()).hexdigest()[:16],
        "profile_id": "",
        "thread_id": thread_id,
        "contact_handle": contact_handle,
        "fact_type": "relationship_type",
        "fact_value": rel_type,
        "confidence": classification["work_confidence"],
        "source_excerpt": "",
        "source_timestamp": "",
        "is_accepted": 0,
        "is_rejected": 0,
        "created_at": now_iso,
    })

    # Distinct systems mentioned
    system_matches = {m.lower() for m in _SYSTEM_RE.findall(combined)}
    for sys_name in sorted(system_matches):
        facts.append({
            "fact_id": hashlib.sha256((base + "system:" + sys_name).encode()).hexdigest()[:16],
            "profile_id": "",
            "thread_id": thread_id,
            "contact_handle": contact_handle,
            "fact_type": "system",
            "fact_value": sys_name,
            "confidence": classification["work_confidence"],
            "source_excerpt": "",
            "source_timestamp": "",
            "is_accepted": 0,
            "is_rejected": 0,
            "created_at": now_iso,
        })

    return facts


# ── Status helper (used by API endpoint and CLI) ──────────────────────────────

def get_backfill_status() -> dict[str, Any]:
    """Return current backfill status without touching chat.db."""
    result: dict[str, Any] = {
        "total_indexed": 0,
        "work": 0,
        "mixed": 0,
        "personal": 0,
        "unknown": 0,
        "reviewed": 0,
        "approved_profiles": 0,
        "proposed_facts": 0,
        "last_run": None,
    }

    if THREAD_INDEX_DB.is_file():
        try:
            conn = sqlite3.connect(f"file:{THREAD_INDEX_DB}?mode=ro", uri=True)
            for row in conn.execute(
                "SELECT category, COUNT(*) FROM threads GROUP BY category"
            ).fetchall():
                cat = row[0] or "unknown"
                result[cat] = result.get(cat, 0) + int(row[1])
                result["total_indexed"] += int(row[1])
            result["reviewed"] = conn.execute(
                "SELECT COUNT(*) FROM threads WHERE is_reviewed=1"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

    if PROFILES_DB.is_file():
        try:
            conn = sqlite3.connect(f"file:{PROFILES_DB}?mode=ro", uri=True)
            result["approved_profiles"] = conn.execute(
                "SELECT COUNT(*) FROM profiles WHERE status='approved'"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

    if PROPOSED_FACTS_DB.is_file():
        try:
            conn = sqlite3.connect(f"file:{PROPOSED_FACTS_DB}?mode=ro", uri=True)
            result["proposed_facts"] = conn.execute(
                "SELECT COUNT(*) FROM proposed_facts WHERE is_accepted=0 AND is_rejected=0"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

    if BACKFILL_LOG.is_file():
        try:
            lines = BACKFILL_LOG.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last = json.loads(lines[-1])
                result["last_run"] = last.get("ts")
        except Exception:
            pass

    return result


# ── Main backfill logic ───────────────────────────────────────────────────────

def run_backfill(
    limit: int = 100,
    dry_run: bool = True,
    output_summary: bool = True,
) -> dict:
    """Run the backfill pipeline.

    dry_run=True  — classifies and indexes with is_reviewed=-1 (proposal).
                    Does not extract proposed facts. Skips already-indexed threads.
    dry_run=False — applies: upgrades dry-run entries, extracts proposed facts for
                    work/mixed threads. Skips already-applied threads (is_reviewed>=0).
    """
    init_schemas()

    # Checkpoint: load already-processed thread_ids before opening chat.db
    already_indexed = _load_checkpoint(THREAD_INDEX_DB, apply_mode=not dry_run)

    started_at = datetime.now(timezone.utc).isoformat()
    counters: dict[str, int] = {"work": 0, "personal": 0, "mixed": 0, "unknown": 0}
    skipped = 0
    review_candidates = 0
    facts_proposed = 0
    thread_results: list[dict] = []

    chat_conn, _chat_tmp = _open_chat_db()
    try:
        threads = fetch_threads(chat_conn, limit)
        now_iso = datetime.now(timezone.utc).isoformat()

        facts_conn: sqlite3.Connection | None = None
        if not dry_run:
            facts_conn = sqlite3.connect(str(PROPOSED_FACTS_DB))

        try:
            with sqlite3.connect(THREAD_INDEX_DB) as idx_conn:
                for t in threads:
                    tid = _thread_id(t["chat_guid"], t["contact_handle"])

                    if tid in already_indexed:
                        skipped += 1
                        continue

                    texts = fetch_sample_texts(chat_conn, t["chat_guid"])
                    classification = classify_text_sample(texts)
                    cat = classification["category"]
                    counters[cat] = counters.get(cat, 0) + 1

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
                        # Apply mode: write live entry (overwrite dry-run if present)
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

                        # Extract proposed facts for work/mixed only
                        if cat in ("work", "mixed") and facts_conn is not None:
                            facts = _extract_facts_for_thread(
                                tid, t["contact_handle"], texts, classification, now_iso
                            )
                            for fact in facts:
                                facts_conn.execute("""
                                    INSERT OR IGNORE INTO proposed_facts
                                      (fact_id,profile_id,thread_id,contact_handle,fact_type,
                                       fact_value,confidence,source_excerpt,source_timestamp,
                                       is_accepted,is_rejected,created_at)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                                """, (
                                    fact["fact_id"], fact["profile_id"], fact["thread_id"],
                                    fact["contact_handle"], fact["fact_type"], fact["fact_value"],
                                    fact["confidence"], fact["source_excerpt"],
                                    fact["source_timestamp"], fact["is_accepted"],
                                    fact["is_rejected"], fact["created_at"],
                                ))
                                facts_proposed += 1
                            if facts:
                                review_candidates += 1
                    else:
                        # Dry-run: index with is_reviewed=-1 (proposal, not applied)
                        idx_conn.execute("""
                            INSERT OR IGNORE INTO threads
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
            if facts_conn is not None:
                facts_conn.commit()
                facts_conn.close()
    finally:
        _close_chat_db(chat_conn, _chat_tmp)

    run_entry = {
        "ts": started_at,
        "mode": "dry_run" if dry_run else "live",
        "limit": limit,
        "processed": len(thread_results),
        "skipped": skipped,
        "review_candidates": review_candidates,
        "facts_proposed": facts_proposed,
        **counters,
    }
    with BACKFILL_LOG.open("a") as f:
        f.write(json.dumps(run_entry) + "\n")

    if output_summary:
        _print_summary(thread_results, counters, dry_run, skipped, facts_proposed)

    return {"run": run_entry, "threads": thread_results}


def _print_summary(
    threads: list[dict],
    counters: dict,
    dry_run: bool,
    skipped: int = 0,
    facts_proposed: int = 0,
) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n=== Client Intel Backfill — {mode} ===")
    print(f"Processed: {len(threads)} threads  |  Skipped (already indexed): {skipped}")
    print(f"  work:     {counters.get('work', 0)}")
    print(f"  mixed:    {counters.get('mixed', 0)}")
    print(f"  personal: {counters.get('personal', 0)}")
    print(f"  unknown:  {counters.get('unknown', 0)}")
    if not dry_run:
        print(f"  facts proposed: {facts_proposed}")
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
    parser = argparse.ArgumentParser(description="Client Intelligence Backfill v2")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Dry-run mode — classify and index only, no fact extraction")
    parser.add_argument("--apply", action="store_true",
                        help="Apply mode — write to DB and extract proposed facts")
    parser.add_argument("--live", action="store_true",
                        help="Alias for --apply (legacy)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max threads to fetch from chat.db")
    parser.add_argument("--output-summary", action="store_true", default=True,
                        help="Print summary table (default on)")
    parser.add_argument("--init-only", action="store_true",
                        help="Only create schemas, do not run backfill")
    parser.add_argument("--status", action="store_true",
                        help="Print current backfill status and exit")
    args = parser.parse_args()

    if args.init_only:
        init_schemas()
        print("Schemas initialised.")
    elif args.status:
        s = get_backfill_status()
        print(json.dumps(s, indent=2))
    else:
        # Default to dry-run unless --apply or --live is specified
        dry = not (args.apply or args.live)
        run_backfill(limit=args.limit, dry_run=dry, output_summary=args.output_summary)
