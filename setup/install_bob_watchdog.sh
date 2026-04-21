#!/bin/bash
# setup/install_bob_watchdog.sh
#
# Idempotent installer for com.symphony.bob-watchdog (user LaunchAgent).
#
# What it does:
#   - Makes the watchdog script executable.
#   - Writes state & log directories the watchdog needs outside the repo
#     (/usr/local/var/log, /usr/local/var/bob-watchdog). Skipped gracefully
#     if those directories are not writable (root-owned).
#   - Copies ops/launchd/com.symphony.bob-watchdog.plist into
#     ~/Library/LaunchAgents/ and loads it as a user agent.
#   - Kicks it once so the first tick runs immediately.
#
# Safe to re-run. Uninstall with --uninstall. Status with --status.
#
# Exit codes:
#   0   install ok / uninstall ok / status printed
#   2   unsupported flag
#   3   required repo file missing
#   4   launchctl load failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LABEL="com.symphony.bob-watchdog"
REPO_PLIST="${REPO_ROOT}/ops/launchd/${LABEL}.plist"
WATCHDOG_SH="${REPO_ROOT}/scripts/bob-watchdog.sh"

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"

mode="install"
case "${1:-}" in
  --uninstall) mode="uninstall" ;;
  --status)    mode="status" ;;
  ""|--install) mode="install" ;;
  *) echo "error: unsupported flag ${1}" >&2
     echo "usage: $0 [--install|--uninstall|--status]" >&2
     exit 2 ;;
esac

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
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
  rm -f "${TARGET_PLIST}"
  echo "uninstalled ${LABEL}"
  status_line
  exit 0
fi

for required in "${REPO_PLIST}" "${WATCHDOG_SH}"; do
  if [ ! -f "${required}" ]; then
    echo "error: missing required file: ${required}" >&2
    exit 3
  fi
done

mkdir -p "${LAUNCH_AGENTS_DIR}"
mkdir -p "${REPO_ROOT}/data/task_runner"
chmod +x "${WATCHDOG_SH}"

cp "${REPO_PLIST}" "${TARGET_PLIST}"

# Unload any existing registration so changes take effect.
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl unload "${TARGET_PLIST}" 2>/dev/null || true

if ! launchctl bootstrap "gui/$(id -u)" "${TARGET_PLIST}"; then
  # Fallback for older macOS releases that don't support bootstrap.
  if ! launchctl load "${TARGET_PLIST}"; then
    echo "error: launchctl load failed for ${TARGET_PLIST}" >&2
    exit 4
  fi
fi

launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>/dev/null || true

echo "installed ${LABEL}"
echo "plist: ${TARGET_PLIST}"
echo "log:   ${REPO_ROOT}/data/task_runner/bob-watchdog.out.log"
status_line
