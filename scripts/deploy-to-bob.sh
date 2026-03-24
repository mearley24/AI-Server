#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Deploy AI-Server to Bob — Run from M2 MacBook
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Usage:
#    ./deploy-to-bob.sh                  # Pull + restart changed services
#    ./deploy-to-bob.sh --rebuild        # Pull + rebuild + restart ALL
#    ./deploy-to-bob.sh --service name   # Rebuild + restart ONE service
#    ./deploy-to-bob.sh --status         # Just show service status
#    ./deploy-to-bob.sh --logs name      # Tail logs for a service
#
#  Setup (one-time):
#    1. Set BOB_HOST below (or use BOB_HOST env var)
#    2. Copy SSH key:  ssh-copy-id bob@Bob.local
#    3. chmod +x deploy-to-bob.sh
#    4. Optionally: cp deploy-to-bob.sh /usr/local/bin/bob-deploy
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

# ── Config ─────────────────────────────────────────
# Bob's hostname or IP — edit this or set BOB_HOST env var
# Try Bob.local first (Bonjour/mDNS), fall back to IP
BOB_HOST="${BOB_HOST:-Bob.local}"
BOB_USER="${BOB_USER:-$(whoami)}"
REPO_DIR="~/AI-Server"

# ── Colors ─────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;34m'
C='\033[0;36m'; W='\033[1;37m'; D='\033[0m'

banner() { echo -e "\n${B}━━━ ${W}$1${B} ━━━${D}\n"; }
ok()     { echo -e "  ${G}✓${D} $1"; }
warn()   { echo -e "  ${Y}⚠${D} $1"; }
fail()   { echo -e "  ${R}✗${D} $1"; }
info()   { echo -e "  ${C}→${D} $1"; }

# ── SSH helper ─────────────────────────────────────
bob() {
  ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${BOB_USER}@${BOB_HOST}" "$@"
}

# ── Check connectivity ─────────────────────────────
check_bob() {
  banner "Connecting to Bob (${BOB_USER}@${BOB_HOST})"
  if bob "echo 'connected'" &>/dev/null; then
    ok "Bob is reachable"
  else
    fail "Can't reach Bob at ${BOB_HOST}"
    echo ""
    echo "  Try setting BOB_HOST to Bob's IP address:"
    echo "    export BOB_HOST=192.168.1.XXX"
    echo "    ./deploy-to-bob.sh"
    echo ""
    echo "  Or find Bob's IP on the Mac Mini:"
    echo "    ipconfig getifaddr en0"
    exit 1
  fi
}

# ── Commands ───────────────────────────────────────

do_status() {
  banner "Bob Service Status"
  bob "cd ${REPO_DIR} && docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null || \
  bob "cd ${REPO_DIR} && docker compose ps"
}

do_logs() {
  local svc="$1"
  banner "Logs: ${svc}"
  bob "cd ${REPO_DIR} && docker logs ${svc} --tail 50" 2>&1
}

do_health() {
  banner "Health Checks"
  local services=(
    "proposals:8091"
    "email-monitor:8092"
    "voice-receptionist:8093"
    "calendar-agent:8094"
    "notification-hub:8095"
    "dtools-bridge:8096"
    "clawwork:8097"
    "mission-control:8098"
    "polymarket-bot:8430"
  )
  for entry in "${services[@]}"; do
    local name="${entry%%:*}"
    local port="${entry##*:}"
    local result
    result=$(bob "curl -sf http://127.0.0.1:${port}/health 2>/dev/null" || echo "UNREACHABLE")
    if [[ "$result" == *"ok"* ]] || [[ "$result" == *"healthy"* ]] || [[ "$result" == *"status"* ]]; then
      ok "${name} (:${port}) — ${result}"
    elif [[ "$result" == "UNREACHABLE" ]]; then
      fail "${name} (:${port}) — down"
    else
      warn "${name} (:${port}) — ${result}"
    fi
  done
}

do_pull() {
  banner "Git Pull"
  bob "cd ${REPO_DIR} && git pull origin main" 2>&1
  ok "Code updated"
}

do_deploy() {
  do_pull

  banner "Building & Deploying"
  bob "cd ${REPO_DIR} && docker compose up -d --build" 2>&1
  ok "All services deployed"

  sleep 3
  do_health
}

do_rebuild() {
  do_pull

  banner "Rebuilding ALL (--no-cache)"
  bob "cd ${REPO_DIR} && docker compose build --no-cache" 2>&1
  ok "Build complete"

  banner "Restarting"
  bob "cd ${REPO_DIR} && docker compose up -d --force-recreate" 2>&1
  ok "All services restarted"

  sleep 5
  do_health
}

do_service() {
  local svc="$1"
  do_pull

  banner "Rebuilding: ${svc}"
  bob "cd ${REPO_DIR} && docker compose build --no-cache ${svc}" 2>&1
  ok "Build complete"

  banner "Restarting: ${svc}"
  bob "cd ${REPO_DIR} && docker compose up -d --force-recreate ${svc}" 2>&1
  ok "${svc} restarted"

  sleep 3
  info "Checking health..."
  bob "cd ${REPO_DIR} && docker logs ${svc} --tail 10" 2>&1
}

do_env_check() {
  banner "Environment Variable Check"
  local checks=(
    "calendar-agent:ZOHO_CLIENT_ID"
    "calendar-agent:ZOHO_REFRESH_TOKEN"
    "dtools-bridge:DTOOLS_API_KEY"
    "notification-hub:NOTIFICATION_CHANNEL"
    "notification-hub:LINQ_API_KEY"
    "voice-receptionist:OPENAI_API_KEY"
    "voice-receptionist:TWILIO_ACCOUNT_SID"
    "polymarket-bot:ANTHROPIC_API_KEY"
  )
  for entry in "${checks[@]}"; do
    local container="${entry%%:*}"
    local var="${entry##*:}"
    local val
    val=$(bob "docker exec ${container} printenv ${var} 2>/dev/null" || echo "")
    if [[ -n "$val" && "$val" != "sk-..." && "$val" != "your_"* && "$val" != "ACxx"* ]]; then
      ok "${container} → ${var} = [set]"
    else
      fail "${container} → ${var} = [missing or placeholder]"
    fi
  done
}

# ── Main ───────────────────────────────────────────

case "${1:-}" in
  --status|-s)
    check_bob
    do_status
    ;;
  --health|-h)
    check_bob
    do_health
    ;;
  --logs|-l)
    check_bob
    do_logs "${2:?Usage: $0 --logs <service-name>}"
    ;;
  --rebuild|-r)
    check_bob
    do_rebuild
    ;;
  --service)
    check_bob
    do_service "${2:?Usage: $0 --service <service-name>}"
    ;;
  --env-check|-e)
    check_bob
    do_env_check
    ;;
  --help)
    echo "Usage: $0 [option]"
    echo ""
    echo "  (no args)           Pull + deploy changed services"
    echo "  --status, -s        Show docker compose ps"
    echo "  --health, -h        Health check all services"
    echo "  --logs, -l <name>   Tail logs for a service"
    echo "  --rebuild, -r       Full rebuild (--no-cache) + restart"
    echo "  --service <name>    Rebuild + restart one service"
    echo "  --env-check, -e     Verify API keys are reaching containers"
    echo "  --help              This help"
    ;;
  *)
    check_bob
    do_deploy
    ;;
esac

echo ""
