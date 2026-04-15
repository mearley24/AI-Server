<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes. Use printf or write-file patterns instead. -->

# Bob 24/7 Hardening — Launchd, Trading Activation, X-Intake Sandbox

## Objective

Make Bob truly run 24/7 with auto-recovery, activate dormant trading integrations,
and isolate x-intake experiments in their own container. This is a reliability +
revenue prompt.

---

## Phase 1: Launchd Hardening (auto-restart everything)

### 1A. Add KeepAlive to all repo plists that are missing it

These plists in `setup/launchd/` need `<key>KeepAlive</key><true/>` added
inside the top-level `<dict>`:

- `com.symphony.backup-data.plist`
- `com.symphony.business-hours-throttle.plist`
- `com.symphony.learning.plist`
- `com.symphony.network-guard.plist`
- `com.symphony.notes-indexer.plist`
- `com.symphony.smoke-test.plist`

File-watcher, mobile-api, trading-api, and icloud-watch already have it.

### 1B. Audit and commit orphan launchd plists from Bob

Bob has 42+ launchd services that were created directly on the machine and
never committed to the repo. Run this on Bob to find them all:

```
find ~/Library/LaunchAgents -name "com.symphony*" -o -name "com.symphonysh*" | sort
```

For each plist found that is NOT already in `setup/launchd/`:
1. Copy it to `setup/launchd/` in the repo
2. Ensure it has `<key>KeepAlive</key><true/>` for always-on services
3. For scheduled jobs (daily, hourly, weekly), use `StartCalendarInterval` instead of KeepAlive
4. Ensure the `PATH` key includes `/Users/bob/Library/Python/3.9/bin` if it runs Python

Categorize each service:
- **Always-on** (KeepAlive: true): imessage-bridge, imessage-watcher, file-watcher,
  dropbox-organizer, mobile-api, trading-api, bob-maintenance, watcher, incoming-tasks,
  email-reply-agent, memory-guard, worker-betty, employee-beatrice-bot, employee-betty-bot
- **Scheduled** (StartCalendarInterval): daily-digest, overnight-learner, backup-data,
  quality-gate-nightly, trading-research-daily-digest, trading-pnl-attribution-daily,
  trading-topic-graph-daily, graph-drift-watcher-daily, trading-research-quality-weekly
- **Periodic** (StartInterval in seconds): polymarket-hourly, polymarket-scan,
  trading-research-bot-hourly, core-ops-health-hourly, decision-hygiene-hourly,
  signal-action-hourly, service-sre-loop, focus-ops-monitor,
  trading-provider-slo-monitor, subscription-audit
- **Evaluate if needed** (may be dead weight): seo-content, multi-machine-sync-monitor,
  contacts-sync, notes-sync-photos, x-drip, learner-light, markup-app, x-mention-replier,
  betty-learner, voice-webhook

For the "evaluate" category: check if the script/binary the plist points to
actually exists. If the target file is missing, the service is dead weight.
Remove the plist from Bob and do NOT commit it.

### 1C. Create a master restart script

Create `scripts/restart-all-launchd.sh`:
- Unloads then loads every plist in `setup/launchd/`
- Verifies each service started (check exit code via `launchctl list`)
- Prints a summary: service name, PID or exit code, status (running/crashed/scheduled)

---

## Phase 2: Trading Activation

### 2A. Kraken — wire the keys

The `KRAKEN_API_KEY` and `KRAKEN_SECRET` env vars are in docker-compose.yml
but empty in .env. Check if Kraken credentials exist anywhere on Bob:

```
grep -ri "kraken" ~/.env* ~/AI-Server/.env ~/AI-Server/data/ ~/AI-Server/polymarket-bot/ --include="*.env" --include="*.yaml" --include="*.yml" --include="*.json" 2>/dev/null
```

If found, add them to `.env`. If not found, add placeholder lines to `.env`
with a comment that Matt needs to fill them in:

```
KRAKEN_API_KEY=  # Matt: paste your Kraken API key here
KRAKEN_SECRET=   # Matt: paste your Kraken secret here
```

### 2B. Kalshi — add env vars to compose

The Kalshi client (`polymarket-bot/src/platforms/kalshi_client.py`) uses
RSA-PSS auth. It needs these env vars added to the `polymarket-bot` service
in `docker-compose.yml`:

```yaml
- KALSHI_API_KEY=${KALSHI_API_KEY:-}
- KALSHI_PRIVATE_KEY_PATH=${KALSHI_PRIVATE_KEY_PATH:-/data/kalshi_private_key.pem}
- KALSHI_ENV=${KALSHI_ENV:-production}
```

Also add a volume mount for the key file:
```yaml
- ./data/kalshi_private_key.pem:/data/kalshi_private_key.pem:ro
```

Add placeholder lines to `.env`:
```
KALSHI_API_KEY=  # Matt: paste your Kalshi API key
# Place your Kalshi RSA private key PEM at data/kalshi_private_key.pem
```

### 2C. Polymarket — switch from paper to live

In `polymarket-bot/config.example.yaml`, `dry_run` is `true`.
Check if there is a `config.yaml` override on Bob:

```
ls -la ~/AI-Server/polymarket-bot/config.yaml ~/AI-Server/data/config.yaml 2>/dev/null
```

If config.yaml exists and dry_run is true, change it to false.
If no config.yaml exists, create `polymarket-bot/config.yaml` by copying
config.example.yaml and setting:
- `dry_run: false`
- `paper_ledger.enabled: true` (keep paper tracking alongside live)

Do NOT restart the polymarket-bot yet. Just prepare the config.
Add a comment at the top: `# LIVE TRADING - switched from paper mode by hardening prompt`

---

## Phase 3: X-Intake Sandbox Container

### 3A. Create a new Docker service: x-intake-lab

This is an experimental container for x-intake features that go beyond the
basic tweet-link pipeline. It runs alongside the existing x-intake service
without interfering.

Add to `docker-compose.yml`:

```yaml
  x-intake-lab:
    build: ./integrations/x_intake
    container_name: x-intake-lab
    restart: unless-stopped
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=${REDIS_PASSWORD}
      - CORTEX_URL=http://cortex:8102
      - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
      - OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - PYTHONUNBUFFERED=1
      - TZ=America/Denver
      - LAB_MODE=true
    volumes:
      - ./data/transcripts:/data/transcripts
      - ./data/bookmarks:/data/bookmarks
      - x-intake-lab-data:/data/lab
    networks:
      - symphony
    depends_on:
      redis:
        condition: service_healthy
      cortex:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python3", "-c", "import requests; requests.get('http://localhost:8101/health', timeout=3)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

Add the volume at the bottom of docker-compose.yml:
```yaml
  x-intake-lab-data:
```

### 3B. Create the lab entrypoint

Create `integrations/x_intake/lab_main.py`:

This should:
1. Run the transcript analyst on a loop (check for new unanalyzed transcripts every 5 min)
2. Run the bookmark organizer on a schedule (check data/bookmarks/ for new exports every 30 min)
3. Expose a FastAPI health endpoint on port 8101 (different internal port, map to 8103 on host)
4. Subscribe to a Redis channel `x-intake-lab` for ad-hoc commands:
   - `{"action": "analyze_transcript", "path": "/data/transcripts/file.md"}`
   - `{"action": "organize_bookmarks", "path": "/data/bookmarks/export.json"}`
   - `{"action": "scrape_bookmarks"}` (triggers bookmark scraper)
5. Log all activity to Cortex via POST /remember

Actually, map to port 8103 on host:
```yaml
    ports:
      - "127.0.0.1:8103:8101"
```

And add to the gateway SERVICES map in `api/gateway.py`:
```python
"x-intake-lab": "http://localhost:8103",
```

### 3C. Create data directories

Ensure these directories exist (add to scripts/pull.sh):
```
mkdir -p data/transcripts data/bookmarks
```

---

## Phase 4: Cleanup

### 4A. Remove dead Docker containers from Bob

These were removed from docker-compose.yml but containers persist:

```
docker stop knowledge-scanner remediator context-preprocessor 2>/dev/null
docker rm knowledge-scanner remediator context-preprocessor 2>/dev/null
```

### 4B. Remove Supabase references

Check `.env` for any SUPABASE variables and remove them:
```
grep -i supabase .env
```
Delete any lines found (SUPABASE_URL, SUPABASE_KEY, SUPABASE_ANON_KEY, etc.)

### 4C. Update PORTS.md

Add x-intake-lab on port 8103 to PORTS.md.

---

## Verification

After all changes, run:

```
docker compose config --quiet && echo "Compose valid"
```

Then commit and push with message:
```
feat: 24/7 hardening — launchd auto-restart, trading activation, x-intake-lab

- All launchd plists committed to repo with KeepAlive/scheduling
- Master restart script for launchd services
- Kraken + Kalshi env vars wired into compose
- Polymarket switched from paper to live trading config
- x-intake-lab sandbox container for transcript/bookmark experiments
- Dead containers and Supabase references cleaned up
```

Do NOT restart Docker services or launchd — just prepare everything.
Matt will do the restart when ready.
