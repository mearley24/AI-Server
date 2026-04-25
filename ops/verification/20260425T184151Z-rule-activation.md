# Verification: Self-Improvement Rule Approval + Activation v1

**Timestamp:** 2026-04-25T18:41:51Z  
**Operator:** Claude (automated verification)

---

## Files Created / Modified

| File | Change |
|---|---|
| `cortex/self_improvement_engine.py` | NEW — core engine: load/save, approve, reject, behavior application |
| `cortex/engine.py` | Added approve/reject endpoints; hooked `_build_draft_with_context` and `_compute_follow_ups` |
| `cortex/static/dashboard.js` | Added Approve/Reject buttons per rule; status badges; action handlers |
| `data/cortex/promoted_rules.json` | Migrated — added 5 new fields to all 3 existing rules |
| `scripts/auto_triage_client_threads.py` | Imports `_apply_triage_boost`; applies to each thread's `review_value_score` |
| `ops/tests/test_self_improvement_activation.py` | NEW — 30 tests |

---

## 1. Schema Migration

All 3 existing rules migrated with new fields:
- `approved_at`: null
- `approved_by`: null
- `rejected_at`: null
- `rejected_reason`: null
- `behavior_category`: derived from `proposed_behavior` text

Derived categories:
- `RULE-20260425-036df2` → `pipeline` (iMessage/x_intake keywords)
- `RULE-20260425-5ee7f5` → `pipeline` (batch consolidation keywords)
- `RULE-20260425-f8c13b` → `general` (no matching keywords)

---

## 2. Approval + Rejection Demonstration

**Approved:** `RULE-20260425-036df2` (low risk, pipeline)
```
status: proposed → approved
approved_by: matt
approved_at: 2026-04-25T18:41:31+00:00
```

**Rejected:** `RULE-20260425-f8c13b` (medium risk, general/unclassified)
```
status: proposed → rejected
rejected_reason: Too vague — manual review needed, no actionable behavior change
rejected_at: 2026-04-25T18:41:31+00:00
```

**Remaining proposed:** `RULE-20260425-5ee7f5` (high risk — manual approval required)

---

## 3. Active Rules Confirmation

```
get_active_rules() → 1 rule
  RULE-20260425-036df2  category=pipeline  approved_by=matt
```

Only approved rules are returned. The pending high-risk rule remains as `proposed`.

---

## 4. Behavior Application

Since the currently approved rule has `behavior_category = "pipeline"`, it does not influence reply drafting, triage scoring, or follow-up thresholds (by design — pipeline rules affect the card ingestion pipeline, not Bob's response behavior).

**Reply hints (pipeline rule active):** `{}` — no change to draft behavior  
**Triage boost (pipeline rule active):** `0.5 → 0.5` — no change to review_value_score  
**Follow-up adjustments:** `{}` — no threshold changes

The hooks are in place and verified:
- `_build_draft_with_context` accepts `behavior_hints` parameter; returns `active_rule_hints` in output
- `_compute_review_value_score` boost is applied in `run_triage()` (wrapped in try/except)
- `_compute_follow_ups` applies `apply_followup_adjustments` per-item (wrapped in try/except)

When a `reply_phrasing`, `triage_scoring`, or `follow_up_threshold` rule is approved in the future, the hooks will fire automatically.

---

## 5. Safety Verification

- No rule was auto-approved — all required explicit `approve_rule()` call
- High-risk rule (`RULE-20260425-5ee7f5`) remains `proposed`
- Approval is mutually exclusive with rejection (prior state is cleared on transition)
- Atomic write: `promoted_rules.json` written via `os.replace()` on temp file — no partial writes
- All integration hooks wrapped in `try/except` — system continues normally on rule engine failure
- No client-facing messages sent
- No Docker/launchd/Tailscale changes
- No secrets modified

---

## 6. Tests

**30 tests, 0 failures**

Coverage:
- `TestApproveRule` (6 tests): status, approved_at, approved_by, persistence, unknown/already-approved errors
- `TestRejectRule` (5 tests): status, rejected_reason, rejected_at, persistence, unknown error
- `TestGetActiveRules` (4 tests): only approved, empty when none, empty on missing file, empty on malformed
- `TestReplyDraftingReceivesRules` (4 tests): behavior_hints parameter accepted, no crash on None, empty hints for no rules, dict for phrasing rule
- `TestTriageScoringWithRules` (4 tests): no rules = base, prioritize repeat increases score, cap at 1.0, pipeline rule ignored
- `TestRobustness` (7 tests): crash-proofing for missing file, bad rules, None behavior, category derivation

**Full suite: 817 passed** (up from 787)

---

## Root cause / Fix applied
N/A — new feature

## Next
Matt can approve/reject rules via the Self Improvement tab in the Cortex dashboard at http://localhost:8102, or via:
- `POST /api/self-improvement/promoted-rules/{rule_id}/approve`
- `POST /api/self-improvement/promoted-rules/{rule_id}/reject`

To add rules that affect reply behavior, run:
```
python3 scripts/promote_self_improvement_cards.py --apply
```
Then review and approve rules with `behavior_category = reply_phrasing`, `triage_scoring`, or `follow_up_threshold`.
