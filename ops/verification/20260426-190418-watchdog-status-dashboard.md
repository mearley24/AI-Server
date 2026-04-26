# Verification — Watchdog Status → Cortex Dashboard v1
**Date:** 2026-04-26T19:04:18Z
**Author:** Claude Sonnet 4.6

## Endpoint Output

### GET /api/watchdog/status
```json
{
    "status": "degraded",
    "services": [
        {"name": "Containers",       "state": "ok",       "event_type": "recovery", "details": "Last watchdog action 49h ago"},
        {"name": "Docker engine",    "state": "degraded",  "event_type": "recovery", "details": "Watchdog recovery 2.9h ago"},
        {"name": "Tailscale",        "state": "ok",       "event_type": "recovery", "details": "Last watchdog action 43h ago"},
        {"name": "OpenClaw",         "state": "degraded",  "event_type": "restart",  "details": "Watchdog restart 2.0h ago"},
        {"name": "Polymarket Bot",   "state": "ok",       "event_type": "restart",  "details": "Last watchdog action 51h ago"},
        {"name": "VPN",              "state": "ok",       "event_type": "restart",  "details": "Last watchdog action 49h ago"},
        {"name": "X Alpha Collector","state": "ok",       "event_type": "restart",  "details": "Last watchdog action 47h ago"},
        {"name": "X Intake",         "state": "ok",       "event_type": "recovery", "details": "Last watchdog action 4h ago"}
    ],
    "degraded_count": 2,
    "updated_at": "2026-04-26T13:03:30-0600",
    "warning": null
}
```

Docker engine and OpenClaw both degraded (within 3h window). All other services ok.

## Files Changed

| File | Change |
|------|--------|
| `cortex/engine.py` | Added `_TASK_RUNNER_DIR`, `_WATCHDOG_STATE_DIR`, `_WATCHDOG_HEARTBEAT` path constants; added `_WD_SERVICE_NAMES` map, `_WD_STALE_SECS` threshold, `_read_watchdog_state()` helper, `GET /api/watchdog/status` endpoint |
| `cortex/static/index.html` | Added `#wd-header-alert` span in header; added `#watchdog-card` with `#watchdog-overview` div in Overview column 1 |
| `cortex/static/dashboard.js` | Added `watchdog` to `Promise.all` fetch list; added `renderWatchdog()` function; added `renderWatchdog(watchdog)` call in refresh |
| `cortex/static/dashboard.css` | Added `.wd-alert` / `.wd-alert.hidden` styles (yellow pill matching `.fu-alert` pattern) |
| `ops/tests/test_watchdog_status.py` | 10 new tests (NEW) |
| `ops/verification/20260426-190418-watchdog-status-dashboard.md` | This file |

## Logic Summary

**State file interpretation:**
- Files in `bob-watchdog-state/` named `uh_{service}` = unhealthy+restart event timestamp for that service
- Other files (`docker`, `x_intake`, `tailscale`, `containers`) = recovery event timestamps
- `required_source` = metadata, always skipped
- Threshold: events < 3h old → `state=degraded`; older → `state=ok`

**Banner behavior:**
- If `degraded_count > 0`: yellow `#wd-header-alert` shows "⚠ N degraded service(s)"
- Otherwise: banner hidden

**Overview card:**
- All clear: "✓ all clear — N services monitored · updated X ago"
- Degraded: shows dot+name+detail rows for degraded services; ok count in small text below

**Graceful fallback:**
- Missing state dir → `status=ok`, `services=[]`, `warning="No watchdog state directory found."`
- Missing state files → `status=ok`, `services=[]`, `warning="No watchdog state files found."`
- Malformed file content → silently skipped (no crash)
- Missing heartbeat → `updated_at=null`

## No Docker Socket / No Sends

The endpoint is entirely read-only. It reads state files from the mounted volume only.
No Docker commands are issued from the container. No messages are sent.

## Tests Run

```
python3 -m pytest ops/tests -q
972 passed, 4 warnings in 13.17s
```

New tests (10 in `ops/tests/test_watchdog_status.py`):
- `TestWatchdogMissingDir` (2 tests): missing dir returns ok+warning, empty dir returns warning
- `TestWatchdogStateFiles` (8 tests): old events ok, recent events degraded, required_source skipped, malformed content no crash, degraded_count accuracy, recovery event_type, no raw phones, heartbeat used as updated_at

## No Sends Occurred

No iMessage sends, no Docker modifications, no external calls during this session.
