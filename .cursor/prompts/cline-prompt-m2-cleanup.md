# Cline Prompt: M2 MacBook Pro — Deep Cleanup

## Context
The M2 MacBook Pro (M2 Pro, 12-core, 16GB) is being set up as a dedicated Ollama worker. We need to free up as much disk space and RAM as possible so it can focus on inference. Remove anything that hasn't been touched in 3+ months.

## Task: Create the cleanup script
Create `scripts/m2-cleanup.sh` that Matt can run directly on the M2. The script should:

1. **Audit first, delete second** — show what will be removed and sizes before deleting
2. **Be safe** — never delete system files, Ollama, Tailscale, or the AI-Server repo

```
#!/bin/zsh
set -euo pipefail

printf '=== M2 MacBook Pro Deep Cleanup ===\n'
printf 'Finding files not accessed in 90+ days...\n\n'

TOTAL_BEFORE=$(df -h / | tail -1 | awk '{print $4}')
printf 'Free space before: %s\n\n' "$TOTAL_BEFORE"

printf '=== 1. Homebrew Cleanup ===\n'
if command -v brew >/dev/null 2>&1; then
  brew cleanup --dry-run 2>/dev/null | tail -5
  printf 'Run cleanup? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    brew cleanup -s
    brew autoremove
    printf 'Homebrew cleaned.\n'
  fi
else
  printf 'Homebrew not installed, skipping.\n'
fi

printf '\n=== 2. Old Downloads ===\n'
OLD_DOWNLOADS=$(find ~/Downloads -maxdepth 1 -atime +90 -not -name ".DS_Store" 2>/dev/null)
if [ -n "$OLD_DOWNLOADS" ]; then
  echo "$OLD_DOWNLOADS" | while read -r f; do
    du -sh "$f" 2>/dev/null
  done
  printf '\nTotal: '
  echo "$OLD_DOWNLOADS" | xargs du -shc 2>/dev/null | tail -1
  printf 'Move to Trash? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    echo "$OLD_DOWNLOADS" | while read -r f; do
      mv "$f" ~/.Trash/ 2>/dev/null && printf '  Trashed: %s\n' "$f"
    done
  fi
else
  printf 'No old downloads found.\n'
fi

printf '\n=== 3. Old Caches ===\n'
du -sh ~/Library/Caches 2>/dev/null
printf 'Large cache folders:\n'
du -sh ~/Library/Caches/* 2>/dev/null | sort -rh | head -10
printf '\nClear all caches older than 90 days? (y/n) '
read -r ans
if [ "$ans" = "y" ]; then
  find ~/Library/Caches -atime +90 -type f -delete 2>/dev/null
  printf 'Old caches cleared.\n'
fi

printf '\n=== 4. Xcode/Developer Tools ===\n'
if [ -d ~/Library/Developer ]; then
  du -sh ~/Library/Developer 2>/dev/null
  printf 'Xcode derived data:\n'
  du -sh ~/Library/Developer/Xcode/DerivedData 2>/dev/null || printf '  None\n'
  du -sh ~/Library/Developer/CoreSimulator 2>/dev/null || printf '  No simulators\n'
  printf 'Remove DerivedData and old simulators? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    rm -rf ~/Library/Developer/Xcode/DerivedData 2>/dev/null
    xcrun simctl delete unavailable 2>/dev/null || true
    printf 'Developer cleanup done.\n'
  fi
else
  printf 'No Developer directory found.\n'
fi

printf '\n=== 5. Docker (if installed) ===\n'
if command -v docker >/dev/null 2>&1; then
  docker system df 2>/dev/null
  printf 'Prune everything? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    docker system prune -a -f --volumes
    docker builder prune -a -f
    printf 'Docker cleaned.\n'
  fi
else
  printf 'Docker not installed, skipping.\n'
fi

printf '\n=== 6. Node.js / npm ===\n'
if [ -d ~/.npm ]; then
  du -sh ~/.npm 2>/dev/null
  printf 'Clear npm cache? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    npm cache clean --force 2>/dev/null
    printf 'npm cache cleared.\n'
  fi
fi
if [ -d ~/.nvm ]; then
  du -sh ~/.nvm 2>/dev/null
  printf 'Consider removing old Node versions from ~/.nvm/versions/\n'
fi

printf '\n=== 7. Python ===\n'
if [ -d ~/.local/lib/python* ] || [ -d ~/Library/Caches/pip ]; then
  du -sh ~/Library/Caches/pip 2>/dev/null || true
  printf 'Clear pip cache? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    pip3 cache purge 2>/dev/null || pip cache purge 2>/dev/null || true
    printf 'pip cache cleared.\n'
  fi
fi

printf '\n=== 8. Large Files (500MB+) ===\n'
printf 'Scanning for large files not in system directories...\n'
find ~ -size +500M -type f \
  -not -path "*/Library/Application Support/*" \
  -not -path "*/Library/Mail/*" \
  -not -path "*/.Trash/*" \
  -not -path "*/AI-Server/*" \
  -not -path "*/.ollama/*" \
  2>/dev/null | while read -r f; do
    du -sh "$f"
  done
printf '(Review and manually delete any you do not need)\n'

printf '\n=== 9. Old Applications ===\n'
printf 'Apps not opened in 90+ days:\n'
find /Applications -maxdepth 1 -name "*.app" -type d 2>/dev/null | while read -r app; do
  last_used=$(mdls -name kMDItemLastUsedDate "$app" 2>/dev/null | awk -F= '{print $2}' | xargs)
  if [ "$last_used" = "(null)" ] || [ -z "$last_used" ]; then
    printf '  NEVER USED: %s\n' "$(basename "$app")"
  else
    days_ago=$(( ($(date +%s) - $(date -jf "%Y-%m-%d %H:%M:%S %z" "$last_used" +%s 2>/dev/null || echo "0")) / 86400 ))
    if [ "$days_ago" -gt 90 ] 2>/dev/null; then
      printf '  %d days ago: %s\n' "$days_ago" "$(basename "$app")"
    fi
  fi
done
printf '(Review and manually remove apps you do not need via Finder > Move to Trash)\n'

printf '\n=== 10. Empty Trash ===\n'
du -sh ~/.Trash 2>/dev/null || printf '  Trash is empty\n'
printf 'Empty Trash? (y/n) '
read -r ans
if [ "$ans" = "y" ]; then
  rm -rf ~/.Trash/* 2>/dev/null
  printf 'Trash emptied.\n'
fi

printf '\n=== 11. Ollama Models ===\n'
printf 'Current Ollama models:\n'
ollama list 2>/dev/null || printf '  Ollama not running\n'
printf '\nKeep only llama3.2:3b and llama3.1:8b. Remove benchmark models:\n'
for model in gemma3:12b gemma3:4b phi4-mini:3.8b qwen3:4b llama3.2:1b; do
  if ollama list 2>/dev/null | grep -q "$model"; then
    printf '  Remove %s? (y/n) ' "$model"
    read -r ans
    if [ "$ans" = "y" ]; then
      ollama rm "$model"
      printf '  Removed %s\n' "$model"
    fi
  fi
done

printf '\n=== Summary ===\n'
TOTAL_AFTER=$(df -h / | tail -1 | awk '{print $4}')
printf 'Free space before: %s\n' "$TOTAL_BEFORE"
printf 'Free space after:  %s\n' "$TOTAL_AFTER"

printf '\n=== RAM Check ===\n'
printf 'Current memory pressure:\n'
memory_pressure 2>/dev/null | head -5 || vm_stat | head -10

printf '\nTo free RAM, quit unused apps and run:\n'
printf '  sudo purge\n'
printf '\nCleanup complete.\n'
```

Make it executable: `chmod +x scripts/m2-cleanup.sh`

## Important Notes
- The script is interactive — it asks before deleting anything
- It does NOT touch: AI-Server repo, Ollama install, Tailscale, system files
- It DOES target: old downloads, caches, Xcode artifacts, Docker leftovers, npm/pip caches, unused apps, benchmark Ollama models
- Matt runs this directly on the M2: `cd ~/AI-Server && bash scripts/m2-cleanup.sh`

## Commit
```
git add scripts/m2-cleanup.sh
git commit -m "feat: add M2 cleanup script — free disk and RAM for Ollama worker"
```
Push to main.
