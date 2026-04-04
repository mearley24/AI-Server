# Wrap It Up — Final Cursor Prompt

## Context
This is the LAST prompt. It merges three documents into one pass:
- `finish-line.md` — 10 missing files that AGENTS.md references
- `ship-it.md` — Mission Control polish + operational hardening + smoke test
- `perplexity-computer-handoff.md` — D-Tools proposal workflow, optional service tagging, env verification

**Read every file referenced below before editing.** Do not rewrite existing working code. Only create missing files and make targeted edits.

---

## PART A: Create All Missing Files

### A1. `openclaw/continuous_learning.py` (P0)
Mines decision journal + trading outcomes → writes to `knowledge/cortex/learnings.md`. Also reads email classifications if the email DB is accessible. See `finish-line.md` §1 for the full implementation. Create exactly as specified — SQLite reads from decision_journal.db and cost_tracker.db, grouped by category, appended to cortex.

### A2. `openclaw/task_board.py` (P1)
CLI task queue with `add`, `list`, `complete` subcommands. SQLite at `DATA_DIR/task_board.db`. See `finish-line.md` §2 for the full implementation.

### A3. `setup/nodes/configure_bob_always_on.sh` (P1)
`pmset` commands to prevent sleep, enable wake-on-LAN, auto-restart. See `finish-line.md` §3. Make executable (`chmod +x`).

### A4. `setup/nodes/BOB_24_7_RUNBOOK.md` (P1)
Always-on operational runbook with setup, manual checks, monitoring, and recovery sections. See `finish-line.md` §3.

### A5. `knowledge/cortex/learnings.md` (P1)
Seed file with initial system knowledge (16 services, D-Tools scanning 100 opps, weather top category, Steve Topletz active client, C4+Samsung+Episode+Araknis standard stack). See `finish-line.md` §4.

### A6. `tools/bob_maintenance.py` (P1)
Docker prune (72h filter), log truncation (>10MB), backup cleanup (keep 7 days). `--dry` flag for preview. See `finish-line.md` §5.

### A7. `tools/bob_export_dtools.py` (P2)
D-Tools project export via bridge API. Control4 fallback for ambiguous manufacturers. `search_before_create()` for duplicate prevention. See `finish-line.md` §6.

### A8. `knowledge/agents/ULTRA_RUNBOOK.md` (P1)
Session start protocol for Cursor Ultra:
```markdown
# Ultra Runbook — Session Protocol

## Session Start
1. Read AGENTS.md for persistent context
2. Read orchestrator/WORK_IN_PROGRESS.md for current state
3. Check task_board.py for queued work
4. Run smoke-test.sh to verify system health

## Model Selection
- Opus 4.6: multi-file wiring, orchestrator changes, complex debugging
- GPT-5.4 High: greenfield feature code, new modules
- Composer 2 Fast: quick fixes, small edits, file creation
- Sonnet 4.6: general coding, React components

## Handoff
Before ending a session:
1. Update orchestrator/WORK_IN_PROGRESS.md with current state
2. Commit all changes
3. Run smoke-test.sh
4. Note any unfinished items in task_board.py
```

### A9. `orchestrator/WORK_IN_PROGRESS.md` (P1)
```markdown
# Work In Progress

## Current State (auto-updated)
Last session: 2026-04-04

## Active
- Orchestrator ticking every 5 min with full event bus
- Follow-up + payment trackers wired
- D-Tools auto-job creation active
- Decision journal logging + outcome listener running

## Needs Verification
- Follow-up/payment DBs populating with real data
- D-Tools "Won" string matching actual API responses
- Redis events:log filling over time
- Backup cron installed on host

## Queued
- Enable AUTO_RESPONDER_ENABLED when ready
- Approval execution (send email on grant)
- Dropbox auto-folder creation on job creation
- Linear project template creation on job creation
```

### A10. `setup/launchd/com.symphony.learning.plist` (P2)
Sunday 5 AM launchd schedule for continuous_learning.py. See `finish-line.md` §8.

---

## PART B: Wire Continuous Learning into Orchestrator

Edit `openclaw/orchestrator.py`:
- Import and call `continuous_learning.main()` in the weekly Sunday window (same schedule as pattern engine)
- Attribute to employee "beatrice"
- Publish `events:knowledge` / `knowledge.learned`

Check how the pattern engine's weekly schedule works (look for day-of-week check, e.g., `datetime.now().weekday() == 6` for Sunday). Add learning alongside it.

---

## PART C: Mission Control Polish (from ship-it.md Phase 2)

### C1. Settings View
Edit `mission_control/static/index.html` — find the Settings nav view. Replace placeholder with:
- Service ports table (Mission Control :8098, OpenClaw :8099, Email :8092, Calendar :8094, Notifications :8095, D-Tools :8091/:8096, Bot :8430, Redis :6379, WebUI :3000, Preprocessor :8028)
- Quick links to: `/api/services`, `/api/intelligence`, `/api/decisions/recent`, `/events`, `/digest`, `/status`
- Config display: timezone America/Denver, tick interval 5min
- Auto-responder status (fetch from `/status` or check env)

### C2. Digest Markdown
Verify `marked.min.js` is loaded from CDN. In the digest modal render, use `marked.parse(text)` not `textContent`. Add CSS for rendered markdown (headers, lists, code blocks) inside the modal.

### C3. Trading View Mobile
Wrap position tables in `overflow-x: auto` container. When bot fetch fails, show "Bot offline" banner with last cached data from `localStorage`.

---

## PART D: Operational Hardening

### D1. Optional vs Core Service Tagging
Edit `mission_control/main.py` `api_services()` — tag Remediator and ClawWork as `"optional": true` in the service list. The dashboard can then show "Core: 10/10" separately from "Optional: 0/2".

Edit `mission_control/static/index.html` — update the service health badge to show core health vs total:
```javascript
const core = services.filter(s => !s.optional);
const coreHealthy = core.filter(s => s.status === 'healthy').length;
badge.textContent = `Core ${coreHealthy}/${core.length}`;
```

### D2. Backup Cron Documentation
Print at the end of the build:
```
echo ""
echo "=== HOST CRONS TO INSTALL ==="
echo "crontab -e on Bob, add these lines:"
echo ""
echo "0 4 * * * /Users/bob/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1"
echo "0 12 * * * cd /Users/bob/AI-Server && set -a && source .env && set +a && /opt/homebrew/bin/python3 openclaw/daily_briefing.py >> /tmp/briefing.log 2>&1"
echo ""
echo "=== LAUNCHD TO LOAD ==="
echo "launchctl load ~/AI-Server/setup/launchd/com.symphony.learning.plist"
echo ""
```

### D3. Git Hygiene
Check `.gitignore` includes:
```
data/*.db
data/**/*.db
*.db-wal
*.db-shm
.env
backups/
```

If any of these are missing from `.gitignore`, add them.

---

## PART E: Smoke Test

After ALL changes, run the full smoke test:
```bash
docker compose build --no-cache openclaw mission-control
docker compose up -d openclaw mission-control
sleep 90

./scripts/smoke-test.sh

echo ""
echo "=== EXTRA CHECKS ==="
echo "--- Missing files created ---"
for f in openclaw/continuous_learning.py openclaw/task_board.py tools/bob_maintenance.py tools/bob_export_dtools.py setup/nodes/configure_bob_always_on.sh setup/nodes/BOB_24_7_RUNBOOK.md knowledge/cortex/learnings.md knowledge/agents/ULTRA_RUNBOOK.md orchestrator/WORK_IN_PROGRESS.md; do
  [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"
done

echo ""
echo "--- Continuous learning test ---"
python3 openclaw/continuous_learning.py 2>/dev/null && echo "OK" || echo "FAILED (may need DATA_DIR)"

echo ""
echo "--- Task board test ---"
python3 openclaw/task_board.py add "Smoke test task" --priority low 2>/dev/null && python3 openclaw/task_board.py list 2>/dev/null || echo "FAILED"

echo ""
echo "--- Maintenance dry run ---"
python3 tools/bob_maintenance.py --dry 2>/dev/null | tail -3 || echo "FAILED"
```

Print results. Note any failures and suggest fixes.
