# Launch Agent Cleanup — Pass 2 Verification
Date: 2026-04-27T14:13:12Z  
Source audit: ops/verification/20260427-135834-retired-launch-agents-pass1.md

---

## Result: 4 agents fixed, 3 agents documented (cannot fix without Matt decision)

---

## Fixed Agents

### 1. notes-sync — FIXED ✅
**Root cause:** `integrations/apple_notes/notes_indexer.py` failed with `ModuleNotFoundError: yaml` because the plist's EnvironmentVariables.PATH was `/usr/local/bin:/usr/bin:/bin` (system Python 3.9, no pyyaml).

**Fix applied:** Updated `~/Library/LaunchAgents/com.symphony.notes-sync.plist` — EnvironmentVariables.PATH changed to `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`.

**Verification:**
- Agent reloaded: `launchctl bootstrap gui/UID` rc=0
- `launchctl list` shows exit 0 after reload
- Manual run: notes_indexer completed successfully, wrote `/Users/bob/AI-Server/data/notes_index.json` (2 notes)
- pyyaml confirmed available in homebrew python3 (version 6.0.1)

---

### 2. voice-webhook — FIXED ✅
**Root cause:** Port 8088 conflict with markup-tool (PID 762) + wrong interpreter (`/usr/bin/python3` missing flask).

**Fix applied:** Updated `~/Library/LaunchAgents/com.symphony.voice-webhook.plist`:
- ProgramArguments[0]: `/usr/bin/python3` → `/opt/homebrew/bin/python3`
- EnvironmentVariables.VOICE_WEBHOOK_PORT: `"8104"` (was 8088, free port confirmed against PORTS.md)

**Verification:**
- Agent reloaded: bootstrap rc=0
- `launchctl list` shows PID 8360, exit 0
- `curl http://127.0.0.1:8104/health` → `{"service":"voice-webhook","status":"ok"}`

---

### 3. bob-maintenance — FIXED ✅
**Root cause:** `tools/bob_maintenance.py` calls `subprocess.run(["docker", "system", "df"])` but `/usr/local/bin/docker` was not in launchd PATH.

**Fix applied:** Added EnvironmentVariables section to `~/Library/LaunchAgents/com.symphony.bob-maintenance.plist`:
```
PATH = /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
```

**Verification:**
- Agent reloaded: bootstrap rc=0
- `launchctl list` shows exit 0 after reload
- Manual run with PATH fix: completed successfully through Docker disk usage section, printed "Done."
- docker binary confirmed at `/usr/local/bin/docker` → symlink to Docker Desktop

---

### 4. daily-digest — FIXED ✅
**Root cause:** plist used `/usr/bin/python3` (system Python), which is missing `aiohttp`. Last successful digest was 2026-03-23. Has been silently failing ever since.

**Fix applied:** Updated `~/Library/LaunchAgents/com.symphony.daily-digest.plist`:
- ProgramArguments[0]: `/usr/bin/python3` → `/opt/homebrew/bin/python3`

**Verification:**
- Agent reloaded: bootstrap rc=0
- `launchctl list` shows exit 0
- Import test: `/opt/homebrew/bin/python3 -c "import aiohttp"` → success
- Next scheduled run: 8 PM today (MT)

---

## Agents Documented — Cannot Fix Without Matt Decision

### 5. approval-drainer — NEEDS MATT DECISION ⚠️
**Root cause:** `/app/data/decision_journal.db` inside openclaw container is malformed.

```
sqlite3.DatabaseError: database disk image is malformed
```

**Scope:** `approval_drain.py` queries `pending_approvals` table in `decision_journal.db`.  
**Table structure confirmed:** Tables `decisions`, `sqlite_sequence`, `pending_approvals` exist (readable from sqlite_master even when data pages are malformed).  
**Other DBs:** All other DBs in openclaw pass integrity_check. Only `decision_journal.db` is affected.

**Risk:** Medium — repairing/replacing will clear the pending approvals backlog. Nightly approval drain (expire >7d items) has been failing since the DB became malformed.

**Recommended action (needs Matt confirmation):**
```bash
# Option A: attempt SQLite dump-and-restore
docker exec openclaw sh -c "sqlite3 /app/data/decision_journal.db .dump | sqlite3 /app/data/decision_journal.db.repaired"
docker exec openclaw mv /app/data/decision_journal.db /app/data/decision_journal.db.bak
docker exec openclaw mv /app/data/decision_journal.db.repaired /app/data/decision_journal.db

# Option B: if dump fails (severe corruption), create fresh DB
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/decision_journal.db.new')
conn.execute('CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, ...)')
conn.execute('CREATE TABLE IF NOT EXISTS pending_approvals (id INTEGER PRIMARY KEY, ...)')
conn.commit()
"
```

---

### 6. imessage-watcher — CANNOT FIX (module deleted) ⛔
**Root cause:** `tools/imessage_watcher.py` imports `from security_utils import hash_text, mask_contact, mask_name, redact_text` but `security_utils.py` was deleted. Only `tools/__pycache__/security_utils.cpython-314.pyc` remains (source gone).

**Last successful run:** 2026-03-24 at 12:16 (over a month ago)

**Current state:** Fails on import immediately, KeepAlive=true causes repeated restarts (drain on system). The log output in `.log` is stale from March 24.

**Overlap with imessage-bridge:** `com.symphony.imessage-bridge` (PID 2421) is running and actively relaying iMessages. imessage-watcher's role of monitoring and logging iMessage activity may be redundant with the bridge.

**Recommended action (needs Matt decision):**
- Option A: Recreate `security_utils.py` with the 4 functions (hash_text, mask_contact, mask_name, redact_text) — low-risk, enables the watcher
- Option B: Unload and archive the plist if functionality is covered by imessage-bridge

---

### 7. email-reply-agent — CONFIRMED HARMLESS, NEEDS POLICY DECISION ⚠️
**Current state:** `symphony.email.cli` module is not installed. Every 5-minute run fails immediately:
```
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named symphony.email.cli
```

**Confirmed:** Cannot auto-send email without the module. Currently harmless.

**Risk if module installed:** `--mode auto` flag sends replies without any human approval gate, to 16 trusted senders every 5 minutes, looking back 2 days, limit 60 emails per run.

**Recommended action (needs Matt decision):** Define auto-mode policy before restoring `symphony.email`. Consider switching plist to `--mode suggest` (drafts only) as the safe default.

---

## Service Health Verification

| Service | Port | Status | Notes |
|---|---|---|---|
| imessage-bridge | 8199 | `{"status":"ok","queue_depth":0}` | ✅ Active |
| trading-api | 8421 | `{"status":"healthy"}` | ✅ Active (PID 5981) |
| markup-tool | 8088 | 404 on /health (no health endpoint) | ✅ PID 762 running |
| voice-webhook | 8104 | `{"service":"voice-webhook","status":"ok"}` | ✅ Fixed |
| cortex | 8102 | `{"status":"alive","memories":{"total":97459,...}}` | ✅ Active |

---

## Test Suite

```
1117 passed, 4 warnings in 13.54s
```
All 1117 tests pass. 4 deprecation warnings only (FastAPI `on_event` → lifespan), no failures.

---

## Full launchctl Symphony Agent Status (post Pass 2)

```
AGENT                                    PID   EXIT  STATE
com.symphony.trading-api                5981   -15   RUNNING (healthy, port 8421)
com.symphony.imessage-bridge            2421   -15   RUNNING (healthy, port 8199)
com.symphony.markup-tool                 762     0   RUNNING (port 8088)
com.symphony.voice-webhook              8360     0   RUNNING FIXED (port 8104)
com.symphony.file-watcher                749     0   Running
com.symphonysh.dropbox-organizer         794     0   Running
com.symphony.bob-maintenance               -     0   Scheduled (weekly Sun 3am) FIXED
com.symphony.task-runner                   -     0   Scheduled
com.symphony.task-runner-watchdog          -     0   Scheduled
com.symphony.bob-watchdog                  -     0   Scheduled
com.symphony.audio-intake                  -     0   Scheduled
com.symphony.network-guard                 -     0   Scheduled
com.symphony.business-hours-throttle       -     0   Scheduled
com.symphony.daily-digest                  -     0   Scheduled (6am/8pm) FIXED
com.symphony.notes-sync                    -     0   Scheduled (4am) FIXED
com.symphony.realized-change-watcher       -     0   Scheduled
com.symphony.smoke-test                    -     0   Scheduled
com.symphony.learning                      -     0   Scheduled
com.symphony.self-improvement              -     0   Scheduled
com.symphony.bluebubbles-health            -     0   Scheduled
com.symphony.bob.workspace                 -     0   Scheduled
com.symphonysh.icloud-watch                -     0   Scheduled
com.symphony.markup-app                    -     1   FAILING (see note below)
com.symphony.approval-drainer              -     1   FAILING (malformed DB — needs Matt)
com.symphony.email-reply-agent             -     1   FAILING (module missing — intentional)
com.symphony.imessage-watcher              -     1   FAILING (security_utils deleted — needs Matt)
```

**Note on markup-app:** Both `markup-app` and `markup-tool` are plists for the same service. `markup-tool` (PID 762) is running healthy. `markup-app` shows exit 1 in launchctl but markup-tool covers the same port. Pre-existing state; not touched in this pass.

---

## Summary of Pass 2 Changes

| Agent | Action | Result |
|---|---|---|
| notes-sync | Updated plist PATH to homebrew, reloaded | ✅ Fixed |
| voice-webhook | Changed port to 8104, interpreter to homebrew, reloaded | ✅ Fixed |
| bob-maintenance | Added PATH with /usr/local/bin, reloaded | ✅ Fixed |
| daily-digest | Changed interpreter to homebrew, reloaded | ✅ Fixed |
| approval-drainer | Identified malformed DB (`decision_journal.db`) | ⚠️ Needs Matt |
| imessage-watcher | Identified missing `security_utils.py` module | ⚠️ Needs Matt |
| email-reply-agent | Confirmed harmless (module absent), documented risk | ⚠️ Needs Matt policy |
