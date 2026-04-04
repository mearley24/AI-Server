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
