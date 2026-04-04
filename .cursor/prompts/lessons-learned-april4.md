# Lessons Learned — April 4, 2026

## What Was Claimed Working vs What Actually Broke

This documents every manual fix Matt or Computer had to make during the April 4 session. Bob and the team need to learn from each one so it never happens again.

### 1. Agreement PDF had wrong pricing
- **Claimed:** Agreement was up to date in Dropbox Client folder
- **Reality:** Agreement still showed $63,019.17 (V4 pricing from March 31). Proposal was updated to $57,683.09 but agreement was never regenerated.
- **Manual fix:** Computer regenerated the entire 6-page agreement PDF from scratch with correct numbers
- **Root cause:** No system links proposal price changes to agreement regeneration. D-Tools price changes don't trigger downstream document updates.
- **Bob should:** When D-Tools proposal total changes, flag ALL project documents that contain pricing (agreement, deliverables, payment schedule) as stale. Never send a document package where the numbers don't match across all docs.

### 2. Deliverables PDF had wrong lighting schedule
- **Claimed:** Deliverables were current
- **Reality:** Deliverables showed 41 lighting devices (25 KD + 11 APD + 5 SW) from the original scope. The current proposal has 18 devices (16 KD + 2 SW). Payment schedule still showed $63K numbers. Change log was missing deviations 6-9.
- **Manual fix:** Computer regenerated the entire 12-page deliverables from scratch
- **Root cause:** Deliverables were generated March 31 and never updated when Steve confirmed the switch reduction. No system tracks "which documents contain scope-dependent content."
- **Bob should:** Maintain a dependency map: lighting schedule appears in deliverables → when lighting scope changes, deliverables are stale. Payment schedule appears in agreement AND deliverables → when pricing changes, both are stale.

### 3. TV Mount Recommendations referenced wrong ceiling mount
- **Claimed:** TV mount doc was current (April 1 date)
- **Reality:** Doc still says "Peerless-AV PLCM-2 ceiling mount for the Hearth Room remains as specified" — but we determined on April 3 that PLCM-2 doesn't fit the Hisense 100" (wrong VESA, wrong weight). Chief XCM7000 is the replacement. Also still references Legrand back boxes instead of Strong VersaBox.
- **Manual fix:** Needs regeneration (in progress)
- **Root cause:** The April 3 email discussion about ceiling mounts and back boxes never triggered a document update flag.
- **Bob should:** When an email thread discusses a specific product/component that appears in project documents, flag those documents as potentially stale.

### 4. Dropbox share links were wrong format
- **Claimed:** Dropbox links were shared with Steve
- **Reality:** Steve couldn't open them because they were `/preview/` format links that require a Dropbox account. Should be `scl/fi/` format links.
- **Manual fix:** Matt manually generated new share links from Dropbox web UI
- **Root cause:** The original links were generated as preview links, not public share links.
- **Bob should:** ALWAYS use `scl/fi/` format Dropbox links. NEVER use `/preview/` links. Test every share link in an incognito browser before sending to a client.

### 5. Signature wasn't on any documents
- **Claimed:** Documents were ready to send
- **Reality:** None of the four Client folder documents had Matt's signature. No system for auto-signing.
- **Manual fix:** Matt wrote signature on iPad, Computer processed it (transparent background, navy ink), regenerated agreement with signature embedded
- **Root cause:** No signature automation existed. Documents were generated unsigned.
- **Bob should:** Every client-facing document gets Matt's signature (at `knowledge/brand/matt_earley_signature.png`) and today's date automatically. No unsigned documents leave the system.

### 6. Git pull constantly broken by data files
- **Claimed:** `git pull` works
- **Reality:** Every single `git pull` failed due to `data/network_watch/dropout_watch_status.json` conflicts. Required 2-3 manual attempts every time.
- **Manual fix:** Created `scripts/pull.sh` that nukes the file before every git operation
- **Root cause:** Runtime data files being tracked by git. `.gitignore` didn't cover all data files.
- **Bob should:** `scripts/pull.sh` is the ONLY way to pull. Never bare `git pull`. Also verify `.gitignore` covers all `data/**/*.json` and `data/**/*.db` files.

### 7. Dropbox not installed on Bob
- **Claimed:** Bob has access to project files
- **Reality:** Dropbox was installed via brew but never launched/signed in. Bob had no filesystem access to any project documents.
- **Manual fix:** Matt launched Dropbox app, signed in, waited for sync
- **Root cause:** `brew install --cask dropbox` installs but doesn't launch or authenticate.
- **Bob should:** After any new app installation, verify it's actually running and authenticated. Check with `ls ~/Library/CloudStorage/Dropbox*/ 2>/dev/null`.

### 8. iCloud not signed in on Bob
- **Claimed:** iCloud file watcher running
- **Reality:** iCloud watch process was running (PID 57482) but getting "Logged out - iCloud Drive is not configured." Zero files accessible.
- **Manual fix:** Matt physically signed Bob into iCloud via System Settings
- **Root cause:** Bob was never signed into iCloud. The launchd service ran but had nothing to watch.
- **Bob should:** On startup/restart, verify iCloud is signed in: `brctl status 2>/dev/null | head -5`. If "not configured," alert Matt.

### 9. Daily briefing couldn't find email DB
- **Claimed:** Daily briefing works
- **Reality:** Briefing script looked for `/data/emails.db` which doesn't exist. Actual path is `/app/data/email-monitor/emails.db` (Docker) or `/Users/bob/AI-Server/data/email-monitor/emails.db` (crontab).
- **Manual fix:** Added `_find_email_db()` path fallback in the Cursor prompt
- **Root cause:** Hardcoded path that was wrong from day one. Never tested.
- **Bob should:** Every script that reads a file should have path fallback logic. Never hardcode a single path.

### 10. Mission Control fonts too small
- **Claimed:** Dashboard rebuilt and working
- **Reality:** Dashboard tiles filled the viewport but all text was 9-11px — unreadable. Multiple rounds of font size adjustments needed.
- **Manual fix:** Computer edited CSS multiple times, then wrote a Cursor prompt for `clamp()` responsive sizing
- **Root cause:** The "compact Apple tiles" redesign prompt made everything too small without testing at real screen sizes.
- **Bob should:** After any UI change, screenshot at 1280px and 375px and verify readability before deploying.

### 11. Jobs DB empty — D-Tools sync created zero jobs
- **Claimed:** D-Tools sync working, auto-creating jobs
- **Reality:** D-Tools sync scanned 100 opportunities but logged "no active job" for every single one and moved on. Zero jobs in the database. This blocked the ENTIRE downstream pipeline: follow-ups, payments, proposals, daily briefing.
- **Manual fix:** Wrote Cursor prompt to add auto-creation logic for Won/On Hold opportunities
- **Root cause:** The sync was built to FIND existing jobs, not CREATE them. Nobody noticed because the jobs table was never checked.
- **Bob should:** After any "pipeline" feature is deployed, verify the pipeline actually has data flowing through it. Empty tables = dead pipeline.

### 12. Multiple Cursor prompts claimed "done" but files didn't exist
- **Claimed:** Decision journal, confidence, pattern engine, continuous learning, task board, etc. all working
- **Reality:** AGENTS.md referenced 10 files that didn't exist in the repo. Cursor reported them as implemented but the actual Python files were never created.
- **Manual fix:** Wrote `finish-line.md` and `wrap-it-up.md` prompts to actually create every missing file
- **Root cause:** Cursor may have created files locally but they were never committed/pushed. Or Cursor reported planning to create them but didn't actually do it.
- **Bob should:** After every Cursor prompt, run a verification: for each file the prompt claims to create, check `ls -la [file]` and `wc -l [file]`. If it doesn't exist or is 0 lines, it wasn't created.

### 13. Redis IP changes after every Docker restart — Polymarket bot breaks
- **Frequency:** 5+ times across April 1-4. Every single container restart.
- **Reality:** Polymarket bot connects to Redis via hardcoded container IP (172.18.0.x) because it runs through VPN (network_mode: service:vpn) and can't use Docker DNS. After any compose restart, Redis gets a new IP. Bot silently fails to send notifications.
- **Time wasted:** ~2 hours total debugging across multiple sessions. Same fix applied 3+ times.
- **Manual fix:** `docker inspect redis` to get new IP, update polymarket-bot/.env, restart bot.
- **Root cause:** VPN routing captures all traffic (AllowedIPs = 0.0.0.0/0), blocking host.docker.internal resolution. Redis bound to 127.0.0.1 initially, then changed to 0.0.0.0 but VPN still blocked it.
- **Bob should:** After EVERY `docker compose up/restart`, automatically check Redis IP and update bot .env if changed. Add to `symphony-ship.sh` verification. Or better: assign Redis a static IP in docker-compose.yml via `networks: default: ipv4_address: 172.18.0.100`.

### 14. Zoho token expiration — breaks email sending every hour
- **Frequency:** Every session that tried to send email via API
- **Reality:** Zoho access tokens expire in 1 hour. Every curl command to send/draft email required a manual token refresh first.
- **Time wasted:** ~30 min per session on token refresh dance
- **Manual fix:** curl to Zoho OAuth refresh endpoint, get new token, paste into next command
- **Root cause:** No automatic token refresh in the email sending flow
- **Bob should:** The email-monitor and orchestrator should auto-refresh Zoho tokens using the refresh_token in .env. Never require manual token refresh.

### 15. Auto-responder couldn't import across Docker containers
- **Claimed:** Auto-responder generates draft replies to client emails
- **Reality:** Auto-responder lives in openclaw container, email-monitor is a separate container. `from auto_responder import ...` fails with ModuleNotFoundError because containers don't share filesystems.
- **Time wasted:** ~1 hour debugging + user frustration
- **Root cause:** Architecture assumes shared filesystem between containers. Should use HTTP API calls between services, not Python imports.
- **Bob should:** Services communicate via HTTP endpoints, never cross-container Python imports. If openclaw has the auto-responder, email-monitor should POST to openclaw's API, not try to import its code.

### 16. Strategy filters never deployed — bot burned through $1,900 in one day
- **Claimed:** Temperature clustering, crypto filter, category blacklist all working
- **Reality:** None of the strategy filters were active because the bot container was never rebuilt after the code was pushed. 242 buys, 17 sells in 24 hours.
- **Time wasted:** Real money lost. $1,900+ deployed in one day with almost no exits.
- **Manual fix:** `docker compose up -d --build polymarket-bot`
- **Root cause:** Config changes baked into Docker images require `--build` flag. Simple restart doesn't pick up code changes.
- **Bob should:** After ANY code push to a service, ALWAYS rebuild: `docker compose up -d --build [service]`. Never bare restart. Add to pull.sh and symphony-ship.sh.

### 17. Sell haircut rounding error — positions stuck in exit loops
- **Frequency:** Ongoing since early April
- **Reality:** Bot tried to sell 9.94M token units but only held 9.62M on-chain. The 0.995 haircut wasn't enough. Positions retried every minute for 25+ minutes, losing value while looping.
- **Time wasted:** ~1 hour debugging + real money lost as sell price dropped during loop
- **Manual fix:** Changed haircut from 0.995 to 0.96
- **Root cause:** Internal share tracking doesn't match on-chain balance (slippage, rounding in CTF token math)
- **Bob should:** Before ANY sell order, query on-chain balance first. Sell min(internal_shares * haircut, on_chain_balance). If on-chain is 0, drop the position from tracking.

### 18. Multiple .env entries — first one wins, duplicates ignored
- **Frequency:** 3 times during Redis IP fix
- **Reality:** `echo "REDIS_URL=..." >> .env` appends a new line but Docker uses the FIRST occurrence. So the broken old value kept loading.
- **Time wasted:** 30+ min running the same fix multiple times
- **Manual fix:** `sed -i '' '/REDIS_URL/d' .env` to delete all, then add one clean entry
- **Root cause:** Appending to .env instead of replacing
- **Bob should:** NEVER append to .env. Always delete the key first, then add: `sed -i '' '/KEY/d' .env && echo 'KEY=value' >> .env`

### 19. Shell escaping breaks every multi-line curl command
- **Frequency:** Every session that involves Zoho API, Dropbox API, or any JSON POST
- **Reality:** Quotes, apostrophes, and special characters get mangled when pasting curl commands into terminal. JSON parse errors, invalid_client errors.
- **Time wasted:** ~1 hour total across sessions
- **Manual fix:** Save JSON to file first (`cat > /tmp/payload.json << 'EOF'`), then `curl -d @/tmp/payload.json`
- **Root cause:** Complex quoting in shell commands
- **Bob should:** NEVER inline JSON in curl commands. Always write to a temp file first, then reference with `-d @file`. This is now a hard rule.

### 20. Cursor claims work is done but files don't exist
- **Frequency:** At least 3 times (next-level modules, finish-line files, continuous learning)
- **Reality:** Cursor reports "implemented" in status docs but actual .py files were never created. Or files were created locally but never committed.
- **Time wasted:** Multiple hours writing follow-up prompts to build what was supposedly already built
- **Root cause:** Cursor may plan to create files but not execute, or creates in a temp context that doesn't persist. Status docs written optimistically.
- **Bob should:** After EVERY Cursor prompt, run verification: `for f in [expected files]; do [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"; done`. Never trust status docs — check the filesystem.

### 21. Dashboard rebuilt 4+ times before it looked right
- **Frequency:** 4 iterations (original build, Apple tiles, font fix, final polish)
- **Reality:** First build was too big, second too small, third fonts too tiny, fourth still needed work. Each iteration required a full Docker rebuild + wait.
- **Time wasted:** ~2 hours of rebuild cycles
- **Root cause:** No visual QA before deploying. No screenshot review. Prompts described design but didn't verify output.
- **Bob should:** After any UI change, take a screenshot via Playwright at 1280px and 375px BEFORE deploying. Fix issues in the same prompt, not in follow-up prompts.

### 22. git pull fails every single time
- **Frequency:** EVERY git pull on Bob. 10+ times this session alone.
- **Reality:** `data/network_watch/dropout_watch_status.json` conflicts on every pull. Required stash/checkout/rebase dance each time.
- **Time wasted:** ~1 hour total, 5+ min per occurrence
- **Manual fix:** Created `scripts/pull.sh` that nukes the file first
- **Root cause:** Runtime data files tracked by git, modified by running services between pulls
- **Bob should:** `scripts/pull.sh` is the ONLY pull method. Also add ALL runtime data files to .gitignore permanently.

### 23. Launchd services reference nonexistent scripts
- **Claimed:** efficiency, morning_scan launchd jobs running
- **Reality:** Exit code 2 because `orchestrator/efficiency_audit.py` and `orchestrator/daily_market_scan.py` don't exist. Cursor created the plists but never the scripts.
- **Time wasted:** 15 min diagnosing
- **Manual fix:** Unloaded the broken plists
- **Root cause:** Launchd plists generated without verifying target scripts exist
- **Bob should:** Every launchd plist must verify its target exists before loading: `[ -f /path/to/script ] && launchctl load plist || echo "SKIP: script missing"`

### 24. VPN guard couldn't find docker command
- **Claimed:** VPN guard monitoring every 5 min
- **Reality:** Launchd runs with minimal PATH. `docker` is at `/usr/local/bin/docker` but launchd's PATH doesn't include that.
- **Time wasted:** 15 min
- **Manual fix:** `sed` to replace `docker` with `/usr/local/bin/docker` in the script
- **Root cause:** Scripts written for interactive shell, not launchd environment
- **Bob should:** ALL scripts run by launchd must use full paths for every command: `/usr/local/bin/docker`, `/opt/homebrew/bin/python3`, etc. Never assume PATH.

### 25. pip install fails on macOS — externally managed environment
- **Frequency:** Every time a Python package needs installing on Bob
- **Reality:** PEP 668 prevents `pip install` on macOS managed Python. Requires `--break-system-packages` or venv.
- **Time wasted:** 10 min each time
- **Root cause:** macOS Sonoma+ enforces PEP 668
- **Bob should:** Use `pip3 install --break-system-packages [pkg]` or maintain a venv at `~/AI-Server/.venv/` for all host-side Python work.

---

## System Changes Needed (Cursor Prompt Below)

Based on the above, here's what needs to be built/fixed:

### A. Document Staleness Detection
Create `openclaw/doc_staleness.py`:
- Maintains a registry of project documents and what data they contain
- When pricing changes (D-Tools sync detects new total) → flag agreement + deliverables as stale
- When scope changes (email classified as scope change) → flag relevant docs based on DOC_IMPACT_MAP
- When a doc is flagged stale, publish `events:documents` / `doc.stale` event
- Send notification to Matt: "[Project] Agreement is stale — pricing changed from $X to $Y. Reply UPDATE to regenerate."

### B. Document Regeneration Pipeline
Create `openclaw/doc_generator.py`:
- Wraps `tools/generate_agreement.py` with auto-population from jobs DB + D-Tools data
- Auto-applies signature from `knowledge/brand/matt_earley_signature.png`
- Auto-applies today's date
- Auto-publishes to Dropbox Client folder (replace in place)
- Generates: agreement, deliverables, TV recommendations
- Only runs after Matt approves (via iMessage approval flow)

### C. Dropbox Link Validator
Add to `openclaw/orchestrator.py` — before any email with Dropbox links is sent:
- Verify each link is `scl/fi/` format (not `/preview/`)
- Verify the link returns HTTP 200 (file exists and is accessible)
- If validation fails, alert and block the email

### D. Post-Deploy Verification
Create `scripts/verify-deploy.sh`:
- After any `docker compose up`, check:
  - All expected files exist (from a manifest)
  - All DB tables have rows (jobs, decisions, follow_ups, payments)
  - All API endpoints return 200
  - Redis events:log has entries
  - Dropbox is syncing
  - iCloud is connected
- Run automatically after `symphony-ship.sh`

### E. Linear Issue Auto-Update
When D-Tools pricing changes or scope changes are confirmed:
- Update the relevant Linear issues with new pricing
- Close resolved scope issues
- Open new issues for document regeneration tasks

### G. Redis Static IP
In `docker-compose.yml`, assign Redis a static IP so the polymarket bot never loses connection:
```yaml
networks:
  default:
    ipam:
      config:
        - subnet: 172.18.0.0/16

redis:
  networks:
    default:
      ipv4_address: 172.18.0.100
```
Then set `REDIS_URL=redis://172.18.0.100:6379` in the polymarket-bot environment. No more IP hunting.

### H. Auto Token Refresh for Zoho
Create `openclaw/zoho_auth.py` — a helper that reads ZOHO_REFRESH_TOKEN from .env and auto-refreshes the access token before any Zoho API call. Cache the access token in memory with its expiry time. If token is within 5 min of expiry, refresh proactively. Every service that calls Zoho (email-monitor, orchestrator, daily briefing) imports this helper.

### I. Inter-Service Communication via HTTP Only
Add to AGENTS.md as a hard rule: "Services NEVER import Python modules from other containers. All inter-service communication is via HTTP endpoints. If openclaw needs email-monitor data, it calls GET http://email-monitor:8092/api/endpoint. If email-monitor needs auto-responder logic, it POSTs to http://openclaw:3000/api/auto-respond."

### J. Mandatory Rebuild After Code Push
Edit `scripts/pull.sh` — after pulling, detect which service directories changed and auto-rebuild:
```bash
changed=$(git diff --name-only HEAD~1 HEAD | cut -d/ -f1 | sort -u)
for svc in openclaw mission_control polymarket-bot email-monitor; do
  if echo "$changed" | grep -q "$svc\|mission.control\|polymarket.bot\|email.monitor"; then
    echo "Rebuilding $svc..."
    docker compose up -d --build $svc
  fi
done
```

### K. Cursor Verification Script
Create `scripts/verify-cursor.sh` — takes a list of expected files as args, checks each exists and has >10 lines:
```bash
#!/bin/bash
for f in "$@"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
  elif [ $(wc -l < "$f") -lt 10 ]; then
    echo "STUB (<10 lines): $f"
  else
    echo "OK ($(wc -l < $f) lines): $f"
  fi
done
```
Run after every Cursor prompt: `bash scripts/verify-cursor.sh openclaw/file1.py openclaw/file2.py ...`

### L. .env Management
Create `scripts/set-env.sh` — safe .env setter that deletes then appends:
```bash
#!/bin/bash
# Usage: bash scripts/set-env.sh KEY value [file]
KEY=$1; VAL=$2; FILE=${3:-.env}
sed -i '' "/^${KEY}=/d" "$FILE"
echo "${KEY}=${VAL}" >> "$FILE"
echo "Set ${KEY} in ${FILE}"
```

### M. JSON Payload Helper
Create `scripts/api-post.sh` — writes JSON to temp file then curls:
```bash
#!/bin/bash
# Usage: bash scripts/api-post.sh URL '{"key":"value"}' [auth_header]
URL=$1; JSON=$2; AUTH=${3:-}
TMP=$(mktemp /tmp/api-XXXXXX.json)
echo "$JSON" > "$TMP"
if [ -n "$AUTH" ]; then
  curl -s -X POST "$URL" -H "$AUTH" -H "Content-Type: application/json" -d @"$TMP"
else
  curl -s -X POST "$URL" -H "Content-Type: application/json" -d @"$TMP"
fi
rm "$TMP"
```

### F. Startup Health Verification
Add to orchestrator first-tick:
- Check iCloud: `brctl status` → if not configured, alert
- Check Dropbox: `ls ~/Library/CloudStorage/Dropbox*/` → if empty, alert
- Check all DB files exist and have tables
- Check signature file exists at `knowledge/brand/matt_earley_signature.png`
- Check `.env` has all required keys (without logging values)

---

## Implementation

Build all of the above. After building, run the full smoke test. Then update AGENTS.md with these lessons so every future session starts with this knowledge.

## Verification
```bash
docker compose build --no-cache openclaw
docker compose up -d openclaw
sleep 60

echo "=== Doc staleness check ==="
docker exec openclaw python3 -c "from doc_staleness import DocStalenessTracker; print('OK')"

echo "=== Doc generator check ==="  
docker exec openclaw python3 -c "from doc_generator import DocGenerator; print('OK')"

echo "=== Startup health ==="
docker logs openclaw 2>&1 | grep "health_check\|icloud\|dropbox\|signature\|stale" | tail -10

echo "=== Smoke test ==="
./scripts/smoke-test.sh
```
