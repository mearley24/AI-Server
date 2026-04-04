#!/usr/bin/env bash
# Verify Docker health + iMessage bridge; restart unhealthy services; notify owner.
# Intended for cron every ~5 minutes on the Mac Mini.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

ts() { date '+%Y-%m-%dT%H:%M:%S'; }

log() { echo "$(ts) [healthcheck] $*" | tee -a "${LOG_FILE}"; }

send_alert() {
  local msg="$1"
  [[ -z "${NOTIFY_PHONE}" ]] && return 0
  NOTIFY_PHONE="${NOTIFY_PHONE}" ALERT_BODY="${msg}" python3 <<'PY' 2>/dev/null || true
import json
import os
import urllib.request

phone = (os.environ.get("NOTIFY_PHONE") or "").strip()
body = (os.environ.get("ALERT_BODY") or "").strip()
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

BRIDGE_OK=1
if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
  log "iMessage bridge OK (${BRIDGE_PORT})"
else
  BRIDGE_OK=0
  log "iMessage bridge DOWN on ${BRIDGE_PORT} — restarting"
  if [[ -z "${OPENAI_API_KEY:-}" ]] && [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
  export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
  nohup python3 "${ROOT}/scripts/imessage-server.py" >> "${IMESSAGE_BRIDGE_LOG:-/tmp/imessage-bridge.log}" 2>&1 &
  sleep 3
  if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
    log "iMessage bridge recovered"
    send_alert "Bob healthcheck: iMessage bridge was down; restarted. OK now."
  else
    log "iMessage bridge still not responding"
    send_alert "Bob healthcheck: iMessage bridge failed to start on port ${BRIDGE_PORT}."
  fi
fi

RESTARTED=""
while read -r line; do
  [[ -z "${line}" ]] && continue
  cid="${line%% *}"
  svc="${line#* }"
  [[ -z "${cid}" || -z "${svc}" ]] && continue
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo unknown)"
  state="$(docker inspect --format '{{.State.Status}}' "${cid}" 2>/dev/null || echo unknown)"

  if [[ "${state}" != "running" ]]; then
    log "Service ${svc} not running (state=${state}) — docker compose up -d --build ${svc}"
    if docker compose up -d --build "${svc}" >>"${LOG_FILE}" 2>&1; then
      RESTARTED="${RESTARTED} ${svc}"
    fi
    continue
  fi

  if [[ "${health}" == "unhealthy" ]]; then
    log "Service ${svc} unhealthy — docker compose up -d --build ${svc}"
    if docker compose up -d --build "${svc}" >>"${LOG_FILE}" 2>&1; then
      RESTARTED="${RESTARTED} ${svc}"
    fi
  elif [[ "${health}" == "starting" ]]; then
    log "Service ${svc} still starting (health)"
  fi
done < <(docker compose ps -q 2>/dev/null | while read -r q; do
  [[ -z "${q}" ]] && continue
  state="$(docker inspect --format '{{.State.Status}}' "${q}" 2>/dev/null || true)"
  [[ "${state}" != "running" ]] && continue
  s="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "${q}" 2>/dev/null || true)"
  [[ -n "${s}" ]] && echo "${q} ${s}"
done)

if [[ -n "${RESTARTED// /}" ]]; then
  send_alert "Bob healthcheck: rebuilt/restarted:${RESTARTED} (see ${LOG_FILE})"
fi

if [[ "${BRIDGE_OK}" -eq 1 && -z "${RESTARTED// /}" ]]; then
  log "All checks passed"
fi
