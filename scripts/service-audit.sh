#!/bin/bash
# =============================================================================
# service-audit.sh — Container audit & cleanup for AI-Server (Bob / Mac Mini M4)
#
# Usage:
#   ./service-audit.sh              Print color-coded status to terminal
#   ./service-audit.sh --report     Write report to ./backups/audit_<timestamp>.txt
#                                   (also prints to terminal)
#
# What it does:
#   1. Lists every running container with status, uptime, and resource usage
#   2. Checks the "should be running" list — flags any that are down
#   3. Stops and removes containers in the "should be stopped" list
#   4. Flags any container not in either list as "unknown"
#
# Should-be-RUNNING:
#   redis, vpn, polymarket-bot, email-monitor, calendar-agent,
#   notification-hub, dtools-bridge, openclaw, proposals, voice-receptionist,
#   mission-control, knowledge-scanner, intel-feeds
#
# Should-be-STOPPED (dead weight / security risk):
#   remediator  — Docker socket mount is a container escape vector
#   clawwork     — inactive service
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backups"

# ---------------------------------------------------------------------------
# Terminal colors (disabled automatically when writing to file)
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  RED='' GREEN='' YELLOW='' CYAN='' BOLD='' RESET=''
fi

# ---------------------------------------------------------------------------
# Service lists
# ---------------------------------------------------------------------------
SHOULD_RUN=(
  redis
  vpn
  polymarket-bot
  email-monitor
  calendar-agent
  notification-hub
  dtools-bridge
  openclaw
  proposals
  voice-receptionist
  mission-control
  knowledge-scanner
  intel-feeds
)

SHOULD_STOP=(
  remediator   # Docker socket mount (/var/run/docker.sock) = privilege escalation risk
  clawwork     # Inactive — consuming resources with no active purpose
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "$*"; }

header() {
  local title="$1"
  log ""
  log "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
  log "${BOLD}${CYAN}  ${title}${RESET}"
  log "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
}

ok()   { log "  ${GREEN}[  OK  ]${RESET}  $*"; }
warn() { log "  ${YELLOW}[ WARN ]${RESET}  $*"; }
fail() { log "  ${RED}[ DOWN ]${RESET}  $*"; }
info() { log "  ${CYAN}[ INFO ]${RESET}  $*"; }
stop_tag() { log "  ${RED}[ STOP ]${RESET}  $*"; }

# Check whether a container name appears in the SHOULD_STOP list
in_stop_list() {
  local name="$1"
  for s in "${SHOULD_STOP[@]}"; do
    [[ "${s}" == "${name}" ]] && return 0
  done
  return 1
}

# Check whether a container name appears in the SHOULD_RUN list
in_run_list() {
  local name="$1"
  for r in "${SHOULD_RUN[@]}"; do
    [[ "${r}" == "${name}" ]] && return 0
  done
  return 1
}

# Stop and remove a container; no-op if it isn't running
remove_container() {
  local name="$1"
  local running
  running=$(docker ps -q --filter "name=^${name}$" 2>/dev/null || true)
  local exists
  exists=$(docker ps -aq --filter "name=^${name}$" 2>/dev/null || true)

  if [[ -n "${running}" ]]; then
    stop_tag "Stopping '${name}'..."
    docker stop "${name}" >/dev/null
  fi
  if [[ -n "${exists}" ]]; then
    stop_tag "Removing '${name}'..."
    docker rm "${name}" >/dev/null
    stop_tag "'${name}' removed"
  else
    info "'${name}' is not present — nothing to remove"
  fi
}

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
section_overview() {
  header "ALL RUNNING CONTAINERS — STATUS / UPTIME / RESOURCES"
  log ""
  log "  $(printf '%-30s %-12s %-30s %s' 'CONTAINER' 'STATUS' 'UPTIME' 'CPU / MEM')"
  log "  $(printf '%-30s %-12s %-30s %s' '─────────────────────────────' '──────────' '─────────────────────────────' '────────────────')"

  # Collect stats + status in one pass (compatible with bash 3.x / macOS)
  # Write stats to a temp file for lookup
  local stats_tmp
  stats_tmp=$(mktemp /tmp/audit_stats.XXXXXX)
  docker stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null > "${stats_tmp}" || true

  # Iterate all containers (running + stopped) for status / uptime
  docker ps -a --format "{{.Names}}\t{{.Status}}" 2>/dev/null | sort | \
  while IFS=$'\t' read -r cname status; do
    local cpu mem usage
    cpu=$(grep "^${cname}" "${stats_tmp}" 2>/dev/null | cut -f2 || echo "—")
    mem=$(grep "^${cname}" "${stats_tmp}" 2>/dev/null | cut -f3 || echo "—")
    [[ -z "${cpu}" ]] && cpu="—"
    [[ -z "${mem}" ]] && mem="—"
    usage="${cpu} / ${mem}"
    printf "  %-30s %-12s %-30s %s\n" "${cname}" "running" "${status}" "${usage}"
  done
  rm -f "${stats_tmp}"
}

section_should_run() {
  header "SHOULD-BE-RUNNING SERVICES"
  local any_down=0
  for name in "${SHOULD_RUN[@]}"; do
    local health_status container_status
    container_status=$(docker inspect --format '{{.State.Status}}' "${name}" 2>/dev/null || echo "missing")
    health_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "${name}" 2>/dev/null || echo "missing")

    if [[ "${container_status}" == "running" ]]; then
      local health_label=""
      if [[ "${health_status}" == "healthy" ]]; then
        health_label=" (healthy)"
      elif [[ "${health_status}" == "unhealthy" ]]; then
        health_label="${RED} (UNHEALTHY)${RESET}"
        any_down=1
      elif [[ "${health_status}" == "starting" ]]; then
        health_label="${YELLOW} (starting)${RESET}"
      elif [[ "${health_status}" == "no-healthcheck" ]]; then
        health_label=" (no healthcheck)"
      fi
      ok "${name} — running${health_label}"
    elif [[ "${container_status}" == "missing" ]]; then
      fail "${name} — NOT FOUND (container does not exist)"
      any_down=1
    else
      fail "${name} — ${container_status} (expected: running)"
      any_down=1
    fi
  done

  if (( any_down )); then
    log ""
    warn "One or more required services are down. Investigate immediately."
  else
    log ""
    ok "All required services are running."
  fi
}

section_should_stop() {
  header "SHOULD-BE-STOPPED SERVICES (cleanup)"
  for name in "${SHOULD_STOP[@]}"; do
    local exists
    exists=$(docker ps -aq --filter "name=^${name}$" 2>/dev/null || true)
    if [[ -n "${exists}" ]]; then
      local reason=""
      if [[ "${name}" == "remediator" ]]; then
        reason="Docker socket mount (/var/run/docker.sock) = security risk"
      elif [[ "${name}" == "clawwork" ]]; then
        reason="Inactive service — no active purpose"
      fi
      warn "Found '${name}' — removing (${reason})"
      remove_container "${name}"
    else
      ok "'${name}' is already absent — nothing to do"
    fi
  done
}

section_unknowns() {
  header "UNKNOWN CONTAINERS (not in either list)"
  local found_unknown=0

  # Combine both lists for lookup
  local all_known=("${SHOULD_RUN[@]}" "${SHOULD_STOP[@]}")

  while IFS= read -r cname; do
    local known=0
    for k in "${all_known[@]}"; do
      [[ "${k}" == "${cname}" ]] && known=1 && break
    done
    if (( ! known )); then
      warn "UNKNOWN container: '${cname}' — not in any managed list"
      found_unknown=1
    fi
  done < <(docker ps -a --format "{{.Names}}" 2>/dev/null | sort)

  if (( ! found_unknown )); then
    ok "No unknown containers detected."
  fi
}

section_summary() {
  header "AUDIT COMPLETE"
  log "  Host   : Bob (Mac Mini M4)"
  log "  Time   : $(date '+%Y-%m-%d %H:%M:%S %Z')"
  log ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
REPORT_FLAG=0
for arg in "$@"; do
  case "${arg}" in
    --report) REPORT_FLAG=1 ;;
    --help|-h)
      echo "Usage: $0 [--report]"
      echo ""
      echo "  (no flag)   Print color-coded audit to terminal"
      echo "  --report    Write plain-text report to scripts/backups/audit_<ts>.txt"
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: $0 [--report]" >&2
      exit 1
      ;;
  esac
done

run_audit() {
  log ""
  log "  AI-Server Service Audit — Bob (Mac Mini M4)"
  log "  $(date '+%Y-%m-%d %H:%M:%S %Z')"

  section_overview
  section_should_run
  section_should_stop
  section_unknowns
  section_summary
}

mkdir -p "${BACKUP_DIR}"

if (( REPORT_FLAG )); then
  TS="$(date '+%Y%m%d_%H%M%S')"
  REPORT_FILE="${BACKUP_DIR}/audit_${TS}.txt"
  # Strip ANSI color codes for the file copy
  run_audit 2>&1 | tee >(sed 's/\x1b\[[0-9;]*m//g' > "${REPORT_FILE}")
  log ""
  info "Report saved → ${REPORT_FILE}"
else
  run_audit
fi
