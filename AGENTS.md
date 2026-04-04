# Agent Memory — Symphony AI Server

Persistent context for AI agents (Cursor, Bob, OpenClaw) working in this repo.

---

## North Star — 24/7 Machine Time

**Goal:** The team (Bob, Betty, Beatrice, Claude Code, Perplexity, etc.) operates continuously. When a question comes up, agents take the reins. Human input becomes optional — the system works together 24/7, indefinitely in machine time.

**What we're building toward:**
- **24/7 learner** — Faster they learn company + industry → faster they release agents for front-end work
- **Autonomous Q&A** — Claude Code + Perplexity handle questions; loop tightens, human optional
- Ideas emerge from the team during operation
- Betty scans Polymarket, learner builds knowledge, D-Tools proposals flow
- Human steps in only when needed (approvals, edge cases, direction)

**Roadmap:** `knowledge/agents/LEARNER_ROADMAP.md`

---

## Pre-Ultra Setup & Autonomous Runbook

**Before upgrading to Cursor Ultra**, prepare the system so agents run at full power:

1. **Read `knowledge/agents/ULTRA_RUNBOOK.md`** — Session start, handoff, model selection.
2. **Read `orchestrator/WORK_IN_PROGRESS.md`** — What's in progress? Continue it.
3. **Run continual-learning skill** — Mine `~/.cursor/.../agent-transcripts/` → update AGENTS.md with user preferences and workspace facts.
4. **Queue tasks** — `python3 orchestrator/task_board.py add "Task" --type research --priority high`
5. **Verify launchd** — `launchctl list | grep symphony` (SEO, X drip, learning, incoming tasks)

**Cursor rule**: `.cursor/rules/ultra-workflows.mdc` — When to use Ultra vs fast, session protocol, handoff.

---

## Bob 24/7 Always-On (No Interruptions)

Bob must run continuously. Run once to lock in power and system settings:

```bash
./setup/nodes/configure_bob_always_on.sh
```

**What it sets:** Never sleep when plugged in; display can sleep. Manual checks: Screen Time Off, no Focus schedules, Software Update manual only.

**Full runbook:** `setup/nodes/BOB_24_7_RUNBOOK.md`

---

## Bob Maintenance (Storage + Memory)

Weekly cleanup keeps Bob lean. Run manually or via launchd.

```bash
# Preview what would be cleaned
python3 tools/bob_maintenance.py --dry

# Execute cleanup
python3 tools/bob_maintenance.py --run

# Also clear inactive RAM (macOS)
python3 tools/bob_maintenance.py --run --purge-memory
```

**What it does:**
- Rotates/compresses logs >7 days
- Deletes Claude job logs >14 days
- Prunes .cache >30 days
- SQLite VACUUM (task_board, bob_brain, events)
- Reports top memory processes

**Scheduled (optional):** `com.symphony.bob-maintenance` — Sundays 3 AM.
```bash
cp setup/launchd/com.symphony.bob-maintenance.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.bob-maintenance.plist
```

---

## Overnight Schedule (10:55 PM / 5:55 AM)

Automatically wind down non-essential processes at 10:55 PM and restart them at 5:55 AM so Bob and team services keep running with more memory overnight.

**Winddown (10:55 PM):** Quit Cursor, quit Xcode, purge. (chrome-headless-shell left running for team automation.)

**Wakeup (5:55 AM):** Start Cursor, purge.

**Never touched:** mobile API, Bob/Telegram, voice webhook, remediator, openwebui.

```bash
# Manual run
python3 tools/overnight_schedule.py --winddown   # or --wakeup
python3 tools/overnight_schedule.py --winddown --dry   # preview

# Install launchd (runs daily)
cp setup/launchd/com.symphony.overnight-winddown.plist ~/Library/LaunchAgents/
cp setup/launchd/com.symphony.overnight-wakeup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.overnight-winddown.plist
launchctl load ~/Library/LaunchAgents/com.symphony.overnight-wakeup.plist
```

**Note:** Mac must be awake at those times. If asleep, jobs run at next occurrence. Consider Energy Saver → Prevent automatic sleeping when plugged in.

---

## iPad Voice Interface — Talk to Bob via Tailscale

Speak to Bob from any iPad/iPhone on your Tailscale network.

### Endpoint
- **URL**: `http://100.89.1.51:8088/ask`
- **Method**: POST
- **Body**: `{"message": "your spoken text"}`
- **Response**: `{"reply": "Bob's response"}`

### Quick Test
```bash
curl -X POST http://100.89.1.51:8088/ask \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Bob"}'
```

### iOS Shortcut Setup
1. **Dictate Text** — User speaks
2. **Get Contents of URL** — POST to `http://100.89.1.51:8088/ask` with JSON body `{"message": [Dictated Text]}`
3. **Get Dictionary Value** — Extract `reply` field
4. **Speak Text** — Read reply aloud

Full guide: `setup/ipad/VOICE_SHORTCUT.md`

### Service Management
```bash
# Install (auto-start on boot)
cp setup/launchd/com.symphony.voice-webhook.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.voice-webhook.plist

# Check status
curl http://100.89.1.51:8088/health

# Logs
tail -f logs/voice-webhook.log
```

### Files
- `api/voice_webhook.py` — Flask server (port 8088)
- `setup/launchd/com.symphony.voice-webhook.plist` — launchd service
- `setup/ipad/VOICE_SHORTCUT.md` — iOS Shortcut instructions

---

## Polymarket Integration (NEW)

### Telegram Commands
- `/poly` — Trending markets (by 24h volume)
- `/poly_search <query>` — Search markets
- `/poly_arb` — Find arbitrage opportunities

### CLI
```bash
python3 integrations/polymarket/polymarket_client.py --trending
python3 integrations/polymarket/polymarket_client.py --search "Trump"
python3 integrations/polymarket/polymarket_client.py --arbitrage
python3 integrations/polymarket/polymarket_scan.py --dry   # 10-min scan (dry run)
```

### 10-Minute Scan (launchd)
- Runs every 10 min via `com.symphony.polymarket-scan`
- Flags **NEW high-volume** predictions (markets that just appeared in top trending)
- Sends to Telegram only when arbitrage or new high-volume detected

### API Endpoints
- **Gamma API**: `https://gamma-api.polymarket.com/markets` — Market data
- **CLOB API**: `https://clob.polymarket.com` — Order book, trading

### Research Saved
- `knowledge/research/polymarket_api.md` — API docs
- `knowledge/research/polycop_bot.md` — PolyCop bot features
- `knowledge/research/polymarket_strategies.md` — Trading strategies

### Polymarket Research (Betty/Beatrice)
- **Skill:** `.cursor/skills/polymarket-research/SKILL.md` — Workflow for agents
- **Agent:** `@product/polymarket-researcher` — Structured Polymarket analysis
- **Autonomous worker:** Research tasks with "polymarket", "arbitrage", "first winning trade" run polymarket_client --trending, --arbitrage first, then parallel-cli search
- **Betty → Telegram:** When she finds arbitrage or opportunities, she sends an alert to Telegram
- **Hourly scan:** `com.symphony.polymarket-hourly` runs 9am–8pm, sends trending + arbitrage to Telegram so you can spot winners
- **parallel-cli:** Ensure `~/.local/bin` in PATH for Betty; worker adds it automatically

### Next Steps for Trading
1. Set up Polygon wallet (USDC)
2. Get API keys from Polymarket
3. Implement order placement in `polymarket_client.py`
4. Consider PolyCop bot for copy trading ($29/mo)

---

## Incoming Tasks — Zero-Touch Task Management

Drop tasks into your **"Incoming Tasks"** Apple Notes folder → They get auto-processed → Results appear in Telegram.

### How It Works
1. **Add a task** to "Incoming Tasks" folder in Apple Notes (natural language)
2. **Processor** (`orchestrator/incoming_task_processor.py`) reads and categorizes it
3. **Auto-implements** if possible (research, integrations, automations)
4. **Creates task** on Task Board for team to complete
5. **Updates note** with "✅ PROCESSED" and result

### Task Categories (Auto-Detected)
| Category | Keywords | Can Auto-Implement |
|----------|----------|-------------------|
| Research | "find", "look up", "research" | ✅ Uses parallel-cli |
| Integration | "connect", "api", "telegram", "bot" | ✅ Creates task + research |
| Automation | "automate", "script", "schedule" | ✅ Creates script |
| Proposal | "proposal", "quote", "d-tools" | ⚠️ Needs human review |
| Communication | "call", "email", "message" | ❌ Human only |

### Telegram Commands
- `/incoming` — Process new tasks now
- `/incoming_status` — View pending tasks

### Running the Processor
```bash
# One-time check
python3 orchestrator/incoming_task_processor.py --check

# Continuous daemon (checks every 5 min)
python3 orchestrator/incoming_task_processor.py --watch --interval 300

# Install launchd for auto-start
cp setup/launchd/com.symphony.incoming-tasks.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.incoming-tasks.plist
```

---

## Task Board — 24/7 Autonomous Operations

The team works autonomously around the clock. No prompting needed.

### How It Works
1. **Task Board** (`orchestrator/task_board.py`) — Central SQLite queue
2. **Autonomous Workers** (`orchestrator/autonomous_worker.py`) — Each employee runs continuously
3. **Periodic Updates** (`orchestrator/periodic_updater.py`) — Telegram updates every 1-2 hours
4. **Notes Watcher** (`tools/notes_watcher.py`) — Auto-creates tasks from new Apple Notes
5. **Incoming Processor** (`orchestrator/incoming_task_processor.py`) — Processes natural language tasks

### Worker Skills
| Worker | Skills | Focus | Bot |
|--------|--------|-------|-----|
| Betty 📚 | research, documentation, learning, troubleshooting | Knowledge base, research | @SymphonyBettyBot |
| Beatrice 📋 | proposal, commissioning, integration | D-Tools, system shells | @SymphonyBeatriceBot |
| Bill 🔧 | maintenance, troubleshooting, integration | Monitoring, fixes | (future) |
| Bob 🎩 | all | Orchestration, human interface | @SymphonyBobBot |

### Symphony Ops Group
All bots can be added to a "Symphony Ops" Telegram group for team coordination.
Each employee bot responds to mentions and can report their status.

**Setup:**
1. Create bots via @BotFather: `/newbot` → "Betty - Symphony" → @SymphonyBettyBot
2. Add tokens to `.env`: `BETTY_BOT_TOKEN=xxx`, `BEATRICE_BOT_TOKEN=xxx`
3. Create Telegram group "Symphony Ops", add all bots
4. Run `./START_SYMPHONY_OPS.command`

### Task Types
- `research` — Find information, docs, specs
- `documentation` — Create/update guides, references
- `troubleshooting` — Debug issues, find solutions
- `proposal` — D-Tools proposals, quotes
- `commissioning` — System shells, device setup
- `learning` — Process training notes, certifications
- `idea` — Expand ideas into actionable tasks
- `maintenance` — System health, scheduled maintenance
- `integration` — Connect systems, configure protocols

### Task Priority
- 🔴 `critical` — Do immediately
- 🟠 `high` — Today
- 🟡 `medium` — This week
- 🟢 `low` — When time permits

### CLI Commands
```bash
# Add task
python3 orchestrator/task_board.py add "Research EA-5 wiring" --type research --priority high

# List tasks
python3 orchestrator/task_board.py list --status pending

# Get worker's next task
python3 orchestrator/task_board.py next --worker betty

# Complete task
python3 orchestrator/task_board.py complete 1 --notes "Found docs, saved to knowledge/"

# Board status
python3 orchestrator/task_board.py status

# Work report (last 2 hours)
python3 orchestrator/task_board.py report --hours 2
```

### Telegram Commands
- `/tasks` — View pending tasks
- `/task_add <title>` — Add new task
- `/task_status` — Board overview
- `/task_report [hours]` — Work completed

### Running the System
```bash
# Start Betty's worker (runs forever)
python3 orchestrator/autonomous_worker.py --worker betty

# Start periodic updates (every 2 hours)
python3 orchestrator/periodic_updater.py --daemon --interval 2

# Or install launchd plists for auto-start
cp setup/launchd/com.symphony.worker-betty.plist ~/Library/LaunchAgents/
cp setup/launchd/com.symphony.periodic-updater.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.worker-betty.plist
launchctl load ~/Library/LaunchAgents/com.symphony.periodic-updater.plist
```

---

## Previous: Human Input Windows

### Job Queue (`orchestrator/job_queue.py`)
Persistent SQLite-based task queue for async work delegation.
- `python3 orchestrator/job_queue.py add research '{"query":"SIG-56-IC specs"}'`
- `python3 orchestrator/job_queue.py status`
- Telegram: `/queue` to view, `/queue add <type> <payload>` to add

### Worker (`orchestrator/worker.py`)
Continuous job processor. Each employee runs their own worker.
- `python3 orchestrator/worker.py --worker betty --types research,scrape_docs`
- Can run as launchd daemon (see `setup/launchd/`)

### Perplexity Research (`tools/perplexity_research.py`)
Real-time research when local knowledge insufficient.
- `python3 tools/perplexity_research.py "SIG-56-IC wiring diagram"`
- Telegram: `/research <query>`
- Requires: `PERPLEXITY_API_KEY` in `.env`

### Daily Briefings (`integrations/telegram/daily_digest.py`)
Auto-generated briefings at 6am and 8pm.
- **Team joke:** Bob, Betty, Beatrice present a joke they came up with together at the start of every briefing (Perplexity or rotating fallback).
- System health, queue status, pending proposals
- Items needing human decision
- Runs via launchd (`setup/launchd/com.symphony.daily-digest.plist`)

### SnapAV Documentation (`tools/snapav_scraper.py`)
Autonomous product doc scraping with Playwright.
- `python3 tools/snapav_scraper.py docs SIG-56-IC`
- Telegram: `/getdocs <SKU>`
- Saves to `knowledge/products/snapone/`

### Worker Learning (24/7 — `workers_cortex_learn.py` + `workers_question_generator.py`)
Bob sends work to Betty every 3 min via conductor_checkin. Workers build cortex connections and answer domain questions.

### Task Filler (`orchestrator/task_filler.py`) — No One Task-Free
When pending tasks < 6, adds learning tasks (cortex connections, product Q&A). Runs from conductor_checkin and when autonomous_worker finds no tasks. Betty/Beatrice/Bill always have work.

- **Connections:** `workers_cortex_learn.py` — Extracts connections from cortex chunks (Control4 ↔ Lutron, etc.)
- **Q&A:** `workers_question_generator.py` — Asks product questions (physical connections, HDMI, pre-amp, setup) from `knowledge/cortex/question_templates.json`
- **Templates:** Receivers, controllers, amplifiers, lighting, networking, surveillance, displays, shades
- **Add more:** Edit `question_templates.json` — products + question templates for any category

**Local AI options:** `docs/LOCAL_AI_OPTIONS.md` — Ollama, LM Studio, Open WebUI, llama.cpp

### Overnight Learning (`tools/overnight_learner.py`)
Betty runs nightly at 11 PM to build knowledge base.
- `python3 tools/overnight_learner.py --all` — Full learning session
- `python3 tools/overnight_learner.py --mitchell` — Mitchell proposal products
- `python3 tools/overnight_learner.py --status` — Check progress

Currently learning:
- Mitchell proposal: 36 products (networking, surveillance, speakers, power)
- Araknis networking: 22 products (switches, APs, routers)
- Luma surveillance: 14 products (NVRs, cameras, mounts)
- Lutron QS shades: Research notes and compatibility

### Apple Notes Reader (`tools/notes_reader.py`)
Access to Apple Notes database — project photos, codes, programming notes, previous work.
- `python3 tools/notes_reader.py --list-folders` — Show all folders
- `python3 tools/notes_reader.py --list "Symphony SH"` — List notes in folder
- `python3 tools/notes_reader.py --read 346` — Read specific note
- `python3 tools/notes_reader.py --search "Holdeman"` — Search all notes
- `python3 tools/notes_reader.py --project-summary "Aspen Glen"` — Full project context

Key folders:
- **Symphony SH** (104 notes, 654 photos) — Active projects, system configs, codes
- **Previous Work** (21 notes) — Completed projects for reference
- **Work Cheats** (11 notes) — Quick reference, macros, shortcuts

### Notes Sync (`tools/notes_sync.py`)
Sync and categorize notes into the knowledge base.
- `python3 tools/notes_sync.py --sync-all` — Sync everything
- `python3 tools/notes_sync.py --sync-photos` — Export photos by project (785 photos, 72 projects)
- `python3 tools/notes_sync.py --sync-learning` — Sync Learning notes (courses, certs)
- `python3 tools/notes_sync.py --sync-ideas` — Sync My Stuff (ideas → tasks)
- `python3 tools/notes_sync.py --list-courses` — List all training/courses
- `python3 tools/notes_sync.py --list-ideas` — List ideas with potential tasks

**Learning Notes Categories:**
- av_integration: CEDIA, Control4, Snap One
- networking: Network+, VLANs, TCP/IP
- cloud: AWS, Azure
- programming: Python, Docker, React
- certifications: CompTIA A+/Network+/Security+

**Ideas Pipeline:**
- Auto-extracts potential tasks from idea notes
- Tags: automation, hardware, software, design, improvement
- Exports to `knowledge/ideas/ideas_index.json`

**Photo Export:**
- Categorizes 785+ photos by project name
- Creates `knowledge/photos_by_project/index.json`
- Use for website portfolio, documentation

Telegram commands:
- `/learning` — List courses/training
- `/ideas` — List ideas from My Stuff
- `/sync_notes [all|photos|learning|ideas]` — Run sync
- **Control4** (scheduled): Controllers, keypads, amplifiers

### Outline Creator (`tools/outline-creator/`)
Auto-organizes chat conversations into structured knowledge.
- `python3 tools/knowledge_bridge.py route "Control4 EA-5 reboot fixed issue" --title "EA-5 Fix"`
- `python3 tools/knowledge_bridge.py status`
- Drop files in `tools/outline-creator/_Inbox/Chats/` for auto-routing
- Categories: Control4, Automations, Network, Servers, Diagnostics

### Paid Research (`tools/paid_research.py`)
Only researches when revenue justifies cost.
- `python3 tools/paid_research.py --query "speaker comparison" --context proposal --value 500`
- Low-value queries fall back to local knowledge
- ROI tracked in `logs/research_roi.jsonl`

### Trading — Team Strategy (`trading/`)

Paper trading with team-based analysis and free-first research.

**Research Hierarchy (cheapest first):**
1. Alpaca (FREE) - quotes, news, market status
2. Yahoo Finance (FREE) - fundamentals, history
3. Finnhub (FREE tier) - sentiment, news (requires `FINNHUB_API_KEY`)
4. Local Knowledge (FREE) - Betty's research
5. Perplexity (PAID) - ONLY when team is stumped

**Commands:**
- `python3 trading/market_research.py --analysis SPY` — Full FREE analysis
- `python3 trading/strategy_framework.py --analyze SPY` — Team analysis
- `python3 trading/strategy_framework.py --performance` — Track P&L
- `python3 trading/alpaca_trader.py --status` — Account status
- `python3 trading/alpaca_trader.py --positions` — Current holdings

**Strategy:**
- Paper trade for 3-7 days, prove profitability, then switch to real
- Max 5% portfolio per position, 2% stop loss, 4% take profit
- Win rate target: 55%, profit target: $500 before real money

**Free API Keys:**
- Alpaca: Required, get at https://alpaca.markets
- Finnhub: Optional, get FREE at https://finnhub.io/register

### Architecture Doc
See `docs/AUTONOMOUS_TEAM_ARCHITECTURE.md` for full design.

---

## Continuous Learning System — Persistent Growth

The team learns continuously, building knowledge that compounds over time.

### How It Works
The `continuous_learning.py` daemon runs 24/7, learning something new every 20-30 minutes:

1. **Company Knowledge** (priority: high) — Control4 techniques, Lutron tips, project management, pricing strategies
2. **Industry Trends** (priority: medium) — CEDIA announcements, new products, market analysis
3. **News & Events** (priority: medium) — Tech news, market updates, economic indicators
4. **Polymarket Intel** (priority: low) — Prediction markets, event probabilities, trading opportunities
5. **Local Market** (priority: low) — Denver real estate, Colorado construction, regional trends

### Knowledge Saved To
- `knowledge/cortex/company/` — Internal best practices
- `knowledge/cortex/industry/` — Industry knowledge
- `knowledge/news/` — Daily news by month
- `knowledge/market_intel/` — Polymarket and investment research

### Telegram Commands
- `/learning` — Show learning status (queries today, topics learned)
- `/learn [topic]` — Learn something specific now
- `/news` — Get latest news digest
- `/cortex` — Knowledge base stats

### CLI
```bash
# Check status
python3 orchestrator/continuous_learning.py --status

# Learn once
python3 orchestrator/continuous_learning.py --once

# Learn specific topic
python3 orchestrator/continuous_learning.py --query "Lutron shading best practices" --category company

# Run daemon (every 30 min)
python3 orchestrator/continuous_learning.py --daemon --interval 30
```

### Daily Budget
- **50 queries/day** — Conserves Perplexity API while building substantial knowledge
- Uses `sonar` model (smaller, cheaper) for learning queries
- Full `sonar-pro` model reserved for user research requests

### Launchd Service
```bash
# Install auto-start
cp setup/launchd/com.symphony.learning.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.learning.plist
```

---

## New Tools Available

### iCloud Sync (`tools/icloud_sync.py`)
Syncs files from iCloud `Symphony SH/` folder to `knowledge/` subdirectories.
- `--sync` — One-time sync
- `--watch` — Continuous daemon (every 5 min)
- `--status` — Show sync status
- `--dry-run` — Preview without copying

### System Shell Generator (`tools/system_shell.py`)
Creates commissioning shells from proposals with auto-VLAN, ports, and documentation.
- `--generate "Project"` — Create shell from proposal (auto-assigns VLANs + docs)
- `--show "Project"` — Display shell with VLAN assignments
- `--vlans "Project"` — Show VLAN summary for project
- `--export-vlans "Project"` — Export VLAN config to JSON
- `--setup-guide "Project"` — Show step-by-step installation guide with manual links
- `--export-guide "Project"` — Export setup guide to markdown
- `--update "Project" --room "Theater" --device "EA-5" --ip "192.168.1.10"` — Update device

**Auto-generated per project:**
1. `shell.json` — Device inventory with VLAN, ports, manual links
2. `vlan_config.json` — Router/switch VLAN configuration
3. `port_allocation.json` — Switch/NVR port assignments
4. `port_labels.csv` — Cable labels for commissioning
5. `setup_guide.md` — Step-by-step installation guide with docs links

### Port Allocator (`tools/port_allocator.py`)
Auto-assigns switch/NVR ports following Symphony rules (cameras→NVR, not switch).
- `--project "Project"` — Allocate ports for all devices
- `--export "Project"` — Export port labels to CSV for cable labeling

### VLAN Best Practices (`knowledge/network/vlan_best_practices.md`)
Symphony Standard VLAN Scheme:
| VLAN | Name | Subnet | Purpose |
|------|------|--------|---------|
| 1 | Management | 192.168.1.0/24 | Switches, routers, APs, WattBox |
| 10 | Trusted | 192.168.10.0/24 | Personal devices (phones, laptops) |
| 20 | Control | 192.168.20.0/24 | Control4, Lutron, Sonos |
| 30 | IoT | 192.168.30.0/24 | Smart TVs, thermostats, Alexa |
| 40 | Guest | 192.168.40.0/24 | Guest WiFi (internet only) |
| 50 | Surveillance | 192.168.50.0/24 | Cameras + NVR (block internet) |

### Araknis Product Guide (`knowledge/network/araknis_product_guide.md`)
Complete switch/router/AP reference with specs and config steps.
- 110/210/310/320/420 switch series comparison
- AN-220/520/810 router specs
- AN-510/710 access point options
- PoE budget planning
- VLAN configuration steps for routers and switches

### Smart Home Protocol Reference (`knowledge/network/smart_home_protocols.md`)
Comprehensive protocol guide for understanding how every device communicates:

**Lutron RadioRA 3:**
- Clear Connect Type X: 2.4GHz mesh (Sunnata, Palladiom) — 100 devices/processor
- Clear Connect Type A: 434MHz star (legacy RA2, Maestro RF) — 95 devices/processor
- QS Link: RS-485 wired bus (Sivoia QS shades, panels)
- Lutron Integration Protocol: TCP 23 (Control4/Josh integration)

**Control4:**
- ZigBee Pro: 2.4GHz mesh (wireless keypads, sensors) — 125 devices
- SDDP: UDP 5020 auto-discovery
- Control4Net: TCP/IP controller-to-controller

**Network (Araknis):**
- IEEE 802.1Q: VLAN tagging
- IEEE 802.3af/at/bt: PoE (15W/30W/60-100W)
- IGMP: Multicast management (Sonos, AirPlay, surveillance)
- mDNS: Service discovery (port 5353) — needs reflector across VLANs

**Surveillance (Luma):**
- ONVIF: Camera interoperability
- RTSP: Video streaming (port 554)

**Audio (Sonos):**
- SonosNet: 2.4GHz proprietary mesh
- Requires: mDNS + IGMP snooping

**Integration Matrix:**
| Source | Target | Protocol |
|--------|--------|----------|
| Control4 | Lutron RA3 | LEAP driver (IP) |
| Control4 | Sonos | SSDP/mDNS (IP) |
| Control4 | Luma | RTSP from NVR |
| Lutron RA3 | Shades | Type A RF or QS Link |

### Knowledge Query (`tools/knowledge_query.py`)
Unified search for Telegram integration.
- `find "EA-5 manual"` — Search files
- `project "Smith"` — Project info
- `sku "C4-KPZ"` — SKU usage
- `device "Smith" "EA-5"` — Device MAC/IP
- `network "Smith"` — All network devices
- `shell "Smith"` — Shell summary
- `protocol "mDNS"` — Protocol details and device compatibility
- `troubleshoot "Sonos"` — Find troubleshooting guides for product/issue

### Notes Watcher (`tools/notes_watcher.py`)
Monitors Apple Notes for new/updated content with auto-categorization.
- `--watch` — Continuous monitoring daemon (5 min interval)
- `--check` — One-time check for changes
- `--status` — Show sync status and recent notes
- `--process-new` — Process all unprocessed notes

**Auto-categorization rules:**
- Notes from "Symphony SH" → project (linked to project folder)
- Notes from "Learning" → learning (indexed with relevance score)
- Notes from "My Stuff" → ideas (tasks extracted)
- Notes matching patterns → reference (IPs, MACs, codes extracted)

**Project matching:**
- Recognizes address patterns: "524 Beeler", "4684 Wildridge"
- Recognizes property names: "Aspen Glen", "High Cliffe - Bersin"
- Creates project directories under `knowledge/projects/`
- Links notes to existing System Shells when matched

Telegram commands:
- `/watch_notes` — Check for new notes
- `/watch_status` — Watcher status

### Integration Troubleshooting (`knowledge/network/integration_troubleshooting.md`)
Complete troubleshooting guide for common integration issues:

**Control4 ↔ Lutron:**
- LEAP driver offline (OS 4.x bug) — update driver, verify static IP
- Room name mismatches — use "Add Areas" first
- VCRX integration issues — needs separate RS-232/Telnet

**Control4 ↔ Sonos:**
- Sonos not discovered — mDNS/SSDP blocked, VLAN isolation
- Groups keep breaking — STP issues, wire one speaker
- Volume sync issues — restart driver, check duplicates

**Control4 ↔ Luma:**
- RTSP stream errors — verify password, test URL directly
- Cameras in NVR but not C4 — routing between VLANs
- Multi-camera grid blank — sub-stream not configured

**Network/VLAN Issues:**
- mDNS not crossing VLANs — enable mDNS reflector
- IGMP multicast flooding — configure snooping + querier

**Quick Reference Ports:**
| Protocol | Port | Used By |
|----------|------|---------|
| mDNS | 5353/UDP | Sonos, Apple TV, Chromecast |
| SSDP | 1900/UDP | UPnP, Sonos, Control4 |
| SDDP | 5020/UDP | Control4 discovery |
| RTSP | 554/TCP | Cameras, NVRs |
| Telnet | 23/TCP | Lutron integration |

Telegram: `/troubleshoot <product>` — Find issues for product

### Role Template (`.claude/agents/_template.md`)
Copy to create new agent roles on the fly.

### Knowledge Graph (`tools/knowledge_graph.py`)
Fractal knowledge tree where everything connects. 81 nodes, 76 relationships.
- `--init` — Initialize database and build tree
- `--add "SKU" --type product --parent "Brand"` — Add node
- `--connect "SKU1" "controls" "Category"` — Create relationship
- `--path "Device1" "Device2"` — Find connection path
- `--info "Node"` — Show node details
- `--stats` — Show graph statistics

**Inference Rules (auto-applied):**
- Cameras always connect through NVR (not directly to switch)
- NVR provides PoE to cameras
- WattBox powers all rack equipment

### Graph Learner (`tools/graph_learner.py`)
Betty's continuous learning engine populating the knowledge graph.
- `--learn` — Learn all products with relationships
- `--status` — Show graph status
- `--query "how does X connect to Y?"` — Query connections

---

## Browser Automation — Full Autonomous Control

The team has full browser control. No hand-holding required.

### Tools Available

| Tool | Use Case | How to Use |
|------|----------|------------|
| **browser-use** (Python) | Autonomous tasks | Give it a goal, it figures out navigation, forms, clicks |
| **agent-browser** (CLI) | Quick automation | Shell commands: `agent-browser open URL`, `agent-browser click @e1` |
| **Playwright MCP** | Cursor agent tool | Direct browser control via MCP protocol |

### Telegram Commands
- `/browse <task>` — Autonomous browser task (e.g., "Go to D-Tools and create project Mitchell")
- `/dtools_auto create "Project" "Client"` — Playwright headless project creation
- `/dtools_auto import P-XXXX` — Create project + import equipment from symphony proposal (Playwright)

### CLI Examples
```bash
# Autonomous task (browser-use)
python3 -m symphony.browser.autonomous "Log into D-Tools, create project 'Smith Residence' for client 'John Smith'"

# D-Tools workflow
python3 -m symphony.browser.autonomous --dtools-project "Mitchell" --client "Mitchell Family" --address "182 Stage Coach Way"

# Quick CLI automation (agent-browser)
agent-browser open https://portal.d-tools.com
agent-browser snapshot -i  # Get interactive elements
agent-browser fill @e1 "username"
agent-browser click @e3
```

### Files
- `symphony/browser/autonomous.py` — browser-use wrapper with D-Tools presets
- `.cursor/mcp.json` — Playwright MCP config

---

## Email Integration — BuildingConnected Bids

Auto-monitor `info@symphonysh.com` for BuildingConnected bid invitations.

### Telegram Commands
- `/inbox` — Check inbox summary
- `/bids` — Check for new BuildingConnected bids
- `/bid_list` — List all saved invitations
- `/bid_create EMAIL_UID` — Create proposal from bid
- `/email_search query` — Search emails

### CLI
```bash
python3 -m symphony.email.cli inbox
python3 -m symphony.email.cli bids --check
python3 -m symphony.email.cli bid-create EMAIL_UID
```

### Auto-Extracted from BC Emails
- Project name, address
- GC name, contact, phone
- Bid due date/time
- Scope of work
- Direct link to BuildingConnected

### Setup
Add to `.env`:
```
SYMPHONY_EMAIL=info@symphonysh.com
SYMPHONY_EMAIL_PASSWORD=your_gmail_app_password
```

---

## Perplexity Computer — External AI Workforce

For tasks beyond local capabilities, Perplexity Computer offers:

### Connectors (400+ Apps)
- **Gmail** — Read, write, send emails
- **Google Drive** — Search, create, update documents
- **Slack** — Team communication
- **Notion** — Documentation
- **Google Calendar** — Scheduling
- **GitHub** — Code repos

### Features
- 19 AI models (Claude, GPT, Gemini) auto-selected per task
- Persistent memory across conversations
- Cloud sandboxes with browser, filesystem, CLI
- Complex end-to-end workflows

### Pricing
- Pro: $20/mo (basic access)
- Max: $200/mo (Perplexity Computer + 10k credits)

### When to Use
- Multi-step workflows across many apps
- When local browser automation isn't enough
- Document generation across Google Workspace
- Complex research requiring multiple sources

---

## Active: D-Tools Cloud Proposal

**Status:** ~65% complete. **Roadmap:** `orchestrator/PROPOSAL_PROCESS_ROADMAP.md` — team tasks for ironing out the process.

**Goal:** Complete any task on dtools.cloud, with full job/install awareness and a reliable fallback.

### Required Behaviors

1. **Search previous jobs** — Before creating or updating a proposal, search all past D-Tools projects/opportunities. Use `dtools_client.get_projects()`, `get_opportunities()`, and `get_clients()` to avoid duplicates and match existing work.

2. **Track current installs** — Keep up with active installs and projects. Use `get_active_pipeline()` and status filters (Active, Completed, OnHold) so proposals align with real work.

3. **Offer alternatives when no match** — If a search returns no suitable project/install, offer the user another option (e.g. create new, link to similar project, or suggest a follow-up).

4. **Control4 as return option** — Control4 is always the default/return option for proposals. When equipment choices are ambiguous or a fallback is needed, use Control4. See `tools/bob_export_dtools.py` and HARPA D-Tools commands for Control4 categories (Lighting, HVAC, Annual Membership, etc.).

### Secrets

- **DTOOLS_API_KEY** — Put in Bob’s `.env` (root of AI-Server). Bob and all employees load from here.
- **Per-employee secrets** — Use config drive `/Volumes/HomebaseConfig/{employee}.env` (e.g. HARPA keys). Only Bob and employees below him can access these via the setup flow.

### Relevant Files

- `integrations/dtools/dtools_client.py` — API client
- `setup/harpa/harpa_dtools_commands.json` — HARPA commands for portal.d-tools.com
- `tools/bob_export_dtools.py` — CSV export, Control4 line-item format
- `.cursor/rules/dtools.mdc` — D-Tools rules and proposal workflow

---

## Claude Code — Terminal-Based AI Agent

Claude Code is Anthropic's agentic CLI. It runs in terminal and can work **in parallel with Cursor**.

### Installation
```bash
# Already installed on Bob
which claude  # /opt/homebrew/bin/claude
claude --version  # 2.1.70
```

### When to Use Claude Code vs Cursor

| Task | Best Tool | Why |
|------|-----------|-----|
| Multi-file refactoring | Claude Code | Works autonomously across files |
| Quick single-file edit | Cursor | Faster for targeted changes |
| Background autonomous work | Claude Code | Runs in terminal, no GUI |
| Research + implement | Cursor | Has web search + MCP tools |
| Code review | Claude Code | Systematic file traversal |
| Batch operations | Claude Code | Can process many files |

### Telegram `/claude` — Run with Context
From Telegram: `/claude <task>` — Launches Claude Code with WORK_IN_PROGRESS + task board context. Output: `logs/claude_job_*.log`. Optional: write `knowledge/agents/CLAUDE_FOCUS.txt` to add "what we're working on."

### Claude Approval Bridge (You as Bridge)
New tasks with `--type claude` flow: **Task Board → iOS Approve → Bob → Claude Code**.

1. **Add task:** `python3 orchestrator/task_board.py add "Refactor X" --type claude --priority high`
2. **iOS:** Symphony Ops app → Claude tab → Pending tasks → Approve
3. **Bob:** On approve, runs `claude -p "<task>"` with WORK_IN_PROGRESS context

- **API:** `GET /tasks/claude_pending`, `POST /tasks/{id}/approve_claude`, `POST /tasks` (add)
- **Files:** `tools/claude_runner.py`, `orchestrator/task_board.py`

### Starting a Session
```bash
cd /Users/bob/AI-Server
claude
# Auto-loads CLAUDE.md for project context
```

### Best Patterns

**1. Parallel Work** — Run Claude Code in Terminal while using Cursor:
```bash
# Terminal 1 (Claude Code)
claude
> Refactor telegram-bob-remote/main.py into modules

# Cursor: Continue interactive work
```

**2. Batch Operations:**
```
For every Python file in tools/:
1. Add type hints to all function parameters
2. Add docstrings if missing
3. Run linter and fix issues
```

**3. Agent Roles:**
```
Act as @engineering/backend-architect and review the API design.
```

**4. Single Command:**
```bash
claude -p "List all TODO comments in the codebase"
cat error.log | claude -p "Diagnose this error"
```

### Future: Agent-to-Agent Communication (MCP or API)

Cursor and Claude Code cannot talk directly today. **Keep in mind for future:**
- If Claude Code exposed an MCP server or HTTP API, Cursor could call it.
- If Cursor exposed an agent API, Claude could call back.
- That would enable real programmatic handoffs; not standard today. Current workaround: shared files (mailbox), task board, or user as bridge.

### Key Files
- `setup/claude_code/CLAUDE_CODE_ADVANTAGE.md` — **How to leverage Claude Code** (parallel work, best tasks, one-liners)
- `setup/claude_code/CLAUDE.md` — Auto-loaded context
- `setup/claude_code/USAGE_GUIDE.md` — Detailed guide
- `setup/claude_code/claude_code_workflows.md` — 7 workflow templates
- `.claude/agents/` — 30+ specialized roles

---

## Claude Agent Role Workflow

Role definitions live in `.claude/agents/` by department. Bob and other agents can invoke these roles when a task matches:

| Department | Roles |
|------------|-------|
| Engineering | frontend-developer, backend-architect, mobile-app-builder, devops-automator, ai-engineer, rapid-prototyper |
| Product | trend-researcher, feedback-synthesizer, sprint-prioritizer |
| Marketing | tiktok-strategist, instagram-curator, twitter-engager, reddit-community-builder, app-store-optimizer, content-creator, growth-hacker |
| Design | ui-designer, ux-researcher, brand-guardian, visual-storyteller, whimsy-injector |
| Project Management | experiment-tracker, project-shipper, studio-producer |
| Studio Operations | support-responder, analytics-reporter, infrastructure-maintainer, legal-compliance-checker, finance-tracker |
| Testing | tool-evaluator, api-tester, workflow-optimizer, performance-benchmarker, test-results-analyzer |

- **Index:** `.claude/agents/INDEX.md`
- **Cursor rule:** `.cursor/rules/claude-agents.mdc`

---

## Link Future Agents to This Task

When starting work on D-Tools or proposals:

1. Read this AGENTS.md section.
2. Read `.cursor/rules/dtools.mdc` for workflow rules.
3. Ensure DTOOLS_API_KEY is set (user provides via secure file).
4. Follow: search jobs → track installs → offer alternatives → Control4 fallback.

---

## Learned User Preferences

- Vail Valley, not Denver — all SEO, jobs, and results should reflect Vail Valley / Eagle County
- Never use real addresses, house numbers, or client names in social posts — strip PII; road names and client last names are OK as project nicknames
- Use Cloudflare API for DNS changes when browser automation is blocked (CAPTCHA)
- Store everything local — keep data and catalogs local for speed; avoid expensive APIs when manual export works
- Prefer free/local tools over paid APIs (e.g., SnapOne CSV export vs $350/mo API)
- Use Perplexity and local knowledge before paid APIs; research hierarchy: local first, Perplexity when stumped
- Perplexity credits available; use in tools/social_content.py when needed (falls back to GPT if disabled)
- Perplexity credit strategy: `knowledge/research/perplexity_credit_strategy.md` — video (0 used) = highest ROI; text for research/social
- Use GitHub for Cloudflare sign-in (migrating away from Google)
- Gap checker and proposal tools should have full SKU catalog search with multi-word queries
- Use ROI-first model routing: ask before costly model shifts unless high rework risk; auto-use Ultra/multi-model early for high-risk work to avoid repeat loops (e.g., git stash/merge retry chains)

---

## Learned Workspace Facts

- NVR has built-in PoE for cameras — cameras connect to NVR, not directly to the main switch; don't count cameras against switch port count
- Sonos AMPs and TVs are hardwired — include them in switch port calculations
- SnapOne price list: `knowledge/other/SnapOnePriceList.csv` (or XLS from iCloud); rebuild with `tools/rebuild_catalog.sh`
- Client sheets (Pre-Wiring Pricing, Previous Clients, SnapOne) live in `knowledge/sheets/`
- Proposal gap checker: run `python3 -m http.server 8080` from tools folder, then open `http://localhost:8080/proposal_gap_checker.html`
- Gap checker search: multi-word AND logic (e.g., "C4 dimmer", "araknis 48 poe") across full SnapOne catalog
- D-Tools Cloud REST API: only DTOOLS_API_KEY needed (from Settings > Integration > Developer); Basic Auth is fixed
- Runtime under `data/` (SQLite, WAL, polymarket JSON/CSV, email-monitor DB, intel feeds, transcripts, `network_watch/`, OpenClaw live exports) is **gitignored** — stays on Bob; never commit it.
- Machine-local / experiments: **`symphonysh-web/`**, **`redis/`**, **`knowledge/cortex/`**, **`scratch/`**, **`.cursor/local/`** are gitignored. Put WIP sites, Redis dumps, generated cortex, and scratch files there. Shared Cursor prompts stay under **`.cursor/prompts/`** as normal filenames; drafts use **`scratch/`**, **`.cursor/local/`**, or the ignored name patterns in **`.gitignore`** (e.g. `*-part2.md`). Do not add **`knowledge/__init__.py`** — repo **`knowledge/`** is content + scripts, not a Python package root (polymarket-bot has its own **`knowledge/`** package).
- Overnight learner requires Playwright: `pip3 install playwright && playwright install chromium`; launchd uses `/usr/bin/python3`
- Overnight learner SKUs: extend via `knowledge/learning/overnight_skus.json` (optional merge with built-in lists)
- iOS signing recovery: if `CodeSign failed` due to revoked `Apple Development` cert and Xcode delete is grayed out, open Keychain Access -> `login` -> `My Certificates`, search `Apple Development`, then delete affected Apple Development cert entries and matching private keys, regenerate cert in Xcode Accounts, and rebuild.
