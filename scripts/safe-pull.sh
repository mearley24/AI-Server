#!/bin/bash
# =============================================================================
# safe-pull.sh — Safe git pull wrapper for AI-Server (Bob / Mac Mini M4)
#
# Usage:
#   ./safe-pull.sh               Pull and rebuild only containers whose
#                                Dockerfiles/contexts changed in the pull
#   ./safe-pull.sh --rebuild-all Rebuild every service after the pull
#
# What it does:
#   1. Backs up WireGuard config (polymarket-bot/vpn/) and top-level .env
#   2. git stash --include-untracked  (preserves all local-only files)
#   3. git pull --rebase origin main
#   4. Restores any backed-up files that were removed or clobbered by the pull
#   5. git stash pop
#   6. Detects which services had Dockerfile or build-context changes and
#      rebuilds only those (or all if --rebuild-all is passed)
#
# Rebuild detection:
#   Compares the list of files changed in the pull against known build-context
#   directories from docker-compose.yml. If any file inside a service's build
#   context changed, that service is rebuilt with:
#     docker compose build --no-cache <service>
#     docker compose up -d --no-deps <service>
#
# Dependencies: docker, docker compose (v2 plugin), git
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backups"
VPN_CONFIG_SRC="${REPO_ROOT}/polymarket-bot/vpn"
ENV_FILE="${REPO_ROOT}/.env"

# Build-context directories mapped to their compose service names.
# Format: "service_name:build_context" — parsed with simple string ops (bash 3.x safe)
SERVICE_CONTEXT_LIST=(
  "remediator:remediator"
  "polymarket-bot:polymarket-bot"
  "proposals:proposals"
  "email-monitor:email-monitor"
  "voice-receptionist:voice_receptionist"
  "calendar-agent:calendar-agent"
  "notification-hub:notification-hub"
  "dtools-bridge:integrations/dtools"
  "clawwork:clawwork"
  "openclaw:openclaw"
  "knowledge-scanner:knowledge-scanner"
  "mission-control:mission_control"
  "intel-feeds:integrations/intel_feeds"
  "context-preprocessor:context-preprocessor"
)

# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
  GREEN='' YELLOW='' RED='' CYAN='' BOLD='' RESET=''
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%H:%M:%S')] [safe-pull] $*"; }
ok()   { echo -e "[$(date '+%H:%M:%S')] [safe-pull] ${GREEN}✓${RESET} $*"; }
warn() { echo -e "[$(date '+%H:%M:%S')] [safe-pull] ${YELLOW}⚠${RESET} $*"; }
fail() { echo -e "[$(date '+%H:%M:%S')] [safe-pull] ${RED}✗${RESET} $*" >&2; }

die() {
  fail "$*"
  exit 1
}

# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------
backup_vpn_config() {
  local ts="$1"
  local dest="${BACKUP_DIR}/vpn_${ts}"
  mkdir -p "${dest}"
  if [[ -d "${VPN_CONFIG_SRC}" ]]; then
    cp -r "${VPN_CONFIG_SRC}/." "${dest}/"
    ok "WireGuard config backed up → ${dest}"
  else
    warn "VPN config not found at ${VPN_CONFIG_SRC} — skipping backup"
  fi
}

backup_env_file() {
  local ts="$1"
  if [[ -f "${ENV_FILE}" ]]; then
    local dest="${BACKUP_DIR}/.env_${ts}"
    cp "${ENV_FILE}" "${dest}"
    ok ".env backed up → ${dest}"
  else
    warn ".env not found at ${ENV_FILE} — skipping backup"
  fi
}

restore_vpn_config() {
  local ts="$1"
  local src="${BACKUP_DIR}/vpn_${ts}"
  if [[ ! -d "${src}" ]]; then
    warn "No VPN backup found for timestamp ${ts} — skipping restore"
    return 0
  fi
  mkdir -p "${VPN_CONFIG_SRC}"
  # Only copy files that are missing in the destination (don't overwrite
  # newer files that the pull legitimately updated)
  local restored=0
  while IFS= read -r -d '' f; do
    local rel="${f#${src}/}"
    local dst="${VPN_CONFIG_SRC}/${rel}"
    if [[ ! -f "${dst}" ]]; then
      mkdir -p "$(dirname "${dst}")"
      cp "${f}" "${dst}"
      ok "Restored missing VPN file: ${rel}"
      restored=1
    fi
  done < <(find "${src}" -type f -print0)
  if (( ! restored )); then
    log "VPN config files are intact — no restoration needed"
  fi
}

restore_env_file() {
  local ts="$1"
  local src="${BACKUP_DIR}/.env_${ts}"
  if [[ ! -f "${ENV_FILE}" && -f "${src}" ]]; then
    cp "${src}" "${ENV_FILE}"
    ok ".env restored from backup"
  elif [[ -f "${ENV_FILE}" ]]; then
    log ".env is present — no restoration needed"
  fi
}

# ---------------------------------------------------------------------------
# Detect which services need a rebuild based on changed files in the pull
# ---------------------------------------------------------------------------
detect_changed_services() {
  # $1 = newline-separated list of files that changed (from git diff)
  local changed_files="$1"
  # Uses SERVICE_CONTEXT_LIST (bash 3.x compatible — no associative arrays)
  for entry in "${SERVICE_CONTEXT_LIST[@]}"; do
    local service="${entry%%:*}"
    local context="${entry#*:}"
    for f in ${changed_files}; do
      if [[ "${f}" == "${context}/"* || "${f}" == "${context}" ]]; then
        SERVICES_TO_REBUILD+=("${service}")
        break
      fi
    done
  done
}

# ---------------------------------------------------------------------------
# Rebuild a single service using docker compose
# ---------------------------------------------------------------------------
rebuild_service() {
  local service="$1"
  log "Rebuilding service: ${service}"
  (
    cd "${REPO_ROOT}"
    docker compose build --no-cache "${service}" \
      && docker compose up -d --no-deps "${service}"
  ) && ok "Service '${service}' rebuilt and restarted" \
    || warn "Rebuild of '${service}' failed — manual intervention may be required"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
REBUILD_ALL=0
for arg in "$@"; do
  case "${arg}" in
    --rebuild-all) REBUILD_ALL=1 ;;
    --help|-h)
      echo "Usage: $0 [--rebuild-all]"
      echo ""
      echo "  (no flag)      Rebuild only services with changed build contexts"
      echo "  --rebuild-all  Rebuild every service after pulling"
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: $0 [--rebuild-all]" >&2
      exit 1
      ;;
  esac
done

mkdir -p "${BACKUP_DIR}"
cd "${REPO_ROOT}"

TS="$(date '+%Y%m%d_%H%M%S')"
log "=== safe-pull starting (${TS}) ==="

# 1. Capture current HEAD so we can diff later
PRE_PULL_SHA=$(git rev-parse HEAD)
log "Pre-pull HEAD: ${PRE_PULL_SHA}"

# 2. Backup sensitive files before touching anything
backup_vpn_config "${TS}"
backup_env_file   "${TS}"

# 3. Stash local changes (untracked included) so rebase is clean
log "Stashing local changes..."
STASH_OUTPUT=$(git stash --include-untracked 2>&1 || true)
STASH_WAS_EMPTY=0
if echo "${STASH_OUTPUT}" | grep -q "No local changes"; then
  log "Nothing to stash — working tree is clean"
  STASH_WAS_EMPTY=1
else
  ok "Stash created: ${STASH_OUTPUT}"
fi

# 4. Pull
log "Running git pull --rebase origin main..."
if ! git pull --rebase origin main; then
  fail "git pull --rebase failed — aborting"
  # Restore everything before bailing
  if (( ! STASH_WAS_EMPTY )); then
    git rebase --abort 2>/dev/null || true
    git stash pop 2>/dev/null || true
  fi
  restore_vpn_config "${TS}"
  restore_env_file   "${TS}"
  die "Pull failed. Local changes restored. See git output above for details."
fi

POST_PULL_SHA=$(git rev-parse HEAD)
log "Post-pull HEAD: ${POST_PULL_SHA}"

# 5. Restore any files that the pull may have removed
restore_vpn_config "${TS}"
restore_env_file   "${TS}"

# 6. Pop the stash
if (( ! STASH_WAS_EMPTY )); then
  log "Popping stash..."
  if ! git stash pop; then
    warn "Stash pop encountered conflicts — resolve manually with 'git checkout -- <file>'"
    warn "Stash is still saved; run 'git stash list' to see it"
  else
    ok "Stash popped successfully"
  fi
fi

# 7. Determine what changed
if [[ "${PRE_PULL_SHA}" == "${POST_PULL_SHA}" ]]; then
  ok "Already up to date — no changes pulled"
  log "=== safe-pull complete (no rebuild needed) ==="
  exit 0
fi

CHANGED_FILES=$(git diff --name-only "${PRE_PULL_SHA}" "${POST_PULL_SHA}" 2>/dev/null || true)
log "Changed files in this pull:"
echo "${CHANGED_FILES}" | while IFS= read -r f; do log "  ${f}"; done

# 8. Rebuild
if (( REBUILD_ALL )); then
  log "Flag --rebuild-all set — rebuilding all services..."
  (
    cd "${REPO_ROOT}"
    docker compose build --no-cache
    docker compose up -d
  ) && ok "Full stack rebuilt and restarted" || warn "Full rebuild had errors — check docker compose output"
else
  # Detect which services have changes
  SERVICES_TO_REBUILD=()
  detect_changed_services "${CHANGED_FILES}"

  # Deduplicate (bash 3.x compatible — no mapfile)
  if (( ${#SERVICES_TO_REBUILD[@]} > 0 )); then
    local deduped
    deduped=$(printf '%s\n' "${SERVICES_TO_REBUILD[@]}" | sort -u)
    SERVICES_TO_REBUILD=()
    while IFS= read -r svc; do
      [[ -n "${svc}" ]] && SERVICES_TO_REBUILD+=("${svc}")
    done <<< "${deduped}"
  fi

  if (( ${#SERVICES_TO_REBUILD[@]} == 0 )); then
    ok "No build contexts changed — no container rebuilds needed"
  else
    log "Services requiring rebuild: ${SERVICES_TO_REBUILD[*]}"
    for svc in "${SERVICES_TO_REBUILD[@]}"; do
      rebuild_service "${svc}"
    done
  fi
fi

log "=== safe-pull complete (${TS}) ==="
