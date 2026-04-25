# Client Intelligence Fact Quality Audit
**Date:** 2026-04-25T03:57Z
**Operator:** Claude Code
**Scope:** proposed_facts.sqlite — accepted fact reclassification

---

## Dry-run summary

```
=== audit_client_facts — DRY-RUN ===
  Accepted facts reviewed : 5
  valid   : 3
  invalid : 2  → will mark rejected
  weak    : 0     → will reset to pending

  ✓ KEEP     [equipment   ]  conf=0.75  'Sonos'
  ✗ REJECT   [follow_up   ]  conf=0.50  'Let me know'
             reason: generic/non-actionable: 'let me know'
  ✗ REJECT   [request     ]  conf=0.70  'give me call as soon as you can as am trying to setup the WiFi network and need'
             reason: trailing incomplete fragment
  ✓ KEEP     [system      ]  conf=0.75  'WiFi'
  ✓ KEEP     [system      ]  conf=0.75  'network'
```

## Apply summary

```
  Applied: 2 rejected, 0 reset to pending
```

## Before / after counts

```sql
-- Before
is_accepted=1, is_rejected=0  →  5  (accepted)
is_accepted=0, is_rejected=1  →  3  (rejected)

-- After
is_accepted=1, is_rejected=0  →  3  (accepted)
is_accepted=0, is_rejected=1  →  5  (rejected)
```

## Facts reclassified

| fact_type  | fact_value                                                                    | before   | after    | reason                          |
|------------|-------------------------------------------------------------------------------|----------|----------|---------------------------------|
| request    | give me call as soon as you can as am trying to setup the WiFi network and need | accepted | rejected | trailing incomplete fragment     |
| follow_up  | Let me know                                                                   | accepted | rejected | generic/non-actionable phrase    |

## Facts preserved (valid)

| fact_type  | fact_value | verdict |
|------------|------------|---------|
| equipment  | Sonos      | valid   |
| system     | WiFi       | valid   |
| system     | network    | valid   |

## Tests run

```
python3 -m pytest ops/tests/test_client_fact_quality.py ops/tests/test_context_card.py ops/tests/test_reply_approval.py -q
→ 121 passed, 2 warnings
```

## Remaining blockers

None. Rejected facts are excluded by the existing `is_rejected=0` SQL filter in
`_facts_for_profile()` (cortex/engine.py). Context cards, suggested_next_action,
and reply drafts all use only accepted facts.

## Follow-up (non-blocking)

- TODO in audit_client_facts.py: extract `validate_fact()` into a shared module
  so extract_relationship_profiles.py uses the same quality bar at extraction time.
- More approved profiles will need auditing as client intel grows.
