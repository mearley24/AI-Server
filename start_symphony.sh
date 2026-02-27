#!/usr/bin/env bash
# =============================================================================
# start_symphony.sh — Symphony Smart Homes AI-Server Bootstrap
# Host: Bob (Mac Mini M4, Apple Silicon / arm64)
#
# Usage:
#   ./start_symphony.sh            # Normal start
#   ./start_symphony.sh --build    # Force rebuild all images before starting
#   ./start_symphony.sh --pull     # Pull base images before building
#   ./start_symphony.sh --fresh    # Stop, remove containers, then start clean
#   ./start_symphony.sh --help     # Show this help
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}  \u2714  ${RESET}$*"; }
warn() { echo -e "${YELLOW}  \u26a0  ${RESET}$*"; }
err()  { echo -e "${RED}  \u2718  ${RESET}$*" >&2; }
info() { echo -e "${CYAN}  \u2192  ${RESET}$*"; }
banner() {
  echo ""
  echo -e "${BOLD}${CYAN}\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550${RESET}"
  echo -e "${BOLD}${CYAN}  $*${RESET}"
  echo -e "${BOLD}${CYAN}\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550${RESET}"
}

# ---------------------------------------------------------------------------
# Script location — always run from the directory containing docker-compose.yml
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
NETWORK_NAME="symphony"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
DO_BUILD=false
DO_PULL=false
DO_FRESH=false

for arg in "$@"; do
  case $arg in
    --build)  DO_BUILD=true ;;
    --pull)   DO_PULL=true ;;
    --fresh)  DO_FRESH=true ;;
    --help|-h)
      echo ""
      echo "  Symphony Smart Homes — AI-Server Bootstrap"
      echo ""
      echo "  Usage: $0 [OPTIONS]"
      echo ""
      echo "  Options:"
      echo "    --build    Force rebuild all service images"
      echo "    --pull     Pull latest base images before building"
      echo "    --fresh    Stop and remove existing containers, then start clean"
      echo "    --help     Show this help message"
      echo ""
      exit 0
      ;;
    *)
      err "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# STEP 1 — Check Docker is running
# ---------------------------------------------------------------------------
banner "Step 1 — Docker Runtime"

if ! command -v docker &>/dev/null; then
  err "Docker not found. Install Docker Desktop for Mac from https://www.docker.com/products/docker-desktop"
  exit 1
fi

if ! docker info &>/dev/null; then
  err "Docker daemon is not running."
  info "Start Docker Desktop from Applications or run: open -a Docker"
  exit 1
fi

DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
ok "Docker daemon running (server v${DOCKER_VERSION})"

if ! docker compose version &>/dev/null; then
  err "Docker Compose plugin not found. Update Docker Desktop to v4.x or later."
  exit 1
fi

COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "unknown")
ok "Docker Compose available (v${COMPOSE_VERSION})"

# ---------------------------------------------------------------------------
# STEP 2 — Validate .env file
# ---------------------------------------------------------------------------
banner "Step 2 — Environment Configuration"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    warn ".env not found. Copying from .env.example — you MUST fill in all REQUIRED values."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    err "Edit $ENV_FILE and re-run this script."
    exit 1
  else
    err ".env file is missing and no .env.example found. Cannot continue."
    exit 1
  fi
fi
ok ".env file found"

# Check required variables are set and non-empty
REQUIRED_VARS=(
  OPENAI_API_KEY
  ANTHROPIC_API_KEY
  OLLAMA_HOST
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  SYMPHONY_PHONE
  DTOOLS_API_KEY
  TELEGRAM_BOT_TOKEN
  TELEGRAM_OWNER_CHAT_ID
  HA_URL
  HA_TOKEN
  MQTT_BROKER
)

# Source the .env file to check values (only for validation)
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

MISSING_VARS=()
PLACEHOLDER_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
  value="${!var:-}"
  if [[ -z "$value" ]]; then
    MISSING_VARS+=("$var")
  elif [[ "$value" == *"XXX"* ]] || [[ "$value" == "your_"* ]] || [[ "$value" == "sk-..."* ]] || [[ "$value" == "sk-ant-..."* ]]; then
    PLACEHOLDER_VARS+=("$var")
  fi
done

if [[ ${#MISSING_VARS[@]} -gt 0 ]]; then
  err "The following REQUIRED variables are missing from .env:"
  for v in "${MISSING_VARS[@]}"; do
    echo "    - $v"
  done
  exit 1
fi

if [[ ${#PLACEHOLDER_VARS[@]} -gt 0 ]]; then
  warn "The following variables still have placeholder values — double-check before going live:"
  for v in "${PLACEHOLDER_VARS[@]}"; do
    echo "    - $v"
  done
  echo ""
  read -rp "  Continue anyway? [y/N] " confirm
  [[ "${confirm,,}" == "y" ]] || { info "Aborted. Fill in real values and re-run."; exit 0; }
fi

ok "All required environment variables are set"

# ---------------------------------------------------------------------------
# STEP 3 — Create the symphony network if it doesn't exist
# ---------------------------------------------------------------------------
banner "Step 3 — Docker Network"

if docker network inspect "$NETWORK_NAME" &>/dev/null; then
  ok "Network '${NETWORK_NAME}' already exists"
else
  info "Creating Docker network '${NETWORK_NAME}'..."
  docker network create \
    --driver bridge \
    --label "com.symphony.description=Symphony backbone network" \
    "$NETWORK_NAME"
  ok "Network '${NETWORK_NAME}' created"
fi

# ---------------------------------------------------------------------------
# STEP 4 — Fresh mode: stop and remove existing containers
# ---------------------------------------------------------------------------
if [[ "$DO_FRESH" == true ]]; then
  banner "Step 4 — Fresh Start (removing existing containers)"
  info "Stopping and removing existing Symphony containers..."
  docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true
  ok "Existing containers removed"
else
  banner "Step 4 — Fresh Start"
  info "Skipping (use --fresh to remove existing containers)"
fi

# ---------------------------------------------------------------------------
# STEP 5 — Pull base images (optional)
# ---------------------------------------------------------------------------
banner "Step 5 — Base Images"

if [[ "$DO_PULL" == true ]]; then
  info "Pulling latest base images..."
  docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" pull --ignore-pull-failures || true
  ok "Base images updated"
else
  info "Skipping pull (use --pull to update base images)"
fi

# ---------------------------------------------------------------------------
# STEP 6 — Build service images
# ---------------------------------------------------------------------------
banner "Step 6 — Build Service Images"

BUILD_ARGS=""
if [[ "$DO_BUILD" == true ]]; then
  info "Force-rebuilding all images (--no-cache)..."
  BUILD_ARGS="--no-cache"
else
  info "Building images (using cache where available)..."
fi

docker compose \
  --file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  build \
  --parallel \
  ${BUILD_ARGS} \
  2>&1 | while IFS= read -r line; do
    echo "    $line"
  done

ok "All service images built"

# ---------------------------------------------------------------------------
# STEP 7 — Start all services
# ---------------------------------------------------------------------------
banner "Step 7 — Starting Services"

info "Launching Symphony stack..."
docker compose \
  --file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  up \
  --detach \
  --remove-orphans

ok "Stack started in detached mode"

# ---------------------------------------------------------------------------
# STEP 8 — Health checks
# ---------------------------------------------------------------------------
banner "Step 8 — Health Checks"

# Services and their health endpoints
declare -A SERVICE_HEALTH=(
  [redis]="redis-cli -h 127.0.0.1 ping"
  [openclaw]="http://127.0.0.1:3000/health"
  [voice-receptionist]="http://127.0.0.1:5000/health"
  [dtools-bridge]="http://127.0.0.1:5050/health"
  [homeassistant-bridge]="http://127.0.0.1:5100/health"
)

# Give services a moment to initialise
info "Waiting 10s for services to initialise..."
sleep 10

# Poll each service health endpoint
MAX_WAIT=60     # seconds per service
INTERVAL=5

all_healthy=true

check_http_health() {
  local service=$1
  local url=$2
  local elapsed=0

  while [[ $elapsed -lt $MAX_WAIT ]]; do
    if curl -sf --connect-timeout 3 "$url" &>/dev/null; then
      ok "${service} is healthy (${url})"
      return 0
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    info "${service}: waiting... (${elapsed}s/${MAX_WAIT}s)"
  done

  warn "${service} did not respond at ${url} within ${MAX_WAIT}s — check logs: docker logs symphony_${service//-/_}"
  return 1
}

# Redis — check via docker exec since it's loopback-only
REDIS_CONTAINER="symphony_redis"
elapsed=0
while [[ $elapsed -lt $MAX_WAIT ]]; do
  if docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q PONG; then
    ok "redis is healthy"
    break
  fi
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  info "redis: waiting... (${elapsed}s/${MAX_WAIT}s)"
done
if [[ $elapsed -ge $MAX_WAIT ]]; then
  warn "redis did not respond within ${MAX_WAIT}s"
  all_healthy=false
fi

check_http_health "openclaw"              "http://127.0.0.1:3000/health"  || all_healthy=false
check_http_health "voice-receptionist"    "http://127.0.0.1:5000/health"  || all_healthy=false
check_http_health "dtools-bridge"         "http://127.0.0.1:5050/health"  || all_healthy=false
check_http_health "homeassistant-bridge"  "http://127.0.0.1:5100/health"  || all_healthy=false

# telegram-bot uses long-polling (no inbound port), check container state only
TELEGRAM_STATE=$(docker inspect --format='{{.State.Status}}' symphony_telegram_bot 2>/dev/null || echo "not found")
if [[ "$TELEGRAM_STATE" == "running" ]]; then
  ok "telegram-bot container is running (long-poll mode)"
else
  warn "telegram-bot container state: ${TELEGRAM_STATE}"
  all_healthy=false
fi

# ---------------------------------------------------------------------------
# STEP 9 — Status summary
# ---------------------------------------------------------------------------
banner "Step 9 — Status Summary"

echo ""
echo -e "  ${BOLD}CONTAINER STATUS${RESET}"
echo "  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
printf "  %-35s %-12s %-10s %s\n" "CONTAINER" "STATUS" "HEALTH" "PORTS"
echo "  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"

docker compose \
  --file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  ps \
  --format "table {{.Name}}\t{{.Status}}\t{{.Health}}\t{{.Ports}}" \
  2>/dev/null | tail -n +2 | while IFS=$'\t' read -r name status health ports; do
    if [[ "$status" == *"Up"* ]]; then
      status_col="${GREEN}${status}${RESET}"
    else
      status_col="${RED}${status}${RESET}"
    fi
    printf "  %-35s ${status_col} %-10s %s\n" "$name" "$health" "$ports"
  done

echo ""
echo -e "  ${BOLD}SERVICE ENDPOINTS${RESET}"
echo "  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
echo -e "  OpenClaw (orchestrator)    \u2192  ${CYAN}http://localhost:3000${RESET}"
echo -e "  Voice Receptionist         \u2192  ${CYAN}http://localhost:5000${RESET}  (Twilio webhook target)"
echo -e "  D-Tools Bridge             \u2192  ${CYAN}http://localhost:5050${RESET}"
echo -e "  HA Bridge                  \u2192  ${CYAN}http://localhost:5100${RESET}"
echo -e "  Redis                      \u2192  ${CYAN}localhost:6379${RESET}  (loopback only)"
echo -e "  Ollama (external/Maestro)  \u2192  ${CYAN}${OLLAMA_HOST}${RESET}"
echo ""
echo -e "  ${BOLD}USEFUL COMMANDS${RESET}"
echo "  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
echo "  Tail all logs:        docker compose -f $COMPOSE_FILE logs -f"
echo "  Tail one service:     docker compose -f $COMPOSE_FILE logs -f openclaw"
echo "  Restart one service:  docker compose -f $COMPOSE_FILE restart voice-receptionist"
echo "  Stop everything:      docker compose -f $COMPOSE_FILE down"
echo "  Rebuild one service:  docker compose -f $COMPOSE_FILE up -d --build openclaw"
echo ""

if [[ "$all_healthy" == true ]]; then
  echo -e "  ${GREEN}${BOLD}\u2714  All services healthy \u2014 Symphony is live.${RESET}"
else
  echo -e "  ${YELLOW}${BOLD}\u26a0  One or more services need attention. Review warnings above.${RESET}"
  echo -e "  ${YELLOW}  Tip: docker compose -f $COMPOSE_FILE logs <service>${RESET}"
fi

echo ""
