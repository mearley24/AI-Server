#!/usr/bin/env python3
"""
Client Intelligence Fact Quality Auditor.

Inspects accepted facts in proposed_facts.sqlite and reclassifies low-quality
ones.  Never deletes rows.

Usage:
    python3 scripts/audit_client_facts.py           # dry-run (default)
    python3 scripts/audit_client_facts.py --dry-run
    python3 scripts/audit_client_facts.py --apply

Classification:
  invalid  -> is_rejected=1, is_accepted=0   (clearly bad, should not be used)
  weak     -> is_rejected=0, is_accepted=0   (reset to pending for human review)
  valid    -> unchanged

Validation rules
----------------
Always valid (equipment / system / product names):
  Sonos, WiFi, network, Control4, Lutron, etc.
  Short equipment/system names pass even if < 4 useful words.

Invalid – request facts:
  • Ends with an incomplete fragment: "and need", "as am", "with the", "to the"
  • Contains speech-fragment patterns: "give me call", "as am trying", "as soon as you can"
  • Contains decoder artifacts: "+E", "+J", "iI", "lI", control characters
  • Longer than 15 words (raw transcript, not a description)

Invalid – follow_up facts:
  • Standalone generic phrases that provide no action value:
    "let me know", "ok", "sure", "yes", "got it", "will do", "thanks", etc.
  • Decoder artifacts

Invalid – issue facts:
  • Single-word overly generic terms: "problem", "issue", "trouble", "error"
  • Decoder artifacts

All types:
  • Empty or whitespace-only value

TODO: extract validate_fact() into a shared cortex/client_intel_quality.py
      module so extract_relationship_profiles.py and the approval endpoint
      can use the same validator.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "client_intel" / "proposed_facts.sqlite"

# ── Pattern constants ─────────────────────────────────────────────────────────

# Equipment / system names that are always valid regardless of word count
_EQUIPMENT_NAMES_RE = re.compile(
    r"^(sonos|lutron|control4|vantage|araknis|wattbox|episode|triad|pakedge|snapav|"
    r"wifi|wi-fi|wi\s*fi|network|theater|alarm|camera|shade|keypad|dimmer|"
    r"lighting|audio|rack|prewire)$",
    re.I,
)

# Decoder artifacts from iMessage NSAttributedString blobs
_DECODER_ARTIFACT_RE = re.compile(
    r"\b(iI|lI|Il|Ii|oO|O0|0O|l1|1l)\b"   # impossible mixed-case tokens
    r"|\+[A-Z~#]"                            # size-byte prefixes (+E, +J, +3 …)
    r"|[^\x20-\x7e\xa0-\xff]{2,}",           # non-printable sequences
)

# Trailing fragment patterns that indicate a captured request is incomplete
_TRAILING_FRAGMENT_RE = re.compile(
    r"(\band\s+need\s*$"
    r"|\bas\s+am\s*$"
    r"|\bwith\s+the\s*$"
    r"|\bto\s+the\s*$"
    r"|\band\s+also\s*$"
    r"|\bor\s+the\s*$)",
    re.I,
)

# Speech-transcript patterns — strings the client said TO Bob, not about an issue
_SPEECH_FRAGMENT_RE = re.compile(
    r"\bgive\s+me\s+call\b"
    r"|\bcall\s+me\s+back\b"
    r"|\bas\s+am\s+trying\b"
    r"|\bam\s+trying\s+to\b"
    r"|\bas\s+soon\s+as\s+you\s+can\b"
    r"|\bneed\s+to\s+reach\b",
    re.I,
)

# Generic follow-up phrases that add no actionable value
_GENERIC_FOLLOW_UP = frozenset({
    "let me know", "lmk",
    "ok", "okay", "k", "ok thanks",
    "sure", "sounds good", "sounds great",
    "yes", "yep", "yeah", "yup",
    "no problem", "np", "no worries",
    "got it", "got that", "understood",
    "will do", "on it",
    "thanks", "thank you", "thx",
    "perfect", "great", "awesome",
    "noted",
})

# Issue words too generic to be useful on their own
_GENERIC_ISSUE_WORDS = frozenset({
    "problem", "issue", "trouble", "error",
    "fail", "failed", "bad", "wrong",
})

_USEFUL_WORD_RE = re.compile(r"[A-Za-z]{3,}")


# ── Core validator ────────────────────────────────────────────────────────────

def validate_fact(fact_type: str, fact_value: str) -> tuple[str, str]:
    """Check one fact.  Returns (verdict, reason).

    verdict:
      "valid"   – passes quality bar, keep accepted
      "invalid" – clearly bad; mark rejected
      "weak"    – marginal; reset to pending for human review
    """
    v = fact_value.strip()

    # Empty is always invalid
    if not v:
        return "invalid", "empty value"

    # ── Equipment / system / product ─────────────────────────────────────────
    if fact_type in ("equipment", "product", "system"):
        if _DECODER_ARTIFACT_RE.search(v):
            return "invalid", "decoder artifact"
        return "valid", ""

    # ── Request ──────────────────────────────────────────────────────────────
    if fact_type == "request":
        if _DECODER_ARTIFACT_RE.search(v):
            return "invalid", "decoder artifact"
        if _TRAILING_FRAGMENT_RE.search(v):
            return "invalid", "trailing incomplete fragment"
        if _SPEECH_FRAGMENT_RE.search(v):
            return "invalid", "speech/transcript fragment"
        if len(v.split()) > 15:
            return "invalid", f"too long ({len(v.split())} words) — raw transcript"
        if len(_USEFUL_WORD_RE.findall(v)) < 4:
            return "weak", "fewer than 4 useful words"
        return "valid", ""

    # ── Follow-up ─────────────────────────────────────────────────────────────
    if fact_type == "follow_up":
        if _DECODER_ARTIFACT_RE.search(v):
            return "invalid", "decoder artifact"
        normalised = re.sub(r"[.,!?;:\s]+$", "", v).strip().lower()
        if normalised in _GENERIC_FOLLOW_UP:
            return "invalid", f"generic/non-actionable: '{normalised}'"
        if len(_USEFUL_WORD_RE.findall(v)) < 3:
            return "weak", "fewer than 3 useful words"
        return "valid", ""

    # ── Issue ─────────────────────────────────────────────────────────────────
    if fact_type == "issue":
        if _DECODER_ARTIFACT_RE.search(v):
            return "invalid", "decoder artifact"
        if v.lower().strip(".,!? ") in _GENERIC_ISSUE_WORDS:
            return "invalid", f"too generic: '{v}'"
        return "valid", ""

    # ── All other types ───────────────────────────────────────────────────────
    if _DECODER_ARTIFACT_RE.search(v):
        return "invalid", "decoder artifact"
    if len(_USEFUL_WORD_RE.findall(v)) < 2:
        return "weak", "fewer than 2 useful words"
    return "valid", ""


# ── Audit runner ──────────────────────────────────────────────────────────────

def audit(db_path: Path, apply: bool = False) -> list[dict]:
    """Read accepted facts, classify each, optionally write changes.

    Returns list of result dicts for reporting / testing.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT fact_id, profile_id, fact_type, fact_value, confidence, "
        "source_timestamp "
        "FROM proposed_facts "
        "WHERE is_accepted=1 AND is_rejected=0 "
        "ORDER BY fact_type, fact_value"
    ).fetchall()

    results: list[dict] = []
    for r in rows:
        verdict, reason = validate_fact(r["fact_type"], r["fact_value"])
        results.append({
            "fact_id":    r["fact_id"],
            "fact_type":  r["fact_type"],
            "fact_value": r["fact_value"],
            "confidence": r["confidence"],
            "verdict":    verdict,
            "reason":     reason,
        })

    mode = "APPLY" if apply else "DRY-RUN"
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\n=== audit_client_facts — {mode}  {ts} ===")
    print(f"  Accepted facts reviewed : {len(results)}")

    n_valid   = sum(1 for r in results if r["verdict"] == "valid")
    n_invalid = sum(1 for r in results if r["verdict"] == "invalid")
    n_weak    = sum(1 for r in results if r["verdict"] == "weak")
    print(f"  valid   : {n_valid}")
    print(f"  invalid : {n_invalid}  → will mark rejected")
    print(f"  weak    : {n_weak}     → will reset to pending")
    print()

    for r in results:
        tag = {
            "valid":   "✓ KEEP   ",
            "invalid": "✗ REJECT ",
            "weak":    "~ PENDING",
        }[r["verdict"]]
        print(f"  {tag}  [{r['fact_type']:12s}]  conf={r['confidence']:.2f}"
              f"  {r['fact_value']!r:.60s}")
        if r["reason"]:
            print(f"           reason: {r['reason']}")

    if apply and (n_invalid + n_weak) > 0:
        print()
        applied_reject = applied_weak = 0
        for r in results:
            if r["verdict"] == "invalid":
                conn.execute(
                    "UPDATE proposed_facts SET is_accepted=0, is_rejected=1 WHERE fact_id=?",
                    (r["fact_id"],),
                )
                applied_reject += 1
            elif r["verdict"] == "weak":
                conn.execute(
                    "UPDATE proposed_facts SET is_accepted=0, is_rejected=0 WHERE fact_id=?",
                    (r["fact_id"],),
                )
                applied_weak += 1
        conn.commit()
        print(f"  Applied: {applied_reject} rejected, {applied_weak} reset to pending")
    elif not apply and (n_invalid + n_weak) > 0:
        print(f"  Dry-run only — re-run with --apply to write changes")

    conn.close()
    print()
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Audit accepted Client Intelligence facts")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                   help="Show what would change (default)")
    g.add_argument("--apply",   dest="apply",   action="store_true", default=False,
                   help="Write reclassifications to DB")
    p.add_argument("--db", default=str(DEFAULT_DB), help="Path to proposed_facts.sqlite")
    args = p.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"ERROR: DB not found: {db}")
        raise SystemExit(1)

    audit(db, apply=args.apply)


if __name__ == "__main__":
    main()
