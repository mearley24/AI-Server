# Cline Prompt: Bob as Sole Team Member + M2 MacBook Pro as Worker

## IMPORTANT — Read First
Read `STATUS_REPORT.md` and `CLAUDE.md` completely before making any changes. Do NOT assume any service is unused.

## Overview
Bob (Mac Mini M4, 16GB) becomes the single primary node that handles everything — Docker services, Ollama, orchestration. Maestro (2019 iMac) is being retired. The M2 MacBook Pro (16GB) will be prepped as a future worker node.

Three tasks:
1. **Install Ollama on Bob** and point all services to localhost
2. **Remove Maestro references** — clean out all hardcoded Maestro IPs and configs
3. **Conservative cleanup** — remove confirmed dead services, add memory limits, update node registry
4. **Prep M2 worker config** — add M2 to the node registry as a future Ollama worker

## Task 1: Install and Configure Ollama on Bob

### 1.1 Install Ollama
On Bob:
```
curl -fsSL https://ollama.com/install.sh | sh
```

### 1.2 Pull the required model
```
ollama pull llama3.2:3b
```

### 1.3 Configure Ollama to listen on all interfaces
So the M2 (and future workers) can also reach Bob's Ollama if needed:
```
launchctl setenv OLLAMA_HOST "0.0.0.0"
```
Restart Ollama and verify:
```
curl http://127.0.0.1:11434/api/tags
```

### 1.4 Update OLLAMA_HOST in docker-compose.yml
Change ALL `OLLAMA_HOST` defaults from `http://192.168.1.199:11434` to `http://host.docker.internal:11434`.

This applies to these services (7 total):
- polymarket-bot
- calendar-agent
- openclaw
- cortex
- x-intake
- cortex-autobuilder
- x-intake-lab (will be removed in Task 3, but update before removing so the diff is clean)

Use `host.docker.internal` because Ollama runs on the host (not in Docker), and Docker containers need this special hostname to reach host services.

### 1.5 Update all Python files referencing Maestro IP
Search the entire repo for `192.168.1.199` and replace with `host.docker.internal` (for code that runs in containers) or `127.0.0.1` (for code that runs on the host).

Key files to grep and update:
- Any `.py` file with `192.168.1.199`
- `scripts/verify-readonly.sh` (line 139)
- `start_symphony.sh` (line 370 — the Ollama status display)

For Python files in Docker services, use `http://host.docker.internal:11434`.
For Python files that run on the host (tools/, scripts/), use `http://127.0.0.1:11434`.

### 1.6 Update .env file
If `.env` has an `OLLAMA_HOST` variable, update it to `http://host.docker.internal:11434`.

## Task 2: Remove Maestro/Betty References

### 2.1 Clean up setup files
These files are Maestro-specific and no longer needed. Delete them:
- `scripts/setup-ollama-maestro.sh`
- `setup/launchd/com.symphony.worker-betty.plist`
- `setup/launchd/com.symphony.employee-betty-bot.plist`

### 2.2 Update node registry
Edit `setup/nodes/nodes_registry.json`:
- Change Maestro's `"status"` from `"active"` to `"retired"`
- Add a `"retired_date": "2026-04-16"` field
- Update Bob's `"notes"` to: `"HQ node. Runs all Docker services, Ollama (llama3.2:3b), OpenClaw conductor. Primary for all inference."`
- Update Bob's `"network"` → `"ip"` to `"192.168.1.189"` (actual current IP)

### 2.3 Update openclaw_workers.json
Edit `setup/nodes/openclaw_workers.json`:
- Change all `"maestro_ollama"` references to `"bob_ollama"`
- Change all `"maestro_harpa"` references to `"bob_harpa"` (or remove if HARPA is not running on Bob)
- Update node_id from `"maestro"` to `"bob"` for those workers
- Remove or comment out Maestro-specific worker entries that no longer apply

### 2.4 Update business_hours_throttle.py
Edit `tools/business_hours_throttle.py`:
- Remove the Betty-specific plist names from the throttle list:
  - `com.symphony.betty-learner`
  - `com.symphony.employee-betty-bot`
  - `com.symphony.worker-betty`

### 2.5 Clean up setup_ui references
The setup UI (`setup/setup_ui/server.py` and `setup/setup_ui/README.md`) heavily references Betty. Update these to reference the M2 MacBook Pro instead of Betty, or mark as deprecated if the setup UI is no longer used.

## Task 3: Conservative Cleanup

### 3.1 Remove ONLY confirmed dead containers
Remove from `docker-compose.yml`:
- **x-intake-lab** — experimental duplicate of x-intake, confirmed unused

**DO NOT remove any other service.** Everything else is wired into the pipeline.

### 3.2 Add memory limits to all Docker services
Add `mem_limit` to each service in `docker-compose.yml`:

| Service | Memory Limit | Rationale |
|---------|-------------|-----------|
| cortex | 2GB | Brain — heaviest service |
| polymarket-bot | 1GB | Trading — needs headroom |
| openclaw | 1GB | Orchestrator |
| voice-receptionist | 512MB | Node.js Twilio |
| proposals | 512MB | PDF generation |
| client-portal | 512MB | E-signature pages |
| email-monitor | 512MB | IMAP polling |
| notification-hub | 512MB | Message routing |
| clawwork | 512MB | Background workflows |
| calendar-agent | 256MB | Calendar sync |
| dtools-bridge | 256MB | API bridge |
| x-intake | 512MB | X/Twitter analysis |
| x-alpha-collector | 256MB | RSS monitoring |
| intel-feeds | 256MB | Intel aggregation |
| cortex-autobuilder | 512MB | Research loop |
| rsshub | 256MB | Node.js RSS proxy |
| redis | 256MB | Cache/pubsub |
| vpn | 128MB | WireGuard tunnel |

Total: ~9GB max, leaving ~7GB for Ollama + macOS. In practice containers will use much less than their limits.

### 3.3 DO NOT touch the markup tool
The markup tool (`tools/markup_app/server.py`) runs on port 8088 via launchd plist `com.symphony.markup-app` with KeepAlive. It is NOT a Docker container. Leave it completely alone.

## Task 4: Prep M2 MacBook Pro as Future Worker

### 4.1 Add M2 to node registry
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
    "ip": "TBD",
    "hostname": "m2.local",
    "mac_address": ""
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
  "status": "planned",
  "notes": "Future Ollama worker. Apple Silicon Metal acceleration. Can offload inference from Bob when available on the network. Not always-on (laptop).",
  "added_date": "2026-04-16"
}
```

### 4.2 Update openclaw_workers.json
Add an M2 Ollama worker entry (status: planned) so the routing config is ready when the M2 comes online:

```json
{
  "worker_id": "m2_ollama",
  "display_name": "M2 MacBook Pro (LLM)",
  "node_id": "m2",
  "type": "ollama",
  "endpoint": "http://TBD:11434",
  "priority": 60,
  "capabilities": ["text_generation", "summarization", "classification"],
  "models": ["llama3.2:3b"],
  "status": "planned",
  "notes": "Available when laptop is on the network. Not always-on."
}
```

### 4.3 Create M2 setup script
Create `scripts/setup-ollama-m2.sh`:

```
#!/bin/zsh
set -euo pipefail
printf 'M2 MacBook Pro Ollama Worker Setup\n'
printf '===================================\n\n'

printf 'Step 1: Installing Ollama...\n'
curl -fsSL https://ollama.com/install.sh | sh

printf '\nStep 2: Pulling llama3.2:3b...\n'
ollama pull llama3.2:3b

printf '\nStep 3: Configuring Ollama to listen on all interfaces...\n'
launchctl setenv OLLAMA_HOST "0.0.0.0"

printf '\nStep 4: Restarting Ollama...\n'
pkill ollama 2>/dev/null || true
sleep 2
ollama serve &
sleep 3

printf '\nStep 5: Verifying...\n'
curl -s http://127.0.0.1:11434/api/tags && printf '\n\nOllama is running.\n'

printf '\nDone. Update the IP address in setup/nodes/nodes_registry.json on Bob.\n'
printf 'Bob can reach this machine at: '
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk "{print \$2}" | head -1
printf '\n'
```

Make it executable: `chmod +x scripts/setup-ollama-m2.sh`

## Verification Checklist
- [ ] Ollama installed and running on Bob (127.0.0.1:11434)
- [ ] `llama3.2:3b` model pulled on Bob
- [ ] All `OLLAMA_HOST` in docker-compose.yml point to `host.docker.internal:11434`
- [ ] No remaining references to `192.168.1.199` in any `.py`, `.sh`, `.yml`, or `.json` file
- [ ] `x-intake-lab` removed from docker-compose.yml
- [ ] Memory limits added to all Docker services
- [ ] Maestro marked as retired in nodes_registry.json
- [ ] M2 MacBook Pro added to nodes_registry.json (status: planned)
- [ ] M2 setup script created and executable
- [ ] Markup tool on port 8088 untouched
- [ ] Client portal unchanged (internal, port 8096)
- [ ] `docker compose config` validates without errors
- [ ] At least one Ollama-dependent service tested and working against localhost

## Commit
Commit all changes with message: `feat: Bob as primary node, retire Maestro, prep M2 worker, add memory limits`
Push to main.
