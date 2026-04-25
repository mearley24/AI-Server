"""promote_self_improvement_cards.py — Self-improvement card promotion workflow.

Scans ops/self_improvement/cards/, groups cards by pattern, scores each group,
and generates proposed automation rules.

Usage:
    python3 scripts/promote_self_improvement_cards.py --dry-run
    python3 scripts/promote_self_improvement_cards.py --apply
    python3 scripts/promote_self_improvement_cards.py --stats
    python3 scripts/promote_self_improvement_cards.py --cards-dir PATH --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Repo root and default paths ──────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARDS_DIR = REPO_ROOT / "ops" / "self_improvement" / "cards"
PROMOTED_RULES_MD = REPO_ROOT / "ops" / "self_improvement" / "promoted_rules.md"
PROMOTED_RULES_JSON = REPO_ROOT / "data" / "cortex" / "promoted_rules.json"

# ── Pattern definitions ───────────────────────────────────────────────────────

PATTERNS = {
    "imessage_x_intake_bridge": {
        "summary": (
            "Route X.com URLs received via iMessage to the x_intake pipeline automatically."
        ),
        "proposed_behavior": (
            "When the self-improvement collector detects an X.com URL in an iMessage "
            "(`handle=+19705193013 is_from_me=0`), submit it to the x_intake ingest "
            "endpoint instead of writing a standalone card. This closes the gap between "
            "URL capture and content analysis."
        ),
        "relevance": 4,
    },
    "batch_card_consolidation": {
        "summary": (
            "Add pattern deduplication and batch consolidation to the self-improvement "
            "card pipeline to reduce redundant individual cards for identical patterns."
        ),
        "proposed_behavior": (
            "Extend the self-improvement collector to detect repeated URL-pattern cards "
            "within the same processing window, consolidate them into a single batch card, "
            "and emit one improvement proposal instead of N identical ones. Reduces card "
            "generation overhead and improves signal-to-noise ratio."
        ),
        "relevance": 5,
    },
    "unclassified": {
        "summary": "Unclassified improvement cards not matching a known automation pattern.",
        "proposed_behavior": (
            "Manual review required. No automated rule can be generated for this group "
            "without additional context."
        ),
        "relevance": 2,
    },
}


# ── Card parser ───────────────────────────────────────────────────────────────

def _extract_section(text: str, heading: str) -> str:
    """Return first non-empty line(s) of content after a markdown heading."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    lines = text.splitlines()
    in_section = False
    result_lines: list[str] = []
    for line in lines:
        if re.match(pattern, line.strip()):
            in_section = True
            continue
        if in_section:
            # Next heading ends the section
            if line.startswith("##"):
                break
            stripped = line.strip()
            if stripped:
                result_lines.append(stripped)
    return "\n".join(result_lines)


def parse_card(path: Path) -> dict[str, Any]:
    """Parse a single improvement card .md file into a structured dict."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # title
    title = ""
    for line in lines:
        if line.startswith("# Improvement card"):
            title = line.replace("# Improvement card —", "").replace("# Improvement card-", "").strip()
            if title.startswith("—"):
                title = title[1:].strip()
            break

    # status
    status = ""
    m = re.search(r"\*\*Status:\*\*\s*(.+)", text)
    if m:
        status = m.group(1).strip()

    # source_url
    source_url = ""
    m = re.search(r"\*\*Original URL:\*\*\s*(.+)", text)
    if m:
        source_url = m.group(1).strip()

    # impact / effort / risk
    def _int_field(label: str) -> int:
        m = re.search(rf"-\s+{label}:\s+(\d+)", text, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    impact = _int_field("Impact")
    effort = _int_field("Effort")
    risk   = _int_field("Risk")

    # affected_subsystem
    affected_subsystem = _extract_section(text, "Affected subsystem")

    # automation_hypothesis (first 200 chars)
    automation_hypothesis = _extract_section(text, "Automation hypothesis")[:200]

    # safe_next_prompt
    safe_next_prompt_raw = _extract_section(text, "Safe next prompt")
    safe_next_prompt = "" if safe_next_prompt_raw.lower().startswith("not drafted") else safe_next_prompt_raw

    # can_auto_run
    can_auto_run_raw = _extract_section(text, "Can this be auto-run?")
    can_auto_run = can_auto_run_raw.lower().startswith("yes")

    return {
        "filename": path.name,
        "title": title,
        "status": status,
        "source_url": source_url,
        "impact": impact,
        "effort": effort,
        "risk": risk,
        "affected_subsystem": affected_subsystem,
        "automation_hypothesis": automation_hypothesis,
        "safe_next_prompt": safe_next_prompt,
        "can_auto_run": can_auto_run,
    }


# ── Pattern classifier ────────────────────────────────────────────────────────

def classify_card(card: dict[str, Any]) -> str:
    """Return pattern name for a card."""
    fname = card["filename"].lower()
    hyp = card["automation_hypothesis"].lower()
    status = card["status"].lower()

    # batch_card_consolidation: filename contains batch, consolidated, or urls-pattern
    if any(kw in fname for kw in ("batch", "consolidated", "urls-pattern")):
        return "batch_card_consolidation"

    # imessage_x_intake_bridge: status is "needs fetch" AND hypothesis mentions imessage AND x_intake/intake
    if (
        "needs fetch" in status
        and ("imessage" in hyp or "imessage" in hyp)
        and ("x_intake" in hyp or "intake" in hyp)
    ):
        return "imessage_x_intake_bridge"

    return "unclassified"


# ── Scorer ────────────────────────────────────────────────────────────────────

def score_group(pattern: str, cards: list[dict[str, Any]]) -> dict[str, int]:
    """Return relevance, actionability, safety scores for a card group."""
    relevance = PATTERNS[pattern]["relevance"]

    # actionability
    has_auto = any(c["can_auto_run"] for c in cards)
    has_prompt = any(c["safe_next_prompt"] for c in cards)
    if has_auto or has_prompt:
        actionability = 4
    elif all(c["status"] == "needs fetch" for c in cards):
        actionability = 1
    else:
        actionability = 2

    # safety (invert risk)
    risks = [c["risk"] for c in cards if c["risk"] > 0]
    min_risk = min(risks) if risks else 1
    max_risk = max(risks) if risks else 1
    if max_risk >= 4:
        safety = 2
    elif min_risk <= 2:
        safety = 4
    else:
        safety = 3

    return {"relevance": relevance, "actionability": actionability, "safety": safety}


# ── Rule ID generation ────────────────────────────────────────────────────────

def _pattern_hash(pattern: str) -> str:
    """Stable 6-char hex hash of the pattern name."""
    return hashlib.md5(pattern.encode()).hexdigest()[:6]


def make_rule_id(pattern: str, today: str | None = None) -> str:
    """Return a stable rule ID like RULE-20260425-a1b2c3."""
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"RULE-{today}-{_pattern_hash(pattern)}"


# ── Risk level determination ──────────────────────────────────────────────────

def risk_level_for_group(cards: list[dict[str, Any]], scoring: dict[str, int]) -> str:
    """Determine risk_level string."""
    risks = [c["risk"] for c in cards if c["risk"] > 0]
    max_risk = max(risks) if risks else 0
    if max_risk >= 4 or scoring["safety"] <= 2:
        return "high"
    elif max_risk <= 2 and scoring["safety"] >= 4:
        return "low"
    else:
        return "medium"


# ── Main scan function ────────────────────────────────────────────────────────

def scan_cards(cards_dir: Path) -> list[dict[str, Any]]:
    """Scan cards_dir (not inbox/archive) and return list of parsed card dicts."""
    if not cards_dir.is_dir():
        print(f"ERROR: cards directory does not exist: {cards_dir}", file=sys.stderr)
        sys.exit(1)
    card_files = sorted(cards_dir.glob("*.md"))
    return [parse_card(f) for f in card_files]


def group_cards(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group cards by pattern name."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        pattern = classify_card(card)
        groups.setdefault(pattern, []).append(card)
    return groups


def build_rules(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Generate one rule per pattern group (if group size >= 1)."""
    rules: list[dict[str, Any]] = []
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Consistent ordering
    pattern_order = ["imessage_x_intake_bridge", "batch_card_consolidation", "unclassified"]
    for pattern in pattern_order:
        if pattern not in groups:
            continue
        cards = groups[pattern]
        if not cards:
            continue

        scoring = score_group(pattern, cards)
        rl = risk_level_for_group(cards, scoring)

        primary = cards[0]["filename"]
        extra = len(cards) - 1
        source_card = primary if extra == 0 else f"{primary} (and {extra} more)"

        rule: dict[str, Any] = {
            "rule_id": make_rule_id(pattern, today),
            "source_card": source_card,
            "summary": PATTERNS[pattern]["summary"],
            "proposed_behavior": PATTERNS[pattern]["proposed_behavior"],
            "risk_level": rl,
            "status": "proposed",
            "created_at": now_str,
            "card_count": len(cards),
            "scoring": scoring,
        }

        if rl == "high":
            rule["_note"] = "manual approval required before applying"

        rules.append(rule)

    return rules


# ── Output writers ────────────────────────────────────────────────────────────

def write_markdown(rules: list[dict[str, Any]], cards_total: int, cards_dir: Path) -> None:
    """Write promoted_rules.md."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    rel_cards_dir = str(cards_dir.relative_to(REPO_ROOT)) if cards_dir.is_relative_to(REPO_ROOT) else str(cards_dir)

    lines = [
        "# Self-Improvement Promoted Rules",
        "",
        f"_Last updated: {now}_",
        f"_Cards scanned: {cards_total} | Rules proposed: {len(rules)} | Source: {rel_cards_dir}/_",
        "",
        "---",
        "",
    ]

    for rule in rules:
        rid = rule["rule_id"]
        note = ""
        if rule.get("_note"):
            note = f"\n> **Note:** {rule['_note']}\n"
        lines += [
            f"<!-- RULE:{rid} -->",
            f"## {rid}",
            "",
            f"- **rule_id**: {rid}",
            f"- **status**: {rule['status']}",
            f"- **risk_level**: {rule['risk_level']}",
            f"- **card_count**: {rule['card_count']}",
            f"- **source_card**: {rule['source_card']}",
            f"- **created_at**: {rule['created_at']}",
            "",
        ]
        if note:
            lines.append(note)
        lines += [
            f"**Summary:** {rule['summary']}",
            "",
            f"**Proposed behavior:** {rule['proposed_behavior']}",
            "",
            "**To approve:** Change `status: proposed` → `status: approved`, then re-run `--apply` to update the JSON.",
            "<!-- /RULE -->",
            "",
            "---",
            "",
        ]

    PROMOTED_RULES_MD.parent.mkdir(parents=True, exist_ok=True)
    PROMOTED_RULES_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {PROMOTED_RULES_MD}")


def write_json(rules: list[dict[str, Any]], cards_total: int) -> None:
    """Write promoted_rules.json (Cortex reads this)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    payload = {
        "rules": [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in rules
        ],
        "updated_at": now,
        "card_count": cards_total,
    }
    PROMOTED_RULES_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROMOTED_RULES_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Written: {PROMOTED_RULES_JSON}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote self-improvement cards to automation rules."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Parse, score, print — do NOT write files")
    mode.add_argument("--apply", action="store_true", help="Write promoted_rules.md and promoted_rules.json")
    mode.add_argument("--stats", action="store_true", help="Print card scan stats only")
    parser.add_argument(
        "--cards-dir",
        type=Path,
        default=DEFAULT_CARDS_DIR,
        help=f"Path to cards directory (default: {DEFAULT_CARDS_DIR})",
    )
    args = parser.parse_args()

    cards = scan_cards(args.cards_dir)
    groups = group_cards(cards)

    if args.stats:
        print(f"Cards scanned : {len(cards)}")
        for pattern, grp in sorted(groups.items()):
            print(f"  {pattern}: {len(grp)} cards")
        return

    rules = build_rules(groups)

    if args.dry_run:
        print(f"=== DRY RUN ===")
        print(f"Cards scanned : {len(cards)}")
        print(f"Groups        : {len(groups)}")
        print(f"Rules proposed: {len(rules)}")
        print()
        for rule in rules:
            print(f"  [{rule['rule_id']}] {rule['risk_level'].upper()} — {rule['summary']}")
            print(f"    cards={rule['card_count']}  scoring={rule['scoring']}")
            if rule.get("_note"):
                print(f"    NOTE: {rule['_note']}")
        print()
        print("No files written (dry-run mode).")
        return

    if args.apply:
        write_markdown(rules, len(cards), args.cards_dir)
        write_json(rules, len(cards))
        print()
        print(f"Cards scanned : {len(cards)}")
        print(f"Rules proposed: {len(rules)}")
        for rule in rules:
            print(f"  [{rule['rule_id']}] {rule['risk_level'].upper()} — {rule['card_count']} cards")
        return


if __name__ == "__main__":
    main()
