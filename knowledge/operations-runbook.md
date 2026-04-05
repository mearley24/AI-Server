# Symphony Smart Homes — Operations Runbook

This document explains how the Bob AI system works so that anyone (not just Matthew) can understand, operate, and troubleshoot it.

---

## System Overview

**What is Bob?**
Bob is Symphony Smart Homes' AI operations system running on a Mac Mini M4 in Matthew's office. It handles email triage, auto-responses, bid evaluation, daily briefings, project management, and knowledge management — all running 24/7 via Docker.

**Where does Bob live?**
- Hardware: Mac Mini M4 (Apple Silicon, 64GB RAM)
- OS: macOS
- GitHub Repo: `mearley24/AI-Server`
- All services run in Docker containers managed by `docker-compose.yml`

### Services and What They Do

| Service | What It Does | Port |
|---------|-------------|------|
| **OpenClaw** | Main AI orchestration — routes tasks, manages jobs, coordinates agents | 8000 |
| **Email Monitor** | Watches the Zoho inbox, categorizes incoming email, triggers auto-responses | — |
| **Auto-Responder** | Drafts professional email replies for Matthew to review before sending | — |
| **Research Agent** | Looks up products, codes, specs when needed for proposals or client questions | — |
| **Bid Triage** | Evaluates incoming bids/RFPs, texts Matthew BID/PASS/REVIEW | — |
| **Daily Briefing** | Sends Matthew a morning summary via text (Twilio) | — |
| **Notification Hub** | Dispatches notifications (text, email, Telegram) | 8003 |
| **Mission Control** | Event server and health monitoring | 8001 |
| **Redis** | In-memory cache and message queue for inter-service communication | 6379 |

### Where Configs Live

| Config | Location | Purpose |
|--------|----------|---------|
| Environment variables | `.env` on Mac Mini | API keys, credentials, feature flags |
| Docker services | `docker-compose.yml` | Service definitions, ports, volumes |
| Email routing | `email-monitor/routing_config.json` | Who gets categorized how |
| Active clients | `ACTIVE_CLIENT_EMAILS` env var | Which senders get auto-responses |
| OpenClaw config | `setup/openclaw/openclaw.json` | LLM providers, token budgets |
| Agent configs | `agents/` directory | Agent definitions and routing |
| Product knowledge | `knowledge/products/` | Product specs and pricing |
| SOW blocks | `knowledge/sow-blocks/` | Modular scope of work text |
| Project configs | `knowledge/[project]/project-config.yaml` | Per-project scope and settings |

---

## Daily Operations

### Morning Briefing

Bob sends a daily text message to Matthew covering:
- New emails received overnight (categorized)
- Pending items requiring attention
- Active project status updates
- Upcoming deadlines or follow-ups

The briefing runs on a cron schedule. If it doesn't arrive by 9am, check the Troubleshooting section below.

### Checking System Health

Open Terminal on the Mac Mini and run:

```bash
# Check all Docker containers are running
docker compose ps

# Check logs for a specific service (last 50 lines)
docker compose logs --tail 50 openclaw
docker compose logs --tail 50 email-monitor

# Check if Redis is up
docker compose exec redis redis-cli ping
# Should return: PONG

# Restart a single service without affecting others
docker compose restart openclaw
```

All containers should show `Up` status. If any show `Exited` or `Restarting`, check their logs.

### Reviewing Draft Emails

Bob drafts email responses but does NOT send them automatically. To review:

1. Log into Zoho Mail at mail.zoho.com (credentials: info@symphonysh.com)
2. Check the Drafts folder for Bob's prepared responses
3. Review, edit if needed, and send — or delete if not appropriate

---

## Project Lifecycle

Here's how a project flows through the system, from lead to completion:

### 1. New Lead Comes In

```
Email arrives → Email Monitor categorizes → Auto-Responder drafts reply
```

- Email Monitor reads the incoming message and categorizes it (new lead, existing client, vendor, bid, etc.)
- If it's from an active client or a new lead, Auto-Responder drafts a professional reply
- Matthew reviews the draft in Zoho and sends or edits it

### 2. Bid/RFP Arrives

```
Bid email arrives → Bid Triage evaluates → Texts BID/PASS/REVIEW to Matthew
```

- Bid Triage analyzes the project scope, location, timeline, and fit
- **BID**: Good fit — start preparing a proposal
- **PASS**: Not a fit — archive and move on
- **REVIEW**: Needs human judgment — Matthew decides

### 3. Project Won

```
Run project_template.py → Creates 22 Linear issues → Set up project folder
```

To set up a new won project:

```bash
# Create Linear issues from template
python3 openclaw/project_template.py "Client Name" "Project Address"

# Create the project knowledge folder
mkdir -p knowledge/[project-name]/

# Create the project config
cp knowledge/topletz/project-config.yaml knowledge/[project-name]/project-config.yaml
# Edit the new config with the correct project details
```

### 4. Scope Changes

When the client or project team changes scope:

1. **Log the change** in `knowledge/[project]/confirmed-decisions.md`
   - Add a row to the decisions table with item, decision, and notes
2. **Update the project config** (`project-config.yaml`)
   - Toggle scope flags, update locations, add/remove items
3. **Regenerate the SOW**:
   ```bash
   python3 openclaw/sow_assembler.py knowledge/[project]/project-config.yaml -o sow-draft.md
   ```
4. **Update D-Tools proposal** manually (no API integration yet)
5. **Run pre-flight check** before sending the agreement:
   ```bash
   python3 openclaw/preflight_check.py knowledge/[project]/project-config.yaml
   ```

### 5. Before Agreement Goes Out

Always run the pre-flight checker:

```bash
python3 openclaw/preflight_check.py knowledge/[project]/project-config.yaml
```

This cross-references:
- Every confirmed decision has a corresponding SOW section
- Products referenced in SOW exist in the knowledge base
- Scope config is internally consistent (no contradictions)
- Flags anything not yet in D-Tools

**All checks must PASS or have acceptable WARNs before Matthew sends the agreement.**

### 6. Agreement Signed

After the client signs:
1. Collect deposit per agreement terms
2. Begin procurement (order equipment)
3. Coordinate with GC on schedule
4. Track progress through Linear issues

---

## How to Add a New Product

When Symphony starts using a new product:

1. **Create a knowledge file**:
   ```bash
   # Copy an existing product as a template
   cp knowledge/products/control4-core3.md knowledge/products/new-product.md
   ```

2. **Edit the file** with the correct:
   - YAML frontmatter (name, SKU, vendor, MSRP, category)
   - Overview, specs, and Symphony usage sections
   - Set `in_d_tools: false` if not yet added to D-Tools

3. **Add to D-Tools manually** — there's no API integration, so log into D-Tools and add the product there too

4. **If it's a recurring product**, consider whether it needs a SOW block in `knowledge/sow-blocks/`

---

## How to Handle a Scope Change

1. **Log the change** — add to `knowledge/[project]/confirmed-decisions.md`:
   ```
   | 11 | New item | Decision made | Notes about it |
   ```

2. **Update project-config.yaml** — toggle the relevant scope flag or add new values

3. **Regenerate SOW**:
   ```bash
   python3 openclaw/sow_assembler.py knowledge/[project]/project-config.yaml -o updated-sow.md
   ```

4. **Update D-Tools** — manually update the proposal with new line items

5. **Run pre-flight**:
   ```bash
   python3 openclaw/preflight_check.py knowledge/[project]/project-config.yaml
   ```

---

## How to Add a New Client/Project

1. **Create Linear project** using the template script:
   ```bash
   python3 openclaw/project_template.py "Client Name" "123 Address St, City, CO 81632"
   ```
   This creates 22 standard issues tracking the full project lifecycle.

2. **Add sender to routing config** — edit `email-monitor/routing_config.json`:
   ```json
   "project_routes": {
     "client@email.com": "project-name"
   }
   ```

3. **Add to active client emails** — update the `ACTIVE_CLIENT_EMAILS` environment variable in `.env`:
   ```
   ACTIVE_CLIENT_EMAILS=existing@email.com,newclient@email.com
   ```
   Then restart the email monitor: `docker compose restart email-monitor`

4. **Create project knowledge folder**:
   ```bash
   mkdir -p knowledge/[project-name]/
   ```

5. **Create project config** — copy and edit:
   ```bash
   cp knowledge/topletz/project-config.yaml knowledge/[project-name]/project-config.yaml
   ```

---

## Key Contacts

| Who | Role | Email | Phone |
|-----|------|-------|-------|
| Matthew Earley | Principal, Symphony Smart Homes | info@symphonysh.com | (970) 519-3013 |
| Bob | AI System | bob@symphonysh.com | — |
| Zoho Mail | Business inbox | info@symphonysh.com | — |

---

## Service Credentials & Config

- **All API keys and credentials** are in the `.env` file on the Mac Mini. Never commit this file to git.
- **Docker Compose** (`docker-compose.yml`) defines all services, ports, and volume mounts.
- **GitHub repo**: `mearley24/AI-Server` — this is the source of truth for all code and configuration.
- **LLM Providers** (configured in `setup/openclaw/openclaw.json`):
  - Anthropic (Claude) — primary AI model
  - OpenAI (GPT-4o-mini) — secondary, cost-efficient tasks
  - Ollama — local inference on the iMac for non-critical tasks

---

## Troubleshooting

### Email Monitor Not Categorizing Correctly

**Symptoms**: Emails from known clients are not being routed or auto-responded to.

**Check**:
1. Is the sender in `email-monitor/routing_config.json` under `project_routes`?
2. Is the sender's email in the `ACTIVE_CLIENT_EMAILS` environment variable?
3. Check logs: `docker compose logs --tail 100 email-monitor`
4. Restart: `docker compose restart email-monitor`

### Auto-Responder Not Firing

**Symptoms**: Emails are categorized but no draft appears in Zoho.

**Check**:
1. Is the sender in the `ACTIVE_CLIENT` category? (Check routing config)
2. Is the auto-responder service running? `docker compose ps`
3. Check logs: `docker compose logs --tail 100 openclaw`
4. Verify Zoho SMTP credentials haven't expired in `.env`

### Daily Briefing Not Sending

**Symptoms**: Matthew doesn't get the morning text.

**Check**:
1. Is the cron job running? Check crontab on the Mac Mini: `crontab -l`
2. Does Twilio have credits? Log into Twilio dashboard and check balance
3. Check logs for the briefing service: `docker compose logs --tail 50 openclaw | grep briefing`
4. Run manually to test: `docker compose exec openclaw python3 daily_briefing.py`

### Bid Triage Not Working

**Symptoms**: Bids come in but no BID/PASS/REVIEW text is sent.

**Check**:
1. Has the bid email format changed? BC (BuildingConnected) occasionally updates their email templates, which can break parsing.
2. Check logs: `docker compose logs --tail 100 email-monitor | grep -i bid`
3. Verify Twilio is working (see above)
4. Run a test bid through manually if needed

### Docker Container Won't Start

**Symptoms**: A container shows `Exited` or keeps `Restarting`.

**Check**:
1. Check the exit code: `docker compose ps`
2. Read the logs: `docker compose logs [service-name]`
3. Common causes:
   - Missing environment variable in `.env`
   - Port conflict (another service using the same port)
   - Redis not running (many services depend on it)
4. Fix the issue, then: `docker compose up -d [service-name]`

### Everything Is Down

The **watchdog daemon** should handle this automatically within 60-120 seconds. Check if it's running:

```bash
launchctl list | grep symphony
tail -20 /usr/local/var/log/bob-watchdog.log
```

If the watchdog is NOT running or you need manual recovery:

```bash
# Start everything
cd ~/AI-Server && docker compose up -d

# Verify all containers are running
docker compose ps

# Check Redis is healthy (requires auth now)
docker exec redis redis-cli -a "$(grep REDIS_PASSWORD .env | cut -d= -f2)" ping
```

### Docker Desktop Crashed

**Symptoms**: Docker icon shows `?` or is missing. All containers down. Possibly DNS is dead too.

**The watchdog handles this automatically.** If it doesn't:

```bash
# 1. Relaunch Docker
open -a Docker
# Wait 60 seconds

# 2. Bring up containers
cd ~/AI-Server && docker compose up -d

# 3. If DNS is also broken (can't reach websites)
nslookup google.com
# If that fails:
networksetup -setdnsservers Ethernet 1.1.1.1 8.8.8.8
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# 4. After DNS recovers, restart email monitor (stale DNS in container)
docker restart email-monitor
```

**Why DNS dies**: Bob routes DNS through Tailscale (100.100.100.100). When Docker crashes, Tailscale's network integration breaks, killing DNS for the entire Mac. The watchdog sets fallback DNS (1.1.1.1/8.8.8.8) automatically and restores Tailscale DNS when it recovers.

### OpenClaw Won't Start (Volume Mount Error)

**Symptoms**: `permission denied` error mentioning `Symphony SH` or `SymphonySH`.

**Fix**: The iCloud folder name has a space. Check `.env`:
```bash
grep SYMPHONY .env
# Should show: SYMPHONY_DOCS_PATH=/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH

# Verify the folder exists:
ls ~/Library/Mobile\ Documents/com~apple~CloudDocs/ | grep -i symph
```

If the `.env` path is wrong, fix it and restart:
```bash
# Edit .env, then:
docker compose up -d openclaw
```

---

## Self-Healing Watchdog

Bob has a watchdog daemon that monitors the entire stack and auto-recovers from failures. It runs every 60 seconds as a macOS LaunchDaemon.

### What It Monitors

| Check | What Happens on Failure | Cooldown |
|-------|------------------------|----------|
| Tailscale | Relaunches Tailscale app + `tailscale up` | 120s |
| DNS resolution | Flushes cache → sets fallback DNS (1.1.1.1/8.8.8.8) | 180s |
| DNS restore | Restores Tailscale DNS when it recovers | — |
| Docker Desktop | Kills stale processes, relaunches, waits up to 90s | 180s |
| Missing containers | Runs `docker compose up -d --no-build` | 120s |
| Unhealthy containers | Restarts individual unhealthy containers | 300s per container |
| Email monitor DNS | Restarts email-monitor if container DNS is stale | 120s |

### Managing the Watchdog

```bash
# Check if it's running
launchctl list | grep symphony

# View recent logs
tail -50 /usr/local/var/log/bob-watchdog.log

# Watch logs live
tail -f /usr/local/var/log/bob-watchdog.log

# Run manually (for testing)
sudo bash /usr/local/bin/bob-watchdog.sh

# Stop the watchdog
sudo launchctl unload /Library/LaunchDaemons/com.symphony.bob-watchdog.plist

# Start the watchdog
sudo launchctl load /Library/LaunchDaemons/com.symphony.bob-watchdog.plist

# Reinstall after updates
cd ~/AI-Server && sudo bash bob-resilience-install.sh
```

### Recovery Timeline

From a full crash (Docker + DNS), expected recovery:

```
0s    — Watchdog detects failure
5s    — Tailscale restart triggered
10s   — DNS cache flushed, fallback DNS set
15s   — Docker Desktop relaunch triggered
75s   — Docker ready, containers starting
90s   — All containers up
105s  — Email monitor DNS verified/restarted
120s  — Full system operational
```

---

## Security

### Port Binding Policy

ALL Docker ports MUST be bound to `127.0.0.1`. Never use `0.0.0.0`.

```yaml
# CORRECT
ports:
  - "127.0.0.1:8099:3000"

# WRONG — exposes to entire LAN
ports:
  - "0.0.0.0:8099:3000"
  - "8099:3000"          # also binds to 0.0.0.0 by default
```

Verify no ports are exposed:
```bash
docker ps --format '{{.Ports}}' | grep '0.0.0.0' && echo "EXPOSED PORTS FOUND" || echo "All safe"
```

### Redis Authentication

Redis requires a password (set in `.env` as `REDIS_PASSWORD` and in `redis/redis.conf`). Dangerous commands (`FLUSHALL`, `FLUSHDB`, `DEBUG`) are disabled.

```bash
# This should FAIL (no auth)
redis-cli -h 127.0.0.1 ping

# This should return PONG
docker exec redis redis-cli -a "$(grep REDIS_PASSWORD ~/AI-Server/.env | cut -d= -f2)" ping
```

All services connect via `REDIS_URL=redis://:<password>@redis:6379` set in `docker-compose.yml`.

### Security Checklist (monthly)

- [ ] No `0.0.0.0` port bindings: `grep '0.0.0.0:' docker-compose.yml`
- [ ] Redis requires auth: `redis-cli -h 127.0.0.1 ping` should fail
- [ ] Redis version patched: `docker exec redis redis-server --version` (need 7.2.11+ for CVE-2025-49844)
- [ ] macOS firewall enabled: System Settings → Network → Firewall
- [ ] No router port forwarding to Bob's IP
- [ ] Watchdog running: `launchctl list | grep symphony`
- [ ] Watchdog logs clean: `tail -50 /usr/local/var/log/bob-watchdog.log`

---

## Incident History

See `knowledge/incidents/` for detailed incident reports.

| Date | Incident | Resolution |
|------|----------|------------|
| 2026-04-04 | Docker crash cascade — full outage ~45 min, DNS dead, 3 exposed ports found | Watchdog daemon, Redis auth, port lockdown, DNS fallback |

---

## SOW Management Tools

### SOW Assembler

Generates a complete Scope of Work from modular building blocks:

```bash
# Generate SOW to stdout
python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml

# Generate SOW to a file
python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml -o sow-draft.md

# Generate plain text for D-Tools paste
python3 openclaw/sow_assembler.py knowledge/topletz/project-config.yaml -f dtools
```

How it works:
1. Reads the project config to determine what's in scope
2. Loads all SOW blocks from `knowledge/sow-blocks/`
3. Includes "always include" blocks plus blocks whose trigger matches a scope flag
4. Replaces `{{variable}}` placeholders with project-specific values
5. Appends the scope change log from confirmed decisions

### Pre-Flight Checker

Validates everything before an agreement goes out:

```bash
python3 openclaw/preflight_check.py knowledge/topletz/project-config.yaml
```

Checks performed:
- Every confirmed decision has a corresponding SOW section
- Products in the knowledge base are marked as in D-Tools
- Scope config is internally consistent
- Flags missing or contradictory items

Output format:
- **[PASS]** — check passed
- **[WARN]** — needs attention but not blocking
- **[FAIL]** — must be fixed before sending
- **[INFO]** — informational only

---

*Last updated: April 4, 2026*
*Maintained by: Matthew Earley / Bob*
