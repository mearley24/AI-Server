# Verification — Reply Suggestion Inbox v1
**Date:** 2026-04-26T18:05:34Z
**Author:** Claude Sonnet 4.6

## Endpoint Output

### GET /api/reply/suggestions/pending (empty state)
```json
{
    "status": "ok",
    "count": 0,
    "suggestions": []
}
```
Queue is currently empty — no overdue follow-ups in x_intake_queue. Empty state response is correct.

### POST /api/reply/regenerate (missing queue_item_id)
```json
{"status": "error", "error": "queue_item_id required", "draft": "", "confidence": 0.0}
```

### POST /api/reply/regenerate (unknown queue_item_id)
```json
{"status": "error", "error": "queue_item_id 999999 not found or has no sender_guid", "draft": "", "confidence": 0.0}
```

## Files Changed

| File | Change |
|------|--------|
| `cortex/engine.py` | Added `GET /api/reply/suggestions/pending` and `POST /api/reply/regenerate` endpoints |
| `cortex/static/index.html` | Added "Replies" tab button + panel with `ri-cards` container |
| `cortex/static/dashboard.js` | Added `loadReplyInbox()`, `_riCardHtml()`, `_riCopy()`, `_riRegenerate()`, `_riApprove()`, lazy-load flag `_riLoaded`, hash restore |
| `ops/tests/test_reply_inbox.py` | 18 new tests (NEW) |
| `ops/verification/20260426-180534-reply-suggestion-inbox.md` | This file |

## UI Behavior Summary

**Reply Suggestions tab** (accessible at `#reply-inbox`):
- Lazy-loads on first tab click
- Shows "Replies" badge with count in nav if > 0
- Empty state: "No pending reply suggestions."
- When suggestions exist, each card shows:
  - Contact (masked: e.g. `+13***32`) + display name
  - Relationship type + systems
  - Incoming message (if available)
  - Editable textarea with suggested draft
  - Confidence % + quality status badge
  - Active rules applied (green badges)
  - Priority badge (urgent/high/medium/low/review)
  - Overdue duration

**Button behavior:**
- **Regenerate** → POST `/api/reply/regenerate` with `queue_item_id`, updates textarea in-place. Falls back gracefully if Ollama offline.
- **Copy** → `navigator.clipboard.writeText(textarea.value)` — client-side only, no network call.
- **Approve Draft** → POST `/api/x-intake/approve-reply` with `approved=true`, `send_triggered: false`, `send_dry_run: true`. Dims the card on success. Shows approval_id in status line.
- **Edit Draft** → Textarea is always editable (no separate button needed — just type).

## No-Send Confirmation

All approval paths flow through `/api/x-intake/approve-reply` which:
- Sets `send_triggered: false`
- Sets `send_dry_run: true`
- Writes to `data/cortex/reply_approvals.ndjson` only
- Writes a dry-run receipt to `data/cortex/reply_receipts_dry_run.ndjson`
- Never calls the BlueBubbles bridge or any live send path

## Tests Run

```
python3 -m pytest ops/tests -q
962 passed, 4 warnings in 13.61s
```

New tests (18 in `ops/tests/test_reply_inbox.py`):
- `TestPendingSuggestionsEndpoint` (6 tests): empty state, shape validation, priority_rank stripped, no raw phones, count matches length, limit respected
- `TestRegenerateEndpoint` (3 tests): missing queue_item_id error, unknown queue_item_id error, no raw phone in error
- `TestApproveReplyNeverSends` (9 tests): approval stored, send_triggered=False, send_dry_run=True, dry-run receipt written, no raw phone in record/response, empty draft error, not_approved noop, edited reply used as final

## No Sends Occurred

No live iMessage sends were triggered during this session. All approval paths write to dry-run files only. The BlueBubbles bridge was not called.
