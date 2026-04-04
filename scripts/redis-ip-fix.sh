#!/usr/bin/env bash
# =============================================================================
# redis-ip-fix.sh — Redis IP auto-detection & polymarket-bot env repair
# =============================================================================
#
# PURPOSE:
#   The polymarket-bot connects to Redis at the static IP 172.18.0.100, which
#   is assigned via the docker-compose network IPAM config. If Docker recreates
#   the network (e.g., after a full `/usr/local/bin/docker compose down && up`), the IP could
#   drift. This script:
#     1. Verifies Redis is reachable at 172.18.0.100:6379
#     2. If not, discovers the actual Redis container IP
#     3. Rewrites the polymarket-bot's REDIS_URL environment variable in the
#        .env file (or docker-compose override) to the correct IP
#     4. Restarts polymarket-bot if a change was made
#
# USAGE:
#   ./redis-ip-fix.sh              # Check and auto-repair if needed
#   ./redis-ip-fix.sh --check      # Check only, exit 1 if mismatch (no repair)
#   ./redis-ip-fix.sh --force      # Force restart polymarket-bot regardless
#
# RUN AFTER:
#   Any `/usr/local/bin/docker compose restart`, `/usr/local/bin/docker compose up -d`, or network change.
#   Add to your post-deploy hook or run manually after infra changes.
#
# DEPENDENCIES:
#   docker
#
# CONFIGURATION (override via environment variables):
#   COMPOSE_DIR         — docker-compose project root (default: ~/ai-server)
#   REDIS_CONTAINER     — Redis container name (default: redis)
#   BOT_CONTAINER       — polymarket-bot container name (default: polymarket-bot)
#   EXPECTED_REDIS_IP   — The IP the bot expects to reach Redis on (default: 172.18.0.100)
#   REDIS_PORT          — Redis port (default: 6379)
#   ENV_FILE            — .env file to update if IP drifts (default: COMPOSE_DIR/.env)
#   CONNECT_TIMEOUT     — TCP connect timeout in seconds (default: 5)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/ai-server}"
REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"
BOT_CONTAINER="${BOT_CONTAINER:-polymarket-bot}"
EXPECTED_REDIS_IP="${EXPECTED_REDIS_IP:-172.18.0.100}"
REDIS_PORT="${REDIS_PORT:-6379}"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-5}"
LOG_PREFIX="[redis-ip-fix $(date '+%Y-%m-%d %H:%M:%S')]"

# ---------------------------------------------------------------------------
# Mode flags
# ---------------------------------------------------------------------------
CHECK_ONLY=false
FORCE_RESTART=false

for arg in "$@"; do
  case "$arg" in
    --check)  CHECK_ONLY=true  ;;
    --force)  FORCE_RESTART=true ;;
    -h|--help)
      grep '^#' "$0" | head -40 | sed 's/^# \?//'
      exit 0
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { echo "$LOG_PREFIX INFO  $*"; }
warn() { echo "$LOG_PREFIX WARN  $*" >&2; }
err()  { echo "$LOG_PREFIX ERROR $*" >&2; }

# ---------------------------------------------------------------------------
# redis_ping — returns 0 if Redis at $host:$port responds to PING
# ---------------------------------------------------------------------------
redis_ping() {
  local host="$1"
  local port="${2:-$REDIS_PORT}"

  # Try via host-side redis-cli first
  if command -v redis-cli &>/dev/null; then
    if redis-cli -h "$host" -p "$port" -e PING 2>/dev/null | grep -q "PONG"; then
      return 0
    fi
  fi

  # Fallback: run redis-cli inside the redis container itself
  if /usr/local/bin/docker exec "$REDIS_CONTAINER" \
       redis-cli -h "$host" -p "$port" -e PING 2>/dev/null | grep -q "PONG"; then
    return 0
  fi

  # Last resort: raw TCP connect check (bash built-in /dev/tcp)
  if timeout "$CONNECT_TIMEOUT" bash -c \
       "echo > /dev/tcp/$host/$port" 2>/dev/null; then
    return 0
  fi

  return 1
}

# ---------------------------------------------------------------------------
# get_redis_container_ip — inspect the redis container for its actual IP
# on the default bridge network.
# ---------------------------------------------------------------------------
get_redis_container_ip() {
  local ip

  # Try the compose project network first (network name may be <project>_default)
  ip="$(docker inspect \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
    "$REDIS_CONTAINER" 2>/dev/null | head -n1)"

  if [[ -z "$ip" ]]; then
    # Broader fallback — grab first non-empty IP from any network
    ip="$(docker inspect "$REDIS_CONTAINER" \
      --format '{{json .NetworkSettings.Networks}}' 2>/dev/null \
      | grep -oP '"IPAddress":"[^"]*"' \
      | grep -v '""' \
      | head -n1 \
      | grep -oP '\d+\.\d+\.\d+\.\d+' || true)"
  fi

  echo "$ip"
}

# ---------------------------------------------------------------------------
# update_env_file — rewrite REDIS_URL in the .env file.
# Creates a .env.bak backup before modifying.
# ---------------------------------------------------------------------------
update_env_file() {
  local new_ip="$1"
  local new_url="redis://${new_ip}:${REDIS_PORT}"

  if [[ ! -f "$ENV_FILE" ]]; then
    warn "ENV file not found: $ENV_FILE — creating with new REDIS_URL"
    echo "REDIS_URL=$new_url" >> "$ENV_FILE"
    return
  fi

  # Backup
  cp "$ENV_FILE" "${ENV_FILE}.bak"
  log "Backed up .env to ${ENV_FILE}.bak"

  if grep -q '^REDIS_URL=' "$ENV_FILE"; then
    # Update existing line
    sed -i "s|^REDIS_URL=.*|REDIS_URL=$new_url|" "$ENV_FILE"
    log "Updated REDIS_URL in $ENV_FILE → $new_url"
  else
    # Append
    echo "REDIS_URL=$new_url" >> "$ENV_FILE"
    log "Appended REDIS_URL to $ENV_FILE → $new_url"
  fi
}

# ---------------------------------------------------------------------------
# update_compose_override — write a docker-compose.override.yml that sets the
# correct REDIS_URL on polymarket-bot. This is the preferred method since
# polymarket-bot reads the env at container start, not from the .env file.
# ---------------------------------------------------------------------------
update_compose_override() {
  local new_ip="$1"
  local new_url="redis://${new_ip}:${REDIS_PORT}"
  local override_file="$COMPOSE_DIR/docker-compose.redis-fix.yml"

  log "Writing compose override: $override_file"
  cat > "$override_file" <<EOF
# Auto-generated by redis-ip-fix.sh on $(date --iso-8601=seconds)
# Redis IP drifted from $EXPECTED_REDIS_IP to $new_ip — override applied.
# Remove this file and re-run redis-ip-fix.sh once the static IP is restored.
services:
  polymarket-bot:
    environment:
      - REDIS_URL=${new_url}
EOF
  log "Override written with REDIS_URL=$new_url"
}

# ---------------------------------------------------------------------------
# restart_bot — restart the polymarket-bot container via /usr/local/bin/docker compose.
# ---------------------------------------------------------------------------
restart_bot() {
  log "Restarting polymarket-bot..."
  cd "$COMPOSE_DIR"
  /usr/local/bin/docker compose restart "$BOT_CONTAINER"
  log "polymarket-bot restarted"
}

# ---------------------------------------------------------------------------
# verify_bot_redis — confirm the running polymarket-bot container sees the
# correct REDIS_URL environment variable.
# ---------------------------------------------------------------------------
verify_bot_redis() {
  local bot_redis
  bot_redis="$(docker exec "$BOT_CONTAINER" \
    printenv REDIS_URL 2>/dev/null || echo 'unknown')"
  log "polymarket-bot REDIS_URL (live): $bot_redis"
  echo "$bot_redis"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
  log "=== Redis IP check starting ==="
  log "Expected Redis IP: $EXPECTED_REDIS_IP:$REDIS_PORT"

  # Step 1: Check if Redis is reachable at the expected IP
  if redis_ping "$EXPECTED_REDIS_IP"; then
    log "Redis is reachable at $EXPECTED_REDIS_IP:$REDIS_PORT — all good"

    if [[ "$FORCE_RESTART" == "true" ]]; then
      log "--force flag set — restarting polymarket-bot anyway"
      restart_bot
    else
      verify_bot_redis
      log "=== Redis IP check done — no changes needed ==="
      exit 0
    fi
  fi

  warn "Redis is NOT reachable at $EXPECTED_REDIS_IP:$REDIS_PORT"

  # Step 2: Find the actual Redis container IP
  log "Discovering actual Redis container IP..."
  local actual_ip
  actual_ip="$(get_redis_container_ip)"

  if [[ -z "$actual_ip" ]]; then
    err "Could not determine Redis container IP — is the redis container running?"
    /usr/local/bin/docker ps --filter "name=$REDIS_CONTAINER" --format "  {{.Names}}  {{.Status}}"
    exit 1
  fi

  log "Redis container actual IP: $actual_ip"

  # Confirm the discovered IP actually responds
  if ! redis_ping "$actual_ip"; then
    err "Redis container is running at $actual_ip but not responding to PING — Redis may be down"
    exit 1
  fi

  log "Redis is responding at $actual_ip:$REDIS_PORT"

  if [[ "$CHECK_ONLY" == "true" ]]; then
    warn "--check mode: IP mismatch detected ($EXPECTED_REDIS_IP vs $actual_ip) — no changes made"
    exit 1
  fi

  # Step 3: Update configuration
  log "IP drift detected: $EXPECTED_REDIS_IP → $actual_ip — updating configuration"
  update_env_file "$actual_ip"
  update_compose_override "$actual_ip"

  # Step 4: Restart polymarket-bot with the corrected env
  restart_bot

  # Step 5: Verify
  local live_url
  live_url="$(verify_bot_redis)"
  if echo "$live_url" | grep -q "$actual_ip"; then
    log "Verification PASSED — polymarket-bot is using REDIS_URL=$live_url"
  else
    warn "Verification: polymarket-bot REDIS_URL ($live_url) may not reflect the update yet"
    warn "The container environment is injected at start — check that the override file is being loaded:"
    warn "  /usr/local/bin/docker compose -f docker-compose.yml -f docker-compose.redis-fix.yml up -d polymarket-bot"
  fi

  log "=== Redis IP fix complete ==="
  log ""
  log "SUMMARY"
  log "  Old Redis IP : $EXPECTED_REDIS_IP"
  log "  New Redis IP : $actual_ip"
  log "  Updated      : $ENV_FILE + $COMPOSE_DIR/docker-compose.redis-fix.yml"
  log ""
  log "NOTE: To make the static IP permanent, ensure the Docker network subnet"
  log "      172.18.0.0/16 and Redis ipv4_address: 172.18.0.100 are in docker-compose.yml"
  log "      and run: /usr/local/bin/docker compose down && /usr/local/bin/docker compose up -d"
}

main "$@"
