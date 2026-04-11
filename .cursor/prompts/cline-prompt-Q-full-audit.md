# Prompt Q — Full Project Audit & Status Baseline

You just loaded CLAUDE.md. Prove it by using the context from that file throughout this audit. Do NOT re-explore the codebase from scratch — use the repo map, service ports, and key paths documented in CLAUDE.md.

## TASK: Produce a comprehensive status report of the entire AI-Server stack

### Phase 1: Health Check (use the startup checks from CLAUDE.md)

Run every health check listed in CLAUDE.md's "Startup Health Checks" section. Log the results.

Then check these additional services:
```zsh
curl -s http://127.0.0.1:8092/health    # email-monitor
curl -s http://127.0.0.1:8091/health    # notification-hub
curl -s http://127.0.0.1:8430/health    # polymarket-bot
curl -s http://127.0.0.1:9091/health    # browser-agent
curl -s http://127.0.0.1:8096/health    # client-portal / dtools-bridge
docker compose ps 2>&1                   # all container states
```

### Phase 2: Data Pipeline Verification

Check that data is actually flowing, not just that services are "up":

```zsh
# SQLite databases have real data
for db in data/openclaw/jobs.db data/openclaw/decision_journal.db data/openclaw/follow_ups.db data/email-monitor/emails.db; do
  if [ -f "$db" ]; then
    echo "$db: $(sqlite3 "$db" 'SELECT COUNT(*) FROM sqlite_master WHERE type="table";') tables, $(sqlite3 "$db" 'SELECT name FROM sqlite_master WHERE type="table";' | tr '\n' ', ')"
  else
    echo "MISSING: $db"
  fi
done

# Redis events flowing
docker exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 LRANGE events:log 0 4
docker exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 LLEN events:log

# Cortex memory entries
curl -s http://127.0.0.1:8102/api/stats

# Recent orchestrator activity
docker logs openclaw --tail 30 2>&1 | grep -E "tick|sync|briefing|follow|health"
```

### Phase 3: Prompt History Audit

Read every file in `.cursor/prompts/` (not DONE/ subfolder). For each prompt file, determine:
1. What it was supposed to build/fix
2. Whether the referenced files/features actually exist in the repo now
3. Status: COMPLETE, PARTIAL, or NOT STARTED

Focus especially on:
- Prompts A through P (the Cline series from Perplexity Computer)
- `lessons-learned-april4.md` fixes — which of the 25 lessons have been implemented vs still open
- `close-all-gaps-april10.md` — which of the 6 tasks are done

### Phase 4: File Existence Verification

Verify these specific files exist and have real content (not stubs under 10 lines):

```zsh
files=(
  "openclaw/orchestrator.py"
  "openclaw/main.py"
  "openclaw/daily_briefing.py"
  "openclaw/follow_up_tracker.py"
  "openclaw/follow_up_engine.py"
  "openclaw/dtools_sync.py"
  "openclaw/decision_journal.py"
  "openclaw/continuous_learning.py"
  "openclaw/task_board.py"
  "openclaw/zoho_auth.py"
  "openclaw/doc_staleness.py"
  "openclaw/doc_generator.py"
  "openclaw/outcome_listener.py"
  "integrations/cortex/main.py"
  "integrations/x_intake/main.py"
  "integrations/x_intake/post_fetcher.py"
  "integrations/x_intake/video_transcriber.py"
  "integrations/dtools/dtools_server.py"
  "email-monitor/monitor.py"
  "notification-hub/main.py"
  "mission_control/main.py"
  "mission_control/static/index.html"
  "client-portal/main.py"
  "scripts/pull.sh"
  "scripts/symphony-ship.sh"
  "scripts/smoke-test.sh"
  "scripts/verify-deploy.sh"
  "scripts/set-env.sh"
  "scripts/api-post.sh"
  "scripts/bob-watchdog.sh"
  "scripts/backup-data.sh"
  "tools/bob_maintenance.py"
  "tools/bob_export_dtools.py"
  "knowledge/brand/matt_earley_signature.png"
)

for f in "${files[@]}"; do
  if [ -f "$f" ]; then
    lines=$(wc -l < "$f" 2>/dev/null || echo "binary")
    echo "OK ($lines lines): $f"
  else
    echo "MISSING: $f"
  fi
done
```

### Phase 5: Docker Compose vs Running Reality

Compare what docker-compose.yml defines vs what is actually running:
```zsh
# Services defined in compose
grep -E "^\s+\w+:" docker-compose.yml | grep -v "#" | sed 's/://g' | sort

# Services actually running
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>&1
```

Flag any service defined but not running, or running but not defined.

## OUTPUT

Write the full report to `STATUS_REPORT.md` in the repo root. Structure it as:

1. **Stack Health** — green/yellow/red for each service
2. **Data Pipeline** — what's flowing, what's stale, what's empty
3. **Prompt Completion Matrix** — table of all prompts A-P + operational prompts with status
4. **Missing Files** — anything referenced but not present
5. **Lessons Learned Implementation** — which of the 25 April 4 lessons are fixed vs still open
6. **Open Issues** — prioritized list of what still needs work (P0/P1/P2)
7. **Recommended Next Prompts** — what Claude Code should tackle next, in order

Commit and push when done:
```zsh
git add STATUS_REPORT.md
git commit -m "Add full stack audit and status baseline"
git push origin main
```
