#!/usr/bin/env bash
set -euo pipefail
URL="${1:?url}"
JSON="${2:?json}"
AUTH="${3:-}"
TMP="$(mktemp /tmp/api-post-XXXXXX.json)"
trap 'rm -f "$TMP"' EXIT
printf '%s' "$JSON" > "$TMP"
if [ -n "$AUTH" ]; then
  curl -sS -X POST "$URL" -H "$AUTH" -H "Content-Type: application/json" --data-binary @"$TMP"
else
  curl -sS -X POST "$URL" -H "Content-Type: application/json" --data-binary @"$TMP"
fi
echo
