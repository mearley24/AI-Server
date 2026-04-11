# Cline Prompt M — Bob's Cortex: Persistent Brain + Self-Improvement Loop

## Mission

Build the **cortex** — Bob's persistent memory, autonomous learning engine, and self-improvement loop. The cortex unifies all of Bob's fragmented knowledge stores (AGENT_LEARNINGS.md, ideas.txt, knowledge/, heartbeat learnings, X intel, trade outcomes) into a single queryable brain that Bob consults before every decision and updates after every outcome. It also runs an autonomous improvement loop that discovers new edges, evaluates strategy performance, prunes bad ideas, and surfaces opportunities — all without Matt having to check in.

## Architecture Overview

The cortex is a new top-level service: `cortex/` with its own Docker container.
It is NOT a rewrite of existing systems — it is a **layer on top** that unifies and orchestrates them.

```
cortex/
  __init__.py
  engine.py            # CortexEngine — the main brain loop
  memory.py            # MemoryStore — persistent memory layer (SQLite)
  goals.py             # GoalTracker — tracks objectives and progress
  improvement.py       # ImprovementLoop — autonomous self-improvement
  opportunity.py       # OpportunityScanner — finds new edges
  digest.py            # DigestBuilder — builds daily/weekly summaries
  config.py            # Cortex configuration
  Dockerfile
  requirements.txt
```

## Step 1 — Memory Store (`cortex/memory.py`)

The memory store is a SQLite database at `/data/cortex/brain.db` that acts as Bob's long-term memory.

### Schema

```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    importance INTEGER DEFAULT 5,
    ttl_days INTEGER DEFAULT NULL,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT DEFAULT NULL,
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    decision_type TEXT NOT NULL,
    context TEXT NOT NULL,
    options_considered TEXT DEFAULT '[]',
    chosen_option TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    outcome TEXT DEFAULT 'pending',
    outcome_details TEXT DEFAULT '',
    outcome_recorded_at TEXT DEFAULT NULL,
    memories_consulted TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    goal_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'active',
    target_metric TEXT DEFAULT '',
    current_value TEXT DEFAULT '',
    target_value TEXT DEFAULT '',
    deadline TEXT DEFAULT NULL,
    progress_log TEXT DEFAULT '[]',
    parent_goal_id TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS improvement_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    loop_type TEXT NOT NULL,
    findings TEXT NOT NULL,
    actions_taken TEXT DEFAULT '[]',
    impact_estimate TEXT DEFAULT '',
    status TEXT DEFAULT 'proposed'
);
```

### Categories for memories

- `trading_rule` — hard rules learned from trade outcomes (replaces AGENT_LEARNINGS.md)
- `strategy_idea` — pending/active/rejected strategy ideas (replaces ideas.txt)
- `strategy_performance` — rolling performance data per strategy
- `market_pattern` — recurring patterns observed across markets
- `whale_intel` — wallet behavior patterns from copytrade
- `x_intel` — alpha signals from X intake
- `infrastructure` — system health patterns, failure modes
- `edge` — identified edges with supporting data
- `meta_learning` — learnings about how Bob learns (meta)
- `external_research` — research findings from RBI pipeline, web

### Class: MemoryStore

```python
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/data/cortex/brain.db")

class MemoryStore:
    """Bob's persistent long-term memory."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        # Execute the full schema from above
        ...

    def remember(self, category, title, content, source="", confidence=0.5, importance=5, tags=None, metadata=None, ttl_days=None):
        """Store a new memory. Returns the memory ID."""
        mem_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO memories (id, created_at, updated_at, category, title, content, source, confidence, importance, tags, metadata, ttl_days) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mem_id, now, now, category, title, content, source, confidence, importance, json.dumps(tags or []), json.dumps(metadata or {}), ttl_days)
        )
        self.conn.commit()
        return mem_id

    def recall(self, query, category=None, min_importance=0, limit=20):
        """Search memories by keyword. Returns list of dicts. Updates access_count."""
        # Full-text search on title + content
        # Filter by category if provided
        # Order by (importance DESC, relevance DESC)
        # Update access_count and last_accessed for returned results
        ...

    def get_rules(self, category="trading_rule", min_confidence=0.6):
        """Get all active rules above confidence threshold."""
        ...

    def update_confidence(self, memory_id, new_confidence, reason=""):
        """Adjust confidence of a memory based on new evidence."""
        ...

    def deprecate(self, memory_id, reason=""):
        """Mark a memory as deprecated (importance=0) instead of deleting."""
        ...

    def record_decision(self, decision_type, context, options, chosen, reasoning, memories_consulted=None):
        """Log a decision for future outcome tracking."""
        ...

    def record_outcome(self, decision_id, outcome, details=""):
        """Record the outcome of a past decision. Triggers confidence updates."""
        ...

    def get_pending_decisions(self):
        """Get decisions awaiting outcome recording."""
        ...

    def prune_expired(self):
        """Remove memories past their TTL. Called by improvement loop."""
        ...

    def get_stats(self):
        """Return memory stats: total, by category, avg confidence, etc."""
        ...
```

## Step 2 — Seed the Brain (Migration)

On first startup, the cortex must ingest existing knowledge. Create `cortex/migrate.py`:

### From AGENT_LEARNINGS.md → `trading_rule` memories

Parse AGENT_LEARNINGS.md line by line. Each data point becomes a memory:

```
Example line: "Entry <40¢: Only 35% WR (206 mkts tracked), 47% for >40¢"
→ memory(category="trading_rule", title="Avoid entries below 40 cents", content="Only 35% WR on 206 markets tracked for entries <40c vs 47% for >40c entries", confidence=0.85, importance=9, tags=["entry_price", "win_rate"])
```

Key rules to extract from the existing file:
- Entry price thresholds (<40c = 35% WR, >40c = 47% WR)
- Position sizing ($1-5 = 78% WR, >$10 = 34% WR)
- Time-of-day rules (midnight-6am = 29% WR)
- Category rules (avoid US sports/soccer, weather is best)
- Hold time patterns
- Wallet quality thresholds

### From ideas.txt → `strategy_idea` memories

Parse the `---`-delimited blocks. Each IDEA becomes a memory:
- `status: implementing` → importance=8, tags=["active"]
- `status: pending` → importance=6, tags=["pending"]
- Extract HYPOTHESIS as the content

### From polymarket-bot/knowledge/ → various categories

- `knowledge/strategies/*.md` → `strategy_performance` or `market_pattern`
- `knowledge/wallets/*.md` → `whale_intel`
- `knowledge/markets/*.md` → `market_pattern`
- `knowledge/research/*.md` → `external_research`

### From cortex/seed_data.json → `meta_learning`

The timeline entries are project history. Extract key lessons:
- "Kraken losses contaminated P/L" → infrastructure lesson
- "Code pushed but not deployed on Bob" → infrastructure lesson
- Pattern recognition across the full timeline

## Step 3 — Goal Tracker (`cortex/goals.py`)

Goals give Bob direction. They are hierarchical:

### Seed Goals

```python
SEED_GOALS = [
    {
        "title": "Maximize daily trading profit",
        "description": "Increase net daily P/L across all strategies. Current: ~$2-5/day target. Stretch: $20/day.",
        "goal_type": "financial",
        "priority": 10,
        "target_metric": "daily_net_pnl",
        "current_value": "2.00",
        "target_value": "20.00",
    },
    {
        "title": "Maintain 60%+ win rate across all strategies",
        "description": "Track resolved trade win rate. Currently variable. Target sustained 60%+.",
        "goal_type": "performance",
        "priority": 9,
        "target_metric": "overall_win_rate",
        "current_value": "0.50",
        "target_value": "0.60",
    },
    {
        "title": "Discover and validate one new edge per week",
        "description": "From X intel, research, whale watching, or pattern mining. Must be backtestable.",
        "goal_type": "growth",
        "priority": 8,
        "target_metric": "new_edges_per_week",
        "current_value": "0",
        "target_value": "1",
    },
    {
        "title": "Zero downtime on trading operations",
        "description": "Bot should trade 24/7. No missed trades due to crashes, network issues, or stale containers.",
        "goal_type": "reliability",
        "priority": 10,
        "target_metric": "uptime_percent",
        "current_value": "0.90",
        "target_value": "0.99",
    },
    {
        "title": "Reduce Matt's required intervention to zero",
        "description": "Bob should self-heal, self-tune, and self-improve without Matt needing to check in.",
        "goal_type": "autonomy",
        "priority": 9,
        "target_metric": "manual_interventions_per_week",
        "current_value": "10",
        "target_value": "0",
    },
]
```

### GoalTracker class

```python
class GoalTracker:
    def __init__(self, memory_store):
        self.memory = memory_store

    def update_progress(self, goal_id, new_value, note=""):
        """Update a goal's current value and append to progress_log."""
        ...

    def check_goals(self):
        """Review all active goals. Returns list of {goal, status, gap, recommendation}."""
        # For each goal, compare current_value to target_value
        # If regressing, flag it
        # If close to target, celebrate
        ...

    def suggest_subgoals(self, goal_id):
        """Use Ollama to suggest concrete sub-goals for a parent goal."""
        ...
```

## Step 4 — Improvement Loop (`cortex/improvement.py`)

This is the heart of the cortex. It runs on a schedule and makes Bob better over time.

### Class: ImprovementLoop

```python
class ImprovementLoop:
    """Bob's autonomous self-improvement engine."""

    def __init__(self, memory, goals, opportunity_scanner):
        self.memory = memory
        self.goals = goals
        self.scanner = opportunity_scanner

    async def run_daily_improvement(self):
        """Full daily improvement cycle. Runs at 5:30 AM MT (before heartbeat at 6 AM)."""

        findings = {}

        # 1. REVIEW: What happened in the last 24 hours?
        findings["trade_review"] = await self._review_trade_outcomes()

        # 2. LEARN: Extract lessons from outcomes
        findings["lessons"] = await self._extract_lessons(findings["trade_review"])

        # 3. EVALUATE: How are current strategies performing vs goals?
        findings["goal_progress"] = self.goals.check_goals()

        # 4. PRUNE: Deprecate bad rules/ideas with low confidence
        findings["pruned"] = self._prune_low_confidence()

        # 5. SCAN: Look for new opportunities
        findings["opportunities"] = await self.scanner.scan()

        # 6. PROPOSE: Generate improvement proposals
        findings["proposals"] = await self._generate_proposals(findings)

        # 7. ACT: Auto-execute safe proposals, queue risky ones for review
        findings["actions"] = await self._execute_safe_proposals(findings["proposals"])

        # 8. RECORD: Log this improvement cycle
        self._log_cycle(findings)

        # 9. NOTIFY: Alert Matt only if something significant
        await self._notify_if_significant(findings)

        return findings

    async def run_hourly_pulse(self):
        """Quick hourly check — is anything on fire? Any quick wins?"""
        # Check Redis for recent X intel signals
        # Check if any strategy has stopped producing trades
        # Check if bankroll is critically low
        # Check for resolution opportunities (presolution_scalp)
        ...

    async def _review_trade_outcomes(self):
        """Pull recent resolved trades, compare against predictions in decision log."""
        # Query Polymarket positions API for recently resolved
        # Match against decisions table
        # Calculate actual vs expected performance
        ...

    async def _extract_lessons(self, trade_review):
        """Use Ollama to extract actionable lessons from trade outcomes."""
        # Build prompt with recent trade data
        # Ask Ollama: "What patterns do you see? What rules should we add/modify?"
        # Store new rules as memories with initial confidence=0.5
        # Boost confidence of existing rules that are confirmed
        ...

    def _prune_low_confidence(self):
        """Deprecate memories with confidence < 0.3 and no recent access."""
        # Query memories with confidence < 0.3 and last_accessed > 14 days ago
        # Deprecate them (set importance=0)
        # Return list of pruned items for the log
        ...

    async def _generate_proposals(self, findings):
        """Use Ollama to generate concrete improvement proposals."""
        prompt = """You are Bob's self-improvement engine. Based on the following findings,
        propose specific, actionable improvements. Each proposal must have:
        - What to change
        - Why (data-backed)
        - Expected impact
        - Risk level (safe/moderate/risky)
        - Auto-executable? (yes if safe, no if risky)

        Findings:
        {findings}

        Current goals:
        {goals}

        Rules:
        - "safe" proposals: adjusting an existing parameter within tested bounds
        - "moderate" proposals: enabling a new strategy that's been backtested
        - "risky" proposals: anything that changes core trading logic or increases exposure
        """
        ...

    async def _execute_safe_proposals(self, proposals):
        """Auto-execute proposals marked as safe. Queue the rest."""
        executed = []
        queued = []
        for p in proposals:
            if p.get("risk") == "safe" and p.get("auto_executable"):
                # Execute it (e.g., update a Redis config key, adjust a parameter)
                await self._execute_proposal(p)
                executed.append(p)
            else:
                # Store in improvement_log as "proposed"
                queued.append(p)
        return {"executed": executed, "queued": queued}

    async def _notify_if_significant(self, findings):
        """Only notify Matt if something is actually important."""
        # Significant = new edge found, strategy halted, goal regressing, big win/loss
        # Do NOT notify for routine operations
        import redis.asyncio as aioredis
        r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        # Publish to notifications:cortex channel
        ...
```

## Step 5 — Opportunity Scanner (`cortex/opportunity.py`)

Scans for new money-making opportunities from all sources.

```python
class OpportunityScanner:
    """Scans all intel sources for new edges and opportunities."""

    def __init__(self, memory):
        self.memory = memory

    async def scan(self):
        """Run all scanners. Returns list of opportunities."""
        opps = []
        opps.extend(await self._scan_x_intel())
        opps.extend(await self._scan_whale_moves())
        opps.extend(await self._scan_market_inefficiencies())
        opps.extend(await self._scan_strategy_gaps())
        return opps

    async def _scan_x_intel(self):
        """Check Redis for recent X intel that hasn't been acted on."""
        # Read from polymarket:intel_signals
        # Cross-reference with existing memories
        # Flag anything new and high-confidence
        ...

    async def _scan_whale_moves(self):
        """Check if tracked whales made unusual moves."""
        # Query wallet rolling data
        # Compare against historical patterns in whale_intel memories
        ...

    async def _scan_market_inefficiencies(self):
        """Look for mispriced markets (complements don't sum to 1, stale prices, etc.)."""
        # Query Polymarket API for active markets
        # Check for pricing anomalies
        ...

    async def _scan_strategy_gaps(self):
        """Are there market categories we're not covering that we should be?"""
        # Check which categories are active
        # Compare against profitable categories in memories
        # Flag gaps (e.g., "crypto_updown" is avoided but a new pattern emerged)
        ...
```

## Step 6 — Digest Builder (`cortex/digest.py`)

Builds human-readable summaries Matt can check when he wants.

```python
class DigestBuilder:
    """Builds daily and weekly digests for Matt."""

    def __init__(self, memory, goals):
        self.memory = memory
        self.goals = goals

    async def build_daily_digest(self):
        """Build a daily summary. Saved to /data/cortex/digests/YYYY-MM-DD.md"""
        # Sections:
        # 1. P/L Summary (realized, unrealized, by strategy)
        # 2. Goal Progress (each goal with current vs target)
        # 3. New Learnings (memories added today)
        # 4. Improvement Actions (what the cortex did autonomously)
        # 5. Opportunities Found (new edges, unacted X intel)
        # 6. Alerts (anything needing Matt's attention)
        # 7. Ideas Pipeline (status of each idea in strategy_idea memories)
        ...

    async def build_weekly_digest(self):
        """Weekly rollup. Saved to /data/cortex/digests/week-YYYY-WNN.md"""
        # Sections:
        # 1. Week P/L (vs previous week)
        # 2. Goal Trend (improving/declining/flat for each goal)
        # 3. Strategy Report Card (grade each strategy A-F)
        # 4. Top Learnings (highest-importance memories from the week)
        # 5. Improvement Loop Summary (proposals made, actions taken, impact)
        # 6. Next Week Focus (what the cortex plans to work on)
        ...
```

## Step 7 — Cortex Engine (`cortex/engine.py`)

The main orchestrator. Ties everything together.

```python
class CortexEngine:
    """Bob's brain — orchestrates memory, goals, improvement, and opportunities."""

    def __init__(self):
        self.memory = MemoryStore()
        self.goals = GoalTracker(self.memory)
        self.scanner = OpportunityScanner(self.memory)
        self.improver = ImprovementLoop(self.memory, self.goals, self.scanner)
        self.digest = DigestBuilder(self.memory, self.goals)

    async def start(self):
        """Start the cortex background loops."""
        # Run migration if brain.db is empty
        if self.memory.get_stats()["total"] == 0:
            from cortex.migrate import run_migration
            await run_migration(self.memory)

        # Start background tasks
        asyncio.create_task(self._hourly_loop())
        asyncio.create_task(self._daily_loop())
        asyncio.create_task(self._weekly_loop())
        asyncio.create_task(self._redis_listener())

        logger.info("cortex_started", memories=self.memory.get_stats()["total"])

    async def _hourly_loop(self):
        """Run hourly pulse."""
        while True:
            try:
                await self.improver.run_hourly_pulse()
            except Exception as e:
                logger.error("cortex_hourly_error", error=str(e))
            await asyncio.sleep(3600)

    async def _daily_loop(self):
        """Run daily improvement at 5:30 AM MT."""
        while True:
            now = _local_now()
            # Calculate seconds until 5:30 AM MT
            target = now.replace(hour=5, minute=30, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                await self.improver.run_daily_improvement()
                await self.digest.build_daily_digest()
            except Exception as e:
                logger.error("cortex_daily_error", error=str(e))

    async def _weekly_loop(self):
        """Run weekly digest on Sunday at 6 AM MT."""
        while True:
            now = _local_now()
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0 and now.hour >= 6:
                days_until_sunday = 7
            target = (now + timedelta(days=days_until_sunday)).replace(hour=6, minute=0, second=0, microsecond=0)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            try:
                await self.digest.build_weekly_digest()
            except Exception as e:
                logger.error("cortex_weekly_error", error=str(e))

    async def _redis_listener(self):
        """Listen for events from other services and update memory in real-time."""
        r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        pubsub = r.pubsub()
        await pubsub.psubscribe(
            "polymarket:*",
            "intel:*",
            "notifications:*",
            "cortex:*",
        )

        async for msg in pubsub.listen():
            if msg["type"] not in ("pmessage",):
                continue
            try:
                channel = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
                data = json.loads(msg["data"]) if isinstance(msg["data"], (str, bytes)) else msg["data"]
                await self._process_event(channel, data)
            except Exception as e:
                logger.error("cortex_event_error", channel=str(msg.get("channel")), error=str(e))

    async def _process_event(self, channel, data):
        """Route incoming events to the appropriate memory/action."""
        if channel.startswith("polymarket:intel_signals"):
            # X intel arrived — store as memory
            self.memory.remember(
                category="x_intel",
                title=data.get("title", "X Signal"),
                content=json.dumps(data),
                source=data.get("url", "x_intake"),
                confidence=data.get("relevance", 50) / 100.0,
                importance=min(10, data.get("relevance", 50) // 10),
                tags=data.get("market_keywords", []),
            )

        elif channel.startswith("polymarket:volume"):
            # Volume spike — could indicate opportunity
            self.memory.remember(
                category="market_pattern",
                title=f"Volume spike: {data.get('market', 'unknown')}",
                content=json.dumps(data),
                source="volume_monitor",
                importance=6,
                ttl_days=7,
            )

        elif channel == "cortex:learn":
            # External service asking cortex to learn something
            self.memory.remember(
                category=data.get("category", "external_research"),
                title=data.get("title", "External Learning"),
                content=data.get("content", ""),
                source=data.get("source", "external"),
                confidence=data.get("confidence", 0.5),
                importance=data.get("importance", 5),
                tags=data.get("tags", []),
            )

    def query(self, question, context=None):
        """Other services call this to ask the cortex a question.
        Returns relevant memories + a synthesized answer via Ollama."""
        memories = self.memory.recall(question, limit=10)
        # Build prompt with memories as context
        # Ask Ollama to synthesize an answer
        # Return both raw memories and synthesized answer
        ...
```

## Step 8 — Wire into Existing Systems

### 8a. Heartbeat Integration

Edit `polymarket-bot/heartbeat/runner.py` — after the existing review cycle, publish results to cortex:

```python
# At end of run_full_review(), add:
try:
    import redis
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
    r.publish("cortex:learn", json.dumps({
        "category": "strategy_performance",
        "title": f"Heartbeat review {report['timestamp']}",
        "content": json.dumps(report, default=str),
        "source": "heartbeat",
        "confidence": 0.9,
        "importance": 7,
        "tags": ["heartbeat", "daily_review"],
    }))
except Exception as e:
    logger.error("cortex_publish_error", error=str(e))
```

### 8b. Strategy Manager Integration

Edit `polymarket-bot/strategies/strategy_manager.py` — before placing a trade, consult the cortex:

```python
# In the trade execution path, add cortex consultation:
async def _consult_cortex(self, market, strategy_name, entry_price, size):
    """Ask the cortex if this trade aligns with learned rules."""
    try:
        import redis
        r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        # Publish query and wait for response on cortex:response:{request_id}
        request_id = str(uuid.uuid4())[:8]
        r.publish("cortex:query", json.dumps({
            "request_id": request_id,
            "question": f"Should I enter {market} at {entry_price} for ${size} via {strategy_name}?",
            "context": {"market": market, "strategy": strategy_name, "entry_price": entry_price, "size": size},
        }))
        # Non-blocking — cortex will log advice but trade proceeds
        # Future: make this blocking with timeout for pre-trade gate
    except Exception:
        pass  # Cortex down should never block trading
```

### 8c. X Intel Integration

The `x_intel_processor.py` already publishes to `polymarket:intel_signals`. The cortex listens to this channel (Step 7 `_redis_listener`). No changes needed — the cortex automatically ingests X intel.

### 8d. Trade Outcome Integration

After each position resolves, publish to cortex:

```python
# In redeemer or position tracking code:
r.publish("cortex:learn", json.dumps({
    "category": "trading_rule",
    "title": f"Trade outcome: {market_title}",
    "content": f"Strategy: {strategy}, Entry: {entry_price}, Outcome: {'WIN' if won else 'LOSS'}, P/L: ${pnl}",
    "source": "trade_outcome",
    "confidence": 1.0,  # Outcomes are facts
    "importance": 8,
    "tags": [strategy, "win" if won else "loss", category],
}))
```

## Step 9 — Docker Setup

### Dockerfile (`cortex/Dockerfile`)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/cortex/
COPY ../AGENT_LEARNINGS.md /app/AGENT_LEARNINGS.md
COPY ../polymarket-bot/ideas.txt /app/ideas.txt
CMD ["python", "-m", "cortex.engine"]
```

### requirements.txt (`cortex/requirements.txt`)

```
redis>=5.0
httpx>=0.27
structlog>=24.0
```

### docker-compose.yml addition

Add to the existing `docker-compose.yml`:

```yaml
  cortex:
    build:
      context: .
      dockerfile: cortex/Dockerfile
    container_name: cortex
    restart: unless-stopped
    depends_on:
      - redis
    environment:
      - TZ=America/Denver
      - REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
      - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
      - OLLAMA_MODEL=${OLLAMA_CORTEX_MODEL:-qwen3:8b}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - CORTEX_LOG_LEVEL=${CORTEX_LOG_LEVEL:-INFO}
    volumes:
      - cortex_data:/data/cortex
      - ./AGENT_LEARNINGS.md:/app/AGENT_LEARNINGS.md:ro
      - ./polymarket-bot/ideas.txt:/app/ideas.txt:ro
      - ./polymarket-bot/knowledge:/app/knowledge:ro
    networks:
      - default
```

Add to volumes section:
```yaml
volumes:
  cortex_data:
```

## Step 10 — Cortex Query API

Add a simple HTTP API so other services can query the cortex synchronously.

In `cortex/engine.py`, add a FastAPI app alongside the background loops:

```python
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Bob's Cortex")

@app.get("/health")
async def health():
    return {"status": "alive", "memories": engine.memory.get_stats()}

@app.post("/query")
async def query(request: dict):
    """Ask the cortex a question."""
    return engine.query(request["question"], context=request.get("context"))

@app.post("/remember")
async def remember(request: dict):
    """Tell the cortex to remember something."""
    mem_id = engine.memory.remember(**request)
    return {"id": mem_id}

@app.get("/goals")
async def get_goals():
    return engine.goals.check_goals()

@app.get("/digest/today")
async def today_digest():
    return await engine.digest.build_daily_digest()

@app.get("/memories")
async def list_memories(category: str = None, limit: int = 20):
    return engine.memory.recall("", category=category, limit=limit)
```

Expose port `8100` in docker-compose.

## Implementation Order

1. Create `cortex/` directory structure
2. Implement `memory.py` with full SQLite schema and MemoryStore class
3. Implement `migrate.py` — parse AGENT_LEARNINGS.md, ideas.txt, and knowledge/ files
4. Implement `goals.py` with seed goals
5. Implement `config.py` with environment variables
6. Implement `opportunity.py`
7. Implement `improvement.py`
8. Implement `digest.py`
9. Implement `engine.py` with FastAPI + background loops
10. Create Dockerfile and requirements.txt
11. Add cortex service to docker-compose.yml (port 8100)
12. Wire heartbeat runner to publish to cortex (8a)
13. Wire strategy manager cortex consultation (8b — non-blocking initially)
14. Wire trade outcome publishing (8d)
15. Test migration: run `python -m cortex.migrate` and verify memories created
16. Test engine startup: `docker compose up cortex` and check `/health`

## Coding Rules

- All code must use `zsh`-compatible syntax in any shell commands
- Use single quotes for git commit messages
- No chained `&&` commands — split into separate lines
- Python 3.11+ syntax (match/case okay, `|` union types okay)
- Use `structlog` for all logging
- Ollama first, Claude fallback for any LLM calls
- All Redis connections must use the authenticated URL from env
- Never block trading operations — cortex failures must be caught and logged
- Use `/data/cortex/` for all persistent storage (Docker volume)

## Commit

After implementing all steps, commit and push:

```zsh
git add -A
git commit -m 'feat: cortex — persistent brain + self-improvement loop (Prompt M)

- SQLite memory store with categories, confidence tracking, TTL
- Migration from AGENT_LEARNINGS.md, ideas.txt, knowledge/ files
- Goal tracker with 5 seed goals (profit, win rate, edges, uptime, autonomy)
- Improvement loop: daily review, lesson extraction, pruning, proposals
- Opportunity scanner: X intel, whale moves, market inefficiencies
- Daily and weekly digest builder
- FastAPI query API on port 8100
- Redis event listener for real-time memory updates
- Wired into heartbeat, strategy manager, trade outcomes
- Docker service with persistent volume'
git push origin main
```
