# Network Monitoring LaunchDaemon Verification — Run 2 (2026-04-23)

**Date**: 2026-04-23T09:34:48 MDT  
**Author**: Claude Code (autonomous, repo-only pass)  
**Source audit**: [`docs/audits/2026-04-23-unfinished-setup-audit.md`](2026-04-23-unfinished-setup-audit.md)  
**Prior run doc**: [`docs/audits/2026-04-23-network-monitoring-launchd-verification.md`](2026-04-23-network-monitoring-launchd-verification.md) (commit `9e12fc6`)  
**Verification artifact**: `ops/verification/20260423-093448-network-monitoring-launchd.txt`

---

## Purpose of This Run

Idempotent re-execution of the network-monitoring launchd setup prompt to produce
a fresh observation receipt and confirm the prior run's committed work remains
intact and correct on Bob.

---

## State as Observed This Run

| Item | Prior run (09:15) | This run (09:34) | Change? |
|------|-------------------|------------------|---------|
| `com.symphony.network-guard.plist` lint | PASS | PASS | None |
| `com.symphony.network-dropout-watch.plist` lint | PASS | PASS | None |
| network-guard launchctl state | `- 1` (loaded, exit=1) | `- 1` (loaded, exit=1) | None |
| network-guard running | NO (crash-loop) | NO (crash-loop) | None |
| `logs/network-guard.log` last write | 2026-04-03 | 2026-04-03 | None |
| `logs/network-guard.err` size | ~8.0 MB | ~8.0 MB+ (growing) | Still growing |
| dropout-watch plist matches spec | N/A (just created) | YES — all keys verified | Confirmed |
| dropout-watch armed | NO | NO | None |
| `data/network_watch/` state | `stopped=true`, Apr 4 | `stopped=true`, Apr 4 | None |
| `network_dropout_watch.py` compile | PASS | PASS | None |

---

## Plist Spec Verification (Phase 3)

`setup/launchd/com.symphony.network-dropout-watch.plist` verified key-by-key
against the prompt spec. All fields match exactly:

- Label, ProgramArguments (python3 path + all 6 args), WorkingDirectory ✓
- PATH and HOME environment variables ✓
- RunAtLoad=true, KeepAlive=true, ThrottleInterval=30 ✓
- StandardOutPath, StandardErrorPath ✓
- No UserName key (correct — user LaunchAgent) ✓
- No StartInterval key (correct — continuous process) ✓

**No changes were required.**

---

## Ongoing Issues (unchanged)

**network_guard_daemon.py is crash-looping.** The installed
`~/Library/LaunchAgents/com.symphony.network-guard.plist` (mtime Mar 10) runs a
version of `tools/network_guard_daemon.py` that imports `security_utils`, which is
not on the Python path in the LaunchAgent environment. The `.err` log has grown to
143,000+ lines of repeated tracebacks; no new health records have been written since
2026-04-03. The plist is registered in launchd but the daemon is non-functional.

---

## What Is Still Not Done

### Requires Matt (`[NEEDS_MATT]`)

1. **Arm dropout-watch** (no `sudo`):
   ```
   launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-dropout-watch.plist
   ```
   Verify: `cat data/network_watch/dropout_watch_status.json`

2. **Fix network-guard crash** — resolve `security_utils` import, then:
   ```
   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist
   launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-guard.plist
   ```

---

## Out of Scope (same as Run 1)

Any launchctl mutation, sudo, new ports, Docker changes, docker-compose.yml edits,
reply-leg/Cortex/BlueBubbles work, secrets, ntopng/netdata stack.

---

## References

- Source audit: `docs/audits/2026-04-23-unfinished-setup-audit.md`
- Run 1 audit doc: `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
- Verification artifact: `ops/verification/20260423-093448-network-monitoring-launchd.txt`
- Plist: `setup/launchd/com.symphony.network-dropout-watch.plist`
