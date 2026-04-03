# API-11: Bob's Brain — Unified Context Engine

## The Vision

Right now Bob is 16+ services that don't talk to each other. The trading bot doesn't know there's a proposal due tomorrow. The email router doesn't know the trading bot just hit a new P/L high. The daily briefing pulls from scattered sources manually. Mission Control shows health but not intelligence.

Bob's Brain is a central context engine — a single place where every service writes events and reads context, so Bob operates as ONE intelligence, not 16 dumb workers.

The flywheel this enables: **business revenue → funds trading capital → trading profits fund daily operations → operations help win more business → repeat.** Every service needs to be aware of where the flywheel is spinning and where it's stalling.

## Context Files to Read First
- AGENTS.md (north star: 24/7 machine time)
- CONTEXT.md (current shared context approach)
- notification-hub/main.py
- openclaw/orchestrator.py
- polymarket-bot/heartbeat/runner.py
- email-monitor/main.py

## Prompt

Build the unified context engine that makes Bob self-aware:

### 1. Event Bus (`core/event_bus.py`)

**Transport: Redis pub/sub.** Use Redis because it's already running on Bob, it's lightweight, and it handles fan-out to multiple subscribers naturally. No new infrastructure required.

Every service publishes structured events to the `events:bus` Redis stream (XADD) and to the `events:pubsub` channel (PUBLISH) simultaneously — stream for durability/replay, pub/sub for real-time fan-out.

**Canonical event envelope:**
```python
event = {
    "service": "polymarket-bot",       # which service published this
    "event_type": "trade_executed",    # snake_case type (see taxonomy below)
    "timestamp": "2026-04-03T16:24:35Z",  # ISO 8601 UTC
    "payload": {                        # event-specific data
        "market": "...",
        "size": 1.0,
        "price": 0.09
    },
    "priority": "normal"               # low | normal | high | critical
}
```

Note: use `event_type` (not `type`) and `payload` (not `data`) — this is the canonical field naming across all services. Update any existing services that use the old format.

**Event taxonomy:**
- `trade_executed`, `trade_exited`, `position_resolved`, `portfolio_updated` (trading)
- `email_received`, `email_responded`, `email_escalated`, `email_classified` (email)
- `proposal_generated`, `proposal_sent`, `proposal_accepted`, `proposal_rejected` (proposals)
- `payment_received`, `payment_pending`, `deposit_confirmed` (payments)
- `follow_up_due`, `follow_up_sent`, `follow_up_overdue` (follow-ups)
- `meeting_scheduled`, `meeting_reminder`, `meeting_completed` (calendar)
- `service_healthy`, `service_unhealthy`, `service_restarted` (infra)
- `intel_signal`, `idea_validated`, `idea_rejected` (intel/RBI)
- `daily_briefing_sent`, `weekly_report_sent` (reporting)
- `file_synced`, `client_uploaded`, `proposal_uploaded` (file pipeline)
- `project_created`, `project_phase_changed`, `project_completed` (lifecycle)
- `error_critical`, `error_recoverable` (errors)

Redis Stream: `events:bus` with consumer groups per listener.  
Redis Pub/Sub channel: `events:pubsub` for real-time fan-out.  
Redis at `redis://172.18.0.100:6379` inside Docker.

**Publisher helper:**
```python
class EventBus:
    def publish(self, service: str, event_type: str, payload: dict, priority: str = "normal"):
        event = {
            "service": service,
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": payload,
            "priority": priority
        }
        # Publish to both stream (durable) and pub/sub (real-time)
        self.redis.xadd("events:bus", {"data": json.dumps(event)})
        self.redis.publish("events:pubsub", json.dumps(event))
```

**Consumer helper:**
```python
class EventConsumer:
    def __init__(self, service_name: str, event_types: list[str]):
        # Create consumer group on stream
        self.redis.xgroup_create("events:bus", service_name, id="$", mkstream=True)
    
    def listen(self, handler: callable):
        # XREADGROUP for durable processing, also SUBSCRIBE for real-time
        ...
```

### 2. Context Store (`core/context_store.py`)

A living document in Redis that any service can read to understand the current state of everything. Organized as **Redis hashes per domain** so services can read only what they need:

- `bob:context:portfolio` — trading state
- `bob:context:email` — email queue state
- `bob:context:calendar` — calendar/scheduling state
- `bob:context:project` — active project state (one hash per project + summary hash)
- `bob:context:infrastructure` — service health, disk, VPN
- `bob:context:intelligence` — signals, ideas, RBI state
- `bob:context:owner` — Matt's last active, preferences, focus mode

**Full context shape:**
```python
context = {
    "trading": {
        "portfolio_value": 1343.00,
        "available_usdc": 217.00,
        "positions_count": 47,
        "daily_pnl": 19.50,
        "last_trade": "2026-04-03T16:24:35Z",
        "strategies_active": ["copytrade", "weather", "spread_arb"],
        "alerts": ["exit_engine_stuck_ct-760c"]
    },
    "business": {
        "active_projects": [{"name": "Topletz", "status": "proposal_sent", "value": 57683}],
        "pending_emails": 3,
        "next_meeting": "2026-04-04T10:00:00",
        "proposals_pending": 1,
        "follow_ups_due_today": 1,
        "payments_pending": [{"client": "Topletz", "amount": 34609, "type": "deposit"}],
        "revenue_mtd": 0,
        "pipeline_value": 57683
    },
    "infrastructure": {
        "services_healthy": 14,
        "services_unhealthy": 2,
        "disk_usage_pct": 45,
        "vpn_status": "connected",
        "last_restart": "2026-04-03T13:18:00Z"
    },
    "intelligence": {
        "signals_today": 5,
        "ideas_pending_validation": 2,
        "top_signal": "weather edge detected in Shanghai brackets"
    },
    "owner": {
        "last_active": "2026-04-03T10:30:00",
        "notification_preference": "imessage",
        "focus_mode": false
    }
}
```

**Access API:**
```python
class ContextStore:
    def get(self, path: str) -> any:
        # e.g. context_store.get("trading.portfolio_value")
        # Reads from redis hash bob:context:{domain}
        ...
    
    def set(self, path: str, value: any):
        # e.g. context_store.set("business.pending_emails", 3)
        ...
    
    def get_section(self, section: str) -> dict:
        # e.g. context_store.get_section("trading") → full trading dict
        ...
```

- Persisted to Redis hash `bob:context` + backed up to `data/context_snapshots/` hourly
- Any service can call `context_store.get("trading.portfolio_value")` without knowing which service owns that data

### 3. Decision Engine (`core/decision_engine.py`)

**Architecture: rules-based first, ML later.**

The decision engine subscribes to the event bus and evaluates rules whenever relevant events fire. Rules are evaluated in-order; first match wins. ML scoring can be added later as a rule modifier.

**Rule evaluation loop:**
```python
# Triggered every 5 minutes by heartbeat AND on every high/critical priority event
def evaluate_rules(context: dict, recent_events: list[dict]) -> list[Action]:
    actions = []
    for rule in RULES:
        if rule.condition(context, recent_events):
            actions.append(rule.action)
    return actions
```

**Core rules:**

a) **Proposal + Project cross-service rule:**
   - `IF event_type == "email_received" AND payload contains ["proposal", "quote", "pricing"] AND project exists for sender → emit check_proposal action → proposal checker validates → notification hub alerts Matt`
   - Full cross-service flow: `email-monitor` detects proposal request → `dtools-bridge` pulls matching project → `proposal-checker` validates scope/pricing → `notification-hub` sends iMessage to Matt
   - This is the canonical example of cross-service intelligence. Wire it first.

b) **Trading + Business awareness:**
   - If a proposal is accepted and deposit received → reduce trading risk (preserve capital for equipment procurement)
   - If no active projects and pipeline is empty → increase trading aggression (this is the primary revenue stream)
   - If daily trading P/L exceeds +$50 → send Matt a celebration iMessage

c) **Email + Trading awareness:**
   - If an email mentions "Polymarket" or "trading" → flag for Matt, don't auto-respond
   - If a client emails during market hours and Bob is mid-trade → prioritize client, queue trade signals

d) **Infrastructure + Everything awareness:**
   - If VPN goes down → pause all trading immediately, alert Matt
   - If disk >85% → auto-rotate old logs, archive old paper trading reports
   - If any service crashes 3x in an hour → stop it, alert Matt, don't keep restarting

e) **Calendar + Business awareness:**
   - Morning of a client meeting → compile all project context, recent emails, pending decisions into a brief
   - If no meetings today → Bob focuses on ClawWork and trading

**Adding new rules:**
```python
# Rules live in core/rules/ as individual Python files, auto-loaded at startup
# Each rule is a dataclass: condition(context, events) → bool, action → Action
```

### 4. Natural Language Interface

Bob should be able to answer questions about himself via iMessage:

- "How's trading going?" → pulls from `bob:context:portfolio`, formats a summary
- "Any emails I need to handle?" → pulls from `bob:context:email`
- "System status?" → pulls from `bob:context:infrastructure`
- "What happened overnight?" → queries `events:bus` stream for last 12 hours, summarizes
- "Any follow-ups due?" → pulls from `bob:context:project`, lists clients needing follow-up
- "Any pending payments?" → pulls from `bob:context:project`, lists outstanding deposits

Wire into the existing iMessage bridge at port 8199. When a message from Matt matches a "status query" pattern, route to the context engine instead of GPT.

### 5. CONTEXT.md Auto-Updater

The existing `CONTEXT.md` in the repo is manually maintained. Make it auto-generated:
- Every hour, dump the context store to CONTEXT.md
- Format it as readable markdown
- Git commit + push if content changed (so any Cursor session on any device has fresh context)
- This replaces manual updates and ensures CONTEXT.md is always accurate

### 6. Integration Points

- **Trading bot**: publishes trade events, reads `bob:context:portfolio` for risk adjustment
- **Email monitor**: publishes email events, reads `bob:context:calendar` for auto-response timing
- **Calendar agent**: publishes meeting events, reads `bob:context:project` for meeting prep
- **Notification hub**: subscribes to high-priority events on `events:pubsub`, routes to iMessage
- **Mission Control**: reads entire context store via `GET /context` for dashboard display
- **Heartbeat**: runs the decision engine every 5 minutes
- **Intel feeds**: publishes signal events, reads `bob:context:portfolio` for relevance scoring
- **Client lifecycle (API-13)**: publishes project/payment/follow-up events, reads business context

### 7. Docker Service

Add `bobs-brain` service to docker-compose.yml:
- Port 8096
- Depends on Redis
- Runs the event bus consumer, context store updater, and decision engine loop
- Health endpoint at `/health`
- API:
  - `GET /context` — full context store as JSON
  - `GET /context/{section}` — specific section (trading, business, infrastructure, etc.)
  - `GET /events?since=1h` — recent events from the stream
  - `POST /events` — publish an event (for services that can't use the Python library directly)
  - `GET /rules` — list active rules and their last evaluation result

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.
