# API-11: Bob's Brain — Unified Context Engine

## The Vision

Right now Bob is 16+ services that don't talk to each other. The trading bot doesn't know there's a proposal due tomorrow. The email router doesn't know the trading bot just hit a new P/L high. The daily briefing pulls from scattered sources manually. Mission Control shows health but not intelligence.

Bob's Brain is a central context engine — a single place where every service writes events and reads context, so Bob operates as ONE intelligence, not 16 dumb workers.

The flywheel this enables: **business revenue → funds trading capital → trading profits fund daily operations → operations help win more business → repeat.** Every service needs to be aware of where the flywheel is spinning and where it's stalling.

Read the existing code first.

## Context Files to Read First

- `openclaw/agent_bus.py` (Redis pub/sub bus — AgentBus class)
- `openclaw/orchestrator.py` (current dispatch logic)
- `openclaw/main.py` (OpenClaw entry point)

## Prompt

Build the unified context engine on top of the existing OpenClaw infrastructure:

### 1. Understand the Existing Infrastructure

Before writing any new code:
- Read `agent_bus.py` — understand the AgentBus class: what channel it uses (`agents:messages`), how publish/subscribe work, what the message envelope looks like
- Read `orchestrator.py` — understand current dispatch: what events it handles, how it routes to agents, what the agent interface expects
- Read `main.py` — understand the startup sequence and how modules are loaded
- The new context store and decision engine must extend these — not replace them

### 2. Build the Context Store (`openclaw/context_store.py`)

A living Redis-backed state document that any service can read or write:

```python
class ContextStore:
    """
    Redis hash per domain: bob:context:{domain}
    Any service can query without knowing who owns the data.
    """
    
    def get(self, path: str) -> any:
        # e.g. context_store.get("portfolio.total_value") → 1343.00
        # Split on first dot: domain=portfolio, key=total_value
        # HGET bob:context:portfolio total_value → parse JSON value
        
    def set(self, path: str, value: any, ttl_seconds: int = 300):
        # e.g. context_store.set("portfolio.total_value", 1343.00)
        # HSET bob:context:portfolio total_value json.dumps(value)
        # TTL: set expiry on the hash key (5 min default, configurable per domain)
        
    def get_section(self, section: str) -> dict:
        # e.g. context_store.get_section("portfolio") → full portfolio dict
        # HGETALL bob:context:portfolio → parse all values from JSON
        
    def update_section(self, section: str, data: dict):
        # Batch update: HMSET bob:context:{section} {k: json.dumps(v) for k,v in data.items()}
```

**Domain → Redis key mapping:**
- `portfolio` → `bob:context:portfolio`
- `email` → `bob:context:email`
- `calendar` → `bob:context:calendar`
- `project` → `bob:context:project`
- `infrastructure` → `bob:context:infrastructure`
- `intelligence` → `bob:context:intelligence`
- `owner` → `bob:context:owner`

**Each service writes its own domain.** Examples:
```python
# Trading bot writes portfolio context on every portfolio update
context_store.update_section("portfolio", {
    "portfolio_value": 1343.00,
    "available_usdc": 217.00,
    "positions_count": 47,
    "daily_pnl": 19.50,
    "last_trade": "2026-04-03T16:24:35Z",
    "strategies_active": ["copytrade", "weather", "spread_arb"]
})

# Email monitor writes email context after processing inbox
context_store.update_section("email", {
    "pending_count": 3,
    "last_checked": "2026-04-03T16:00:00Z",
    "urgent_count": 1
})
```

Back up context to `data/context_snapshots/context_{timestamp}.json` every hour. Keep last 24 snapshots.

### 3. Build the Decision Engine (`openclaw/decision_engine.py`)

Rules-based engine that evaluates conditions against the context store and emits actions:

```python
class DecisionEngine:
    def __init__(self, context_store: ContextStore, agent_bus: AgentBus):
        self.context = context_store
        self.bus = agent_bus
        self.rules = self._load_rules()  # Load from agents/decision_rules.yml
    
    def evaluate(self):
        """Run all rules. Called every 60 seconds from main loop."""
        context_snapshot = {
            section: self.context.get_section(section)
            for section in ["portfolio", "email", "calendar", "project", "infrastructure"]
        }
        for rule in self.rules:
            try:
                if rule.condition(context_snapshot):
                    rule.action(context_snapshot, self.bus)
            except Exception as e:
                log.error(f"Rule {rule.name} failed: {e}")
```

**Rules file (`agents/decision_rules.yml`):**

```yaml
rules:
  - name: proposal_email_detected
    description: "Email with proposal/quote keywords from known client → check proposal"
    condition:
      event_type: email_received
      payload_contains: [proposal, quote, pricing]
      sender_in: known_clients
    action: trigger_proposal_checker

  - name: portfolio_drop_alert
    description: "Portfolio drops >10% in 5 min → alert Matt, pause new trades"
    condition:
      metric: portfolio.daily_pnl_pct
      operator: less_than
      threshold: -0.10
    action: alert_matt_and_pause_trades

  - name: calendar_reminder
    description: "Calendar event in 30 min → send iMessage reminder"
    condition:
      metric: calendar.next_event_minutes
      operator: less_than
      threshold: 30
    action: send_meeting_reminder

  - name: follow_up_due
    description: "Follow-up due today → draft and queue follow-up email"
    condition:
      metric: project.follow_ups_due_today
      operator: greater_than
      threshold: 0
    action: draft_follow_up_emails
```

Load YAML rules at startup. The engine evaluates YAML rules in order; Python rules in `core/rules/` are auto-loaded as plugins for complex conditions.

### 4. Wire into OpenClaw Main Loop (`openclaw/main.py`)

Extend (do not replace) the existing main loop:

```python
# In main.py startup sequence (after existing initialization):
context_store = ContextStore(redis_client)
decision_engine = DecisionEngine(context_store, agent_bus)

# In the existing event loop:
# 1. Every service event → update context store
agent_bus.on_message(lambda event: context_store.handle_event(event))

# 2. Decision engine runs every 60 seconds
scheduler.add_job(decision_engine.evaluate, 'interval', seconds=60)
```

`ContextStore.handle_event(event)` maps event types to context updates:
```python
EVENT_TO_CONTEXT = {
    "trade_executed": lambda e: ("portfolio", "last_trade", e["payload"]["timestamp"]),
    "email_received": lambda e: ("email", "pending_count", "+1"),  # increment
    "proposal_sent":  lambda e: ("project", "proposals_pending", "+1"),
    "payment_received": lambda e: ("project", "payments_pending", "-1"),
}
```

### 5. Test: Publish a Mock Event, Verify Everything Fires

```bash
# Publish a mock event to the agents:messages channel
python3 -c "
import redis, json
r = redis.from_url('redis://localhost:6379')
event = {
    'service': 'email-monitor',
    'event_type': 'email_received',
    'timestamp': '2026-04-03T16:00:00Z',
    'payload': {
        'from': 'john@topletz.com',
        'subject': 'Question about the proposal',
        'body_preview': 'I had a question about the pricing and the proposal...'
    },
    'priority': 'normal'
}
r.publish('agents:messages', json.dumps(event))
print('Published')
"

# Verify context store captured it
python3 -c "
from openclaw.context_store import ContextStore
import redis
cs = ContextStore(redis.from_url('redis://localhost:6379'))
print(cs.get_section('email'))
"

# Verify decision engine would trigger proposal_email_detected rule
# (Run with --dry-run flag if implemented)
python3 -c "
from openclaw.decision_engine import DecisionEngine
# ... verify rule matches the mock event
"
```

### 6. CONTEXT.md Auto-Updater

The repo's `CONTEXT.md` is manually maintained. Auto-generate it:

```python
# Runs every hour via scheduler
def update_context_md():
    snapshot = {s: context_store.get_section(s) for s in ALL_SECTIONS}
    md = format_context_as_markdown(snapshot)
    
    current = open("CONTEXT.md").read()
    if md != current:
        open("CONTEXT.md", "w").write(md)
        subprocess.run(["git", "add", "CONTEXT.md"])
        subprocess.run(["git", "commit", "-m", f"auto: update CONTEXT.md {utc_now}"])
        subprocess.run(["git", "push"])
```

The markdown format must be human-readable — Matt should be able to open CONTEXT.md in any Cursor session and immediately understand the system state.

Use standard logging. All log messages prefixed with `[context-engine]`. Redis at `redis://172.18.0.100:6379` inside Docker.
