# Cline Prompt: Verify All Services + Ingest All Received X Links

## IMPORTANT — Read First
Read `STATUS_REPORT.md` and `CLAUDE.md` before making any changes.

## Task 1: Verify All Services Are Running

### 1.1 Docker services
```
docker compose ps
```
Every service should show `Up` or `Up (healthy)`. If any are down, bring them up:
```
docker compose up -d --build
```

### 1.2 Health checks
Run each and confirm HTTP 200 / valid response:
```
curl -s http://127.0.0.1:8099/health
curl -s http://127.0.0.1:8102/health
curl -s http://127.0.0.1:8092/health
curl -s http://127.0.0.1:8095/health
curl -s http://127.0.0.1:8101/health
curl -s http://127.0.0.1:8103/health
curl -s http://127.0.0.1:8115/health
docker exec redis redis-cli -a "$REDIS_PASSWORD" PING
```

### 1.3 Ollama
```
curl -s http://127.0.0.1:11434/api/tags
ollama ps
```
Confirm `llama3.2:3b` is available. That should be the only model on Bob now.

### 1.4 Markup tool
```
curl -s http://127.0.0.1:8088/health || curl -s http://127.0.0.1:8088/
```
Should be running via launchd. If not, do NOT try to fix it here — just report the status.

### 1.5 Report any failures
List any service that is not healthy. Fix only Docker services (restart/rebuild). Do not touch launchd services or the markup tool.

## Task 2: Ingest All Received X Links

### 2.1 Check the x-intake queue
```
curl -s http://127.0.0.1:8101/queue/stats
curl -s "http://127.0.0.1:8101/queue?status=pending&limit=50"
```

### 2.2 Check Redis for pending iMessage X links
```
docker exec redis redis-cli -a "$REDIS_PASSWORD" LRANGE events:imessage 0 -1
```

### 2.3 Check x-alpha-collector for recent signals
```
docker logs x-alpha-collector --tail 50 2>&1
```

### 2.4 Trigger a manual x-intake scan
If there are pending items in Redis that haven't been processed:
```
docker restart x-intake
```
Wait 30 seconds, then check:
```
curl -s http://127.0.0.1:8101/queue/stats
docker logs x-intake --tail 30 2>&1
```

### 2.5 Trigger x-intake-lab transcript scan
```
docker restart x-intake-lab
```
Wait 30 seconds, then check:
```
curl -s http://127.0.0.1:8103/health
docker logs x-intake-lab --tail 30 2>&1
```

### 2.6 Check Cortex received the data
```
curl -s "http://127.0.0.1:8102/api/memories?limit=10&source=x-intake"
curl -s "http://127.0.0.1:8102/api/memories?limit=10&source=x-intake-lab"
```

If those endpoints don't exist, try:
```
curl -s "http://127.0.0.1:8102/query" -H "Content-Type: application/json" -d '{"query": "latest x intake analysis"}'
```

### 2.7 Check x-alpha-collector is feeding
```
docker logs x-alpha-collector --tail 30 2>&1
curl -s "http://127.0.0.1:8102/api/memories?limit=5&source=x_intel"
```

## Task 3: Report

Print a summary:
- Total Docker services running / total expected
- Any unhealthy services
- x-intake queue stats (pending / processed / auto_approved)
- x-intake-lab status
- x-alpha-collector last run
- Cortex memory count
- Ollama status
- Disk space remaining (`df -h /`)

## DO NOT
- Remove any services
- Change any ports
- Modify any code
- Touch the markup tool on 8088

## Commit
Only commit if you had to fix something. Message: `fix: <what was fixed>`
Push to main.
