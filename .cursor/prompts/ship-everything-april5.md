# Ship Everything — April 5, 2026

## Context

Bob (Mac Mini M4) runs the AI-Server Docker stack — 16 services, all healthy. Tonight we hardened the infrastructure (watchdog daemon, Redis auth, port lockdown, DNS auto-recovery). Now it's time to close every open gap in the system.

This prompt covers 14 items across 4 priorities. Work through them in order. Every change must be backward-compatible and not break existing healthy services.

**Volume mounts are live** — editing files under `./openclaw/`, `./email-monitor/`, `./mission_control/`, etc. takes effect on container restart. No rebuild needed unless Dockerfile/requirements change.

**Redis requires auth now** — all services connect via `REDIS_URL=redis://:PASSWORD@redis:6379` from docker-compose.yml env vars. The polymarket-bot uses `host.docker.internal` instead of `redis` because it runs on the VPN network. Never hardcode `redis://redis:6379` without auth.

**All ports must bind to 127.0.0.1** — never `0.0.0.0`. The only exception is Mission Control (see P1-1 below) which needs Tailscale network access.

---

## P0 — Revenue & Client Impact

### P0-1: Scope Tracker Pipeline

**Status**: Cursor prompt exists at `.cursor/prompts/scope-tracker-pipeline.md` — never run.
**What to build**: Read that prompt and implement it fully.

Summary of what's needed:
- In `openclaw/orchestrator.py` `check_emails()`: after existing email classification, detect scope change emails using keyword matching
- Auto-create Linear issues tagged to the project when scope changes are detected
- Track which documents need updating when scope changes are resolved
- Integrate with the existing `follow_up_tracker.py` and `job_lifecycle.py`

The existing prompt has the full architecture. Implement all steps.

### P0-2: Testimonial Collection Flow

**Status**: Cursor prompt exists at `.cursor/prompts/testimonial-collection-flow.md` — never run.
**What to build**: Read that prompt and implement it fully.

Summary:
- Email template for testimonial requests (`proposals/email_templates/testimonial_request.md`)
- Auto-trigger when a job moves to COMPLETED phase in `job_lifecycle.py`
- `/review` page on the Symphony website (or a simple form endpoint)
- Store testimonials in a DB table
- Eventually feed into `symphonysh.com` Testimonials component

The existing prompt has the full architecture. Implement all steps.

### P0-3: Daily Briefing Delivery Verification

**Status**: `maybe_send_briefing()` exists in `orchestrator.py` (line 982). It generates a briefing at 6 AM MT and calls `self.notify("briefing", briefing)` which goes to notification-hub, which sends via iMessage bridge.

**Problem**: Never confirmed the briefing actually arrives on Matt's phone. The chain is:
`orchestrator → notification-hub:8095/notify → POST to iMessage bridge:8199 → AppleScript → Messages.app`

**What to fix**:
1. Add a delivery confirmation log: after `self.notify()`, log the briefing content length and timestamp
2. Add a `/briefing/status` endpoint to OpenClaw that returns:
   - `last_briefing_date` 
   - `last_briefing_delivered` (from notification-hub response)
   - `briefing_content_preview` (first 200 chars)
3. Add a Redis event: `events:system` → `{"type": "briefing.delivered", "data": {"date": today, "length": len(briefing)}}`
4. In the notification-hub response handler, check if the iMessage bridge returned 200 and log success/failure
5. If the briefing fails to deliver, retry once after 5 minutes

### P0-4: Auto-Responder Wiring Verification

**Status**: `auto_responder.py` exists in `openclaw/`. Both `orchestrator.py` (line 461) and `email-monitor/monitor.py` (line 719) import it. The email-monitor import was fixed tonight to use `/app/openclaw` instead of `../openclaw`.

**What to verify and fix**:
1. Verify `auto_respond()` is actually being called on incoming client emails (not just imported)
2. Add a log line before and after `auto_respond()` calls in both orchestrator and email-monitor
3. Verify the Zoho draft creation works (the function creates a draft in Zoho, not a sent email)
4. Add an auto-responder status to the `/health` endpoint: `"auto_responder": {"enabled": true, "last_draft_at": "...", "drafts_created_today": N}`

---

## P1 — System Functionality

### P1-1: Mission Control LAN/Tailscale Access

**Status**: Port is `127.0.0.1:8098` — inaccessible from Matt's phone or laptop.

**What to fix**: Mission Control needs to be accessible from the Tailscale network (100.x.x.x range) but NOT from the general LAN. The approach:

1. Change the port binding in `docker-compose.yml` from `127.0.0.1:8098:8098` to `0.0.0.0:8098:8098`
2. Add authentication to Mission Control — a simple API key or session token:
   - Generate a `MISSION_CONTROL_TOKEN` (add to `.env`)
   - Require `?token=...` query param or `Authorization: Bearer ...` header on all endpoints
   - The dashboard HTML should include the token in requests (read from a config endpoint or embed in the page)
3. Add a note in `knowledge/operations-runbook.md` that Mission Control is the ONE exception to the 127.0.0.1 rule, protected by auth token instead

This way Matt can access `http://[Bob's Tailscale IP]:8098/dashboard?token=...` from his phone.

### P1-2: X/Twitter Intake Pipeline

**Status**: Code exists at `integrations/x_intake/` with `pipeline.py`, `post_fetcher.py`, `analyzer.py`, `bookmark_scraper.py`, `video_transcriber.py`. Well-architected but NOT wired into any Docker service or the orchestrator.

**What to build**:
1. Add an `x-intake` service to `docker-compose.yml`:
   ```yaml
   x-intake:
     container_name: x-intake
     build: ./integrations/x_intake
     restart: unless-stopped
     ports:
       - "127.0.0.1:8101:8101"
     environment:
       - REDIS_URL=${REDIS_URL}
       - IMESSAGE_BRIDGE_URL=http://host.docker.internal:8199
     depends_on:
       redis:
         condition: service_healthy
     networks:
       - default
   ```
2. Create a `Dockerfile` in `integrations/x_intake/` — Python 3.12 slim, install requirements
3. Create a `requirements.txt` with httpx, structlog, redis, yt-dlp (for video transcriber)
4. Create a `main.py` entry point that:
   - Starts the Redis subscriber from `pipeline.py`
   - Also runs a FastAPI health endpoint on 8101
5. Wire it so: when Matt texts Bob an X/Twitter link, the iMessage bridge publishes to Redis → x-intake picks it up → analyzes the post → sends the summary back via iMessage
6. Also add a `/analyze` POST endpoint so other services can submit X links programmatically

### P1-3: Kraken Avellaneda Market Maker

**Status**: Code exists at `polymarket-bot/strategies/crypto/avellaneda_market_maker.py` (722 lines). NOT in docker-compose. NOT running. Last checked March 24. No `KRAKEN_API_KEY` or `KRAKEN_SECRET` in `.env.example` or docker-compose.

**What to build**:
1. Add Kraken env vars to `.env.example`:
   ```
   KRAKEN_API_KEY=
   KRAKEN_SECRET=
   KRAKEN_TRADING_PAIR=XRP/USD
   ```
2. Add a `kraken-bot` service to `docker-compose.yml` OR integrate it as a strategy within the existing polymarket-bot container. Since the Avellaneda market maker is already under `polymarket-bot/strategies/crypto/`, the simplest approach is to add it as an optional strategy that starts if `KRAKEN_API_KEY` is set.
3. In `polymarket-bot/src/main.py`, add:
   ```python
   if os.environ.get("KRAKEN_API_KEY"):
       from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker
       kraken = AvellanedaMarketMaker(config)
       # start it alongside the other strategies
   ```
4. Add health check reporting for Kraken: current P/L, open orders, last tick time
5. Add a `/kraken/status` endpoint to the polymarket-bot health API

### P1-4: Polymarket Position Recovery on Restart

**Status**: `position_syncer.py` exists and loads positions from on-chain data on startup. The logs show `copytrade_positions_loaded: 38, copytrade_positions_restored: 38` on restart. But the weather strategy shows `open_positions: 0` because it tracks positions separately.

**What to fix**:
1. Check if the weather strategy (`weather_scanner.py` or similar) has its own position tracking separate from the copytrade positions
2. If so, make it also restore from the position syncer on startup
3. After position sync completes, log a clear summary: total positions, total value, positions per strategy
4. Ensure `open_positions` in all tick logs reflects the actual synced count, not an empty in-memory set

---

## P2 — Cleanup & Polish

### P2-1: Archive Duplicate Topletz Linear Project

**What to do**: There are two Topletz projects in Linear:
- Original: "Topletz — 84 Aspen Meadow Dr" (the real one with active issues)
- Duplicate: Auto-created on 4/3 with 22 template issues (SYM-41 through SYM-62) sitting in backlog

In `openclaw/project_template.py` or wherever the auto-creation logic lives:
1. Add a check before creating a new project: does a project with this client name already exist?
2. If yes, skip creation and log a warning
3. The duplicate project should be archived via the Linear API (but do NOT do this in the code — just add a comment noting it should be manually archived, or provide a script)

### P2-2: D-Tools Cloud API Key Placeholder

**Status**: D-Tools integration currently works via the browser_agent (Playwright screen scraping). A proper API key has never been generated.

**What to do**:
1. Add `DTOOLS_CLOUD_API_KEY` to `.env.example` with a comment: `# Generate at https://cloud.dtools.com/settings/api`
2. In `openclaw/dtools_sync.py` (or wherever D-Tools is called), add a check: if `DTOOLS_CLOUD_API_KEY` is set, use the REST API; otherwise fall back to the browser agent
3. Don't break the existing browser agent flow — it's working

### P2-3: Clean Up Resolved Polymarket Positions from View

**Status**: The Polymarket Data API returns all historical positions (100+) including zero-balance ones. The dust sweeper (just deployed) handles selling low-value positions. But resolved positions with zero token balance still show up.

**What to fix**: In `position_syncer.py` or the redeemer:
1. After redeeming a position successfully, add its condition_id to a `redeemed_conditions.json` file
2. On the `/positions` endpoint, filter out positions that are in the redeemed set AND have zero on-chain balance
3. The portfolio view should only show positions where the user actually holds tokens

---

## P3 — Low Priority / Deferred

### P3-1: Rename iMacs (Betty & Stagehand)

**What to do**: Add a script at `scripts/rename-imacs.sh` that:
1. Uses `scutil` or `systemsetup` to rename Macs over SSH
2. Betty (64GB iMac) → Maestro
3. Stagehand (the other iMac) → Stagehand (if not already)
4. Include the SSH commands but note: requires SSH access to each iMac

Don't implement anything Docker-related for this — just the rename script.

### P3-2: Get Ollama Running on Maestro

**What to do**: Create a script at `scripts/setup-ollama-maestro.sh` that:
1. SSHes into Maestro (the 64GB iMac)
2. Installs Ollama if not present
3. Pulls models: `llama3.1:70b`, `codellama:34b`
4. Starts the Ollama server
5. Configures the AI-Server stack to use Maestro as an Ollama backend (add `OLLAMA_HOST` env var pointing to Maestro's IP)

Don't implement the SSH part — just create the script with the commands and a README.

---

## Verification

After implementing everything, run this verification:

```bash
# 1. All services up
docker ps --format "table {{.Names}}\t{{.Status}}" | wc -l
# Should be 17+ (16 existing + x-intake)

# 2. No 0.0.0.0 ports (except Mission Control 8098 which has auth)
docker ps --format "{{.Ports}}" | grep "0.0.0.0" | grep -v 8098

# 3. Scope tracker detects keywords
docker logs openclaw --tail 50 2>&1 | grep "scope_change"

# 4. Auto-responder status
curl -s http://127.0.0.1:8099/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('auto_responder', 'NOT FOUND'))"

# 5. Briefing status
curl -s http://127.0.0.1:8099/briefing/status | python3 -m json.tool

# 6. Mission Control accessible with auth
curl -s http://127.0.0.1:8098/health?token=$(grep MISSION_CONTROL_TOKEN .env | cut -d= -f2)

# 7. X-intake running
docker logs x-intake --tail 5 2>&1

# 8. Kraken status (if API key is set)
curl -s http://127.0.0.1:8430/kraken/status 2>/dev/null | python3 -m json.tool || echo "Kraken not configured (no API key)"

# 9. Position count on restart matches
docker logs polymarket-bot --tail 50 2>&1 | grep "positions_loaded\|positions_restored"

# 10. Duplicate project guard
grep "project.*already.*exists\|duplicate.*project" openclaw/project_template.py
```

## Files to Create/Modify

| File | Action | Item |
|------|--------|------|
| `openclaw/orchestrator.py` | MODIFY | P0-1 (scope tracker), P0-3 (briefing), P0-4 (auto-responder) |
| `openclaw/scope_tracker.py` | CREATE | P0-1 |
| `openclaw/job_lifecycle.py` | MODIFY | P0-2 (testimonial trigger) |
| `proposals/email_templates/testimonial_request.md` | CREATE | P0-2 |
| `openclaw/testimonial_collector.py` | CREATE | P0-2 |
| `mission_control/main.py` | MODIFY | P1-1 (auth token) |
| `docker-compose.yml` | MODIFY | P1-1 (port), P1-2 (x-intake service), P1-3 (Kraken env) |
| `integrations/x_intake/Dockerfile` | CREATE | P1-2 |
| `integrations/x_intake/main.py` | CREATE | P1-2 |
| `integrations/x_intake/requirements.txt` | CREATE | P1-2 |
| `polymarket-bot/src/main.py` | MODIFY | P1-3 (Kraken startup), P1-4 (position log) |
| `polymarket-bot/src/position_syncer.py` | MODIFY | P1-4 |
| `openclaw/project_template.py` | MODIFY | P2-1 (duplicate guard) |
| `.env.example` | MODIFY | P1-1 (MC token), P1-3 (Kraken), P2-2 (D-Tools API) |
| `openclaw/dtools_sync.py` | MODIFY | P2-2 (API key check) |
| `polymarket-bot/src/redeemer.py` | MODIFY | P2-3 (redeemed tracking) |
| `scripts/rename-imacs.sh` | CREATE | P3-1 |
| `scripts/setup-ollama-maestro.sh` | CREATE | P3-2 |
| `knowledge/operations-runbook.md` | MODIFY | P1-1 (MC auth note) |

## Constraints

- Do NOT rebuild Docker images unless Dockerfile or requirements change
- Do NOT break existing healthy services
- All new ports bind to `127.0.0.1` (except Mission Control with auth)
- All Redis URLs use the authenticated format from env vars
- All new services need `restart: unless-stopped` and healthchecks
- Test each item independently before moving to the next
- Commit after each priority level (P0, P1, P2, P3)
