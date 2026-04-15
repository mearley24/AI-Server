## Dashboard Activation + X-Intake Test

You are working on ~/AI-Server on Bob.

### Goal

Pull latest, restart the mobile gateway so the new dashboard loads, then verify x-intake works end-to-end by submitting a test URL.

### Step 1 -- Pull

```zsh
bash scripts/pull.sh
```

### Step 2 -- Restart the mobile gateway

The gateway caches dashboard HTML at import time. Must restart to pick up changes.

```zsh
launchctl unload ~/Library/LaunchAgents/com.symphony.mobile-api.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.symphony.mobile-api.plist
```

Verify it's running:

```zsh
curl -s http://127.0.0.1:8420/health | python3 -m json.tool
```

### Step 3 -- Verify dashboard loads

```zsh
curl -s http://127.0.0.1:8420/dashboard -o /dev/null -w "%{http_code}"
```

Should return 200.

### Step 4 -- Test x-intake analysis

Submit a test tweet URL through the new gateway endpoint:

```zsh
curl -s -X POST http://127.0.0.1:8420/api/x-intake-test \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/elonmusk/status/1911901037498257875"}' | python3 -m json.tool
```

This calls x-intake's /analyze endpoint. Check the response:
- If you get a result with `relevance`, `summary`, `post_type` -- x-intake is working
- If you get `"error"` -- check `docker logs x-intake --tail 30` and report

### Step 5 -- Verify the item appeared in the queue

```zsh
curl -s http://127.0.0.1:8420/proxy/x-intake/queue/stats | python3 -m json.tool
```

The `pending` count should have increased by 1.

### Step 6 -- Test markdown file viewer

```zsh
curl -s http://127.0.0.1:8420/files/STATUS_REPORT.md -o /dev/null -w "%{http_code}"
```

Should return 200.

### Step 7 -- Verify Ops tab endpoints work

```zsh
curl -s http://127.0.0.1:8420/proxy/cortex/health | python3 -m json.tool
curl -s http://127.0.0.1:8420/proxy/openclaw/health | python3 -m json.tool
curl -s http://127.0.0.1:8420/proxy/x-intake/queue/stats | python3 -m json.tool
```

All should return JSON, not errors.

### Output

Report:
- Gateway health status
- X-intake test result (did the tweet get analyzed and queued?)
- Markdown viewer working?
- Any service endpoints returning errors from Ops tab proxies

Fix any issues found and commit:

```zsh
git add -A && git commit -m "fix: dashboard activation adjustments" && git push
```
