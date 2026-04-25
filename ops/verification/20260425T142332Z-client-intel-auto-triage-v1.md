# Client Intel Auto-Triage v1 — 2026-04-25

## Result

686 passed · 0 failed · 0 errors · 4 warnings (FastAPI on_event deprecation, pre-existing)
48 new tests added (all pass).

## Triage counts (live run on current DB)

| Bucket | Count |
|---|---|
| high_value | 1 |
| ambiguous | 133 |
| low_priority | 133 |
| hidden_personal | 0 |
| untriaged | 0 |
| **Total processed** | **267** |

Last triaged: 2026-04-25T14:22:59Z

## Examples

**high_value** (+19***98): named contact with high classifier confidence (80%)
  domain=smart_home_work  suggested=unknown  conf=0.80

**ambiguous** (+17***02): builder coordination signals — verify builder vs client role
  domain=builder_coordination  suggested=builder  conf=0.60

**low_priority** (+15***41): unnamed contact with low classification confidence (25%)
  domain=smart_home_work  suggested=unknown  conf=0.80

Note: chat.db not readable from this process (read-only lock from Messages.app),
so all threads received empty texts → _score_domain_signals relies on reason_codes only.
Reason_codes without tech signals → conf=0.25 → low_priority for unnamed threads.
Re-running triage when Messages.app is closed will improve signals.

## Safety guarantees verified

- is_reviewed was NOT changed for any thread
- Phone numbers masked in all output
- No profiles auto-created
- Approved/rejected threads skipped
- Personal threads → hidden_personal only

---

## Changes applied

### 1. `scripts/auto_triage_client_threads.py` — new script

Core functions:
- `_ensure_triage_columns(conn)` — idempotent ALTER TABLE for 8 triage fields
- `_determine_triage_bucket(category, work_confidence, message_count, date_last, name, assist)`
  Pure function, priority waterfall: hidden_personal → high_value → ambiguous → low_priority
- `run_triage(conn, limit, dry_run, bucket_filter)` — classifies pending threads only (is_reviewed=-1)
- `get_triage_summary(conn)` — bucket counts + untriaged + last_triaged
- `get_review_queue(conn, bucket, limit)` — for dashboard/API, phone numbers always masked

CLI: --apply, --limit N, --bucket, --summary, --verbose (dry-run is default)

### 2. `cortex/engine.py` — 2 new endpoints

`GET /api/client-intel/triage-summary`
  Returns: {status, high_value, ambiguous, low_priority, hidden_personal, untriaged, last_triaged}

`GET /api/client-intel/review-queue?bucket=&limit=`
  Returns: {status, count, threads[]} — all contact_handle fields masked
  Validates bucket parameter before DB access.

### 3. `cortex/static/index.html` — Review Queue card

Added `<div id="ci-queue-card">` with triage summary stats and queue list
above the Profiles/Facts grid in the Clients tab.

### 4. `cortex/static/client-intel.js` — Review Queue JS

- `renderTriageSummary(d)` — 4-cell stat grid (clickable, switches bucket)
- `renderQueueThreads(data, bucket)` — per-thread rows with contact_display,
  domain, suggested_relationship, triage_reason, confidence, risk_flags
- `updateQueueTabs(activeBucket)` — All/High Value/Ambiguous/Low Priority/Hidden tabs
- `window.loadReviewQueue(bucket)` — fetches and renders the queue
- `loadClientIntel()` now calls `renderTriageSummary` and `loadReviewQueue('all')` automatically

### 5. `ops/tests/test_auto_triage.py` — 48 new tests

| Class | Tests |
|---|---|
| TestDetermineTriageBucket | 17 pure-function tests covering all waterfall branches |
| TestSchemaMigration | 2 tests (idempotent, existing table) |
| TestTriageDryRun | 6 tests (no writes, processed count, masking, keys, valid bucket) |
| TestTriageApply | 8 tests (writes fields, is_reviewed unchanged, approved/rejected skipped, personal=hidden_personal) |
| TestBucketFilter | 1 test |
| TestGetTriageSummary | 4 tests |
| TestGetReviewQueue | 5 tests (masking, filter, approved excluded) |
| TestCortexEndpoints | 4 tests (shape, invalid bucket, bucket filter) |

---

## Triage DB columns added to threads table

- triage_bucket TEXT
- triage_reason TEXT
- triage_confidence REAL
- triage_suggested_relationship TEXT
- triage_inferred_domain TEXT
- triage_risk_flags TEXT DEFAULT '[]'
- triage_contact_display TEXT
- triaged_at TEXT
