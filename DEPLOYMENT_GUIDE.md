# Symphony Smart Homes — Master Deployment Guide

**Version:** 1.0 — February 2026  
**Repository:** [https://github.com/mearley24/AI-Server](https://github.com/mearley24/AI-Server)  
**Owner:** earleystream@gmail.com

> **Read this first.** Follow the phases in order. Do not skip ahead. Each phase produces a dependency the next phase needs.

---

## Table of Contents

1. [Infrastructure Overview](#1-infrastructure-overview)
2. [How Everything Connects](#2-how-everything-connects)
3. [Pre-Flight Checklist](#3-pre-flight-checklist)
4. [Phase 1 — Mac Mini M4 (OpenClaw)](#4-phase-1--mac-mini-m4-openclaw)
5. [Phase 2 — 64GB iMac (Ollama + HARPA)](#5-phase-2--64gb-imac-ollama--harpa)
6. [Phase 3 — 8GB iMac (HARPA Browser Only)](#6-phase-3--8gb-imac-harpa-browser-only)
7. [Phase 4 — Connect Everything](#7-phase-4--connect-everything)
8. [Verification & Smoke Tests](#8-verification--smoke-tests)
9. [Ongoing Maintenance](#9-ongoing-maintenance)
10. [Troubleshooting Quick Reference](#10-troubleshooting-quick-reference)

---

## 1. Infrastructure Overview

| Machine | Role | RAM | Key Software |
|---|---|---|---|
| Mac Mini M4 | Orchestrator (OpenClaw) | 16GB | Docker, OpenClaw, Nginx, Redis |
| iMac 64GB | AI Worker | 64GB | Ollama, HARPA, Docker |
| iMac 8GB | Browser Automation | 8GB | HARPA, Chrome |

**Network requirement:** All 3 machines on the same local network (LAN). Static IPs strongly recommended.

---

## 2. How Everything Connects

```
┌────────────────────────────────────────────────────────┐
│                    LOCAL NETWORK                         │
│                                                         │
│  ┌──────────────┐    HTTP/WS    ┌──────────────────┐   │
│  │  Mac Mini M4  │◄────────────►│   iMac 64GB      │   │
│  │  (OpenClaw)   │              │  (Ollama Worker)  │   │
│  │  Port 8080    │              │   Port 11434      │   │
│  └──────┬───────┘              └──────────────────┘   │
│         │                                               │
│         │ HTTP/WS              ┌──────────────────┐   │
│         └─────────────────────►│   iMac 8GB       │   │
│                                │  (HARPA Browser)  │   │
│                                │   Port 3000       │   │
│                                └──────────────────┘   │
└────────────────────────────────────────────────────────┘
```

**Data flows:**
- D-Tools Cloud jobs → OpenClaw (Mac Mini) → Ollama (64GB iMac) for AI inference
- OpenClaw → HARPA (either iMac) for browser automation tasks
- All results → OpenClaw → D-Tools Cloud

---

## 3. Pre-Flight Checklist

Complete these before touching any machine.

### Network
- [ ] All 3 Macs on same LAN (same router/switch)
- [ ] Assign static IPs (router DHCP reservation or manual):
  - Mac Mini M4: e.g., `192.168.1.10`
  - iMac 64GB: e.g., `192.168.1.20`
  - iMac 8GB: e.g., `192.168.1.30`
- [ ] Macs can ping each other: `ping 192.168.1.20` from Mac Mini
- [ ] Firewall allows ports: 8080, 11434, 3000, 6379

### Accounts & Credentials
- [ ] GitHub account with access to `mearley24/AI-Server`
- [ ] D-Tools Cloud API credentials (username + password or API key)
- [ ] HARPA AI account (free tier is fine)
- [ ] Docker Hub account (optional, for pulling images)

### Software Pre-installed
- [ ] Homebrew installed on all Macs: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- [ ] Xcode Command Line Tools: `xcode-select --install`
- [ ] Git: `git --version` (comes with Xcode CLT)

### Repo Cloned
On **every machine**:
```bash
cd ~
git clone https://github.com/mearley24/AI-Server.git
cd AI-Server
```

---

## 4. Phase 1 — Mac Mini M4 (OpenClaw)

**Goal:** Mac Mini M4 is fully running OpenClaw, accepting jobs, routing to workers.

**Estimated time:** 45–90 minutes

### Step 1 — Install Docker Desktop

1. Download from https://www.docker.com/products/docker-desktop/
2. Install the Apple Silicon (M-series) version
3. Launch Docker Desktop, complete setup
4. Verify: `docker --version` and `docker compose version`

### Step 2 — Install Python 3.11+

```bash
brew install python@3.11
python3 --version  # should show 3.11.x or higher
```

### Step 3 — Clone and Configure OpenClaw

```bash
cd ~/AI-Server
ls openclaw/  # confirm files are present
```

Expected files:
```
openclaw/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── orchestrator.py
├── config.py
└── README.md
```

### Step 4 — Create Environment File

```bash
cd ~/AI-Server/openclaw
cp .env.example .env  # if .env.example exists
# OR create from scratch:
cat > .env << 'EOF'
# OpenClaw Configuration
OPENCLAW_PORT=8080
REDIS_URL=redis://localhost:6379

# Worker endpoints (update with real IPs)
OLLAMA_WORKER_URL=http://192.168.1.20:11434
HARPA_WORKER_URL=http://192.168.1.20:3000
HARPA_WORKER_2_URL=http://192.168.1.30:3000

# D-Tools Cloud
DTOOLS_API_URL=https://api.d-toolscloud.com
DTOOLS_USERNAME=your_username_here
DTOOLS_PASSWORD=your_password_here

# Security
API_SECRET_KEY=change_this_to_a_random_string
EOF
```

**Edit the .env file** — replace placeholder values:
```bash
nano .env
# Update: OLLAMA_WORKER_URL, HARPA_WORKER_URL, DTOOLS_USERNAME, DTOOLS_PASSWORD, API_SECRET_KEY
```

### Step 5 — Start OpenClaw

```bash
cd ~/AI-Server/openclaw
docker compose up -d
```

Expected output:
```
[+] Running 3/3
 ✔ Container openclaw-redis-1      Started
 ✔ Container openclaw-app-1        Started
 ✔ Container openclaw-nginx-1      Started
```

### Step 6 — Verify OpenClaw is Running

```bash
# Check containers
docker compose ps

# Check health endpoint
curl http://localhost:8080/health
# Expected: {"status": "ok", "version": "1.0"}

# Check logs
docker compose logs app --tail=20
```

### Step 7 — Test from Another Machine

From iMac 64GB (once on network):
```bash
curl http://192.168.1.10:8080/health
# Should return same health JSON
```

### Phase 1 Complete ✅

Checkpoint: OpenClaw running on Mac Mini, health endpoint responding.

---

## 5. Phase 2 — 64GB iMac (Ollama + HARPA)

**Goal:** 64GB iMac running Ollama for AI inference and HARPA for browser automation.

**Estimated time:** 60–120 minutes (model download is slow)

### Step 1 — Install Ollama

```bash
# Download and install
curl -fsSL https://ollama.ai/install.sh | sh

# Verify installation
ollama --version

# Start Ollama service
ollama serve &
# OR install as a launchd service:
brew services start ollama
```

### Step 2 — Pull Required Models

```bash
# Pull the models OpenClaw expects
# Note: These are large downloads — use a fast connection

# Primary model (general tasks)
ollama pull llama3:8b
# ~4.7GB download

# Coding model (for automation scripts)
ollama pull codellama:13b
# ~7.4GB download

# Fast model (quick lookups)
ollama pull phi3:mini
# ~2.2GB download

# Verify models are ready
ollama list
```

Expected output from `ollama list`:
```
NAME              ID              SIZE    MODIFIED
llama3:8b         365c0bd3c000    4.7 GB  ...
codellama:13b     9f438cb9cd58    7.4 GB  ...
phi3:mini         4f2222927938    2.2 GB  ...
```

### Step 3 — Configure Ollama for Network Access

By default, Ollama only listens on localhost. Configure it to accept connections from the Mac Mini:

```bash
# Create or edit Ollama config
mkdir -p ~/.ollama
cat > ~/.ollama/config.json << 'EOF'
{
  "host": "0.0.0.0",
  "port": 11434
}
EOF

# Restart Ollama
brew services restart ollama
# OR: kill the process and re-run: ollama serve
```

Verify Ollama accepts external connections:
```bash
# From Mac Mini:
curl http://192.168.1.20:11434/api/tags
# Should return JSON list of models
```

### Step 4 — Install Docker Desktop

Same as Phase 1 — download and install Docker Desktop for Mac (Apple Silicon or Intel depending on your iMac).

```bash
docker --version
docker compose version
```

### Step 5 — Deploy HARPA Worker

```bash
cd ~/AI-Server/harpa
ls  # confirm files
```

Expected files:
```
harpa/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── harpa_worker.py
├── config.py
└── README.md
```

Create HARPA environment file:
```bash
cd ~/AI-Server/harpa
cat > .env << 'EOF'
# HARPA Worker Configuration
HARPA_PORT=3000
HARPA_WORKER_ID=imac-64gb-worker-1

# OpenClaw orchestrator (Mac Mini)
ORCHESTRATOR_URL=http://192.168.1.10:8080

# Chrome/Browser settings
CHROME_HEADLESS=true
CHROME_TIMEOUT=30

# D-Tools Cloud credentials (same as OpenClaw)
DTOOLS_API_URL=https://api.d-toolscloud.com
DTOOLS_USERNAME=your_username_here
DTOOLS_PASSWORD=your_password_here
EOF

nano .env  # update credentials
```

Start HARPA worker:
```bash
docker compose up -d
docker compose ps
curl http://localhost:3000/health
# Expected: {"status": "ok", "worker_id": "imac-64gb-worker-1"}
```

### Step 6 — Install HARPA Chrome Extension

1. Open Chrome on this iMac
2. Go to Chrome Web Store → search "HARPA AI"
3. Install the extension
4. Click extension icon → sign in with your HARPA account
5. Configure HARPA to use the local worker:
   - Open HARPA settings
   - Set API endpoint to `http://localhost:3000`
   - Enable automation mode

### Phase 2 Complete ✅

Checkpoint: Ollama running with models loaded, HARPA worker running, Chrome extension installed.

---

## 6. Phase 3 — 8GB iMac (HARPA Browser Only)

**Goal:** 8GB iMac running HARPA browser automation only (no Ollama — not enough RAM).

**Estimated time:** 20–30 minutes

### Step 1 — Install Docker Desktop

Same process as other machines.

### Step 2 — Deploy HARPA Worker

```bash
cd ~/AI-Server/harpa
cat > .env << 'EOF'
# HARPA Worker Configuration — 8GB iMac
HARPA_PORT=3000
HARPA_WORKER_ID=imac-8gb-worker-2

# OpenClaw orchestrator (Mac Mini)
ORCHESTRATOR_URL=http://192.168.1.10:8080

# Chrome/Browser settings
CHROME_HEADLESS=true
CHROME_TIMEOUT=30

# D-Tools Cloud credentials
DTOOLS_API_URL=https://api.d-toolscloud.com
DTOOLS_USERNAME=your_username_here
DTOOLS_PASSWORD=your_password_here
EOF

nano .env
docker compose up -d
curl http://localhost:3000/health
# Expected: {"status": "ok", "worker_id": "imac-8gb-worker-2"}
```

### Step 3 — Install HARPA Chrome Extension

Same as Phase 2, Step 6. Set worker API endpoint to `http://localhost:3000`.

### Step 4 — Register with OpenClaw

From this iMac, register as a worker:
```bash
curl -X POST http://192.168.1.10:8080/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "imac-8gb-worker-2",
    "worker_type": "harpa",
    "endpoint": "http://192.168.1.30:3000",
    "capabilities": ["browser_automation", "d_tools_cloud"]
  }'
```

### Phase 3 Complete ✅

Checkpoint: 8GB iMac running HARPA, registered as worker-2 with OpenClaw.

---

## 7. Phase 4 — Connect Everything

**Goal:** All workers registered with OpenClaw, full pipeline test passing.

### Step 1 — Register Workers with OpenClaw

From **Mac Mini**, register both workers (or they self-register on startup):

```bash
# Register 64GB iMac as Ollama worker
curl -X POST http://localhost:8080/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "imac-64gb-ollama",
    "worker_type": "ollama",
    "endpoint": "http://192.168.1.20:11434",
    "capabilities": ["llm_inference", "llama3", "codellama", "phi3"]
  }'

# Register 64GB iMac as HARPA worker
curl -X POST http://localhost:8080/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "imac-64gb-harpa",
    "worker_type": "harpa",
    "endpoint": "http://192.168.1.20:3000",
    "capabilities": ["browser_automation", "d_tools_cloud"]
  }'

# Register 8GB iMac as HARPA worker
curl -X POST http://localhost:8080/workers/register \
  -H "Content-Type: application/json" \
  -d '{
    "worker_id": "imac-8gb-harpa",
    "worker_type": "harpa",
    "endpoint": "http://192.168.1.30:3000",
    "capabilities": ["browser_automation", "d_tools_cloud"]
  }'
```

### Step 2 — Verify All Workers Registered

```bash
curl http://localhost:8080/workers
```

Expected output:
```json
{
  "workers": [
    {"id": "imac-64gb-ollama", "type": "ollama", "status": "online"},
    {"id": "imac-64gb-harpa", "type": "harpa", "status": "online"},
    {"id": "imac-8gb-harpa", "type": "harpa", "status": "online"}
  ]
}
```

### Step 3 — Run Full Pipeline Test

```bash
# Submit a test job
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "test",
    "payload": {"message": "hello world"},
    "priority": "low"
  }'

# Check job status (use job_id from response)
curl http://localhost:8080/jobs/JOB_ID
```

### Step 4 — Test D-Tools Cloud Integration

```bash
# Test D-Tools authentication
curl -X POST http://localhost:8080/dtools/auth-test
# Expected: {"authenticated": true, "user": "your_username"}

# List recent D-Tools projects
curl http://localhost:8080/dtools/projects?limit=5
```

### Phase 4 Complete ✅

Checkpoint: All workers online, test job processed, D-Tools auth confirmed.

---

## 8. Verification & Smoke Tests

Run these from Mac Mini after completing all phases.

### Full System Health Check

```bash
cd ~/AI-Server
bash scripts/health_check.sh
# OR manually:

echo "=== OpenClaw ==="
curl -s http://localhost:8080/health | python3 -m json.tool

echo "=== Workers ==="
curl -s http://localhost:8080/workers | python3 -m json.tool

echo "=== Ollama (via OpenClaw) ==="
curl -s http://localhost:8080/ollama/health | python3 -m json.tool

echo "=== HARPA Worker 1 ==="
curl -s http://192.168.1.20:3000/health | python3 -m json.tool

echo "=== HARPA Worker 2 ==="
curl -s http://192.168.1.30:3000/health | python3 -m json.tool
```

### Quick Smoke Tests

```bash
# 1. LLM inference test
curl -X POST http://localhost:8080/infer \
  -H "Content-Type: application/json" \
  -d '{"model": "phi3:mini", "prompt": "Say hello in 5 words."}'

# 2. Browser automation test
curl -X POST http://localhost:8080/automate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "action": "get_title"}'

# 3. Redis connectivity test
docker exec openclaw-redis-1 redis-cli ping
# Expected: PONG
```

### All Tests Pass ✅

Your Symphony Smart Homes AI server is fully operational.

---

## 9. Ongoing Maintenance

### Daily
- Check OpenClaw health: `curl http://localhost:8080/health`
- Review logs for errors: `docker compose logs --since=24h | grep ERROR`

### Weekly
- Update Ollama models: `ollama pull llama3:8b` (gets latest version)
- Check disk usage: `df -h` and `docker system df`
- Review job queue: `curl http://localhost:8080/jobs/stats`

### Monthly
- Pull latest repo changes: `git pull origin main`
- Rebuild Docker images: `docker compose build --no-cache && docker compose up -d`
- Review and rotate API credentials
- Check for Docker Desktop updates

### Updating the System

```bash
# On all machines:
cd ~/AI-Server
git pull origin main

# On Mac Mini:
cd openclaw
docker compose pull
docker compose up -d

# On 64GB iMac:
ollama pull llama3:8b  # update models
cd ~/AI-Server/harpa
docker compose pull
docker compose up -d

# On 8GB iMac:
cd ~/AI-Server/harpa
docker compose pull
docker compose up -d
```

### Backup

```bash
# Backup .env files (NEVER commit these to git)
cp ~/AI-Server/openclaw/.env ~/Desktop/openclaw.env.backup
cp ~/AI-Server/harpa/.env ~/Desktop/harpa.env.backup
```

---

## 10. Troubleshooting Quick Reference

### OpenClaw won't start
```bash
docker compose logs app
# Common fixes:
# - Port 8080 in use: lsof -i :8080 → kill PID
# - Redis not starting: docker compose restart redis
# - .env missing: check .env file exists with required vars
```

### Ollama not responding from network
```bash
# On 64GB iMac:
curl http://localhost:11434/api/tags  # works locally?
# If yes but not from network:
# - Check ~/.ollama/config.json has host: 0.0.0.0
# - Check macOS firewall: System Settings → Network → Firewall
# - Check that port 11434 is allowed
```

### HARPA worker not processing jobs
```bash
docker compose logs harpa-worker
# Common fixes:
# - Can't reach OpenClaw: check ORCHESTRATOR_URL in .env
# - Chrome crashed: docker compose restart
# - HARPA extension disconnected: reload extension in Chrome
```

### D-Tools authentication failing
```bash
curl -X POST http://localhost:8080/dtools/auth-test
# If 401: check DTOOLS_USERNAME and DTOOLS_PASSWORD in .env
# If 502: check DTOOLS_API_URL is correct
# If timeout: check internet connectivity on Mac Mini
```

### Jobs stuck in queue
```bash
curl http://localhost:8080/jobs/stats
# Check: are workers online? curl http://localhost:8080/workers
# If workers offline: restart worker services on each machine
# Force-clear stuck jobs: curl -X POST http://localhost:8080/jobs/clear-stuck
```

### General Docker Issues
```bash
# Restart everything
docker compose down && docker compose up -d

# Check resource usage
docker stats --no-stream

# Clean up unused images/containers
docker system prune -f

# View all container statuses
docker ps --format "table {{.Names}}\t{{.Status}}"
```

> Replace `IMAC_IP` with the real 64GB iMac IP before running.

---

*Last updated: February 26, 2026*  
*Repo: https://github.com/mearley24/AI-Server*
