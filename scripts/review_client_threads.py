#!/usr/bin/env python3
"""
Interactive CLI for reviewing detected work threads from the client intel backfill.

Usage:
    python3 scripts/review_client_threads.py                    # names-first (default)
    python3 scripts/review_client_threads.py --full             # full context for operator
    python3 scripts/review_client_threads.py --named-only       # only resolved-name threads
    python3 scripts/review_client_threads.py --unnamed-only     # only raw-number threads
    python3 scripts/review_client_threads.py --names-first      # named contacts first (default)
    python3 scripts/review_client_threads.py --approved-only    # assign relationship type
    python3 scripts/review_client_threads.py --snippets 3       # show 3 message snippets
    python3 scripts/review_client_threads.py --no-snippets      # hide snippets
    python3 scripts/review_client_threads.py --summary

Modes:
    --safe (default)   Contacts masked; safe for screen sharing.
    --full             Full phone + contact name + message snippets (operator only).
    --approved-only    Shows approved threads with relationship_type='unknown'.
                       Only prompts for relationship_type — does NOT change is_reviewed.

Contact filters (mutually exclusive; default: --names-first):
    --named-only       Show only threads with a resolved contact name.
    --unnamed-only     Show only threads without a resolved contact name.
    --names-first      Sort named contacts first, then unnamed (default).

All approvals are explicit — nothing is auto-approved.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"

CHAT_DB  = Path.home() / "Library" / "Messages" / "chat.db"
ABOOK_DB = Path.home() / "Library" / "Application Support" / "AddressBook" / "AddressBook-v22.abcddb"

SNIPPET_DEFAULT = 2
SNIPPET_WIDTH   = 100

PENDING  = -1
REJECTED =  0
APPROVED =  1

STATUS_LABEL = {PENDING: "pending", REJECTED: "rejected", APPROVED: "approved"}

VALID_RELATIONSHIP_TYPES = frozenset({
    "client", "vendor", "builder", "trade_partner",
    "internal_team", "personal_work_related", "unknown",
})

RELATIONSHIP_CHOICES = {
    "c": "client", "v": "vendor", "b": "builder",
    "t": "trade_partner", "i": "internal_team",
    "p": "personal_work_related", "u": "unknown",
}
RELATIONSHIP_MENU = (
    "  [c] client          [v] vendor       [b] builder\n"
    "  [t] trade_partner   [i] internal     [p] personal_work_related\n"
    "  [u] unknown (default)"
)


# ── Masking ───────────────────────────────────────────────────────────────────

def _mask(handle: str) -> str:
    return handle[:3] + "***" + handle[-2:] if len(handle) > 6 else "***"


def _norm_phone(phone: str) -> str:
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


_contact_cache: dict[str, tuple[str, str]] = {}


def _lookup_contact_cached(handle: str) -> tuple[str, str]:
    """Return (name, match_type). Cached per session. match_type='exact'|'none'."""
    if handle not in _contact_cache:
        name = _lookup_contact_name(handle)
        _contact_cache[handle] = (name, "exact" if name else "none")
    return _contact_cache[handle]


def _clear_contact_cache() -> None:
    """Clear the contact cache. Exposed for tests."""
    _contact_cache.clear()


# ── Contact filter / sort ─────────────────────────────────────────────────────

def _apply_contact_filter(
    resolved: list[tuple[Any, str, str]],
    named_only: bool = False,
    unnamed_only: bool = False,
    names_first: bool = True,
) -> list[tuple[Any, str, str]]:
    """Filter and sort a list of (row, name, match_type) tuples.

    named_only   — keep only rows where name is non-empty.
    unnamed_only — keep only rows where name is empty.
    names_first  — sort named contacts first, both groups by work_confidence desc.
    When named_only or unnamed_only is active, names_first ordering is not applied.
    """
    if named_only:
        return [(r, n, m) for r, n, m in resolved if n]
    if unnamed_only:
        return [(r, n, m) for r, n, m in resolved if not n]
    if names_first:
        return sorted(resolved, key=lambda x: (0 if x[1] else 1, -x[0]["work_confidence"]))
    return list(resolved)


# ── Snippet cleaning ──────────────────────────────────────────────────────────

_NS_NOISE_RE = re.compile(
    r"streamtyped|bplist\d*|NSAttributedString|NSMutableAttributedString|"
    r"NSMutableString|NSMutableDictionary|NSDictionary|NSObject|NSString|"
    r"NSArray|NSFont|NSColor|NSParagraphStyle|NSValue|NSNumber|NSURL|"
    r"CTFont|CTParagraph|__NSCFString|__NSCFConstantString|"
    r"__kIMMessagePartAttributeName|kIMMessagePartAttributeName",
    re.IGNORECASE,
)
_JUNK_FRAG_RE = re.compile(r"\b(__\w+|iI)\b|[+&]{2,}")


def _clean_snippet(text: str, width: int = SNIPPET_WIDTH) -> str:
    """Strip decoder garbage and truncate to width characters."""
    if not text:
        return ""
    text = text.replace("ï¿¼", "").replace("ï»¿", "").replace("�", "")
    text = _NS_NOISE_RE.sub(" ", text)
    text = _JUNK_FRAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:width]


def _is_junk_snippet(text: str) -> bool:
    """Return True if the snippet is too short or mostly non-alphanumeric noise."""
    if len(text) < 5:
        return True
    return sum(1 for c in text if c.isalnum()) < 3


def _decode_attr_body(blob: bytes) -> str:
    """Extract human-readable text from an NSAttributedString binary blob."""
    if not blob:
        return ""
    try:
        raw = blob.decode("latin-1", errors="replace")
        raw = _NS_NOISE_RE.sub(" ", raw)
        cleaned = re.sub(r"[^\x20-\x7e\xa0-\xff]+", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        words = [w for w in cleaned.split() if len(w) >= 2]
        return _clean_snippet(" ".join(words).strip())
    except Exception:
        return ""


def _fetch_snippets(
    chat_guid: str,
    n: int = SNIPPET_DEFAULT,
    width: int = SNIPPET_WIDTH,
) -> list[dict]:
    """Return last n clean messages from a thread as {direction, text}."""
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
            (chat_guid, n * 3),
        ).fetchall()
        conn.close()
        for text, attr_body, is_from_me in reversed(rows):
            if len(snippets) >= n:
                break
            body = _clean_snippet((text or "").strip(), width)
            if not body and attr_body:
                body = _decode_attr_body(attr_body)
            if body and not _is_junk_snippet(body):
                snippets.append({
                    "direction": "sent" if is_from_me else "received",
                    "text": body,
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

def _count_named_unnamed(handles: list[str]) -> tuple[int, int]:
    named = sum(1 for h in handles if _lookup_contact_cached(h)[0])
    return named, len(handles) - named


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

    pending_handles = [r[0] for r in conn.execute(
        "SELECT contact_handle FROM threads WHERE category='work' AND is_reviewed=-1"
    ).fetchall()]
    pending_named, pending_unnamed = _count_named_unnamed(pending_handles)

    approved_handles = [r[0] for r in conn.execute(
        "SELECT contact_handle FROM threads WHERE is_reviewed=1"
    ).fetchall()]
    approved_named, approved_unnamed = _count_named_unnamed(approved_handles)

    pending_total = len(pending_handles)
    approved_total = len(approved_handles)
    unclassified = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE is_reviewed=1 AND "
        "coalesce(relationship_type,'unknown')='unknown'"
    ).fetchone()[0]

    print(f"\n  Pending work review : {pending_total}  (named={pending_named}  unnamed={pending_unnamed})")
    print(f"  Approved total      : {approved_total}  (named={approved_named}  unnamed={approved_unnamed})")
    if unclassified:
        print(f"  Needs relationship  : {unclassified}  (run --approved-only to assign)")
    print()


def _print_thread_safe(
    i: int,
    total: int,
    r: Any,
    name: str = "",
    match_type: str = "none",
) -> None:
    masked    = _mask(r["contact_handle"])
    codes     = json.loads(r["reason_codes"] or "[]")
    codes_str = ", ".join(codes[:3]) if codes else "(none)"
    date_rng  = f"{(r['date_first'] or '')[:10]} → {(r['date_last'] or '')[:10]}"
    is_named  = "yes" if name else "no"
    print(f"[{i}/{total}] {masked}  named={is_named}  contact_match={match_type}")
    print(f"       msgs={r['message_count']}  conf={r['work_confidence']:.2f}  {date_rng}")
    print(f"       signals: {codes_str}")


def _print_thread_full(
    i: int,
    total: int,
    r: Any,
    name: str = "",
    match_type: str = "none",
    snippets: int = SNIPPET_DEFAULT,
    show_snippets: bool = True,
) -> None:
    handle    = r["contact_handle"]
    codes     = json.loads(r["reason_codes"] or "[]")
    codes_str = ", ".join(codes[:4]) if codes else "(none)"
    date_rng  = f"{(r['date_first'] or '')[:10]} → {(r['date_last'] or '')[:10]}"

    header = f"{name} ({handle})" if name else handle
    print(f"[{i}/{total}] {header}  contact_match={match_type}")
    print(f"       msgs={r['message_count']}  conf={r['work_confidence']:.2f}  {date_rng}")
    print(f"       signals: {codes_str}")

    if show_snippets:
        snips = _fetch_snippets(r["chat_guid"], n=snippets)
        if snips:
            print("       recent:")
            for s in snips:
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
    named_only: bool = False,
    unnamed_only: bool = False,
    names_first: bool = True,
    snippets: int = SNIPPET_DEFAULT,
    show_snippets: bool = True,
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

    resolved: list[tuple[Any, str, str]] = [
        (r, *_lookup_contact_cached(r["contact_handle"])) for r in rows
    ]
    resolved = _apply_contact_filter(resolved, named_only, unnamed_only, names_first)

    if not resolved:
        print(f"\n✓ No pending {category} threads matching current filter (confidence ≥ {min_confidence}).")
        return

    mode_label = "FULL CONTEXT" if full else "SAFE (masked)"
    print(f"\n=== Review {len(resolved)} pending {category} threads  [{mode_label}] ===")
    print("  [y] approve  [n] reject  [s] skip  [q] quit\n")

    approved_count = rejected_count = skipped_count = 0

    for i, (r, name, match_type) in enumerate(resolved, 1):
        if full:
            _print_thread_full(i, len(resolved), r, name, match_type, snippets, show_snippets)
        else:
            _print_thread_safe(i, len(resolved), r, name, match_type)

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


# ── Relationship-only review ──────────────────────────────────────────────────

def run_relationship_review(
    conn: sqlite3.Connection,
    limit: int = 50,
    full: bool = False,
    named_only: bool = False,
    unnamed_only: bool = False,
    names_first: bool = True,
    snippets: int = SNIPPET_DEFAULT,
    show_snippets: bool = True,
) -> None:
    """Review approved threads with no relationship_type set. Does NOT change is_reviewed."""
    rows = conn.execute(
        "SELECT thread_id, chat_guid, contact_handle, message_count, date_first, date_last, "
        "category, work_confidence, reason_codes, is_reviewed, "
        "coalesce(relationship_type,'unknown') as relationship_type "
        "FROM threads "
        "WHERE is_reviewed = 1 AND coalesce(relationship_type,'unknown') = 'unknown' "
        "ORDER BY work_confidence DESC, date_last DESC "
        "LIMIT ?",
        (limit,),
    ).fetchall()

    resolved: list[tuple[Any, str, str]] = [
        (r, *_lookup_contact_cached(r["contact_handle"])) for r in rows
    ]
    resolved = _apply_contact_filter(resolved, named_only, unnamed_only, names_first)

    if not resolved:
        print("\n✓ No approved threads with unset relationship_type matching current filter.")
        return

    mode_label = "FULL CONTEXT" if full else "SAFE (masked)"
    print(f"\n=== Assign relationship type: {len(resolved)} approved thread(s)  [{mode_label}] ===")
    print("  Approved threads only — is_reviewed will NOT change.")
    print(f"  {RELATIONSHIP_MENU}")
    print("  [s] skip  [q] quit\n")

    classified_count = skipped_count = 0

    for i, (r, name, match_type) in enumerate(resolved, 1):
        if full:
            _print_thread_full(i, len(resolved), r, name, match_type, snippets, show_snippets)
        else:
            _print_thread_safe(i, len(resolved), r, name, match_type)

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                print(f"Session: classified={classified_count}  skipped={skipped_count}")
                return

            if choice in RELATIONSHIP_CHOICES:
                rel = RELATIONSHIP_CHOICES[choice]
                set_relationship(conn, r["thread_id"], rel)
                print(f"       → relationship_type = {rel}\n")
                classified_count += 1
                break
            elif choice in ("s", "skip", ""):
                print("       ⬜ Skipped.\n")
                skipped_count += 1
                break
            elif choice in ("q", "quit", "exit"):
                print(f"Session: classified={classified_count}  skipped={skipped_count}")
                return
            else:
                print(f"       ? Enter a type key ({', '.join(RELATIONSHIP_CHOICES)}), s, or q")

    print(f"Session: classified={classified_count}  skipped={skipped_count}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive client thread review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python3 scripts/review_client_threads.py --summary
  python3 scripts/review_client_threads.py --full --limit 10
  python3 scripts/review_client_threads.py --full --named-only
  python3 scripts/review_client_threads.py --full --unnamed-only
  python3 scripts/review_client_threads.py --full --snippets 5
  python3 scripts/review_client_threads.py --full --no-snippets
  python3 scripts/review_client_threads.py --safe --min-confidence 0.7
  python3 scripts/review_client_threads.py --full --approved-only
""",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--category", default="work")
    parser.add_argument("--summary", action="store_true",
                        help="Show counts only, skip review loop")
    parser.add_argument("--approved-only", action="store_true",
                        help="Assign relationship_type to approved threads with type='unknown'")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--safe", dest="full", action="store_false", default=False,
                      help="Masked display — safe for screen sharing (default)")
    mode.add_argument("--full", dest="full", action="store_true",
                      help="Full phone + contact name + snippets (operator only)")

    contact_filter = parser.add_mutually_exclusive_group()
    contact_filter.add_argument("--named-only", action="store_true",
                                help="Show only threads with a resolved contact name")
    contact_filter.add_argument("--unnamed-only", action="store_true",
                                help="Show only threads without a resolved contact name")
    contact_filter.add_argument("--names-first", action="store_true",
                                help="Sort named contacts first (default behavior)")

    parser.add_argument("--snippets", type=int, default=SNIPPET_DEFAULT, metavar="N",
                        help=f"Number of message snippets to show (default {SNIPPET_DEFAULT})")
    parser.add_argument("--no-snippets", action="store_true",
                        help="Hide message snippets entirely")

    args = parser.parse_args()

    named_only   = args.named_only
    unnamed_only = args.unnamed_only
    names_first  = not (named_only or unnamed_only)
    show_snippets = not args.no_snippets

    conn = _open_db()
    try:
        print_summary(conn)
        if not args.summary:
            if args.approved_only:
                run_relationship_review(
                    conn, limit=args.limit, full=args.full,
                    named_only=named_only, unnamed_only=unnamed_only,
                    names_first=names_first, snippets=args.snippets,
                    show_snippets=show_snippets,
                )
            else:
                run_review(
                    conn, limit=args.limit, min_confidence=args.min_confidence,
                    category=args.category, full=args.full,
                    named_only=named_only, unnamed_only=unnamed_only,
                    names_first=names_first, snippets=args.snippets,
                    show_snippets=show_snippets,
                )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
