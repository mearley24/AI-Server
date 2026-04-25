#!/usr/bin/env python3
"""
Matt Reply Style Extractor v1.

Reads Matt's outgoing messages from chat.db for approved work threads,
extracts style patterns, and writes data/client_intel/reply_style.json.

Only processes:
  - is_from_me=1 (Matt's sent messages, not the client's)
  - threads with is_reviewed=1 and relationship_type in
    {client, builder, vendor, trade_partner}

Does NOT process:
  - internal_team (irrelevant for client-facing replies)
  - personal_work_related (different tone expectations)
  - unknown (no relationship signal)

Does NOT store full message bodies — extracts patterns and phrase statistics.
No raw phone numbers in output.

Usage:
  python3 scripts/extract_reply_style.py            # generate + save profile
  python3 scripts/extract_reply_style.py --sample   # print analysis + examples
  python3 scripts/extract_reply_style.py --dry-run  # analyse without saving
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
THREAD_DB   = REPO_ROOT / "data" / "client_intel" / "message_thread_index.sqlite"
CHAT_DB     = Path.home() / "Library" / "Messages" / "chat.db"
STYLE_OUT   = REPO_ROOT / "data" / "client_intel" / "reply_style.json"

ALLOWED_REL_TYPES = frozenset({"client", "builder", "vendor", "trade_partner"})
APPLE_EPOCH = 978_307_200   # seconds between Unix epoch and Apple epoch (Jan 1 2001)

# ── Text cleaning ─────────────────────────────────────────────────────────────

_DECODE_NS_RE = re.compile(
    r"streamtyped|bplist\d*|NSAttributedString|NSMutableAttributedString|"
    r"NSMutableString|NSMutableDictionary|NSDictionary|NSObject|NSString|"
    r"NSArray|NSFont|NSColor|NSParagraphStyle|NSValue|NSNumber|NSURL|"
    r"CTFont|CTParagraph|__NSCFString|__kIM\w+|kIM\w+",
    re.I,
)
# Binary metadata keywords that only appear in blob garbage (case-sensitive).
_BINARY_META_RE = re.compile(
    r"NSMutableData|NSKeyedArchiver|X\$version|Y\$archiver|U\$null"
    r"|_NS\.rangeval|NS\.rangeval|Z\$classname|X\$classes"
    r"|\bNSMutable\w+\b|\bNSData\b|\bNSArray\b|\bNSString\b"
    r"|\b[A-Z_]{5,}\b"      # all-caps token ≥5 chars (class names, not normal words)
    r"|\w{25,}",             # impossibly long tokens from binary garbage
)
_LEADING_SIZE_BYTE_RE = re.compile(r"^\+[A-Z~#$&/*^!;\"'\-\d]\s*")
_TRAILING_DECODER_RE  = re.compile(r"\s*\biI\b.*$", re.DOTALL)


def _decode_attr(blob: bytes) -> str:
    """Decode NSAttributedString blob to plain text."""
    try:
        raw = blob.decode("latin-1", errors="replace")
        raw = _DECODE_NS_RE.sub(" ", raw)
        cleaned = re.sub(r"[^\x20-\x7e\xa0-\xff]+", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        words = [w for w in cleaned.split() if len(w) >= 2]
        result = " ".join(words)
        return result[:300] if len(result) > 4 else ""
    except Exception:
        return ""


def _clean_message(text: str) -> str:
    """Strip decoder artifacts, binary metadata, and normalise whitespace."""
    # Remove binary metadata blocks
    text = _BINARY_META_RE.sub(" ", text)
    # Strip leading iMessage size bytes (+E, +3, +K …)
    text = _LEADING_SIZE_BYTE_RE.sub("", text)
    # Strip trailing 'iI' decoder artifact and everything after it
    text = _TRAILING_DECODER_RE.sub("", text)
    # Collapse whitespace
    text = " ".join(text.split())
    # Reject if mostly non-ASCII (binary remnants)
    if text and sum(1 for c in text if ord(c) > 127) / len(text) > 0.15:
        return ""
    return text.strip()


def _is_usable(text: str) -> bool:
    """Return True if cleaned message is usable for style learning."""
    if not text or len(text) < 3:
        return False
    words = text.split()
    if len(words) < 2:
        return False
    # Skip messages that look like phone numbers, URLs, or pure codes
    if re.match(r"^[\d\s+\-().]+$", text):
        return False
    if re.search(r"https?://|www\.", text, re.I):
        return False
    # Skip automated/templated content
    if "This is Matt Earley" in text or "High Mountain Home Tech" in text:
        return False
    return True


# ── Data fetching ─────────────────────────────────────────────────────────────

def _approved_work_threads() -> list[dict]:
    """Return approved threads with allowed relationship types."""
    if not THREAD_DB.is_file():
        return []
    conn = sqlite3.connect(f"file:{THREAD_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT thread_id, chat_guid, relationship_type "
        "FROM threads "
        "WHERE is_reviewed=1 "
        "  AND relationship_type IN ('client','builder','vendor','trade_partner')"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fetch_sent_messages(chat_guid: str, limit: int = 100) -> list[str]:
    """Return Matt's outgoing messages for a chat guid (cleaned text only)."""
    if not CHAT_DB.is_file():
        return []
    messages: list[str] = []
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro&immutable=1", uri=True)
        rows = conn.execute(
            "SELECT m.text, m.attributedBody "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE c.guid = ? "
            "  AND m.is_from_me = 1 "
            "  AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL) "
            "  AND m.date > 0 "
            "ORDER BY m.date DESC LIMIT ?",
            (chat_guid, limit),
        ).fetchall()
        conn.close()
        for text, attr_body in rows:
            raw = (text or "").strip()
            if not raw and attr_body:
                raw = _decode_attr(bytes(attr_body))
            cleaned = _clean_message(raw)
            if _is_usable(cleaned):
                messages.append(cleaned)
    except Exception:
        pass
    return messages


# ── Pattern extraction ────────────────────────────────────────────────────────

_GREETING_RE = re.compile(
    r"^(alrighty|yeah|yep|sure|perfect|all good|no worries|no biggie|"
    r"got it|on it|sounds good|absolutely|definitely|of course|hey|hi)\b",
    re.I,
)
_ACK_PHRASES = [
    "no biggie", "all good", "sure, no problem", "no worries", "perfect",
    "sounds good", "got it", "makes sense",
]
_SCHEDULING_RE = re.compile(
    r"\b(swing by|swing up|come by|stop by|drop by|give me call|"
    r"what time|what times|when are you|when do you|i can be|i can stop)\b",
    re.I,
)
_CLOSE_RE = re.compile(
    r"\b(let me know|thank you|thanks again|talk soon|take care|"
    r"have a good|enjoy your|no worries|appreciate)\b",
    re.I,
)


def _extract_ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i:i+n]) for i in range(len(words) - n + 1)]


def extract_patterns(all_messages: list[str]) -> dict:
    """Build a style profile from a list of cleaned sent messages."""
    greeting_counts: Counter = Counter()
    ack_counts:      Counter = Counter()
    scheduling:      Counter = Counter()
    closing:         Counter = Counter()
    phrase_counts:   Counter = Counter()

    total_words = 0
    total_sentences = 0
    contraction_count = 0
    double_excl_count = 0

    for msg in all_messages:
        words = msg.lower().split()
        total_words += len(words)
        # Sentences: split on . ! ?
        sentences = [s.strip() for s in re.split(r"[.!?]+", msg) if s.strip()]
        total_sentences += max(1, len(sentences))

        if re.search(r"!!", msg):
            double_excl_count += 1
        if re.search(r"\b(i'm|i'll|i've|i'd|can't|won't|don't|it's|you're|that's|he's|she's|they're|we're|isn't|wasn't|couldn't)\b", msg, re.I):
            contraction_count += 1

        # Greeting / opener
        m = _GREETING_RE.match(msg)
        if m:
            greeting_counts[m.group(1).lower()] += 1

        # Acknowledgment phrases
        for phrase in _ACK_PHRASES:
            if phrase in msg.lower():
                ack_counts[phrase] += 1

        # Scheduling
        for m2 in _SCHEDULING_RE.finditer(msg):
            scheduling[m2.group(1).lower()] += 1

        # Closing
        for m3 in _CLOSE_RE.finditer(msg):
            closing[m3.group(1).lower()] += 1

        # Bigrams and trigrams for common phrases
        for n in (2, 3):
            for gram in _extract_ngrams(words, n):
                if not re.search(r"[^a-z' ]", gram):  # only clean text
                    phrase_counts[gram] += 1

    n = len(all_messages)
    avg_words = round(total_words / n, 1) if n else 0
    avg_sentences = round(total_sentences / n, 1) if n else 0
    double_excl_rate = round(double_excl_count / n, 2) if n else 0
    contraction_rate = round(contraction_count / n, 2) if n else 0

    # Top bigrams/trigrams that appear ≥2 times and aren't noise
    top_phrases = [
        {"phrase": phrase, "frequency": count}
        for phrase, count in phrase_counts.most_common(30)
        if count >= 2 and len(phrase.split()) >= 2
    ]

    return {
        "greeting_patterns": [
            {"phrase": p, "frequency": c}
            for p, c in greeting_counts.most_common(10)
        ],
        "acknowledgment_patterns": [
            {"phrase": p, "frequency": c}
            for p, c in ack_counts.most_common(10)
            if c >= 1
        ],
        "scheduling_language": [
            {"phrase": p, "frequency": c}
            for p, c in scheduling.most_common(10)
        ],
        "closing_patterns": [
            {"phrase": p, "frequency": c}
            for p, c in closing.most_common(10)
        ],
        "common_phrases": top_phrases[:15],
        "tone": {
            "avg_message_length_words": avg_words,
            "avg_sentence_count":       avg_sentences,
            "double_exclamation_rate":  double_excl_rate,
            "contraction_rate":         contraction_rate,
            "casual_words": ["alrighty", "no biggie", "swing by", "yeah", "yep"],
            "style_notes": [
                "Short, direct messages preferred",
                "Uses 'Alrighty' as distinctive opener",
                "Rarely uses formal phrasing",
                "'No biggie' to minimise client concern",
                "Action-oriented: 'I'll swing by', 'give me a call'",
            ],
        },
        # Phrases Matt never uses — used by style engine to flag/remove
        "robotic_phrases": [
            "I wanted to follow up on your request",
            "thank you for reaching out",
            "please don't hesitate to contact me",
            "don't hesitate to reach out",
            "I hope this finds you well",
            "I'll get back to you at my earliest convenience",
            "as per our conversation",
            "going forward",
            "at your earliest convenience",
            "please feel free to",
            "I look forward to hearing from you",
            "let me know if you have any questions",
            "I appreciate your patience",
            "I apologize for any inconvenience",
        ],
        # Direct replacements — robotic → natural
        "replacements": [
            {"from": "I'll get back to you shortly",
             "to":   "I'll let you know"},
            {"from": "get back to you with what I find",
             "to":   "let you know what I find"},
            {"from": "I'll reach out once I have an update",
             "to":   "I'll let you know"},
            {"from": "Give me a few minutes and I'll let you know what I find",
             "to":   "Give me a bit and I'll let you know"},
            {"from": "let me know what I find",
             "to":   "let you know"},
            {"from": "I'll take a look and let you know what I find",
             "to":   "I'll check on it and let you know"},
        ],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, sample: bool = False) -> dict:
    threads = _approved_work_threads()
    if not threads:
        print("No approved work threads found in thread index.")
        return {}

    all_messages: list[str] = []
    thread_stats: list[dict] = []
    for t in threads:
        msgs = _fetch_sent_messages(t["chat_guid"])
        all_messages.extend(msgs)
        thread_stats.append({
            "relationship_type": t["relationship_type"],
            "message_count": len(msgs),
        })

    print(f"\n=== extract_reply_style — {'DRY-RUN' if dry_run else 'APPLY'} ===")
    print(f"  Threads analysed   : {len(threads)}")
    for ts in thread_stats:
        print(f"    {ts['relationship_type']:15s}  {ts['message_count']} sent messages")
    print(f"  Total sent messages: {len(all_messages)}")
    print()

    if not all_messages:
        print("  No usable sent messages found (chat.db unavailable or empty).")
        return {}

    patterns = extract_patterns(all_messages)

    profile = {
        "version":                   "1.0",
        "extracted_at":              datetime.now(timezone.utc).isoformat(),
        "message_count":             len(all_messages),
        "thread_count":              len(threads),
        "allowed_relationship_types": sorted(ALLOWED_REL_TYPES),
        **patterns,
    }

    if sample:
        print("  Top common phrases:")
        for p in profile["common_phrases"][:8]:
            print(f"    [{p['frequency']:2d}x]  {p['phrase']}")
        print()
        print("  Greeting patterns:")
        for p in profile["greeting_patterns"][:5]:
            print(f"    [{p['frequency']:2d}x]  {p['phrase']}")
        print()
        print("  Tone:")
        t = profile["tone"]
        print(f"    avg message length : {t['avg_message_length_words']} words")
        print(f"    avg sentences      : {t['avg_sentence_count']}")
        print(f"    contraction rate   : {t['contraction_rate']}")
        print(f"    double !! rate     : {t['double_exclamation_rate']}")
        print()
        print("  Example transformations (current drafts → styled):")
        from pathlib import Path as _P
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT))
        try:
            from cortex.style_engine import apply_style
            examples = [
                "Thanks for the heads up — I'll take a look and get back to you shortly.",
                "I'll take a look at your Sonos and let you know what I find.",
                "Got it — I'll take a look and get back to you with what I find.",
                "I'll reach out once I have an update.",
            ]
            for draft in examples:
                styled, applied, conf = apply_style(draft)
                marker = "→" if applied else "="
                print(f"    BEFORE: {draft}")
                print(f"    AFTER   {marker}: {styled}  (conf={conf:.2f})")
                print()
        except ImportError:
            print("    (style_engine not yet available — run after creating cortex/style_engine.py)")

    if not dry_run:
        STYLE_OUT.parent.mkdir(parents=True, exist_ok=True)
        STYLE_OUT.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
        print(f"  Profile written to: {STYLE_OUT.relative_to(REPO_ROOT)}")
    else:
        print("  Dry-run: profile NOT written.")

    print()
    return profile


def main() -> None:
    p = argparse.ArgumentParser(description="Extract Matt reply style from chat history")
    p.add_argument("--sample",   action="store_true", help="Print analysis + example transformations")
    p.add_argument("--dry-run",  action="store_true", help="Analyse without writing profile")
    args = p.parse_args()
    run(dry_run=args.dry_run, sample=args.sample)


if __name__ == "__main__":
    main()
