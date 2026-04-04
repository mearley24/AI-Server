#!/bin/bash
cd ~/AI-Server || exit 1
git add -A
git diff --quiet --cached || git commit -m "auto: local changes before pull"
git stash --include-untracked
git pull --rebase origin main
git stash pop 2>/dev/null
echo "Done. Ready to build."
