# Network Monitoring LaunchDaemon Verification (2026-04-23)

**Date**: 2026-04-23  
**Author**: Claude Code (autonomous, repo-only pass)  
**Source audit**: [`docs/audits/2026-04-23-unfinished-setup-audit.md`](2026-04-23-unfinished-setup-audit.md)  
**Verification artifact**: `ops/verification/20260423-091516-network-monitoring-launchd.txt`  

---

## What the Repo Looked Like Before This Run

- `setup/launchd/com.symphony.network-guard.plist` — committed, installed in
  `~/Library/LaunchAgents/` (mtime Mar 10), but the daemon has been crash-looping
  since ~Apr 3 due to `ModuleNotFoundError: No module named 'security_utils'` in
  `tools/network_guard_daemon.py`. The `.err` log is 8 MB of repeated tracebacks;
  `.log` stopped writing healthy records on 2026-04-03T13:46:14.
- `setup/launchd/com.symphony.network-dropout-watch.plist` — **did not exist**.
- `tools/network_dropout_watch.py` — present (214 lines), compiles cleanly, last
  state file dated 2026-04-04 (`stopped=true`, health=`lan_or_router_down`).
- No `ops/verification/` receipt proving either tool is running on Bob.

---

## What This Run Changed

| File | Action |
|------|--------|
| `setup/launchd/com.symphony.network-dropout-watch.plist` | **Created** |
| `docs/audits/2026-04-23-network-monitoring-launchd-verification.md` | **Created** (this file) |
| `ops/verification/20260423-091516-network-monitoring-launchd.txt` | **Created** |
| `STATUS_REPORT.md` | **Updated** (new dated section, `[FOLLOWUP]` + `[NEEDS_MATT]` tags) |

No runtime state on Bob was altered. No launchctl commands were run.  
No service was started, stopped, or reloaded.

---

## Existing network-guard Plist — Observed State

| Check | Result |
|-------|--------|
| `plutil -lint` on repo copy | **PASS** |
| `launchctl list \| grep network-guard` | `- 1 com.symphony.network-guard` (loaded, not running, exit=1) |
| Installed in `~/Library/LaunchAgents/` | Yes — mtime **Mar 10** (stale vs repo) |
| Installed in `/Library/LaunchDaemons/` | No (correct — user LaunchAgent) |
| `.log` producing records | **NO** — last entry 2026-04-03; daemon broken |
| `.err` content | `ModuleNotFoundError: No module named 'security_utils'` (crash-loop) |

The daemon is installed and launchd keeps it in its registry, but it has not
produced a healthy-status log line since Apr 3. The `security_utils` module
is not on the Python path in the LaunchAgent environment.

---

## New Plist — Design Decisions

**`setup/launchd/com.symphony.network-dropout-watch.plist`**

- **LaunchAgent, not LaunchDaemon**: runs as `bob`, no `sudo` or root required.
- **`KeepAlive: true`** + **`ThrottleInterval: 30`**: launchd supervises restarts;
  30-second throttle prevents restart storms if the tool crashes.
- **No `StartInterval`**: this is a continuous `--watch` process (SIGTERM-safe at
  lines 20–28 of `network_dropout_watch.py`), not a periodic tick.
- **No `UserName` key**: inherited from the LaunchAgent user context.
- **`--interval-sec 2.0`**: polls every 2 seconds; writes state JSON on every
  transition, not every tick (events-driven).
- **Outbound surface**: ICMP ping to `192.168.1.1` (gateway) and `1.1.1.1` (WAN
  check). No inbound ports, no new external exposure.
- Lint: `plutil -lint` **PASS**.

---

## What Is Still Not Done

### Requires Matt (`[NEEDS_MATT]`)

1. **Arm the dropout-watch LaunchAgent** (no `sudo` needed):
   ```
   launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-dropout-watch.plist
   ```
   Then verify: `cat data/network_watch/dropout_watch_status.json`  
   Expected: `"running": true`, `"health": "healthy"`.

2. **Fix `network_guard_daemon.py` crash** — resolve or remove the `security_utils`
   import, then reload the plist:
   ```
   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist
   launchctl bootstrap gui/$(id -u) /Users/bob/AI-Server/setup/launchd/com.symphony.network-guard.plist
   ```

---

## Out of Scope for This Run

- Any `launchctl` mutation (load / unload / bootstrap / bootout / kickstart).
- Any change to `com.symphony.network-guard.plist` semantics.
- Any new open port, public exposure, or Docker service.
- Any change to `docker-compose.yml`.
- Any reply-leg / Cortex / BlueBubbles work.
- Any Bob-only secret or `.env` read.
- Full LAN traffic-monitoring stack (ntopng / netdata) — absent by choice, per audit §1.
- Cross-check against ntopng/netdata (not yet scheduled).

---

## References

- Source audit: `docs/audits/2026-04-23-unfinished-setup-audit.md`
- Verification artifact: `ops/verification/20260423-091516-network-monitoring-launchd.txt`
- Tool source: `tools/network_dropout_watch.py`
- New plist: `setup/launchd/com.symphony.network-dropout-watch.plist`
- Existing plist: `setup/launchd/com.symphony.network-guard.plist`
