# Cline Prompt: Bob as Sole Primary Node + Retire Maestro + Prep M2 Worker

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

## Task 3: Prep M2 MacBook Pro as Future Worker

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

### 3.2 Add M2 worker to openclaw_workers.json
Add a planned worker entry:
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

### 3.3 Create M2 setup script
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

## Task 4: DO NOT TOUCH These

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
- [ ] M2 MacBook Pro added to nodes_registry.json (status: planned)
- [ ] M2 setup script created and executable
- [ ] `docker compose config` validates without errors
- [ ] All existing services still running (`docker compose ps`)

## Commit
Commit all changes with message: `feat: restore x-intake-lab, retire Maestro, prep M2 worker node`
Push to main.
