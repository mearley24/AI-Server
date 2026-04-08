#!/usr/bin/env bash
# Verify Docker health + iMessage bridge; restart unhealthy services; notify owner.
# Crash-looping services are git-reset to origin/main before rebuild so bad code
# can't keep the service down indefinitely.
# Intended for cron every ~5 minutes on the Mac Mini.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
cd "$ROOT"

LOG_FILE="${BOB_HEALTHCHECK_LOG:-/tmp/bob-healthcheck.log}"
BRIDGE_PORT="${IMESSAGE_BRIDGE_PORT:-8199}"
export IMESSAGE_BRIDGE_PORT="${BRIDGE_PORT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

NOTIFY_PHONE="${MATT_PHONE:-${OWNER_PHONE_NUMBER:-}}"
export NOTIFY_PHONE

# Map Docker service name -> source directory (for git-reset on crash loops)
declare -A SERVICE_PATHS=(
  [email-monitor]="email-monitor"
  [polymarket-bot]="polymarket-bot"
  [notification-hub]="notification-hub"
  [openclaw]="openclaw"
  [mission-control]="mission-control"
  [calendar-agent]="calendar-agent"
  [clawwork]="clawwork"
  [knowledge-base]="knowledge-base"
  [voice-receptionist]="voice-receptionist"
  [context-preprocessor]="context-preprocessor"
  [d-tools-bridge]="d-tools-bridge"
)

ts()         { date '+%Y-%m-%dT%H:%M:%S'; }
log()        { echo "$(ts) [healthcheck] $*" | tee -a "${LOG_FILE}"; }

send_alert() {
  local msg="$1"
  [[ -z "${NOTIFY_PHONE}" ]] && return 0
  NOTIFY_PHONE="${NOTIFY_PHONE}" ALERT_BODY="${msg}" python3 <<'PY' 2>/dev/null || true
import json, os, urllib.request
phone = (os.environ.get("NOTIFY_PHONE") or "").strip()
body  = (os.environ.get("ALERT_BODY")   or "").strip()
if not phone or not body:
    raise SystemExit(0)
port = (os.environ.get("IMESSAGE_BRIDGE_PORT") or "8199").strip()
req = urllib.request.Request(
    "http://127.0.0.1:%s/" % port,
    data=json.dumps({"phone": phone, "body": body}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
urllib.request.urlopen(req, timeout=15)
PY
}

# Validate Python source before rebuilding — prevents deploy of broken code
py_compile_check() {
  local svc="$1"
  local src_dir="${SERVICE_PATHS[$svc]:-}"
  [[ -z "$src_dir" || ! -d "$src_dir" ]] && return 0   # no source mapping, skip
  local failed=()
  while IFS= read -r -d '' pyfile; do
    if ! python3 -m py_compile "$pyfile" 2>/dev/null; then
      failed+=("$pyfile")
    fi
  done < <(find "$src_dir" -name "*.py" -print0 2>/dev/null)
  if [[ ${#failed[@]} -gt 0 ]]; then
    log "py_compile FAILED in ${svc}: ${failed[*]}"
    return 1
  fi
  return 0
}

# Git-reset a service's source directory to origin/main
git_reset_service() {
  local svc="$1"
  local src_dir="${SERVICE_PATHS[$svc]:-}"
  [[ -z "$src_dir" ]] && return 0
  log "git reset ${svc} source to origin/main"
  git fetch origin >> "${LOG_FILE}" 2>&1 \
    && git checkout origin/main -- "$src_dir" >> "${LOG_FILE}" 2>&1 \
    && log "git reset OK for ${svc}" \
    || log "git reset FAILED for ${svc} (continuing with local code)"
}

# ── iMessage bridge ────────────────────────────────────────────

BRIDGE_OK=1
if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
  log "iMessage bridge OK (${BRIDGE_PORT})"
else
  BRIDGE_OK=0
  log "iMessage bridge DOWN on ${BRIDGE_PORT} — restarting"
  if [[ -z "${OPENAI_API_KEY:-}" ]] && [[ -f .env ]]; then
    set -a; source .env; set +a
  fi
  export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
  nohup python3 "${ROOT}/scripts/imessage-server.py" >> "${IMESSAGE_BRIDGE_LOG:-/tmp/imessage-bridge.log}" 2>&1 &
  sleep 3
  if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
    log "iMessage bridge recovered"
    send_alert "Bob: iMessage bridge was down — restarted OK."
  else
    log "iMessage bridge still not responding"
    send_alert "Bob: iMessage bridge FAILED to start on port ${BRIDGE_PORT}."
  fi
fi

# ── Container health loop ──────────────────────────────────────

RESTARTED=""
while read -r line; do
  [[ -z "${line}" ]] && continue
  cid="${line%% *}"
  svc="${line#* }"
  [[ -z "${cid}" || -z "${svc}" ]] && continue

  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo unknown)"
  state="$(docker inspect --format '{{.State.Status}}' "${cid}" 2>/dev/null || echo unknown)"
  restarts="$(docker inspect --format '{{.RestartCount}}' "${cid}" 2>/dev/null || echo 0)"

  needs_rebuild=0

  if [[ "${state}" != "running" ]]; then
    log "Service ${svc} not running (state=${state}, restarts=${restarts})"
    needs_rebuild=1
  elif [[ "${health}" == "unhealthy" ]]; then
    log "Service ${svc} unhealthy (restarts=${restarts})"
    needs_rebuild=1
  elif [[ "${health}" == "starting" ]]; then
    log "Service ${svc} still starting"
  fi

  # Crash loop: running but restarted 3+ times — treat as broken
  if [[ "${restarts}" -ge 3 && "${state}" == "running" && "${needs_rebuild}" -eq 0 ]]; then
    log "Service ${svc} crash loop detected (${restarts} restarts)"
    needs_rebuild=1
  fi

  if [[ "${needs_rebuild}" -eq 1 ]]; then
    # 1. Git-reset source to clean state
    git_reset_service "${svc}"

    # 2. Validate Python before building
    if ! py_compile_check "${svc}"; then
      send_alert "Bob: ${svc} has syntax errors even after git reset — needs manual fix."
      continue
    fi

    # 3. Rebuild and restart
    log "Rebuilding ${svc}"
    if /usr/local/bin/docker compose up -d --build "${svc}" >> "${LOG_FILE}" 2>&1; then
      RESTARTED="${RESTARTED} ${svc}"
    else
      log "Rebuild FAILED for ${svc}"
      send_alert "Bob: failed to rebuild ${svc} — check ${LOG_FILE}."
    fi
  fi

done < <(/usr/local/bin/docker compose ps -q 2>/dev/null | while read -r q; do
  [[ -z "${q}" ]] && continue
  state="$(docker inspect --format '{{.State.Status}}' "${q}" 2>/dev/null || true)"
  [[ "${state}" != "running" ]] && { s="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "${q}" 2>/dev/null || true)"; [[ -n "${s}" ]] && echo "${q} ${s}"; continue; }
  s="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "${q}" 2>/dev/null || true)"
  [[ -n "${s}" ]] && echo "${q} ${s}"
done)

if [[ -n "${RESTARTED// /}" ]]; then
  send_alert "Bob: rebuilt/restarted:${RESTARTED}"
fi

if [[ "${BRIDGE_OK}" -eq 1 && -z "${RESTARTED// /}" ]]; then
  log "All checks passed"
fi
