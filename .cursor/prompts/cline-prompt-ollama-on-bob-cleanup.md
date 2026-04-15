# Cline Prompt: Migrate Ollama to Bob + Conservative Container Cleanup

## IMPORTANT — Read First
Before making ANY changes, read `STATUS_REPORT.md` and `CLAUDE.md` to understand the full system. Do NOT assume any service is unused — almost everything is wired into the pipeline.

## Overview
Two tasks:
1. **Migrate Ollama from Maestro to Bob** — Bob (Mac Mini M4, 16GB) is far faster than Maestro (2019 iMac, i3 CPU-only)
2. **Conservative container cleanup** — only remove confirmed dead containers, add memory limits to free resources

## Task 1: Install and Configure Ollama on Bob

### 1.1 Install Ollama on Bob
SSH to Bob (`192.168.1.189` or Tailscale `100.89.1.51`):

```
curl -fsSL https://ollama.com/install.sh | sh
```

### 1.2 Pull the required model
```
ollama pull llama3.2:3b
```

### 1.3 Configure Ollama to listen on all interfaces
Edit the Ollama service config so it binds to `0.0.0.0:11434` (not just localhost). On macOS this means setting the environment variable:

```
launchctl setenv OLLAMA_HOST "0.0.0.0"
```

Then restart Ollama and verify:
```
ollama serve
```

Test from another machine:
```
curl http://192.168.1.189:11434/api/tags
```

### 1.4 Update all Ollama endpoint references
The global speed fix (commit `b6a4641`) already switched models to `llama3.2:3b`. Now update the Ollama base URL everywhere it appears. Search the entire repo for any reference to `192.168.1.199` (Maestro) or `localhost:11434` and replace with Bob's address.

Key files to check (non-exhaustive — grep the whole repo):
- `bob/cortex/memory_engine.py`
- `bob/cortex/daily_digest.py`
- `bob/cortex/query_engine.py`
- `bob/cortex/ingest_memories.py`
- `tools/ai_receptionist/call_handler.py`
- `tools/ai_receptionist/receptionist_brain.py`
- `tools/notes_ingest_v2/ingest.py`
- `tools/notes_ingest_v2/ingest_v2.py`
- `tools/clawwork/analyzer.py`
- `tools/clawwork/claw_intelligence.py`
- `tools/clawwork/proposal_brain.py`
- `intel/polymarket-bot/strategy_engine.py`
- `intel/polymarket-bot/market_analyzer.py`
- `intel/x-alpha-collector/alpha_signals.py`
- `intel/x-alpha-collector/signal_processor.py`
- Any `.env` files or docker-compose sections referencing Ollama

Replace with: `http://192.168.1.189:11434`

**Do NOT change the model names** — those were already fixed to `llama3.2:3b` in the previous commit.

### 1.5 Verify Ollama is working on Bob
After updating endpoints, test one of the services to confirm it can reach Ollama on Bob and get a response.

## Task 2: Conservative Container Cleanup

### 2.1 Remove ONLY confirmed dead containers
The ONLY container confirmed as dead/experimental duplicate is:

- **x-intake-lab** — experimental duplicate of x-alpha-collector, not used

Remove it from `docker-compose.yml` and delete its directory if it exists separately.

**DO NOT remove any other containers.** Every other service is wired into the system:
- `intel-feeds` feeds `polymarket-bot` trading signals
- `x-alpha-collector` feeds Cortex `x_intel`
- `clawwork` is side-hustle earnings tracking
- `voice-receptionist` has Cortex integration
- `proposals` is core business
- `client-portal` is for symphonysh.com website (proposal/docusign/payment)
- All other services are active parts of the pipeline

### 2.2 Add memory limits to Docker containers
Add memory limits to `docker-compose.yml` for all services to prevent any single container from hogging Bob's 16GB RAM. Use `deploy.resources.limits.memory` or `mem_limit`:

| Service | Memory Limit |
|---------|-------------|
| cortex | 2GB |
| polymarket-bot | 1GB |
| voice-receptionist | 512MB |
| proposals | 512MB |
| client-portal | 512MB |
| intel-feeds | 512MB |
| x-alpha-collector | 512MB |
| clawwork | 512MB |
| redis | 256MB |
| All others | 256MB each |

This ensures Docker stays under ~8GB total, leaving the other 8GB for Ollama and macOS.

### 2.3 DO NOT touch the markup tool
The markup tool (`tools/markup_app/server.py`) runs on port 8088 via launchd plist `com.symphony.markup-app` with KeepAlive. It is NOT a Docker container. Leave it completely alone.

## Verification Checklist
- [ ] Ollama installed and running on Bob (`192.168.1.189:11434`)
- [ ] `llama3.2:3b` model pulled on Bob
- [ ] All Ollama endpoint references updated from Maestro to Bob
- [ ] `x-intake-lab` removed from docker-compose.yml
- [ ] Memory limits added to all Docker services
- [ ] Markup tool on port 8088 untouched
- [ ] Client portal unchanged (internal Docker container, port 8096)
- [ ] `docker compose up -d` runs cleanly
- [ ] At least one Ollama-dependent service tested and working

## Commit
Commit all changes with message: `feat: migrate Ollama to Bob M4 + remove x-intake-lab + add memory limits`
Push to main.
