#!/usr/bin/env python3
"""
Relationship Profile Extractor — Phase 2 (proposed facts only).

Reads approved threads from message_thread_index.sqlite and their message
snippets from chat.db, then creates proposed profile records and extracted
facts. Nothing is approved automatically — every fact is proposed first.

Usage:
    python3 scripts/extract_relationship_profiles.py --dry-run
    python3 scripts/extract_relationship_profiles.py --apply-approved

Rules:
  - Only processes is_reviewed=1 AND relationship_type != 'unknown'
  - No auto-approval of profiles or facts
  - Source excerpt and timestamp preserved for every fact
  - Raw messages never stored in profiles
  - personal_work_related: work-relevant context only, no auto-reply eligibility
  - internal_team: ops/task references only, no client profile facts
  - Fragment filter: values < 4 useful words dropped unless equipment/project name
  - OCR/decode garbage (e.g. "iI", "lI") is silently dropped
  - request facts validated: must imply actual ask/action/need/service-issue
  - open_requests separated from project_refs: only phrases with action triggers
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR        = REPO_ROOT / "data" / "client_intel"
THREAD_INDEX_DB = DATA_DIR / "message_thread_index.sqlite"
PROFILES_DB     = DATA_DIR / "client_profiles.sqlite"
FACTS_DB        = DATA_DIR / "proposed_facts.sqlite"

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

PROCESSABLE_TYPES = frozenset({
    "client", "builder", "vendor", "trade_partner",
    "internal_team", "personal_work_related",
})

# ── Extraction rules — (pattern, fact_type) pairs per relationship_type ───────
# request pattern uses [^\n.!?]{10,80} to stop at sentence boundaries naturally

_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "client": [
        (re.compile(r"\b(sonos|lutron|control4|vantage|araknis|wattbox|episode|triad|pakedge|snapav)\b", re.I), "equipment"),
        (re.compile(r"\b(theater|surveillance|camera|alarm|shade|keypad|dimmer|lighting|audio|network|wi.?fi|rack|prewire)\b", re.I), "system"),
        (re.compile(r"(?:can you|could you|please|need to|want to|would like|looking for|request)\s+([^\n.!?]{10,80})", re.I), "request"),
        (re.compile(r"\b(not working|broken|issue|problem|offline|trouble|cutting out|goes out)\b", re.I), "issue"),
        (re.compile(r"(?:follow.?up|call me|text me|let me know|get back|schedule|remind)\b", re.I), "follow_up"),
        (re.compile(r"(?:project|job|house|home|property)\s+(?:at|on|in|called)?\s*([A-Z][^,.!?\n]{3,40})", re.I), "project_ref"),
    ],
    "builder": [
        (re.compile(r"(?:job|project|site|lot|build)\s+(?:at|on|called)?\s*([A-Z][^,.!?\n]{3,40})", re.I), "job_name"),
        (re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|next week|tomorrow|by the \d+|schedule|deadline)\b", re.I), "schedule"),
        (re.compile(r"\b(rough.?in|trim|finish|prewire|pre-wire|walkthrough|walk.through|punch.list|inspection)\b", re.I), "coordination"),
        (re.compile(r"(?:contact|call|reach|talk to)\s+([A-Z][a-z]+ [A-Z][a-z]+)", re.I), "contact"),
    ],
    "vendor": [
        (re.compile(r"\b(sonos|lutron|control4|araknis|wattbox|triad|episode|pakedge|snapav|vantage)\b", re.I), "product"),
        (re.compile(r"\$\s*(\d[\d,]{1,6}(?:\.\d{2})?)", re.I), "pricing"),
        (re.compile(r"\b(order|part number|sku|ship|stock|available|lead.?time|back.?order|eta)\b", re.I), "order"),
        (re.compile(r"\b(warranty|rma|return|support|defect|replace)\b", re.I), "warranty"),
    ],
    "trade_partner": [
        (re.compile(r"\b(after you|before we|coordinate|handoff|hand.off|depends on|waiting on|sync up)\b", re.I), "coordination"),
        (re.compile(r"(?:job|site|project)\s+(?:at|on)?\s*([A-Z][^,.!?\n]{3,40})", re.I), "job_dependency"),
        (re.compile(r"\b(schedule|timeline|milestone|phase|ready|complete)\b", re.I), "timeline"),
    ],
    "internal_team": [
        (re.compile(r"\b(?:task|ticket|project|job|ref|#\d+|issue\s*#?\d+)\b", re.I), "ops_ref"),
        (re.compile(r"\b(deadline|due|complete|finish|done|deploy|release|ship)\b", re.I), "ops_timeline"),
    ],
    "personal_work_related": [
        (re.compile(r"\b(office|meeting|call|conference|presentation|agenda)\b", re.I), "work_context"),
        (re.compile(r"\b(budget|proposal|contract|quote|invoice|bid|estimate)\b", re.I), "work_document"),
    ],
}

# ── Quality filters ────────────────────────────────────────────────────────────

# Equipment/system names exempt from word-count requirement (short but meaningful)
_EQUIPMENT_RE = re.compile(
    r"\b(sonos|lutron|control4|vantage|araknis|wattbox|episode|triad|pakedge|snapav|"
    r"network|wi.?fi|theater|alarm|camera|shade|keypad|dimmer|lighting|audio|rack|prewire)\b",
    re.I,
)

# OCR/decoder artifacts: impossible mixed-case tokens from iMessage blob decoding
# Note: we allow \xa0-\xff (Latin-1 extended) which appear legitimately in decoded blobs
_OCR_JUNK_RE = re.compile(r"\b(iI|lI|Il|Ii|oO|O0|0O|l1|1l)\b|[^\x20-\x7e\xa0-\xff]{2,}")

# Sentence boundary for trimming captured values
_SENTENCE_END_RE = re.compile(r"[.!?]")

# Clause break for trimming run-on captures
_CLAUSE_BREAK_RE = re.compile(
    r"\b(and then|and also|but then|however|in addition to|as well as)\b", re.I
)

# Minimum useful words for general-type facts
_USEFUL_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# Triggers that confirm a "request" fact is a real open ask/need/service-issue
_REQUEST_TRIGGER_RE = re.compile(
    r"\b(can you|could you|please|need|want|fix|check|verify|look at|schedule|book|"
    r"send|call me|text me|let me know|follow.?up|not working|broken|issue|problem|"
    r"offline|trouble|cutting out|goes out|help|replace|upgrade|restart|reset|"
    r"come by|stop by|swing by|take a look|take a look at)\b",
    re.I,
)

# Fact types where short values are inherently meaningful (no word-count gate)
_SHORT_OK_TYPES = frozenset({"equipment", "product", "issue", "follow_up",
                              "schedule", "coordination", "timeline",
                              "work_context", "work_document", "ops_ref", "ops_timeline"})


def _clean_value(value: str) -> str:
    """Trim to sentence/clause boundary and strip likely-truncated trailing tokens."""
    v = value.strip()
    if not v:
        return v
    # Stop at first sentence-ending punctuation (skip first 8 chars to avoid empty result)
    m = _SENTENCE_END_RE.search(v, 8)
    if m:
        v = v[: m.start()].strip()
    # Stop at prominent clause break if it leaves at least 8 chars
    m = _CLAUSE_BREAK_RE.search(v)
    if m and m.start() >= 8:
        v = v[: m.start()].strip()
    # Strip trailing truncated token: ≤4 chars, no vowels (e.g. "syst" from "system")
    words = v.split()
    if len(words) >= 2:
        last = words[-1].rstrip(".,!?;:")
        if len(last) <= 4 and not re.search(r"[aeiou]", last, re.I):
            v = " ".join(words[:-1]).strip()
    return v.strip()


def _is_fragment(value: str, fact_type: str) -> bool:
    """Return True if value is too broken or short to trust as a proposed fact."""
    v = value.strip()
    if not v:
        return True
    # Short-OK types: only filter OCR junk, not word count
    if fact_type in _SHORT_OK_TYPES:
        return bool(_OCR_JUNK_RE.search(v))
    # Equipment/system mentions exempt from word-count requirement
    if _EQUIPMENT_RE.search(v):
        return bool(_OCR_JUNK_RE.search(v))
    # OCR/decoder garbage
    if _OCR_JUNK_RE.search(v):
        return True
    # Require at least 4 useful words for request/project_ref/contact/pricing etc.
    if len(_USEFUL_WORD_RE.findall(v)) < 4:
        return True
    return False


def _is_open_request_phrase(value: str) -> bool:
    """Return True if the phrase implies an ask, action, need, or service follow-up."""
    return bool(_REQUEST_TRIGGER_RE.search(value))


def _dedup_key(fact_type: str, value: str) -> str:
    """Normalized dedup key: strip non-alphanumeric, lowercase, truncate to 50."""
    norm = re.sub(r"[^a-z0-9]", "", value.lower())[:50]
    return f"{fact_type}:{norm}"


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid(contact_handle: str, rel_type: str) -> str:
    raw = f"{contact_handle}::{rel_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _fid(thread_id: str, fact_type: str, fact_value: str) -> str:
    raw = f"{thread_id}::{fact_type}::{fact_value[:60]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _ensure_profiles_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            profile_id          TEXT PRIMARY KEY,
            relationship_type   TEXT NOT NULL,
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


def _ensure_facts_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS proposed_facts (
            fact_id          TEXT PRIMARY KEY,
            profile_id       TEXT NOT NULL,
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


# ── chat.db access ─────────────────────────────────────────────────────────────

_APPLE_EPOCH = 978_307_200  # Jan 1 2001 UTC


def _fetch_messages(chat_guid: str, limit: int = 50) -> list[dict]:
    """Return up to limit messages with text, direction, and ISO timestamp."""
    if not CHAT_DB.is_file():
        return []
    msgs: list[dict] = []
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro&immutable=1", uri=True)
        rows = conn.execute(
            "SELECT m.text, m.attributedBody, m.is_from_me, m.date "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE c.guid = ? "
            "  AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL) "
            "  AND m.date > 0 "
            "ORDER BY m.date DESC LIMIT ?",
            (chat_guid, limit),
        ).fetchall()
        conn.close()
        for text, attr_body, is_from_me, date_ns in reversed(rows):
            body = (text or "").strip()
            if not body and attr_body:
                body = _decode_attr(attr_body)
            if body:
                ts = datetime.fromtimestamp(
                    date_ns / 1_000_000_000 + _APPLE_EPOCH, tz=timezone.utc
                ).isoformat()
                msgs.append({"text": body, "from_me": bool(is_from_me), "ts": ts})
    except Exception:
        pass
    return msgs


def _decode_attr(blob: bytes) -> str:
    """Decode NSAttributedString binary blob to plain text.

    Note: decoded messages often contain a trailing 'iI' artifact — this is
    normal for iMessage blobs and is handled at the fact-value level, not here.
    """
    try:
        raw = blob.decode("latin-1", errors="replace")
        raw = re.sub(
            r"streamtyped|bplist\d*|NSAttributedString|NSMutableAttributedString|"
            r"NSMutableString|NSMutableDictionary|NSDictionary|NSObject|NSString|"
            r"NSArray|NSFont|NSColor|NSParagraphStyle|NSValue|NSNumber|NSURL|"
            r"CTFont|CTParagraph|__NSCFString|__kIMMessagePartAttributeName|"
            r"kIMMessagePartAttributeName",
            " ", raw,
        )
        cleaned = re.sub(r"[^\x20-\x7e\xa0-\xff]+", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        words = [w for w in cleaned.split() if len(w) >= 2]
        result = " ".join(words).strip()
        return result[:200] if len(result) > 4 else ""
    except Exception:
        return ""


# ── Fact extraction ────────────────────────────────────────────────────────────

def extract_facts(
    thread_id: str,
    profile_id: str,
    contact_handle: str,
    rel_type: str,
    messages: list[dict],
) -> list[dict]:
    """Run extraction rules against messages; return proposed fact dicts.

    Quality gates applied:
    - _clean_value: trim at sentence/clause boundaries, strip truncated tokens
    - _is_fragment: drop < 4-word non-equipment values and OCR junk
    - _is_open_request_phrase: only keep 'request' facts that imply real asks
    - _dedup_key: normalized dedup (alphanumeric-only, lowercase)
    """
    rules = _RULES.get(rel_type, [])
    facts: list[dict] = []
    seen: set[str] = set()

    for msg in messages:
        text = msg["text"]
        ts   = msg["ts"]

        for pattern, fact_type in rules:
            for m in pattern.finditer(text):
                raw_value = (m.group(1) if m.lastindex and m.group(1) else m.group(0)).strip()
                value = _clean_value(raw_value[:200])
                if not value or len(value) < 2:
                    continue

                # Drop fragments and OCR garbage
                if _is_fragment(value, fact_type):
                    continue

                # Request facts must imply a real open ask or service issue
                if fact_type == "request" and not _is_open_request_phrase(value):
                    continue

                # Deduplicate using normalized key (alphanumeric only)
                dedup_key = _dedup_key(fact_type, value)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Confidence: higher for strong keyword / named-entity matches
                confidence = 0.6 if m.lastindex else 0.5
                if rel_type in ("client", "builder") and fact_type in ("equipment", "system", "job_name"):
                    confidence = 0.75
                if fact_type == "request" and _EQUIPMENT_RE.search(value):
                    confidence = 0.70  # service request mentioning known equipment

                excerpt = text[:120].replace("\n", " ")
                facts.append({
                    "fact_id":          _fid(thread_id, fact_type, value),
                    "profile_id":       profile_id,
                    "thread_id":        thread_id,
                    "contact_handle":   contact_handle,
                    "fact_type":        fact_type,
                    "fact_value":       value,
                    "confidence":       confidence,
                    "source_excerpt":   excerpt,
                    "source_timestamp": ts,
                    "is_accepted":      0,
                    "is_rejected":      0,
                    "created_at":       _now(),
                })

    return facts


# ── Profile builder ────────────────────────────────────────────────────────────

def build_profile(
    thread: dict,
    facts: list[dict],
    existing_thread_ids: list[str],
) -> dict:
    """Create or merge a profile dict from a thread and extracted facts.

    open_requests: only facts whose value implies an actual ask/action/need.
    project_refs: job/project name facts only (not open requests).
    """
    contact = thread["contact_handle"]
    rel     = thread["relationship_type"]

    systems = list({
        f["fact_value"] for f in facts
        if f["fact_type"] in ("system", "equipment", "product")
    })[:10]

    # open_requests: request-type facts that actually imply an open ask
    requests = list({
        f["fact_value"] for f in facts
        if f["fact_type"] == "request" and _is_open_request_phrase(f["fact_value"])
    })[:5]

    # follow_ups: follow_up + ops timeline facts with action language
    followups = list({
        f["fact_value"] for f in facts
        if f["fact_type"] in ("follow_up", "ops_timeline", "timeline")
    })[:5]

    # project_refs: project/job name facts — exclude values that look like open requests
    projects = list({
        f["fact_value"] for f in facts
        if f["fact_type"] in ("project_ref", "job_name", "job_dependency")
        and not _is_open_request_phrase(f["fact_value"])
    })[:10]

    thread_ids = list({*existing_thread_ids, thread["thread_id"]})
    confidence = round(min(0.95, 0.5 + 0.05 * len(facts)), 3)

    summary_parts = []
    if systems:
        summary_parts.append(f"Systems/topics: {', '.join(systems[:3])}")
    if projects:
        summary_parts.append(f"Projects: {', '.join(projects[:2])}")
    if facts:
        summary_parts.append(f"{len(facts)} proposed fact(s) extracted")
    summary = ". ".join(summary_parts) or f"{rel} profile — no facts extracted yet"

    return {
        "profile_id":          _pid(contact, rel),
        "relationship_type":   rel,
        "display_name":        "",
        "contact_handle":      contact,
        "thread_ids":          json.dumps(thread_ids),
        "first_seen":          thread.get("date_first", ""),
        "last_seen":           thread.get("date_last", ""),
        "summary":             summary[:400],
        "open_requests":       json.dumps(requests),
        "follow_ups":          json.dumps(followups),
        "systems_or_topics":   json.dumps(systems),
        "project_refs":        json.dumps(projects),
        "dtools_project_refs": json.dumps([]),
        "confidence":          confidence,
        "status":              "proposed",
        "last_updated":        _now(),
    }


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_extraction(dry_run: bool = True) -> dict:
    mode = "DRY-RUN" if dry_run else "APPLY"

    idx_conn = sqlite3.connect(f"file:{THREAD_INDEX_DB}?mode=ro&immutable=1", uri=True)
    idx_conn.row_factory = sqlite3.Row
    threads = idx_conn.execute(
        "SELECT thread_id, chat_guid, contact_handle, relationship_type, "
        "date_first, date_last, work_confidence "
        "FROM threads "
        "WHERE is_reviewed=1 AND coalesce(relationship_type,'unknown')!='unknown' "
        "  AND relationship_type IN (?,?,?,?,?,?)",
        tuple(PROCESSABLE_TYPES),
    ).fetchall()
    idx_conn.close()

    if not threads:
        print("\nNo approved threads with classified relationship_type found.")
        return {"mode": mode, "threads": 0, "profiles": 0, "facts": 0}

    all_profiles: list[dict] = []
    all_facts: list[dict]    = []
    skipped: list[str]       = []

    for t in threads:
        rel = t["relationship_type"]
        if rel not in PROCESSABLE_TYPES:
            skipped.append(f"{t['contact_handle']} ({rel})")
            continue

        messages = _fetch_messages(t["chat_guid"])
        pid      = _pid(t["contact_handle"], rel)
        facts    = extract_facts(
            thread_id=t["thread_id"],
            profile_id=pid,
            contact_handle=t["contact_handle"],
            rel_type=rel,
            messages=messages,
        )
        profile = build_profile(dict(t), facts, [])
        all_profiles.append(profile)
        all_facts.extend(facts)

    if not dry_run:
        thread_ids = [t["thread_id"] for t in threads]
        _write_profiles(all_profiles)
        _write_facts(all_facts, reprocess_thread_ids=thread_ids)

    _print_summary(all_profiles, all_facts, skipped, dry_run)
    return {
        "mode":     mode,
        "threads":  len(threads),
        "profiles": len(all_profiles),
        "facts":    len(all_facts),
        "skipped":  len(skipped),
    }


def _write_profiles(profiles: list[dict]) -> None:
    conn = sqlite3.connect(str(PROFILES_DB))
    _ensure_profiles_schema(conn)
    for p in profiles:
        conn.execute(
            "INSERT OR REPLACE INTO profiles VALUES "
            "(:profile_id,:relationship_type,:display_name,:contact_handle,"
            ":thread_ids,:first_seen,:last_seen,:summary,:open_requests,"
            ":follow_ups,:systems_or_topics,:project_refs,:dtools_project_refs,"
            ":confidence,:status,:last_updated)",
            p,
        )
    conn.commit()
    conn.close()


def _write_facts(
    facts: list[dict],
    reprocess_thread_ids: list[str] | None = None,
) -> None:
    """Write proposed facts, clearing pending (not yet reviewed) facts for reprocessed threads."""
    conn = sqlite3.connect(str(FACTS_DB))
    _ensure_facts_schema(conn)
    # Remove pending facts for threads being re-processed; leave accepted/rejected alone
    if reprocess_thread_ids:
        placeholders = ",".join("?" * len(reprocess_thread_ids))
        conn.execute(
            f"DELETE FROM proposed_facts WHERE thread_id IN ({placeholders}) "
            f"AND is_accepted=0 AND is_rejected=0",
            reprocess_thread_ids,
        )
    for f in facts:
        conn.execute(
            "INSERT OR IGNORE INTO proposed_facts VALUES "
            "(:fact_id,:profile_id,:thread_id,:contact_handle,:fact_type,"
            ":fact_value,:confidence,:source_excerpt,:source_timestamp,"
            ":is_accepted,:is_rejected,:created_at)",
            f,
        )
    conn.commit()
    conn.close()


def _print_summary(
    profiles: list[dict],
    facts: list[dict],
    skipped: list[str],
    dry_run: bool,
) -> None:
    mode = "DRY-RUN (nothing written)" if dry_run else "APPLIED"
    print(f"\n=== Relationship Profile Extraction — {mode} ===")
    print(f"  Profiles proposed : {len(profiles)}")
    print(f"  Facts proposed    : {len(facts)}")
    if skipped:
        print(f"  Skipped (unknown) : {len(skipped)}")

    by_type: dict[str, int] = {}
    for p in profiles:
        by_type[p["relationship_type"]] = by_type.get(p["relationship_type"], 0) + 1
    for rt, n in sorted(by_type.items()):
        print(f"    {rt:25s} profiles={n}")

    if facts:
        fact_types: dict[str, int] = {}
        for f in facts:
            fact_types[f["fact_type"]] = fact_types.get(f["fact_type"], 0) + 1
        print("\n  Fact type breakdown:")
        for ft, n in sorted(fact_types.items(), key=lambda x: -x[1]):
            print(f"    {ft:20s} {n}")
    print()


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Relationship Profile Extractor — Phase 2")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview extraction without writing to DB (default)")
    parser.add_argument("--apply-approved", action="store_true",
                        help="Write profiles and facts to DB for approved threads")
    args = parser.parse_args()

    dry = not args.apply_approved
    run_extraction(dry_run=dry)


if __name__ == "__main__":
    main()
