#!/usr/bin/env bash
# install_self_improvement_watcher.sh — dry-run installer for the
# self-improvement launchd watcher.
#
# Modes:
#   --dry-run   Print what would be installed. Does NOT touch disk.
#   --install   (Matt only, on Bob) copy the plist into
#               ~/Library/LaunchAgents/ and print the exact
#               `launchctl bootstrap` command. Does NOT bootstrap.
#   --uninstall (Matt only, on Bob) remove the plist from
#               ~/Library/LaunchAgents/ and print the exact
#               `launchctl bootout` command. Does NOT bootout.
#
# This script NEVER calls launchctl on your behalf. It only stages
# files and prints the commands Matt must run manually after a
# deliberate review. That is by design — recurring local jobs consume
# compute and API budget and should be turned on knowingly.
#
# Default is --dry-run. Running with no args == --dry-run.

set -euo pipefail

MODE="${1:---dry-run}"

PLIST_NAME="com.symphony.self-improvement.plist"
SRC_PLIST_REPO_REL="setup/launchd/${PLIST_NAME}"
DEST_DIR="${HOME}/Library/LaunchAgents"
DEST_PLIST="${DEST_DIR}/${PLIST_NAME}"

# Locate repo root (same logic as the other scripts).
resolve_repo_root() {
  if [ -d "${HOME}/AI-Server/.git" ]; then
    echo "${HOME}/AI-Server"
    return 0
  fi
  local here dir
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  dir="$here"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/.git" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

REPO_ROOT="$(resolve_repo_root)" || {
  echo "[install-watcher] ERROR: could not locate AI-Server repo root" >&2
  exit 1
}

SRC_PLIST="${REPO_ROOT}/${SRC_PLIST_REPO_REL}"

banner() {
  echo "== self-improvement watcher installer =="
  echo "mode:         $MODE"
  echo "repo_root:    $REPO_ROOT"
  echo "source plist: $SRC_PLIST"
  echo "dest plist:   $DEST_PLIST"
  echo
}

check_plist_source() {
  if [ ! -f "$SRC_PLIST" ]; then
    echo "[install-watcher] ERROR: source plist not found at $SRC_PLIST" >&2
    exit 1
  fi
}

check_host_is_bob() {
  # Soft check: look for the conventional AI-Server install path on Bob.
  if [ ! -d "${HOME}/AI-Server" ] && [ "${REPO_ROOT}" != "${HOME}/AI-Server" ]; then
    echo "[install-watcher] NOTE: expected ~/AI-Server on Bob; this host may differ."
    echo "                  Proceeding so you can see the dry-run output."
    echo
  fi
}

cmd_dry_run() {
  banner
  check_plist_source
  check_host_is_bob
  echo "This is a DRY RUN. No files will be written. No launchctl calls."
  echo
  echo "If you re-ran with --install, this script would:"
  echo "  1. mkdir -p $DEST_DIR"
  echo "  2. cp $SRC_PLIST $DEST_PLIST"
  echo "  3. Print (for you to run manually):"
  echo
  echo "       launchctl bootstrap gui/\$(id -u) $DEST_PLIST"
  echo "       launchctl kickstart -k gui/\$(id -u)/com.symphony.self-improvement"
  echo
  echo "Before enabling, read:"
  echo "  - docs/self-improvement-loop.md (always-on loop semantics)"
  echo "  - setup/launchd/${PLIST_NAME} (inline comments on cost)"
  echo
  echo "Rough cost estimate at 30-min cadence:"
  echo "  up to 48 Claude Code invocations / day if inbox is non-empty."
  echo "  Inbox-empty runs short-circuit cheaply."
  echo
  echo "To tighten the cadence (e.g. every 60 min), edit StartInterval"
  echo "in the plist to 3600 before bootstrapping."
  echo
  echo "Sanity checks you should run first:"
  echo "  bash scripts/self-improve.sh sources"
  echo "  bash scripts/self-improve.sh scan"
  echo "  bash scripts/self-improve.sh daemon-once"
  echo
  echo "STATUS: DRY-RUN OK"
}

cmd_install() {
  banner
  check_plist_source
  check_host_is_bob

  echo "Staging plist (no launchctl call)..."
  mkdir -p "$DEST_DIR"
  cp "$SRC_PLIST" "$DEST_PLIST"
  echo "Copied: $DEST_PLIST"
  echo
  echo "NEXT — run these manually on Bob after reviewing the plist:"
  echo
  echo "  launchctl bootstrap gui/\$(id -u) $DEST_PLIST"
  echo "  launchctl kickstart -k gui/\$(id -u)/com.symphony.self-improvement"
  echo
  echo "To watch output:"
  echo "  tail -f ~/AI-Server/data/task_runner/self-improvement.out.log"
  echo "  tail -f ~/AI-Server/data/task_runner/self-improvement.err.log"
  echo
  echo "STATUS: STAGED (not bootstrapped — launchctl not invoked)"
}

cmd_uninstall() {
  banner
  if [ -f "$DEST_PLIST" ]; then
    echo "Removing staged plist: $DEST_PLIST"
    rm -f "$DEST_PLIST"
  else
    echo "No staged plist at $DEST_PLIST — nothing to remove."
  fi
  echo
  echo "NEXT — run this manually on Bob to unload the watcher:"
  echo "  launchctl bootout gui/\$(id -u)/com.symphony.self-improvement || true"
  echo
  echo "STATUS: UNSTAGED (not booted out — launchctl not invoked)"
}

case "$MODE" in
  --dry-run|"")   cmd_dry_run ;;
  --install)      cmd_install ;;
  --uninstall)    cmd_uninstall ;;
  -h|--help|help)
    cat <<'EOF'
Usage:
  bash setup/install_self_improvement_watcher.sh --dry-run
  bash setup/install_self_improvement_watcher.sh --install    # stage only; prints launchctl commands
  bash setup/install_self_improvement_watcher.sh --uninstall  # unstage only; prints bootout command
EOF
    ;;
  *) echo "[install-watcher] unknown mode: $MODE" >&2; exit 2 ;;
esac
