<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes. Use printf or write-file patterns instead. -->

# Bob 24/7 Hardening — Launchd, Trading Activation, X-Intake Sandbox

## Objective

Make Bob truly run 24/7 with auto-recovery, activate dormant trading integrations,
and isolate x-intake experiments in their own container. This is a reliability +
revenue prompt.

---

## Phase 1: Launchd Hardening (auto-restart everything)

### 1A. Add KeepAlive to all repo plists that are missing it

These plists in `setup/launchd/` need `<key>KeepAlive</key><true/>` added
inside the top-level `<dict>`:

- `com.symphony.backup-data.plist`
- `com.symphony.business-hours-throttle.plist`
- `com.symphony.learning.plist`
- `com.symphony.network-guard.plist`
- `com.symphony.notes-indexer.plist`
- `com.symphony.smoke-test.plist`

File-watcher, mobile-api, trading-api, and icloud-watch already have it.

### 1B. Audit and commit orphan launchd plists from Bob

Bob has 42+ launchd services that were created directly on the machine and
never committed to the repo. Run this on Bob to find them all:

```
find ~/Library/LaunchAgents -name "com.symphony*" -o -name "com.symphonysh*" | sort
```

For each plist found that is NOT already in `setup/launchd/`:
1. Copy it to `setup/launchd/` in the repo
2. Ensure it has `<key>KeepAlive</key><true/>` for always-on services
3. For scheduled jobs (daily, hourly, weekly), use `StartCalendarInterval` instead of KeepAlive
4. Ensure the `PATH` key includes `/Users/bob/Library/Python/3.9/bin` if it runs Python

Categorize each service:
- **Always-on** (KeepAlive: true): imessage-bridge, imessage-watcher, file-watcher,
  dropbox-organizer, mobile-api, trading-api, bob-maintenance, watcher, incoming-tasks,
  email-reply-agent, memory-guard, worker-betty, employee-beatrice-bot, employee-betty-bot
- **Scheduled** (StartCalendarInterval): daily-digest, overnight-learner, backup-data,
  quality-gate-nightly, trading-research-daily-digest, trading-pnl-attribution-daily,
  trading-topic-graph-daily, graph-drift-watcher-daily, trading-research-quality-weekly
- **Periodic** (StartInterval in seconds): polymarket-hourly, polymarket-scan,
  trading-research-bot-hourly, core-ops-health-hourly, decision-hygiene-hourly,
  signal-action-hourly, service-sre-loop, focus-ops-monitor,
  trading-provider-slo-monitor, subscription-audit
- **Evaluate if needed** (may be dead weight): seo-content, multi-machine-sync-monitor,
  contacts-sync, notes-sync-photos, x-drip, learner-light, markup-app, x-mention-replier,
  betty-learner, voice-webhook

For the "evaluate" category: check if the script/binary the plist points to
actually exists. If the target file is missing, the service is dead weight.
Remove the plist from Bob and do NOT commit it.

### 1C. Create a master restart script

Create `scripts/restart-all-launchd.sh`:
- Unloads then loads every plist in `setup/launchd/`
- Verifies each service started (check exit code via `launchctl list`)
- Prints a summary: service name, PID or exit code, status (running/crashed/scheduled)

---

## Phase 2: Trading Activation

### 2A. Kraken — wire the keys

The `KRAKEN_API_KEY` and `KRAKEN_SECRET` env vars are in docker-compose.yml
but empty in .env. Check if Kraken credentials exist anywhere on Bob:

```
grep -ri "kraken" ~/.env* ~/AI-Server/.env ~/AI-Server/data/ ~/AI-Server/polymarket-bot/ --include="*.env" --include="*.yaml" --include="*.yml" --include="*.json" 2>/dev/null
```

If found, add them to `.env`. If not found, add placeholder lines to `.env`
with a comment that Matt needs to fill them in:

```
KRAKEN_API_KEY=  # Matt: paste your Kraken API key here
KRAKEN_SECRET=   # Matt: paste your Kraken secret here
```

### 2B. Kalshi — add env vars to compose

The Kalshi client (`polymarket-bot/src/platforms/kalshi_client.py`) uses
RSA-PSS auth. It needs these env vars added to the `polymarket-bot` service
in `docker-compose.yml`:

```yaml
- KALSHI_API_KEY=${KALSHI_API_KEY:-}
- KALSHI_PRIVATE_KEY_PATH=${KALSHI_PRIVATE_KEY_PATH:-/data/kalshi_private_key.pem}
- KALSHI_ENV=${KALSHI_ENV:-production}
```

Also add a volume mount for the key file:
```yaml
- ./data/kalshi_private_key.pem:/data/kalshi_private_key.pem:ro
```

Add placeholder lines to `.env`:
```
KALSHI_API_KEY=  # Matt: paste your Kalshi API key
# Place your Kalshi RSA private key PEM at data/kalshi_private_key.pem
```

### 2C. Polymarket — switch from paper to live

In `polymarket-bot/config.example.yaml`, `dry_run` is `true`.
Check if there is a `config.yaml` override on Bob:

```
ls -la ~/AI-Server/polymarket-bot/config.yaml ~/AI-Server/data/config.yaml 2>/dev/null
```

If config.yaml exists and dry_run is true, change it to false.
If no config.yaml exists, create `polymarket-bot/config.yaml` by copying
config.example.yaml and setting:
- `dry_run: false`
- `paper_ledger.enabled: true` (keep paper tracking alongside live)

Do NOT restart the polymarket-bot yet. Just prepare the config.
Add a comment at the top: `# LIVE TRADING - switched from paper mode by hardening prompt`

---

## Phase 3: X-Intake Sandbox Container

### 3A. Create a new Docker service: x-intake-lab

This is an experimental container for x-intake features that go beyond the
basic tweet-link pipeline. It runs alongside the existing x-intake service
without interfering.

Add to `docker-compose.yml`:

```yaml
  x-intake-lab:
    build: ./integrations/x_intake
    container_name: x-intake-lab
    restart: unless-stopped
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=${REDIS_PASSWORD}
      - CORTEX_URL=http://cortex:8102
      - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
      - OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - PYTHONUNBUFFERED=1
      - TZ=America/Denver
      - LAB_MODE=true
    volumes:
      - ./data/transcripts:/data/transcripts
      - ./data/bookmarks:/data/bookmarks
      - x-intake-lab-data:/data/lab
    networks:
      - symphony
    depends_on:
      redis:
        condition: service_healthy
      cortex:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python3", "-c", "import requests; requests.get('http://localhost:8101/health', timeout=3)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

Add the volume at the bottom of docker-compose.yml:
```yaml
  x-intake-lab-data:
```

### 3B. Create the lab entrypoint

Create `integrations/x_intake/lab_main.py`:

This should:
1. Run the transcript analyst on a loop (check for new unanalyzed transcripts every 5 min)
2. Run the bookmark organizer on a schedule (check data/bookmarks/ for new exports every 30 min)
3. Expose a FastAPI health endpoint on port 8101 (different internal port, map to 8103 on host)
4. Subscribe to a Redis channel `x-intake-lab` for ad-hoc commands:
   - `{"action": "analyze_transcript", "path": "/data/transcripts/file.md"}`
   - `{"action": "organize_bookmarks", "path": "/data/bookmarks/export.json"}`
   - `{"action": "scrape_bookmarks"}` (triggers bookmark scraper)
5. Log all activity to Cortex via POST /remember

Actually, map to port 8103 on host:
```yaml
    ports:
      - "127.0.0.1:8103:8101"
```

And add to the gateway SERVICES map in `api/gateway.py`:
```python
"x-intake-lab": "http://localhost:8103",
```

### 3C. Create data directories

Ensure these directories exist (add to scripts/pull.sh):
```
mkdir -p data/transcripts data/bookmarks
```

---

## Phase 4: X-Intake Action Loop (close the dead end)

Currently x-intake analyzes X links and replies with a summary, but nobody
acts on the intelligence. High-relevance posts with actionable flags need to
create real tasks that Bob picks up and executes.

### 4A. Add Cortex memory storage to every analyzed post

In `integrations/x_intake/main.py`, find `_process_url_and_reply()`. After
the iMessage reply is sent, add a Cortex POST:

```python
async def _save_to_cortex(url: str, author: str, analysis: dict, poly_signals: dict) -> None:
    """Save analyzed X post to Cortex for long-term memory and action tracking."""
    try:
        import httpx
        relevance = analysis.get("relevance", 0)
        action = analysis.get("action", "none")
        post_type = analysis.get("type", "info")
        summary = analysis.get("summary", "")[:1000]

        category = "x_intel"
        if post_type == "build":
            category = "x_intel_actionable"
        elif post_type == "alpha":
            category = "x_intel_alpha"
        elif post_type == "tool":
            category = "x_intel_tools"

        memory_text = f"X post from @{author} (relevance {relevance}%): {summary}"
        if action and action.lower() != "none":
            memory_text += f"\nAction: {action}"
        if poly_signals.get("strategies"):
            for s in poly_signals["strategies"]:
                if isinstance(s, dict):
                    memory_text += f"\nStrategy: {s.get('name', '')}: {s.get('description', '')}"
        if poly_signals.get("alpha_insights"):
            memory_text += "\nAlpha: " + "; ".join(poly_signals["alpha_insights"])
        memory_text += f"\nSource: {url}"

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{CORTEX_URL}/remember",
                json={
                    "text": memory_text,
                    "category": category,
                    "source": "x_intake",
                    "metadata": {
                        "author": author,
                        "url": url,
                        "relevance": relevance,
                        "type": post_type,
                        "action": action,
                    }
                }
            )
            logger.info("saved_to_cortex", author=author, category=category)
    except Exception as exc:
        logger.warning("cortex_save_failed", error=str(exc)[:200])
```

Call `_save_to_cortex()` from `_process_url_and_reply()` after the iMessage
reply, for ALL posts (not just high relevance). Cortex should see everything.

### 4B. Add action queue for high-relevance posts

Create `integrations/x_intake/action_queue.py`:

This module maintains a SQLite DB at `/data/x_intake/action_queue.db` with:

```sql
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    author TEXT,
    action_type TEXT NOT NULL,  -- build, investigate, deploy, test, evaluate
    description TEXT NOT NULL,
    relevance INTEGER,
    status TEXT DEFAULT 'pending',  -- pending, in_progress, done, dismissed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    result TEXT
);
```

Provide functions:
- `enqueue(url, author, action_type, description, relevance)` — add new action
- `get_pending(limit=10)` — get pending actions ordered by relevance desc
- `update_status(action_id, status, result=None)` — mark done/dismissed
- `get_stats()` — counts by status

### 4C. Wire action queue into the pipeline

In `_process_url_and_reply()`, after saving to Cortex, check if the post
should create an action:

```python
if relevance >= 60 and action.lower() != "none":
    action_queue.enqueue(
        url=url,
        author=author,
        action_type=analysis.get("type", "info"),
        description=f"@{author}: {action}\n\n{summary[:500]}",
        relevance=relevance,
    )
    logger.info("action_queued", author=author, action=action, relevance=relevance)
```

Also for strategy suggestions from poly_signals:
```python
for strat in poly_signals.get("strategies", []):
    if isinstance(strat, dict):
        action_queue.enqueue(
            url=url,
            author=author,
            action_type="build",
            description=f"Strategy from @{author}: {strat.get('name', '')} — {strat.get('description', '')}",
            relevance=relevance,
        )
```

### 4D. Add API endpoints for the action queue

Add these routes to the x-intake FastAPI app in `main.py`:

```python
@app.get("/actions")
async def list_actions(status: str = "pending", limit: int = 20):
    """List queued actions."""
    from action_queue import get_pending, get_by_status
    if status == "pending":
        return {"actions": get_pending(limit)}
    return {"actions": get_by_status(status, limit)}

@app.get("/actions/stats")
async def action_stats():
    """Action queue statistics."""
    from action_queue import get_stats
    return get_stats()

@app.post("/actions/{action_id}/dismiss")
async def dismiss_action(action_id: int):
    """Dismiss an action."""
    from action_queue import update_status
    update_status(action_id, "dismissed")
    return {"ok": True}

@app.post("/actions/{action_id}/done")
async def complete_action(action_id: int, result: str = ""):
    """Mark an action complete."""
    from action_queue import update_status
    update_status(action_id, "done", result)
    return {"ok": True}
```

### 4E. Add action queue to the mobile dashboard

Update `api/templates/dashboard.html` to show the action queue.

Add a new section after the trading section that:
1. Fetches `/proxy/x-intake/actions?status=pending&limit=5`
2. Shows each pending action as a card with:
   - Author and action type (color-coded: build=blue, alpha=green, tool=purple)
   - Description (truncated to 2 lines)
   - Relevance score
   - Source link
   - Dismiss button (POST to `/proxy/x-intake/actions/{id}/dismiss`)
   - Done button (POST to `/proxy/x-intake/actions/{id}/done`)
3. Shows a count badge: "3 pending actions" in the status pills at top

### 4F. Daily action digest

Create a function in `action_queue.py`:

```python
def get_daily_digest() -> str:
    """Build a daily digest of pending actions for iMessage."""
    pending = get_pending(limit=10)
    if not pending:
        return ""
    lines = [f"\U0001f4cb {len(pending)} pending X-intel actions:\n"]
    for i, a in enumerate(pending, 1):
        emoji = {"build": "\U0001f528", "alpha": "\U0001f4b0", "tool": "\U0001f527", "investigate": "\U0001f50d"}.get(a["action_type"], "\U00002753")
        lines.append(f"{i}. {emoji} [{a['relevance']}%] {a['description'][:100]}")
    lines.append("\nReview: http://100.89.1.51:8420/proxy/x-intake/actions")
    return "\n".join(lines)
```

Add an endpoint:
```python
@app.post("/actions/digest")
async def send_action_digest():
    from action_queue import get_daily_digest
    digest = get_daily_digest()
    if digest:
        await _send_imessage(digest)
        return {"ok": True, "sent": True}
    return {"ok": True, "sent": False, "reason": "no pending actions"}
```

This can be triggered by the daily-digest launchd job or a cron inside the container.

### 4G. Replace OpenAI with Ollama for x-intake analysis

The x-intake analysis currently uses OpenAI GPT-4o-mini. Switch to Ollama first,
OpenAI as fallback:

1. In `main.py`, find `_analyze_with_llm()`. Refactor it to try Ollama first:

```python
async def _analyze_with_ollama(text: str, author: str, has_video: bool, transcript: str = "") -> dict:
    """Try Ollama first (free), fall back to OpenAI."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://192.168.1.199:11434")
    model = os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen3:8b")

    content_parts = [f"Post by @{author}:\n{text}"]
    if transcript:
        content_parts.append(f"\nVideo transcript:\n{transcript[:8000]}")

    prompt = MATT_PROFILE + "\n\nAnalyze this post:\n" + "\n".join(content_parts)
    prompt += "\n\nRespond in JSON: {summary, type, relevance (0-100), action, flags}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "format": "json",
                    "stream": False,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                parsed = json.loads(content)
                logger.info("ollama_analysis_ok", model=model)
                return parsed
    except Exception as exc:
        logger.warning("ollama_analysis_failed", error=str(exc)[:200])

    # Fallback to OpenAI
    return _analyze_with_llm(text, author, has_video, transcript)
```

2. Replace all calls to `_analyze_with_llm()` with `_analyze_with_ollama()`
   (but keep the old function as the fallback inside the new one).

3. Do the same for the Polymarket signal extraction (`_extract_polymarket_signals`):
   try Ollama first, OpenAI fallback.

This cuts the OpenAI cost for x-intake to near zero while keeping it as a
safety net.

---

## Phase 5: Cleanup

### 5A. Remove dead Docker containers from Bob

These were removed from docker-compose.yml but containers persist:

```
docker stop knowledge-scanner remediator context-preprocessor 2>/dev/null
docker rm knowledge-scanner remediator context-preprocessor 2>/dev/null
```

### 5B. Remove Supabase references

Check `.env` for any SUPABASE variables and remove them:
```
grep -i supabase .env
```
Delete any lines found (SUPABASE_URL, SUPABASE_KEY, SUPABASE_ANON_KEY, etc.)

### 5C. Update PORTS.md

Add x-intake-lab on port 8103 to PORTS.md.

---

## Verification

After all changes, run:

```
docker compose config --quiet && echo "Compose valid"
```

Then commit and push with message:
```
feat: 24/7 hardening — launchd, trading, x-intake action loop

- All launchd plists committed to repo with KeepAlive/scheduling
- Master restart script for launchd services
- Kraken + Kalshi env vars wired into compose
- Polymarket switched from paper to live trading config
- x-intake-lab sandbox container for transcript/bookmark experiments
- X-intake now saves ALL posts to Cortex memory
- Action queue with SQLite DB for high-relevance posts (>= 60%)
- Action queue API endpoints + mobile dashboard integration
- Daily action digest via iMessage
- Ollama-first analysis (free) with OpenAI fallback
- Dead containers and Supabase references cleaned up
```

Do NOT restart Docker services or launchd — just prepare everything.
Matt will do the restart when ready.
