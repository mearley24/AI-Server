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
4. [Phase 1 — Mac Mini M4 (Bob HQ) — OpenClaw Gateway](#4-phase-1--mac-mini-m4-bob-hq--openclaw-gateway)
5. [Phase 2 — 64GB iMac — Ollama Worker + HARPA Node](#5-phase-2--64gb-imac--ollama-worker--harpa-node)
6. [Phase 3 — 8GB iMac — HARPA Browser Node](#6-phase-3--8gb-imac--harpa-browser-node)
7. [Phase 4 — Connect Everything](#7-phase-4--connect-everything)
8. [Phase 5 — Home Assistant Integration](#8-phase-5--home-assistant-integration)
9. [Phase 6 — Telegram Bot Setup](#9-phase-6--telegram-bot-setup)
10. [Phase 7 — ClawWork Side Hustle](#10-phase-7--clawwork-side-hustle)
11. [Phase 8 — Client AI Deployment (Future)](#11-phase-8--client-ai-deployment-future)
12. [File Map](#12-file-map)
13. [Quick Reference Commands](#13-quick-reference-commands)
14. [Troubleshooting](#14-troubleshooting)
15. [Security Notes](#15-security-notes)

---

## 1. Infrastructure Overview

| Machine | Hostname | Specs | Role |
|---------|----------|-------|------|
| Mac Mini M4 | **Bob** | Apple Silicon M4, Docker | HQ — OpenClaw gateway, primary AI, Telegram interface, all orchestration |
| iMac 64GB | *(local IP needed)* | Intel i3 2019, 64GB RAM, macOS 15.7.4 | Ollama LLM worker + HARPA browser node |
| iMac 8GB | *(local IP needed)* | Intel, 8GB RAM | HARPA browser node only |

**Key principle:** Bob is the brain. The iMacs are workers. Bob decides what to do; the iMacs do the heavy lifting (LLM inference, browser automation).

---

## 2. How Everything Connects

```
You (Telegram)
      │
      ▼
┌─────────────┐     routes requests     ┌──────────────────────┐
│  Bob (M4)   │ ──────────────────────► │  64GB iMac           │
│  OpenClaw   │     http://IMAC_IP:11434 │  Ollama (LLM worker) │
│  Gateway    │                         └──────────────────────┘
│             │     HARPA Grid API      ┌──────────────────────┐
│             │ ──────────────────────► │  64GB iMac           │
│             │                         │  HARPA + D-Tools     │
│             │                         └──────────────────────┘
│             │     HARPA Grid API      ┌──────────────────────┐
│             │ ──────────────────────► │  8GB iMac            │
└─────────────┘                         │  HARPA + D-Tools     │
                                        └──────────────────────┘
```

**Data flow example — "Create a test project":**
1. You send the message to your Telegram bot
2. OpenClaw on Bob receives it, routes to the orchestrator
3. Bob uses Claude (Anthropic API) for reasoning
4. Bob optionally offloads summarization/classification to Ollama on the 64GB iMac
5. HARPA on the 64GB or 8GB iMac executes the D-Tools Cloud browser command
6. Bob reports back to you via Telegram

---

## 3. Pre-Flight Checklist

Before starting, collect these items. You'll need them during setup.

### API Keys (have these ready)

| Key | Where to get it | Used in |
|-----|----------------|---------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | OpenClaw on Bob |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | Optional, for OpenClaw |
| `TELEGRAM_BOT_TOKEN` | [@BotFather on Telegram](https://t.me/BotFather) | OpenClaw on Bob |
| `TELEGRAM_USER_ID` | [@userinfobot on Telegram](https://t.me/userinfobot) | OpenClaw on Bob |
| HARPA Grid API Key | HARPA extension settings (after installing) | Bob's bridge config |

### Software Pre-Requisites

| Machine | Pre-requisite | Check |
|---------|--------------|-------|
| Bob (M4) | Node.js 18+ | `node --version` |
| Bob (M4) | Git | `git --version` |
| Bob (M4) | Docker Desktop running | `docker ps` |
| 64GB iMac | Git | `git --version` |
| 64GB iMac | Chrome browser | Needed for HARPA |
| 8GB iMac | Git | `git --version` |
| 8GB iMac | Chrome browser | Needed for HARPA |

**Install Node.js 18+ on Bob if needed:**
```bash
# Using Homebrew
brew install node@18
brew link node@18 --force
node --version  # should print v18.x.x or higher
```

### Find Your iMac IP Addresses Now

On each iMac, run:
```bash
ipconfig getifaddr en0
```
Write these down — you'll use them multiple times:
- 64GB iMac IP: `___________________`
- 8GB iMac IP: `___________________`

---

## 4. Phase 1 — Mac Mini M4 (Bob HQ) — OpenClaw Gateway

**All commands below run on Bob (Mac Mini M4) unless noted.**

### Step 1.1 — Get the Latest Code

```bash
# If you've never cloned this repo on Bob:
cd ~
git clone https://github.com/mearley24/AI-Server.git

# If the repo is already there:
cd ~/AI-Server && git pull
```

Verify you're on main and everything is up to date:
```bash
git log --oneline -5
```

### Step 1.2 — Install OpenClaw

```bash
cd ~/AI-Server
chmod +x setup/openclaw/install_openclaw.sh
./setup/openclaw/install_openclaw.sh
```

This script installs OpenClaw globally and creates the `~/.openclaw/` config directory. After it finishes, verify the installation:

```bash
openclaw --version
```

If the command isn't found, you may need to reload your shell:
```bash
source ~/.zshrc   # or ~/.bash_profile if you're using bash
openclaw --version
```

### Step 1.3 — Set Up Your Telegram Bot

Follow the instructions in `setup/openclaw/setup_telegram_bot.md`. The short version:

1. Open Telegram and message `@BotFather`
2. Send `/newbot`
3. Give your bot a name (e.g., "Bob Symphony") and a username (e.g., `BobSymphony_bot`)
4. BotFather returns your **bot token** — copy it now
5. Message `@userinfobot` on Telegram to get **your user ID**

### Step 1.4 — Configure OpenClaw

Open the config file:
```bash
nano ~/.openclaw/openclaw.json
```

Fill in all the required fields. The file structure looks like this:

```json
{
  "channels": {
    "telegram": {
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowedUsers": ["YOUR_TELEGRAM_USER_ID"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "YOUR_ANTHROPIC_API_KEY"
    },
    "openai": {
      "apiKey": "YOUR_OPENAI_API_KEY"
    },
    "ollama": {
      "url": "http://PLACEHOLDER_IMAC_IP:11434"
    }
  }
}
```

> **Note:** You're setting the Ollama URL to a placeholder now. You'll update it with the real 64GB iMac IP in Phase 4, Step 4.1. Leave it as a placeholder until then.

Save with `Ctrl+O`, exit with `Ctrl+X`.

### Step 1.5 — Copy SOUL.md and AGENTS.md

These files define Bob's personality and routing rules:

```bash
# Create the workspace directory if it doesn't exist
mkdir -p ~/.openclaw/workspace-bob/

# Copy the files from the repo
cp ~/AI-Server/setup/openclaw/SOUL.md ~/.openclaw/workspace-bob/
cp ~/AI-Server/setup/openclaw/AGENTS.md ~/.openclaw/workspace-bob/
```

Verify they're there:
```bash
ls ~/.openclaw/workspace-bob/
# Should show: SOUL.md  AGENTS.md
```

### Step 1.6 — Start OpenClaw

```bash
openclaw gateway
```

You should see output like:
```
OpenClaw Gateway starting...
Telegram channel: connected
Listening for messages...
```

> **Leave this terminal open**, or run it in a background process. See the Quick Reference section for how to run it as a background service.

### Step 1.7 — Test Telegram

Open Telegram on your phone or desktop and send a message to your bot. Something simple like:
```
Hello Bob
```

Bob should respond within a few seconds. If he does, Phase 1 is complete.

**If there's no response:** See [Troubleshooting — Telegram bot not responding](#telegram-bot-not-responding).

### Step 1.8 — (Optional) Stop the Old Telegram Container

If you had the previous `telegram-interface` Docker container running, you can stop it now — OpenClaw replaces it.

```bash
docker ps                        # find the container ID
docker stop <container_id>
docker rm <container_id>         # optional, removes it entirely
```

> See `setup/openclaw/migration_plan.md` for details on what the old container did and what OpenClaw now handles.

---

## 5. Phase 2 — 64GB iMac — Ollama Worker + HARPA Node

**All commands below run on the 64GB iMac unless noted.**

### Step 2.1 — Get the Code

```bash
# If you've never cloned the repo on this machine:
cd ~
git clone https://github.com/mearley24/AI-Server.git

# If the repo is already there:
cd ~/AI-Server && git pull
```

### Step 2.2 — Run the Ollama Worker Setup Script

```bash
cd ~/AI-Server
chmod +x setup/ollama_worker/setup_ollama_worker.sh
./setup/ollama_worker/setup_ollama_worker.sh
```

This script:
- Installs Ollama if not already installed
- Configures Ollama to listen on `0.0.0.0:11434` (accessible from Bob)
- Installs the required models (from the included Modelfiles)
- Sets up a launchctl service so Ollama starts automatically on login

**This step takes a while** — the models need to download. Expected sizes:
- `bob-classifier` (based on llama3) — ~4GB
- `bob-summarizer` (based on mistral) — ~4GB

Watch the progress in the terminal. Don't close it until it prints "Setup complete."

### Step 2.3 — Verify Ollama Works

```bash
chmod +x setup/ollama_worker/test_ollama_worker.sh
./setup/ollama_worker/test_ollama_worker.sh
```

This script runs a test prompt through each model and confirms the API is reachable. Expected output:
```
Testing bob-classifier... OK
Testing bob-summarizer... OK
Ollama API accessible at: http://0.0.0.0:11434
Local IP: 192.168.x.x
```

**Write down the local IP printed by the script:**  
`64GB iMac IP: ___________________`

### Step 2.4 — Set Up HARPA on This Machine

```bash
chmod +x setup/harpa/setup_imac_harpa.sh
./setup/harpa/setup_imac_harpa.sh
```

This script sets up the HARPA bridge service (a Python background process that listens for commands from Bob and executes them via HARPA's browser automation).

### Step 2.5 — Install HARPA Extension and Log In to D-Tools Cloud

1. Open Chrome on this iMac
2. Go to [harpa.ai](https://harpa.ai) and install the HARPA Chrome extension
3. In Chrome, navigate to [D-Tools Cloud](https://cloud.d-tools.com) and log in with your account credentials
4. Open the HARPA extension, go to **Settings → Grid**
5. Note your **HARPA Grid API Key** — you'll need this in Phase 4

> **Important:** D-Tools Cloud must remain logged in in Chrome for HARPA commands to work. If Chrome quits or the session expires, you'll need to log in again.

---

## 6. Phase 3 — 8GB iMac — HARPA Browser Node

**All commands below run on the 8GB iMac.**

This machine is a browser-only worker. It doesn't run Ollama — it only runs the HARPA extension to give Bob additional browser automation capacity.

### Step 3.1 — Get the Code

```bash
cd ~
git clone https://github.com/mearley24/AI-Server.git
# or if already cloned:
cd ~/AI-Server && git pull
```

### Step 3.2 — Run the Browser Node Setup Script

```bash
cd ~/AI-Server
chmod +x setup/harpa/setup_imac_browser_only.sh
./setup/harpa/setup_imac_browser_only.sh
```

This is a lighter version of the HARPA setup — it configures the bridge service but skips Ollama.

### Step 3.3 — Install HARPA Extension and Log In

1. Open Chrome on this iMac
2. Install the HARPA extension from [harpa.ai](https://harpa.ai)
3. Navigate to [D-Tools Cloud](https://cloud.d-tools.com) and log in
4. Open HARPA extension → **Settings → Grid**
5. Note the **HARPA Grid API Key** and this machine's **Grid Node ID**

**Write these down:**  
- 8GB iMac HARPA Grid API Key: `___________________`  
- 8GB iMac Grid Node ID: `___________________`

---

## 7. Phase 4 — Connect Everything

**Commands run on Bob (Mac Mini M4) unless noted.**

### Step 4.1 — Update the Ollama Endpoint in OpenClaw Config

Now that you have the 64GB iMac's real IP address, update the config:

```bash
nano ~/.openclaw/openclaw.json
```

Find the ollama section and replace the placeholder:
```json
"ollama": {
  "url": "http://192.168.x.x:11434"
}
```

Save and exit.

### Step 4.2 — Verify Bob Can Reach Ollama

```bash
curl http://192.168.x.x:11434/api/tags
```

Replace `192.168.x.x` with the actual 64GB iMac IP. Expected output: a JSON object listing installed models. If you get a connection error, see [Troubleshooting — Ollama worker unreachable](#ollama-worker-unreachable).

### Step 4.3 — Update the HARPA Bridge Config

```bash
nano ~/AI-Server/setup/harpa/imac_node_config.md
```

Fill in:
- Grid API keys from both iMacs
- Node IDs for each machine
- The 64GB iMac IP (for direct connections)

Then restart the HARPA bridge service on both iMacs:

```bash
# On each iMac:
launchctl stop com.symphonysmarthomes.harpa
launchctl start com.symphonysmarthomes.harpa
```

### Step 4.4 — Restart OpenClaw to Pick Up Config Changes

If OpenClaw is already running, restart it:

```bash
# Stop the current instance (Ctrl+C in its terminal, or find the process)
pkill -f "openclaw gateway"

# Start fresh
openclaw gateway
```

### Step 4.5 — Run a Full End-to-End Test

Send this message to your Telegram bot:
```
Create a test project called "Deployment Test" in D-Tools Cloud
```

Watch what happens:
1. Bob should acknowledge the request
2. Bob should route the command to HARPA on one of the iMacs
3. HARPA should execute the browser action in D-Tools Cloud
4. Bob should report back with confirmation

If this works, **the entire system is operational.**

---

## 8. File Map

This is what the full repo looks like after all setup files are added:

```
~/AI-Server/                                   ← cloned on all 3 machines
│
├── setup/
│   ├── openclaw/                              ← Mac Mini M4 (Bob) only
│   │   ├── install_openclaw.sh               ← installs OpenClaw + deps
│   │   ├── openclaw.json                     ← config template (copy to ~/.openclaw/)
│   │   ├── SOUL.md                           ← Bob's personality/identity
│   │   ├── AGENTS.md                         ← agent routing rules
│   │   ├── setup_telegram_bot.md             ← step-by-step Telegram setup
│   │   └── migration_plan.md                 ← how OpenClaw replaces telegram-interface
│   │
│   ├── ollama_worker/                         ← 64GB iMac only
│   │   ├── setup_ollama_worker.sh            ← installs Ollama, models, service
│   │   ├── ollama_worker.env                 ← environment vars (OLLAMA_HOST, etc.)
│   │   ├── test_ollama_worker.sh             ← verifies models + API are working
│   │   ├── Modelfile.bob-classifier          ← classifier model definition
│   │   ├── Modelfile.bob-summarizer          ← summarizer model definition
│   │   └── README.md
│   │
│   └── harpa/                                 ← both iMacs
│       ├── setup_imac_harpa.sh               ← full setup (64GB iMac)
│       ├── setup_imac_browser_only.sh        ← browser-only setup (8GB iMac)
│       ├── harpa_dtools_commands.json        ← D-Tools command library for HARPA
│       ├── bob_harpa_bridge.py               ← Python bridge: OpenClaw ↔ HARPA Grid
│       ├── imac_node_config.md               ← fill in API keys + node IDs here
│       └── README.md
│
├── knowledge/
│   ├── standards/
│   │   └── bob_system_prompt.md              ← ALREADY PUSHED — Bob's core instructions
│   └── proposal_library/                     ← ALREADY PUSHED — 22 proposal templates
│
├── orchestrator/
│   └── core/
│       └── bob_orchestrator.py               ← existing orchestration logic
│
├── telegram-interface/                        ← existing — being replaced by OpenClaw
│   └── (Docker-based Telegram bot)
│
├── tools/                                     ← existing Python + Shell tools
│   ├── bob_build_inventory.py
│   ├── bob_build_room_packages.py
│   ├── bob_fetch_manuals.py
│   ├── bob_ingest_new.sh
│   ├── bob_project_analyzer.py
│   ├── bob_proposal_to_dtools.py
│   ├── bob_regen_signals.py
│   ├── bob_room_mapper.py
│   ├── bob_scan_library.sh
│   ├── bob_scan_raw_projects.sh
│   ├── bob_sort_inbox.sh
│   └── (+ runner .command files)
│
├── remediator/                                ← existing Docker watchdog
│   ├── Dockerfile
│   ├── index.js
│   └── package.json
│
├── .gitignore                                 ← secrets excluded
└── RUN_BOB.command                            ← existing launcher
```

### What Lives Where (Local, Not in Git)

| Path | Machine | Purpose |
|------|---------|---------|
| `~/.openclaw/openclaw.json` | Bob | Live config with API keys (never committed) |
| `~/.openclaw/workspace-bob/SOUL.md` | Bob | Bob's active identity file |
| `~/.openclaw/workspace-bob/AGENTS.md` | Bob | Bob's active agent routing |
| `/Library/LaunchAgents/com.ollama.plist` | 64GB iMac | Ollama autostart service |
| `/Library/LaunchAgents/com.symphonysmarthomes.harpa.plist` | Both iMacs | HARPA bridge autostart |

---

## 9. Quick Reference Commands

### Bob — Mac Mini M4

```bash
# OpenClaw
openclaw gateway                      # Start the gateway
openclaw doctor                       # Diagnose connection/config issues
openclaw agents list --bindings       # Show how messages route to agents
openclaw channels status --probe      # Check Telegram + other channel health

# Check if OpenClaw is already running
ps aux | grep "openclaw gateway"

# Docker (existing services)
docker ps                             # List running containers
docker logs <container_id>            # View container logs
```

### 64GB iMac — Ollama Worker

```bash
# Ollama
ollama list                           # Show all installed models
ollama ps                             # Show models currently loaded in memory
ollama run bob-classifier             # Interactive test of the classifier model
ollama run bob-summarizer             # Interactive test of the summarizer model

# API check
curl localhost:11434/api/tags         # Confirm API is responding
curl localhost:11434/api/tags | python3 -m json.tool  # Pretty-print the output

# Service management
launchctl list | grep ollama          # Check if Ollama service is running
launchctl stop com.ollama             # Stop Ollama service
launchctl start com.ollama            # Start Ollama service
```

### Both iMacs — HARPA Service

```bash
# Service management
launchctl list | grep symphonysmarthomes          # Check if HARPA bridge is running
launchctl stop com.symphonysmarthomes.harpa       # Stop HARPA bridge
launchctl start com.symphonysmarthomes.harpa      # Start HARPA bridge

# View logs
tail -f /tmp/harpa_bridge.log                     # Live log output
```

### All Machines — Git

```bash
cd ~/AI-Server
git pull                              # Get latest changes
git status                            # See what's changed locally
git log --oneline -10                 # Recent commit history
```

---

## 10. Troubleshooting

### OpenClaw won't start

**Symptom:** `openclaw gateway` exits immediately or prints an error.

**Check Node.js version:**
```bash
node --version
```
Must be 18.0 or higher. If it's lower, upgrade:
```bash
brew upgrade node
```

**Check the config file:**
```bash
openclaw doctor
```
This command validates your `openclaw.json` and reports missing or malformed fields.

**Check for a syntax error in the config:**
```bash
cat ~/.openclaw/openclaw.json | python3 -m json.tool
```
If this prints "No JSON object could be decoded", find and fix the syntax error (common issue: trailing commas).

---

### Telegram bot not responding

**Symptom:** You send a message to your bot and nothing comes back.

1. **Verify the bot token is correct:**  
   Log into Telegram, message `@BotFather`, send `/mybots`, select your bot, and confirm the token matches what's in `openclaw.json`.

2. **Verify your user ID is allowed:**  
   In `openclaw.json`, the `allowedUsers` list must contain your numeric Telegram user ID (not your username). Get it from `@userinfobot`.

3. **Check if OpenClaw is actually running:**  
   ```bash
   ps aux | grep "openclaw gateway"
   ```

4. **Run diagnostics:**  
   ```bash
   openclaw doctor
   ```

5. **Check for error output:**  
   Run `openclaw gateway` in a terminal and watch for error messages as you send a test message.

---

### Ollama worker unreachable

**Symptom:** `curl http://IMAC_IP:11434/api/tags` fails or times out from Bob.

**Confirm Ollama is listening on all interfaces (not just localhost):**
```bash
# On the 64GB iMac:
curl localhost:11434/api/tags        # This should work
```
If localhost works but Bob can't reach it, Ollama is bound to 127.0.0.1 only.

**Fix — set OLLAMA_HOST environment variable:**
```bash
# On the 64GB iMac, edit the launchctl plist or .env file:
nano ~/AI-Server/setup/ollama_worker/ollama_worker.env
# Make sure this line exists:
# OLLAMA_HOST=0.0.0.0

# Then restart the service:
launchctl stop com.ollama
launchctl start com.ollama
```

**Check macOS firewall:**
- Go to System Settings → Network → Firewall
- Make sure it's not blocking incoming connections on port 11434
- Or add an exception for Ollama

**Check that both machines are on the same network segment** — some routers use AP isolation that prevents machine-to-machine communication on Wi-Fi.

---

### HARPA commands failing

**Symptom:** Bob routes a command to HARPA but nothing happens in D-Tools Cloud.

1. **Check that Chrome is open** on the iMac — HARPA only runs when Chrome is active.

2. **Check that D-Tools Cloud session is active:**  
   Open Chrome on the affected iMac, navigate to `cloud.d-tools.com`. If it redirects to a login page, re-authenticate.

3. **Check the HARPA bridge service:**
   ```bash
   launchctl list | grep symphonysmarthomes
   tail -20 /tmp/harpa_bridge.log
   ```

4. **Verify the Grid API key** in `imac_node_config.md` matches what's shown in HARPA's Settings → Grid panel.

5. **Restart HARPA:**  
   Disable and re-enable the HARPA extension in Chrome's extension manager (`chrome://extensions`).

---

### Models loading slowly

**Symptom:** First request to Ollama takes 30–60+ seconds.

This is normal. The first request loads the model weights from disk into RAM. Subsequent requests are fast. The 64GB iMac is specifically chosen because it has enough RAM to hold multiple models simultaneously.

If you need models to stay loaded:
```bash
# On the 64GB iMac — keep models warm by pinging them
watch -n 60 "curl -s -X POST localhost:11434/api/generate \
  -d '{\"model\": \"bob-classifier\", \"prompt\": \"ping\", \"stream\": false}' \
  > /dev/null"
```

---

### "SOUL.md not found" or "AGENTS.md not found"

**Symptom:** OpenClaw starts but Bob has no personality or agents don't route correctly.

```bash
ls ~/.openclaw/workspace-bob/
```

If those files are missing, re-copy them:
```bash
cp ~/AI-Server/setup/openclaw/SOUL.md ~/.openclaw/workspace-bob/
cp ~/AI-Server/setup/openclaw/AGENTS.md ~/.openclaw/workspace-bob/
openclaw gateway    # restart
```

---

## 11. Security Notes

**Never commit API keys to the repo.**  
The `.gitignore` already excludes `~/.openclaw/openclaw.json` and `.env` files, but check before every `git add`:
```bash
git diff --staged   # review what you're about to commit
```

**Ollama is LAN-accessible.**  
Port 11434 is open on the 64GB iMac to allow Bob to reach it. This is by design but means anyone on your local network can send inference requests to your models. Keep your home/office network secured with a strong Wi-Fi password and avoid doing this on public or shared networks.

**Telegram is your only external entry point.**  
OpenClaw's `allowedUsers` list is the gatekeep. Only your Telegram user ID is allowed. Do not add others unless you trust them with full system access.

**HARPA Grid API key = full browser automation access.**  
Store it in environment variables or in `imac_node_config.md` (which is gitignored), never hardcode it in Python scripts that get committed.

**Rotate API keys if you ever push secrets accidentally:**  
- Anthropic: [console.anthropic.com/settings/api-keys](https://console.anthropic.com/settings/api-keys)
- OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- Telegram: Message `@BotFather → /mybots → Revoke token`

---

---

## 8. Phase 5 — Home Assistant Integration

**All commands below run on Bob (Mac Mini M4) unless noted.**

This phase connects your Raspberry Pi running Home Assistant to the Symphony AI stack. Bob gains awareness of all connected devices, camera feeds, and MQTT events.

### Step 5.1 — Generate a Home Assistant Long-Lived Access Token

1. On your Raspberry Pi, open a browser and go to `http://PI_IP:8123/profile`
2. Scroll to **Long-Lived Access Tokens** at the bottom of the page
3. Click **Create Token**, give it a name (e.g., `bob-symphony`), and copy the token — **it's only shown once**

Replace `PI_IP` with your Raspberry Pi's local IP address.

### Step 5.2 — Configure Environment Variables

```bash
cd ~/AI-Server/integrations/homeassistant
cp .env.example .env
nano .env
```

Fill in at minimum:

```env
HA_URL=http://PI_IP:8123
HA_TOKEN=your_long_lived_token_here
MQTT_HOST=PI_IP
MQTT_PORT=1883
```

Save with `Ctrl+O`, exit with `Ctrl+X`.

### Step 5.3 — Run the Setup Script

```bash
bash ~/AI-Server/integrations/homeassistant/setup_ha_integration.sh
```

This script:
- Installs the Python Home Assistant client library
- Configures the MQTT bridge
- Registers Bob as an authorized device in Home Assistant

### Step 5.4 — Start the Integration Services

```bash
cd ~/AI-Server/integrations/homeassistant
docker-compose -f docker-compose.ha.yml up -d
```

Verify the containers are running:
```bash
docker ps | grep homeassistant
```

### Step 5.5 — Test MQTT Connectivity

From Bob, publish a test message to the Mosquitto broker on the Pi:

```bash
mosquitto_pub -h PI_IP -t symphony/test -m "hello from bob"
```

If the Pi's Mosquitto broker receives it, you'll see the message echo in the HA logs. If `mosquitto_pub` isn't installed on Bob:

```bash
brew install mosquitto
```

> **What this unlocks:** Bob can now query device states, trigger automations, subscribe to sensor events, and receive camera motion alerts — all via MQTT and the HA REST API.

---

## 9. Phase 6 — Telegram Bot Setup

**All commands below run on Bob (Mac Mini M4) unless noted.**

This phase deploys a dedicated Telegram bot — "Bob the Conductor" — for remote management with 13 slash commands, a daily digest, and priority alert escalation.

> **Note:** If you already configured a basic Telegram integration in Phase 1 via OpenClaw, this is a separate, more full-featured bot with its own Docker service and command set.

### Step 6.1 — Create the Bot via BotFather

1. Open Telegram on any device
2. Search for `@BotFather` and start a chat
3. Send `/newbot`
4. When prompted for a name, enter: `Bob the Conductor`
5. When prompted for a username, enter something unique like `BobConductor_bot` or `SymphonyBob_bot`
6. BotFather returns your **bot token** — copy it immediately

### Step 6.2 — Get Your Chat ID

First send any message to your new bot, then:

```bash
curl https://api.telegram.org/bot<TOKEN>/getUpdates
```

Replace `<TOKEN>` with your actual bot token. Look for `"id"` inside the `"chat"` object in the JSON response — that's your Chat ID.

### Step 6.3 — Configure Environment Variables

```bash
cd ~/AI-Server/integrations/telegram
cp .env.example .env
nano .env
```

Fill in:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
ALERT_LEVEL=priority          # options: all, priority, critical
DIGEST_TIME=08:00             # daily digest delivery time (24h, local timezone)
```

### Step 6.4 — Start the Bot

```bash
cd ~/AI-Server/integrations/telegram
docker-compose -f docker-compose.telegram.yml up -d
```

Confirm the container is running:
```bash
docker logs -f --tail 20 telegram_bot
```

You should see `Bot started. Listening for commands...` in the logs.

### Step 6.5 — Test the Bot

Open Telegram and send your bot:
```
/status
```

Bob should respond with a current system status summary. If there's no response within 10 seconds, check the container logs.

**Available commands (13 total):**

| Command | Action |
|---------|--------|
| `/status` | System-wide health check |
| `/logs` | Recent error/warning logs |
| `/restart <service>` | Restart a named Docker service |
| `/clawwork` | ClawWork earnings summary |
| `/ha <command>` | Send a Home Assistant command |
| `/ollama` | Ollama model status |
| `/nodes` | Node health overview |
| `/docker` | Docker container list |
| `/pull` | Git pull on all nodes |
| `/deploy <client>` | Trigger client AI deployment |
| `/earnings` | Daily ClawWork earnings report |
| `/digest` | Request an immediate digest |
| `/help` | List all commands |

---

## 10. Phase 7 — ClawWork Side Hustle

**All commands below run on Bob (Mac Mini M4) unless noted.**

This phase sets up the ClawWork 24/7 autonomous earnings system. ClawWork runs GDPVal tasks with adaptive sector selection, capped at 50 tasks per day to stay within platform limits.

### Step 7.1 — Install ClawWork

```bash
bash ~/AI-Server/clawwork/install_clawwork.sh
```

This script installs the ClawWork client, its Python dependencies, and configures the Docker service definition.

### Step 7.2 — Configure ClawWork

```bash
cd ~/AI-Server/clawwork
nano clawwork_config.json
```

Key configuration options:

```json
{
  "daily_task_limit": 50,
  "sector_mode": "adaptive",
  "preferred_sectors": ["gdpval", "data_annotation", "classification"],
  "min_task_value": 0.05,
  "run_hours": { "start": 0, "end": 23 },
  "earnings_alert_threshold": 10.00
}
```

Save and exit.

### Step 7.3 — Start the Daemon

```bash
cd ~/AI-Server/clawwork
docker-compose -f docker-compose.clawwork.yml up -d
```

The daemon runs continuously in the background, picking up tasks, completing them, and logging results.

### Step 7.4 — Check Status

```bash
python3 ~/AI-Server/clawwork/bob_side_hustle.py --status
```

Expected output:
```
ClawWork Status
───────────────
Daemon:    RUNNING
Tasks today: 0 / 50
Balance:   $0.00
Sector:    gdpval (adaptive)
```

### Step 7.5 — View Earnings Report

```bash
python3 ~/AI-Server/clawwork/earnings_tracker.py --report daily
```

For a weekly summary:
```bash
python3 ~/AI-Server/clawwork/earnings_tracker.py --report weekly
```

Earnings reports are also delivered automatically via Telegram at the time configured in Phase 6 (`DIGEST_TIME`).

> **Monitoring tip:** The Telegram bot's `/clawwork` command gives you an instant earnings snapshot from your phone without SSH access.

---

## 11. Phase 8 — Client AI Deployment (Future)

> **Status: Planned.** This phase is not yet implemented. The scaffolding exists in `client_ai/` but the full deployment pipeline is in development.

This phase covers deploying a personalized "Symphony Concierge AI" to each client's smart home system. Each deployment is a tailored knowledge package — trained on that client's system configuration, room layout, vendor equipment, and service preferences.

### Planned Architecture

```
Bob (orchestrator)
      │
      ├── Build knowledge package (client_knowledge_builder.py)
      ├── Provision client node (provision_client_node.sh)
      └── Push updates (update_pipeline.py)
                │
                ▼
        Client's local node
        (Raspberry Pi or Mac Mini at client site)
              │
              └── Personalized AI concierge
                  responds to voice/app commands
```

### Planned Commands

```bash
# Build a tailored knowledge package for a client
python3 client_ai/client_knowledge_builder.py --client CLIENT_ID

# Provision their on-site node
bash client_ai/provision_client_node.sh --hostname CLIENTNAME --bob-ip <BOB_IP>

# Push an update to an existing deployment
python3 client_ai/update_pipeline.py push --client CLIENT_ID
```

### What Each Client Deployment Includes

| Component | Description |
|-----------|-------------|
| System prompt | Client-specific personality + knowledge |
| Equipment database | All installed gear, model numbers, manuals |
| Room map | Room names, zones, and automation rules |
| Service contacts | Preferred vendors, support numbers |
| Escalation rules | When to call vs. when to self-resolve |

> **Timeline:** Target Q2 2026 for first client pilot deployment.

---

## 12. File Map

*Updated to include all new integrations.*

```
~/AI-Server/                                   ← cloned on all 3 machines
│
├── setup/
│   ├── openclaw/                              ← Mac Mini M4 (Bob) only
│   ├── ollama_worker/                         ← 64GB iMac only
│   └── harpa/                                 ← both iMacs
│
├── integrations/
│   ├── homeassistant/                         ← Phase 5 (NEW)
│   │   ├── setup_ha_integration.sh
│   │   ├── docker-compose.ha.yml
│   │   └── .env.example
│   └── telegram/                              ← Phase 6 (NEW)
│       ├── docker-compose.telegram.yml
│       └── .env.example
│
├── clawwork/                                  ← Phase 7 (NEW)
│   ├── install_clawwork.sh
│   ├── clawwork_config.json
│   ├── docker-compose.clawwork.yml
│   ├── bob_side_hustle.py
│   └── earnings_tracker.py
│
├── voice_receptionist/                        ← existing
│   ├── docker-compose.yml
│   └── app/
│
├── client_ai/                                 ← Phase 8 scaffolding
│   ├── client_knowledge_builder.py
│   ├── provision_client_node.sh
│   └── update_pipeline.py
│
├── knowledge/
├── orchestrator/
├── tools/
├── remediator/
├── .gitignore
└── RUN_BOB.command
```

---

## 13. Quick Reference Commands

*(Preserves original Phase 1–4 quick reference — see sections above for Phase 5–8 commands.)*

### Bob — Mac Mini M4

```bash
# OpenClaw
openclaw gateway
openclaw doctor
openclaw agents list --bindings
openclaw channels status --probe

# ClawWork
python3 ~/AI-Server/clawwork/bob_side_hustle.py --status
python3 ~/AI-Server/clawwork/earnings_tracker.py --report daily

# Home Assistant
curl -H "Authorization: Bearer $HA_TOKEN" http://PI_IP:8123/api/states

# Telegram Bot
docker logs -f --tail 50 telegram_bot
```

---

## 14. Troubleshooting

*(Original troubleshooting content preserved — see original sections above.)*

### MQTT broker unreachable

**Symptom:** `mosquitto_pub` times out or returns a connection refused error.

1. Verify Mosquitto is running on the Pi: `sudo systemctl status mosquitto`
2. Check the Pi's firewall: port 1883 must be open for LAN connections
3. Confirm `MQTT_HOST` in `.env` matches the Pi's actual IP
4. Test from the Pi itself: `mosquitto_pub -h localhost -t test -m "ping"`

### Telegram bot not responding

1. Verify the container is running: `docker ps | grep telegram`
2. Check logs: `docker logs telegram_bot --tail 30`
3. Confirm the bot token in `.env` matches the one from BotFather
4. Make sure you sent a message to the bot first (bots can't initiate contact)

### ClawWork daemon not picking up tasks

1. Check the daemon is running: `docker ps | grep clawwork`
2. View recent activity: `docker logs clawwork_daemon --tail 50`
3. Verify your ClawWork account credentials in `clawwork_config.json`
4. Check that you haven't hit the daily limit: `python3 ~/AI-Server/clawwork/bob_side_hustle.py --status`

---

## 15. Security Notes

*(Original security content preserved — additional notes below.)*

**Home Assistant token is sensitive.** Store it only in `.env` (which is gitignored). Never hardcode it in scripts.

**ClawWork credentials.** Keep account credentials in `clawwork_config.json` (gitignored). Rotate if you suspect exposure.

**Telegram bot token.** The bot token in `integrations/telegram/.env` grants full bot control. Treat it like a password. If exposed, revoke via BotFather: `/mybots → Revoke token`.

---

*Last updated: February 27, 2026*  
*Repo: https://github.com/mearley24/AI-Server*

## Appendix A — Running OpenClaw as a Background Service

If you want OpenClaw to start automatically at login on Bob (instead of manually running `openclaw gateway`):

```bash
# Create a launchctl plist
cat > ~/Library/LaunchAgents/com.symphonysmarthomes.openclaw.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.symphonysmarthomes.openclaw</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/openclaw</string>
    <string>gateway</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/openclaw.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/openclaw.error.log</string>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.symphonysmarthomes.openclaw.plist

# Verify it's running
launchctl list | grep openclaw
```

To view live logs:
```bash
tail -f /tmp/openclaw.log
```

---

## Appendix B — Checking System Health at a Glance

Run this on Bob to get a quick status of the entire stack:

```bash
echo "=== OpenClaw ===" && ps aux | grep "openclaw gateway" | grep -v grep | head -1 || echo "NOT RUNNING"
echo ""
echo "=== Ollama (64GB iMac) ===" && curl -s --max-time 3 http://IMAC_IP:11434/api/tags | python3 -c "import sys,json; data=json.load(sys.stdin); print(f'{len(data[\"models\"])} models loaded')" 2>/dev/null || echo "UNREACHABLE"
echo ""
echo "=== Docker Containers ===" && docker ps --format "table {{.Names}}\t{{.Status}}"
```

> Replace `IMAC_IP` with the real 64GB iMac IP before running.

---

*Last updated: February 26, 2026*  
*Repo: https://github.com/mearley24/AI-Server*
