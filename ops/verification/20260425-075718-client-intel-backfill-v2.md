# Client Intelligence Backfill Expansion v2 — 2026-04-25T07:57:18Z

## Result

591 passed · 0 failed · 0 errors · 4 warnings (FastAPI on_event deprecation, pre-existing)
18 new tests added (all pass).

## Threads indexed

Not run against live chat.db in this pass — all changes verified via mocked unit tests.
Use `python3 scripts/client_intel_backfill.py --dry-run --limit 1000` to index threads.

## Review candidates added

0 (unit-test pass only; no live backfill run performed).

## Facts proposed

0 (unit-test pass only).

---

## Changes applied

### 1. `scripts/client_intel_backfill.py` — major expansion

**Batch support:**
- `--dry-run --limit 1000` classifies up to 1000 threads, indexes with `is_reviewed=-1` (proposal).
- `--apply --limit 1000` upgrades dry-run proposals, extracts proposed facts for work/mixed threads.
- `--live` retained as alias for `--apply`.
- `--status` prints current DB counts and exits.

**Checkpoint / resume:**
- `_load_checkpoint(db_path, apply_mode)` loads already-processed thread_ids before opening chat.db.
- Dry-run mode skips all already-indexed threads.
- Apply mode skips threads with `is_reviewed >= 0` (already applied) but re-processes dry-run proposals (`is_reviewed=-1`) to extract facts.
- `run_entry` now includes `skipped`, `review_candidates`, `facts_proposed` counters.

**Personal thread isolation:**
- Personal threads are written to the thread index only (`is_reviewed=-1` or `0`).
- No entries written to `proposed_facts.sqlite` for personal threads.

**Work/mixed fact extraction (apply mode only):**
- `_extract_facts_for_thread()` produces one `relationship_type` fact (inferred from builder/client signals in reason_codes) plus one `system` fact per distinct system signal (Sonos, Control4, Lutron, Araknis, WattBox, etc.).
- All facts start with `is_accepted=0, is_rejected=0` — pending Matt approval.
- Facts use `INSERT OR IGNORE` so duplicate runs never overwrite existing review decisions.
- `review_candidates` counter counts threads that produced at least one fact.

**Status helper:**
- `get_backfill_status()` reads all three DBs (thread index, profiles, facts) and the run log without touching chat.db. Returns: `total_indexed, work, mixed, personal, unknown, reviewed, approved_profiles, proposed_facts, last_run`.

### 2. `cortex/engine.py` — new endpoint

`GET /api/client-intel/backfill-status` added after the existing `client_intel_summary` endpoint.

Returns:
```json
{
  "status": "ok",
  "total_indexed": 0,
  "work": 0,
  "mixed": 0,
  "personal": 0,
  "unknown": 0,
  "reviewed": 0,
  "approved_profiles": 0,
  "proposed_facts": 0,
  "last_run": null
}
```

### 3. `cortex/static/index.html` — Backfill Status card

Added `<div id="ci-backfill-card">` with `<div id="ci-backfill-status">` above the existing Profiles/Facts grid in the Clients tab.

### 4. `cortex/static/client-intel.js` — dashboard integration

`window.loadBackfillStatus()` fetches `/api/client-intel/backfill-status` and renders an 8-cell stat grid (Total Indexed, Work, Mixed, Personal, Unknown, Reviewed, Approved Profiles, Pending Facts) plus last-run timestamp. Called automatically by `loadClientIntel()`.

### 5. `ops/tests/test_client_intel_backfill.py` — 18 new tests

| Class | Tests |
|---|---|
| `TestBatchLimit` | limit_respected_dry_run, limit_respected_apply, limit_zero, limit_larger_than_available |
| `TestCheckpoint` | apply_resume_skips_applied, dry_run_resume_skips_indexed, partial_resume_processes_new, dry_run_then_apply_reprocesses |
| `TestPersonalThreads` | personal_indexed, personal_no_proposed_facts |
| `TestWorkMixedCandidates` | work_creates_review_candidates, dry_run_no_facts_written, work_facts_include_relationship_type, work_facts_are_pending |
| `TestBackfillStatus` | status_required_keys, status_counts_correctly, status_last_run_populated, status_empty_db_zeros |

---

## Commit hash

See git log for commit "Add client intelligence backfill expansion v2".
