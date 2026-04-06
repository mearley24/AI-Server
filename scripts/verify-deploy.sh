#!/usr/bin/env bash
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"
FAIL=0
echo "=== Manifest: expected files ==="
MANIFEST=(
  "openclaw/main.py"
  "openclaw/orchestrator.py"
  "openclaw/doc_staleness.py"
  "openclaw/doc_generator.py"
  "openclaw/zoho_auth.py"
  "mission_control/main.py"
  "docker-compose.yml"
)
for f in "${MANIFEST[@]}"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
    FAIL=1
  fi
done
echo ""
echo "=== Redis PING (container) ==="
if docker exec redis redis-cli PING 2>/dev/null | grep -q PONG; then
  echo "OK redis PONG"
else
  echo "FAIL redis not responding"
  FAIL=1
fi

echo ""
echo "=== Redis static IP (expect 172.18.0.100) ==="
RIP="$(docker inspect redis --format '{{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}' 2>/dev/null || true)"
if [ "$RIP" = "172.18.0.100" ]; then
  echo "OK redis IP=$RIP"
else
  echo "WARN redis IP=$RIP (polymarket-bot uses REDIS_URL=redis://172.18.0.100:6379)"
fi

echo ""
echo "=== HTTP health ==="
for pair in "http://127.0.0.1:8098/health mission-control" "http://127.0.0.1:8099/health openclaw"; do
  url="${pair%% *}"
  name="${pair##* }"
  if curl -sfS --connect-timeout 3 "$url" >/dev/null; then
    echo "OK $name"
  else
    echo "FAIL $name"
    FAIL=1
  fi
done
echo ""
echo "=== Redis events:log (sample) ==="
if docker exec redis redis-cli LRANGE events:log 0 0 >/dev/null 2>&1; then
  docker exec redis redis-cli LRANGE events:log 0 2 || true
else
  echo "(redis not reachable)"
fi
echo ""
echo "=== polymarket-bot redeemer (optional) ==="
if curl -sfS --connect-timeout 3 "http://127.0.0.1:8430/redeem/status" 2>/dev/null | head -c 400; then
  echo ""
  echo "OK /redeem/status reachable"
else
  echo "WARN polymarket-bot /redeem/status not reachable (bot/vpn down or warming up)"
fi

echo ""
echo "=== SQLite DBs ==="
for db in "data/openclaw/jobs.db" "data/email-monitor/emails.db"; do
  if [ -f "$db" ]; then echo "OK exists $db"; else echo "WARN missing $db"; fi
done
echo ""
if [ "$FAIL" -ne 0 ]; then echo "verify-deploy: FAILED"; exit 1; fi
echo "verify-deploy: OK"
exit 0
