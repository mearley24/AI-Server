# Prompt V — CLAUDE.md Accuracy Pass

Read CLAUDE.md first. Then read STATUS_REPORT.md. The audit found several inaccuracies in CLAUDE.md itself. Fix them all.

## FIXES REQUIRED

### 1. Service Table — Wrong Ports and Missing Services

The "Docker Services Quick Reference" table in CLAUDE.md has errors. Rebuild it from the actual `docker-compose.yml` and running containers.

Run:
```zsh
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>&1
grep -E "^\s+\w+.*:" docker-compose.yml | head -30
```

Known issues from STATUS_REPORT:
- **notification-hub** is port **8095** and Python, NOT 8091/Node.js
- **proposals** (port **8091**) is completely missing from the table
- **browser-agent** (9091) does NOT exist — remove it
- **mission-control** was removed in Prompt S — delete it from the table
- **cortex** is now at **8102** and serves the dashboard — add it properly
- **voice-receptionist** external port is **8093**, internal 3000
- **calendar-agent** is **8094**
- **clawwork** is **8097**
- **context-preprocessor** is **8028**
- **intel-feeds** is **8765**
- **knowledge-scanner** is **8100**
- **openwebui** external port is **3000**, internal 8080
- **x-intake** is **8101**

Rebuild the ENTIRE service table with accurate data. Include every service in docker-compose.yml. Format:

| Service | Port | Language | Notes |
|---|---|---|---|

### 2. Repo Structure — Cortex Path

CLAUDE.md says `integrations/cortex/` but cortex lives at the **top-level** `cortex/` directory. Fix the repo map tree to show `cortex/` at root level, not under integrations/.

### 3. Inter-Service Communication — Update Cortex

Mission Control references should be removed. Cortex is now:
- Dashboard: `http://cortex:8102/dashboard`
- API: `http://cortex:8102/api/*`
- Memory: `http://cortex:8102/remember`
- Health: `http://cortex:8102/health`

### 4. Startup Health Checks — Update

Replace the mission-control health check line with cortex:
```zsh
curl -s http://127.0.0.1:8102/health                 # cortex brain + dashboard
```

Remove:
```zsh
curl -s http://127.0.0.1:8098/health                 # mission control alive?
```

### 5. Quick Commands — Update

Replace any `mission-control` references with `cortex`:
```zsh
# Old
docker compose restart openclaw mission-control

# New
docker compose restart openclaw cortex
```

### 6. Common Failure Modes — Add New Entry

Add to the failure table:
| Cortex orphaned from compose | Service running but not in docker-compose.yml | Every service MUST be defined in docker-compose.yml |

### 7. Verify Against Reality

After making all edits, run a final cross-check:

```zsh
# Every service in compose should appear in CLAUDE.md
grep -E "^\s+\w+:" docker-compose.yml | sed 's/://' | tr -d ' ' | sort > /tmp/compose_services.txt
# Manually verify each one appears in the service table
cat /tmp/compose_services.txt
```

Read through the entire CLAUDE.md one more time and fix anything else that looks wrong or outdated based on what you know from the audit and the Prompt S merge.

### 8. Also update .clinerules

The `.clinerules` file has the same stale info (it references Topletz project which was lost, may have wrong ports). Update it to match the corrected CLAUDE.md. Keep `.clinerules` as a lighter version — it doesn't need the full lessons-learned table, just the project overview, tech stack, coding standards, git rules, and key paths.

Remove any reference to the Topletz project from `.clinerules`. Current active projects are tracked in the symphonysh repo's `src/data/projects.ts`.

Commit and push:
```zsh
git add CLAUDE.md .clinerules
git commit -m "Fix CLAUDE.md and .clinerules accuracy — ports, services, paths"
git push origin main
```
