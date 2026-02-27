#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_SERVER_DIR="$SCRIPT_DIR"

VENV_ACTIVATE="$AI_SERVER_DIR/.venv/bin/activate"
if [ -f "$VENV_ACTIVATE" ]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
  PYBIN="python"
else
  PYBIN="python3"
fi

export AI_SERVER_DIR
exec "$PYBIN" "$AI_SERVER_DIR/orchestrator/core/bob_orchestrator.py" "$@"
