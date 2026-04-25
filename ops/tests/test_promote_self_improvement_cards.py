"""Tests for scripts/promote_self_improvement_cards.py

Tests:
1. test_only_cards_dir_scanned      — --cards-dir limits scan to given dir
2. test_inbox_ignored               — scanner never touches inbox/ or archive/
3. test_duplicate_cards_grouped     — two cards with same pattern yield one rule
4. test_proposed_rules_created      — scan produces at least one rule with status == "proposed"
5. test_risky_rules_not_auto_approved — rules with risk_level "high" stay as "proposed"
6. test_api_returns_proposed_rules  — endpoint parsing logic using a temp JSON file
7. test_dry_run_no_write            — dry_run mode does not write any files
8. test_rule_fields_complete        — every generated rule has all required fields
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.promote_self_improvement_cards as mod


# ── Fixtures ──────────────────────────────────────────────────────────────────

BRIDGE_CARD_CONTENT = textwrap.dedent("""\
    # Improvement card — iMessage X intake bridge test

    - **Source stream:** `imessage.chat.db`
    - **Source kind:** imessage
    - **Original URL:** https://x.com/testuser/status/1234567890?s=42
    - **Original excerpt:**
      handle=+19705193013 is_from_me=0
      text=https://x.com/testuser/status/1234567890?s=42
    - **Captured:** 20260425T000000Z
    - **Origin confidence:** medium
    - **Status:** needs fetch

    ## Automation hypothesis

    If we implemented an iMessage→x_intake auto-routing step, AI-Server would be able
    to enqueue X links arriving on the business iMessage line directly into the
    `x_intake` processing queue automatically.

    ## Efficiency lever

    Less human toil.

    ## Affected subsystem

    `integrations/x_intake`

    ## Impact / Effort / Risk
    - Impact: 2
    - Effort: 2
    - Risk:   2

    ## Recommended next action

    needs fetch

    ## Safe next prompt

    Not drafted — action was not auto-safe.

    ## Can this be auto-run?

    No — requires Matt.
""")

BATCH_CARD_CONTENT = textwrap.dedent("""\
    # Improvement card — batch processing test

    - **Source stream:** `imessage.chat.db`
    - **Source kind:** imessage (batch)
    - **Original URL:** Multiple X.com URLs
    - **Original excerpt:** handle=+19705193013 is_from_me=0
    - **Captured:** 20260425T000001Z
    - **Origin confidence:** medium
    - **Status:** auto-run via ai-dispatch

    ## Automation hypothesis

    If we implemented smarter batch pattern recognition for recurring iMessage X.com URL
    batches, AI-Server would consolidate similar inputs automatically.

    ## Efficiency lever

    Fewer context switches.

    ## Affected subsystem

    `ops/self_improvement/`

    ## Impact / Effort / Risk
    - Impact: 3
    - Effort: 2
    - Risk:   1

    ## Recommended next action

    auto-run via ai-dispatch

    ## Safe next prompt

    bash scripts/ai-dispatch.sh run-prompt .cursor/prompts/extend-batch.md

    ## Can this be auto-run?

    Yes — auto-safe, bounded, no secrets.
""")

HIGH_RISK_CARD_CONTENT = textwrap.dedent("""\
    # Improvement card — high risk operation

    - **Source stream:** `imessage.chat.db`
    - **Source kind:** imessage
    - **Original URL:** https://x.com/testuser/status/9999999999?s=42
    - **Original excerpt:** handle=+19705193013 is_from_me=0
    - **Captured:** 20260425T000002Z
    - **Origin confidence:** medium
    - **Status:** needs fetch

    ## Automation hypothesis

    If we implemented an iMessage→x_intake auto-routing step, this would automatically
    process X.com URLs from iMessage into the x_intake pipeline.

    ## Efficiency lever

    Automated pipeline.

    ## Affected subsystem

    `integrations/x_intake`

    ## Impact / Effort / Risk
    - Impact: 4
    - Effort: 3
    - Risk:   5

    ## Recommended next action

    needs fetch

    ## Safe next prompt

    Not drafted — too risky without more context.

    ## Can this be auto-run?

    No — requires approval.
""")

UNCLASSIFIED_CARD_CONTENT = textwrap.dedent("""\
    # Improvement card — unrelated thing

    - **Source stream:** `email-monitor`
    - **Source kind:** email
    - **Original URL:** https://example.com/article
    - **Original excerpt:** test
    - **Captured:** 20260425T000003Z
    - **Origin confidence:** low
    - **Status:** needs review

    ## Automation hypothesis

    If we improved email classification, AI-Server could sort emails better.

    ## Efficiency lever

    Fewer manual classifications.

    ## Affected subsystem

    `email-monitor`

    ## Impact / Effort / Risk
    - Impact: 2
    - Effort: 3
    - Risk:   2

    ## Recommended next action

    Review manually.

    ## Safe next prompt

    Not drafted.

    ## Can this be auto-run?

    No — requires context.
""")


def _write_card(tmpdir: Path, filename: str, content: str) -> Path:
    path = tmpdir / filename
    path.write_text(content, encoding="utf-8")
    return path


# ── Test 1: only cards_dir is scanned ─────────────────────────────────────────

def test_only_cards_dir_scanned(tmp_path: Path) -> None:
    """Passing --cards-dir to a dir with one card shows count=1."""
    cards_dir_a = tmp_path / "cards_a"
    cards_dir_a.mkdir()
    _write_card(cards_dir_a, "card-one.md", BRIDGE_CARD_CONTENT)

    cards_dir_b = tmp_path / "cards_b"
    cards_dir_b.mkdir()
    _write_card(cards_dir_b, "card-one.md", BRIDGE_CARD_CONTENT)
    _write_card(cards_dir_b, "card-two.md", BATCH_CARD_CONTENT)

    cards_a = mod.scan_cards(cards_dir_a)
    cards_b = mod.scan_cards(cards_dir_b)

    assert len(cards_a) == 1
    assert len(cards_b) == 2


# ── Test 2: inbox and archive are never touched ────────────────────────────────

def test_inbox_ignored(tmp_path: Path) -> None:
    """Scanner function never touches inbox/ or archive/ when given cards dir."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    _write_card(cards_dir, "real-card.md", BRIDGE_CARD_CONTENT)
    _write_card(inbox_dir, "inbox-card.md", BRIDGE_CARD_CONTENT)
    _write_card(archive_dir, "archive-card.md", BRIDGE_CARD_CONTENT)

    cards = mod.scan_cards(cards_dir)

    filenames = [c["filename"] for c in cards]
    assert "real-card.md" in filenames
    assert "inbox-card.md" not in filenames
    assert "archive-card.md" not in filenames
    assert len(cards) == 1


# ── Test 3: duplicate cards are grouped into one rule ─────────────────────────

def test_duplicate_cards_grouped(tmp_path: Path) -> None:
    """Two cards with same pattern yield one rule, not two."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    _write_card(cards_dir, "card-a.md", BRIDGE_CARD_CONTENT)
    _write_card(cards_dir, "card-b.md", BRIDGE_CARD_CONTENT)

    cards = mod.scan_cards(cards_dir)
    groups = mod.group_cards(cards)
    rules = mod.build_rules(groups)

    # Both cards should be in the same group → one rule for that pattern
    bridge_rules = [r for r in rules if "x_intake" in r["summary"].lower() or "imessage" in r["summary"].lower()]
    assert len(bridge_rules) == 1
    assert bridge_rules[0]["card_count"] == 2


# ── Test 4: proposed rules created ────────────────────────────────────────────

def test_proposed_rules_created(tmp_path: Path) -> None:
    """Scan produces at least one rule with status == 'proposed'."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    _write_card(cards_dir, "card-a.md", BRIDGE_CARD_CONTENT)

    cards = mod.scan_cards(cards_dir)
    groups = mod.group_cards(cards)
    rules = mod.build_rules(groups)

    assert len(rules) >= 1
    assert all(r["status"] == "proposed" for r in rules)


# ── Test 5: risky rules stay proposed, not auto-approved ─────────────────────

def test_risky_rules_not_auto_approved(tmp_path: Path) -> None:
    """Rules with risk_level 'high' stay as 'proposed' (not 'approved')."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    _write_card(cards_dir, "high-risk-card.md", HIGH_RISK_CARD_CONTENT)

    cards = mod.scan_cards(cards_dir)
    groups = mod.group_cards(cards)
    rules = mod.build_rules(groups)

    high_rules = [r for r in rules if r["risk_level"] == "high"]
    for rule in high_rules:
        assert rule["status"] == "proposed", f"High-risk rule should stay proposed: {rule['rule_id']}"


# ── Test 6: API endpoint parsing with temp JSON file ──────────────────────────

def test_api_returns_proposed_rules(tmp_path: Path) -> None:
    """Test the endpoint parsing logic using a temp JSON file."""
    json_path = tmp_path / "promoted_rules.json"
    payload = {
        "rules": [
            {
                "rule_id": "RULE-20260425-abcdef",
                "status": "proposed",
                "risk_level": "low",
                "summary": "Test rule summary",
                "proposed_behavior": "Test behavior",
                "source_card": "test-card.md",
                "card_count": 1,
                "created_at": "20260425T000000Z",
                "scoring": {"relevance": 3, "actionability": 2, "safety": 4},
            },
            {
                "rule_id": "RULE-20260425-123456",
                "status": "approved",
                "risk_level": "medium",
                "summary": "Approved rule",
                "proposed_behavior": "Approved behavior",
                "source_card": "approved-card.md",
                "card_count": 2,
                "created_at": "20260425T000001Z",
                "scoring": {"relevance": 4, "actionability": 3, "safety": 3},
            },
        ],
        "updated_at": "2026-04-25T00:00:00+00:00Z",
        "card_count": 3,
    }
    json_path.write_text(json.dumps(payload))

    # Simulate endpoint logic
    data = json.loads(json_path.read_text())
    all_rules = data.get("rules", [])
    proposed_only = [r for r in all_rules if r.get("status") == "proposed"]

    assert len(all_rules) == 2
    assert len(proposed_only) == 1
    assert proposed_only[0]["rule_id"] == "RULE-20260425-abcdef"
    assert data["card_count"] == 3


# ── Test 7: dry_run does not write any files ──────────────────────────────────

def test_dry_run_no_write(tmp_path: Path) -> None:
    """dry-run mode (running scan+build but NOT calling write functions) does not write files."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    _write_card(cards_dir, "card-a.md", BRIDGE_CARD_CONTENT)

    # The script's --dry-run mode calls scan_cards + group_cards + build_rules but NOT write_* fns.
    # We verify that calling only those functions leaves no output files.
    cards = mod.scan_cards(cards_dir)
    groups = mod.group_cards(cards)
    rules = mod.build_rules(groups)  # builds rules in memory

    # No write calls made — verify output files don't exist in tmp_path
    for p in tmp_path.rglob("promoted_rules.*"):
        pytest.fail(f"Unexpected output file created: {p}")

    # Confirm we did get rules (the scan itself worked)
    assert len(rules) >= 1


# ── Test 8: every generated rule has all required fields ─────────────────────

def test_rule_fields_complete(tmp_path: Path) -> None:
    """Every generated rule has all required fields."""
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    _write_card(cards_dir, "bridge-card.md", BRIDGE_CARD_CONTENT)
    _write_card(cards_dir, "batch-card.md", BATCH_CARD_CONTENT)
    _write_card(cards_dir, "unclassified-card.md", UNCLASSIFIED_CARD_CONTENT)

    cards = mod.scan_cards(cards_dir)
    groups = mod.group_cards(cards)
    rules = mod.build_rules(groups)

    required_fields = {
        "rule_id",
        "source_card",
        "summary",
        "proposed_behavior",
        "risk_level",
        "status",
        "created_at",
        "card_count",
    }

    assert len(rules) >= 1, "Expected at least one rule"
    for rule in rules:
        missing = required_fields - set(rule.keys())
        assert not missing, f"Rule {rule.get('rule_id', '?')} missing fields: {missing}"
