# Close the Loop — Outcome Wiring, Calibration, and Operational Hardening

## Context
Decision journal, confidence, pattern engine, cost tracker, sentiment, weather accuracy, client scoring, and health restart are all implemented. This prompt wires the **feedback loops** that make the system actually learn, and hardens operations for 24/7 reliability.

Read each existing file before editing to understand current method signatures.

---

## 1. Outcome Loop Wiring

Architecture: **Redis pub/sub callbacks** (cleanest — services already publish events, journal just subscribes).

### 1a. Create `openclaw/outcome_listener.py` (~120 lines)

A background asyncio task that subscribes to Redis event channels and calls `decision_journal.update_outcome()` when outcomes are observed:

```python
"""
Outcome Listener — subscribes to event bus and retroactively scores decisions.
Runs as a background task in the OpenClaw process.
"""
import asyncio, json, redis.asyncio as aioredis
from decision_journal import DecisionJournal

class OutcomeListener:
    def __init__(self, journal: DecisionJournal, redis_url: str):
        self.journal = journal
        self.redis_url = redis_url
    
    async def run(self):
        r = aioredis.from_url(self.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("events:email", "events:trading", "events:jobs", "events:clients")
        
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                event = json.loads(msg["data"])
                await self._process_event(event)
            except Exception:
                pass
    
    async def _process_event(self, event):
        etype = event.get("type", "")
        
        # Client replied to follow-up email
        if etype == "email.client_reply":
            # Find the most recent follow-up decision for this client
            decisions = self.journal.search_recent(
                category="followup", 
                context_contains=event.get("data", {}).get("client_name", ""),
                hours=336  # 14 days
            )
            for d in decisions:
                if not d.outcome:  # Not yet scored
                    self.journal.update_outcome(
                        d.id, "client_responded", 
                        0.8 if event.get("data", {}).get("sentiment", "neutral") != "negative" else 0.2
                    )
                    break
        
        # Trade resolved
        elif etype in ("trade.redeemed", "trade.exited"):
            data = event.get("data", {})
            pnl = data.get("pnl", 0)
            decisions = self.journal.search_recent(
                category="trading",
                context_contains=data.get("position_id", data.get("market", "")),
                hours=720  # 30 days
            )
            for d in decisions:
                if not d.outcome:
                    score = min(1.0, max(-1.0, pnl / 10))  # Normalize: +$10 = 1.0, -$10 = -1.0
                    self.journal.update_outcome(d.id, f"pnl_{pnl:+.2f}", score)
                    break
        
        # Job payment received
        elif etype == "job.payment_received":
            decisions = self.journal.search_recent(
                category="jobs",
                context_contains=event.get("data", {}).get("job_id", ""),
                hours=2160  # 90 days
            )
            for d in decisions:
                if not d.outcome:
                    self.journal.update_outcome(d.id, "payment_received", 1.0)
                    break
        
        # Email that was classified as low-priority later got flagged urgent
        elif etype == "email.escalated":
            decisions = self.journal.search_recent(
                category="email",
                context_contains=event.get("data", {}).get("subject", ""),
                hours=168  # 7 days
            )
            for d in decisions:
                if not d.outcome and "low" in d.action.lower():
                    self.journal.update_outcome(d.id, "misclassified_escalated", -0.8)
                    break
```

**Wire into OpenClaw main.py:** Start as background task alongside the orchestrator:
```python
outcome_listener = OutcomeListener(journal, redis_url)
asyncio.create_task(outcome_listener.run())
```

### 1b. Add `search_recent` to DecisionJournal

The outcome listener needs to find related decisions. Add to `decision_journal.py`:
```python
def search_recent(self, category: str, context_contains: str, hours: int = 168) -> list:
    """Find recent decisions matching category and context substring."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = self.conn.execute(
        "SELECT * FROM decisions WHERE category = ? AND context_json LIKE ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 5",
        (category, f"%{context_contains}%", cutoff)
    ).fetchall()
    return [self._row_to_decision(r) for r in rows]
```

### 1c. Emit outcome-triggering events from services

**Email monitor** — when a reply arrives to a thread that had a follow-up:
Edit `openclaw/orchestrator.py` `check_emails()`: after detecting a client reply, publish:
```python
await self.bus.publish("events:email", {
    "type": "email.client_reply",
    "data": {"client_name": sender_name, "subject": subject, "sentiment": "positive"}
})
```

**Trading** — when positions resolve:
In `check_trading()` or the trading bridge, after detecting a resolved position:
```python
await self.bus.publish("events:trading", {
    "type": "trade.redeemed",
    "data": {"position_id": pos_id, "market": title, "pnl": pnl_amount}
})
```

---

## 2. Confidence Calibration

### 2a. Rolling accuracy feedback

Edit `openclaw/confidence.py` — add a method that reads from the decision journal to adjust scores:

```python
def calibrate(self, journal: DecisionJournal):
    """Update confidence baselines from journal outcomes."""
    self._category_accuracy = {}
    for category in ["email", "trading", "jobs", "followup", "client"]:
        accuracy = journal.get_accuracy(category, days=30)
        if accuracy is not None:
            self._category_accuracy[category] = accuracy
```

Then in scoring methods, adjust:
```python
def score_email_action(self, email_data, classification):
    base = self._heuristic_score(email_data, classification)
    # If our email decisions have been 90% accurate, boost confidence
    # If only 50% accurate, reduce it
    historical = self._category_accuracy.get("email", 0.7)
    adjustment = (historical - 0.7) * 20  # ±0 at 70%, +6 at 100%, -14 at 0%
    return max(0, min(100, int(base + adjustment)))
```

Call `calibrate()` once per tick (it's a fast DB query):
```python
# In orchestrator tick, before processing:
self.confidence.calibrate(self.journal)
```

---

## 3. Pattern Engine — Richer Learning

### 3a. Store timestamps for client response patterns

Edit `openclaw/pattern_engine.py` `_analyze_clients()`:

Query the email DB for client emails with timestamps:
```python
# For each known client, get their email timestamps
# Group by: hour_of_day, day_of_week
# Find: preferred response window (e.g., "Tuesday 9-11 AM")
# Store in patterns.json: {"clients": {"Steve Topletz": {"best_day": "Tuesday", "best_hour": 9, "avg_response_hours": 2.5}}}
```

Only need timestamps from the email DB — no full text storage required.

### 3b. Richer weekly summary

The "What I learned" message should include:
```
This week (Apr 1-7):
━━━━━━━━━━━━━━━━━━
Decisions: 84 logged, 61 scored (73%)
Accuracy: 78% (up from 72% last week)

By category:
  Trading: 45 decisions, 82% accurate — weather leads at 91%
  Email: 28 decisions, 71% — 2 misclassified (low→urgent)
  Client: 11 decisions, 82%

Patterns found:
  • Steve responds fastest Tue-Thu 8-10 AM MT
  • Weather bets: Seoul station 94% accurate, NYC 71% — adjusting Kelly
  • Crypto up/down under 30min: 45% win rate, correctly filtering

Costs:
  LLM tokens: $1.20 (14,200 tokens)
  Trading P&L: +$32.50 net
  Gas fees: $0.45
```

---

## 4. Unified Event Bus

**Keep both Redis pub/sub AND HTTP notification-hub.** They serve different purposes:
- **Redis pub/sub** (`events:*`): machine-to-machine, internal services, high-volume, fire-and-forget
- **Notification-hub** (`POST /send`): human-facing alerts, iMessage/Telegram delivery

The orchestrator should:
1. Always publish to Redis event bus (for Mission Control, outcome listener, logging)
2. For high-priority events, ALSO send via notification-hub (for Matt's phone)

No changes needed — just make sure both paths fire for `needs_approval`, `service.down`, `trade.alert`, and `client.followup_due` events. Check orchestrator code and add notification-hub calls where missing.

---

## 5. Design Validation on Job Creation

**Manual trigger only for now.** D-Tools API returns opportunity metadata (name, value, status) but not component-level BOM data. The component list only exists in D-Tools Cloud's proposal export.

Add to OpenClaw API:
```python
@app.post("/intelligence/validate-design")
async def validate_design_manual(components: list[dict]):
    """Manual trigger — Matt pastes or uploads a component list."""
    from design_validator import DesignValidator
    validator = DesignValidator()
    return validator.validate_project(components)
```

Future: when browser_agent can scrape D-Tools project pages, auto-extract components.

---

## 6. Weather Accuracy — Resolution Recording

**Wire into the redeemer.** After `redeemer_redeemed` event for a weather market:

Edit `polymarket-bot/strategies/polymarket_copytrade.py` or create a hook in the redeemer loop:

```python
# After a weather position resolves:
if "temperature" in position.question.lower() or "weather" in position.question.lower():
    from strategies.weather_accuracy import WeatherAccuracy
    wa = WeatherAccuracy()
    # Extract station from market title (e.g., "Seoul" → RKSS, "NYC" → KJFK)
    station = wa.extract_station(position.question)
    if station:
        wa.record_forecast(
            station=station,
            horizon_hours=wa.estimate_horizon(position.entered_at),
            predicted_temp=position.outcome_temp,  # from market title parsing
            actual_temp=None,  # filled by METAR lookup at resolution time
            correct=(position.pnl > 0)
        )
```

The simplest path: just record `correct=True/False` based on whether the position was won or lost. Skip the actual temp comparison for now — win/loss already tells you if the forecast was right.

---

## 7. Human Approval UX

**iMessage reply-based approval (simplest, already works):**

When Bob sends a `needs_approval` notification:
```
[Needs approval] Draft follow-up to Steve Topletz (Day 7)
Reply YES to send, NO to skip, or EDIT with changes.
Decision ID: dec_abc123
```

The iMessage bridge (in the tmux workspace) already receives replies. Add a handler:
```python
# In scripts/imessage-server.py message handler:
if message.lower().startswith("yes") and "dec_" in context:
    # Execute the queued action
    publish_to_redis("events:system", {"type": "approval.granted", "decision_id": context_id})
elif message.lower().startswith("no"):
    publish_to_redis("events:system", {"type": "approval.denied", "decision_id": context_id})
```

The orchestrator's outcome listener picks up `approval.granted` / `approval.denied` and executes or cancels the action.

**Future (not now):** iOS Shortcut that reads from a web endpoint and shows approve/reject buttons. The Mission Control dashboard could also have an approval queue panel.

---

## 8. Operational Hardening

### 8a. SQLite Backup

Create `scripts/backup-data.sh`:
```bash
#!/bin/bash
BACKUP_DIR=~/AI-Server/backups/$(date +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"
for db in data/decision_journal.db data/cost_tracker.db data/openclaw/jobs.db data/openclaw/openclaw_memory.db data/email-monitor/emails.db data/mission-control/events.db data/polymarket/weather_accuracy.db; do
    [ -f "$db" ] && cp "$db" "$BACKUP_DIR/$(basename $db)"
done
find ~/AI-Server/backups -maxdepth 1 -mtime +7 -exec rm -rf {} \;
echo "Backed up to $BACKUP_DIR"
```

Add to crontab: `0 4 * * * /Users/bob/AI-Server/scripts/backup-data.sh >> /tmp/backup.log 2>&1`
(4 AM UTC = 10 PM MDT — low activity window)

### 8b. Docker Compose Health Dependencies

In `docker-compose.yml`, ensure services that need Redis wait for it:
```yaml
openclaw:
  depends_on:
    redis:
      condition: service_healthy
```

Add a health check to Redis if it doesn't have one:
```yaml
redis:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 3s
    retries: 3
```

### 8c. Resource Limits

Add to `docker-compose.yml` for the bot (it's the heaviest):
```yaml
polymarket-bot:
  deploy:
    resources:
      limits:
        memory: 2G
      reservations:
        memory: 512M
```

### 8d. Redis Persistence

Redis currently loses data on restart. Add a redis.conf:

Create `redis/redis.conf`:
```
save 300 1
save 60 100
appendonly yes
appendfsync everysec
maxmemory 512mb
maxmemory-policy allkeys-lru
```

Mount it in docker-compose:
```yaml
redis:
  volumes:
    - redis_data:/data
    - ./redis/redis.conf:/usr/local/etc/redis/redis.conf
  command: redis-server /usr/local/etc/redis/redis.conf
```

### 8e. Alerting for Silent Failures

Add to orchestrator health check: if ANY of these haven't produced an event in 2 hours, alert:
- email-monitor (should scan every 60s)
- polymarket-bot (should tick every 5min)
- calendar-agent (should check every 30min)

```python
async def check_silent_services(self):
    """Alert if expected services go quiet."""
    r = redis.from_url(self.redis_url)
    events = r.lrange("events:log", 0, 200)
    # Parse timestamps, group by source
    # If any expected source has no events in 2h, alert
```

---

## Bring-Up Checklist (in order)

### Minimum Viable Online (5 services)
```bash
cd ~/AI-Server
docker compose up -d redis
sleep 3
docker compose up -d vpn
sleep 5
docker compose up -d polymarket-bot
docker compose up -d openclaw
docker compose up -d mission-control
```
Verify: `curl -s localhost:8098/health && curl -s localhost:8098/api/services | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"healthy\"]}/{d[\"total\"]} healthy')"`

### Full Stack
```bash
docker compose up -d
```
Services start in dependency order if `depends_on` with health checks are set. Redis must be healthy before anything else.

### Health Verification
```bash
curl -s localhost:8098/health          # Mission Control
curl -s localhost:8098/api/services    # All service health
curl -s localhost:8098/api/intelligence # Decision journal + patterns
curl -s localhost:8098/status          # Employee status + connections
docker exec redis redis-cli LRANGE events:log 0 2  # Event bus flowing
```

### Common Mac + Docker Failures
- **VPN DNS**: polymarket-bot uses `network_mode: service:vpn` — if VPN container restarts, bot loses network. Fix: `docker restart polymarket-bot` after VPN restart
- **Redis IP drift**: bot connects via container IP (172.18.0.x) not hostname. After compose restart, IP may change. Fix: use `redis` hostname in compose network, or re-check IP with `docker inspect redis | grep IPAddress`
- **Port 3000 conflict**: Open WebUI and OpenClaw both want 3000 internally. Map OpenClaw to 8099 externally.
- **host.docker.internal**: works on Docker Desktop for Mac. If using Lima/Colima, add `extra_hosts: ["host.docker.internal:host-gateway"]`
- **Disk pressure**: polymarket-bot logs can grow. Add `logging: { driver: json-file, options: { max-size: "50m", max-file: "3" } }` to heavy services

## Verification After All Changes
```bash
docker compose build --no-cache openclaw
docker compose up -d openclaw
sleep 60
docker logs openclaw 2>&1 | grep "outcome_listener\|calibrate\|pattern\|backup\|silent_service" | tail -15
docker exec redis redis-cli LRANGE events:log 0 5
```
