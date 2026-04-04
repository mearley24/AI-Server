#!/usr/bin/env bash
# Symphony — one-shot Docker build/up + verify (close-the-loop stack on Bob).
# Usage: ./scripts/symphony-ship.sh [ship|verify|restart|full|help]
set -euo pipefail

ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"

usage() {
  cat <<'EOF'
symphony-ship.sh — build/up/verify for the core Symphony loop stack.

Commands:
  ship    Build openclaw + polymarket-bot, start core stack, run checks (default).
  verify  Only health / Redis events:log / HTTP checks (no build).
  restart Quick: restart openclaw, polymarket-bot, mission-control (after bind-mount edits).
  full    docker compose up -d (entire compose file).

Env:
  SYMPHONY_ROOT  Repo path (default: ~/AI-Server)
EOF
}

# Core services for the autonomous loop (matches close-the-loop bring-up).
LOOP_SERVICES=(redis vpn polymarket-bot openclaw mission-control)

verify() {
  set +e
  echo "=== Redis PING ==="
  docker exec redis redis-cli PING
  echo ""
  echo "=== events:log (newest 3) ==="
  docker exec redis redis-cli LRANGE events:log 0 2
  echo ""
  echo "=== OpenClaw :8099/health ==="
  curl -sfS --connect-timeout 3 "http://127.0.0.1:8099/health" || echo "(fail)"
  echo ""
  echo "=== Mission Control :8098/health ==="
  curl -sfS --connect-timeout 3 "http://127.0.0.1:8098/health" || echo "(fail)"
  echo ""
  echo "=== OpenClaw /intelligence/events-log?limit=5 ==="
  curl -sfS --connect-timeout 3 "http://127.0.0.1:8099/intelligence/events-log?limit=5" | head -c 800 || echo "(fail)"
  echo ""
  echo ""
  echo "=== Polymarket bot :8430/health (via VPN publish) ==="
  curl -sfS --connect-timeout 3 "http://127.0.0.1:8430/health" | head -c 400 || echo "(fail)"
  echo ""
  set -e
  echo "=== Done ==="
}

case "${1:-ship}" in
  ship|loop)
    docker compose build openclaw polymarket-bot
    docker compose up -d "${LOOP_SERVICES[@]}"
    sleep 3
    verify
    ;;
  verify)
    verify
    ;;
  restart)
    docker compose restart openclaw polymarket-bot mission-control
    sleep 2
    verify
    ;;
  full)
    docker compose up -d
    sleep 5
    verify
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
