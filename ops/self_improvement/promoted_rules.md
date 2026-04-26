# Self-Improvement Promoted Rules

_Last updated: 2026-04-25T19:35:14+00:00Z_
_Cards scanned: 24 | Rules proposed: 3 | Source: ops/self_improvement/cards/_

---

<!-- RULE:RULE-20260425-036df2 -->
## RULE-20260425-036df2

- **rule_id**: RULE-20260425-036df2
- **status**: proposed
- **risk_level**: low
- **card_count**: 7
- **source_card**: 20260424T163001Z-imessage-x-com-nousresearch-status-2047495677651918885-card.md (and 6 more)
- **created_at**: 20260425T193514Z

**Summary:** Route X.com URLs received via iMessage to the x_intake pipeline automatically.

**Proposed behavior:** When the self-improvement collector detects an X.com URL in an iMessage (`handle=+19705193013 is_from_me=0`), submit it to the x_intake ingest endpoint instead of writing a standalone card. This closes the gap between URL capture and content analysis.

**To approve:** Change `status: proposed` → `status: approved`, then re-run `--apply` to update the JSON.
<!-- /RULE -->

---

<!-- RULE:RULE-20260425-5ee7f5 -->
## RULE-20260425-5ee7f5

- **rule_id**: RULE-20260425-5ee7f5
- **status**: proposed
- **risk_level**: high
- **card_count**: 4
- **source_card**: 20260422-20260425-imessage-x-urls-pattern-card.md (and 3 more)
- **created_at**: 20260425T193514Z


> **Note:** manual approval required before applying

**Summary:** Add pattern deduplication and batch consolidation to the self-improvement card pipeline to reduce redundant individual cards for identical patterns.

**Proposed behavior:** Extend the self-improvement collector to detect repeated URL-pattern cards within the same processing window, consolidate them into a single batch card, and emit one improvement proposal instead of N identical ones. Reduces card generation overhead and improves signal-to-noise ratio.

**To approve:** Change `status: proposed` → `status: approved`, then re-run `--apply` to update the JSON.
<!-- /RULE -->

---

<!-- RULE:RULE-20260425-f8c13b -->
## RULE-20260425-f8c13b

- **rule_id**: RULE-20260425-f8c13b
- **status**: proposed
- **risk_level**: medium
- **card_count**: 13
- **source_card**: 20260422T111725Z-imessage-x-com-ihtesham2005-status-2046528187593830850-card.md (and 12 more)
- **created_at**: 20260425T193514Z

**Summary:** Unclassified improvement cards not matching a known automation pattern.

**Proposed behavior:** Manual review required. No automated rule can be generated for this group without additional context.

**To approve:** Change `status: proposed` → `status: approved`, then re-run `--apply` to update the JSON.
<!-- /RULE -->

---
