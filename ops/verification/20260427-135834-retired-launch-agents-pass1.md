# Launch Agent Cleanup — Pass 1 Verification
Date: 2026-04-27T13:58:34Z  
Source audit: ops/verification/20260427-135117-failing-launch-agents-audit.md

---

## Result: 24 agents retired, 7 protected agents untouched

---

## Agents Unloaded and Archived

All plists moved to: `/Users/bob/AI-Server/_archive/launchagents-retired-20260427/`

| Agent | bootout rc | Notes |
|---|---|---|
| com.symphony.notes-watcher | 3 | Already not registered in launchd (plist was on disk only); archived |
| com.symphony.employee-beatrice-bot | 0 | Unloaded cleanly |
| com.symphony.polymarket-hourly | 0 | Unloaded cleanly |
| com.symphony.trading-provider-slo-monitor | 0 | Unloaded cleanly |
| com.symphony.service-sre-loop | 0 | Unloaded cleanly |
| com.symphony.focus-ops-monitor | 0 | Unloaded cleanly |
| com.symphony.failure-replay-queue | 0 | Unloaded cleanly |
| com.symphony.email-project-intake | 0 | Unloaded cleanly |
| com.symphony.trading-research-bot-hourly | 0 | Unloaded cleanly |
| com.symphony.watcher | 0 | Unloaded cleanly |
| com.symphony.trading-research-daily-digest | 0 | Unloaded cleanly |
| com.symphony.quality-gate-nightly | 0 | Unloaded cleanly |
| com.symphony.trading-pnl-attribution-daily | 0 | Unloaded cleanly |
| com.symphony.trading-topic-graph-daily | 0 | Unloaded cleanly |
| com.symphony.subscription-audit | 0 | Unloaded cleanly |
| com.symphony.graph-drift-watcher-daily | 0 | Unloaded cleanly |
| com.symphony.trading-research-quality-weekly | 0 | Unloaded cleanly |
| com.symphony.core-ops-health-hourly | 0 | Unloaded cleanly |
| com.symphony.decision-hygiene-hourly | 0 | Unloaded cleanly |
| com.symphony.polymarket-scan | 0 | Unloaded cleanly |
| com.symphony.signal-action-hourly | 0 | Unloaded cleanly |
| com.symphony.incoming-tasks | 0 | Unloaded cleanly |
| com.symphony.overnight-learner | 0 | Unloaded cleanly |
| com.symphony.mobile-api | 0 | Unloaded cleanly |

---

## Protected Agents — Confirmed Untouched

| Agent | Plist on disk | launchctl status |
|---|---|---|
| com.symphony.trading-api | ✅ present | RUNNING (PID 98451) |
| com.symphony.imessage-bridge | ✅ present | RUNNING (PID 2421) |
| com.symphony.markup-app | ✅ present | RUNNING (PID 762, port 8088) |
| com.symphony.approval-drainer | ✅ present | Loaded (broken DB — needs repair) |
| com.symphony.voice-webhook | ✅ present | Loaded (port conflict — needs fix) |
| com.symphony.notes-sync | ✅ present | Loaded (yaml missing — needs pip) |
| com.symphony.x-autoposter | ✅ present | Loaded but dormant (intentionally broken) |

---

## Remaining Symphony Agents in launchctl

Active / healthy:
- com.symphony.trading-api (PID 98451)
- com.symphony.imessage-bridge (PID 2421)
- com.symphony.markup-app / markup-tool (PID 762 / 762)
- com.symphony.file-watcher (PID 749)
- com.symphony.task-runner, task-runner-watchdog
- com.symphony.bob-watchdog, bob-maintenance
- com.symphony.audio-intake, bluebubbles-health, network-guard
- com.symphony.business-hours-throttle
- com.symphony.realized-change-watcher, self-improvement, learning, smoke-test
- com.symphony.bob.workspace
- com.symphonysh.dropbox-organizer, icloud-watch

Still failing (Pass 2 / needs-matt-approval):
- com.symphony.approval-drainer (exit 1 — malformed DB)
- com.symphony.voice-webhook (exit 1 — port conflict + wrong python)
- com.symphony.notes-sync (exit 1 — missing yaml module)
- com.symphony.email-reply-agent (exit 1 — symphony.email module missing; auto-send risk)
- com.symphony.imessage-watcher (exit 1 — needs log investigation)
- com.symphony.daily-digest (exit 1 — appears functional but intermittent)
- com.symphony.bob-maintenance (exit 1 — appears functional)

---

## Pass 2 Recommended Actions

| Agent | Fix Required | Risk |
|---|---|---|
| notes-sync | `pip3 install pyyaml` | Low — local only |
| voice-webhook | Reassign port (away from 8088), switch interpreter | Low — no external impact |
| bob-maintenance | Investigate exit 1 (likely cosmetic) | Low |
| daily-digest | Investigate intermittent exit 1 | Low — sends to Matt only |
| imessage-watcher | Separate log from bob-maintenance; check exit | Low |
| approval-drainer | Inspect/repair malformed SQLite inside openclaw | Medium — Matt approval needed |
| email-reply-agent | Define auto-mode policy before restoring symphony.email | High — auto-sends email |
