#!/bin/bash
# setup/install_realized_change_watcher.sh
#
# Idempotent installer for com.symphony.realized-change-watcher.
#
# What it does:
#   - Verifies required repo files exist (launchd plist, watcher script,
#     sweep script).
#   - Copies ops/launchd/com.symphony.realized-change-watcher.plist into
#     ~/Library/LaunchAgents/ (overwriting any older version).
#   - Unloads any existing instance first so edits take effect cleanly.
#   - Loads the plist and prints a short status line.
#
# Safe to run repeatedly. Does NOT trigger the watcher — it only installs
# and arms it. The first sweep will fire the next time STATUS_REPORT.md
# is saved or a sentinel file lands in ops/realized_changes/.
#
# Usage:
#   bash setup/install_realized_change_watcher.sh            # install
#   bash setup/install_realized_change_watcher.sh --uninstall
#   bash setup/install_realized_change_watcher.sh --status
#
# Exit codes:
#   0   install ok (or uninstall ok, or status printed)
#   2   unsupported flag
#   3   required repo file missing
#   4   launchd load failed

set -uo pipefail

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LABEL="com.symphony.realized-change-watcher"
REPO_PLIST="${REPO_ROOT}/ops/launchd/${LABEL}.plist"
WATCHER_SCRIPT="${REPO_ROOT}/scripts/realized_change_watcher.sh"
SWEEP_SCRIPT="${REPO_ROOT}/scripts/autonomy_sweep.py"

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"

mode="install"
if [ "${1:-}" = "--uninstall" ]; then
  mode="uninstall"
elif [ "${1:-}" = "--status" ]; then
  mode="status"
elif [ -n "${1:-}" ] && [ "${1:-}" != "--install" ]; then
  echo "error: unsupported flag ${1}" >&2
  echo "usage: $0 [--install|--uninstall|--status]" >&2
  exit 2
fi

status_line() {
  if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
    launchctl list 2>/dev/null | awk -v l="${LABEL}" '$3==l {print}' | head -1
  else
    echo "${LABEL} not loaded"
  fi
}

if [ "${mode}" = "status" ]; then
  status_line
  exit 0
fi

if [ "${mode}" = "uninstall" ]; then
  launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
  rm -f "${TARGET_PLIST}"
  echo "uninstalled ${LABEL}"
  status_line
  exit 0
fi

for required in "${REPO_PLIST}" "${WATCHER_SCRIPT}" "${SWEEP_SCRIPT}"; do
  if [ ! -f "${required}" ]; then
    echo "error: missing required file: ${required}" >&2
    exit 3
  fi
done

mkdir -p "${LAUNCH_AGENTS_DIR}"
chmod +x "${WATCHER_SCRIPT}" 2>/dev/null || true

cp "${REPO_PLIST}" "${TARGET_PLIST}"

launchctl unload "${TARGET_PLIST}" 2>/dev/null || true

if ! launchctl load "${TARGET_PLIST}"; then
  echo "error: launchctl load failed for ${TARGET_PLIST}" >&2
  exit 4
fi

echo "installed ${LABEL}"
echo "plist: ${TARGET_PLIST}"
status_line
