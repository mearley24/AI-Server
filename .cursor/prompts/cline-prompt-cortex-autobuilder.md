# Cline Prompt: Autonomous Cortex Builder + X Bookmark Organization

## Objective

Build an autonomous research loop where Bob generates questions, Betty (Ollama LLM — free, local) researches and answers them, and the results flow into the Cortex as permanent knowledge. Also wire up X bookmark folder parsing so Matt's categorized bookmarks become structured Cortex memories.

Three deliverables:
1. **Cortex Auto-Builder daemon** — Bob asks, Betty answers via Ollama, knowledge stored
2. **X Bookmark Folder Organizer** — parse exported bookmark folders into categories, ingest into Cortex
3. **Wire both into Docker Compose** as new services

---

## Part 1: Cortex Auto-Builder (`integrations/cortex_autobuilder/`)

### Architecture

```
                    cortex_autobuilder daemon
                           |
    +----------------------+----------------------+
    |                                             |
    v                                             v
 Question Generator                        Research Executor
 (reads Cortex gaps,                       (Ollama via LLM Router)
  trading positions,                              |
  recent X intel)                                 v
    |                                     Answer Validator
    v                                     (quality check)
 Question Queue                                   |
 (Redis list:                                     v
  cortex:research_queue)                  Cortex /remember
                                          (store as knowledge)
```

### Files to Create

#### `integrations/cortex_autobuilder/__init__.py`
Empty.

#### `integrations/cortex_autobuilder/question_generator.py`

```python
"""Generate research questions by analyzing Cortex gaps and current context."""
```

Implement class `QuestionGenerator`:

- `__init__(self, cortex_url, redis_url)` — store config
- `async def generate_questions(self) -> list[dict]` — main method, returns list of question dicts

Question generation strategy:
1. **GET `{CORTEX_URL}/memories?category=trading_rule&limit=50`** — find what Bob already knows
2. **GET `{CORTEX_URL}/memories?category=x_intel&limit=20`** — recent X intel
3. **GET `{CORTEX_URL}/goals`** — active goals
4. For each gap/goal, generate 1-3 research questions

Question categories:
- `trading_strategy` — "What is the optimal Kelly criterion sizing for prediction markets with binary outcomes?"
- `market_mechanics` — "How does Polymarket's CLOB order book handle negative risk positions?"
- `risk_management` — "What are the best practices for hedging correlated prediction market positions?"
- `tech_infrastructure` — "What are the performance characteristics of Ollama vs vLLM for local inference?"
- `smart_home` — "What is the correct wire gauge for low-voltage Control4 keypads over 100ft runs?"
- `business` — "What are the most effective client acquisition channels for smart home integrators?"

Each question dict:
```python
{
    "question": "...",
    "category": "trading_strategy",
    "context": "Related to active goal: improve copytrade detection",
    "priority": 7,  # 1-10
    "source": "gap_analysis"  # or "goal_driven", "x_intel_followup", "scheduled_topic"
}
```

Also implement **scheduled topic rotation** — cycle through domains daily:
- Monday: trading strategies
- Tuesday: market mechanics and arbitrage
- Wednesday: risk management and treasury
- Thursday: AI infrastructure and automation
- Friday: smart home technical knowledge
- Saturday: business development and client services
- Sunday: review and cross-domain synthesis

Push questions to Redis list `cortex:research_queue` with `LPUSH`.

#### `integrations/cortex_autobuilder/researcher.py`

```python
"""Betty researches questions using Ollama (free local LLM)."""
```

Implement class `BettyResearcher`:

- `__init__(self, cortex_url, redis_url)` — store config
- `async def research_question(self, question: dict) -> dict` — main method

Research flow:
1. Pop question from Redis `cortex:research_queue` with `BRPOP` (blocking, 30s timeout)
2. Build a research prompt:

```
You are Betty, an expert research assistant. Answer the following question thoroughly.
Provide specific, actionable information with concrete examples where possible.
If you are uncertain about something, say so explicitly.

Category: {category}
Context: {context}

Question: {question}

Provide your answer in this structure:
- SUMMARY: 2-3 sentence answer
- DETAILS: Detailed explanation with specifics
- ACTIONABLE: Concrete steps or recommendations
- CONFIDENCE: How confident are you (low/medium/high)?
- RELATED: What follow-up questions would deepen this knowledge?
```

3. Call `openclaw.llm_router.completion()` with:
   - `complexity="medium"` (uses qwen3:8b on Ollama — free)
   - `cache_ttl=86400` (cache for 24h to avoid repeat work)
   - `service="cortex_autobuilder"`
   - `system_prompt="You are Betty, Bob's research assistant. You provide thorough, accurate answers focused on prediction markets, trading, smart home technology, and AI infrastructure."`

4. Parse the structured response
5. Validate quality (reject empty, too-short, or clearly hallucinated answers)
6. POST to Cortex:

```python
POST {CORTEX_URL}/remember
{
    "category": question["category"],
    "title": f"Research: {question['question'][:80]}",
    "content": formatted_answer,
    "source": "cortex_autobuilder",
    "importance": question["priority"],
    "tags": ["auto_research", question["category"], question.get("source", "unknown")],
    "confidence": confidence_score  # 0.0-1.0 based on LLM self-assessment
}
```

7. If the answer includes follow-up questions (from RELATED section), generate new questions and push to queue (with lower priority to prevent infinite loops — cap at priority 4 for follow-ups, and max 2 follow-ups per answer).

8. Log to Redis hash `cortex:autobuilder:stats` — increment counters for questions_asked, questions_answered, knowledge_stored, ollama_calls, errors.

#### `integrations/cortex_autobuilder/daemon.py`

```python
"""Main daemon — runs question generation hourly, research continuously."""
```

Implement:
- Run `QuestionGenerator.generate_questions()` every 60 minutes
- Run `BettyResearcher` in a continuous loop (BRPOP with 30s timeout so it naturally pauses when queue is empty)
- Health endpoint on port 8115: `GET /health` returns stats
- `GET /stats` returns `cortex:autobuilder:stats` from Redis
- `POST /ask` — manually inject a question: `{"question": "...", "category": "...", "priority": 8}`
- Rate limit: max 30 questions per hour to avoid overwhelming Ollama
- Backoff: if Ollama is down (LLM router returns error), exponential backoff starting at 60s, max 15 min

**IMPORTANT**: Use `from openclaw.llm_router import completion` for ALL LLM calls. This automatically handles Ollama-first routing with cloud fallback, caching, and cost tracking. Do NOT call Ollama directly.

#### `integrations/cortex_autobuilder/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/
CMD ["python", "-m", "integrations.cortex_autobuilder.daemon"]
```

#### `integrations/cortex_autobuilder/requirements.txt`

```
httpx>=0.27
redis>=5.0
structlog
uvicorn
fastapi
```

---

## Part 2: X Bookmark Folder Organizer (`integrations/x_intake/bookmark_organizer.py`)

### What Exists

- `integrations/x_intake/bookmark_scraper.py` — Playwright-based scraper that collects bookmarks from X using Brave browser (runs on host, not Docker). Outputs `bookmarks.json` with `{post_id, url, author, text, has_video, has_images}`.
- `integrations/x_intake/main.py` — FastAPI server on port 8101 with video transcription and LLM analysis.

### What to Build

A new module that takes the raw bookmarks JSON and:
1. Categorizes each bookmark using Ollama (free)
2. Groups by Matt's X bookmark folder categories
3. Ingests each categorized group into Cortex with proper tags

#### `integrations/x_intake/bookmark_organizer.py`

Implement class `BookmarkOrganizer`:

- `__init__(self, cortex_url, bookmarks_path)` — load bookmarks JSON
- `async def categorize_all(self) -> dict[str, list]` — categorize every bookmark
- `async def ingest_to_cortex(self, categorized: dict) -> dict` — POST each to Cortex

**Categorization approach** — use LLM Router for batch categorization:

For each bookmark (batch 10 at a time to be efficient):
```
Categorize this X/Twitter post into exactly ONE of these categories:
- trading_alpha: trading strategies, market analysis, price targets
- prediction_markets: Polymarket, Kalshi, prediction market news
- crypto: cryptocurrency news, DeFi, on-chain analysis
- ai_agents: AI, MCP, autonomous agents, LLM tools
- smart_home: Control4, Lutron, home automation, AV
- business: entrepreneurship, SaaS, client acquisition
- macro: Fed, inflation, economic policy, geopolitics
- sports: NBA, NFL, MLB, UFC betting/analysis
- weather: weather events, hurricane tracking
- general: everything else

Post by @{author}: "{text[:300]}"

Reply with ONLY the category name, nothing else.
```

Use `complexity="simple"` (routes to llama3.1:8b — free).

After categorization, build a structured summary per category:

```python
POST {CORTEX_URL}/remember
{
    "category": "x_bookmarks",
    "title": f"X Bookmarks: {category} ({count} posts)",
    "content": formatted_summary_of_posts_in_category,
    "source": "bookmark_organizer",
    "importance": 6,
    "tags": ["x_bookmarks", category, "batch_import"]
}
```

For high-value bookmarks (trading_alpha, prediction_markets with video), also trigger the existing `process_bookmarks()` pipeline for full video transcription + analysis.

#### Add endpoint to `integrations/x_intake/main.py`:

```python
@app.post("/organize-bookmarks")
async def organize_bookmarks(request: dict):
    """Organize and ingest bookmarks into Cortex."""
    bookmarks_path = request.get("path", "/data/bookmarks.json")
    organizer = BookmarkOrganizer(CORTEX_URL, bookmarks_path)
    categorized = await organizer.categorize_all()
    result = await organizer.ingest_to_cortex(categorized)
    return result
```

---

## Part 3: Docker Compose Integration

### Add to `docker-compose.yml`:

```yaml
  cortex-autobuilder:
    build:
      context: .
      dockerfile: integrations/cortex_autobuilder/Dockerfile
    container_name: cortex-autobuilder
    ports:
      - "127.0.0.1:8115:8115"
    volumes:
      - ./integrations:/app/integrations
      - ./openclaw:/app/openclaw
      - ./data:/data
    environment:
      - CORTEX_URL=http://cortex:8102
      - REDIS_URL=redis://redis:6379
      - OLLAMA_HOST=http://192.168.1.199:11434
      - LLM_ROUTER_MODE=local_first
      - AUTOBUILDER_PORT=8115
      - MAX_QUESTIONS_PER_HOUR=30
      - GENERATION_INTERVAL_MINUTES=60
    depends_on:
      cortex:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8115/health')"]
      interval: 60s
      timeout: 10s
      retries: 3
    networks:
      - bob-net
```

### Update x-intake service environment (already exists, just add):

```yaml
    environment:
      - CORTEX_URL=http://cortex:8102  # may already exist
```

---

## Part 4: Validation Checklist

After implementation, verify:

1. **Cortex Auto-Builder**:
   - `python -m integrations.cortex_autobuilder.daemon` starts without errors
   - `GET http://localhost:8115/health` returns 200
   - `POST http://localhost:8115/ask` with `{"question": "What is negative risk on Polymarket?", "category": "trading_strategy", "priority": 8}` queues and gets answered
   - Answers appear in Cortex (`GET http://localhost:8102/memories?category=trading_strategy`)
   - LLM Router logs show Ollama calls (cost $0.00)
   - Follow-up questions are generated but capped at priority 4

2. **Bookmark Organizer**:
   - `POST http://localhost:8101/organize-bookmarks` with `{"path": "/data/bookmarks.json"}` works
   - Bookmarks are categorized and grouped
   - Each category group is stored in Cortex with proper tags
   - High-value bookmarks trigger video transcription pipeline

3. **Docker**:
   - `docker compose up cortex-autobuilder` starts and connects to Cortex + Redis
   - Container stays healthy
   - No cloud LLM costs (all Ollama)

4. **Rate Limits**:
   - Max 30 questions/hour respected
   - Follow-up depth capped (no infinite loops)
   - Ollama backoff works when server is temporarily down

---

## Implementation Order

1. Create `integrations/cortex_autobuilder/` directory and all files
2. Implement `question_generator.py` first (can test standalone)
3. Implement `researcher.py` with LLM Router integration
4. Implement `daemon.py` with FastAPI health endpoint
5. Create `bookmark_organizer.py` in `integrations/x_intake/`
6. Add `/organize-bookmarks` endpoint to `integrations/x_intake/main.py`
7. Add `cortex-autobuilder` service to `docker-compose.yml`
8. Test each component individually before Docker build
9. Commit and push

---

## Key Constraints

- **ALL LLM calls go through `openclaw.llm_router.completion()`** — never call Ollama directly
- **Zero cloud cost by default** — `LLM_ROUTER_MODE=local_first` with Ollama handles everything; cloud is emergency fallback only
- **No bare `git pull`** — use `bash scripts/pull.sh` for AI-Server repo
- **No `#` characters in bash scripts** — replace with alternatives
- **Cortex /remember API** accepts: `{category, title, content, source, importance, tags, confidence, ttl_days}`
- **Redis URL**: `redis://redis:6379` inside Docker network
- **Ollama URL**: `http://192.168.1.199:11434` (Bob's Mac Mini on LAN)
