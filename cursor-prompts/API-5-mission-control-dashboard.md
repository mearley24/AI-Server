# API-5: Mission Control Dashboard — Wire Real Data Into the UI

## The Problem

The Mission Control container runs on port 8098 and serves a dashboard. `mission_control/main.py` (597 lines) and `event_server.py` (412 lines) define the backend API endpoints. The `dashboard/` directory has `index.html`, `app.js`, and `style.css` but the UI is basic — it does not actually display trading data, email queue status, calendar events, follow-ups, or system resources. The backend data is already flowing into Redis. The job is to build out the real dashboard UI that reads from the existing API endpoints and Redis keys, displayed in six panels on a dark-themed grid layout.

## Context Files to Read First

- `mission_control/main.py` (all 597 lines — understand every API endpoint it exposes)
- `mission_control/event_server.py` (all 412 lines — understand the SSE/WebSocket event format)
- `dashboard/index.html` (current UI structure — understand what is already there)
- `dashboard/app.js` (current JS — understand what it already polls/renders)
- `dashboard/style.css` (current styles — understand what to keep vs upgrade)
- `docker-compose.yml` (understand how mission-control mounts the dashboard directory)
- `AGENTS.md` (Redis key schema overview)

## Prompt

Read the existing code first — understand what API endpoints `main.py` already exposes, what event types `event_server.py` emits, and what the current `app.js` already renders. Do not replace working panels. Upgrade and extend what is there.

### 1. Audit Existing Endpoints and Events

Read `main.py` and list every `@app.get` / `@app.post` route. Read `event_server.py` and list every event type it pushes. These are the data sources for the dashboard — you do not need to invent new Redis reads in the frontend if the backend already aggregates the data.

Create a comment block at the top of `app.js` documenting the available endpoints:

```javascript
/*
 * Mission Control Dashboard — Available Data Sources
 * 
 * REST Endpoints (from main.py):
 *   GET /api/health         → service health statuses
 *   GET /api/portfolio      → trading bot portfolio snapshot
 *   GET /api/email/queue    → email queue stats
 *   GET /api/calendar/today → today's events
 *   GET /api/followups      → pending follow-ups
 *   GET /api/system         → CPU/RAM/disk stats
 * 
 * SSE Stream (from event_server.py):
 *   GET /events             → Server-Sent Events for real-time updates
 * 
 * Redis Keys (read by main.py, not directly by dashboard):
 *   portfolio:snapshot, email:*, calendar:*, followup:*, system:*
 */
```

Fill in the actual endpoints from the code — do not guess.

### 2. Build the Six-Panel Layout in index.html

Replace or upgrade `dashboard/index.html` with a CSS Grid layout:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bob — Mission Control</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>Mission Control</h1>
    <div id="last-updated">Last updated: —</div>
    <div id="connection-status" class="status-indicator"></div>
  </header>

  <main class="dashboard-grid">
    <section class="panel" id="panel-services">
      <h2>Service Health</h2>
      <div id="service-list"></div>
    </section>

    <section class="panel" id="panel-trading">
      <h2>Trading Bot</h2>
      <div id="trading-summary"></div>
      <div id="open-positions"></div>
      <div id="recent-trades"></div>
    </section>

    <section class="panel" id="panel-email">
      <h2>Email Queue</h2>
      <div id="email-stats"></div>
      <div id="pending-drafts"></div>
      <div id="recent-responses"></div>
    </section>

    <section class="panel" id="panel-calendar">
      <h2>Today's Calendar</h2>
      <div id="calendar-events"></div>
    </section>

    <section class="panel" id="panel-followups">
      <h2>Follow-Ups</h2>
      <div id="followup-list"></div>
    </section>

    <section class="panel" id="panel-system">
      <h2>System Resources</h2>
      <div id="system-stats"></div>
    </section>
  </main>

  <script src="app.js"></script>
</body>
</html>
```

### 3. Build the Dashboard Logic in app.js

Use vanilla JavaScript — no React, no Vue, no heavy frameworks. Write functions that fetch from the backend and render into the panel divs.

**Auto-refresh every 30 seconds:**

```javascript
const REFRESH_INTERVAL = 30_000;

async function refreshAll() {
  const timestamp = new Date().toLocaleTimeString();
  document.getElementById("last-updated").textContent = `Last updated: ${timestamp}`;
  
  await Promise.allSettled([
    refreshServices(),
    refreshTrading(),
    refreshEmail(),
    refreshCalendar(),
    refreshFollowups(),
    refreshSystem(),
  ]);
}

refreshAll();
setInterval(refreshAll, REFRESH_INTERVAL);
```

**Service Health panel** — call the endpoint from main.py that returns container statuses:

```javascript
async function refreshServices() {
  const data = await fetchJSON("/api/health");
  const container = document.getElementById("service-list");
  container.innerHTML = data.services.map(svc => `
    <div class="service-row">
      <span class="status-dot ${svc.status}"></span>
      <span class="service-name">${svc.name}</span>
      <span class="service-uptime">${svc.uptime || ""}</span>
    </div>
  `).join("");
}
```

(Use the actual response shape from main.py — read what `/api/health` actually returns and match it.)

**Trading Bot panel** — read from `portfolio:snapshot` via whatever endpoint main.py exposes:

```javascript
async function refreshTrading() {
  const data = await fetchJSON("/api/portfolio");
  document.getElementById("trading-summary").innerHTML = `
    <div class="stat-row">
      <span>Available</span><span class="value">$${data.usdc_balance.toFixed(2)}</span>
    </div>
    <div class="stat-row">
      <span>Positions</span><span class="value">$${data.total_position_value.toFixed(2)}</span>
    </div>
    <div class="stat-row">
      <span>Portfolio</span><span class="value highlight">$${data.total_portfolio_value.toFixed(2)}</span>
    </div>
    <div class="stat-row">
      <span>24h P&L</span><span class="value ${data.pnl_24h >= 0 ? 'positive' : 'negative'}">
        ${data.pnl_24h >= 0 ? '+' : ''}$${data.pnl_24h.toFixed(2)}
      </span>
    </div>
  `;
  document.getElementById("open-positions").innerHTML = 
    `<div class="subheader">Open Positions: ${data.positions?.length || 0}</div>` +
    (data.positions || []).slice(0, 5).map(p => `
      <div class="position-row">
        <span>${p.market_title?.substring(0, 40) || p.condition_id}</span>
        <span>${p.side} ${p.shares?.toFixed(1)} shares</span>
      </div>
    `).join("");
}
```

Match the actual field names from `main.py`'s portfolio endpoint response — do not assume.

**Email Queue panel:**

```javascript
async function refreshEmail() {
  const data = await fetchJSON("/api/email/queue");
  document.getElementById("email-stats").innerHTML = `
    <div class="stat-row"><span>Unread</span><span class="value">${data.unread_count}</span></div>
    <div class="stat-row"><span>Pending Drafts</span><span class="value">${data.pending_drafts}</span></div>
    <div class="stat-row"><span>Auto-Responses Sent</span><span class="value">${data.auto_responses_today}</span></div>
  `;
}
```

**Calendar panel:**

```javascript
async function refreshCalendar() {
  const data = await fetchJSON("/api/calendar/today");
  const events = data.events || [];
  document.getElementById("calendar-events").innerHTML = events.length === 0
    ? "<div class='empty-state'>No events today</div>"
    : events.map(evt => `
        <div class="calendar-event">
          <span class="event-time">${evt.time || evt.start}</span>
          <span class="event-title">${evt.title || evt.summary}</span>
        </div>
      `).join("");
}
```

**Follow-Ups panel:**

```javascript
async function refreshFollowups() {
  const data = await fetchJSON("/api/followups");
  const items = data.followups || [];
  document.getElementById("followup-list").innerHTML = items.length === 0
    ? "<div class='empty-state'>No pending follow-ups</div>"
    : items.map(f => `
        <div class="followup-row ${f.overdue ? 'overdue' : ''}">
          <span class="followup-client">${f.client}</span>
          <span class="followup-due">${f.due_date || f.due}</span>
        </div>
      `).join("");
}
```

**System Resources panel:**

```javascript
async function refreshSystem() {
  const data = await fetchJSON("/api/system");
  document.getElementById("system-stats").innerHTML = `
    <div class="resource-bar">
      <span>CPU</span>
      <div class="bar-track"><div class="bar-fill" style="width:${data.cpu_percent}%"></div></div>
      <span>${data.cpu_percent?.toFixed(1)}%</span>
    </div>
    <div class="resource-bar">
      <span>RAM</span>
      <div class="bar-track"><div class="bar-fill" style="width:${data.ram_percent}%"></div></div>
      <span>${data.ram_percent?.toFixed(1)}%</span>
    </div>
    <div class="resource-bar">
      <span>Disk</span>
      <div class="bar-track"><div class="bar-fill" style="width:${data.disk_percent}%"></div></div>
      <span>${data.disk_percent?.toFixed(1)}%</span>
    </div>
  `;
}
```

**Error handling:**

```javascript
async function fetchJSON(url) {
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (e) {
    console.warn(`fetchJSON failed for ${url}:`, e);
    return {};
  }
}
```

### 4. Dark Theme in style.css

Replace or upgrade `style.css` with a dark theme:

```css
:root {
  --bg-primary: #0d0d0d;
  --bg-panel: #1a1a1a;
  --bg-panel-header: #222222;
  --border: #2e2e2e;
  --text-primary: #e8e8e8;
  --text-secondary: #999999;
  --accent-green: #00e676;
  --accent-yellow: #ffd740;
  --accent-red: #ff5252;
  --accent-blue: #40c4ff;
}

body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: "SF Mono", "Fira Code", monospace;
  margin: 0;
  padding: 16px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-top: 16px;
}

.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}

.panel h2 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
  margin: 0 0 12px;
}

.status-dot.healthy { color: var(--accent-green); }
.status-dot.degraded { color: var(--accent-yellow); }
.status-dot.down { color: var(--accent-red); }

.value.positive { color: var(--accent-green); }
.value.negative { color: var(--accent-red); }
.value.highlight { color: var(--accent-blue); font-weight: bold; }

.bar-track { background: #333; border-radius: 4px; height: 6px; flex: 1; margin: 0 8px; }
.bar-fill { background: var(--accent-blue); height: 100%; border-radius: 4px; }

.overdue { color: var(--accent-red); }
.empty-state { color: var(--text-secondary); font-style: italic; }

@media (max-width: 1200px) { .dashboard-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 768px) { .dashboard-grid { grid-template-columns: 1fr; } }
```

### 5. Verify It Runs on Port 8098

After building the dashboard:

- Confirm `docker-compose.yml` mounts the `dashboard/` directory into the mission-control container at the path that main.py serves static files from
- If main.py serves static files from `mission_control/static/` but the files are in `dashboard/`, either update the mount path or move the files — check the Dockerfile or docker-compose volume mounts
- Confirm main.py has a static file handler — if not, add `app.mount("/", StaticFiles(directory="static"), name="static")` (FastAPI) or equivalent
- Test: `curl http://localhost:8098/` should return the HTML, not a 404

Do not change the port. Do not add nginx. The existing container already serves on 8098 — just make sure the dashboard files are in the right directory.
