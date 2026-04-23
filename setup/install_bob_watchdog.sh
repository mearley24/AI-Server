#!/bin/bash
# setup/install_bob_watchdog.sh
#
# Idempotent installer for com.symphony.bob-watchdog (user LaunchAgent).
#
# What it does:
#   - Makes the watchdog script executable.
#   - Deploys scripts/bob-watchdog.sh to /usr/local/bin/bob-watchdog.sh
#     (the path used by the system LaunchDaemon). Tries direct copy first;
#     falls back to sudo when /usr/local/bin is root-owned.
#   - Verifies the deployed copy's SHA-256 matches the repo source.
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
#   5   checksum mismatch after deploy (deployed file differs from repo)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LABEL="com.symphony.bob-watchdog"
REPO_PLIST="${REPO_ROOT}/ops/launchd/${LABEL}.plist"
WATCHDOG_SH="${REPO_ROOT}/scripts/bob-watchdog.sh"

# System path used by the root LaunchDaemon plist.
DAEMON_SH="/usr/local/bin/bob-watchdog.sh"

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

# Print SHA-256 of a file (macOS shasum).
file_sha256() {
  shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
}

# Compare repo source checksum against deployed copy. Prints result; returns
# 0 on match, 1 on mismatch or missing deployed file.
verify_checksum() {
  local src="${1}" dst="${2}"
  local src_sum dst_sum
  src_sum=$(file_sha256 "${src}")
  dst_sum=$(file_sha256 "${dst}")
  if [ -z "${dst_sum}" ]; then
    echo "checksum SKIP  ${dst} not found"
    return 1
  fi
  if [ "${src_sum}" = "${dst_sum}" ]; then
    echo "checksum OK    sha256:${src_sum}"
    return 0
  fi
  echo "checksum MISMATCH" >&2
  printf '  repo: sha256:%s\n' "${src_sum}" >&2
  printf '  live: sha256:%s\n' "${dst_sum}" >&2
  return 1
}

# Copy src to dst, trying direct write first then sudo.
# Returns 0 on success, 1 if both paths fail.
deploy_system_script() {
  local src="${1}" dst="${2}"
  mkdir -p "$(dirname "${dst}")" 2>/dev/null || true
  if cp "${src}" "${dst}" 2>/dev/null && chmod 755 "${dst}" 2>/dev/null; then
    return 0
  fi
  # Fallback: sudo — requires an interactive terminal with password.
  if sudo cp "${src}" "${dst}" 2>/dev/null && sudo chmod 755 "${dst}" 2>/dev/null; then
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------
# --status: show agent registration + checksum comparison
# ------------------------------------------------------------------
status_line() {
  if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
    launchctl list 2>/dev/null | awk -v l="${LABEL}" '$3==l {print}' | head -1
  else
    echo "${LABEL} not loaded"
  fi
}

if [ "${mode}" = "status" ]; then
  echo "=== LaunchAgent status ==="
  status_line
  echo ""
  echo "=== System daemon script checksum ==="
  if [ -f "${DAEMON_SH}" ]; then
    printf 'repo  mtime: %s\n' "$(stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "${WATCHDOG_SH}" 2>/dev/null)"
    printf 'live  mtime: %s\n' "$(stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "${DAEMON_SH}" 2>/dev/null)"
    verify_checksum "${WATCHDOG_SH}" "${DAEMON_SH}" && echo "Daemon copy is UP TO DATE." || echo "Daemon copy is STALE — re-run install to sync."
  else
    echo "${DAEMON_SH} not found — run install to deploy."
  fi
  exit 0
fi

# ------------------------------------------------------------------
# --uninstall
# ------------------------------------------------------------------
if [ "${mode}" = "uninstall" ]; then
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
  rm -f "${TARGET_PLIST}"
  echo "uninstalled ${LABEL}"
  status_line
  exit 0
fi

# ------------------------------------------------------------------
# --install (default)
# ------------------------------------------------------------------
for required in "${REPO_PLIST}" "${WATCHDOG_SH}"; do
  if [ ! -f "${required}" ]; then
    echo "error: missing required file: ${required}" >&2
    exit 3
  fi
done

mkdir -p "${LAUNCH_AGENTS_DIR}"
mkdir -p "${REPO_ROOT}/data/task_runner"
chmod +x "${WATCHDOG_SH}"

# --- Deploy system copy ---
echo "Deploying ${DAEMON_SH} ..."
if deploy_system_script "${WATCHDOG_SH}" "${DAEMON_SH}"; then
  echo "  deployed: ${DAEMON_SH}"
  if ! verify_checksum "${WATCHDOG_SH}" "${DAEMON_SH}"; then
    echo "error: deployed file checksum does not match repo source" >&2
    exit 5
  fi
else
  echo "warning: could not write ${DAEMON_SH}" >&2
  echo "  Run manually:" >&2
  printf '  sudo cp %s %s && sudo chmod 755 %s\n' "${WATCHDOG_SH}" "${DAEMON_SH}" "${DAEMON_SH}" >&2
  echo "  Then re-run: bash setup/install_bob_watchdog.sh" >&2
fi

# --- Optional: create system log/state dirs when writable ---
for d in /usr/local/var/log /usr/local/var/bob-watchdog; do
  mkdir -p "${d}" 2>/dev/null || true
done

# --- Install user LaunchAgent plist ---
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

echo ""
echo "installed ${LABEL}"
echo "plist:  ${TARGET_PLIST}"
echo "daemon: ${DAEMON_SH}"
echo "log:    ${REPO_ROOT}/data/task_runner/bob-watchdog.out.log"
status_line
