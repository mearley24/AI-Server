#!/bin/bash
cd ~/AI-Server || exit 1
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null
git add -A
git diff --quiet --cached || git commit -m "auto: local changes before pull"
git stash --include-untracked 2>/dev/null
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null
git pull --rebase origin main || (git rebase --abort 2>/dev/null && git pull --no-rebase origin main)
git stash pop 2>/dev/null
git checkout -- data/network_watch/dropout_watch_status.json 2>/dev/null
echo "Done. Ready to build."
docker compose restart openclaw mission-control 2>/dev/null && echo "Restarted openclaw + mission-control"

# Money-critical: polymarket-bot needs --build when compose or bot code changes (lesson #16)
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -qE '^docker-compose\.yml|^docker-compose\.yaml|^polymarket-bot/'; then
    echo "docker-compose or polymarket-bot/ changed — rebuilding polymarket-bot..."
    docker compose up -d --build polymarket-bot 2>/dev/null || true
  fi
fi

# Rebuild services when last commit touched their directories (lessons-learned-april4)
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  changed="$(git diff --name-only HEAD~1 HEAD 2>/dev/null | cut -d/ -f1 | sort -u || true)"
  for svc in openclaw mission_control polymarket-bot email-monitor; do
    case "$svc" in
      openclaw) pat="openclaw" ;;
      mission_control) pat="mission_control" ;;
      polymarket-bot) pat="polymarket-bot" ;;
      email-monitor) pat="email-monitor" ;;
    esac
    if echo "$changed" | grep -q "$pat"; then
      echo "Rebuilding $svc (files changed in last commit)..."
      docker compose up -d --build "$svc" 2>/dev/null || true
    fi
  done
fi

