# Cline Prompt: Bob as Sole Primary Node + Retire Maestro + M2 Always-On Worker

## IMPORTANT — Read First
Read `STATUS_REPORT.md` and `CLAUDE.md` completely before making any changes. Do NOT assume any service is unused.

## Context — What's Already Done
The previous prompt (`cline-prompt-ollama-on-bob-cleanup.md`) already completed:
- Ollama installed on Bob (46.8 tok/s on M4 Metal)
- All OLLAMA_HOST references updated to Bob (192.168.1.189:11434)
- Memory limits added to all Docker services
- llama3.2:3b pulled and working

**x-intake-lab was incorrectly removed** — it needs to be restored. It runs transcript analysis and bookmark organization feeding into Cortex. Not a throwaway experiment.

## Task 1: Restore x-intake-lab to docker-compose.yml

Add this service back to `docker-compose.yml` (it was incorrectly removed):

```yaml
  x-intake-lab:
    build: ./integrations/x_intake
    container_name: x-intake-lab
    restart: unless-stopped
    command: ["python3", "lab_main.py"]
    ports:
      - "127.0.0.1:8103:8101"
    mem_limit: 512m
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=${REDIS_PASSWORD}
      - CORTEX_URL=http://cortex:8102
      - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.189:11434}
      - OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-llama3.2:3b}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - PYTHONUNBUFFERED=1
      - TZ=America/Denver
      - LAB_MODE=true
    volumes:
      - ./data/transcripts:/data/transcripts
      - ./data/bookmarks:/data/bookmarks
      - x-intake-lab-data:/data/lab
    networks:
      - default
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
```

Also restore the `x-intake-lab-data` volume at the bottom of docker-compose.yml if it was removed:
```yaml
volumes:
  x-intake-lab-data:
```

Note the updates from the old version:
- `OLLAMA_HOST` now points to Bob (192.168.1.189) not Maestro
- `OLLAMA_ANALYSIS_MODEL` updated to `llama3.2:3b` (was `qwen3:8b`)
- `mem_limit: 512m` added to match the other services

Run `docker compose up -d --build x-intake-lab` to bring it back up.

## Task 2: Remove Maestro/Betty References

Maestro (2019 iMac) is being retired. Bob handles everything now.

### 2.1 Delete Maestro-specific files
- `scripts/setup-ollama-maestro.sh`
- `setup/launchd/com.symphony.worker-betty.plist`
- `setup/launchd/com.symphony.employee-betty-bot.plist`

### 2.2 Update node registry
Edit `setup/nodes/nodes_registry.json`:
- Change Maestro's `"status"` from `"active"` to `"retired"`
- Add `"retired_date": "2026-04-16"` to the Maestro entry
- Update Bob's `"notes"` to: `"HQ node. Runs all Docker services, Ollama (llama3.2:3b), OpenClaw conductor. Primary for all inference. 46.8 tok/s on M4 Metal."`
- Update Bob's `"network"` -> `"ip"` to `"192.168.1.189"` (actual current IP)

### 2.3 Update openclaw_workers.json
Edit `setup/nodes/openclaw_workers.json`:
- Change all `"maestro_ollama"` worker references to `"bob_ollama"` with `"node_id": "bob"`
- Change all `"maestro_harpa"` references — remove these entries entirely (HARPA is not on Bob)
- Update endpoints from Maestro IP to `http://192.168.1.189:11434`

### 2.4 Update business_hours_throttle.py
Edit `tools/business_hours_throttle.py` — remove these Betty-specific plist names:
- `com.symphony.betty-learner`
- `com.symphony.employee-betty-bot`
- `com.symphony.worker-betty`

### 2.5 Update setup_ui
Edit `setup/setup_ui/server.py` and `setup/setup_ui/README.md`:
- Replace Betty references with M2 MacBook Pro where applicable
- Update the verify section to check M2 instead of Betty
- Update default IP placeholder

### 2.6 Grep for any remaining Maestro references
Run: `grep -rn "192.168.1.199\|192.168.1.132\|maestro\.local" --include="*.py" --include="*.sh" --include="*.json" --include="*.yml" .`
Fix anything that still points to Maestro. The docker-compose.yml and Python service files were already updated in the previous prompt — this is for anything that was missed.

## Task 3: Set Up M2 MacBook Pro as Always-On Worker

The M2 MacBook Pro (16GB, Apple Silicon) is an always-on worker node. It sits on the home network 24/7, but also travels with the owner. When traveling, it connects back to Bob via Tailscale VPN through a GL.iNet WiFi 7 travel router.

### 3.1 Add M2 to node registry
Add a new entry to `setup/nodes/nodes_registry.json`:

```json
{
  "node_id": "m2",
  "display_name": "M2 MacBook Pro",
  "role": "llm_worker",
  "hardware": {
    "model": "MacBook Pro M2",
    "cpu": "Apple M2",
    "ram_gb": 16,
    "storage_gb": 512,
    "architecture": "arm64",
    "notes": "Apple Silicon with Metal GPU acceleration. Good for 3B-8B models."
  },
  "network": {
    "lan_ip": "TBD",
    "tailscale_ip": "TBD",
    "hostname": "m2.local",
    "mac_address": "",
    "notes": "LAN IP when home. Tailscale IP when traveling via GL.iNet travel router. Services should prefer Tailscale IP for reliability across both modes."
  },
  "services": {
    "ollama": true,
    "ollama_port": 11434,
    "ollama_host": "0.0.0.0",
    "docker": false,
    "registry_api": false,
    "harpa": false,
    "openclaw": false
  },
  "models_loaded": [],
  "status": "active",
  "notes": "Always-on Ollama worker. Apple Silicon Metal acceleration. On home LAN 24/7 normally. When traveling, connects back to Bob via Tailscale VPN through GL.iNet WiFi 7 travel router — remains reachable at its Tailscale IP from anywhere with internet.",
  "added_date": "2026-04-16"
}
```

### 3.2 Add M2 worker to openclaw_workers.json
Add an active worker entry:
```json
{
  "worker_id": "m2_ollama",
  "display_name": "M2 MacBook Pro (LLM)",
  "node_id": "m2",
  "type": "ollama",
  "endpoint": "http://TBD:11434",
  "priority": 50,
  "capabilities": ["text_generation", "summarization", "classification"],
  "models": ["llama3.2:3b"],
  "status": "active",
  "notes": "Always-on active worker. Handles heavier inference (transcript analysis, research loops, batch processing). Reachable via Tailscale IP when traveling. Bob's Ollama handles speed-critical requests (trading, orchestrator).",
  "health_check": "http://TBD:11434/api/tags",
  "fallback_endpoint": "http://TBD:11434"
}
```

Note: Priority 50 means the M2 is an active equal worker, not just overflow. Once the benchmark results come in, we'll route specific services to the M2 based on performance. Update the TBD IPs once Tailscale is configured on the M2.

### 3.3 Update llm_router.py for dual-node routing
The LLM router (`openclaw/llm_router.py`) needs to know about the M2 as an active inference endpoint. After the M2 is set up and benchmarked, the routing logic should:
- Send lightweight/fast requests (classification, short summaries) to Bob's local Ollama (lowest latency, no network hop)
- Send heavier requests (transcript analysis, research loops, long-form generation) to the M2's Ollama (dedicated resources, no Docker competition)
- Fall back to the other node if one is unreachable (M2 traveling, Bob under load)

For now, add a config entry in `.env` for the M2 Ollama endpoint:
```
M2_OLLAMA_HOST=http://TBD:11434
```

The specific routing split will be decided after benchmark results.

Services that are good candidates to route to the M2:
- `cortex-autobuilder` (research loop, runs every 60 min, heavy inference)
- `x-intake-lab` (transcript analysis, batch processing)
- `x-intake` (X/Twitter analysis)
- `intel-feeds` (intel aggregation)
- `x-alpha-collector` (when it needs LLM analysis)

Services that should stay on Bob's local Ollama (speed-critical, low latency):
- `openclaw` (orchestrator, needs fast responses)
- `cortex` (brain, real-time queries)
- `polymarket-bot` (trading, time-sensitive)
- `calendar-agent` (quick classification)

### 3.4 Create M2 setup script
Create `scripts/setup-m2-worker.sh`:

```
#!/bin/zsh
set -euo pipefail
printf 'M2 MacBook Pro — Always-On Worker Setup\n'
printf '=========================================\n\n'

printf 'This script sets up the M2 as an always-on Ollama worker with Tailscale.\n'
printf 'Run this ON the M2 MacBook Pro.\n\n'

printf '=== Part 1: Ollama ===\n\n'

printf 'Step 1: Installing Ollama...\n'
curl -fsSL https://ollama.com/install.sh | sh

printf '\nStep 2: Pulling llama3.2:3b...\n'
ollama pull llama3.2:3b

printf '\nStep 3: Configuring Ollama to listen on all interfaces...\n'
launchctl setenv OLLAMA_HOST "0.0.0.0"

printf '\nStep 4: Restarting Ollama...\n'
pkill ollama 2>/dev/null || true
sleep 2
open -a Ollama 2>/dev/null || ollama serve &
sleep 3

printf '\nStep 5: Verifying Ollama...\n'
curl -s http://127.0.0.1:11434/api/tags && printf '\nOllama OK.\n'

printf '\n=== Part 2: Tailscale ===\n\n'

if command -v tailscale >/dev/null 2>&1; then
  printf 'Tailscale already installed.\n'
else
  printf 'Installing Tailscale...\n'
  printf 'Download from: https://tailscale.com/download/mac\n'
  printf 'Or install via brew: brew install tailscale\n'
  printf 'After installing, run this script again.\n'
  exit 1
fi

printf '\nTailscale status:\n'
tailscale status 2>/dev/null || printf 'Tailscale not connected. Run: tailscale up\n'

printf '\nTailscale IP:\n'
tailscale ip -4 2>/dev/null || printf 'Not available yet.\n'

printf '\n=== Part 3: Prevent Sleep ===\n\n'

printf 'Configuring M2 to stay awake with lid closed (clamshell mode)...\n'
printf 'IMPORTANT: The M2 must be connected to an external power source for clamshell mode.\n'
printf 'For always-on without external display, use:\n'
printf '  sudo pmset -a disablesleep 1\n'
printf '  sudo pmset -a sleep 0\n'
printf '  sudo pmset -a hibernatemode 0\n'
printf '  sudo pmset -a autopoweroff 0\n\n'

printf 'Current power settings:\n'
pmset -g | grep -E "sleep|hibernate|autopoweroff|displaysleep"

printf '\n=== Part 4: GL.iNet Travel Router Notes ===\n\n'

printf 'When traveling with the GL.iNet WiFi 7 travel router:\n'
printf '1. Enable Tailscale on the GL.iNet router (Applications > Tailscale)\n'
printf '2. Enable "Allow Remote Access LAN" in the Tailscale settings\n'
printf '3. Approve the subnet route in the Tailscale admin console\n'
printf '4. The M2 connects to the GL.iNet WiFi — all traffic to Bob tunnels through Tailscale\n'
printf '5. Bob reaches the M2 at its Tailscale IP (same IP whether home or traveling)\n\n'
printf 'Alternative: Run Tailscale directly on the M2 (simpler, works without the router):\n'
printf '  tailscale up --accept-routes\n'
printf '  Bob reaches M2 at its Tailscale IP regardless of physical network.\n\n'

printf '=== Setup Complete ===\n\n'
printf 'LAN IP: '
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk "{print \$2}" | head -1
printf 'Tailscale IP: '
tailscale ip -4 2>/dev/null || printf 'N/A'
printf '\n\nNext steps:\n'
printf '1. Update setup/nodes/nodes_registry.json on Bob with both IPs\n'
printf '2. Update setup/nodes/openclaw_workers.json endpoint to Tailscale IP\n'
printf '3. Test from Bob: curl http://<tailscale-ip>:11434/api/tags\n'
printf '4. Configure GL.iNet travel router Tailscale (for travel mode)\n'
```

Make it executable: `chmod +x scripts/setup-m2-worker.sh`

### 3.4 Create GL.iNet travel router setup guide
Create `setup/nodes/glinet_travel_router_setup.md`:

```markdown
# GL.iNet WiFi 7 Travel Router — Tailscale Setup Guide

## Purpose
Keep the M2 MacBook Pro connected to Bob's network securely from anywhere.
When traveling, the M2 connects to the GL.iNet travel router's WiFi, which
tunnels all traffic back to the home Tailnet via Tailscale.

## Architecture

### At Home
M2 (LAN: 192.168.1.x) <--LAN--> Bob (192.168.1.189)
M2 (Tailscale: x.x.x.x) <--Tailscale--> Bob (Tailscale: 100.89.1.51)

### Traveling
M2 --> GL.iNet WiFi --> Hotel/Airport Internet --> Tailscale Tunnel --> Bob (100.89.1.51)

## GL.iNet Router Setup (One-Time)

1. Power on the GL.iNet travel router and connect to its WiFi (default: GL-XXXX)
2. Access admin panel at http://192.168.8.1
3. Go to **Applications > Tailscale**
4. Click **Enable** and sign in with your Tailscale account
5. Enable **Allow Remote Access LAN**
6. In the Tailscale admin console (https://login.tailscale.com/admin/machines):
   - Find the GL.iNet device
   - Click the three dots > Edit route settings
   - Approve the advertised subnet (192.168.8.0/24)

## Travel Workflow

1. Plug in the GL.iNet router at the hotel/location
2. Connect it to the available internet (WiFi repeater, ethernet, or tethering)
3. Connect the M2 to the GL.iNet WiFi
4. Tailscale tunnel activates automatically
5. Bob can reach M2's Ollama at the M2's Tailscale IP
6. All traffic between M2 and Bob is encrypted

## Two Connectivity Options

### Option A: Tailscale on the GL.iNet Router (Recommended for Travel)
- All devices on the GL.iNet WiFi get tunneled
- No Tailscale needed on individual devices
- Router handles the VPN overhead
- GL.iNet Slate 7 WireGuard throughput: up to 490 Mbps

### Option B: Tailscale Directly on the M2 (Simpler)
- Works without the travel router
- M2 connects to any WiFi and Tailscale tunnels directly
- Good as a backup if the router is not available
- Run: `tailscale up --accept-routes`

### Recommended: Use Both
- Tailscale on the M2 directly (always connected to tailnet)
- GL.iNet router as a travel WiFi with additional Tailscale subnet routing
- This gives double redundancy — M2 stays reachable even if one method fails

## Security Notes
- All traffic between M2 and Bob is encrypted via WireGuard (Tailscale)
- No ports need to be opened on the home router
- No port forwarding required
- The GL.iNet router adds a second layer of network isolation when on untrusted WiFi
- Bob's Tailscale IP: 100.89.1.51 (stable, never changes)

## Verifying Connectivity
From Bob:
  curl http://<m2-tailscale-ip>:11434/api/tags

From M2:
  curl http://100.89.1.51:11434/api/tags

If both return model lists, the tunnel is working.
```

## Task 4: Benchmark Ollama on Bob (and prep M2 benchmark)

We need actual numbers to know what models each machine can handle. Run benchmarks on Bob now. The M2 benchmark will be run after `setup-m2-worker.sh` is executed on the M2.

### 4.1 Create the benchmark script
Create `scripts/ollama-benchmark.sh`:

```
#!/bin/zsh
set -euo pipefail

HOST="${1:-http://127.0.0.1:11434}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
HOSTNAME_SHORT=$(hostname -s)
OUTFILE="data/benchmarks/ollama_${HOSTNAME_SHORT}_${TIMESTAMP}.md"
mkdir -p data/benchmarks

printf '## Ollama Benchmark: %s\n' "$HOSTNAME_SHORT" > "$OUTFILE"
printf 'Date: %s\n' "$(date)" >> "$OUTFILE"
printf 'Host: %s\n\n' "$HOST" >> "$OUTFILE"

printf '| Model | Size | Eval Rate (tok/s) | Prompt Rate (tok/s) | Status |\n' >> "$OUTFILE"
printf '|-------|------|-------------------|---------------------|--------|\n' >> "$OUTFILE"

TEST_PROMPT="Explain the concept of supply and demand in economics in exactly three sentences."

benchmark_model() {
  local model="$1"
  printf 'Benchmarking %s...\n' "$model"
  
  ollama pull "$model" 2>/dev/null
  
  local result
  result=$(curl -s -X POST "${HOST}/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${model}\", \"prompt\": \"${TEST_PROMPT}\", \"stream\": false, \"options\": {\"temperature\": 0}}" \
    --max-time 120 2>/dev/null || echo "TIMEOUT")
  
  if [ "$result" = "TIMEOUT" ]; then
    printf '| %s | - | TIMEOUT | TIMEOUT | FAIL |\n' "$model" >> "$OUTFILE"
    printf '  %s: TIMEOUT\n' "$model"
    return
  fi
  
  local eval_count eval_duration prompt_count prompt_duration
  eval_count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('eval_count',0))" 2>/dev/null || echo "0")
  eval_duration=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('eval_duration',1))" 2>/dev/null || echo "1")
  prompt_count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('prompt_eval_count',0))" 2>/dev/null || echo "0")
  prompt_duration=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('prompt_eval_duration',1))" 2>/dev/null || echo "1")
  
  local eval_rate prompt_rate model_size
  eval_rate=$(python3 -c "print(f'{${eval_count}/(${eval_duration}/1e9):.1f}')" 2>/dev/null || echo "0")
  prompt_rate=$(python3 -c "print(f'{${prompt_count}/(${prompt_duration}/1e9):.1f}')" 2>/dev/null || echo "0")
  model_size=$(ollama list | grep "$model" | awk '{print $3 $4}' || echo "?")
  
  printf '| %s | %s | %s | %s | OK |\n' "$model" "$model_size" "$eval_rate" "$prompt_rate" >> "$OUTFILE"
  printf '  %s: %s tok/s eval, %s tok/s prompt\n' "$model" "$eval_rate" "$prompt_rate"
}

printf '\nStarting benchmarks against %s...\n\n' "$HOST"

benchmark_model "llama3.2:3b"
benchmark_model "llama3.2:1b"
benchmark_model "gemma3:4b"
benchmark_model "phi4-mini:3.8b"
benchmark_model "qwen3:4b"
benchmark_model "llama3.1:8b"
benchmark_model "gemma3:12b"

printf '\n### Memory After Benchmarks\n\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"
ollama ps >> "$OUTFILE" 2>/dev/null || printf 'ollama ps unavailable\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"

printf '\n### System Info\n\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"
system_profiler SPHardwareDataType 2>/dev/null | grep -E "Chip|Memory|Cores" >> "$OUTFILE" || printf 'system_profiler unavailable\n' >> "$OUTFILE"
printf '```\n' >> "$OUTFILE"

printf '\nBenchmark complete. Results saved to %s\n' "$OUTFILE"
cat "$OUTFILE"
```

Make it executable: `chmod +x scripts/ollama-benchmark.sh`

### 4.2 Run the benchmark on Bob
Execute on Bob:
```
bash scripts/ollama-benchmark.sh http://127.0.0.1:11434
```

This will:
- Pull and test 7 models ranging from 1B to 12B parameters
- Record eval tok/s (generation speed) and prompt tok/s (input processing speed)
- Save results to `data/benchmarks/ollama_bob_<timestamp>.md`
- Show which models are usable vs too slow vs OOM on 16GB

Models being tested:
- `llama3.2:1b` — tiny, baseline speed reference
- `llama3.2:3b` — current production model
- `gemma3:4b` — Google's latest small model
- `phi4-mini:3.8b` — Microsoft's efficient small model
- `qwen3:4b` — Alibaba's latest 4B
- `llama3.1:8b` — the big question: can 16GB handle 8B?
- `gemma3:12b` — stress test: will it even load on 16GB?

### 4.3 Commit benchmark results
Add `data/benchmarks/` to git and commit the results:
```
git add data/benchmarks/ scripts/ollama-benchmark.sh
git commit -m "feat: add Ollama benchmark script + Bob M4 results"
```

### 4.4 M2 benchmark (after M2 setup)
After running `setup-m2-worker.sh` on the M2, run the same benchmark:
```
bash scripts/ollama-benchmark.sh http://127.0.0.1:11434
```
Then copy `data/benchmarks/ollama_m2_*.md` to Bob's repo and commit. This gives us a side-by-side comparison to decide:
- Which models each machine should serve
- Whether to run different models on each (e.g., Bob handles 8B, M2 handles 3B overflow)
- Maximum model size each can handle without swapping

## Task 5: DO NOT TOUCH These

- **Markup tool** (`tools/markup_app/server.py`) on port 8088 via launchd — leave completely alone
- **Client portal** (`client-portal/main.py`) — internal Docker container on port 8096, leave alone
- **All other Docker services** — everything is wired into the pipeline, do not remove anything
- **Memory limits** — already added in previous prompt, do not change

## Verification Checklist
- [ ] x-intake-lab restored in docker-compose.yml and running (`docker compose ps x-intake-lab`)
- [ ] x-intake-lab health endpoint responding on port 8103
- [ ] No remaining references to `192.168.1.199` or `192.168.1.132` anywhere in the repo
- [ ] Maestro marked `"retired"` in nodes_registry.json
- [ ] Betty plist files and setup-ollama-maestro.sh deleted
- [ ] M2 MacBook Pro added to nodes_registry.json (status: active)
- [ ] M2 worker added to openclaw_workers.json
- [ ] `scripts/setup-m2-worker.sh` created and executable
- [ ] `scripts/ollama-benchmark.sh` created and executable
- [ ] `setup/nodes/glinet_travel_router_setup.md` created
- [ ] Bob benchmark ran successfully — results in `data/benchmarks/`
- [ ] `docker compose config` validates without errors
- [ ] All existing services still running (`docker compose ps`)

## Commit
Commit all changes with message: `feat: restore x-intake-lab, retire Maestro, M2 worker + travel router + benchmarks`
Push to main.
