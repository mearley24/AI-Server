#!/usr/bin/env bash
# scripts/verify-deploy.sh — post-deploy smoke test.
# Replaces the dissolved mission-control probe with cortex (8102) and adds
# coverage for email-monitor, notification-hub, proposals, calendar-agent.
# See CLAUDE.md + STATUS_REPORT.md (Cortex merged mission-control 2026-04-12).
set -euo pipefail
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"
FAIL=0

# Load REDIS_PASSWORD from .env without polluting the shell or echoing values.
# (close-yellow-gaps 2026-04-21: previous PING had no -a flag -> NOAUTH -> false FAIL.)
REDIS_PASSWORD=""
if [ -z "${REDIS_PASSWORD:-}" ] && [ -f "$ROOT/.env" ]; then
  REDIS_PASSWORD="$(grep -E '^REDIS_PASSWORD=' "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
REDIS_AUTH_ARGS=()
if [ -n "$REDIS_PASSWORD" ]; then
  REDIS_AUTH_ARGS=(-a "$REDIS_PASSWORD" --no-auth-warning)
fi

echo "=== Manifest: expected files ==="
# Manifest covers the canonical orchestrator + brain + compose surface.
# mission_control/main.py removed — dissolved into cortex (Prompt S).
MANIFEST=(
  "openclaw/main.py"
  "openclaw/orchestrator.py"
  "openclaw/doc_staleness.py"
  "openclaw/doc_generator.py"
  "openclaw/zoho_auth.py"
  "cortex/engine.py"
  "cortex/dashboard.py"
  "cortex/memory.py"
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
if docker exec redis redis-cli "${REDIS_AUTH_ARGS[@]}" PING 2>/dev/null | grep -q PONG; then
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
# Canonical service port map (see .clinerules / CLAUDE.md).
# openclaw 8099, cortex 8102, email-monitor 8092, notification-hub 8095,
# proposals 8091, calendar-agent 8094. Client-portal intentionally internal.
HTTP_TARGETS=(
  "http://127.0.0.1:8099/health openclaw"
  "http://127.0.0.1:8102/health cortex"
  "http://127.0.0.1:8092/health email-monitor"
  "http://127.0.0.1:8095/health notification-hub"
  "http://127.0.0.1:8091/health proposals"
  "http://127.0.0.1:8094/health calendar-agent"
)
for pair in "${HTTP_TARGETS[@]}"; do
  url="${pair%% *}"
  name="${pair##* }"
  if curl -sfS --connect-timeout 3 "$url" >/dev/null; then
    echo "OK $name"
  else
    echo "FAIL $name ($url)"
    FAIL=1
  fi
done

echo ""
echo "=== Redis events:log (sample) ==="
if docker exec redis redis-cli "${REDIS_AUTH_ARGS[@]}" LRANGE events:log 0 0 >/dev/null 2>&1; then
  docker exec redis redis-cli "${REDIS_AUTH_ARGS[@]}" LRANGE events:log 0 2 || true
else
  echo "(redis not reachable)"
fi

echo ""
echo "=== polymarket-bot redeemer (optional, routes via VPN) ==="
if curl -sfS --connect-timeout 3 "http://127.0.0.1:8430/redeem/status" 2>/dev/null | head -c 400; then
  echo ""
  echo "OK /redeem/status reachable"
else
  echo "WARN polymarket-bot /redeem/status not reachable (bot/vpn down or warming up)"
fi

echo ""
echo "=== SQLite DBs ==="
for db in \
  "data/openclaw/jobs.db" \
  "data/openclaw/decision_journal.db" \
  "data/email-monitor/emails.db" \
  "data/email-monitor/follow_ups.db" \
  "data/cortex/brain.db"; do
  if [ -f "$db" ]; then echo "OK exists $db"; else echo "WARN missing $db"; fi
done

echo ""
if [ "$FAIL" -ne 0 ]; then echo "verify-deploy: FAILED"; exit 1; fi
echo "verify-deploy: OK"
exit 0
