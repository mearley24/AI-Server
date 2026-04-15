#!/bin/zsh
# scripts/restart-all-launchd.sh — Reload every Symphony launchd service from setup/launchd/
# Usage: zsh scripts/restart-all-launchd.sh
# Note: Run as the bob user, not root. Does NOT touch Docker services.
set -euo pipefail

REPO_LAUNCHD="$(cd "$(dirname "$0")/.." && pwd)/setup/launchd"
AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "========================================"
echo "Symphony Launchd Restart — $(date)"
echo "========================================"
echo ""

# ── Step 1: Unload currently-loaded symphony services ─────────────────────
echo "Step 1: Unloading..."
unloaded=0
for plist in "$REPO_LAUNCHD"/*.plist; do
  label=$(basename "$plist" .plist)
  if launchctl list "$label" >/dev/null 2>&1; then
    launchctl unload "$AGENTS_DIR/$label.plist" 2>/dev/null && unloaded=$((unloaded+1)) || true
  fi
done
echo "  Unloaded $unloaded service(s)"

echo ""

# ── Step 2: Load (or reload) all services ─────────────────────────────────
echo "Step 2: Loading..."
loaded=0
skipped=0
for plist in "$REPO_LAUNCHD"/*.plist; do
  label=$(basename "$plist" .plist)
  target="$AGENTS_DIR/$label.plist"
  if [ ! -f "$target" ]; then
    echo "  SKIP (not in LaunchAgents — copy manually): $label"
    skipped=$((skipped+1))
    continue
  fi
  if launchctl load "$target" 2>/dev/null; then
    loaded=$((loaded+1))
  else
    echo "  LOAD FAILED: $label"
    skipped=$((skipped+1))
  fi
done
echo "  Loaded: $loaded  Skipped/Failed: $skipped"

echo ""

# ── Step 3: Status summary ────────────────────────────────────────────────
echo "========================================"
echo "Service Status"
echo "========================================"
printf "%-55s  %s\n" "SERVICE" "STATUS"
printf "%-55s  %s\n" "-------" "------"
for plist in "$REPO_LAUNCHD"/*.plist; do
  label=$(basename "$plist" .plist)
  raw=$(launchctl list "$label" 2>/dev/null || echo "NOT_LOADED")
  if [ "$raw" = "NOT_LOADED" ]; then
    status="not loaded"
  else
    pid=$(echo "$raw" | grep '"PID"' | awk '{print $3}' | tr -d ',')
    exit_code=$(echo "$raw" | grep '"LastExitStatus"' | awk '{print $3}' | tr -d ',')
    if [ -n "$pid" ]; then
      status="RUNNING (pid=$pid)"
    elif [ "$exit_code" = "0" ]; then
      status="scheduled/idle (last exit=0)"
    else
      status="CRASHED or stopped (exit=${exit_code:-?})"
    fi
  fi
  printf "%-55s  %s\n" "$label" "$status"
done

echo ""
echo "Done. $(date)"
echo "NOTE: Do NOT run this without reviewing — it restarts ALL launchd services."
