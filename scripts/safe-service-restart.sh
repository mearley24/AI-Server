#!/usr/bin/env bash
# safe-service-restart.sh — Restart one compose service without touching Docker Desktop.
#
# Usage: bash scripts/safe-service-restart.sh <service>
#
# Behavior:
#   1. Check docker ps once (bounded 10s).
#   2. If Docker is healthy → docker compose restart <service>.
#   3. If Docker is unhealthy → call docker-recover.sh (engine recovery first).
#   4. Never restarts full Docker Desktop just because one container is unhealthy.

set -uo pipefail

SERVICE="${1:-}"
if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$REPO_DIR/docker-compose.yml" ]]; then
    echo "ERROR: docker-compose.yml not found at $REPO_DIR"
    exit 1
fi

# ── One bounded health check (10s) ───────────────────────────────────────────
docker_healthy() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 10 docker ps -q >/dev/null 2>&1
        return $?
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout 10 docker ps -q >/dev/null 2>&1
        return $?
    fi
    # Fallback: background job + wall-clock kill
    docker ps -q >/dev/null 2>&1 &
    local pid=$! waited=0
    while (( waited < 10 )); do
        kill -0 "$pid" 2>/dev/null || { wait "$pid"; return $?; }
        sleep 1; waited=$(( waited + 1 ))
    done
    kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 1
}

echo "=== safe-service-restart: $SERVICE ==="

if docker_healthy; then
    echo "Docker healthy. Running: docker compose restart $SERVICE"
    cd "$REPO_DIR"
    docker compose restart "$SERVICE"
    exit $?
fi

# ── Docker engine unhealthy — escalate to recovery before retrying ────────────
echo "Docker engine unhealthy. Calling docker-recover.sh first..."
RECOVER="$SCRIPT_DIR/docker-recover.sh"
if [[ ! -x "$RECOVER" ]]; then
    echo "ERROR: $RECOVER not found or not executable"
    exit 1
fi

"$RECOVER"
rc=$?
if (( rc != 0 )); then
    echo "docker-recover.sh failed (exit $rc). Cannot restart $SERVICE."
    exit "$rc"
fi

echo "Recovery succeeded. Restarting $SERVICE..."
cd "$REPO_DIR"
docker compose restart "$SERVICE"
