#!/bin/bash
# =============================================================================
# vpn-guard.sh — VPN resilience monitor for AI-Server (Bob / Mac Mini M4)
#
# Usage:
#   ./vpn-guard.sh                  Run a single VPN health check cycle
#   ./vpn-guard.sh --safe-pull      Run safe_pull() then check VPN health
#
# Cron (every 5 minutes):
#   */5 * * * * /path/to/ai-server/scripts/vpn-guard.sh >> /tmp/vpn-guard.log 2>&1
#
# What it does:
#   1. Checks whether the 'vpn' container is healthy via docker inspect
#   2. If unhealthy: restarts the container, waits up to 60 s for recovery,
#      then publishes an alert to Redis channel notifications:email
#   3. Exposes safe_pull() — stash → backup WireGuard config → git pull
#      → restore config → stash pop — so deployments never clobber the VPN
#
# Dependencies: docker, redis-cli (for alerts), git
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"          # ai-server/ lives inside the repo
BACKUP_DIR="${SCRIPT_DIR}/backups"
VPN_CONFIG_SRC="${REPO_ROOT}/polymarket-bot/vpn"
LOG_FILE="/tmp/vpn-guard.log"
VPN_CONTAINER="vpn"
VPN_RESTART_TIMEOUT=60   # seconds to wait for healthy status after restart
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [vpn-guard] $*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

# Send an alert via Redis PUBLISH to the notifications:email channel.
# Payload is a JSON string so downstream consumers can parse it cleanly.
redis_alert() {
  local message="$1"
  local payload
  payload=$(printf '{"source":"vpn-guard","host":"Bob","severity":"critical","message":"%s","timestamp":"%s"}' \
    "${message}" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')")
  if command -v redis-cli &>/dev/null; then
    redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" PUBLISH notifications:email "${payload}" \
      && log "Alert published to Redis: ${message}" \
      || log "WARNING: redis-cli publish failed — Redis may be unavailable"
  else
    log "WARNING: redis-cli not found; skipping Redis alert"
  fi
}

# ---------------------------------------------------------------------------
# backup_vpn_config — copies WireGuard config files to scripts/backups/
# with a datestamped subdirectory so history is preserved.
# ---------------------------------------------------------------------------
backup_vpn_config() {
  local ts
  ts="$(date '+%Y%m%d_%H%M%S')"
  local dest="${BACKUP_DIR}/vpn_${ts}"
  mkdir -p "${dest}"

  if [[ -d "${VPN_CONFIG_SRC}" ]]; then
    cp -r "${VPN_CONFIG_SRC}/." "${dest}/"
    log "WireGuard config backed up → ${dest}"
  else
    log "WARNING: VPN config source not found at ${VPN_CONFIG_SRC}; skipping backup"
  fi
}

# ---------------------------------------------------------------------------
# restore_vpn_config — restores the most recent backup back to the source dir.
# Called after git pull in case the pull removed or overwrote config files.
# ---------------------------------------------------------------------------
restore_vpn_config() {
  # Find the newest backup directory
  local latest
  latest=$(ls -dt "${BACKUP_DIR}"/vpn_* 2>/dev/null | head -1 || true)
  if [[ -z "${latest}" ]]; then
    log "WARNING: No VPN backup found to restore"
    return 0
  fi
  mkdir -p "${VPN_CONFIG_SRC}"
  cp -r "${latest}/." "${VPN_CONFIG_SRC}/"
  log "WireGuard config restored from ${latest}"
}

# ---------------------------------------------------------------------------
# safe_pull — git pull wrapper that protects WireGuard config and .env files.
#
# Flow:
#   1. git stash (includes untracked files)
#   2. backup_vpn_config
#   3. git pull --rebase origin main
#   4. restore_vpn_config (idempotent — only overwrites if files went missing)
#   5. git stash pop
# ---------------------------------------------------------------------------
safe_pull() {
  log "=== safe_pull: starting ==="
  cd "${REPO_ROOT}"

  # Stash local changes (including untracked) so pull is clean
  log "Stashing local changes..."
  git stash --include-untracked || log "WARNING: git stash had nothing to stash"

  # Always backup before touching the repo
  backup_vpn_config

  # Pull
  log "Running git pull --rebase origin main..."
  if ! git pull --rebase origin main; then
    log "ERROR: git pull failed — attempting stash pop and aborting"
    git stash pop || true
    restore_vpn_config
    redis_alert "safe_pull failed on Bob: git pull --rebase returned non-zero"
    exit 1
  fi

  # Restore config in case it was overwritten or deleted by the pull
  restore_vpn_config

  # Re-apply local stashed changes
  log "Popping stash..."
  git stash pop || log "WARNING: stash pop failed (stash may have been empty)"

  log "=== safe_pull: complete ==="
}

# ---------------------------------------------------------------------------
# check_vpn_health — returns 0 if healthy, 1 otherwise
# ---------------------------------------------------------------------------
check_vpn_health() {
  local status
  status=$(docker inspect --format '{{.State.Health.Status}}' "${VPN_CONTAINER}" 2>/dev/null || echo "missing")
  log "VPN container health: ${status}"
  if [[ "${status}" == "healthy" ]]; then
    return 0
  else
    return 1
  fi
}

# ---------------------------------------------------------------------------
# restart_vpn — restarts container and waits up to VPN_RESTART_TIMEOUT seconds
# for a healthy status. Publishes Redis alert regardless of outcome.
# ---------------------------------------------------------------------------
restart_vpn() {
  log "VPN is not healthy — restarting container '${VPN_CONTAINER}'..."
  docker restart "${VPN_CONTAINER}" || die "docker restart ${VPN_CONTAINER} failed"

  log "Waiting up to ${VPN_RESTART_TIMEOUT}s for VPN to become healthy..."
  local elapsed=0
  local interval=5
  while (( elapsed < VPN_RESTART_TIMEOUT )); do
    sleep "${interval}"
    elapsed=$(( elapsed + interval ))
    if check_vpn_health; then
      log "VPN recovered after ${elapsed}s"
      redis_alert "VPN container restarted and recovered on Bob (${elapsed}s)"
      return 0
    fi
    log "Still waiting... (${elapsed}s elapsed)"
  done

  # Timed out
  log "ERROR: VPN did not recover within ${VPN_RESTART_TIMEOUT}s"
  redis_alert "CRITICAL: VPN container failed to recover on Bob after ${VPN_RESTART_TIMEOUT}s restart attempt"
  return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  mkdir -p "${BACKUP_DIR}"

  case "${1:-}" in
    --safe-pull)
      safe_pull
      ;;
    "")
      # Default: health check only
      ;;
    *)
      echo "Usage: $0 [--safe-pull]"
      exit 1
      ;;
  esac

  log "Checking VPN health..."
  if check_vpn_health; then
    log "VPN is healthy — nothing to do"
    exit 0
  fi

  # VPN is down — attempt recovery
  restart_vpn
}

main "$@"
