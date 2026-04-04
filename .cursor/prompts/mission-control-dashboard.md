# Mission Control Dashboard — Build the Real 6-Panel Ops Dashboard

## Context
Mission Control runs on port 8098, served by `mission_control/main.py` which wraps `mission_control/event_server.py`. The current `mission_control/static/index.html` is a stale "Polymarket Trading Playbook" page — a single-purpose trading dashboard. We need to replace it with a proper 6-panel ops dashboard.

The server already has these working API endpoints:
- `GET /api/services` — health checks all 12 Docker services, returns `{services: [{name, status, port, details}], total, healthy}`
- `GET /api/trading/categories` — live Polymarket P&L with category breakdown, returns `{categories: {crypto: {total_pnl, trades, bought, returned, open_value, ...}}, summary: {estimated_deposits, total_returned, open_value, net_pnl, total_trades, activity_count}}`
- `GET /api/trading` — positions and recent trades
- `GET /api/trading/bot-status` — proxy to polymarket-bot /status
- `GET /status` — employee status + 24h stats + WS connection count
- `GET /events` — recent events from SQLite
- `WebSocket /ws` — real-time event stream

## What's Missing
The dashboard needs 6 panels but we only have API endpoints for 2 of them (services + trading). We need to add API endpoints for:

### 1. Email Queue — `/api/emails`
The email-monitor service runs on port 8092 (container hostname: `email-monitor`). Proxy to it:
- Try `GET http://email-monitor:8092/emails/recent` or `/api/emails` — check what endpoints exist by looking at `email-monitor/` in the repo
- If the email monitor has no suitable endpoint, read from Redis keys `email:*` using the REDIS_URL env var
- Return: `{emails: [{from, subject, received_at, read, processed, flagged}], unread_count}`

### 2. Calendar — `/api/calendar`  
The calendar-agent runs on port 8094 (container hostname: `calendar-agent`). Proxy to it:
- Try `GET http://calendar-agent:8094/calendar/today` or `/api/events` — check what endpoints exist
- If no endpoint, read from Redis keys `calendar:*`
- Return: `{events: [{title, start, end, location, description}]}`

### 3. Follow-ups — `/api/followups`
OpenClaw orchestrator runs on port 8099 (container hostname: `openclaw`). It tracks pending jobs/tasks:
- Try `GET http://openclaw:3000/api/jobs` or `/api/tasks` — check the openclaw/ directory  
- Also check the email-monitor for flagged items that need follow-up
- Return: `{followups: [{title, priority, due, source, overdue, assigned_to}]}`

### 4. System Resources — `/api/system`
Aggregate system info from Docker and the host:
- Use `docker` Python SDK or shell out to get container states
- If `psutil` is available, get CPU/memory/disk
- Combine with the existing `/status` employee data
- Return: `{cpu_percent, memory_percent, memory_used, memory_total, disk_percent, containers: [{name, status}], employees: {...}}`

## Task

### Step 1: Investigate existing service APIs
Before building anything, check what endpoints actually exist on each service:
```bash
# Check email monitor
docker exec email-monitor curl -s http://localhost:8092/docs 2>/dev/null || docker exec email-monitor curl -s http://localhost:8092/openapi.json 2>/dev/null
# Check calendar agent  
docker exec calendar-agent curl -s http://localhost:8094/docs 2>/dev/null
# Check openclaw
docker exec openclaw curl -s http://localhost:3000/docs 2>/dev/null
# Check Redis keys
docker exec redis redis-cli KEYS "*email*" 
docker exec redis redis-cli KEYS "*calendar*"
docker exec redis redis-cli KEYS "*task*"
docker exec redis redis-cli KEYS "*portfolio*"
```

### Step 2: Add API endpoints to `mission_control/main.py`
Add the 4 missing endpoints. Each should:
- Try the internal service HTTP endpoint first
- Fall back to Redis if the service is down
- Return graceful empty results on failure (never crash)
- Use `httpx.AsyncClient(timeout=5.0)` consistent with existing code

Also add `redis` (aioredis or redis-py with async) to `requirements.txt` if needed for Redis fallback.

### Step 3: Replace `mission_control/static/index.html`
Build a single-file HTML dashboard with these 6 panels in a 3x2 grid:

**Design:**
- Dark theme: bg `#0f1117`, panels `#161922`, borders `#1e2235`
- Font: Inter (body) + JetBrains Mono (data)
- Accent: `#2dd4bf` (teal) for healthy/positive, `#f87171` (red) for down/negative
- No framework — vanilla HTML/CSS/JS, Chart.js via CDN for the P&L chart
- Sticky top bar: logo, "Mission Control" title, live clock (America/Denver), WebSocket status indicator
- Bottom event strip: shows latest event from WebSocket

**Panel 1 — Service Health** (top-left)
- `GET /api/services` every 30s
- 2-column grid of service cards with colored dot (green/yellow/red), name, port
- Badge shows `healthy/total` count

**Panel 2 — Trading P&L** (top-center)
- `GET /api/trading/categories` every 5m  
- Big hero number: net P&L (green if positive, red if negative)
- 3 stat cards: Deposited, Returned, Open Value
- Horizontal bar chart: P&L by category
- Badge shows activity count

**Panel 3 — Email Queue** (top-right)
- `GET /api/emails` every 60s
- List of recent emails: dot (blue=unread, gray=read, orange=flagged), from, subject, relative time
- Badge shows unread count

**Panel 4 — Calendar** (bottom-left)
- `GET /api/calendar` every 2m
- Today's events: time, colored bar, title, location
- Badge shows event count

**Panel 5 — Follow-ups** (bottom-center)
- `GET /api/followups` every 2m
- Priority-sorted list: colored dot (red=high, orange=medium, gray=low), text, source, due date
- Badge shows overdue count or total

**Panel 6 — System** (bottom-right)
- `GET /api/system` (falls back to `/status`) every 30s
- Resource bars: CPU, Memory, Disk — green/yellow/red based on %
- Container list with status
- Employee list with status from WebSocket

**WebSocket:**
- Connect to `/ws`, show green dot when connected, red when disconnected
- Auto-reconnect with exponential backoff
- Update event strip with latest event
- Update employee status in System panel on `status_update` messages

**Responsive:** 3 cols > 2 cols at 1100px > 1 col at 700px

### Step 4: Update dashboard.html
Change `mission_control/static/dashboard.html` to redirect to `/` instead of `/dashboard`:
```html
<!DOCTYPE html>
<html><head><meta http-equiv="refresh" content="0;url=/"></head><body></body></html>
```

### Step 5: Rebuild and verify
```bash
cd ~/AI-Server
docker compose build mission-control
docker compose up -d mission-control
# Wait for healthy
sleep 5
curl -s http://localhost:8098/health
curl -s http://localhost:8098/api/services | python3 -m json.tool | head -20
curl -s http://localhost:8098/api/emails | python3 -m json.tool | head -20
curl -s http://localhost:8098/api/calendar | python3 -m json.tool | head -20
```

Then open http://bob.local:8098 in a browser and verify all 6 panels load.

## Important Notes
- Keep the existing trading endpoints (`/api/trading/*`) and event_server routes intact — only ADD new endpoints
- The `main.py` imports and extends `event_server.app`, so add new routes to that same `app` object
- Every new endpoint must have try/except and return graceful fallbacks — a single service being down should never crash Mission Control
- Use the same `httpx.AsyncClient(timeout=5.0)` pattern as existing service health checks
