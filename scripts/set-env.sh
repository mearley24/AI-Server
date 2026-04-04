#!/usr/bin/env bash
set -euo pipefail
KEY="${1:?key}"
VAL="${2:?value}"
FILE="${3:-.env}"
ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"
if [[ "$FILE" != /* ]]; then
  FILE="$ROOT/$FILE"
fi
touch "$FILE"
if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' "/^${KEY}=/d" "$FILE"
else
  sed -i "/^${KEY}=/d" "$FILE"
fi
echo "${KEY}=${VAL}" >> "$FILE"
echo "Set ${KEY} in ${FILE}"
