# Cleanup, Test, Learn — Composer 2 Fast

## CRITICAL: Commit Rules

**YOU MUST commit and push after completing each section.** Work ONLY in /Users/bob/AI-Server/. Do NOT create worktrees.

---

## SECTION 1: Cleanup — Remove Dead Code and Stale Data

### 1A. Remove stale fix scripts from repo root
These one-time scripts have been run and should not be in the repo root:
```bash
cd /Users/bob/AI-Server
rm -f fix-followup-tracker.sh fix-polymarket-and-followups.sh fix-redeemer-and-dust.sh bob-resilience-install.sh bob-security-hardening.sh
```

### 1B. Clean up .backups
The .backups directory has copies from every fix today. Archive it:
```bash
tar czf /Users/bob/AI-Server/data/backups-april5.tar.gz /Users/bob/AI-Server/.backups/
rm -rf /Users/bob/AI-Server/.backups/
echo ".backups/" >> /Users/bob/AI-Server/.gitignore
```

### 1C. Remove duplicate Cursor prompts that have been completed
Move completed prompts to a DONE folder:
```bash
mkdir -p /Users/bob/AI-Server/.cursor/prompts/DONE
mv /Users/bob/AI-Server/.cursor/prompts/ship-everything-april5.md /Users/bob/AI-Server/.cursor/prompts/DONE/
mv /Users/bob/AI-Server/.cursor/prompts/high-impact-wave2-april5.md /Users/bob/AI-Server/.cursor/prompts/DONE/
mv /Users/bob/AI-Server/.cursor/prompts/final-opus-april5.md /Users/bob/AI-Server/.cursor/prompts/DONE/
```

### 1D. Gitignore sensitive and generated files
Verify /Users/bob/AI-Server/.gitignore includes:
```
.backups/
polymarket-bot/vpn/
redis/redis.conf
*.db
*.db-journal
*.db-wal
data/**/*.json
!data/.gitkeep
__pycache__/
*.pyc
.env
```

### 1E. Commit
```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "cleanup: remove one-time scripts, archive backups, organize prompts" && git push origin main
```

---

## SECTION 2: Test — Smoke Test Every Service

Create /Users/bob/AI-Server/scripts/smoke-test-full.sh:

```bash
#!/usr/bin/env bash
# Full smoke test for all 18 services
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
    local name="$1" result="$2"
    if [[ "$result" == "PASS" ]]; then
        echo -e "  ${GREEN}✓${NC} $name"
        ((PASS++))
    elif [[ "$result" == "WARN" ]]; then
        echo -e "  ${YELLOW}⚠${NC} $name"
        ((WARN++))
    else
        echo -e "  ${RED}✗${NC} $name"
        ((FAIL++))
    fi
}

echo "========================================="
echo "Full Smoke Test — $(date)"
echo "========================================="

echo ""
echo "--- Container Health ---"
EXPECTED_CONTAINERS="redis openclaw email-monitor notification-hub calendar-agent proposals dtools-bridge mission-control knowledge-scanner clawwork voice-receptionist openwebui remediator vpn polymarket-bot intel-feeds x-intake context-preprocessor"
RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null)
for c in $EXPECTED_CONTAINERS; do
    if echo "$RUNNING" | grep -q "^${c}$"; then
        health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "no-healthcheck")
        if [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then
            check "$c" "PASS"
        else
            check "$c ($health)" "WARN"
        fi
    else
        check "$c (NOT RUNNING)" "FAIL"
    fi
done

echo ""
echo "--- API Endpoints ---"

# OpenClaw
if curl -sf http://127.0.0.1:8099/health >/dev/null 2>&1; then
    check "OpenClaw /health" "PASS"
else
    check "OpenClaw /health" "FAIL"
fi

# Briefing status
if curl -sf http://127.0.0.1:8099/briefing/status >/dev/null 2>&1; then
    check "OpenClaw /briefing/status" "PASS"
else
    check "OpenClaw /briefing/status" "FAIL"
fi

# Email monitor
if curl -sf http://127.0.0.1:8092/health >/dev/null 2>&1; then
    check "Email Monitor /health" "PASS"
else
    check "Email Monitor /health" "FAIL"
fi

# Mission Control (with auth)
MC_TOKEN=$(grep MISSION_CONTROL_TOKEN /Users/bob/AI-Server/.env 2>/dev/null | cut -d= -f2)
if [[ -n "$MC_TOKEN" ]]; then
    if curl -sf "http://127.0.0.1:8098/health" >/dev/null 2>&1; then
        check "Mission Control /health (no auth)" "PASS"
    else
        check "Mission Control /health" "FAIL"
    fi
    if curl -sf "http://127.0.0.1:8098/dashboard?token=$MC_TOKEN" >/dev/null 2>&1; then
        check "Mission Control /dashboard (auth)" "PASS"
    else
        check "Mission Control /dashboard (auth)" "WARN"
    fi
else
    check "Mission Control (no token in .env)" "WARN"
fi

# Polymarket bot
if curl -sf http://127.0.0.1:8430/health >/dev/null 2>&1; then
    check "Polymarket Bot /health" "PASS"
else
    check "Polymarket Bot /health" "FAIL"
fi

# X-intake
if curl -sf http://127.0.0.1:8101/health >/dev/null 2>&1; then
    check "X-Intake /health" "PASS"
else
    check "X-Intake /health" "FAIL"
fi

# Intel feeds
if curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
    check "Intel Feeds /health" "PASS"
else
    check "Intel Feeds /health" "FAIL"
fi

echo ""
echo "--- Redis Auth ---"
REDIS_PASS=$(grep "^REDIS_PASSWORD=" /Users/bob/AI-Server/.env 2>/dev/null | cut -d= -f2)
if docker exec redis redis-cli -a "$REDIS_PASS" ping 2>/dev/null | grep -q PONG; then
    check "Redis auth (PONG)" "PASS"
else
    check "Redis auth" "FAIL"
fi
if redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG; then
    check "Redis NO auth (should fail)" "FAIL"
else
    check "Redis rejects unauthenticated" "PASS"
fi

echo ""
echo "--- Port Security ---"
EXPOSED=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep "0.0.0.0" | grep -v "8098")
if [[ -z "$EXPOSED" ]]; then
    check "All ports 127.0.0.1 (except MC 8098)" "PASS"
else
    check "Exposed ports found: $EXPOSED" "FAIL"
fi

echo ""
echo "--- Watchdog ---"
if launchctl list 2>/dev/null | grep -q "com.symphony.bob-watchdog"; then
    check "Watchdog daemon running" "PASS"
else
    check "Watchdog daemon" "FAIL"
fi
if [[ -f /usr/local/var/log/bob-watchdog.log ]]; then
    LAST_TICK=$(tail -1 /usr/local/var/log/bob-watchdog.log 2>/dev/null | grep -o '20[0-9-]* [0-9:]*' | head -1)
    check "Watchdog last tick: $LAST_TICK" "PASS"
else
    check "Watchdog log missing" "WARN"
fi

echo ""
echo "--- iMessage Bridge ---"
if launchctl list 2>/dev/null | grep -q "com.symphony.imessage-bridge"; then
    check "iMessage bridge running" "PASS"
else
    check "iMessage bridge" "FAIL"
fi
if tail -5 /tmp/imessage-bridge.log 2>/dev/null | grep -q "Watching for handles"; then
    check "iMessage watching handles" "PASS"
fi

echo ""
echo "--- Trading Bot ---"
# Recent trades
RECENT_TRADES=$(docker logs polymarket-bot --since 10m 2>&1 | grep "copytrade_copy_executed" | wc -l | tr -d ' ')
check "Copytrade trades (last 10m): $RECENT_TRADES" "PASS"

# Arb scanner
ARB_FOUND=$(docker logs polymarket-bot --since 10m 2>&1 | grep "arb_negative_risk_found" | tail -1 | grep -o '"count": [0-9]*' | grep -o '[0-9]*')
check "Arb opportunities found: ${ARB_FOUND:-0}" "PASS"

# Weather scanner
WEATHER=$(docker logs polymarket-bot --since 10m 2>&1 | grep "weather_tick_complete" | tail -1)
if echo "$WEATHER" | grep -q "candidates"; then
    CANDIDATES=$(echo "$WEATHER" | grep -o '"candidates": [0-9]*' | grep -o '[0-9]*')
    check "Weather candidates: ${CANDIDATES:-0}" "PASS"
else
    check "Weather ticker not running" "WARN"
fi

# Redeemer
REDEEMED=$(docker logs polymarket-bot --since 1h 2>&1 | grep "redeemer_complete" | tail -1)
if [[ -n "$REDEEMED" ]]; then
    check "Redeemer active: $REDEEMED" "PASS"
else
    check "Redeemer (no recent activity)" "WARN"
fi

echo ""
echo "--- Data Integrity ---"
# Follow-ups
FU_COUNT=$(sqlite3 /Users/bob/AI-Server/data/openclaw/follow_ups.db "SELECT COUNT(*) FROM follow_ups" 2>/dev/null || echo "0")
check "follow_ups rows: $FU_COUNT" "$([ "$FU_COUNT" -gt 0 ] && echo PASS || echo FAIL)"

# Decision journal
DJ_COUNT=$(sqlite3 /Users/bob/AI-Server/data/openclaw/decision_journal.db "SELECT COUNT(*) FROM decisions" 2>/dev/null || echo "0")
check "Decision journal entries: $DJ_COUNT" "$([ "$DJ_COUNT" -gt 0 ] && echo PASS || echo FAIL)"

# Email DB
EMAIL_COUNT=$(sqlite3 /Users/bob/AI-Server/data/email-monitor/emails.db "SELECT COUNT(*) FROM emails" 2>/dev/null || echo "0")
check "Email DB entries: $EMAIL_COUNT" "$([ "$EMAIL_COUNT" -gt 0 ] && echo PASS || echo FAIL)"

# Jobs DB
JOBS=$(sqlite3 /Users/bob/AI-Server/data/openclaw/jobs.db "SELECT COUNT(*) FROM jobs" 2>/dev/null || echo "0")
check "Jobs DB entries: $JOBS" "$([ "$JOBS" -gt 0 ] && echo PASS || echo FAIL)"

echo ""
echo "========================================="
echo -e "  ${GREEN}PASS: $PASS${NC}  ${YELLOW}WARN: $WARN${NC}  ${RED}FAIL: $FAIL${NC}"
echo "========================================="
```

Make executable: `chmod +x /Users/bob/AI-Server/scripts/smoke-test-full.sh`

### 2B. Commit
```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "test: comprehensive smoke test for all 18 services" && git push origin main
```

---

## SECTION 3: Learn — Trading Journal + Project Retrospective

### 3A. Create trading learning system

Create /Users/bob/AI-Server/polymarket-bot/src/trade_learner.py:

This module runs daily (triggered by the orchestrator's morning briefing tick) and:

1. Reads all trades from data/polymarket/trades.csv
2. Groups by category (weather, sports, crypto, politics, etc.)
3. Calculates per-category stats:
   - Total trades, wins, losses
   - Win rate
   - Average P/L per trade
   - Total P/L
   - Average hold time
   - Best trade, worst trade
4. Compares this week vs last week for trends
5. Identifies patterns:
   - Which cities are most profitable for weather?
   - Which wallets have the best signal quality?
   - What entry price range has the best returns?
   - What time of day are trades most profitable?
6. Writes a learning report to data/polymarket/weekly_learning.json:
```json
{
  "generated_at": "2026-04-05T12:00:00Z",
  "period": "2026-03-29 to 2026-04-05",
  "summary": {
    "total_trades": 500,
    "total_pnl": -23.50,
    "best_category": "weather",
    "worst_category": "politics"
  },
  "by_category": {...},
  "by_wallet": {...},
  "by_city": {...},
  "recommendations": [
    "Increase weather allocation — 67% win rate, +$45 P/L",
    "Drop wallet 0xfe78... — 50% WR, negative P/L ratio",
    "Seoul weather overbought — skip for 48h"
  ]
}
```
7. Publishes to Redis: events:trading → {"type": "weekly_learning", "data": {...}}
8. Sends a summary via notification-hub as an iMessage to Matt

### 3B. Create project learning system

Create /Users/bob/AI-Server/openclaw/project_learner.py:

This module runs weekly (Sunday morning) and:

1. Reads all Linear projects and issues via the Linear API or local cache
2. For each project in WON phase:
   - How many issues completed vs total?
   - Average time from issue creation to completion
   - Any overdue issues?
   - Document staleness (last updated dates)
3. Cross-references with follow_ups DB:
   - Client response times
   - Unanswered emails
4. Cross-references with email classification:
   - How many scope change emails detected?
   - Client communication frequency
5. Writes to data/openclaw/project_health.json:
```json
{
  "generated_at": "...",
  "projects": [
    {
      "name": "Topletz — 84 Aspen Meadow Dr",
      "phase": "WON",
      "completion_pct": 35,
      "overdue_issues": 2,
      "last_client_email": "2026-04-04",
      "docs_stale": false,
      "health": "on_track"
    }
  ],
  "alerts": [
    "Topletz: 2 overdue issues (SYM-35, SYM-37)",
    "Topletz: Waiting on signed agreement + $34,609.85 deposit"
  ]
}
```
6. Feeds into the daily briefing — the orchestrator's `maybe_send_briefing()` should include project health

### 3C. Wire learners into the orchestrator

In /Users/bob/AI-Server/openclaw/orchestrator.py:

1. In `maybe_send_briefing()`, before generating the briefing text, call:
   ```python
   try:
       from trade_learner import generate_trading_summary
       trading_summary = generate_trading_summary()
   except Exception:
       trading_summary = ""
   
   try:
       from project_learner import generate_project_health
       project_health = generate_project_health()
   except Exception:
       project_health = ""
   ```

2. Include both summaries in the briefing text:
   ```
   === Daily Briefing — {date} ===
   
   TRADING:
   {trading_summary}
   
   PROJECTS:
   {project_health}
   
   EMAILS:
   {email_summary (already exists)}
   
   CALENDAR:
   {calendar_summary (already exists)}
   ```

3. Add a weekly learning cycle — in the orchestrator's main loop, check if it's Sunday 8 AM MT and run the full weekly analysis (more detailed than daily).

### 3D. Add /learning endpoint to OpenClaw API

In /Users/bob/AI-Server/openclaw/main.py, add:

```python
@app.get("/learning/trading")
async def trading_learning():
    """Latest trading learning report."""
    path = DATA_DIR / "polymarket" / "weekly_learning.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"message": "No learning report yet — runs daily at briefing time"}

@app.get("/learning/projects")  
async def project_learning():
    """Latest project health report."""
    path = DATA_DIR / "project_health.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"message": "No project health report yet — runs weekly Sunday morning"}
```

### 3E. Commit
```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "learn: trading journal, project retrospective, wired into daily briefing" && git push origin main
```

---

## Verify

```bash
# Run the smoke test
bash /Users/bob/AI-Server/scripts/smoke-test-full.sh

# Check learning endpoints
curl -s http://127.0.0.1:8099/learning/trading | python3 -m json.tool
curl -s http://127.0.0.1:8099/learning/projects | python3 -m json.tool
```
