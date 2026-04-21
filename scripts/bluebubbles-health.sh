#!/usr/bin/env bash
# BlueBubbles bridge health check — host-side CLI.
#
# Probes both:
#   1. The Cortex-side aggregate health endpoint
#      (http://127.0.0.1:8102/api/bluebubbles/health)
#   2. The BlueBubbles server /api/v1/server/info directly, if we have the
#      BLUEBUBBLES_SERVER_URL + BLUEBUBBLES_API_PASSWORD in the repo .env.
#
# Exits 0 if both checks pass, 1 on any failure. Output is concise so this is
# safe to invoke from launchd or bob-watchdog. All output is newline-terminated
# and never contains the API password.
#
# Usage:
#   bash scripts/bluebubbles-health.sh
#   bash scripts/bluebubbles-health.sh --json   # machine-readable
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORTEX_URL="${CORTEX_URL:-http://127.0.0.1:8102}"

_json_mode=0
if [[ "${1:-}" == "--json" ]]; then
  _json_mode=1
fi

# ── load server url + password from repo .env if not already in env ──────────
if [[ -f "$REPO_ROOT/.env" && ( -z "${BLUEBUBBLES_SERVER_URL:-}" || -z "${BLUEBUBBLES_API_PASSWORD:-}" ) ]]; then
  # shellcheck disable=SC2046
  while IFS='=' read -r k v; do
    [[ "$k" == "BLUEBUBBLES_SERVER_URL" && -z "${BLUEBUBBLES_SERVER_URL:-}" ]] && export BLUEBUBBLES_SERVER_URL="$v"
    [[ "$k" == "BLUEBUBBLES_API_PASSWORD" && -z "${BLUEBUBBLES_API_PASSWORD:-}" ]] && export BLUEBUBBLES_API_PASSWORD="$v"
  done < <(grep -E '^(BLUEBUBBLES_SERVER_URL|BLUEBUBBLES_API_PASSWORD)=' "$REPO_ROOT/.env" | sed -E 's/^([A-Z_]+)=(.*)$/\1=\2/')
fi

cortex_status="unknown"
cortex_reason=""
cortex_http=""
if cortex_body=$(curl -sS -m 8 -w '\n%{http_code}' "$CORTEX_URL/api/bluebubbles/health" 2>/dev/null); then
  cortex_http=$(printf '%s' "$cortex_body" | tail -n1)
  cortex_payload=$(printf '%s' "$cortex_body" | sed '$d')
  if [[ "$cortex_http" == "200" ]]; then
    cortex_status=$(printf '%s' "$cortex_payload" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status","unknown"))' 2>/dev/null || echo "unknown")
    cortex_reason=$(printf '%s' "$cortex_payload" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("reason") or "")' 2>/dev/null || echo "")
  else
    cortex_status="unreachable"
    cortex_reason="cortex_http_$cortex_http"
  fi
else
  cortex_status="unreachable"
  cortex_reason="cortex_offline"
fi

# ── direct BlueBubbles server ping ───────────────────────────────────────────
bb_status="unknown"
bb_reason=""
bb_http=""
bb_version=""
bb_private_api=""
if [[ -n "${BLUEBUBBLES_SERVER_URL:-}" && -n "${BLUEBUBBLES_API_PASSWORD:-}" ]]; then
  url="${BLUEBUBBLES_SERVER_URL%/}/api/v1/server/info"
  if bb_body=$(curl -sS -m 8 -w '\n%{http_code}' -G --data-urlencode "password=$BLUEBUBBLES_API_PASSWORD" "$url" 2>/dev/null); then
    bb_http=$(printf '%s' "$bb_body" | tail -n1)
    bb_payload=$(printf '%s' "$bb_body" | sed '$d')
    if [[ "$bb_http" == "200" ]]; then
      bb_status="healthy"
      bb_version=$(printf '%s' "$bb_payload" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print(d.get("server_version",""))' 2>/dev/null || echo "")
      bb_private_api=$(printf '%s' "$bb_payload" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print("true" if d.get("private_api") else "false")' 2>/dev/null || echo "false")
    else
      bb_status="unhealthy"
      bb_reason="http_$bb_http"
    fi
  else
    bb_status="unhealthy"
    bb_reason="connect_failed"
  fi
else
  bb_status="not_configured"
  bb_reason="env_missing"
fi

# ── emit output ──────────────────────────────────────────────────────────────
if [[ "$_json_mode" == "1" ]]; then
  python3 - "$cortex_status" "$cortex_reason" "$bb_status" "$bb_reason" "$bb_version" "$bb_private_api" <<'PY'
import json, sys
(_, cs, cr, bs, br, bv, bp) = sys.argv
print(json.dumps({
    "cortex_health": {"status": cs, "reason": cr or None},
    "bluebubbles_server": {
        "status": bs,
        "reason": br or None,
        "server_version": bv or None,
        "private_api": bp == "true",
    },
}))
PY
else
  printf 'cortex bluebubbles health: %s%s\n' "$cortex_status" "${cortex_reason:+ (${cortex_reason})}"
  printf 'bluebubbles server ping:   %s%s%s\n' "$bb_status" \
    "${bb_reason:+ (${bb_reason})}" \
    "${bb_version:+ version=${bb_version} private_api=${bb_private_api}}"
fi

# ── exit code ────────────────────────────────────────────────────────────────
if [[ "$cortex_status" == "healthy" && "$bb_status" == "healthy" ]]; then
  exit 0
fi
exit 1
