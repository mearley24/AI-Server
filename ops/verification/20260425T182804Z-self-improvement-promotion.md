# Self-Improvement Card Promotion — Verification Report

**Timestamp:** 2026-04-25T18:28:04Z
**Feature:** Self-Improvement Card Promotion v1

---

## Summary

Implemented end-to-end self-improvement card promotion workflow for the Symphony AI-Server.

---

## Cards Scanned

- **Directory:** `ops/self_improvement/cards/`
- **Total cards scanned:** 22
- **Patterns identified:** 3

| Pattern | Cards |
|---|---|
| `imessage_x_intake_bridge` | 7 |
| `batch_card_consolidation` | 3 |
| `unclassified` | 12 |

---

## Rules Proposed

**Total rules proposed:** 3

| Rule ID | Risk Level | Cards | Summary |
|---|---|---|---|
| RULE-20260425-036df2 | low | 7 | Route X.com URLs via iMessage to x_intake pipeline |
| RULE-20260425-5ee7f5 | high | 3 | Batch card consolidation / pattern deduplication |
| RULE-20260425-f8c13b | medium | 12 | Unclassified cards — manual review required |

All rules default to `status: proposed`. No rules are auto-approved.
The high-risk rule (RULE-20260425-5ee7f5) carries `# manual approval required before applying` note.

---

## Duplicates Grouped

- 7 individual X.com iMessage URL cards → grouped into 1 rule (RULE-20260425-036df2)
- 3 batch/consolidated/pattern cards → grouped into 1 rule (RULE-20260425-5ee7f5)
- 12 unclassified cards → grouped into 1 rule (RULE-20260425-f8c13b)

**Total duplicate cards consolidated:** 19 cards into 3 rules (7+3+12 → 1+1+1)

---

## Tests Passed

**8/8 tests passed** (0.02s)

| Test | Result |
|---|---|
| `test_only_cards_dir_scanned` | PASSED |
| `test_inbox_ignored` | PASSED |
| `test_duplicate_cards_grouped` | PASSED |
| `test_proposed_rules_created` | PASSED |
| `test_risky_rules_not_auto_approved` | PASSED |
| `test_api_returns_proposed_rules` | PASSED |
| `test_dry_run_no_write` | PASSED |
| `test_rule_fields_complete` | PASSED |

---

## Files Written

| File | Description |
|---|---|
| `scripts/promote_self_improvement_cards.py` | Main promotion script (--dry-run / --apply / --stats / --cards-dir) |
| `ops/self_improvement/promoted_rules.md` | Human-readable proposed rules |
| `data/cortex/promoted_rules.json` | Machine-readable rules for Cortex |
| `cortex/engine.py` | Added `GET /api/self-improvement/promoted-rules` endpoint |
| `cortex/static/index.html` | Added "Self Improvement" tab to nav + tab panel |
| `cortex/static/dashboard.js` | Added `loadSelfImprovement()` function |
| `ops/tests/test_promote_self_improvement_cards.py` | 8 unit tests |
| `ops/verification/20260425T182804Z-self-improvement-promotion.md` | This report |

---

## Root cause

No existing workflow existed to aggregate, group, or score self-improvement cards. Cards accumulated individually without any mechanism to surface recurring patterns as actionable rules.

## Fix applied

Created a complete promotion pipeline:
1. `--dry-run` mode parses and scores cards, prints proposed rules, writes nothing
2. `--apply` mode writes `promoted_rules.md` (human) and `promoted_rules.json` (Cortex)
3. Rule IDs are stable (md5 hash of pattern name) — re-running `--apply` preserves IDs
4. Cortex endpoint exposes rules read-only with optional `?status=proposed` filter
5. Dashboard tab shows rules with risk badges (green/amber/red) and card counts

## Limitations

- The `unclassified` group (12 cards) contains cards with diverse automation hypotheses; a future pass should add more specific classifiers for the "external connector follow-up" pattern and the "fetch required, no hypothesis" pattern.
- `is_relative_to()` method used for path display may fail on very old Python; fallback to `str(path)` is handled.
