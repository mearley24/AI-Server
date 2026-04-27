# Cortex Broken Data Sources Fix

**Date:** 2026-04-27T19:19:44Z  
**Auditor:** Claude (automated)  
**Method:** Live curl + source code fix + container restart verification

---

## Summary

| Source | Before | After | Fix Applied |
|---|---|---|---|
| Follow-ups DB | UNAVAILABLE (`unable to open database file`) | ✓ 4 active, 4 overdue | SQLite immutable=1 URI mode |
| Reply Inbox | Already OK (`count:0, status:ok`) | ✓ Already OK | No fix needed |
| Wallet USDC | BROKEN (zeros, no source) | ✓ $3.72 USDC, source=real | Read from bot `/status` redeemer section |
| Decisions noise | 100% D-Tools automation | ✓ Empty (honest) + debug=raw | Server-side `exclude_automation=true` param |
| Activity noise | health.checked + jobs.synced (~50%) | ✓ Calendar/email events | Server-side `debug` param + client-side filter |

---

## Root Cause Analysis

### Follow-ups DB: SQLite WAL mode on read-only Docker mount

The DB at `/app/data/openclaw/follow_ups.db` is mounted `:ro` (read-only) in the Cortex container. The DB is in WAL (Write-Ahead Logging) mode. When SQLite opens a WAL-mode DB, it tries to create/lock a `.db-shm` shared-memory file. On a read-only mount, this fails with "unable to open database file".

**Fix:** Changed all 6 `sqlite3.connect(str(db_path))` calls in `dashboard.py` to use the immutable URI mode:
```python
conn = sqlite3.connect(f"file://{db_path}?immutable=1", uri=True)
```
`immutable=1` tells SQLite to skip WAL entirely and read the file as-is. Works correctly on read-only mounts.

**Affected DBs:** `follow_ups.db`, `decision_journal.db`, `x_intake/queue.db`, `audio_intake/queue.db` (all 6 sqlite3.connect calls updated).

### Wallet: USDC nested in `/status` response, not at top level

The wallet endpoint's second fallback calls `TRADING_BOT_URL/status` and reads `data.get("usdc_balance", 0)`. But the bot's `/status` response nests USDC inside `strategies.redeemer.usdc_balance`, not at the top level. The third fallback (Polymarket data API) explicitly sets `usdc_balance: 0.0` since it can't read on-chain balances.

**Fix:** Added deep-read of the redeemer section:
```python
redeemer_section = (data.get("strategies") or {}).get("redeemer") or {}
usdc = float(data.get("usdc_balance") or redeemer_section.get("usdc_balance") or 0)
matic = float(redeemer_section.get("matic_balance") or 0)
```
Also added `source: "bot_status"`, `source_type: "real"`, `snapshot_age`, and `matic_balance` to the response shape. UI BROKEN banner no longer fires because `usdc=3.72 > 0`.

### Decisions: All 100% automation (D-Tools category=jobs)

The decision journal contains only `category=jobs` D-Tools sync entries. The JavaScript already filtered these client-side (v3 fix), but the server was still sending 100 automation entries on every refresh.

**Fix:** Added `exclude_automation: bool = Query(True)` param to `/api/decisions/recent`. Default behavior excludes categories `{jobs, sync, heartbeat, health}`. Debug mode passes `exclude_automation=false` to see all entries. The empty response is honest: there genuinely are no human decisions in the journal.

### Activity: health.checked + jobs.synced noise (~50% of feed)

The activity feed was dominated by `health.checked` system pings and `jobs.synced` D-Tools automation events. The JavaScript filtered `health.checked` (v3 fix) but not `jobs.synced` or `heartbeat` events.

**Fix:** 
- **Server-side:** Added `debug: bool = Query(False)` to `/api/activity`. In normal mode, fetches 200 entries and filters `_ACTIVITY_NOISE_TYPES = {health.checked, health.check, jobs.synced, heartbeat, tick}`, then caps at 50.
- **Client-side:** Updated `_isNoise()` to include `jobs.synced`, `heartbeat`, `tick` types.
- **Debug mode wiring:** `refresh()` now passes `?debug=true` to activity and `?exclude_automation=false` to decisions when `_debugMode=true`.

---

## Live Verification

```
GET /api/followups → {"total":4,"overdue_count":4,"error":null}
GET /api/wallet    → {"usdc_balance":3.72,"source":"bot_status","source_type":"real","snapshot_age":"..."}
GET /api/decisions/recent → {"journal":[],"exclude_automation":true}  ← honest empty
GET /api/activity  → [calendar.checked, email.processed, ...]  ← no noise
GET /api/reply/suggestions/pending → {"status":"ok","count":0}  ← already working
```

---

## Sources Still Unavailable (require infrastructure changes)

| Source | Status | Why |
|---|---|---|
| Wallet position_value | 0.0 | Bot tracking paper trades (cvd_arb), not live Polymarket positions. PAPER banner shown. |
| P&L Series | [] | Redis key `portfolio:pnl_series` never populated by bot. Marked UNAVAILABLE. |
| Trading Intel | All zeros | `/api/trading/intel` returns empty signals. No card in UI — endpoint unused. |
| Daily Digest | null/empty | Digest not generated today (agent idle). Empty state shown. |
| Goals timestamps | No updated_at | Would need DB migration — out of scope. |

---

## Files Changed

- `cortex/dashboard.py` — wallet USDC fix, immutable DB fix (×6), decisions exclude_automation, activity debug param
- `cortex/static/dashboard.js` — jobs.synced filter, debug-mode endpoint params, wallet MATIC display
- `ops/tests/test_dashboard_assets.py` — 8 new tests

## Tests
- `ops/tests/test_dashboard_assets.py`: **58 passed**
- `ops/tests/` (full suite): **1182 passed**
