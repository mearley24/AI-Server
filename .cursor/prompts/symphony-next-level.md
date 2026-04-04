# Symphony Next Level — The Autonomous Business

## Context
Symphony Smart Homes runs on a 16-service Docker stack ("Bob") on a Mac Mini M4, with a 64GB iMac ("Betty") as LLM worker. The nervous system prompt just wired the event bus, conductor loop, and auto-job pipeline. Everything talks to everything now.

This prompt builds the NEXT layer: intelligence that learns, predicts, and acts. Not just automation — autonomy.

CEDIA Expo 2026 is in Denver this September. D-Tools, Josh.ai, and others are showcasing AI-enhanced platforms. Symphony needs to be ahead of every integrator walking that floor. This prompt makes that happen.

---

## PART 1: Bob's Brain — Learning Memory That Compounds

The orchestrator processes emails, trades, proposals, and health checks every 5 minutes. Right now it logs and forgets. Build a learning layer.

### 1a. Decision Journal
Create `openclaw/decision_journal.py`:

Every time the orchestrator makes a decision (send follow-up, skip email, execute trade, flag for Matt), log it:
```python
@dataclass
class Decision:
    timestamp: str
    category: str  # email, trading, proposal, client, system
    action: str  # what was decided
    context: dict  # what information was available
    outcome: str  # what happened (filled in later)
    outcome_score: float  # -1 to 1 (filled in later)
    employee: str  # which agent decided
```

Store in SQLite `data/decision_journal.db`. When outcomes are known (trade resolved, client responded, proposal accepted), retroactively score the decision.

Weekly: Bob reviews the last 7 days of decisions, sends Matt a "What I learned this week" summary via iMessage:
```
This week I learned:
- Weather bets on Seoul resolve 2h faster than NYC (avg 4h vs 6h)
- Steve responds within 1h on weekday mornings, never on weekends
- D-Tools proposals with >$5K value get signed 40% faster when SOW is attached
- Crypto up/down markets under 30min have 45% win rate — still filtering correctly
```

### 1b. Pattern Recognition
Create `openclaw/pattern_engine.py`:

Runs weekly (Sunday 5 AM). Analyzes the decision journal + events log to find:
- **Client patterns**: response time by day/hour, preferred communication style, deal velocity
- **Trading patterns**: which categories win by time of day, weather station reliability, wallet quality trends
- **Operational patterns**: which services go down most, common error patterns, peak email times

Store patterns in `data/patterns.json`. The orchestrator reads patterns to inform decisions:
- Don't send follow-ups on weekends if client never responds on weekends
- Weight weather bets toward stations with highest historical accuracy
- Pre-scale resources before peak email times

### 1c. Confidence Scoring
Every orchestrator action gets a confidence score (0-100). If confidence < 50, flag for Matt instead of acting autonomously. If confidence > 80, act and notify. Between 50-80, act but put on Matt's review queue.

Track confidence accuracy over time. If Bob's 80+ confidence decisions are right 95% of the time, gradually increase the autonomy threshold.

---

## PART 2: Trading Intelligence Upgrade

### 2a. Sentiment-Enriched Trading
Create `polymarket-bot/strategies/sentiment_engine.py`:

Before entering any position, check sentiment:
- Use Perplexity API (key in .env as `PERPLEXITY_API_KEY`) to search for the market topic
- Score sentiment: bullish/bearish/neutral + confidence
- If sentiment conflicts with the copy trade signal, reduce position size or skip
- Log sentiment accuracy over time to improve weighting

Implementation:
```python
async def check_sentiment(self, market_title: str, outcome: str) -> dict:
    """Query Perplexity for real-time sentiment on a market."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {self._perplexity_key}"},
            json={
                "model": "sonar",
                "messages": [{
                    "role": "user",
                    "content": f"What is the current consensus/likelihood for: {market_title}? "
                               f"Specifically about the outcome: {outcome}. "
                               f"Give a confidence score 0-100 and brief reasoning."
                }]
            }
        )
        # Parse response, extract confidence
```

Wire this into the copytrade strategy's entry decision. Only call for positions > $5 to manage API costs. Use Ollama on Betty (free) for positions < $5.

### 2b. Weather Station Accuracy Tracker
Create `polymarket-bot/strategies/weather_accuracy.py`:

The bot already uses NOAA/METAR data. Track accuracy per station:
- After each weather market resolves, compare the NOAA forecast at entry time vs actual outcome
- Build accuracy scores per station, per forecast horizon (1h, 3h, 6h, 12h, 24h)
- Feed accuracy into position sizing: high-accuracy stations get full Kelly, low-accuracy get half
- Publish weekly accuracy report to decision journal

### 2c. Market Correlation Engine
`polymarket-bot/strategies/correlation_tracker.py` already exists. Wire it into the main loop:
- Track which markets move together
- When correlated markets diverge, that's an arbitrage signal
- Feed correlations into the strategy manager's position limits (don't overexpose to correlated bets)

### 2d. Portfolio Rebalancing
Add to position syncer: when weather category exceeds 60% of portfolio, stop new weather entries. When any single market has > 10% of portfolio value, flag for reduction. Dynamic category limits based on win rates:
- Categories with > 60% win rate: allow up to 40% allocation
- Categories with 50-60% win rate: cap at 20%
- Categories below 50%: cap at 10%

---

## PART 3: Client Intelligence

### 3a. Client Scoring Model
Enhance `openclaw/client_tracker.py`:

Score every client on:
- **Deal velocity**: days from first contact to signed proposal
- **Communication responsiveness**: average response time
- **Revenue potential**: total project value + upsell probability
- **Relationship health**: frequency of contact, sentiment of emails

Use these scores in the orchestrator:
- High-score clients get same-day responses and proactive check-ins
- Follow-up timing adapts to each client's response pattern
- Proposals include tier recommendations based on their spending pattern

### 3b. Proactive Client Outreach
In the orchestrator, add a weekly "relationship maintenance" check:
- Any active client not contacted in 14+ days: generate a touchpoint
- Past clients approaching their 1-year anniversary: send a check-in / maintenance offer
- Seasonal opportunities: pre-summer outdoor audio campaigns, pre-holiday lighting scenes

Draft the outreach using client history and preferences. Queue for Matt's review before sending.

### 3c. Proposal Intelligence
Enhance `openclaw/sow_assembler.py`:

When generating an SOW for a new project:
1. Look up similar past projects (by room count, system type, value range) from the knowledge base
2. Pre-populate with the most commonly accepted items from similar projects
3. Flag items that were frequently rejected or changed by similar clients
4. Auto-calculate pricing from D-Tools product catalog
5. Include the system graph validation results (component compatibility check)

---

## PART 4: System Design Intelligence

### 4a. Wire the System Graph
`knowledge/hardware/system_graph.py` has a full component compatibility engine. Wire it:

Create `openclaw/design_validator.py`:
```python
class DesignValidator:
    """Validates project component lists against the system graph."""
    
    async def validate_project(self, job_id: str, components: list[dict]) -> dict:
        """Run system graph validation on a project's components."""
        from knowledge.hardware.system_graph import SystemGraph
        graph = SystemGraph()
        
        # Add all components
        for comp in components:
            graph.add_component(comp)
        
        # Run validation
        report = graph.validate()
        
        # Publish results
        await self.bus.publish("events:documents", {
            "type": "doc.validation_complete",
            "title": f"Hardware validation: {len(report.passes)} pass, {len(report.warnings)} warn, {len(report.failures)} fail",
            "data": report.to_dict()
        })
        
        return report
```

Call this:
- When a new job is created from D-Tools (components come from the D-Tools API)
- When Matt sends a component list via iMessage or email
- Before generating any SOW or proposal

### 4b. Product Recommendation Engine
Create `openclaw/product_recommender.py`:

Given a room type, budget range, and client preferences, recommend the optimal product stack:
- TV: check `knowledge/hardware/tvs.json` — match by size, budget, Control4 compatibility
- Mount: check `knowledge/hardware/mounts.json` — match by VESA, weight capacity, ceiling/wall
- Networking: check `knowledge/hardware/networking.json` — calculate PoE budget, port count needed
- Audio: match from `knowledge/products/` — impedance matching, zone count

Use the system graph to validate recommendations before presenting.

### 4c. Room Package Generator
`tools/bob_build_room_packages.py` exists. Wire it into the job creation pipeline:
- When a new project has room data (from D-Tools or manual input), auto-generate room packages
- Each package: recommended products + wiring + labor estimate
- Three tiers: Essential, Recommended, Premium (like the Topletz TV packages)

---

## PART 5: Operational Intelligence

### 5a. Cost Tracking
Create `openclaw/cost_tracker.py`:

Track all costs:
- **LLM tokens**: already tracked by `TokenTracker` in main.py — publish daily summary
- **Trading costs**: fees, gas for redemptions, position losses
- **Operational costs**: Docker resource usage, API calls
- **Revenue**: trading profits, project revenue from D-Tools

Weekly P&L summary:
```
Weekly Business P&L:
  Project Revenue: $0 (no completions this week)
  Trading Revenue: +$42.50 (net after fees)
  LLM Costs: -$0.85 (12,400 tokens)
  Total: +$41.65
```

### 5b. Predictive Maintenance
In the health check, track failure patterns:
- If a service has failed 3 times in 7 days, pre-emptively restart it before the next expected failure
- If Redis memory is growing, alert before OOM
- If VPN has connectivity issues at certain times, document the pattern

### 5c. Self-Healing
When a service goes down and the orchestrator detects it:
1. Attempt restart via Docker API (mount Docker socket or use host exec)
2. If restart fails, check logs for known error patterns
3. If known pattern, apply known fix
4. If unknown, notify Matt with error context
5. Log the incident and resolution in the decision journal

---

## PART 6: Mission Control — Real-Time Intelligence Dashboard

### 6a. Add P&L chart to trading tile
The trading tile should show a mini sparkline of daily P&L over the last 30 days. Pull from the position syncer's history in Redis or from the PnL tracker data.

### 6b. Add client pipeline visualization
New tile or expanded view: show the client pipeline as a kanban-style flow:
`Prospect → Proposal Sent → Negotiation → Won → In Progress → Complete`
Pull from the jobs database. Click a stage to see the jobs in that stage.

### 6c. Add decision confidence meter
Show Bob's average confidence score for the last 24h and a mini chart of confidence over time. When confidence drops (novel situation, many unknowns), the dashboard shows it.

### 6d. Add learning feed
A scrolling feed of things Bob learned this week (from the pattern engine). Shows on Mission Control so Matt always knows what Bob is getting smarter about.

---

## Implementation Priority

Cursor should implement in this order:
1. Decision journal + confidence scoring (foundation for everything else)
2. Sentiment engine + weather accuracy tracker (immediate trading value)
3. Client scoring + proactive outreach (business development)
4. Design validator + product recommender (project efficiency)
5. Cost tracker + self-healing (operational maturity)
6. Dashboard intelligence features (visibility)

## Verification

After all changes:
```bash
docker compose build --no-cache openclaw mission-control polymarket-bot
docker compose up -d openclaw mission-control polymarket-bot
sleep 60

echo "=== DECISION JOURNAL ==="
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/decision_journal.db')
for table in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
    count = conn.execute(f'SELECT COUNT(*) FROM {table[0]}').fetchone()[0]
    print(f'{table[0]}: {count} rows')
conn.close()
"

echo "=== PATTERNS ==="
docker exec openclaw cat /app/data/patterns.json 2>/dev/null | python3 -m json.tool | head -20

echo "=== COST TRACKER ==="
docker logs openclaw 2>&1 | grep "cost_track\|token_usage\|pnl_summary" | tail -5

echo "=== SENTIMENT ==="
docker logs polymarket-bot 2>&1 | grep "sentiment" | tail -5

echo "=== LEARNING ==="
docker logs openclaw 2>&1 | grep "pattern\|learned\|confidence" | tail -10
```
