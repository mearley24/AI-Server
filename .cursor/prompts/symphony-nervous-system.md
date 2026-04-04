# Symphony Nervous System — Wire the Entire Machine Together

## Overview
We have 16 Docker services, 5 agents, 28 OpenClaw modules, 19 trading strategies, a knowledge base with product specs/hardware/SOW blocks/templates, integrations for D-Tools/Dropbox/iCloud/Telegram/HomeAssistant/Apple Notes/X intake, email templates, tools, and a Mission Control dashboard. Every piece has been built by 49 Cursor prompts. Almost none of them talk to each other.

This prompt connects EVERYTHING into a single living system.

---

## PART 1: The Event Bus (Central Nervous System)

Create `openclaw/event_bus.py`:

```python
"""
Symphony Event Bus — Central nervous system via Redis pub/sub.
Every service publishes structured events. Any service subscribes.

Channels:
  events:email      — new/classified/routed emails
  events:trading    — trades, exits, redemptions, P&L
  events:jobs       — created, stage changed, completed
  events:calendar   — meetings, reminders
  events:system     — health, containers, alerts
  events:clients    — comms, preferences, follow-ups
  events:documents  — Dropbox uploads, SOW, proposals
  events:knowledge  — scans, new docs indexed
"""
```

Implementation:
- Class `EventBus` with async `publish(channel, event_dict)` and `subscribe(channel, callback)`
- Every event is: `{"type": "x.y", "employee": "bob|betty|beatrice|bill", "source": "service-name", "title": "Human-readable", "data": {}, "timestamp": "ISO8601"}`
- On publish: (1) Redis PUBLISH to channel, (2) LPUSH to `events:log` + LTRIM 1000, (3) POST to `http://mission-control:8098/event` (fire-and-forget, catch all errors)
- Use `REDIS_URL` env var, fall back to `redis://redis:6379`
- If Redis is unreachable, log warning and continue — never crash

---

## PART 2: Orchestrator Overhaul

Edit `openclaw/orchestrator.py`:

### 2a. Import and init EventBus
```python
from event_bus import EventBus
# In __init__:
self.bus = EventBus(redis_url=os.getenv("REDIS_URL", "redis://redis:6379"))
```

### 2b. Priority-based tick
```python
async def tick(self):
    await self._set_status("bob", "working", "Starting orchestration tick")
    
    # P1: Money
    await self.check_trading()
    
    # P2: Client-facing
    await self.check_emails()
    await self.check_followups()
    await self.check_payments()
    
    # P3: Operations
    await self.check_calendar()
    await self.check_pipeline()
    await self.sync_dtools()
    
    # P4: Maintenance
    await self.check_jobs()
    await self.scan_knowledge()
    await self.check_health()
    await self.consolidate_memories()
    
    # P5: Reporting
    await self.maybe_send_briefing()
    
    await self._set_status("bob", "idle", "")
```

### 2c. Add missing methods

**check_followups()** — Import and call `follow_up_tracker.FollowUpTracker`. Check `openclaw/follow_up_tracker.py` for the actual class/method signatures. The tracker should:
- Query jobs DB for jobs with proposals sent but no response in 3/7/14 days
- For each due follow-up, draft email using templates in `proposals/email_templates/`
- Publish `events:clients` / `client.followup_due`
- Send notification via notification-hub

**check_payments()** — Import and call `payment_tracker.PaymentTracker`. Check `openclaw/payment_tracker.py` for the actual class/method signatures. The tracker should:
- Query jobs DB for jobs awaiting payment
- Check if deposits have arrived (via email keywords or D-Tools status changes)
- Publish `events:jobs` / `job.payment_received`

### 2d. Emit events everywhere

Add `await self.bus.publish(...)` at every decision point:
- After new emails found: `events:email` / `email.new`
- After email classified: `events:email` / `email.classified`
- After D-Tools sync: `events:jobs` / `job.synced` with stats
- After job created: `events:jobs` / `job.created`
- After health check failure: `events:system` / `service.down`
- After briefing sent: `events:system` / `briefing.sent`
- After trading alert: `events:trading` / `trade.alert`
- After follow-up due: `events:clients` / `client.followup_due`
- After knowledge scan: `events:knowledge` / `knowledge.scanned`

### 2e. Employee status helper
```python
async def _set_status(self, employee, status, task):
    await self.bus.publish("events:system", {
        "type": "status_update",
        "employees": {employee: {"status": status, "current_task": task}}
    })
```

Map employees to responsibilities:
- **bob** — orchestrator, email, D-Tools, proposals, client comms
- **betty** — trading, portfolio, redemptions, P&L tracking
- **beatrice** — knowledge scanning, research, context preprocessing
- **bill** — system health, VPN guard, Docker monitoring, network

When each subsystem does work, attribute it to the right employee.

---

## PART 3: Auto-Job Lifecycle Pipeline

Edit `openclaw/dtools_sync.py`:

When a Won opportunity creates a job (the auto-create logic from activate-operations prompt), trigger a full cascade. Check each module's actual method signatures first.

After creating a job, call:

1. **Dropbox folders** — Check `openclaw/dropbox_integration.py` for the class and method. Create `Projects/[Client]/Client/`, `Projects/[Client]/Internal/`, `Projects/[Client]/Archive/`. The Client folder is shared once, files replaced in-place.

2. **Linear project** — Check `openclaw/project_template.py` for the method. Creates the 22-issue standard template (4 phases: Pre-Sale, Pre-Wire, Trim, Commissioning). Check `openclaw/linear_sync.py` for the Linear API integration.

3. **Follow-up scheduling** — Check `openclaw/follow_up_tracker.py`. Schedule Day 3 / Day 7 / Day 14 follow-ups using email templates from `proposals/email_templates/`.

4. **SOW generation** — Check `openclaw/sow_assembler.py`. If the opportunity has enough data, auto-generate an SOW from the blocks in `knowledge/sow-blocks/`.

5. **Preflight check** — Check `openclaw/preflight_check.py`. Validate the project configuration before committing.

6. **Publish event** — `events:jobs` / `job.created` with all details.

Important: Look at each file's actual code first. Some may need `self._job_mgr` or `self._memory` passed in. Some may be async, some sync. Adapt to what exists.

---

## PART 4: Trading Event Integration

The polymarket bot publishes notifications via iMessage. We also want it to emit events to the bus so Mission Control sees trading activity.

Create a lightweight file `openclaw/trading_bridge.py` that:
- Subscribes to Redis channel `notifications:trading` (if the bot publishes there)
- OR periodically fetches `http://vpn:8430/status` and `http://vpn:8430/positions`
- Emits `events:trading` events for: new positions, exits, redemptions, P&L changes
- Attributes all trading events to employee "betty"

Wire this into the orchestrator's `check_trading()` method. The existing method already fetches from the bot — add event bus publishing for any notable findings.

---

## PART 5: Daily Briefing Overhaul

Edit `openclaw/daily_briefing.py`:

### Fix runtime issues:
- Email DB path: try multiple paths (`/app/data/email-monitor/emails.db`, `/Users/bob/AI-Server/data/email-monitor/emails.db`, `/data/emails.db`)
- Phone number: `load_dotenv()` at top of file to pick up `OWNER_PHONE_NUMBER`
- Notification delivery: try `http://notification-hub:8095/send` first (inside Docker), fall back to `http://localhost:8095/send` (from crontab)

### Pull from event bus:
Instead of querying each service, pull last 24h from Redis `events:log`:
```python
import redis
r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
all_events = r.lrange("events:log", 0, -1)
# Parse JSON, filter last 24h, group by type
```

### Briefing format:
```
Symphony Smart Homes — Daily Briefing

TRADING
  Portfolio: $X (N positions)
  24h P&L: +$X
  Redeemed: $X
  Pending resolution: $X in N positions

CLIENTS  
  New emails: N (breakdown by type)
  Follow-ups due: [list]
  Payments pending: [list]

PIPELINE
  Active jobs: N
  New this week: N  
  Total pipeline value: $X

CALENDAR
  Today: [events]

SYSTEM
  Services: X/Y healthy
  Token usage: X / 500,000

---
Generated by Bob at [time]
```

### Print crontab fix for the user:
```
echo "Install this crontab:"
echo "0 12 * * * cd /Users/bob/AI-Server && set -a && source .env && set +a && /opt/homebrew/bin/python3 openclaw/daily_briefing.py >> /tmp/briefing.log 2>&1"
```
(0 12 UTC = 6 AM MDT)

---

## PART 6: Knowledge + Research Integration

### 6a. Wire knowledge scanner events
The `knowledge-scanner` Docker service runs on port 8097. In the orchestrator's `scan_knowledge()`, after scanning, publish:
- `events:knowledge` / `knowledge.new_document` for each new doc found
- `events:knowledge` / `knowledge.scan_complete` with summary

### 6b. Wire the system design graph
`knowledge/hardware/system_graph.py` has a full component compatibility engine with validation. It knows about TVs, mounts, speakers, networking, Control4 — everything. But nothing calls it.

In `openclaw/orchestrator.py`, add a method:
```python
async def validate_project_hardware(self, job_id):
    """Run system graph validation on a project's component list."""
    # Import the graph engine
    # Get components from D-Tools project
    # Run validation
    # Publish results as events:documents / doc.validation_complete
```

This doesn't need to be called every tick — only when a new job is created or a project's component list changes. Wire it into the job creation cascade.

### 6c. Wire Apple Notes indexer
`integrations/apple_notes/notes_indexer.py` exists. The launchd plist runs it on a schedule. Make sure it publishes to the knowledge base when it finds new notes:
- Check the indexer's output format
- If it writes to a DB or files, have the knowledge scanner pick them up
- Publish `events:knowledge` / `knowledge.notes_indexed`

---

## PART 7: Client Tracker + Auto-Responder

### 7a. Client tracker
`openclaw/client_tracker.py` is initialized in main.py and has API routes. Wire it deeper:
- In `check_emails()`, after classifying a client email, update the client tracker
- Track response times, communication frequency, preferences
- When a client hasn't been contacted in 14+ days, publish `events:clients` / `client.stale`

### 7b. Auto-responder
`openclaw/auto_responder.py` exists. Check its interface. Wire it so:
- Vendor emails get auto-acknowledged
- Bid invites get auto-triaged (scored, recommended bid/pass)
- Client emails that need Matt's attention get flagged via notification-hub
- Routine client questions (scheduling, status updates) get draft responses

---

## PART 8: Mission Control Event Feed

### 8a. Verify event flow
In `mission_control/event_server.py`, POST `/event` should:
1. Store in SQLite events DB
2. Broadcast via WebSocket to all connected dashboard clients
3. Update employee status if `type` is `status_update`

Verify this works. If the WebSocket broadcast isn't happening, fix it.

### 8b. Add `/api/events/recent`
New endpoint returning the last 50 events from SQLite or Redis. The dashboard can poll this on load to populate the event strip with history.

### 8c. Mission Control should also read from Redis
Add a background task in `mission_control/event_server.py` that subscribes to `events:*` Redis channels and stores incoming events. This way events from any service (not just those that POST to /event) show up on the dashboard.

---

## PART 9: Notification Hub Enhancement

The notification-hub on port 8095 sends iMessages via Bob's Mac. Verify:
- It can receive `POST /send` with `{"to": "phone_or_email", "message": "text"}`
- It routes to iMessage for phone numbers, email for email addresses
- Wire it so the event bus can trigger notifications for high-priority events

Add a notification filter in the orchestrator:
```python
HIGH_PRIORITY_EVENTS = [
    "trade.alert",
    "service.down",
    "client.followup_due",
    "job.payment_received",
]
# After every bus.publish, check if the event type is high-priority
# If so, also send via notification-hub to Matt's phone
```

---

## PART 10: Trading Strategy Activation Check

Currently active strategies: cvd_detector, flash_crash, sports_arb, stink_bid, weather_trader, strategy_manager.

Built but inactive:
- `liquidity_provider.py` — Avellaneda market maker (was for Kraken XRP/USD)
- `spread_arb.py` — cross-market spread arbitrage
- `rbi_pipeline.py` — research-backed idea pipeline
- `correlation_tracker.py` — tracks correlations between markets
- `kelly_sizing.py` — Kelly Criterion position sizing (may already be used by copytrade)

In `polymarket-bot/src/main.py`, check which strategies are started. For each inactive one, check if it has the right config/env vars to run. If it just needs to be added to the startup list, add it. If it needs config, note what's missing.

Don't enable `liquidity_provider.py` (that's Kraken, separate exchange). Focus on Polymarket strategies.

---

## Verification

After ALL changes:
```bash
docker compose build --no-cache openclaw mission-control
docker compose up -d openclaw mission-control
sleep 60

echo "=== EVENT BUS ==="
docker exec redis redis-cli LRANGE events:log 0 9

echo "=== ORCHESTRATOR ==="
docker logs openclaw 2>&1 | grep "event_bus\|publish\|tick_complete\|status_update\|job.created\|followup\|payment" | tail -20

echo "=== MISSION CONTROL ==="
docker logs mission-control 2>&1 | grep "event\|broadcast\|websocket" | tail -10

echo "=== EMPLOYEE STATUS ==="
curl -s http://localhost:8098/status | python3 -m json.tool

echo "=== JOBS ==="
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/jobs.db')
for row in conn.execute('SELECT * FROM jobs LIMIT 5'):
    print(row)
conn.close()
"
```

Expected:
- Events flowing into Redis `events:log`
- Orchestrator emitting events on every tick
- Mission Control broadcasting events via WebSocket
- Dashboard showing employees as working during tick, idle between
- Jobs created from D-Tools Won opportunities
- Follow-up tracker checking for due follow-ups
- Payment tracker watching for deposits
- Daily briefing script fixed and ready (crontab printed for user to install)
