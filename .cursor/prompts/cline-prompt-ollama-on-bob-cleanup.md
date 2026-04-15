## Move Ollama to Bob + Container Cleanup — Free RAM for Local Inference

You are working on ~/AI-Server on Bob (Mac Mini M4, 16GB RAM).

### Background

Bob runs 18+ Docker containers and the Mac host runs launchd agents (gateway, imessage-server, etc). Ollama currently runs on Maestro (2019 iMac, CPU-only i3) at 192.168.1.199 — it's too slow. We're moving Ollama to Bob where Metal GPU acceleration will give us 20-40 tok/s on a 3-4B model vs 3-6 tok/s on Maestro's CPU.

Problem: Bob only has 16GB RAM. We need to free up as much memory as possible by removing dead/unused containers and launchd agents before installing Ollama.

This prompt has two phases:
1. **Phase 1**: Audit and clean up — remove everything that isn't earning money or essential
2. **Phase 2**: Install Ollama on Bob, pull a model, rewire all services

---

## Phase 1 — Audit and Cleanup

### Step 1.1 — Measure current memory usage

```zsh
echo "=== Total system memory ==="
sysctl -n hw.memsize | awk '{printf "%.1f GB\n", $1/1073741824}'

echo "=== Docker container memory ==="
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | sort -k3 -rn

echo "=== Top non-Docker processes ==="
ps aux --sort=-%mem | head -20

echo "=== Docker disk usage ==="
docker system df

echo "=== Loaded launchd agents ==="
launchctl list | grep -i "symphony\|symphonysh" | sort
```

Record all output — we need the before/after comparison.

### Step 1.2 — Remove dead/unused Docker containers

These containers are candidates for removal. For each one, verify it's actually unused before removing.

**LIKELY SAFE TO REMOVE:**

1. **voice-receptionist** — Twilio AI voice receptionist. Never went live (GO_LIVE_CHECKLIST.md is all unchecked). Uses OpenAI Realtime API (costs money when active). No other service depends on it.
   - Verify: `docker logs voice-receptionist --tail 20 --since 24h` — if no real call logs, remove it.
   - Remove: Comment out the entire `voice-receptionist:` block in docker-compose.yml, then `docker compose rm -sf voice-receptionist`

2. **client-portal** — Has no exposed host port, healthcheck targets port 8096 (wrong — that's dtools-bridge). STATUS_REPORT.md says it reports unhealthy because there's no `/health` endpoint. No service routes traffic to it.
   - Verify: `docker logs client-portal --tail 20 --since 24h`
   - Remove: Comment out the entire `client-portal:` block in docker-compose.yml, then `docker compose rm -sf client-portal`

3. **x-intake-lab** — Experimental/lab version of x-intake. Duplicate of x-intake with `LAB_MODE=true`. If x-intake is working, the lab version is dead weight.
   - Verify: `docker logs x-intake-lab --tail 20 --since 24h`
   - Remove: Comment out the entire `x-intake-lab:` block in docker-compose.yml, then `docker compose rm -sf x-intake-lab`

4. **rsshub** — RSS feed aggregator, only used by x-alpha-collector. Check if x-alpha-collector is actually producing useful output. If x-alpha-collector feeds are not being acted on, both can go.
   - Verify: `docker logs x-alpha-collector --tail 30 --since 24h` and `docker logs rsshub --tail 10 --since 24h`
   - Decision: If x-alpha-collector is producing x_intel items that appear in the Cortex digest, keep both. If it's just noise, remove both.
   - Remove (if removing): Comment out both `rsshub:` and `x-alpha-collector:` blocks, then `docker compose rm -sf rsshub x-alpha-collector`

5. **intel-feeds** — Check what this actually does and if anything consumes its output.
   - Verify: `docker logs intel-feeds --tail 30 --since 24h`
   - If idle or producing unused output, comment out and remove.

**EVALUATE CAREFULLY (may or may not be useful):**

6. **proposals** — Proposal engine for Symphony business. Is Matt actively generating proposals through this service?
   - Verify: `docker logs proposals --tail 20 --since 7d` — any recent proposal generation?
   - If no activity in 7+ days, comment out. Can be re-enabled when needed.

7. **dtools-bridge** — D-Tools Cloud API bridge. Only useful if D-Tools sync is actively running.
   - Verify: `docker logs dtools-bridge --tail 20 --since 7d`
   - If no activity, comment out.

8. **clawwork** — Side-hustle earnings tracker / sector strategies. Check if actively used.
   - Verify: `docker logs clawwork --tail 20 --since 7d`
   - If idle, comment out.

**DO NOT REMOVE (essential for 24/7 operations):**

- **redis** — Everything depends on it
- **polymarket-bot** + **vpn** — Trading (making money)
- **openclaw** — Orchestrator (follow-ups, daily briefing, health)
- **cortex** — Brain (memory, goals, dashboard, digests)
- **cortex-autobuilder** — Research scanner (builds knowledge, uses Ollama)
- **notification-hub** — iMessage dispatch
- **email-monitor** — Email classification and monitoring
- **calendar-agent** — Calendar integration
- **x-intake** — X/Twitter signal processing

### Step 1.3 — Clean up launchd agents

Check which launchd agents are actually loaded and running:

```zsh
launchctl list | grep -i "symphony\|symphonysh"
```

For each loaded agent, check if it's doing useful work or just burning cycles. Key agents to evaluate:

**LIKELY SAFE TO REMOVE (if they reference scripts that don't exist or services that were removed):**

- `com.symphony.worker-betty` — Betty is Maestro. If moving Ollama to Bob, this Maestro worker reference is dead.
- `com.symphony.employee-betty-bot` — Same. Betty/Maestro agent.
- `com.symphony.employee-beatrice-bot` — Another Maestro agent.
- `com.symphony.voice-webhook` — Voice receptionist webhook. If voice-receptionist container is removed, this is dead too.

For each one to remove:

```zsh
launchctl unload ~/Library/LaunchAgents/<plist-name>.plist 2>/dev/null
rm ~/Library/LaunchAgents/<plist-name>.plist 2>/dev/null
```

**DO NOT REMOVE:**

- `com.symphony.mobile-api` — Gateway (port 8420)
- `com.symphony.imessage-bridge` — iMessage server
- `com.symphony.markup-app` — AV markup tool for iPad (port 8088). MUST stay running and persistent. Verify it is loaded and healthy: `curl -s http://127.0.0.1:8088/ -o /dev/null -w '%{http_code}'` should return 200. If the plist is not loaded, load it: `launchctl load ~/Library/LaunchAgents/com.symphony.markup-app.plist`. If the plist is not in ~/Library/LaunchAgents/, copy it from `setup/launchd/com.symphony.markup-app.plist`.
- `com.symphonysh.dropbox-organizer` — Dropbox file organization
- `com.symphonysh.icloud-watch` — iCloud sync monitoring
- `com.symphony.daily-digest` — If this triggers the Cortex daily digest
- `com.symphony.bob-maintenance` / `com.symphony.backup-data` — Maintenance tasks

For anything else not in the "do not remove" list, check the plist to see what script it runs. If the script doesn't exist or references a removed service, unload and remove the plist.

### Step 1.4 — Docker cleanup

After removing containers:

```zsh
docker system prune -af --volumes
docker builder prune -af
```

This removes unused images, build cache, and dangling volumes. Can free several GB.

### Step 1.5 — Measure memory after cleanup

```zsh
echo "=== Docker container memory AFTER cleanup ==="
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | sort -k3 -rn

echo "=== Docker disk usage AFTER ==="
docker system df

echo "=== Free memory ==="
vm_stat | head -10
```

---

## Phase 2 — Install Ollama on Bob

### Step 2.1 — Install Ollama

```zsh
curl -fsSL https://ollama.com/install.sh | sh
```

If that doesn't work on macOS, use Homebrew:

```zsh
brew install ollama
```

Start it as a background service:

```zsh
brew services start ollama
```

Verify it's running:

```zsh
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```

### Step 2.2 — Pull the model

Start with `llama3.2:3b` — smallest, fastest, proven:

```zsh
ollama pull llama3.2:3b
```

Verify:

```zsh
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; [print(f'  {m[\"name\"]} ({m[\"details\"][\"parameter_size\"]})') for m in json.load(sys.stdin)['models']]"
```

### Step 2.3 — Benchmark on Bob

```zsh
time curl -s http://127.0.0.1:11434/api/generate -d '{
  "model": "llama3.2:3b",
  "prompt": "Extract insights as JSON array: AI startup funding reached $100B in 2025. Crypto markets rallied 15% on ETF approval. Housing starts declined in Q3.",
  "stream": false,
  "options": {"num_predict": 256, "temperature": 0.1}
}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Tokens: {d.get('eval_count',0)}, Time: {d.get('eval_duration',0)/1e9:.1f}s, Speed: {d.get('eval_count',0)/(d.get('eval_duration',1)/1e9):.1f} tok/s\")"
```

Expected: 20-40 tok/s with Metal acceleration on M4.

If the speed is good (>15 tok/s), also try pulling `qwen3.5:4b` which is smarter:

```zsh
ollama pull qwen3.5:4b
```

Benchmark qwen3.5:4b the same way. If it's >10 tok/s, use it as the default instead.

### Step 2.4 — Set Ollama to start on boot

Create a launchd plist so Ollama survives reboots:

```zsh
cat > ~/Library/LaunchAgents/com.symphony.ollama.plist << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.ollama</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ollama</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ollama.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>0.0.0.0:11434</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key>
        <string>1</string>
        <key>OLLAMA_NUM_PARALLEL</key>
        <string>1</string>
    </dict>
</dict>
</plist>
PLIST_EOF
```

Notes on the env vars:
- `OLLAMA_HOST=0.0.0.0:11434` — listen on all interfaces (Docker containers need to reach it)
- `OLLAMA_MAX_LOADED_MODELS=1` — only keep 1 model in RAM at a time (critical for 16GB)
- `OLLAMA_NUM_PARALLEL=1` — 1 concurrent request (saves RAM)

Check if `ollama` is at `/usr/local/bin/ollama` or `/opt/homebrew/bin/ollama`:

```zsh
which ollama
```

Update the plist ProgramArguments path to match.

Load it:

```zsh
launchctl load ~/Library/LaunchAgents/com.symphony.ollama.plist
```

If Ollama was already running from `brew services start`, stop that first:

```zsh
brew services stop ollama
launchctl load ~/Library/LaunchAgents/com.symphony.ollama.plist
```

Verify:

```zsh
sleep 3
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; print('Ollama OK:', len(json.load(sys.stdin).get('models',[])), 'models')"
```

### Step 2.5 — Rewire Docker services to use Bob's local Ollama

Docker containers can reach the Mac host via `host.docker.internal`. Update docker-compose.yml:

Change the OLLAMA_HOST default everywhere from `http://192.168.1.199:11434` to `http://host.docker.internal:11434`:

```zsh
cd ~/AI-Server
sed -i '' 's|OLLAMA_HOST:-http://192.168.1.199:11434|OLLAMA_HOST:-http://host.docker.internal:11434|g' docker-compose.yml
```

Verify the change:

```zsh
grep "OLLAMA_HOST" docker-compose.yml
```

All lines should now show `http://host.docker.internal:11434`.

Also update any Python files that hardcode the Maestro IP:

```zsh
grep -rn "192.168.1.199" --include="*.py" | grep -v ".cursor/prompts/"
```

For each match, change `192.168.1.199` to `host.docker.internal` in the default/fallback value. The env var override will still work if someone sets OLLAMA_HOST explicitly.

### Step 2.6 — Also update imessage-server.py (runs on host, not Docker)

The imessage-server runs directly on the Mac host, so it should use `127.0.0.1` not `host.docker.internal`:

In `scripts/imessage-server.py`, find the OLLAMA_HOST reference and make sure it defaults to `http://127.0.0.1:11434` (not Maestro's IP).

### Step 2.7 — Rebuild and restart all Ollama-using services

```zsh
cd ~/AI-Server
docker compose build cortex-autobuilder x-intake openclaw calendar-agent polymarket-bot cortex
docker compose up -d
```

Wait 60s, verify:

```zsh
sleep 60
docker ps --format "table {{.Names}}\t{{.Status}}" | sort
```

### Step 2.8 — Test Ollama from inside a container

```zsh
docker exec cortex-autobuilder python3 -c "
import urllib.request, json
req = urllib.request.Request('http://host.docker.internal:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
print('Ollama reachable from Docker:', [m['name'] for m in data['models']])
"
```

### Step 2.9 — Check Ollama is actually being used

```zsh
sleep 120
docker logs cortex-autobuilder --tail 30 --since 3m 2>&1 | grep -E "ollama|scanner_"
docker logs x-intake --tail 30 --since 3m 2>&1 | grep -i "ollama"
```

If you see successful Ollama calls (no `scanner_ollama_error`), we're golden. Metal acceleration on M4 should handle `llama3.2:3b` in 5-15 seconds per call instead of timing out.

### Step 2.10 — Final memory check

```zsh
echo "=== Final system state ==="
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | sort -k3 -rn
echo ""
echo "=== Ollama memory ==="
ps aux | grep ollama | grep -v grep
echo ""
echo "=== Total memory pressure ==="
memory_pressure
```

---

## Output

Commit and push:

```zsh
cd ~/AI-Server
bash scripts/pull.sh
git add -A
git commit -m "ops: move Ollama to Bob (M4 Metal) + container cleanup

Phase 1 — Cleanup:
- Removed containers: [LIST WHAT WAS REMOVED]
- Removed launchd agents: [LIST WHAT WAS REMOVED]
- Docker prune freed: [X GB]
- RAM freed: [before vs after]

Phase 2 — Ollama on Bob:
- Installed Ollama with Metal acceleration
- Model: [llama3.2:3b and/or qwen3.5:4b]
- Benchmark: [X tok/s] (vs 3-6 tok/s on Maestro CPU)
- OLLAMA_HOST changed from 192.168.1.199 to host.docker.internal
- Ollama launchd plist installed (survives reboot)
- All Ollama-using services rebuilt and verified"
git push
```

Report:
1. Before/after RAM usage
2. What was removed and why
3. Ollama benchmark on Bob (tok/s)
4. Which model was selected as default
5. Whether services are successfully using local Ollama
6. Any errors or issues
