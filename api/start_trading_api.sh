#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

export TRADING_API_PORT="${TRADING_API_PORT:-8421}"
"${PYTHON_BIN}" "${ROOT_DIR}/api/trading_api.py"
