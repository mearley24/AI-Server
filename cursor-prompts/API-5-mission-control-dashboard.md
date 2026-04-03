# API-5: Mission Control Dashboard

## Context Files to Read First
- mission_control/main.py
- mission_control/event_server.py
- mission_control/static/app.js        ← existing dashboard JS to upgrade
- mission_control/static/index.html    ← existing dashboard HTML to replace
- mission_control/static/style.css     ← existing styles to upgrade
- docker-compose.yml (all service definitions)
- AGENTS.md (architecture overview)
- polymarket-bot/heartbeat/runner.py
- core/context_store.py (API-11 context store — primary data source)

## Prompt

Build Mission Control — a comprehensive real-time intelligence dashboard showing health, status, and business context for all services running on Bob. This replaces/upgrades the existing dashboard at `/dashboard/` (app.js, index.html, style.css).

**Runs on Bob's local network at port 8098.** (Not 8095 — that port is taken. Use 8098.)

---

### 1. Backend (`mission_control/main.py` — expand existing)

FastAPI server on port 8098.

**REST endpoints:**
- `GET /api/services` — all service statuses (Docker container health, uptime, restart count)
- `GET /api/trading` — portfolio value, positions, recent trades, daily P/L
- `GET /api/email` — unread count, pending drafts, auto-response stats
- `GET /api/calendar` — today's events, next 3 upcoming events
- `GET /api/followups` — follow-ups due today/overdue, from follow_up_tracker
- `GET /api/projects` — status of each active client project
- `GET /api/payments` — pending deposits and final payments
- `GET /api/system` — Mac Mini CPU%, RAM%, disk%, Docker total resource usage
- `GET /api/context` — proxy to Bob's Brain (API-11) full context store

**WebSocket:**
- `WS /ws/events` — real-time event stream; subscribe to Redis pub/sub `events:pubsub` and forward to connected browser clients

**Data sources per panel (see Section 3):**
- Primary: Bob's Brain context store via Redis (`bob:context:*` hashes)
- Service health: Docker socket (`/var/run/docker.sock`)
- Calendar: Zoho Calendar API
- System resources: `psutil` + Docker stats API
- Follow-ups / payments: Redis keys from `follow_up_tracker` and `payment_tracker`

**Polling:**
- Poll Docker socket every 10s for container states
- Poll system resources every 15s
- Redis keys are read on-request (fast, no polling needed)
- WebSocket forwards Redis pub/sub events in real-time

**Health endpoint:** `GET /health` → `{"status": "ok"}` for Docker healthcheck.

---

### 2. Dashboard Panels

The dashboard has 7 panels in a CSS Grid layout. Each panel polls its corresponding API endpoint every 10 seconds (configurable via `REFRESH_INTERVAL` constant).

#### Panel 1: Service Health
**Data source:** `GET /api/services` → Docker socket  
**Shows:**
- All running Docker containers: name, status (green = running/healthy, yellow = starting/unhealthy, red = exited/dead), uptime, restart count
- Containers are grouped: Trading, Business, Infrastructure, Monitoring
- Any container restarting >3x in an hour → red badge "UNSTABLE"
- Any container unhealthy >5 minutes → yellow badge "DEGRADED"
- Click a service name → expand to show last 20 log lines (from `docker logs --tail 20 {container}`)

**Backend implementation:**
```python
import docker
client = docker.from_env()  # uses /var/run/docker.sock

def get_services():
    containers = client.containers.list(all=True)
    return [{
        "name": c.name,
        "status": c.status,
        "health": c.attrs.get("State", {}).get("Health", {}).get("Status", "none"),
        "uptime": c.attrs["State"]["StartedAt"],
        "restart_count": c.attrs["RestartCount"]
    } for c in containers]
```

#### Panel 2: Trading Bot P/L
**Data source:** `GET /api/trading` → `bob:context:portfolio` Redis hash  
**Shows:**
- Portfolio value (large, prominent)
- Available USDC
- Open positions count
- Daily P/L (green if positive, red if negative)
- 7-day P/L sparkline (from `data/pnl_history.json` if available)
- Last 5 trades (market, size, price, outcome)
- Active strategies list
- Any active trading alerts (exit engine stuck, etc.)

#### Panel 3: Email Queue
**Data source:** `GET /api/email` → `bob:context:email` Redis hash  
**Shows:**
- Unread emails count (badge)
- Pending drafts (emails Bob drafted but not yet approved/sent)
- Auto-responses sent today
- Escalated emails (need Matt's attention — highlighted)
- Last 3 email subjects with classification (lead, client, vendor, spam)

#### Panel 4: Calendar
**Data source:** `GET /api/calendar` → Zoho Calendar API  
**Shows:**
- Today's date (large)
- Today's events in chronological order: time, title, attendees
- Next 3 upcoming events (next 7 days)
- "Meeting prep due" indicator: if a meeting is in <2 hours and no prep brief has been sent → yellow alert
- Empty state: "No meetings today — Bob is focused on ClawWork and trading"

#### Panel 5: Follow-Up Reminders
**Data source:** `GET /api/followups` → Redis `followup:*` keys via follow_up_tracker  
**Shows:**
- Follow-ups due today: client name, project value, which day (Day 3/7/14), CTA button "Mark Sent"
- Overdue follow-ups: any past-due not sent — highlighted red
- Upcoming this week: next 7 days
- Empty state: "No follow-ups due today"

**CTA button "Mark Sent"** → calls `POST /api/followups/{id}/sent` → marks in tracker, logs in comms log

#### Panel 6: Client Projects
**Data source:** `GET /api/projects` → `bob:context:project` Redis hash  
**Shows per active project:**
- Client name + project address
- Current phase (Lead / Proposal Sent / Deposit Pending / Pre-Wire / Install / Commission / Complete)
- Project value
- Last communication (date + subject, from comms log)
- Pending payment indicator: if deposit or final payment pending, show amount + days pending
- Linear link (if project exists in Linear)
- Phase displayed as a horizontal progress indicator (5 steps)

#### Panel 7: System Resources
**Data source:** `GET /api/system` → psutil + Docker stats API  
**Shows:**
- CPU usage % (gauge)
- RAM usage % (gauge) — with used/total GB
- Disk usage % (gauge) — with used/total GB, yellow >75%, red >85%
- Network I/O (bytes in/out per second)
- Docker: total container count, total CPU/RAM consumed by Docker
- VPN status: connected/disconnected (from `bob:context:infrastructure`)

---

### 3. Data Source Map (Redis Keys)

| Panel | Redis Key | Refresh |
|-------|-----------|---------|
| Trading | `bob:context:portfolio` | On event or 10s |
| Email | `bob:context:email` | On event or 10s |
| Projects | `bob:context:project` | On event or 30s |
| Followups | `followup:*` | On event or 30s |
| Payments | `payment:*` | On event or 30s |
| Infra/VPN | `bob:context:infrastructure` | On event or 10s |
| System | psutil (direct) | 15s |
| Calendar | Zoho API | 5 min |
| Services | Docker socket | 10s |

---

### 4. Frontend (`mission_control/static/` — replace existing)

**Tech: vanilla HTML/CSS/JS. No frameworks. No build step. No npm. Must load <1 second on local network.**

**Files to produce:**
- `mission_control/static/index.html` — dashboard shell, panel layout
- `mission_control/static/style.css` — dark theme, grid layout
- `mission_control/static/app.js` — polling logic, WebSocket, panel renderers

**Design:**
- Dark background (`#0d1117`), panel cards with subtle border (`#21262d`)
- Status colors: green `#3fb950`, yellow `#d29922`, red `#f85149`
- Font: system-ui (no external fonts — fast load)
- CSS Grid: 3-column layout on wide screens, 2-column on medium, 1-column on mobile
- Panel headers show last-updated timestamp (fades to yellow if stale >30s)

**JS architecture:**
```javascript
const REFRESH_INTERVAL = 10000; // ms

// Each panel is a self-contained object
const panels = {
  serviceHealth: { endpoint: '/api/services', render: renderServiceHealth },
  trading:       { endpoint: '/api/trading',  render: renderTrading },
  email:         { endpoint: '/api/email',    render: renderEmail },
  calendar:      { endpoint: '/api/calendar', render: renderCalendar },
  followups:     { endpoint: '/api/followups',render: renderFollowUps },
  projects:      { endpoint: '/api/projects', render: renderProjects },
  system:        { endpoint: '/api/system',   render: renderSystem },
};

// Poll all panels
function pollAll() {
  Object.entries(panels).forEach(([name, panel]) => {
    fetch(panel.endpoint)
      .then(r => r.json())
      .then(data => panel.render(data))
      .catch(err => markPanelError(name, err));
  });
}
setInterval(pollAll, REFRESH_INTERVAL);
pollAll(); // immediate on load

// WebSocket for real-time event feed
const ws = new WebSocket(`ws://${location.host}/ws/events`);
ws.onmessage = (msg) => appendActivityFeed(JSON.parse(msg.data));
```

**Activity feed** (bottom of page, full width):
- Real-time scrolling log of events from all services via WebSocket
- Color-coded by priority: normal = white, high = yellow, critical = red
- Shows: timestamp, service name, event_type, payload summary
- Keep last 100 events in DOM (remove oldest when >100)

---

### 5. Alerts Section

Persistent alert bar at top of page, hidden when no alerts:

| Condition | Severity | Message |
|-----------|----------|---------|
| Container restarts >3x in 1 hour | Red | "{service} is unstable — restarted {n} times" |
| Service unhealthy >5 minutes | Yellow | "{service} has been unhealthy for {n} minutes" |
| Portfolio drop >20% in 24h | Red | "Trading: portfolio down {pct}% in 24 hours" |
| Disk usage >85% | Yellow | "Disk at {pct}% — rotation needed" |
| Follow-up overdue | Yellow | "{client} follow-up is {n} days overdue" |
| Payment pending >5 days | Yellow | "Payment from {client} pending {n} days — ${amount}" |
| VPN disconnected | Red | "VPN is DOWN — trading paused" |

Alerts are evaluated server-side (FastAPI background task every 60s) and stored in Redis `bob:alerts`. Dashboard fetches and renders on each poll cycle.

---

### 6. Docker Service

Add `mission-control` service to docker-compose.yml:
- Port 8098
- Volume mount `/var/run/docker.sock:/var/run/docker.sock:ro` (for Docker socket access)
- Depends on Redis, bobs-brain
- Health endpoint at `/health`

No external CSS/JS frameworks. The dashboard must load in <1 second on local network.
