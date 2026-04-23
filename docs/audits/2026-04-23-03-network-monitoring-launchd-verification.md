# Network Monitoring LaunchDaemon Verification — Run 3 (2026-04-23)

**Date**: 2026-04-23T09:38:28 MDT  
**Author**: Claude Code (autonomous, repo-only pass)  
**Source audit**: [`docs/audits/2026-04-23-unfinished-setup-audit.md`](2026-04-23-unfinished-setup-audit.md)  
**Run 1 doc**: [`docs/audits/2026-04-23-network-monitoring-launchd-verification.md`](2026-04-23-network-monitoring-launchd-verification.md) (commit `9e12fc6`)  
**Run 2 doc**: [`docs/audits/2026-04-23-02-network-monitoring-launchd-verification.md`](2026-04-23-02-network-monitoring-launchd-verification.md) (commit `fa914c5`)  
**Verification artifact**: `ops/verification/20260423-093828-network-monitoring-launchd.txt`

---

## Status: PASS — dropout-watch ARMED and HEALTHY

This is the first run where `com.symphony.network-dropout-watch` is live on Bob.

| Agent | launchctl state | Running | Health | .err clean |
|-------|----------------|---------|--------|------------|
| `com.symphony.network-guard` | loaded, exit=1 | **NO** — crash-loop | n/a | NO (143k lines) |
| `com.symphony.network-dropout-watch` | loaded, exit=0, PID 52527 | **YES** | **healthy** | YES |

---

## What Changed Since Run 2

| Change | Commit |
|--------|--------|
| Added `/sbin:/usr/sbin` to plist PATH (ping lives at `/sbin/ping`) | `4dbd996` |
| `launchctl bootstrap` executed — agent armed | manual step |
| `data/network_watch/dropout_watch_status.json` — `running: true` | live state |

---

## Live State (as of this run)

```
PID:     52527
Uptime:  since 2026-04-23T09:37:12
Health:  healthy
Gateway: 192.168.1.1 — ok, 0.549 ms
WAN:     1.1.1.1     — ok, 15.897 ms
.err:    empty (0 bytes)
```

dropout-watch log shows clean lifecycle: started → SIGTERM on reload → restarted with PATH fix → running continuously.

---

## network-guard — Still Broken

The existing guard daemon (`tools/network_guard_daemon.py`) imports `security_utils`
which is absent from the LaunchAgent Python path. Last healthy log write: 2026-04-03.
The `.err` file has 143,415 lines of repeated tracebacks and is still growing.
The installed plist in `~/Library/LaunchAgents/` is dated Mar 10 (stale vs repo).

---

## Remaining Open Items

- [NEEDS_MATT] Fix `tools/network_guard_daemon.py` — resolve or remove `from security_utils import sanitize_for_telegram`, then reload:
  ```
  launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist
  launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-guard.plist
  ```
- [FOLLOWUP] Optionally prune `logs/network-guard.err` once guard is fixed (8 MB / 143k traceback lines).

---

## Out of Scope (same as prior runs)

Any launchctl mutation beyond what was already done, sudo, new ports, Docker changes,
docker-compose.yml edits, reply-leg/Cortex/BlueBubbles work, secrets, ntopng/netdata.

---

## References

- Verification artifact: `ops/verification/20260423-093828-network-monitoring-launchd.txt`
- Plist: `setup/launchd/com.symphony.network-dropout-watch.plist`
- Tool: `tools/network_dropout_watch.py`
- State: `data/network_watch/dropout_watch_status.json`
