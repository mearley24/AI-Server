# Close the Gaps — symphony-next-level.md Completion

## Status Audit
The `symphony-next-level.md` prompt was partially implemented. This prompt completes what's missing. Before building anything, check if any of these files already exist locally (Cursor may have created them in a previous run but they weren't committed). If a file exists and is substantial (>50 lines with real logic), skip it and move to the next item.

## What's Confirmed Done
- `docker-compose.yml` has `PERPLEXITY_API_KEY`, `OLLAMA_HOST` env vars
- `polymarket-bot/strategies/correlation_tracker.py` exists (274 lines)
- `category_cap` logic exists in copytrade strategy
- Cortex memory system prompt exists (`.cursor/prompts/cortex-memory-system.md`) with seed data

## What's Missing — Build These

### P0: Decision Journal + Outcome Loop (Foundation for everything else)

**Create `openclaw/decision_journal.py`** (~200 lines):
```python
"""
Decision Journal — tracks every orchestrator decision with outcome scoring.
SQLite at data/decision_journal.db

Tables:
  decisions: id, timestamp, category, employee, action, context_json, 
             confidence, outcome, outcome_score, outcome_at
  
Categories: email, trading, proposal, client, system, followup, payment
"""
```
- `log_decision(category, employee, action, context, confidence)` → returns decision_id
- `update_outcome(decision_id, outcome, score)` → scores -1.0 to 1.0
- `get_recent(hours=24)` → last N decisions
- `get_accuracy(category, days=7)` → % of decisions where outcome_score > 0
- `get_weekly_summary()` → grouped by category with win/loss counts

**Wire into orchestrator.py:**
- Import DecisionJournal, init in `__init__`
- After every email classification: `journal.log_decision("email", "bob", f"Classified as {type}", {...}, confidence=85)`
- After every D-Tools sync: `journal.log_decision("jobs", "bob", f"Created job {name}", {...}, confidence=90)`
- After trading alerts: `journal.log_decision("trading", "betty", f"Alert: {msg}", {...}, confidence=75)`

**Outcome updates (critical — this is what makes learning work):**
- When a follow-up email gets a client response → `update_outcome(decision_id, "client_responded", 0.8)`
- When a trade resolves (won/lost) → `update_outcome(decision_id, "trade_won", 1.0)` or `("trade_lost", -0.5)`
- When a flagged email turns out to need action → `update_outcome(decision_id, "correctly_flagged", 1.0)`

### P0: Confidence Scoring

**Create `openclaw/confidence.py`** (~80 lines):
```python
"""
Confidence scoring — determines whether Bob acts autonomously or flags for Matt.

Bands:
  80-100: Act autonomously, notify after
  50-79:  Act, but put on Matt's review queue  
  0-49:   Flag for Matt, don't act until approved
"""
```
- `score_email_action(email_data, classification)` → confidence int
- `score_trade_alert(trade_data)` → confidence int
- `should_act(confidence)` → "autonomous" | "act_and_review" | "flag_for_approval"

Higher confidence when:
- Similar decisions in journal had good outcomes
- Client is known (in client_tracker)
- Action matches a known pattern

Lower confidence when:
- New client, no history
- Unusual email content
- Large dollar amount

**Wire into orchestrator:** Before acting on emails or client matters, check confidence. If < 50, publish event `events:system` / `needs_approval` and send notification via notification-hub instead of acting.

### P1: Pattern Engine + Weekly Learning

**Create `openclaw/pattern_engine.py`** (~150 lines):

Runs weekly (add to orchestrator with a `_last_pattern_run` check against Sunday 5 AM MT):
- Reads last 7 days from decision_journal
- Groups by category, computes:
  - Win rate per category
  - Average confidence vs actual outcome accuracy
  - Client response patterns (time of day, day of week)
  - Trading patterns (category win rates, time-of-day edges)
- Saves to `data/patterns.json`
- Sends "What I learned this week" via notification-hub to Matt's phone

Format:
```
This week I learned:
- 12 decisions logged, 9 had good outcomes (75%)
- Emails flagged as urgent were correct 90% of the time
- Trading: weather category won 8/10, crypto won 3/7
- Steve responds fastest on Tuesday mornings
```

### P1: Sentiment Engine for Trading

**Create `polymarket-bot/strategies/sentiment_engine.py`** (~120 lines):
```python
class SentimentEngine:
    """Query Perplexity or Ollama for market sentiment before entering positions."""
    
    async def check_sentiment(self, market_title: str, outcome: str, position_usd: float) -> dict:
        """Returns: {score: 0-100, reasoning: str, source: 'perplexity'|'ollama'}"""
```

- If `position_usd >= 5`: use Perplexity API (`PERPLEXITY_API_KEY` env var, model `sonar`)
- If `position_usd < 5`: use Ollama on Betty (`OLLAMA_HOST` env var, model `llama3.1:8b`)
- If both fail: return `{score: 50, reasoning: "Sentiment check unavailable", source: "none"}`
- Cache results for 30 minutes per market (dict in memory)

**Wire into `polymarket_copytrade.py`:**
After METAR/weather checks pass but before placing the order:
```python
if self._sentiment_engine:
    sentiment = await self._sentiment_engine.check_sentiment(market_title, outcome, size_usd)
    if sentiment["score"] < 30:  # Strong bearish sentiment
        # Reduce position size by 50%
    elif sentiment["score"] < 20:  # Very bearish
        # Skip the trade
```

Import and init SentimentEngine in the copytrade strategy `__init__` using env vars.

### P1: Weather Accuracy Tracker

**Create `polymarket-bot/strategies/weather_accuracy.py`** (~100 lines):

SQLite at `data/weather_accuracy.db`:
```sql
CREATE TABLE station_accuracy (
    station TEXT, forecast_horizon_hours INT, 
    predicted_temp REAL, actual_temp REAL, 
    was_correct BOOLEAN, recorded_at TEXT
);
```

- `record_forecast(station, horizon_hours, predicted, actual, correct)` — called when weather markets resolve
- `get_accuracy(station, horizon_hours=None)` → float 0-1
- `get_best_stations(min_samples=10)` → list sorted by accuracy

**Wire into copytrade:**
- On weather market resolution (redeemer or position exit), call `record_forecast`
- On weather market entry, check station accuracy. If accuracy < 0.6 for that station/horizon, reduce Kelly fraction by 50%

### P1: Cost Tracker

**Create `openclaw/cost_tracker.py`** (~100 lines):

Track all costs in SQLite `data/cost_tracker.db`:
```sql
CREATE TABLE costs (
    id INTEGER PRIMARY KEY, timestamp TEXT, category TEXT,
    description TEXT, amount REAL, currency TEXT DEFAULT 'USD'
);
```

Categories: `llm_tokens`, `trading_fees`, `trading_gas`, `trading_loss`, `trading_profit`, `operational`

- `record_cost(category, description, amount)`
- `get_weekly_summary()` → dict of totals by category
- `get_daily_pnl(days=7)` → list of daily net P&L

Wire into orchestrator:
- After each tick, log LLM token usage (from TokenTracker if it exists)
- Weekly cost summary sent with the pattern engine report

### P2: Client Scoring Pipeline

**Edit `openclaw/client_tracker.py`:**

Add a `compute_scores()` method that calculates:
- `deal_velocity`: days from first email to signed proposal (from jobs DB + email DB)
- `responsiveness`: median email response time (from email timestamps)
- `revenue_potential`: total project value from D-Tools
- `relationship_health`: contact frequency * recency * sentiment

Store in `client_scores` table. Run weekly alongside pattern engine.

### P2: Relationship Maintenance

**Add to orchestrator tick (weekly check):**
- Query client_tracker for any active client not contacted in 14+ days
- Generate a touchpoint event: `events:clients` / `client.maintenance_due`
- Send notification to Matt: "Haven't contacted [client] in [N] days — want to send a check-in?"
- Do NOT auto-send — always flag for Matt's approval

### P2: Portfolio Rebalancing Rules

**Edit `polymarket-bot/strategies/strategy_manager.py` or copytrade:**
- Weather category cap: 60% of portfolio value
- Any single market: 10% of portfolio value
- Dynamic category limits based on 7-day win rate:
  - Win rate > 60%: allow up to 40% allocation
  - Win rate 50-60%: cap at 20%
  - Win rate < 50%: cap at 10%
- Log when a trade is skipped due to rebalancing caps

### P3: Design Validator

**Create `openclaw/design_validator.py`** (~80 lines):

Wraps `knowledge/hardware/system_graph.py`:
- `validate_project(components: list)` → `{passes: [], warnings: [], failures: []}`
- Called when a new job is created from D-Tools and component data is available
- Publishes `events:documents` / `doc.validation_complete`

### P3: Mission Control — Intelligence Panels

**Edit `mission_control/main.py`:**
- Add `GET /api/intelligence` that proxies to OpenClaw's intelligence endpoint or reads from decision journal directly
- Add `GET /api/decisions/recent` returning last 20 decisions from journal

**Edit `mission_control/static/index.html`:**
- Add a "Learning" section in the System tile (or a 7th mini-tile) showing:
  - Decisions today: N
  - Avg confidence: N%
  - Latest learning: "Weather bets on Seoul resolve 2h faster than NYC"
- Pull from `/api/intelligence` or `/api/decisions/recent`

### P3: Self-Healing (basic)

**Edit `openclaw/orchestrator.py` health check:**
When a service is detected as down:
1. Log to decision journal
2. Try `httpx.post(f"http://{service}:{port}/restart")` if the service has a restart endpoint
3. If no restart endpoint, publish `events:system` / `service.down.needs_manual` with the error
4. If same service has been down 3+ times in 24h, escalate to Matt via notification-hub

Don't attempt Docker socket access — that's a security risk in containers.

## Implementation Order
1. Decision journal + confidence (P0) — do this first, everything else builds on it
2. Pattern engine + cost tracker (P1) — weekly learning layer
3. Sentiment engine + weather accuracy (P1) — immediate trading value
4. Client scoring + relationship maintenance (P2)
5. Portfolio rebalancing (P2)
6. Design validator + Mission Control panels + self-healing (P3)

## Verification
```bash
docker compose build --no-cache openclaw polymarket-bot mission-control
docker compose up -d openclaw polymarket-bot mission-control
sleep 60
docker logs openclaw 2>&1 | grep "decision_journal\|confidence\|pattern\|cost" | tail -10
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/decision_journal.db')
for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
    c = conn.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
    print(f'{t[0]}: {c} rows')
"
```
