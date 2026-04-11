# Prompt S — Cortex Becomes the Brain + Dashboard (Merge Mission Control Into Cortex)

Read CLAUDE.md first. This prompt merges Mission Control into Cortex so Bob has ONE brain with ONE dashboard instead of two overlapping services.

## WHY

Mission Control (8098) is a dumb dashboard — it polls other services for health and displays data it doesn't own. Cortex (8102) is Bob's actual brain — memory, goals, improvement loops, digests, opportunity scanning. But Cortex has no UI, and Mission Control has no intelligence. They should be one service.

After this prompt:
- Cortex serves the dashboard at port 8102 (absorbs all MC functionality)
- Mission Control container is removed from docker-compose.yml
- Every service feeds data INTO Cortex (the wide wire-up)
- Cortex displays everything: service health, trading, emails, follow-ups, decisions, memories, goals — all in one place

## PHASE 1: Add Mission Control's API Endpoints to Cortex Engine

In `cortex/engine.py`, add these endpoints (port from `mission_control/main.py`):

1. `GET /api/services` — health-check all services (copy the SERVICES list and `check_service_health()` from MC's main.py, update to current ports: notification-hub=8095, proposals=8091)
2. `GET /api/wallet` — proxy to polymarket bot wallet endpoint
3. `GET /api/positions` — proxy to polymarket bot positions
4. `GET /api/pnl-series` — proxy to polymarket bot P&L
5. `GET /api/activity` — last 50 entries from Redis events:log
6. `GET /api/trading` — proxy to polymarket bot /api/trading
7. `GET /api/trading/categories` — proxy to bot /api/trading/categories
8. `GET /api/trading/positions` — proxy to bot /api/trading/positions
9. `GET /api/emails` — proxy to email-monitor /api/emails (or read emails.db directly)
10. `GET /api/calendar` — proxy to calendar-agent
11. `GET /api/followups` — read follow_ups.db
12. `GET /api/decisions/recent` — read from Cortex's own decisions table
13. `GET /api/events-log` — Redis events:log
14. `GET /api/system` — system info (uptime, container count, disk, memory)

For proxy endpoints, use `httpx.AsyncClient` with 5s timeout and try/except that returns `{"error": "service unavailable"}` if the target is down. Never let a downstream failure crash Cortex.

Keep Cortex's existing endpoints: `/health`, `/query`, `/remember`, `/goals`, `/digest/today`, `/memories`, `/rules`, `/improve/run`

## PHASE 2: Build the Dashboard UI

Create `cortex/static/index.html` — a single-page dashboard that replaces Mission Control's UI.

Design requirements:
- Dark theme matching symphonysh.com: black background (#000), white text, gold accent (#ca9f5c)
- Single page, no frameworks — vanilla JS + HTML + CSS
- Auto-refresh every 60 seconds
- Responsive: works at 1280px and 375px
- Font: Inter (or system-ui fallback)

Layout (desktop — 3 columns, mobile — stacked):

**Column 1: Operations**
- Service health grid (green/yellow/red dots with service name and port)
- Email summary (unread count, last 5 subjects)
- Calendar (next 3 upcoming events)
- Follow-ups due (count + next due date)

**Column 2: Trading**
- Wallet balance (USDC)
- Open positions count + total exposure
- Daily P&L (with sparkline if possible, otherwise just the number)
- Strategy breakdown (active strategies + trade counts)
- Last 5 trades (time, market, side, amount)

**Column 3: Brain (Cortex)**
- Memory count + recent entries
- Active goals with progress bars
- Neural paths / patterns detected
- Improvement actions (last 3)
- Pending decisions count (with alert if >20)
- Daily digest preview

**Header bar:**
- "Bob — Symphony AI" left-aligned
- Current time (Mountain Time) right-aligned
- Uptime badge
- Last refresh timestamp

**Bottom bar:**
- Quick stats: total memories, total decisions, total trades, emails processed
- Link to `/digest/today` for full daily digest

Use `fetch()` to hit the API endpoints. Each section should gracefully show "unavailable" if its API call fails — never break the whole page because one service is down.

Serve this file from Cortex:
```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/static", StaticFiles(directory="cortex/static"), name="static")

@app.get("/dashboard")
async def dashboard():
    return FileResponse("cortex/static/index.html")

@app.get("/")
async def root():
    return RedirectResponse("/dashboard")
```

Minimum font size: 13px for body text, 11px for labels. Use `clamp()` for responsive sizing. Do NOT make the same mistake as the old Mission Control where fonts were unreadable.

## PHASE 3: Wide Wire-Up (All Services Feed Cortex)

Every service should POST to `http://cortex:8102/remember` after significant events. The remember endpoint already exists — use it.

Payload format:
```json
{
  "category": "email|trading|system|client|follow_up",
  "title": "Brief description",
  "content": "Full details",
  "importance": 5,
  "tags": ["relevant", "tags"]
}
```

Wire these services (add a `_post_to_cortex()` helper in each):

1. **email-monitor/monitor.py** — After classifying an email:
   ```python
   category="email", title=f"Email from {sender}: {subject}", content=f"Classified as {classification}. {summary}", tags=["email", sender_domain, classification]
   ```

2. **openclaw/daily_briefing.py** — After sending the daily briefing:
   ```python
   category="system", title=f"Daily briefing sent", content=briefing_text[:500], tags=["briefing", "daily"]
   ```

3. **openclaw/follow_up_tracker.py** — When a follow-up becomes due:
   ```python
   category="follow_up", title=f"Follow-up due: {client_name}", content=f"Day {day_number} follow-up for {project_name}", tags=["follow_up", client_name]
   ```

4. **notification-hub** — After sending any high-priority notification:
   ```python
   category="system", title=f"Notification sent to Matt", content=message_text[:300], tags=["notification", priority_level]
   ```

5. **polymarket-bot** — This is Node.js, so use fetch/axios:
   ```javascript
   // After each trade execution
   fetch('http://cortex:8102/remember', {
     method: 'POST',
     headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({
       category: 'trading',
       title: `${side} ${market_title.substring(0,50)}`,
       content: `Strategy: ${strategy}, Amount: $${amount}, Price: ${price}`,
       importance: amount > 10 ? 8 : 5,
       tags: ['trading', strategy, side]
     })
   }).catch(() => {})  // never block on cortex failure
   ```

For ALL wire-ups: wrap in try/except (Python) or .catch() (JS). Cortex being down must NEVER crash the calling service. Log a warning and move on.

## PHASE 4: Docker Compose Changes

1. **Add cortex to docker-compose.yml:**
```yaml
  cortex:
    build:
      context: .
      dockerfile: cortex/Dockerfile
    container_name: cortex
    restart: unless-stopped
    ports:
      - "8102:8102"
    volumes:
      - ./data/cortex:/data/cortex
      - ./polymarket-bot/knowledge:/app/knowledge:ro
    environment:
      - REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
      - CORTEX_PORT=8102
      - OLLAMA_HOST=http://host.docker.internal:11434
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8102/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    depends_on:
      - redis
```

2. **Remove mission-control from docker-compose.yml entirely.** Delete its service block, its Dockerfile reference, everything.

3. **Update all references:** Any service that pointed to `mission-control:8098` should now point to `cortex:8102`.

4. **Update CLAUDE.md:** Replace mission-control entry with cortex in the service table. Remove the old MC port 8098. Cortex is now at 8102 and serves the dashboard.

## PHASE 5: Verification

```zsh
# Remove old MC container
docker compose stop mission-control 2>/dev/null
docker rm mission-control 2>/dev/null

# Build and start Cortex with the new dashboard
docker compose up -d --build cortex

# Wait for it
sleep 15

# Health
curl -s http://127.0.0.1:8102/health

# Dashboard loads
curl -s http://127.0.0.1:8102/dashboard | head -5

# API endpoints work
curl -s http://127.0.0.1:8102/api/services | python3 -m json.tool | head -20
curl -s http://127.0.0.1:8102/api/activity | python3 -m json.tool | head -10
curl -s http://127.0.0.1:8102/memories | python3 -m json.tool | head -10
curl -s http://127.0.0.1:8102/goals | python3 -m json.tool | head -10

# Cortex stats should show entries
curl -s http://127.0.0.1:8102/health
```

After verification, update STATUS_REPORT.md to reflect the merge.

Commit and push when done:
```zsh
git add -A
git commit -m "Merge Mission Control into Cortex — single brain + dashboard"
git push origin main
```
