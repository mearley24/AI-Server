# Verification: Self-Improvement Rule Impact Scoring + Auto-Suggest v1

**Timestamp:** 2026-04-25T22:11:14Z  
**Operator:** Claude (automated verification)

---

## Files Created / Modified

| File | Change |
|---|---|
| `scripts/evaluate_rule_impact.py` | NEW — impact scorer: category derivation, event simulation, scoring, recommendations |
| `cortex/static/dashboard.js` | Enhanced Self Improvement tab: impact bars, confidence bars, recommendation badges, sorted by impact |
| `ops/tests/test_rule_impact_scoring.py` | NEW — 35 tests |
| `data/cortex/promoted_rules.json` | Impact scores applied (impact_score, confidence_score, recommendation, recommendation_reason, impact_scored_at) |

---

## 1. Evaluator Output (--dry-run then --apply)

```
Loaded 3 rules, 40 cards, 21 cortex entries

RULE-20260425-036df2  [approved / pipeline / low risk]
  affected_events:  42
  impact_score:     0.58
  confidence_score: 0.725
  recommendation:   review
  reason:           Moderate signal: 42 affected events. Worth reviewing but evidence is not yet conclusive.

RULE-20260425-5ee7f5  [proposed / pipeline (derived) / high risk]
  affected_events:  42
  impact_score:     0.90
  confidence_score: 0.50
  recommendation:   review
  reason:           High risk — manual approval required. Impact looks strong (42 affected events).

RULE-20260425-f8c13b  [proposed / general (unclassified) / medium risk]
  affected_events:  34
  impact_score:     0.165
  confidence_score: 0.28
  recommendation:   ignore
  reason:           Unclassified — no actionable behavior pattern detected. Manual review needed.
```

---

## 2. Top Rules by Impact

| Rank | Rule ID | Impact | Confidence | Recommendation |
|---|---|---|---|---|
| 1 | RULE-20260425-5ee7f5 | 0.90 | 0.50 | review (high risk gate) |
| 2 | RULE-20260425-036df2 | 0.58 | 0.73 | review |
| 3 | RULE-20260425-f8c13b | 0.165 | 0.28 | ignore |

---

## 3. Recommendation Logic Verified

- High-risk rules never get `approve` — gated to `review` always ✓
- Unclassified (general) rules get `ignore` ✓
- Duplicate rules get `ignore` + reduced impact score ✓
- `behavior_category` derived from proposed_behavior text when absent/null ✓
- No rule was auto-approved — all require explicit API call ✓

---

## 4. Dashboard UI Changes

The Self Improvement tab now shows per rule:
- Impact score bar (green/amber/gray by threshold)
- Confidence score bar (indigo)
- Recommendation badge (💡 APPROVE / REVIEW / IGNORE)
- "would have touched N events" text
- Recommendation reason (italic, muted)
- Rules sorted: proposed first, then by impact_score descending

---

## 5. Tests

**35 tests, 0 failures**

Coverage:
- `TestEffectiveCategory` (5 tests): derives category when absent/null, respects existing
- `TestDeriveCategory` (6 tests): all 5 categories + general fallback
- `TestExtractMatchKeywords` (4 tests): pipeline/triage/general/absent-category
- `TestScoreRule` (9 tests): range, event count, all fields present, empty-card penalty
- `TestHighRiskRules` (3 tests): never approve, gets review, low-risk can approve
- `TestDuplicateRules` (3 tests): low impact, ignore recommendation, unique not flagged
- `TestUnclassifiedRules` (2 tests): gets ignore, low confidence
- `TestNoSystemBehaviorChange` (3 tests): no mutation, dry-run writes nothing

**Full suite: 852 passed** (up from 817)

---

## 6. Safety Verification

- No rule auto-approved — scoring only, explicit API call still required
- High-risk rule (RULE-5ee7f5) scored as high impact but recommendation=review, not approve
- `score_rule()` does not mutate input rule dict (verified by test + JSON round-trip)
- `--dry-run` writes no files (verified by mtime check in test)
- Atomic write via `os.replace()` on temp file — no partial writes on `--apply`
- All new JSON fields are additive — no existing fields removed
- No client-facing messages sent
- No Docker/launchd/secrets changes

---

## Root cause / Fix applied
N/A — new feature

## Next
Run `python3 scripts/evaluate_rule_impact.py --apply` after adding new rules to refresh scores.
Matt can approve/reject rules with impact scores visible in the Self Improvement tab at http://localhost:8102/dashboard.
