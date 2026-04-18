#!/bin/bash
# scripts/realized_change_watcher.sh
#
# Fires an autonomy sweep when launchd signals a realized change via
# com.symphony.realized-change-watcher's WatchPaths. The watcher plist
# points at two things:
#
#   1. STATUS_REPORT.md  (content changes to the operational status doc)
#   2. ops/realized_changes/ (sentinel files any agent drops in)
#
# Behaviour:
#   - Idempotent: if the sweep script is missing we write a blocker report
#     and exit clean. launchd's own ThrottleInterval prevents retry storms.
#   - Bounded: no long-running processes, no watch modes, no heredocs.
#   - Quiet: normal runs write exactly one verification file via
#     scripts/autonomy_sweep.py; they do not push or rebuild anything.
#
# Exit codes:
#   0   sweep fired (or intentionally skipped)
#   2   invalid invocation
#   3   autonomy_sweep.py missing

set -uo pipefail

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SWEEP_SCRIPT="${REPO_ROOT}/scripts/autonomy_sweep.py"
REALIZED_DIR="${REPO_ROOT}/ops/realized_changes"
VERIFICATION_DIR="${REPO_ROOT}/ops/verification"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3}"

if [ ! -x "${PYTHON_BIN}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  fi
fi

mkdir -p "${REALIZED_DIR}" "${VERIFICATION_DIR}"
cd "${REPO_ROOT}" || exit 2

stamp="$(date '+%Y%m%d-%H%M%S')"

if [ ! -f "${SWEEP_SCRIPT}" ]; then
  blocker="${VERIFICATION_DIR}/${stamp}-blocker-realized-change-watcher.txt"
  printf 'realized-change watcher fired but autonomy_sweep.py is missing.\nExpected: %s\n' \
    "${SWEEP_SCRIPT}" > "${blocker}"
  exit 3
fi

trigger_source="${1:-launchd-watchpath}"
trigger_file=""

newest=""
if [ -d "${REALIZED_DIR}" ]; then
  newest="$(find "${REALIZED_DIR}" -maxdepth 1 -type f \( -name '*.change' -o -name '*.json' -o -name '*.txt' \) -print 2>/dev/null | sort | tail -1)"
fi
if [ -n "${newest}" ]; then
  trigger_file="$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1], sys.argv[2]))" "${newest}" "${REPO_ROOT}")"
fi

slug="realized-change"

argv=(
  "${PYTHON_BIN}" "${SWEEP_SCRIPT}"
  "--trigger" "${trigger_source}"
  "--slug" "${slug}"
)

if [ -n "${trigger_file}" ]; then
  argv+=("--trigger-path" "${trigger_file}")
fi

"${argv[@]}"
rc=$?

exit "${rc}"
