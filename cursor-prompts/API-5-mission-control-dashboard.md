# API-5: Mission Control Dashboard

## Context Files to Read First
- mission_control/main.py
- mission_control/event_server.py
- docker-compose.yml (all service definitions)
- AGENTS.md (architecture overview)
- polymarket-bot/heartbeat/runner.py

## Prompt

Build Mission Control — a real-time web dashboard showing the health and status of all 16+ services running on Bob:

1. Backend (`mission_control/main.py` — expand existing):
   - FastAPI server on port 8095
   - WebSocket endpoint `/ws/events` for real-time updates
   - REST endpoints:
     - `GET /api/services` — all service statuses (Docker container health, uptime, restart count)
     - `GET /api/polymarket` — trading P/L, positions, bankroll, recent trades
     - `GET /api/email` — email routing stats (processed, auto-responded, forwarded)
     - `GET /api/tasks` — task board summary (pending, in progress, completed today)
     - `GET /api/system` — Mac Mini CPU, RAM, disk, Docker resource usage
   - Poll Docker socket every 10s for container states
   - Subscribe to Redis pub/sub for real-time events from all services

2. Frontend (`mission_control/static/index.html` — single-page app):
   - Dark mode, grid layout, responsive
   - Service cards showing: name, status (green/yellow/red), uptime, last restart
   - Polymarket widget: P/L chart (last 7 days), current positions count, bankroll
   - Email widget: today's email count by action (routed, auto-responded, escalated)
   - iMessage widget: recent messages sent/received
   - System resources: CPU/RAM/disk gauges
   - Activity feed: real-time log of events from all services (WebSocket)
   - Auto-refresh every 10s, WebSocket for instant updates

3. Alerts section:
   - Any container that restarts >3 times in an hour → red alert
   - Any service unhealthy for >5 minutes → yellow alert
   - Polymarket bankroll drop >20% in 24h → red alert
   - Disk usage >85% → yellow alert

4. Add to docker-compose.yml as `mission-control` service, port 8095.

5. Add a health endpoint at `/health` for Docker healthcheck.

No external CSS/JS frameworks — use vanilla HTML/CSS/JS with CSS Grid. Keep it lightweight. The dashboard should load in <1 second on local network.
