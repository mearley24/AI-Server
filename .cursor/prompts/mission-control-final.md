# Mission Control Dashboard — Final Polish

## Context
`mission_control/static/index.html` is a 6-panel ops dashboard (Service Health, Trading P&L, Email, Calendar, Follow-ups, System). The backend runs at port 8098, API endpoints defined in `mission_control/main.py` and `mission_control/event_server.py`.

## Known Bugs to Fix

### 1. "Invalid Date" everywhere
The `formatRelative()`, `formatTime()`, and `formatDuration()` functions use `new Date(dateStr)` which returns "Invalid Date" for non-ISO strings. Fix:
- Add a guard: if `isNaN(d.getTime())` return a fallback like `''` or the raw string
- Handle Unix timestamps (numbers), ISO strings, and partial date strings like `"2026-04-03"` or `"03/25 12:55PM"`

### 2. Font sizing / layout
The tiles fill the viewport now but the overall sizing should feel native and comfortable to read on any screen. Use `clamp()` for key font sizes so they scale between mobile and desktop:
- Tile labels: `clamp(12px, 1.2vw, 14px)`
- Service names, email from, calendar titles, followup text: `clamp(12px, 1.1vw, 14px)`
- Secondary text (subjects, locations, ports, due dates): `clamp(11px, 1vw, 13px)`
- Hero P&L number: `clamp(28px, 3vw, 42px)`
- Mini stats, badge text: `clamp(11px, 1vw, 13px)`
- System bar labels/values: `clamp(12px, 1.1vw, 14px)`
- Employee names: `clamp(12px, 1.1vw, 14px)`

### 3. Row padding
Email rows, calendar rows, followup rows, and employee cards need more breathing room:
- Row padding: `8px 0` instead of `5px 0`
- Min-height: `40px` instead of `32px`
- Service pill padding: `8px 10px`

## New Features to Add

### 4. Sidebar Navigation Menu
Add a collapsible left sidebar (56px collapsed showing icons only, 200px expanded). Toggle with a hamburger button in the topbar. The sidebar provides navigation to different views:
- **Dashboard** (current view, grid icon) — active by default
- **Trading** (chart icon) — links to `/api/trading/bot-status` data in a dedicated view, or just scrolls to trading tile for now
- **Events** (list icon) — shows the full event log from `GET /events?limit=50`
- **Digest** (document icon) — shows the daily digest from `GET /digest`
- **Settings** (gear icon) — placeholder for future

The sidebar should:
- Float over content on mobile (overlay with backdrop)
- Push content on desktop (> 900px)
- Remember collapsed/expanded state in localStorage
- Use SF Symbols-style simple SVG icons
- Active item highlighted with accent color pill

### 5. Quick Actions Bar
Add a row of quick-action buttons between the topbar and the grid:
- **Refresh All** — re-fetches all 6 panels immediately
- **Bot Status** — fetches `GET /api/trading/bot-status` and shows a popup/toast with key info (bankroll, open positions, strategy status)
- **View Logs** — fetches `GET /events?limit=20` and shows in a slide-up panel
- **Daily Digest** — fetches `GET /digest` and shows formatted markdown in a modal

Style: small pill buttons, `rgba(255,255,255,0.06)` background, 12px text, horizontal scroll on mobile.

### 6. Tile Click-to-Expand
Clicking a tile header should toggle between compact (grid) and expanded (full-width, taller, more detail) views:
- Service Health expanded: show port numbers, last check time, response details
- Trading expanded: show full category breakdown table with bought/sold/redeemed/open columns
- Email expanded: show more emails, full subject lines
- Calendar expanded: show full event descriptions
- Follow-ups expanded: show source and assigned_to
- System expanded: show all containers with uptime

Use a smooth CSS transition. Only one tile expanded at a time (clicking another collapses the current one).

### 7. Toast Notification System
When WebSocket receives events, show a brief toast notification in the bottom-right:
- Dark card with accent left border
- `[employee] title` in 13px
- Auto-dismiss after 4 seconds
- Stack up to 3 toasts, oldest dismissed first
- Clicking a toast dismisses it

### 8. Topbar Enhancements
- Add a small "last refreshed" timestamp next to the clock: `"Updated 30s ago"` in muted text
- The WS dot should pulse gently when receiving events (CSS animation)
- Add the total portfolio value next to Mission Control title if trading data is loaded: `Mission Control · $148.29`

### 9. Service Health Tile — Status History Sparkline
For each service, keep the last 10 health check results in JS memory (an array of true/false). Render as a tiny 10-dot row next to each service name showing green/red history. This gives at-a-glance stability info without any backend changes.

### 10. Trading Tile — Live Position Count
Show "38 positions" (or whatever the count is) as a subtle tag next to the P&L hero number. Pull from the `activity_count` or add a fetch to `/api/trading/bot-status` to get `open_positions`.

## Implementation Notes
- Edit `mission_control/static/index.html` in place — it's a single-file vanilla HTML/CSS/JS dashboard
- Chart.js is already loaded via CDN
- All API endpoints are relative (same origin on port 8098)
- The WebSocket connects to `/ws` on the same host
- Test by rebuilding: `docker compose build --no-cache mission-control && docker compose up -d mission-control`
- Timezone is always America/Denver for display
- Keep the Apple dark aesthetic: `#000000` background, `#1c1c1e` tiles, `border-radius: 16px`
- Do NOT break any existing functionality — all 6 panels must still load and refresh on their intervals
