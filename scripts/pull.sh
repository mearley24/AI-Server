#!/bin/zsh
# scripts/pull.sh — THE ONLY WAY TO GIT PULL on Bob. Never bare git pull.
# Usage: bash scripts/pull.sh [--verify]
set -euo pipefail
cd ~/AI-Server || exit 1

# ── 1. Warn about local Python changes (before stash) ────────────────────────
local_py_changes=$(git diff --name-only -- '*.py' 2>/dev/null || true)
if [ -n "$local_py_changes" ]; then
  echo "WARNING: Local Python changes detected (will be stashed):"
  echo "$local_py_changes" | sed 's/^/  /'
fi

# ── 2. Checkout data files that always conflict ───────────────────────────────
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null || true

# ── 3. Auto-commit any other local changes ────────────────────────────────────
git add -A
git diff --quiet --cached || git commit -m "auto: local changes before pull"

# ── 4. Stash, pull --rebase, pop ─────────────────────────────────────────────
git stash --include-untracked 2>/dev/null || true
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null || true
git pull --rebase origin main || (git rebase --abort 2>/dev/null || true; git pull --no-rebase origin main)
git stash pop 2>/dev/null || true
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null || true

# ── 5. Scan for merge conflict markers, reset to origin/main if found ────────
echo "Checking for merge conflict markers..."
CONFLICT_FILES=$(grep -rl "<<<<<<<\|=======\|>>>>>>>" --include="*.py" --include="*.js" --include="*.yml" --include="*.yaml" . 2>/dev/null | grep -v node_modules | grep -v .git || true)
if [ -n "$CONFLICT_FILES" ]; then
  echo "CONFLICT MARKERS FOUND in:"
  echo "$CONFLICT_FILES"
  echo "Auto-fixing by resetting to origin/main..."
  for f in $CONFLICT_FILES; do
    git checkout origin/main -- "$f" 2>/dev/null && echo "  Fixed: $f" || true
  done
fi

# ── 6. Python syntax validation ───────────────────────────────────────────────
echo "Validating Python syntax..."
BROKEN=""
for dir in openclaw email-monitor notification-hub integrations cortex client-portal; do
  if [ -d "$dir" ]; then
    for pyfile in $(find "$dir" -name "*.py" -type f 2>/dev/null); do
      if ! /opt/homebrew/bin/python3 -m py_compile "$pyfile" 2>/dev/null; then
        echo "  SYNTAX ERROR: $pyfile"
        BROKEN="$BROKEN $pyfile"
      fi
    done
  fi
done
if [ -n "$BROKEN" ]; then
  echo "Broken files detected — resetting to origin/main:"
  for f in $BROKEN; do
    git checkout origin/main -- "$f" 2>/dev/null && echo "  Reset: $f" || true
  done
  echo "WARNING: syntax errors were found and reset. Investigate before deploying."
fi

# ── 7. Restart bind-mounted services (no rebuild needed for Python edits) ────
docker compose restart openclaw cortex 2>/dev/null && echo "Restarted openclaw + cortex" || true

# ── 8. Auto-rebuild services when their directory changed ────────────────────
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  changed="$(git diff --name-only HEAD~1 HEAD 2>/dev/null | cut -d/ -f1 | sort -u || true)"
  for svc in polymarket-bot email-monitor notification-hub cortex; do
    case "$svc" in
      polymarket-bot) pat="polymarket-bot" ;;
      email-monitor)  pat="email-monitor" ;;
      notification-hub) pat="notification-hub" ;;
      cortex)         pat="cortex" ;;
    esac
    if echo "$changed" | grep -q "^$pat$"; then
      echo "Rebuilding $svc (files changed in last commit)..."
      docker compose up -d --build "$svc" 2>/dev/null || true
    fi
  done
fi

# ── 9. Auto compose up on docker-compose.yml or Dockerfile changes ───────────
compose_changed=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -E "docker-compose\.yml|Dockerfile" || true)
if [ -n "$compose_changed" ]; then
  echo "Compose/Dockerfile changed — running full docker compose up..."
  docker compose up -d --build 2>/dev/null || true
fi

# ── 10. Log what changed ──────────────────────────────────────────────────────
echo ""
echo "Changes pulled:"
git log --oneline HEAD~3..HEAD 2>/dev/null || echo "  (no new commits)"
echo ""
echo "Files changed in last commit:"
git diff --stat HEAD~1 HEAD 2>/dev/null || echo "  (unable to diff)"
echo ""
echo "Pull complete."
mkdir -p data/transcripts data/bookmarks

# ── 11. --verify flag: run smoke test ────────────────────────────────────────
if [ "${1:-}" = "--verify" ]; then
  echo ""
  echo "Running smoke test..."
  if [ -x "scripts/smoke-test.sh" ]; then
    bash scripts/smoke-test.sh
  else
    echo "smoke-test.sh not found or not executable"
  fi
fi
