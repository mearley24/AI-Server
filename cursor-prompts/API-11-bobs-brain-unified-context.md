# API-11: Bob's Brain — Unified Context Engine

## The Vision

Right now Bob is 16+ services that don't talk to each other. The trading bot doesn't know there's a proposal due tomorrow. The email router doesn't know the trading bot just hit a new P/L high. The daily briefing pulls from scattered sources manually. Mission Control shows health but not intelligence.

Bob's Brain is a central context engine — a single place where every service writes events and reads context, so Bob operates as ONE intelligence, not 16 dumb workers.

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

Every service publishes structured events to a central Redis stream:

```python
event = {
    "service": "polymarket-bot",
    "type": "trade_executed",
    "timestamp": "2026-04-03T16:24:35Z",
    "data": {"market": "...", "size": 1.0, "price": 0.09},
    "priority": "normal"  # low, normal, high, critical
}
```

Event types:
- `trade_executed`, `trade_exited`, `position_resolved` (trading)
- `email_received`, `email_responded`, `email_escalated` (email)
- `proposal_generated`, `proposal_sent`, `proposal_accepted` (proposals)
- `meeting_scheduled`, `meeting_reminder` (calendar)
- `service_healthy`, `service_unhealthy`, `service_restarted` (infra)
- `intel_signal`, `idea_validated`, `idea_rejected` (intel/RBI)
- `daily_briefing_sent`, `weekly_report_sent` (reporting)
- `file_synced`, `client_uploaded` (file pipeline)
- `error_critical`, `error_recoverable` (errors)

Redis Stream: `events:bus` with consumer groups per listener.

### 2. Context Store (`core/context_store.py`)

A living document in Redis that any service can read to understand the current state of everything:

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

- Updated by each service after significant events
- Any service can read `context_store.get("trading.portfolio_value")` to make decisions
- Persisted to Redis hash `bob:context` + backed up to `data/context_snapshots/` hourly

### 3. Decision Engine (`core/decision_engine.py`)

Cross-service intelligence that no single service can do alone:

a) **Trading + Business awareness**:
   - If a proposal is accepted and deposit received → reduce trading risk (preserve capital for equipment procurement)
   - If no active projects and pipeline is empty → increase trading aggression (this is the revenue stream)
   - If daily trading P/L exceeds +$50 → send Matt a celebration iMessage

b) **Email + Trading awareness**:
   - If an email mentions "Polymarket" or "trading" → flag for Matt, don't auto-respond
   - If a client emails during market hours and Bob is mid-trade → prioritize client, queue trade signals

c) **Infrastructure + Everything awareness**:
   - If VPN goes down → pause all trading immediately, alert Matt
   - If disk >85% → auto-rotate old logs, archive old paper trading reports
   - If any service crashes 3x in an hour → stop it, alert Matt, don't keep restarting

d) **Calendar + Business awareness**:
   - Morning of a client meeting → compile all project context, recent emails, pending decisions into a brief
   - If no meetings today → Bob focuses on ClawWork and trading

### 4. Natural Language Interface

Bob should be able to answer questions about himself via iMessage:

- "How's trading going?" → pulls from context_store.trading, formats a summary
- "Any emails I need to handle?" → pulls from context_store.business.pending_emails
- "System status?" → pulls from context_store.infrastructure
- "What happened overnight?" → queries event bus for last 12 hours, summarizes

Wire into the existing iMessage bridge at port 8199. When a message from Matt matches a "status query" pattern, route to the context engine instead of GPT.

### 5. CONTEXT.md Auto-Updater

The existing `CONTEXT.md` in the repo is manually maintained. Make it auto-generated:
- Every hour, dump the context store to CONTEXT.md
- Format it as readable markdown
- Git commit + push if content changed (so any Cursor session on any device has fresh context)
- This replaces manual updates and ensures CONTEXT.md is always accurate

### 6. Integration Points

- **Trading bot**: publishes trade events, reads business context for risk adjustment
- **Email monitor**: publishes email events, reads calendar context for auto-response timing
- **Calendar agent**: publishes meeting events, reads project context for meeting prep
- **Notification hub**: subscribes to high-priority events, routes to iMessage
- **Mission Control**: reads entire context store for dashboard display
- **Heartbeat**: runs the decision engine every 5 minutes
- **Intel feeds**: publishes signal events, reads trading context for relevance scoring

### 7. Docker Service

Add `bobs-brain` service to docker-compose.yml:
- Port 8096
- Depends on Redis
- Runs the event bus consumer, context store updater, and decision engine loop
- Health endpoint at `/health`
- API: `GET /context` (full context), `GET /context/{section}` (specific section), `GET /events?since=1h` (recent events)

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
