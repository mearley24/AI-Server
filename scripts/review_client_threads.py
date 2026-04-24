#!/usr/bin/env python3
"""
Interactive CLI for reviewing detected work threads from the client intel backfill.

Usage:
    python3 scripts/review_client_threads.py              # safe mode (masked)
    python3 scripts/review_client_threads.py --full       # full context for operator
    python3 scripts/review_client_threads.py --limit 10
    python3 scripts/review_client_threads.py --min-confidence 0.7
    python3 scripts/review_client_threads.py --summary

Modes:
    --safe (default)  Contacts masked, no message text shown. Safe for screen sharing.
    --full            Full phone, contact name if known, last 3–5 message snippets.
                      Intended for Matt only. Does not store unmasked data.

All approvals are explicit — nothing is auto-approved.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"

CHAT_DB   = Path.home() / "Library" / "Messages" / "chat.db"
ABOOK_DB  = Path.home() / "Library" / "Application Support" / "AddressBook" / "AddressBook-v22.abcddb"

SNIPPET_LIMIT = 5
SNIPPET_WIDTH = 120

# Review state values
PENDING  = -1
REJECTED =  0
APPROVED =  1

STATUS_LABEL = {PENDING: "pending", REJECTED: "rejected", APPROVED: "approved"}

VALID_RELATIONSHIP_TYPES = frozenset({
    "client", "vendor", "builder", "trade_partner",
    "internal_team", "personal_work_related", "unknown",
})

RELATIONSHIP_CHOICES = {
    "c": "client",
    "v": "vendor",
    "b": "builder",
    "t": "trade_partner",
    "i": "internal_team",
    "p": "personal_work_related",
    "u": "unknown",
}
RELATIONSHIP_MENU = (
    "  [c] client          [v] vendor       [b] builder\n"
    "  [t] trade_partner   [i] internal     [p] personal_work_related\n"
    "  [u] unknown (default)"
)


# ── Masking ───────────────────────────────────────────────────────────────────

def _mask(handle: str) -> str:
    """Mask all but first 3 and last 2 chars: '+18609171850' → '+18***50'."""
    return handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"


def _norm_phone(phone: str) -> str:
    """Strip non-digits except leading +."""
    digits = re.sub(r"[^\d]", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits


# ── Contact name lookup (AddressBook) ─────────────────────────────────────────

def _lookup_contact_name(handle: str) -> str:
    """Return 'First Last' or org name from AddressBook, or '' if not found."""
    if not ABOOK_DB.is_file():
        return ""
    norm = _norm_phone(handle)
    if not norm:
        return ""
    try:
        conn = sqlite3.connect(f"file:{ABOOK_DB}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION "
            "FROM ZABCDRECORD r "
            "JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK "
            "WHERE replace(replace(replace(replace(p.ZFULLNUMBER,'+',''),'-',''),'(',''),')','') "
            "      LIKE ? "
            "LIMIT 3",
            (f"%{norm}",),
        ).fetchall()
        conn.close()
        for r in rows:
            first = (r["ZFIRSTNAME"] or "").strip()
            last  = (r["ZLASTNAME"]  or "").strip()
            org   = (r["ZORGANIZATION"] or "").strip()
            name  = " ".join(p for p in [first, last] if p) or org
            if name:
                return name
    except Exception:
        pass
    return ""


# ── Message snippets (chat.db) ────────────────────────────────────────────────

def _decode_attr_body(blob: bytes) -> str:
    """Extract human-readable text from an NSAttributedString binary blob.

    Messages.app uses NSArchiver streamtyped format. Strategy: decode as latin-1,
    strip ObjC class-name tokens and binary noise, keep printable runs.
    """
    if not blob:
        return ""
    try:
        raw = blob.decode("latin-1", errors="replace")
        # Strip known ObjC/NSArchiver class names and binary prefix tokens
        raw = re.sub(
            r"streamtyped|bplist\d*|NSAttributedString|NSMutableAttributedString|"
            r"NSMutableString|NSMutableDictionary|NSDictionary|NSObject|NSString|"
            r"NSArray|NSFont|NSColor|NSParagraphStyle|NSValue|NSNumber|NSURL|"
            r"CTFont|CTParagraph|__NSCFString|__kIMMessagePartAttributeName|kIMMessagePartAttributeName",
            " ", raw
        )
        # Keep printable ASCII + Latin-1 supplement
        cleaned = re.sub(r"[^\x20-\x7e\xa0-\xff]+", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Discard short noise fragments between spaces
        words = [w for w in cleaned.split() if len(w) >= 2]
        result = " ".join(words).strip()
        return result[:SNIPPET_WIDTH] if len(result) > 4 else ""
    except Exception:
        return ""

def _fetch_snippets(chat_guid: str, n: int = SNIPPET_LIMIT) -> list[dict]:
    """Return last n messages from a thread as {direction, text}."""
    if not CHAT_DB.is_file():
        return []
    snippets: list[dict] = []
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro&immutable=1", uri=True)
        rows = conn.execute(
            "SELECT m.text, m.attributedBody, m.is_from_me "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE c.guid = ? "
            "  AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL) "
            "  AND m.date > 0 "
            "ORDER BY m.date DESC "
            "LIMIT ?",
            (chat_guid, n),
        ).fetchall()
        conn.close()
        for text, attr_body, is_from_me in reversed(rows):
            body = (text or "").strip()
            if not body and attr_body:
                body = _decode_attr_body(attr_body)
            if body:
                snippets.append({
                    "direction": "sent" if is_from_me else "received",
                    "text": body[:SNIPPET_WIDTH],
                })
    except Exception:
        pass
    return snippets


# ── DB helpers ────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        print(f"\n[error] Thread index not found: {DB_PATH}")
        print("Run first:  python3 scripts/client_intel_backfill.py --dry-run --limit 100")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def set_reviewed(conn: sqlite3.Connection, thread_id: str, status: int) -> None:
    conn.execute("UPDATE threads SET is_reviewed=? WHERE thread_id=?", (status, thread_id))
    conn.commit()


def set_relationship(conn: sqlite3.Connection, thread_id: str, rel_type: str) -> None:
    conn.execute("UPDATE threads SET relationship_type=? WHERE thread_id=?", (rel_type, thread_id))
    conn.commit()


def prompt_relationship(conn: sqlite3.Connection, thread_id: str) -> str:
    """Prompt operator to select a relationship type after approving. Returns chosen type."""
    print(f"\n       Select relationship type:")
    print(RELATIONSHIP_MENU)
    while True:
        try:
            choice = input("       > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            rel = "unknown"
            set_relationship(conn, thread_id, rel)
            print(f"       → relationship_type = {rel}")
            return rel
        rel = RELATIONSHIP_CHOICES.get(choice, "")
        if rel:
            set_relationship(conn, thread_id, rel)
            print(f"       → relationship_type = {rel}\n")
            return rel
        print(f"       ? Enter one of: {', '.join(RELATIONSHIP_CHOICES)}")


# ── Display ───────────────────────────────────────────────────────────────────

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


def _print_thread_safe(i: int, total: int, r: sqlite3.Row) -> None:
    """Minimal masked display."""
    masked    = _mask(r["contact_handle"])
    codes     = json.loads(r["reason_codes"] or "[]")
    codes_str = ", ".join(codes[:3]) if codes else "(none)"
    date_rng  = f"{(r['date_first'] or '')[:10]} → {(r['date_last'] or '')[:10]}"
    print(f"[{i}/{total}] {masked}")
    print(f"       msgs={r['message_count']}  conf={r['work_confidence']:.2f}  {date_rng}")
    print(f"       signals: {codes_str}")


def _print_thread_full(i: int, total: int, r: sqlite3.Row) -> None:
    """Expanded display with full phone, name, and message snippets."""
    handle    = r["contact_handle"]
    name      = _lookup_contact_name(handle)
    codes     = json.loads(r["reason_codes"] or "[]")
    codes_str = ", ".join(codes[:4]) if codes else "(none)"
    date_rng  = f"{(r['date_first'] or '')[:10]} → {(r['date_last'] or '')[:10]}"

    header = f"{name} ({handle})" if name else handle
    print(f"[{i}/{total}] {header}")
    print(f"       msgs={r['message_count']}  conf={r['work_confidence']:.2f}  {date_rng}")
    print(f"       signals: {codes_str}")

    snippets = _fetch_snippets(r["chat_guid"])
    if snippets:
        print("       recent:")
        for s in snippets:
            arrow = "→" if s["direction"] == "sent" else "←"
            print(f"         {arrow} \"{s['text']}\"")
    else:
        print("       recent: (no text snippets available)")


def _print_session_summary(approved: int, rejected: int, skipped: int) -> None:
    total = approved + rejected + skipped
    print(f"Session: reviewed {total}  →  approved={approved}  rejected={rejected}  skipped={skipped}")


# ── Review loop ───────────────────────────────────────────────────────────────

def run_review(
    conn: sqlite3.Connection,
    limit: int = 50,
    min_confidence: float = 0.5,
    category: str = "work",
    full: bool = False,
) -> None:
    rows = conn.execute(
        "SELECT thread_id, chat_guid, contact_handle, message_count, date_first, date_last, "
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

    mode_label = "FULL CONTEXT" if full else "SAFE (masked)"
    print(f"\n=== Review {len(rows)} pending {category} threads  [{mode_label}] ===")
    print("  [y] approve  [n] reject  [s] skip  [q] quit\n")

    approved_count = rejected_count = skipped_count = 0

    for i, r in enumerate(rows, 1):
        if full:
            _print_thread_full(i, len(rows), r)
        else:
            _print_thread_safe(i, len(rows), r)

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                _print_session_summary(approved_count, rejected_count, skipped_count)
                return

            if choice in ("y", "yes"):
                set_reviewed(conn, r["thread_id"], APPROVED)
                print("       ✓ Approved — eligible for profile extraction.")
                prompt_relationship(conn, r["thread_id"])
                approved_count += 1
                break
            elif choice in ("n", "no"):
                set_reviewed(conn, r["thread_id"], REJECTED)
                print("       ✗ Rejected — excluded from future processing.\n")
                rejected_count += 1
                break
            elif choice in ("s", "skip", ""):
                print("       ⬜ Skipped.\n")
                skipped_count += 1
                break
            elif choice in ("q", "quit", "exit"):
                _print_session_summary(approved_count, rejected_count, skipped_count)
                return
            else:
                print("       ? Enter y / n / s / q")

    _print_session_summary(approved_count, rejected_count, skipped_count)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive client thread review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python3 scripts/review_client_threads.py --summary
  python3 scripts/review_client_threads.py --full --limit 10
  python3 scripts/review_client_threads.py --safe --min-confidence 0.7
""",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--category", default="work")
    parser.add_argument("--summary", action="store_true",
                        help="Show counts only, skip review loop")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--safe", dest="full", action="store_false", default=False,
                      help="Masked display — safe for screen sharing (default)")
    mode.add_argument("--full", dest="full", action="store_true",
                      help="Full phone + contact name + message snippets (operator only)")
    args = parser.parse_args()

    conn = _open_db()
    try:
        print_summary(conn)
        if not args.summary:
            run_review(
                conn,
                limit=args.limit,
                min_confidence=args.min_confidence,
                category=args.category,
                full=args.full,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
