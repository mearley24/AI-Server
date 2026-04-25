# Client Intel Auto-Triage Hardening — Verification Report

**Date**: 2026-04-25T16:11Z
**Task**: Harden Client Intel auto-triage discovery (Task 8)
**Result**: PASS — all 718 tests green

---

## Changes Made

### `scripts/review_client_threads.py`
- `_TECH_TERMS` expanded: added `"proposal"`, `"walkthrough"`, `"project"`, `"site visit"`, `"job site"`, `"budget"`
- `_score_domain_signals`: added intro-phrase boost — `"symphony"` in texts → `tech += 3`
- `analyze_thread_assist`: added `"_scores": scores` to return dict for debug/explain

### `scripts/auto_triage_client_threads.py`
- Added `shutil` import
- New constants: `_SNAPSHOT_DIR`, `_LIVE_CHAT_DB`, `_TRIAGE_STATS_PATH`
- `_TRIAGE_COLS`: added `("triage_debug", "TEXT")` column
- **New function `_auto_snapshot()`**: copies live chat.db + WAL/SHM to snapshot dir; returns None on failure; Messages.app does not need to be closed
- **New function `_snapshot_diagnostics(chat_db_path)`**: returns total/text/attributedBody message counts + decode coverage; warns if coverage < 50%
- `_determine_triage_bucket`: added `readable_message_count: int = 0` parameter; new rule: named contact + message_count > 10 + assist_conf >= 0.50 → high_value
- `run_triage`: stores `triage_debug` JSON per thread (scores, evidence, readable_message_count, etc.); writes `triage_stats.json` sidecar after every run
- **New function `get_thread_explain(conn, thread_id)`**: returns full triage debug for one thread (phone masked)
- New CLI flags: `--snapshot-auto`, `--dry-run` (explicit), `--explain THREAD_ID`, `--bucket-summary`, `--top N`
- New helpers: `_print_explain()`, `_print_bucket_summary()`

### `cortex/engine.py`
- Added `_TRIAGE_STATS_PATH` constant
- `GET /api/client-intel/triage-summary`: merges snapshot health stats from `triage_stats.json` (snapshot_used, snapshot_message_count, attributed_body_count, readable_sample_count)

### `ops/tests/test_auto_triage.py`
- Added 27 new tests across 7 classes:
  - `TestAutoSnapshot` (4 tests): snapshot copy, WAL copy, failure fallback, dir creation
  - `TestSnapshotDiagnostics` (4 tests): required keys, message counts, empty db, bad path
  - `TestTriageBucketReadableCount` (3 tests): param default, debug storage, new rule
  - `TestImprovedHighValueScoring` (6 tests): boundary conditions, symphony boost, new terms
  - `TestTriageDebugStored` (3 tests): column exists, valid JSON, dry-run no write
  - `TestGetThreadExplain` (4 tests): required keys, unknown thread, scores, masking
  - `TestTriageStatsJson` (3 tests): file written, snapshot info, dry_run flag

---

## Live Run Results

```
Snapshot: 90,848 messages — readable sample: 99/100 (coverage_ok)
Processed: 267 pending threads
high_value:     3
ambiguous:    168
low_priority:  96
hidden_personal: 0
```

### triage_stats.json
```json
{
  "last_run": "2026-04-25T16:10:34Z",
  "dry_run": false,
  "processed": 267,
  "snapshot_used": ".../chatdb_snapshot/chat.db",
  "snapshot_message_count": 90848,
  "attributed_body_count": 90316,
  "readable_sample_count": 99
}
```

---

## Test Results

```
718 passed, 4 warnings in 12.93s
```

(was 691 before this session, +27 new tests)

---

## Root cause
N/A — feature hardening, not a bug fix.

## Fix applied
See "Changes Made" above.
