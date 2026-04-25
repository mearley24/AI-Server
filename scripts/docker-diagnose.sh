#!/usr/bin/env bash
# docker-diagnose.sh — Docker Desktop health diagnostic snapshot.
#
# Prints:
#   - docker ps status
#   - Docker-related PIDs
#   - launchctl docker entries
#   - com.docker.socket / vmnetd status
#   - Last 50 Docker Desktop log lines (if available)

echo "=== docker-diagnose.sh — $(date) ==="
echo ""

# ── 1. docker ps ─────────────────────────────────────────────────────────────
echo "--- docker ps ---"
if command -v timeout >/dev/null 2>&1; then
    timeout 10 docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 \
        && echo "(exit 0 — OK)" || echo "(docker ps failed or timed out)"
elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout 10 docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 \
        && echo "(exit 0 — OK)" || echo "(docker ps failed or timed out)"
else
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 \
        && echo "(exit 0 — OK)" || echo "(docker ps failed)"
fi
echo ""

# ── 2. Docker-related PIDs ───────────────────────────────────────────────────
echo "--- Docker Desktop PIDs ---"
echo "com.docker.backend:"
pgrep -fa "com.docker.backend" 2>/dev/null || echo "  (none)"
echo "Docker Desktop:"
pgrep -fa "Docker Desktop" 2>/dev/null | grep -v "grep" || echo "  (none)"
echo "vpnkit:"
pgrep -fa "vpnkit" 2>/dev/null || echo "  (none)"
echo "docker-proxy:"
pgrep -fa "docker-proxy" 2>/dev/null || echo "  (none)"
echo ""

# ── 3. launchctl docker entries ──────────────────────────────────────────────
echo "--- launchctl list (docker-related) ---"
launchctl list 2>/dev/null | grep -i "docker" || echo "(none found)"
echo ""

# ── 4. com.docker.socket and vmnetd ─────────────────────────────────────────
echo "--- com.docker.socket ---"
launchctl print system/com.docker.socket 2>/dev/null | head -6 \
    || echo "  (not loaded in system domain)"
echo ""
echo "--- com.docker.vmnetd ---"
launchctl print system/com.docker.vmnetd 2>/dev/null | head -6 \
    || echo "  (not loaded in system domain)"
echo ""

# ── 5. Docker Desktop log (last 50 lines) ────────────────────────────────────
echo "--- Docker Desktop log (last 50 lines) ---"
DOCKER_LOG_CANDIDATES=(
    "$HOME/Library/Containers/com.docker.docker/Data/log/host/Docker Desktop.log"
    "$HOME/Library/Logs/Docker Desktop.log"
    "$HOME/Library/Application Support/Docker Desktop/log/host/Docker Desktop.log"
)
found_log=0
for log_path in "${DOCKER_LOG_CANDIDATES[@]}"; do
    if [[ -f "$log_path" ]]; then
        echo "  Source: $log_path"
        tail -50 "$log_path"
        found_log=1
        break
    fi
done
if (( found_log == 0 )); then
    echo "  Log not found. Searched:"
    for p in "${DOCKER_LOG_CANDIDATES[@]}"; do echo "    $p"; done
fi
echo ""
echo "=== end docker-diagnose ==="
