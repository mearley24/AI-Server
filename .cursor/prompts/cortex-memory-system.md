# Cortex — Symphony's Living Memory & Learning System

## Context

You are working in `~/AI-Server` on Bob (Mac Mini M4).

We have a static ops log (built by Perplexity) that documents every conversation, decision, outcome, and recurring problem from Feb 27 through Apr 4, 2026. Right now it's a standalone HTML file. This prompt turns it into a **living service** that Bob, Betty, Beatrice, and Bill read from, write to, and learn from — building neural pathways over time.

The existing architecture:
- **EventBus** (`openclaw/event_bus.py` or `openclaw/agent_bus.py`) — Redis pub/sub, channels like `events:email`, `events:trading`, `events:jobs`, `events:system`
- **ContextStore** (`openclaw/context_store.py`) — Redis hashes per domain: `bob:context:{section}`
- **DecisionEngine** (`openclaw/decision_engine.py`) — YAML rules + plugin rules, reads ContextStore
- **Knowledge Base** (`openclaw/knowledge_base.py`) — iCloud folder scanner, SQLite indexed
- **Agent Learnings** (`data/openclaw/AGENT_LEARNINGS_LIVE.md` + `AGENT_LEARNINGS.md`) — Trading knowledge
- **Orchestrator** — 5-minute tick loop calling check_emails, check_trading, check_pipeline, etc.
- **Mission Control** (`mission_control/`) — Dashboard on port 8098 with `/event` endpoint
- **Docker Compose** — 16 services, all on the same Docker network

The system already has the plumbing for events, context, and decisions. What's missing is the **memory layer** — a structured, queryable, auto-updating record of everything that's happened, what worked, what didn't, and what was learned.

---

## PART 1: The Cortex Service

Create `cortex/` as a new Docker service.

### 1a. Directory Structure

```
cortex/
├── Dockerfile
├── requirements.txt
├── server.py              # FastAPI app
├── memory_store.py        # SQLite memory engine
├── learning_engine.py     # Pattern detection & neural path formation
├── ingestion.py           # Event listener that writes to memory
├── query_engine.py        # Search & retrieval API
├── seed_data.json         # Initial seed from the Perplexity ops log
└── templates/
    └── cortex.html        # Web UI (the ops log, but live)
```

### 1b. Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8097
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8097"]
```

### 1c. requirements.txt

```
fastapi>=0.115
uvicorn>=0.34
redis>=5.0
aiohttp>=3.9
jinja2>=3.1
python-dateutil>=2.9
```

### 1d. Docker Compose Addition

Add to `docker-compose.yml`:

```yaml
  cortex:
    build:
      context: ./cortex
    container_name: cortex
    restart: unless-stopped
    ports:
      - "8097:8097"
    volumes:
      - ./data/cortex:/app/data
      - ./knowledge:/app/knowledge:ro
      - ./data/openclaw:/app/data/openclaw:ro
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## PART 2: Memory Store (The Brain's Long-Term Storage)

Create `cortex/memory_store.py`:

SQLite database at `/app/data/cortex.db` with these tables:

### Table: `entries`
The timeline — every significant event, decision, or conversation.

```sql
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,           -- ISO8601
    phase TEXT DEFAULT '',             -- "Foundation", "Building the Stack", etc.
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    details TEXT DEFAULT '',
    outcome TEXT DEFAULT 'pending',    -- success | partial | failure | pending
    problems_downstream TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',      -- manual | event_bus | agent | perplexity
    source_agent TEXT DEFAULT '',      -- bob | betty | beatrice | bill | matt | perplexity
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_entries_outcome ON entries(outcome);
CREATE INDEX IF NOT EXISTS idx_entries_phase ON entries(phase);
```

### Table: `tags`
Many-to-many tags on entries.

```sql
CREATE TABLE IF NOT EXISTS tags (
    entry_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag),
    FOREIGN KEY (entry_id) REFERENCES entries(id)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
```

### Table: `recurring_problems`
Tracked patterns that keep coming back.

```sql
CREATE TABLE IF NOT EXISTS recurring_problems (
    id TEXT PRIMARY KEY,               -- slug like "deployment-gap"
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT DEFAULT 'major',     -- critical | major | minor
    status TEXT DEFAULT 'unresolved',  -- unresolved | partially-fixed | fixed | known-workaround
    fix TEXT DEFAULT '',
    first_seen TEXT,
    last_seen TEXT,
    occurrence_count INTEGER DEFAULT 0
);
```

### Table: `problem_occurrences`
Links entries to recurring problems.

```sql
CREATE TABLE IF NOT EXISTS problem_occurrences (
    entry_id INTEGER NOT NULL,
    problem_id TEXT NOT NULL,
    PRIMARY KEY (entry_id, problem_id),
    FOREIGN KEY (entry_id) REFERENCES entries(id),
    FOREIGN KEY (problem_id) REFERENCES recurring_problems(id)
);
```

### Table: `neural_paths`
Learned connections between events — the actual "learning."

```sql
CREATE TABLE IF NOT EXISTS neural_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_pattern TEXT NOT NULL,      -- what happened (e.g., "docker build cached")
    learned_response TEXT NOT NULL,     -- what should happen (e.g., "always use --no-cache for config changes")
    confidence REAL DEFAULT 0.5,       -- 0.0 to 1.0, increases with reinforcement
    reinforcement_count INTEGER DEFAULT 1,
    category TEXT DEFAULT 'general',   -- trading | email | docker | git | client | deployment
    source_entries TEXT DEFAULT '[]',  -- JSON array of entry IDs that formed this path
    created_at TEXT DEFAULT (datetime('now')),
    last_reinforced TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_neural_category ON neural_paths(category);
CREATE INDEX IF NOT EXISTS idx_neural_confidence ON neural_paths(confidence);
```

### Table: `decisions`
Every autonomous decision the system makes, with outcome tracking.

```sql
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    employee TEXT NOT NULL,            -- bob | betty | beatrice | bill
    category TEXT NOT NULL,            -- email | trading | proposal | client | system
    action TEXT NOT NULL,              -- what was decided
    context TEXT DEFAULT '{}',         -- JSON: what info was available
    confidence REAL DEFAULT 0.5,
    outcome TEXT DEFAULT 'pending',    -- success | failure | neutral | pending
    outcome_score REAL DEFAULT 0.0,   -- -1.0 to 1.0
    neural_path_id INTEGER,           -- which neural path informed this decision
    resolved_at TEXT,
    FOREIGN KEY (neural_path_id) REFERENCES neural_paths(id)
);

CREATE INDEX IF NOT EXISTS idx_decisions_employee ON decisions(employee);
CREATE INDEX IF NOT EXISTS idx_decisions_outcome ON decisions(outcome);
```

### MemoryStore class methods:

```python
class MemoryStore:
    def __init__(self, db_path="/app/data/cortex.db"): ...

    # --- Entries ---
    def add_entry(self, entry: dict) -> int: ...
    def update_entry(self, entry_id: int, updates: dict): ...
    def get_entry(self, entry_id: int) -> dict: ...
    def search_entries(self, query: str = "", outcome: str = "", phase: str = "",
                       tags: list[str] = None, limit: int = 50, offset: int = 0) -> list[dict]: ...

    # --- Tags ---
    def add_tags(self, entry_id: int, tags: list[str]): ...
    def get_tags(self, entry_id: int) -> list[str]: ...
    def get_all_tags(self) -> list[dict]:  # [{tag, count}]

    # --- Recurring Problems ---
    def upsert_problem(self, problem: dict): ...
    def record_occurrence(self, entry_id: int, problem_id: str): ...
    def get_problems(self, severity: str = "") -> list[dict]: ...

    # --- Neural Paths ---
    def create_neural_path(self, path: dict) -> int: ...
    def reinforce_path(self, path_id: int): ...
    def get_paths(self, category: str = "", min_confidence: float = 0.0) -> list[dict]: ...
    def find_relevant_paths(self, context: str) -> list[dict]:
        """Full-text search across trigger_pattern to find applicable learnings."""

    # --- Decisions ---
    def log_decision(self, decision: dict) -> int: ...
    def resolve_decision(self, decision_id: int, outcome: str, score: float): ...
    def get_decision_stats(self, employee: str = "", days: int = 7) -> dict: ...

    # --- Stats ---
    def get_stats(self) -> dict:
        """Return counts, success rates, phase breakdown, top tags, etc."""
```

Full-text search: use SQLite FTS5 on entries(title, summary, details, problems_downstream). Create the FTS table on init:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, summary, details, problems_downstream,
    content=entries, content_rowid=id
);
```

Rebuild FTS triggers on INSERT, UPDATE, DELETE.

---

## PART 3: Event Ingestion (How Memory Forms)

Create `cortex/ingestion.py`:

Subscribe to ALL Redis event channels. When significant events occur, create entries automatically.

```python
WATCHED_CHANNELS = [
    "events:email",
    "events:trading",
    "events:jobs",
    "events:system",
    "events:clients",
    "events:documents",
    "events:knowledge",
    "agents:messages",
]
```

### Ingestion rules — which events become entries:

| Event Type | Creates Entry? | Auto-Tags |
|---|---|---|
| `email.active_client_received` | Yes | `[email, active-client, {client_name}]` |
| `email.auto_response_sent` | Yes | `[email, auto-responder, {client_name}]` |
| `email.auto_response_failed` | Yes (outcome=failure) | `[email, auto-responder, failure]` |
| `trade.executed` | No (too frequent) | — |
| `trade.alert` (whale signal, big move) | Yes | `[trading, polymarket, {category}]` |
| `trade.exit` with P/L | Yes if abs(P/L) > $5 | `[trading, exit, {win/loss}]` |
| `job.created` | Yes | `[jobs, {client_name}, new]` |
| `job.stage_changed` | Yes | `[jobs, {client_name}, {stage}]` |
| `service.down` | Yes (outcome=failure) | `[infrastructure, {service_name}, outage]` |
| `service.recovered` | Yes | `[infrastructure, {service_name}, recovery]` |
| `briefing.sent` | Yes | `[briefing, daily]` |
| `deployment.pull` | Yes | `[deployment, git]` |
| `deployment.build` | Yes | `[deployment, docker, {service}]` |
| `error.*` | Yes (outcome=failure) | `[error, {service}]` |

### Auto-detect recurring problems:

When a new failure entry is created, check if it matches any existing `recurring_problems.title` keywords. If so, auto-link via `problem_occurrences`. Increment `occurrence_count` and update `last_seen`.

Keyword matching logic:
```python
PROBLEM_KEYWORDS = {
    "deployment-gap": ["not deployed", "not pulled", "old code", "git pull", "pull.sh"],
    "email-active-client": ["CLIENT_INQUIRY", "ACTIVE_CLIENT", "miscategorized", "missed email"],
    "docker-cache": ["cached", "--no-cache", "build cached", "file changes"],
    "git-rebase-conflicts": ["rebase", "unstaged changes", "cannot pull"],
    "redis-vpn-ip": ["redis", "172.18", "vpn", "container ip"],
    "jobs-db-empty": ["jobs_created: 0", "no active job", "jobs db"],
    "silent-failures": ["silent", "try/except", "no error", "failed silently"],
}
```

### Phase detection:

Auto-assign phase based on tags and date ranges. If an entry has trading tags, it's in a trading phase. If it has email/client tags, it's in an ops phase. Keep this simple — the human can override.

---

## PART 4: Neural Path Formation (How Learning Happens)

Create `cortex/learning_engine.py`:

This is the core intelligence — it analyzes entries and decisions to form reusable "neural paths" that inform future behavior.

### 4a. Path Formation (runs every 6 hours via internal scheduler)

```python
class LearningEngine:
    def __init__(self, store: MemoryStore, redis_client): ...

    async def run_learning_cycle(self):
        """Analyze recent entries and decisions. Form or reinforce neural paths."""

        # 1. Find clusters of related failures
        recent_failures = self.store.search_entries(outcome="failure", limit=50)
        for failure in recent_failures:
            similar = self._find_similar_entries(failure)
            if len(similar) >= 2:
                # Pattern detected — form or reinforce a neural path
                path = self._extract_pattern(failure, similar)
                existing = self.store.find_relevant_paths(path["trigger_pattern"])
                if existing:
                    self.store.reinforce_path(existing[0]["id"])
                else:
                    self.store.create_neural_path(path)

        # 2. Score resolved decisions
        unresolved = self.store.get_unresolved_decisions()
        for decision in unresolved:
            outcome = await self._check_decision_outcome(decision)
            if outcome:
                self.store.resolve_decision(decision["id"], outcome["result"], outcome["score"])

        # 3. Strengthen high-confidence paths, decay unused ones
        self._decay_unused_paths(days=30)
        self._strengthen_reinforced_paths()

        # 4. Generate weekly summary if it's Sunday
        if datetime.now().weekday() == 6:
            await self._generate_weekly_learnings()
```

### 4b. Pattern extraction

When multiple failures share tags or keyword patterns, extract the root cause:

```python
def _extract_pattern(self, primary: dict, similar: list[dict]) -> dict:
    """Extract a neural path from a cluster of similar events."""
    # Find common tags
    all_tags = [set(self.store.get_tags(e["id"])) for e in [primary] + similar]
    common_tags = set.intersection(*all_tags) if all_tags else set()

    # Find common words in summaries (TF-IDF-lite)
    all_words = []
    for e in [primary] + similar:
        words = set(e["summary"].lower().split())
        all_words.append(words)
    common_words = set.intersection(*all_words) if all_words else set()

    # Build the neural path
    trigger = " + ".join(sorted(common_tags | (common_words & TECHNICAL_TERMS)))
    response = self._derive_response(primary, similar)

    return {
        "trigger_pattern": trigger,
        "learned_response": response,
        "confidence": min(0.3 + (len(similar) * 0.15), 0.95),
        "category": self._categorize(common_tags),
        "source_entries": json.dumps([e["id"] for e in [primary] + similar]),
    }
```

### 4c. Confidence decay and reinforcement

```python
def _decay_unused_paths(self, days=30):
    """Paths not reinforced in N days lose confidence."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    self.store.execute("""
        UPDATE neural_paths
        SET confidence = MAX(0.1, confidence * 0.9)
        WHERE last_reinforced < ? AND confidence > 0.1
    """, (cutoff,))

def _strengthen_reinforced_paths(self):
    """Paths reinforced 3+ times in the last week get a confidence boost."""
    # Query recent reinforcements, boost paths that keep getting validated
```

### 4d. Weekly learnings summary (sent via iMessage to Matt)

```python
async def _generate_weekly_learnings(self):
    """Generate and send weekly learning summary."""
    stats = self.store.get_stats()
    new_paths = self.store.get_paths(min_confidence=0.5)  # Recently formed
    top_problems = self.store.get_problems(severity="critical")

    summary = f"""
Cortex Weekly Report — {datetime.now().strftime('%b %d')}

Entries this week: {stats['entries_this_week']}
Success rate: {stats['success_rate_7d']}%
New neural paths formed: {len(new_paths)}

Top learnings:
"""
    for path in new_paths[:5]:
        summary += f"- {path['learned_response']} (confidence: {path['confidence']:.0%})\n"

    if top_problems:
        summary += "\nStill recurring:\n"
        for p in top_problems[:3]:
            summary += f"- {p['title']} (seen {p['occurrence_count']}x)\n"

    # Publish to notification channel for iMessage delivery
    await self._publish_notification(summary)
```

---

## PART 5: Query Engine & API

Create `cortex/query_engine.py` and wire into `cortex/server.py`:

### API Routes:

```
GET  /                          — Cortex web UI (the live ops log)
GET  /api/entries               — List entries (with search, filters, pagination)
POST /api/entries               — Create a new entry
PUT  /api/entries/{id}          — Update an entry
GET  /api/entries/{id}          — Get single entry with tags and linked problems
GET  /api/problems              — List recurring problems
GET  /api/paths                 — List neural paths (with category/confidence filters)
GET  /api/paths/relevant?q=     — Find paths relevant to a query (used by other services)
GET  /api/decisions             — List decisions with outcomes
GET  /api/stats                 — Dashboard stats
GET  /api/search?q=             — Full-text search across everything
POST /api/ingest                — Manual event ingestion (for testing)
GET  /health                    — Health check
```

### The critical endpoint — used by other services:

```
GET /api/paths/relevant?q=docker+build+cached&min_confidence=0.5
```

Returns the neural paths most relevant to the current situation. Other services call this before making decisions:

- **Email monitor** — before routing: "Have we had problems routing emails from this sender?"
- **Polymarket bot** — before entering: "What have we learned about this category?"
- **Deployment scripts** — before building: "Any known issues with this service?"
- **OpenClaw orchestrator** — each tick: "What should I watch for right now?"

---

## PART 6: Seed Data

Create `cortex/seed_data.json`:

Read the full timeline, recurring problems, and project data from `/home/user/workspace/chat-history-data.json` (Perplexity already built this) and use it as the seed. On first startup, if the DB is empty, import all entries, tags, problems, and problem occurrences from the seed.

Also seed initial neural paths from BOB_TRAINING.md's "Critical Lessons" — each lesson becomes a neural path with high initial confidence (0.85):

```python
INITIAL_NEURAL_PATHS = [
    {
        "trigger_pattern": "polymarket + both sides + same market",
        "learned_response": "ALWAYS check _active_condition_ids before any trade. Never hold opposite sides of same event.",
        "confidence": 0.95,
        "category": "trading",
    },
    {
        "trigger_pattern": "docker + env vars + config change",
        "learned_response": "ALWAYS check docker-compose.yml env vars when changing config. Env var wins over code defaults. Use --build not restart.",
        "confidence": 0.95,
        "category": "deployment",
    },
    {
        "trigger_pattern": "git pull + unstaged changes + rebase",
        "learned_response": "Use 'bash scripts/pull.sh' instead of bare 'git pull'. Never use bare git pull on AI-Server repo.",
        "confidence": 0.95,
        "category": "deployment",
    },
    {
        "trigger_pattern": "code pushed + not deployed + old code running",
        "learned_response": "After pushing to GitHub, ALWAYS pull + rebuild on Bob. No auto-deploy exists. Verify with docker logs.",
        "confidence": 0.95,
        "category": "deployment",
    },
    {
        "trigger_pattern": "redis + vpn + container ip + connection refused",
        "learned_response": "Polymarket bot uses direct container IP for Redis due to VPN routing. Verify IP after every docker compose restart. Current static IP: 172.18.0.100.",
        "confidence": 0.90,
        "category": "infrastructure",
    },
    {
        "trigger_pattern": "stale positions + resolved market + get_midpoint fails",
        "learned_response": "If price lookup fails AND position age > category stale time, clean up the position. Don't rely on price for cleanup.",
        "confidence": 0.90,
        "category": "trading",
    },
    {
        "trigger_pattern": "imessage + port 8199 + python path + permissions",
        "learned_response": "Must use /opt/homebrew/bin/python3. Needs Full Disk Access. Use PYTHONUNBUFFERED=1. REPLY_TO must be +19705193013, NOT bob@symphonysh.com.",
        "confidence": 0.90,
        "category": "infrastructure",
    },
    {
        "trigger_pattern": "version number + client facing + proposal",
        "learned_response": "Version numbers are INTERNAL ONLY. Client sees 'updated proposal' or 'the proposal'. Bob strips version numbers from all outbound materials.",
        "confidence": 0.95,
        "category": "client",
    },
    {
        "trigger_pattern": "auto_responder + import + container + silent failure",
        "learned_response": "Auto-responder lives in openclaw container. Email-monitor can't import across containers. Mount openclaw read-only into email-monitor or use HTTP API.",
        "confidence": 0.90,
        "category": "deployment",
    },
    {
        "trigger_pattern": "entry price + below 40 cents + longshot",
        "learned_response": "Below 40c entry price = 35% win rate. Minimum entry price should be 0.40. Exception: weather markets with METAR data edge.",
        "confidence": 0.85,
        "category": "trading",
    },
]
```

---

## PART 7: Wire Into Existing Services

### 7a. OpenClaw Orchestrator Integration

Edit `openclaw/orchestrator.py` — add a Cortex client that checks neural paths before decisions:

```python
import aiohttp

class CortexClient:
    """Lightweight client for querying Cortex memory."""

    def __init__(self, base_url="http://cortex:8097"):
        self.base_url = base_url

    async def get_relevant_paths(self, query: str, min_confidence: float = 0.5) -> list[dict]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(
                    f"{self.base_url}/api/paths/relevant",
                    params={"q": query, "min_confidence": min_confidence}
                ) as resp:
                    if resp.status == 200:
                        return (await resp.json()).get("paths", [])
        except Exception:
            pass
        return []

    async def log_entry(self, entry: dict) -> int | None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.post(f"{self.base_url}/api/entries", json=entry) as resp:
                    if resp.status == 200:
                        return (await resp.json()).get("id")
        except Exception:
            pass
        return None

    async def log_decision(self, decision: dict) -> int | None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.post(f"{self.base_url}/api/decisions", json=decision) as resp:
                    if resp.status == 200:
                        return (await resp.json()).get("id")
        except Exception:
            pass
        return None
```

In the orchestrator's `__init__`, add:
```python
self.cortex = CortexClient()
```

In each `check_*` method, query Cortex first:
```python
async def check_emails(self):
    # Ask Cortex what we've learned about email handling
    paths = await self.cortex.get_relevant_paths("email routing active_client")
    # paths might return: "Steve's emails get routed to project folder — check there too"
    # Use this context to inform the email check
    ...
```

### 7b. Polymarket Bot Integration

Edit the copytrade strategy's entry decision. Before placing a trade:

```python
# In the trade decision flow:
paths = await cortex.get_relevant_paths(f"polymarket {category} {market_title}")
for path in paths:
    if "AVOID" in path["learned_response"].upper() or "NEVER" in path["learned_response"].upper():
        logger.info("Cortex warns: %s — skipping trade", path["learned_response"])
        return None  # Skip this trade
    if "confidence" in path and path["confidence"] > 0.8:
        # Adjust position size based on learned patterns
        ...
```

### 7c. Mission Control Integration

Add a Cortex panel to the Mission Control dashboard. Fetch from `http://cortex:8097/api/stats` and display:
- Total memory entries
- Neural paths formed
- This week's learnings
- Top recurring problems
- Link to full Cortex UI at port 8097

---

## PART 8: The Web UI (Living Ops Log)

Create `cortex/templates/cortex.html`:

Port the existing Symphony Ops Log HTML from the Perplexity-built site, but make it LIVE:

1. All data loads from `/api/entries`, `/api/problems`, `/api/paths`, `/api/stats`
2. Add a "Neural Paths" tab showing learned patterns with confidence bars
3. Add a "Decisions" tab showing autonomous decisions and their outcomes
4. Auto-refresh every 30 seconds (configurable)
5. New entries appear at the top with a subtle highlight animation
6. Search is real-time against the FTS5 index via `/api/search`

Keep the same dark theme (charcoal #1a1d21, teal accent #4F98A3), same layout patterns, same status badges. Just make it live.

Add a manual entry form at the top (collapsed by default) so Matt can add entries directly from the UI without going through Perplexity.

---

## PART 9: Cortex Auto-Update from Perplexity Sessions

Create `cortex/perplexity_sync.py`:

When Matt has a Perplexity session and decisions are made, the session content can be POSTed to Cortex:

```
POST /api/ingest/session
{
    "date": "2026-04-05",
    "entries": [
        {
            "title": "Fixed daily briefing cron timing",
            "summary": "Changed from 7 AM to 6 AM MDT...",
            "outcome": "success",
            "tags": ["cron", "daily-briefing", "fix"]
        }
    ]
}
```

This endpoint accepts batches of entries from external sources. Perplexity (me) can push session summaries to Cortex after each conversation, keeping the log perpetually current.

---

## Verification

After building everything:

1. `docker compose build cortex`
2. `docker compose up -d cortex`
3. Check: `curl http://localhost:8097/health` → `{"status": "ok", "entries": N, "paths": N}`
4. Check: `curl http://localhost:8097/api/stats` → stats object
5. Check: `curl "http://localhost:8097/api/paths/relevant?q=docker+build"` → returns the "--no-cache" path
6. Open `http://bob.local:8097` in browser → full Cortex UI with seeded data
7. Verify event ingestion: `docker compose logs cortex --tail 20` → shows Redis subscription active
8. Verify from orchestrator: `docker compose logs openclaw --tail 20` → shows Cortex queries

Do NOT skip verification. Run each check and confirm the output before moving on.

---

## Summary

What this creates:

| Component | Purpose |
|---|---|
| **Memory Store** | SQLite with entries, tags, problems, neural paths, decisions — all searchable via FTS5 |
| **Event Ingestion** | Redis subscriber that auto-creates entries from service events |
| **Learning Engine** | Detects patterns from failures, forms neural paths, decays unused ones, strengthens validated ones |
| **Query API** | Other services ask "what have we learned about X?" before making decisions |
| **Decision Tracking** | Every autonomous decision logged with outcome tracking, feeding back into learning |
| **Web UI** | The ops log, but live — auto-updating, searchable, with neural paths and decisions tabs |
| **Seed Data** | Bootstrapped with 51 entries from Feb-Apr 2026 + 10 critical lessons from BOB_TRAINING.md |
| **Weekly Summary** | Cortex sends Matt a "what I learned this week" via iMessage every Sunday |

The result: Bob and the team don't just execute tasks — they remember what happened, learn what works, and get smarter over time. Every failure strengthens a neural path. Every success reinforces a pattern. The system develops institutional memory that persists across sessions, restarts, and refactors.
