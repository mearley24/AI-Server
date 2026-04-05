# Wave 5-6: Business Automation + Bob's Brain

**Priority:** HIGH — this is the business side of the flywheel. Trading funds business → business funds trading.
**Dependencies:** Waves 0-4 assumed complete. Mission Control (API-5) already shipped.

---

## Context Files to Read First

Read these before writing ANY code:

- `notification-hub/main.py` — current dispatcher, understand routing logic and what channels it supports
- `scripts/imessage-server.py` — iMessage bridge, what Redis channel it listens on, message format
- `integrations/telegram/telegram_bot.py` — what is implemented vs stubbed
- `symphony/email/client.py` — Zoho email client, send method signature, auth mechanism
- `scripts/start_hermes.sh` — startup script
- `email-monitor/router.py` — existing Redis pub/sub patterns
- `knowledge/proposal_library/README.md` — knowledge layer overview
- `knowledge/proposal_library/scope_blocks/*.md` — scope blocks
- `knowledge/sow-blocks/*.md` — SOW blocks
- `openclaw/sow_assembler.py` — existing SOW assembler
- `openclaw/preflight_check.py` — existing preflight checker
- `openclaw/proposal_checker.py` — proposal validation
- `proposals/proposal_engine.py` — proposal generation
- `proposals/pricing_calculator.py` — pricing
- `integrations/icloud_watch.py` — iCloud watcher pattern
- `openclaw/dropbox_integration.py` — Dropbox integration
- `knowledge/client_registry.json` — client routing table
- `openclaw/agent_bus.py` — AgentBus class, `agents:messages` channel, message envelope
- `openclaw/orchestrator.py` — current dispatch logic
- `openclaw/main.py` — OpenClaw entry point, startup sequence
- `openclaw/client_tracker.py` — client data storage and queries
- `openclaw/follow_up_tracker.py` — follow-up scheduling
- `openclaw/payment_tracker.py` — payment watching
- `openclaw/project_template.py` — 22-issue Linear template
- `openclaw/daily_briefing.py` — existing briefing
- `polymarket-bot/heartbeat/briefing.py` — BriefingGenerator
- `cursor-prompts/DONE/API-6-hermes-multi-platform.md` — full spec (~11KB)
- `cursor-prompts/DONE/Auto-9-knowledge-layer-assembler.md` — full spec
- `cursor-prompts/DONE/Auto-16-proposal-engine-automation.md` — full spec
- `cursor-prompts/DONE/Auto-18-dropbox-icloud-sync.md` — full spec (~11KB)
- `cursor-prompts/DONE/Auto-3-client-portal-voice.md` — full spec
- `cursor-prompts/DONE/Auto-17-daily-briefing-upgrade.md` — full spec
- `cursor-prompts/DONE/API-11-bobs-brain-unified-context.md` — full spec (~9KB)
- `cursor-prompts/DONE/API-12-profit-reinvestment-loop.md` — full spec (~13KB)
- `cursor-prompts/DONE/API-13-symphony-client-lifecycle.md` — full spec (~10KB)

---

## Part 1: API-6 — Hermes Multi-Platform Messaging

Read `cursor-prompts/DONE/API-6-hermes-multi-platform.md` for the complete spec. Key deliverables:

### 1. Unified Send Endpoint in notification-hub/main.py

Add `POST /api/send` with `NotificationRequest` model:
```
recipient, message, channel (auto|imessage|email|telegram), priority (normal|high|urgent),
message_type (alert|trade|client_comm|system_log|general), subject, thread_id, metadata
```

### 2. Channel Resolution Logic (`resolve_channel()`)

- alert/trade + high/urgent → imessage
- recipient starts with `client:` → email (professional)
- system_log → telegram
- urgent → both_imessage_email
- Matt → imessage
- default → imessage

### 3. Wire iMessage Channel

Publish to the Redis channel that `imessage-server.py` already listens on. Read that file first to find the exact channel name and message format. Store `MATT_PHONE_NUMBER` in `.env`.

### 4. Wire Zoho Email Channel

Use `symphony/email/client.py`'s existing send method. Read the constructor to understand how it's instantiated. Pull Zoho creds from `.env`.

### 5. Wire Telegram Channel (Stub)

Read `integrations/telegram/telegram_bot.py`. If it has `send_message` → wire it. If listener-only → add stub. Never crash notification-hub if Telegram fails.

### 6. Handle `both_imessage_email` for Urgent Alerts

Use `asyncio.gather()` to send via both channels simultaneously.

### 7. Redis Pub/Sub Listener

Listen on `notifications:email`, `notifications:telegram`, `notifications:send`. **CRITICAL**: Check if `imessage-server.py` already subscribes to `notifications:imessage` — if so, do NOT also subscribe to avoid duplicates. Use `notifications:send` as unified inbound.

### 8. Conversation Threading

Simple Redis thread tracker: `hermes:thread:{thread_id}` — list of `{message_id, channel, message, timestamp}`. 30-day TTL.

### 9. Tests

Create `tests/test_hermes.py` — test iMessage, email, and auto-route endpoints.

---

## Part 2: Auto-9 — Knowledge Layer & SOW Assembler

1. **SOW Assembler** (`openclaw/sow_assembler.py` — expand):
   - Takes room list + selected packages as JSON config
   - Pulls correct scope blocks from `knowledge/sow-blocks/`
   - Assembles complete SOW with proper section ordering
   - Auto-fills project variables (client name, address, room names)
   - CLI: `python3 sow_assembler.py --config project_config.yaml --output sow.md`

2. **Preflight Checker** (`openclaw/preflight_check.py` — expand):
   - Validates proposal/SOW against confirmed decisions
   - Cross-refs equipment list against room configs
   - Checks: VersaBox at every TV, network drops, orphaned devices
   - Validates pricing against SKU costs from `knowledge/products/`
   - CLI: `python3 preflight_check.py --proposal path.md --decisions path.md`

3. **Room Packages** (`knowledge/proposal_library/room_packages/`):
   - Complete the full set: required items, recommended add-ons, wire runs, labor hours
   - Composable: "Theater" = Audio + Video + Lighting sub-packages

4. **Knowledge Scanner** (`knowledge-scanner/` — wire up existing):
   - `scanner.py` crawls `knowledge/` and builds index
   - `processor.py` extracts facts (specs, compatibility, pricing)
   - Produces unified `knowledge/Bob_Master_Index.md`
   - Run weekly via heartbeat

5. Wire SOW assembler into email workflow: proposal approved + deposit received → auto-generate SOW → attach to Linear ticket.

---

## Part 3: Auto-16 — Proposal Engine End-to-End

Wire the proposal engine into a complete pipeline from lead to signed agreement:

1. **Intake**: consultation request → new project → LLM parses walkthrough notes into structured room configs → pull matching room packages

2. **Pricing** (`proposals/pricing_calculator.py` — expand):
   - Auto-calculate from SKU database, apply standard markup, labor estimate
   - Three tiers: Essential, Recommended, Premium

3. **Generation** (`proposals/proposal_engine.py` — expand):
   - Build from template + room configs + pricing
   - Always include VersaBox at every TV, network infrastructure, support agreement
   - Hyperlink product names. File naming: "Symphony Smart Homes — [Address] — Proposal.pdf"

4. **Review**: Auto-run preflight before any proposal goes out. Flag issues, block until resolved.

5. **Follow-up** (email templates):
   - Day 0: proposal cover email
   - Day 3, 7, 14: follow-ups via Zoho, logged in Linear

6. **D-Tools sync**: proposal accepted → auto-create D-Tools project → import equipment → generate SOW → create 22-issue Linear project

---

## Part 4: Auto-18 — Dropbox + iCloud File Sync

Read `cursor-prompts/DONE/Auto-18-dropbox-icloud-sync.md` for the complete spec (~11KB). Key deliverables:

1. **iCloud SymphonySH folder**: Diagnose why empty on Bob. Fix iCloud sync. Document setup in `setup/nodes/BOB_ICLOUD_SETUP.md`.

2. **Dropbox folder structure**: Standardize per the spec:
   ```
   Symphony Smart Homes/Projects/[Client] — [Address]/
   ├── Client/ (shared link, never changes)
   │   ├── Proposals/ Agreements/ Documents/
   ├── Internal/
   │   ├── Photos/ Drawings/ Notes/
   └── Archive/
   ```

3. **Proposal version management**: New PDF → upload to `Client/Proposals/`, move old version to `Archive/`. Use Dropbox Python SDK with refresh token.

4. **iCloud watcher** (`integrations/icloud_watch.py`): launchd service on host (not Docker). Auto-categorize by filename: proposals, photos, agreements, drawings → route to correct Dropbox subfolder via `client_registry.json` lookup. Unmatched → `knowledge/unrouted/` + notify Matt.

5. **Dropbox watcher** (`openclaw/dropbox_integration.py`): Poll with longpoll API every 5 min. Client uploads → auto-download, categorize, route. Signed agreement → trigger acceptance workflow.

6. **Unified file index** (`knowledge/file_index.json`): Master index with source, project, category, local/Dropbox paths. Queryable by Bob's Brain.

7. **Client registry** (`knowledge/client_registry.json`): Project lookup table with keywords for routing.

---

## Part 5: Auto-3 — Client Portal + Voice Enhancement

1. **Client Portal** (new dir: `client-portal/`):
   - Simple static HTML + JS (no framework)
   - Reads project data from JSON API
   - Shows: project name, phase, next steps, recent docs (Dropbox links), timeline
   - Password-protected per client (bcrypt)
   - Mobile-friendly. Docker service (nginx).

2. **Voice Receptionist Enhancement** (`voice-receptionist/`):
   - "What's the status of my project?" → phone number lookup, return status
   - "Schedule a walkthrough" → create calendar event, notify Matt
   - "Can I speak with Matt?" → forward or take message
   - Connect to email-monitor's client database for caller ID
   - Log all calls and outcomes

---

## Part 6: Auto-17 — Unified Daily Briefing

**New file: `openclaw/daily_briefing_v2.py`**

Matt receives via iMessage at 6:00 AM MT (13:00 UTC):

1. **Trading summary**: Yesterday's P/L by strategy, portfolio value, bankroll, best/worst trades, positions needing attention, paper trading results

2. **Business summary**: Unread emails (count + top 3), today's calendar events, new leads/bid invitations, follow-ups due today, Linear blocked issues

3. **System health**: All services green/yellow/red, container restarts overnight, VPN status, disk usage if >70%

4. **Intelligence**: Top signals overnight, markets with big moves, new high-volume markets

5. **Format**: Clean, scannable, bullet points, <20 lines. Link to Mission Control.

6. Schedule via heartbeat runner at 13:00 UTC. Also publish to Redis `briefing:daily`.

---

## Part 7: API-11 — Bob's Brain (Unified Context Engine)

Read `cursor-prompts/DONE/API-11-bobs-brain-unified-context.md` for the complete spec (~9KB). This is the GLUE LAYER — build it after Parts 1-6 are solid.

### 1. Context Store (`openclaw/context_store.py`)

Redis-backed state document. Any service reads or writes:
- `context_store.get("portfolio.total_value")` → reads `HGET bob:context:portfolio total_value`
- `context_store.set("portfolio.total_value", 1343.00, ttl_seconds=300)`
- `context_store.get_section("portfolio")` → `HGETALL bob:context:portfolio`

Domains: portfolio, email, calendar, project, infrastructure, intelligence, owner.

Each service writes its own domain. Back up to `data/context_snapshots/` hourly.

### 2. Decision Engine (`openclaw/decision_engine.py`)

Rules-based engine evaluating conditions against context store. Load rules from `agents/decision_rules.yml`:

- `proposal_email_detected` → trigger proposal checker
- `portfolio_drop_alert` (>10% drop in 5 min) → alert Matt, pause trades
- `calendar_reminder` (event in 30 min) → iMessage reminder
- `follow_up_due` → draft and queue follow-up emails

Evaluate every 60 seconds from main loop.

### 3. Wire into OpenClaw Main Loop

Extend (don't replace) `openclaw/main.py`:
- Every service event → update context store via `handle_event()`
- Map event types to context updates (trade_executed → portfolio.last_trade, email_received → email.pending_count +1, etc.)

### 4. CONTEXT.md Auto-Updater

Auto-generate from context store hourly. Commit + push so next Cursor session starts with fresh context.

---

## Part 8: API-12 — Profit Reinvestment Loop

Read `cursor-prompts/DONE/API-12-profit-reinvestment-loop.md` for the complete spec (~13KB).

**New file: `openclaw/treasury.py`**

### Three-Account Model (TreasuryState dataclass):
- Trading: USDC balance + position value (from Auto-21 position syncer via Redis `portfolio:snapshot`)
- Operating: reserve for monthly costs (target 2x burn rate)
- Business: receivables + deposited MTD + pipeline value

### Monthly Costs (hard-coded):
Perplexity Pro $200, D-Tools $99, OpenAI target $50, Mullvad VPN $5, Twilio $20, hosting $15 = **$389/month baseline**.

### Bankroll Auto-Scaling:
- 3 consecutive profitable weeks → scale up 10%
- 2 consecutive losing weeks → scale down 20%
- 50% of profits reinvested to bankroll, 50% to operating reserve
- If reserve already above target → 100% to bankroll

### Alert Rules:
- Reserve below $500 → high severity
- <2 months runway → high
- Monthly profit exceeds burn rate → info ("Flywheel active!")
- Portfolio crosses $2,000 → info

### API: `GET /api/treasury` — full state for Mission Control.

### Daily briefing section: Trading total + reserve + MTD net + flywheel status.

### D-Tools revenue stub: Manual entry via Redis until API-13 provides real data.

### Weekly financial report: Every Sunday 8 AM — trading P/L, business revenue, expenses, goal tracking.

---

## Part 9: API-13 — Symphony Client Lifecycle

Read `cursor-prompts/DONE/API-13-symphony-client-lifecycle.md` for the complete spec (~10KB).

**New file: `openclaw/lifecycle_coordinator.py`**

### Phase Pipeline:
`lead → proposal_sent → follow_up_active → deposit_pending → project_setup → commissioning → handoff → complete`

### Phase Actions:
- **Lead**: `client_tracker.create()`, create Linear ticket, log source
- **Proposal Sent**: `follow_up_tracker.schedule_follow_ups()` (Day 3, 7, 14), create Dropbox folder structure, log date
- **Deposit Received**: `payment_tracker.watch_deposit()`, on confirm → auto-transition to project_setup
- **Project Setup**: `follow_up_tracker.cancel_remaining()`, `project_template.create_project()` (22-issue Linear), kickoff email, iMessage Matt
- **Commissioning**: Generate checklist from system design
- **Handoff**: Access codes, concierge KB URL, support terms PDF. Watch final payment. Schedule 30-day check-in.
- **Complete**: Archive Linear project, move Dropbox to Archive, update client_tracker

### Wire Follow-Up Tracker:
Ensure methods: `schedule_follow_ups()`, `get_due_today()`, `mark_sent()`, `cancel_remaining()`. Follow-up templates: Day 3 (check-in), Day 7 (specific detail), Day 14 (final gentle nudge).

### Wire Payment Tracker:
Ensure methods: `watch_deposit()`, `check_payment_email()`, `confirm_received()`, `get_pending_payments()`, `watch_final_payment()`.

### Daily Briefing Integration:
Follow-ups due today, overdue follow-ups, pending payments, active projects by phase.

### API: `GET /api/lifecycle` — all active projects with phases.

---

## Execution Notes

- **Build order**: API-6 → Auto-9 → Auto-16 → Auto-18 → Auto-3 → Auto-17 → API-11 → API-12 → API-13
- API-11 (Brain) is the glue layer — build it AFTER individual services work
- API-13 depends on Auto-16 (proposals) and Auto-18 (Dropbox) — build those first
- **Commit each part separately**: `feat: add Hermes multi-platform messaging (API-6)`
- Use standard logging throughout (NO structlog)
- Redis at `redis://172.18.0.100:6379` inside Docker
- Dropbox creds in `.env`: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
- Push to origin main when done
