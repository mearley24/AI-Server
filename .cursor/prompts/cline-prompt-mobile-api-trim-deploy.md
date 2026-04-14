---
description: Trim Mobile API of duplicated endpoints and deploy as a host-level launchd service
---

# Mobile API — Trim Duplicates and Deploy on Host

## Context

`api/mobile_api.py` (7,288 lines, 100+ endpoints) is a comprehensive REST API for remote monitoring and control of Bob. It was built to run directly on the Mac because it needs host-level access:

- Reads iMessage database (`~/Library/Messages/chat.db`)
- Accesses iCloud files (`~/Library/Mobile Documents/...`)
- Runs subprocess commands on the host
- Manages launchd services
- Monitors network dropout via host-level tools

**It CANNOT run in Docker** without losing these capabilities. It should run as a **launchd service** on the Mac.

However, many of its endpoints now duplicate functionality that other Docker services handle. This prompt trims the duplicates to avoid confusion and conflicting state, then sets up the launchd service.

## Part 1: Remove Duplicated Endpoints

### Remove Cortex Duplicates
The following endpoints duplicate `cortex:8102` — remove them entirely:

- `/cortex/stats` → cortex has `/memories` and `/health`
- `/facts/learn` → cortex has `/remember`
- `/facts/categories` → cortex has `/memories`
- `/cortex/curator/run` → cortex has `/improve/run`
- `/cortex/curator/status`
- `/cortex/curator/review`
- `/cortex/curator/facts/status`
- `/cortex/curator/promote`
- `/cortex/curator/demote`
- `/memory_guard/status`

Replace them with a single proxy endpoint that returns the cortex URL:

```python
@app.get("/cortex")
async def cortex_redirect():
    """Cortex endpoints moved to dedicated service."""
    return {"service": "cortex", "url": "http://localhost:8102", "endpoints": ["/query", "/remember", "/memories", "/goals", "/rules", "/digest/today"]}
```

### Remove AI Chat Duplicate
- `/ai/chat` → openclaw:8099 has `/v1/chat/completions`
- `/ai/costs` → openclaw has `/api/llm-costs`
- `/ai/status` — KEEP this one (it checks Ollama + LM Studio availability on the host)
- `/ai/verify/ollama` — KEEP
- `/ai/verify/lm_studio` — KEEP
- `/ai/log` — KEEP (local logging)

Replace `/ai/chat` with a redirect:
```python
@app.get("/ai/chat-redirect")
async def ai_chat_redirect():
    return {"service": "openclaw", "url": "http://localhost:8099/v1/chat/completions"}
```

### Remove Trading Duplicate
- `/trading/fix_api` — KEEP (this manages the local trading_api.py process)
- `/morning` → daily-intel-briefing handles this via iMessage now

Remove `/morning` or make it call the intel-briefing endpoint.

### Keep Everything Else
All of these are UNIQUE to the mobile API and should stay:
- `/dashboard`, `/stats`, `/services` — system overview
- `/bids/*`, `/proposals/*` — bid/proposal management
- `/notes/*` — Apple Notes pipeline
- `/imessages/*` — iMessage intake and automation
- `/contacts/*` — contact management
- `/ops/*` — inventory, turnkey, employee bots
- `/network/*` — dropout detection
- `/tasks/*` — project watches, file intake, uploads
- `/projects/*` — manual digest, room modeler, proposal scope
- `/dtools/*` — D-Tools product import/export
- `/markup/*` — markup generation
- `/leads/*` — builder/realtor/listing pipeline
- `/social/*` — X queue, content
- `/seo/*` — keyword tracking
- `/subscriptions`, `/usage/*` — tracking
- `/manuals/*` — auto-digest

## Part 2: Add requirements.txt

Create `api/requirements.txt`:

```
fastapi>=0.104.0
uvicorn>=0.24.0
python-dotenv>=1.0.0
openpyxl>=3.1.0
python-multipart>=0.0.6
```

## Part 3: Create launchd plist

Create `setup/com.symphony.mobile-api.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.mobile-api</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>api/mobile_api.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/bob/AI-Server</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/bob/AI-Server/logs/mobile-api.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/bob/AI-Server/logs/mobile-api-error.log</string>
</dict>
</plist>
```

## Part 4: Create install script

Create `setup/install_mobile_api.sh`:

```zsh
#!/bin/zsh
# Install Mobile API as a launchd service on Bob
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_SERVER_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.symphony.mobile-api"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "Installing Mobile API service..."

# Install Python dependencies
pip3 install -r "$AI_SERVER_DIR/api/requirements.txt" --quiet

# Update working directory in plist to match actual location
sed "s|/Users/bob/AI-Server|$AI_SERVER_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

# Create logs directory
mkdir -p "$AI_SERVER_DIR/logs"

# Unload if already running
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Load the service
launchctl load "$PLIST_DST"

echo "Mobile API installed and running on port 8420"
echo "Check: curl http://localhost:8420/health"
echo "Logs: tail -f $AI_SERVER_DIR/logs/mobile-api.log"
```

## Part 5: Update the dashboard endpoint

The `/dashboard` endpoint should aggregate status from all Docker services. Update it to query:
- `http://redis:6379` (via docker exec) or the Docker socket
- `http://localhost:8430/health` (polymarket-bot via VPN)
- `http://localhost:8099/health` (openclaw)
- `http://localhost:8102/health` (cortex)
- `http://localhost:8095/health` (notification-hub)
- `http://localhost:8096/health` (client-portal)

Use `httpx` or `urllib.request` with short timeouts (2s) to check each service.

Add `httpx` to `api/requirements.txt` if you use it.

## Verification

After changes:

1. `python3 -c "exec(open('api/mobile_api.py').read().split('if __name__')[0]); print('Syntax OK')"` — no syntax errors
2. `grep -c "@app\.\(get\|post\)" api/mobile_api.py` — should be ~15-20 fewer endpoints than before
3. `ls setup/com.symphony.mobile-api.plist` — plist exists
4. `ls setup/install_mobile_api.sh` — install script exists

## After This Prompt

Matt runs on Bob:
```zsh
cd ~/AI-Server && git pull origin main && zsh setup/install_mobile_api.sh
```

Then verify: `curl http://localhost:8420/health`

The Mobile API is now a permanent host-level service that starts on boot, manages Mac-native resources (iMessages, iCloud, network), and delegates everything else to Docker services.

Commit message: `feat: trim mobile API duplicates, add launchd service for host-level deployment`
