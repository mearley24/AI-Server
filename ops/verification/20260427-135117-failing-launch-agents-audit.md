# Failing Symphony Launch Agents — Audit
Generated: 2026-04-27T13:51:17Z  
Source: `/tmp/symphony-failing-agents.txt` (34 agents)  
Auditor: Claude Code — read-only, no changes made

---

## Executive Summary

| Category | Count |
|---|---|
| **RUNNING** (exit -15 = SIGTERM, currently healthy) | 2 |
| **Script/module missing** → retire_unload | 21 |
| **Script exists, fixable** → keep_and_fix | 5 |
| **Messaging/money risk** → needs_matt_approval | 2 |
| **Unknown / stale** | 4 |

**The good news:** Most of the apparent failures are ghost plists for scripts that were deleted. The system is less broken than the count suggests — 21 agents just need to be unloaded.

**Actual problems requiring action:**
1. `approval-drainer` — malformed SQLite DB inside openclaw container
2. `voice-webhook` — port 8088 conflict with markup-app (which is already running there)
3. `notes-sync` — `yaml` module missing (1-line pip fix)
4. `email-reply-agent` — symphony.email module missing, auto-mode email risk when restored

---

## Special Attention Agents

### 1. trading-api — RUNNING ✅
```
PID: 98451 (was 91393 in snapshot)  LastExitStatus: 15 (SIGTERM = clean restart)
Script: api/trading_api.py — EXISTS
Interpreter: .venv/bin/python3
Health: http://127.0.0.1:8421/health → {"status":"healthy"}
```
**Classification: RUNNING — do not touch.**  
Exit -15 in launchctl list means it was previously SIGTERMed by launchd (normal). Currently running and responding. Trading API is healthy.

---

### 2. imessage-bridge — RUNNING ✅
```
PID: 2421  LastExitStatus: 15 (SIGTERM = clean restart)
Script: scripts/imessage-server.py — EXISTS
Interpreter: .venv-imessage/bin/python3
```
**Classification: RUNNING — do not touch.**  
Active in logs: sending/receiving iMessages as of 07:15 today. Responds to X links forwarded by Matt (+19705193013) and queues them for x-intake analysis. Core messaging pipeline, healthy.

---

### 3. polymarket-hourly — BROKEN ⛔
```
Exit: 2  Script: integrations/polymarket/polymarket_hourly_scan.py — MISSING
Interpreter: /usr/bin/python3 (system Python — wrong)
Schedule: 9am–8pm hourly (12 fires/day)
```
**Classification: retire_unload.**  
The entire `trading/` directory contains only `__pycache__`, `core/`, `logs/`, `state/`, `WORK_IN_PROGRESS.md` — no Python scripts. All polymarket and trading batch scripts were deleted. Log is empty (never ran successfully with current state). No money risk — can't reach any API without the script.

---

### 4. polymarket-scan — BROKEN ⛔
```
Exit: 2  Script: integrations/polymarket/polymarket_scan.py — MISSING
Interpreter: /usr/bin/python3
Interval: 600s (every 10 min)
Log: "Failed to reach trading API: Connection refused / HTTP 404"
```
**Classification: retire_unload.**  
Script missing. When it last ran (old copy), it only reached the trading API anyway — which was also failing. No autonomous trading capability without the script. Safe to unload.

---

### 5. trading-api (duplicate entry — see #1 above)
Script exists, currently running. Not broken.

---

### 6. imessage-bridge (duplicate entry — see #2 above)
Currently running and healthy.

---

### 7. email-reply-agent — BROKEN + MESSAGING RISK ⚠️
```
Exit: 1  Module: symphony.email.cli — MISSING
Interpreter: /opt/homebrew/bin/python3
Interval: 300s (every 5 min)
Mode: --mode auto --days 2 --limit 60
Log: "✉️ Running Bob reply agent (auto mode)..." (no success output — module fails to import)
```
**Classification: needs_matt_approval.**  
Module is missing so currently harmless. But the flag `--mode auto` means if `symphony.email.cli` is installed, it will auto-send email replies every 5 minutes without any approval gate. High messaging risk. Needs a review of what auto mode does before reinstalling the module.

---

### 8. voice-webhook — PORT CONFLICT ⛔
```
Exit: 1  Script: api/voice_webhook.py — EXISTS
Interpreter: /usr/bin/python3 (wrong — needs flask, not installed on system Python)
Port: 8088
```
**Classification: keep_and_fix.**  
Port 8088 is occupied by `markup-app` (PID 762, running and healthy). `voice_webhook.py` tries to bind the same port, fails immediately. Two fixes needed: (1) change interpreter to `/opt/homebrew/bin/python3`, (2) give it a different port (suggest 8093 or update `.env`). Not a risk while broken — iPad voice commands just fail silently.

---

### 9. x-autoposter — DISABLED ✅ (per policy — not in failing list)
```
LastExitStatus: 0  No PID (not running)
Content generation: BROKEN (system Python missing `requests`)
```
**Status confirmed disabled.** Not in the failing list. Remains broken by accidental dependency. Do not fix — per audit policy this must stay disabled.

---

## Full Agent Classification Table

| Agent | Exit | Script Exists? | Root Cause | Classification |
|---|---|---|---|---|
| `notes-watcher` | 2 | ❌ MISSING | `tools/notes_watcher.py` deleted | **retire_unload** |
| `employee-beatrice-bot` | 127 | ❌ MISSING | `telegram-bob-remote/start_employee_bot.sh` deleted | **retire_unload** |
| `polymarket-hourly` | 2 | ❌ MISSING | Script deleted, all trading scripts gone | **retire_unload** |
| `bob-maintenance` | 1 | ✅ EXISTS | Exits 1 after Docker disk check — likely cosmetic | **keep_and_fix** |
| `voice-webhook` | 1 | ✅ EXISTS | Port 8088 conflict with markup-app; wrong interpreter | **keep_and_fix** |
| `trading-provider-slo-monitor` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `service-sre-loop` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `focus-ops-monitor` | 2 | ❌ MISSING | `tools/focus_ops_monitor.py` deleted | **retire_unload** |
| `failure-replay-queue` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `approval-drainer` | 1 | ✅ (in container) | `sqlite3.DatabaseError: database disk image is malformed` | **needs_matt_approval** |
| `email-project-intake` | 1 | ❌ module missing | `symphony.email.cli` not installed | **retire_unload** |
| `trading-research-bot-hourly` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `watcher` | 1 | ❌ module missing | `orchestrator.autonomous_watcher` deleted; log from 2026-03-22 | **retire_unload** |
| `daily-digest` | 1 | ✅ EXISTS | Appears to run successfully (sent digest today); exit 1 may be occasional | **keep_and_fix** |
| `trading-research-daily-digest` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `quality-gate-nightly` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `trading-pnl-attribution-daily` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `notes-sync` | 1 | ✅ (shell cmd) | `notes_indexer.py` fails: `ModuleNotFoundError: yaml` | **keep_and_fix** |
| `trading-topic-graph-daily` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `markup-app` | 1 | ✅ EXISTS | **Actually running** (PID 762, port 8088). Old exit code. | **RUNNING** |
| `subscription-audit` | 2 | ❌ MISSING | `integrations/telegram/subscription_audit.py` deleted | **retire_unload** |
| `graph-drift-watcher-daily` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `trading-api` | -15 | ✅ EXISTS | **Running** (PID 98451, :8421 healthy) | **RUNNING** |
| `trading-research-quality-weekly` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `core-ops-health-hourly` | 2 | ❌ MISSING | `orchestrator/core_ops_alert_runner.py` deleted | **retire_unload** |
| `email-reply-agent` | 1 | ❌ module missing | `symphony.email.cli` missing; auto-send risk on restore | **needs_matt_approval** |
| `decision-hygiene-hourly` | 2 | ❌ MISSING | `trading/` directory cleared | **retire_unload** |
| `imessage-watcher` | 1 | ✅ EXISTS | Exit 1 — log mixes with bob-maintenance; needs log check | **keep_and_fix** |
| `polymarket-scan` | 2 | ❌ MISSING | Script deleted | **retire_unload** |
| `signal-action-hourly` | 2 | ❌ MISSING | `trading/signal_action_runner.py` deleted | **retire_unload** |
| `incoming-tasks` | 2 | ❌ MISSING | `orchestrator/incoming_task_processor.py` deleted | **retire_unload** |
| `imessage-bridge` | -15 | ✅ EXISTS | **Running** (PID 2421, active message relay) | **RUNNING** |
| `overnight-learner` | 2 | ❌ MISSING | `tools/overnight_learner.py` deleted | **retire_unload** |
| `mobile-api` | 2 | ❌ MISSING | `api/mobile_api.py` deleted (only legacy version exists) | **retire_unload** |

---

## Root Cause Analysis by Cluster

### Cluster A: `trading/` script mass-deletion (13 agents)
All of these reference scripts under `trading/` which has been reduced to only `core/`, `logs/`, `state/` subdirs:
- trading-provider-slo-monitor, service-sre-loop, failure-replay-queue,
  trading-research-bot-hourly, trading-research-daily-digest, quality-gate-nightly,
  trading-pnl-attribution-daily, trading-topic-graph-daily, graph-drift-watcher-daily,
  trading-research-quality-weekly, decision-hygiene-hourly, signal-action-hourly,
  polymarket-hourly, polymarket-scan

**Action: unload all 13 plists in one pass.**

### Cluster B: `orchestrator/` module gone (2 agents)
- `watcher` (orchestrator.autonomous_watcher)
- `core-ops-health-hourly` (orchestrator/core_ops_alert_runner.py)
- `incoming-tasks` (orchestrator/incoming_task_processor.py)

**Action: unload 3 plists.**

### Cluster C: `symphony.email` module missing (2 agents)
- `email-project-intake` — module missing, intake only (lower risk)
- `email-reply-agent` — module missing, **auto-send mode** (higher risk)

**Action: unload email-project-intake. Hold email-reply-agent for Matt decision on auto-mode policy.**

### Cluster D: Individual missing scripts (5 agents)
- notes-watcher (notes_watcher.py deleted)
- employee-beatrice-bot (start_employee_bot.sh deleted)
- subscription-audit (subscription_audit.py deleted)
- overnight-learner (overnight_learner.py deleted)
- mobile-api (mobile_api.py deleted)

**Action: unload all 5.**

---

## Money-Risk Agents

| Agent | Risk | Current State |
|---|---|---|
| `trading-api` | Exposes `/invest/scan`, `/invest/research`, portfolio endpoints | RUNNING — intentional |
| `polymarket-scan` | Fetched markets, checked for trading opportunities | BROKEN (script missing) |
| `polymarket-hourly` | Ran hourly market scan | BROKEN (script missing) |
| `signal-action-hourly` | Executed trading signal actions | BROKEN (script missing) |
| `failure-replay-queue` | Replayed failed trades | BROKEN (script missing) |

**Current money risk: LOW** — all autonomous trading scripts are missing. Only the trading-api server (read/compute) is live, which requires explicit API calls to trigger any action.

---

## Messaging-Risk Agents

| Agent | Channel | Frequency | Current State |
|---|---|---|---|
| `imessage-bridge` | iMessage | Continuous (20s poll) | RUNNING — sends replies to Matt |
| `email-reply-agent` | Email | Every 5 min (auto mode) | BROKEN (module missing) — risk if module restored |
| `daily-digest` | Telegram | 6am + 8pm | Appears working — sends to Matt only |
| `approval-drainer` | iMessage/Telegram | 2am daily | BROKEN (malformed DB) |

---

## Recommended Cleanup Order

### Pass 1 — Safe unload (no risk, scripts confirmed missing):
```bash
# 21 agents with missing scripts — safe to unload immediately
launchctl unload ~/Library/LaunchAgents/com.symphony.notes-watcher.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.employee-beatrice-bot.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.polymarket-hourly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-provider-slo-monitor.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.service-sre-loop.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.focus-ops-monitor.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.failure-replay-queue.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.email-project-intake.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-research-bot-hourly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.watcher.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-research-daily-digest.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.quality-gate-nightly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-pnl-attribution-daily.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-topic-graph-daily.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.subscription-audit.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.graph-drift-watcher-daily.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.trading-research-quality-weekly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.core-ops-health-hourly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.decision-hygiene-hourly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.polymarket-scan.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.signal-action-hourly.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.incoming-tasks.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.overnight-learner.plist
launchctl unload ~/Library/LaunchAgents/com.symphony.mobile-api.plist
```

### Pass 2 — Fix and keep (requires small fixes):
1. **notes-sync** — `pip3 install pyyaml` for the notes_indexer step
2. **voice-webhook** — reassign port away from 8088; switch to `/opt/homebrew/bin/python3`
3. **bob-maintenance** — investigate exit 1 (likely cosmetic — output looks healthy)
4. **daily-digest** — investigate intermittent exit 1 (appears functional)
5. **imessage-watcher** — check log isolation from bob-maintenance

### Pass 3 — Needs Matt decision:
1. **approval-drainer** — malformed SQLite DB inside openclaw. Need to inspect/repair or rebuild the DB before re-enabling. Contains approval workflow state.
2. **email-reply-agent** — `--mode auto` is high risk. Define what "auto" sends before restoring the module. Consider switching to `--mode suggest` first.

### Do NOT touch:
- `com.symphony.trading-api` — running, healthy
- `com.symphony.imessage-bridge` — running, actively relaying messages
- `com.symphony.markup-app` — running on port 8088
- `com.symphony.x-autoposter` — intentionally broken, must stay that way
