#!/usr/bin/env bash
# Start iMessage bridge on the host, bring up Docker Compose, tail logs briefly, notify owner.
# Usage: from repo root, ./scripts/startup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

_ts() { date '+%Y-%m-%dT%H:%M:%S'; }

BRIDGE_PORT="${IMESSAGE_BRIDGE_PORT:-8199}"
export IMESSAGE_BRIDGE_PORT="${BRIDGE_PORT}"
LOG_FILE="${IMESSAGE_BRIDGE_LOG:-/tmp/imessage-bridge.log}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
if [[ -z "${OPENAI_API_KEY}" ]]; then
  echo "$(_ts) [startup] WARNING: OPENAI_API_KEY is empty after sourcing .env" >&2
fi

NOTIFY_PHONE="${MATT_PHONE:-${OWNER_PHONE_NUMBER:-}}"
export NOTIFY_PHONE

wait_for_bridge() {
  local i
  for i in $(seq 1 90); do
    if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
      echo "$(_ts) [startup] iMessage bridge responding on port ${BRIDGE_PORT}"
      return 0
    fi
    sleep 1
  done
  echo "$(_ts) [startup] ERROR: bridge did not become ready on port ${BRIDGE_PORT}" >&2
  return 1
}

if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/" >/dev/null 2>&1; then
  echo "$(_ts) [startup] iMessage bridge already up on ${BRIDGE_PORT}"
else
  echo "$(_ts) [startup] Starting iMessage bridge (host, not Docker)..."
  nohup python3 "${ROOT}/scripts/imessage-server.py" >> "${LOG_FILE}" 2>&1 &
  echo $! > /tmp/imessage-bridge.pid
  wait_for_bridge
fi

echo "$(_ts) [startup] docker compose up -d --build"
docker compose up -d --build

echo "$(_ts) [startup] Tailing compose logs (~30s)..."
set +e
docker compose logs -f --tail 30 &
LOGF_PID=$!
sleep 30
kill "${LOGF_PID}" 2>/dev/null || true
wait "${LOGF_PID}" 2>/dev/null || true
set -e

if [[ -n "${NOTIFY_PHONE}" ]]; then
  LIST="$(docker compose ps --format '{{.Name}}' 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  export STARTUP_IMESSAGE_BODY="Bob is online — all services healthy. Containers: ${LIST}"
  echo "$(_ts) [startup] Sending iMessage confirmation..."
  set +e
  NOTIFY_PHONE="${NOTIFY_PHONE}" python3 <<'PY'
import json
import os
import urllib.request

phone = (os.environ.get("NOTIFY_PHONE") or "").strip()
body = (os.environ.get("STARTUP_IMESSAGE_BODY") or "").strip()
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
print("notify_ok")
PY
  notify_rc=$?
  set -e
  if [[ "${notify_rc}" -ne 0 ]]; then
    echo "$(_ts) [startup] WARNING: iMessage notify failed (rc=${notify_rc})" >&2
  fi
else
  echo "$(_ts) [startup] Skipping iMessage (set MATT_PHONE or OWNER_PHONE_NUMBER in .env)"
fi

echo "$(_ts) [startup] Done."
