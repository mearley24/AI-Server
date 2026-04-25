"""Rule impact scoring and recommendation engine.

Simulates each proposed/approved rule against historical data (cards,
cortex entries) to produce:
  - affected_events_count
  - impact_score (0–1)
  - confidence_score (0–1)
  - recommendation: approve | review | ignore
  - recommendation_reason

Usage:
  python3 scripts/evaluate_rule_impact.py --dry-run   # print scores, no writes
  python3 scripts/evaluate_rule_impact.py --apply     # write scores to promoted_rules.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── Paths ──────────────────────────────────────────────────────────────────────

_CORTEX_DATA_DIR = Path(os.environ.get("CORTEX_DATA_DIR", "/data/cortex"))
if not _CORTEX_DATA_DIR.is_dir():
    _CORTEX_DATA_DIR = REPO_ROOT / "data" / "cortex"

PROMOTED_RULES_PATH = _CORTEX_DATA_DIR / "promoted_rules.json"
CARDS_DIR = REPO_ROOT / "ops" / "self_improvement" / "cards"
CORTEX_DB = _CORTEX_DATA_DIR / "cortex.db"


# ── Card loading ───────────────────────────────────────────────────────────────

def _load_cards() -> list[dict[str, str]]:
    """Load all self-improvement cards as {name, text} dicts."""
    cards = []
    if CARDS_DIR.is_dir():
        for p in sorted(CARDS_DIR.glob("*.md")):
            try:
                cards.append({"name": p.name, "text": p.read_text(errors="replace").lower()})
            except Exception:
                pass
    return cards


def _load_cortex_entries() -> list[dict[str, Any]]:
    """Load recent cortex DB entries for simulation. Returns [] on error."""
    try:
        if not CORTEX_DB.exists():
            return []
        conn = sqlite3.connect(str(CORTEX_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, summary, details, source FROM entries ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Category derivation (mirrors self_improvement_engine._derive_category) ──────

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("reply_phrasing",      ["phrasing", "draft reply", "wording", "response style", "avoid generic", "prefer short", "self-fix before"]),
    ("triage_scoring",      ["triage", "scoring", "review value", "prioritize repeat", "deprioritize unnamed", "scoring weight"]),
    ("follow_up_threshold", ["follow-up", "follow up", "threshold", "urgency", "overdue"]),
    ("pipeline",            ["imessage", "x_intake", "bridge", "batch consolidat", "dedup", "card pipeline", "self-improvement collector"]),
]


def _derive_category(proposed_behavior: str) -> str:
    text = proposed_behavior.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return "general"


def _effective_category(rule: dict[str, Any]) -> str:
    """Return behavior_category, deriving it from proposed_behavior if absent or None."""
    cat = rule.get("behavior_category")
    if cat:
        return cat
    return _derive_category(rule.get("proposed_behavior", ""))


# ── Keyword extraction ─────────────────────────────────────────────────────────

_PIPELINE_KEYWORDS = [
    "imessage", "x.com", "x_intake", "tweet", "twitter",
    "url", "https://x.com", "https://twitter", "status/",
]
_DEDUP_KEYWORDS = [
    "batch", "dedup", "duplicate", "consolidat", "pattern", "repeated", "redundant",
]
_TRIAGE_KEYWORDS = [
    "triage", "prioritiz", "review value", "score", "rank",
]
_PHRASING_KEYWORDS = [
    "phrasing", "wording", "draft", "reply", "response style", "concise", "short",
]
_FOLLOWUP_KEYWORDS = [
    "follow-up", "follow up", "followup", "overdue", "threshold", "urgency",
]


def _extract_match_keywords(rule: dict[str, Any]) -> list[str]:
    """Return the keyword list most relevant to this rule's behavior_category."""
    category = _effective_category(rule)
    if category == "pipeline":
        return _PIPELINE_KEYWORDS
    if category == "triage_scoring":
        return _TRIAGE_KEYWORDS
    if category == "reply_phrasing":
        return _PHRASING_KEYWORDS
    if category == "follow_up_threshold":
        return _FOLLOWUP_KEYWORDS
    # general — try to match dedup keywords from text
    combined = rule.get("proposed_behavior", "").lower() + " " + rule.get("summary", "").lower()
    if any(k in combined for k in _DEDUP_KEYWORDS):
        return _DEDUP_KEYWORDS
    return []


def _count_card_matches(keywords: list[str], cards: list[dict[str, str]]) -> int:
    if not keywords:
        return 0
    return sum(1 for c in cards if any(kw in c["text"] for kw in keywords))


def _count_entry_matches(keywords: list[str], entries: list[dict[str, Any]]) -> int:
    if not keywords:
        return 0
    count = 0
    for e in entries:
        text = " ".join(str(v or "").lower() for v in [e.get("title"), e.get("summary"), e.get("details"), e.get("source")])
        if any(kw in text for kw in keywords):
            count += 1
    return count


# ── Duplicate detection ────────────────────────────────────────────────────────

def _is_duplicate(rule: dict[str, Any], all_rules: list[dict[str, Any]]) -> bool:
    """True if another approved/proposed rule has the same behavior_category and similar summary."""
    cat = _effective_category(rule)
    rid = rule.get("rule_id")
    summary_words = set(rule.get("summary", "").lower().split())
    for other in all_rules:
        if other.get("rule_id") == rid:
            continue
        if _effective_category(other) != cat:
            continue
        other_words = set(other.get("summary", "").lower().split())
        overlap = len(summary_words & other_words)
        if overlap >= 4 and len(summary_words) > 0:
            return True
    return False


# ── Core scorer ────────────────────────────────────────────────────────────────

def score_rule(
    rule: dict[str, Any],
    all_rules: list[dict[str, Any]],
    cards: list[dict[str, str]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute impact fields for a single rule."""
    category = _effective_category(rule)
    risk_level = rule.get("risk_level", "medium")
    card_count = rule.get("card_count", 0)
    scoring = rule.get("scoring") or {}
    relevance = scoring.get("relevance", 2)
    actionability = scoring.get("actionability", 1)

    keywords = _extract_match_keywords(rule)
    card_hits = _count_card_matches(keywords, cards)
    entry_hits = _count_entry_matches(keywords, entries)
    affected_events = card_hits + min(entry_hits, 20)

    is_dup = _is_duplicate(rule, all_rules)
    is_unclassified = category == "general"

    # ── Impact score ──────────────────────────────────────────────────────────
    # Base: relevance × actionability / 25 (max 5×5)
    base_impact = (relevance * actionability) / 25.0

    # Scale by event coverage (card hits / total cards)
    total_cards = len(cards) if cards else 1
    event_coverage = min(1.0, card_hits / max(total_cards * 0.15, 1))
    impact_score = base_impact * 0.5 + event_coverage * 0.5

    if is_unclassified:
        impact_score *= 0.25
    if is_dup:
        impact_score *= 0.3
    if not keywords:
        impact_score *= 0.2
    impact_score = round(min(1.0, max(0.0, impact_score)), 3)

    # ── Confidence score ──────────────────────────────────────────────────────
    # Based on card_count, event consistency, clarity
    confidence_score = min(1.0, card_count / 8.0) * 0.6
    if card_hits >= 3:
        confidence_score += 0.2
    if entry_hits >= 5:
        confidence_score += 0.1
    if is_unclassified:
        confidence_score *= 0.35
    if not keywords:
        confidence_score *= 0.3
    confidence_score = round(min(1.0, max(0.0, confidence_score)), 3)

    # ── Recommendation ────────────────────────────────────────────────────────
    if is_dup:
        recommendation = "ignore"
        reason = "Duplicate — another rule covers the same behavior category and pattern."
    elif risk_level == "high":
        recommendation = "review"
        reason = "High risk — manual approval required. Impact looks " + (
            "strong" if impact_score > 0.5 else "moderate"
        ) + f" ({affected_events} affected events)."
    elif is_unclassified:
        recommendation = "ignore"
        reason = "Unclassified — no actionable behavior pattern detected. Manual review needed."
    elif impact_score > 0.6 and confidence_score > 0.6:
        recommendation = "approve"
        reason = (
            f"Strong signal: {affected_events} affected events, "
            f"impact {impact_score:.2f}, confidence {confidence_score:.2f}. "
            f"Low risk and clear behavior pattern."
        )
    elif impact_score > 0.35 or confidence_score > 0.4:
        recommendation = "review"
        reason = (
            f"Moderate signal: {affected_events} affected events. "
            "Worth reviewing but evidence is not yet conclusive."
        )
    else:
        recommendation = "ignore"
        reason = f"Low impact ({impact_score:.2f}) and confidence ({confidence_score:.2f}). Not worth activating."

    return {
        "impact_events": affected_events,
        "impact_score": impact_score,
        "confidence_score": confidence_score,
        "recommendation": recommendation,
        "recommendation_reason": reason,
        "impact_scored_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main(apply: bool = False, dry_run: bool = False) -> list[dict[str, Any]]:
    if not PROMOTED_RULES_PATH.exists():
        print(f"[ERROR] promoted_rules.json not found at {PROMOTED_RULES_PATH}")
        sys.exit(1)

    data = json.loads(PROMOTED_RULES_PATH.read_text())
    rules = data.get("rules", [])

    cards = _load_cards()
    entries = _load_cortex_entries()

    print(f"[INFO] Loaded {len(rules)} rules, {len(cards)} cards, {len(entries)} cortex entries")

    results = []
    for rule in rules:
        rid = rule.get("rule_id", "?")
        scores = score_rule(rule, rules, cards, entries)
        results.append({"rule_id": rid, **scores})

        print(
            f"\n--- {rid} ---"
            f"\n  status:        {rule.get('status')}"
            f"\n  risk:          {rule.get('risk_level')}"
            f"\n  category:      {rule.get('behavior_category')}"
            f"\n  affected:      {scores['impact_events']} events"
            f"\n  impact_score:  {scores['impact_score']}"
            f"\n  confidence:    {scores['confidence_score']}"
            f"\n  recommendation:{scores['recommendation']}"
            f"\n  reason:        {scores['recommendation_reason']}"
        )

        if not dry_run and apply:
            rule.update(scores)

    if apply and not dry_run:
        tmp = PROMOTED_RULES_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, PROMOTED_RULES_PATH)
        print(f"\n[APPLIED] Wrote impact scores to {PROMOTED_RULES_PATH}")
    elif dry_run:
        print("\n[DRY-RUN] No changes written.")
    else:
        print("\n[INFO] Pass --apply to write scores to promoted_rules.json")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate self-improvement rule impact")
    parser.add_argument("--apply", action="store_true", help="Write scores to promoted_rules.json")
    parser.add_argument("--dry-run", action="store_true", help="Print scores without writing")
    args = parser.parse_args()
    main(apply=args.apply, dry_run=args.dry_run)
