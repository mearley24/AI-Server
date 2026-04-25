#!/usr/bin/env bash
# docker-recover.sh — Safe Docker Desktop recovery
#
# Policy (2026-04-25):
#   - Never declared unhealthy until docker ps fails for 30+ seconds (6 x 5s probes).
#   - Graceful quit before any kill; waits up to 20s for com.docker.backend to exit.
#   - Force-kill only after graceful exit stalls.
#   - Never reopens Docker Desktop until old backend processes are gone.
#   - 5-minute cooldown prevents back-to-back invocations.
#
# Usage: bash scripts/docker-recover.sh [--force]
#   --force  skip the cooldown check (operator-initiated recovery only)

set -uo pipefail

COOLDOWN_FILE="/tmp/docker-recover-cooldown"
COOLDOWN_SECS=300
FORCE=0
for arg in "$@"; do [[ "$arg" == "--force" ]] && FORCE=1; done

# ── Cooldown gate ─────────────────────────────────────────────────────────────
if (( FORCE == 0 )) && [[ -f "$COOLDOWN_FILE" ]]; then
    last=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    elapsed=$(( now - last ))
    if (( elapsed < COOLDOWN_SECS )); then
        remaining=$(( COOLDOWN_SECS - elapsed ))
        echo "docker-recover: cooldown active (${elapsed}s elapsed, ${remaining}s remaining). Use --force to override."
        exit 0
    fi
fi

# ── Probe: confirm Docker is actually unhealthy (30s / 6 x 5s) ───────────────
echo "=== docker-recover: probing Docker engine (30s max) ==="
healthy=0
for i in 1 2 3 4 5 6; do
    if docker ps >/dev/null 2>&1; then
        healthy=1
        break
    fi
    echo "  probe ${i}/6 failed — waiting 5s..."
    sleep 5
done

if (( healthy )); then
    echo "Docker engine OK — no recovery needed."
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    exit 0
fi

echo "Docker unhealthy after 30s probe. Starting recovery (cooldown stamped)."
echo "$(date +%s)" > "$COOLDOWN_FILE"

# ── Step 1: Graceful quit ─────────────────────────────────────────────────────
echo "Requesting Docker Desktop to quit gracefully..."
osascript -e 'quit app "Docker"' 2>/dev/null || true

# ── Step 2: Wait for com.docker.backend to exit before reopening (20s max) ───
echo "Waiting for com.docker.backend to exit (up to 20s)..."
exit_waited=0
while pgrep -f "com.docker.backend" >/dev/null 2>&1; do
    if (( exit_waited >= 20 )); then
        echo "  still alive after ${exit_waited}s — force-killing"
        pkill -KILL -f "com.docker.backend" 2>/dev/null || true
        pkill -KILL -f "Docker Desktop Helper" 2>/dev/null || true
        pkill -KILL -f "vpnkit" 2>/dev/null || true
        sleep 3
        break
    fi
    sleep 2
    exit_waited=$(( exit_waited + 2 ))
done

if ! pgrep -f "com.docker.backend" >/dev/null 2>&1; then
    echo "  com.docker.backend exited after ${exit_waited}s."
fi

# ── Step 3: Reopen Docker Desktop ────────────────────────────────────────────
echo "Reopening Docker Desktop..."
open -a Docker

# ── Step 4: Wait for engine recovery (5 min max) ─────────────────────────────
echo "Waiting for Docker engine to become ready..."
waited=0
while (( waited < 300 )); do
    sleep 5
    waited=$(( waited + 5 ))
    if docker ps >/dev/null 2>&1; then
        echo "Docker recovered after ${waited}s."
        docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
        exit 0
    fi
done

echo "ERROR: Docker did not recover after 5 minutes."
exit 1
