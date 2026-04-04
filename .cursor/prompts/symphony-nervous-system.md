# Symphony Nervous System — Wire Everything Together

## What This Is
We have 16 Docker services, 5 agents, 28 OpenClaw modules, 19 trading strategies, a knowledge base, integrations for D-Tools/Dropbox/iCloud/Telegram/HomeAssistant/Apple Notes, email templates, scripts, and a Mission Control dashboard. Every piece has been built. Almost none of them talk to each other.

This prompt connects everything into a single living system where:
- A new D-Tools "Won" opportunity automatically creates a job, sets up Dropbox folders, generates a project template in Linear, sends Matt a briefing, and shows up on Mission Control
- A resolved Polymarket position automatically redeems, updates the portfolio, logs to Mission Control, and if profit exceeds threshold, sends a daily P&L summary
- An incoming client email gets classified, routed, triggers follow-up scheduling, updates the client tracker, and Bob responds or flags Matt
- Every service heartbeat, every trade, every email flows through a unified event bus that Mission Control, the daily briefing, and the notification hub all consume

## Architecture: The Event Bus

Create `openclaw/event_bus.py` — a lightweight async event bus using Redis pub/sub:

```python
"""
Symphony Event Bus — Central nervous system.
Every service publishes events. Any service can subscribe.

Channels:
  events:email      — new/classified/routed emails
  events:trading    — trades executed, positions resolved, redemptions
  events:jobs       — job created, stage changed, completed
  events:calendar   — upcoming meetings, reminders
  events:system     — service health, container status, alerts
  events:clients    — client communication, preference updates
  events:documents  — Dropbox uploads, SOW generated, proposals sent
  events:briefing   — daily briefing components as they're collected
"""
```

Every event is a JSON dict:
```python
{
    "type": "trade.executed",
    "employee": "bob",
    "source": "polymarket-bot",
    "title": "Bought $5 BTC Up @ 0.45",
    "data": {...},  # service-specific payload
    "timestamp": "2026-04-04T09:30:00Z"
}
```

The bus should:
- Publish to Redis channel + POST to Mission Control `/event` endpoint
- Store last 1000 events in Redis list `events:log`
- Have a `subscribe(channel, callback)` method for other services
- Work even if Redis is down (graceful no-op)

## Task 1: Event Bus Core

Create `openclaw/event_bus.py`:
- `EventBus` class with `publish(channel, event)` and `subscribe(channel, callback)`
- Uses `redis.asyncio` pub/sub
- Auto-posts to Mission Control `http://mission-control:8098/event`
- Falls back silently on connection errors
- Persists events to `events:log` Redis list (LPUSH + LTRIM to 1000)

## Task 2: Wire the Orchestrator to Emit Events

Edit `openclaw/orchestrator.py`:

Import and initialize the EventBus in `__init__`. Then add `await self.bus.publish(...)` calls at every decision point:

### Email Events
- `events:email` / `email.new` — when new unprocessed emails are found
- `events:email` / `email.classified` — after LLM classifies (bid invite, client reply, vendor, etc.)
- `events:email` / `email.routed` — after IMAP routing
- `events:email` / `email.flagged` — when something needs Matt's attention

### Job Events
- `events:jobs` / `job.created` — when D-Tools sync creates a new job
- `events:jobs` / `job.stage_changed` — when a job moves phases
- `events:jobs` / `job.followup_due` — when follow-up tracker fires
- `events:jobs` / `job.payment_received` — when payment tracker detects deposit

### Trading Events
- `events:trading` / `trade.executed` — new position entered
- `events:trading` / `trade.exited` — position sold
- `events:trading` / `trade.redeemed` — resolved position redeemed
- `events:trading` / `trade.alert` — circuit breaker, large loss, etc.

### System Events
- `events:system` / `health.check` — periodic health check results
- `events:system` / `service.down` — when a service fails health check
- `events:system` / `briefing.sent` — daily briefing sent to Matt

### Document Events
- `events:documents` / `doc.generated` — SOW, proposal, deliverables generated
- `events:documents` / `doc.uploaded` — file pushed to Dropbox client folder
- `events:documents` / `doc.shared` — share link sent to client

## Task 3: The Conductor Loop

Edit `openclaw/orchestrator.py` tick() to add a priority-based action queue. Instead of just checking services sequentially, use a priority queue:

```python
async def tick(self):
    # Priority 1: Money — trading alerts, redemptions, payments
    await self.check_trading()
    
    # Priority 2: Client-facing — emails needing response, follow-ups due
    await self.check_emails()
    await self.check_followups()
    await self.check_payments()
    
    # Priority 3: Operations — calendar, D-Tools sync, proposals
    await self.check_calendar()
    await self.check_pipeline()
    await self.sync_dtools()
    
    # Priority 4: Maintenance — health, knowledge, memory
    await self.check_jobs()
    await self.scan_knowledge()
    await self.check_health()
    await self.consolidate_memories()
    
    # Priority 5: Reporting
    await self.maybe_send_briefing()
    
    # Publish tick summary
    await self.bus.publish("events:system", {
        "type": "orchestrator.tick_complete",
        "employee": "bob",
        "title": f"Tick complete: {self._tick_summary()}",
    })
```

Add `check_followups()` and `check_payments()` methods that call into `follow_up_tracker.py` and `payment_tracker.py`. These modules exist but were never called from the tick.

## Task 4: Auto-Job Lifecycle Pipeline

When D-Tools sync finds a "Won" opportunity and creates a job (from the activate-operations prompt), trigger a cascade:

In `openclaw/dtools_sync.py`, after creating a job:
```python
# 1. Create Dropbox project folders
from dropbox_integration import DropboxIntegration
dbx = DropboxIntegration()
await dbx.create_project_folders(client_name, project_address)

# 2. Create Linear project from template
from project_template import create_project_from_template
await create_project_from_template(job_id, client_name, project_address)

# 3. Schedule initial follow-up (Day 3 after proposal sent)
from follow_up_tracker import FollowUpTracker
tracker = FollowUpTracker(self._job_mgr)
await tracker.schedule_followup(job_id, days=3, template="follow_up_3day")

# 4. Publish event
await self.bus.publish("events:jobs", {
    "type": "job.created",
    "employee": "bob",
    "title": f"New job: {client_name} — {project_address}",
    "data": {"job_id": job_id, "value": value, "source": "dtools"},
})
```

Check each module's actual API and adjust. The key modules are:
- `openclaw/dropbox_integration.py` — `create_project_folders(client, address)`
- `openclaw/project_template.py` — `create_project_from_template(job_id, ...)`
- `openclaw/follow_up_tracker.py` — `schedule_followup(job_id, days, template)`
- `openclaw/payment_tracker.py` — `check_for_payments(job_id)`

Look at each file to understand the actual method signatures before wiring.

## Task 5: Daily Briefing Upgrade

Edit `openclaw/daily_briefing.py` to consume the event bus instead of querying each service individually:

The briefing should pull from `events:log` in Redis for the last 24 hours and compile:

```
🏠 Symphony Smart Homes — Daily Briefing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRADING
  Portfolio: $621 (28 positions)
  24h P&L: +$12.40
  Redeemed: $6.12 (1 position)
  Pending: $209 in 36 near-resolved
  
CLIENTS
  New emails: 4 (2 client, 1 vendor, 1 bid)
  Follow-ups due: Steve Topletz (Day 7)
  Payments: Waiting on $34,609 deposit
  
PIPELINE
  Active jobs: 3
  Proposals sent: 1
  Won this week: 0
  
CALENDAR
  Today: 2 meetings
  - 10:00 AM: Site walk — 84 Aspen Meadow
  - 2:00 PM: Vendor call — Snap One
  
SYSTEM
  Services: 15/16 healthy
  Uptime: 99.8%
  Token usage: 12,400 / 500,000
  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Send via notification-hub (iMessage to Matt's phone). Fix the paths:
- Email DB: use path fallback logic (try multiple paths)
- Phone number: load from .env with `load_dotenv()`
- Send via `http://notification-hub:8095/send` (when inside Docker) or `http://localhost:8095/send` (when run from crontab)

Also fix the crontab. Print this for the user:
```
Recommended crontab (0 12 * * * = 6 AM MDT):
0 12 * * * cd /Users/bob/AI-Server && set -a && source .env && set +a && /opt/homebrew/bin/python3 openclaw/daily_briefing.py >> /tmp/briefing.log 2>&1
```

## Task 6: Mission Control Event Feed

The event bus posts to Mission Control's `/event` endpoint. Mission Control already has WebSocket support. Make sure the events flow through to connected dashboard clients:

In `mission_control/event_server.py`, verify that POST `/event` broadcasts via WebSocket to all connected clients. The dashboard JS already listens for WebSocket messages and updates the event strip + employee status.

Add a new endpoint `GET /api/events/recent` that returns the last 50 events from the SQLite events DB or from Redis `events:log`. The dashboard can poll this on load to populate history.

## Task 7: Employee Status Updates

The dashboard shows bob/betty/beatrice/bill as "idle". Make them active:

In the orchestrator, update employee status based on what's happening:
```python
# At start of each check:
await self.bus.publish("events:system", {
    "type": "status_update",
    "employees": {
        "bob": {"status": "working", "current_task": "Checking emails"},
    }
})

# After each check completes, set back to idle or move to next
```

Map employees to responsibilities:
- **bob** — orchestrator, email, D-Tools, proposals, client comms
- **betty** — trading, portfolio management, redemptions, P&L
- **beatrice** — knowledge scanning, research, context preprocessing  
- **bill** — system health, VPN guard, Docker monitoring, security

When a service does work (email processed, trade executed, knowledge indexed), attribute it to the right employee.

## Verification

After all changes:
```bash
docker compose build --no-cache openclaw mission-control && docker compose up -d openclaw mission-control
sleep 30
docker logs openclaw 2>&1 | grep "event_bus\|publish\|tick_complete\|job.created\|email\." | tail -20
docker logs mission-control 2>&1 | tail -10
docker exec redis redis-cli LRANGE events:log 0 5
```

Expected:
- Events flowing into Redis `events:log`
- Mission Control receiving events via POST and broadcasting via WebSocket
- Dashboard showing employees as working/active during tick, idle between ticks
- Event strip updating in real-time
- D-Tools "Won" opportunities creating full job pipelines
