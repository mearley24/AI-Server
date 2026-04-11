# Prompt U — Client Portal Health + DB Consolidation

Read CLAUDE.md first. STATUS_REPORT.md flagged two P1 issues: client-portal has no /health endpoint, and the jobs DB has scattered tables.

## TASK 1: Fix Client Portal Health Check

The client-portal container reports "unhealthy" because its Docker healthcheck hits `/health` which returns 404.

1. Open `client-portal/main.py`
2. Add a health endpoint:
   ```python
   @app.get("/health")
   async def health():
       return {"status": "ok", "service": "client-portal"}
   ```
3. Rebuild: `docker compose up -d --build client-portal`
4. Verify: `docker compose ps` should show client-portal as "healthy"

## TASK 2: DB Consolidation — Follow-ups

Current state (from STATUS_REPORT):
- `data/openclaw/jobs.db` has a `follow_up_log` table with **0 rows**
- `data/openclaw/follow_ups.db` has a `follow_ups` table with **58 rows**
- Both exist, causing confusion about the canonical home

Decision: **`follow_ups.db` is canonical.** It has real data. Kill the empty duplicate.

1. Drop the empty `follow_up_log` table from `jobs.db`:
   ```zsh
   sqlite3 data/openclaw/jobs.db "DROP TABLE IF EXISTS follow_up_log;"
   ```
2. Verify `follow_ups.db` still has its data:
   ```zsh
   sqlite3 data/openclaw/follow_ups.db "SELECT COUNT(*) FROM follow_ups;"
   ```
3. Search the codebase for any references to `follow_up_log` in jobs.db context and update them to use `follow_ups.db`:
   ```zsh
   grep -r "follow_up_log" openclaw/ --include="*.py"
   ```
   If any file reads from `jobs.db.follow_up_log`, change it to read from `follow_ups.db.follow_ups`.

## TASK 3: DB Consolidation — Client Preferences

Current state:
- `data/openclaw/jobs.db` has a `client_preferences` table with **0 rows**
- Orchestrator just started a backfill from 200 emails

Decision: **Keep `client_preferences` in `jobs.db`** since it relates to jobs/clients. But verify the backfill is actually populating it:

```zsh
# Check if backfill has run
sqlite3 data/openclaw/jobs.db "SELECT COUNT(*) FROM client_preferences;"

# If still 0, check orchestrator logs for backfill activity
docker logs openclaw --tail 50 2>&1 | grep -i "client_pref\|backfill\|preference"
```

If the backfill code isn't working:
1. Find the backfill function in `openclaw/orchestrator.py` or related files
2. Check why it's not writing rows
3. Fix and restart openclaw

## TASK 4: Document the DB schema

Create `data/DATABASE_SCHEMA.md`:

```markdown
# Symphony AI-Server Database Schema

## jobs.db (data/openclaw/jobs.db)
- `jobs` — Active and historical jobs from D-Tools sync
- `clients` — Client records linked to jobs
- `job_events` — Job lifecycle events
- `client_preferences` — Client communication preferences (backfilled from emails)

## follow_ups.db (data/openclaw/follow_ups.db)
- `follow_ups` — Follow-up tracking with due dates and status

## decision_journal.db (data/openclaw/decision_journal.db)
- `decisions` — All automated decisions with reasoning
- `pending_approvals` — Items awaiting Matt's approval

## emails.db (data/email-monitor/emails.db)
- `emails` — All processed emails with classification
- `notified_emails` — Emails that triggered notifications

## brain.db (data/cortex/brain.db)
- `memories` — Cortex long-term memory
- `decisions` — Cortex decision log
- `goals` — Active goals with progress
- `neural_paths` — Learned patterns
- `improvement_log` — Self-improvement actions
```

Verify each table actually exists before documenting it. Add any tables I missed.

### Verification

```zsh
docker compose ps | grep -E "client-portal|openclaw"
sqlite3 data/openclaw/jobs.db ".tables"
sqlite3 data/openclaw/follow_ups.db ".tables"
sqlite3 data/openclaw/decision_journal.db ".tables"
sqlite3 data/email-monitor/emails.db ".tables"
```

Commit and push:
```zsh
git add -A
git commit -m "Fix client-portal health, consolidate DB schema, document databases"
git push origin main
```
