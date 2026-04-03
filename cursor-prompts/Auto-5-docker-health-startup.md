# Auto-5: Docker Health Checks & Startup Orchestration

## Context Files to Read First
- docker-compose.yml
- scripts/imessage-server.py
- polymarket-bot/src/main.py
- .env

## Prompt

Add Docker health checks and a startup orchestration script so the whole stack comes up clean after a reboot:

1. Health checks in docker-compose.yml for every service:
   - Redis: `redis-cli ping` every 10s, 3 retries
   - Polymarket bot: check that the main loop is alive (create a `/health` endpoint or write a heartbeat file every 60s, healthcheck reads it)
   - Bob email router: check that IMAP connection is alive
   - Paper trader: heartbeat file check like polymarket bot
   - Any other services — add appropriate checks

2. Startup dependencies (`depends_on` with `condition: service_healthy`):
   - Redis starts first, everything else waits for it to be healthy
   - Polymarket bot waits for Redis
   - Paper trader waits for Redis
   - Intel feeds wait for Redis

3. Create `scripts/startup.sh`:
   - Starts the iMessage bridge first (runs on host, not Docker): `OPENAI_API_KEY=$(grep OPENAI_API_KEY .env | head -1 | cut -d= -f2) nohup python3 scripts/imessage-server.py > /tmp/imessage-bridge.log 2>&1 &`
   - Waits for iMessage bridge to respond on port 8199
   - Then runs `docker compose up -d --build`
   - Tails logs for 30s to verify clean startup
   - Sends iMessage to Matt (+19705193013) confirming "Bob is online — all services healthy" with a list of running containers

4. Create `scripts/healthcheck.sh`:
   - Checks all Docker container health statuses
   - Checks iMessage bridge on port 8199
   - If anything is unhealthy: restart it and notify Matt via iMessage
   - Can be run by cron every 5 min on the Mac Mini

5. Add a `restart` policy to all services: `restart: unless-stopped`

Remember: config changes require `docker compose up -d --build [service]`, never just restart. Redis is at 172.18.0.100:6379 inside Docker. Use standard logging (not structlog) for host scripts.
