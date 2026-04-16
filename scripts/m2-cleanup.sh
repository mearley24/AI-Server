#!/bin/zsh
set -euo pipefail

printf '=== M2 MacBook Pro Deep Cleanup ===\n'
printf 'Finding files not accessed in 90+ days...\n\n'

TOTAL_BEFORE=$(df -h / | tail -1 | awk '{print $4}')
printf 'Free space before: %s\n\n' "$TOTAL_BEFORE"

printf '=== 1. Homebrew Cleanup ===\n'
if command -v brew >/dev/null 2>&1; then
  brew cleanup -s 2>/dev/null || true
  brew autoremove 2>/dev/null || true
  printf '  Homebrew cleaned.\n'
else
  printf '  Homebrew not installed, skipping.\n'
fi

printf '\n=== 2. Old Downloads ===\n'
OLD_DOWNLOADS=$(find ~/Downloads -maxdepth 1 -atime +90 -not -name ".DS_Store" 2>/dev/null || true)
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
  printf '  No old downloads found.\n'
fi

printf '\n=== 3. Old Caches ===\n'
du -sh ~/Library/Caches 2>/dev/null || true
printf 'Large cache folders:\n'
du -sh ~/Library/Caches/* 2>/dev/null | sort -rh | head -10
printf '\nClear all caches older than 90 days? (y/n) '
read -r ans
if [ "$ans" = "y" ]; then
  find ~/Library/Caches -atime +90 -type f -delete 2>/dev/null || true
  printf '  Old caches cleared.\n'
fi

printf '\n=== 4. Xcode/Developer Tools ===\n'
if [ -d ~/Library/Developer ]; then
  du -sh ~/Library/Developer 2>/dev/null || true
  printf 'Xcode derived data:\n'
  du -sh ~/Library/Developer/Xcode/DerivedData 2>/dev/null || printf '  None\n'
  du -sh ~/Library/Developer/CoreSimulator 2>/dev/null || printf '  No simulators\n'
  printf 'Remove DerivedData and old simulators? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    rm -rf ~/Library/Developer/Xcode/DerivedData 2>/dev/null || true
    xcrun simctl delete unavailable 2>/dev/null || true
    printf '  Developer cleanup done.\n'
  fi
else
  printf '  No Developer directory found.\n'
fi

printf '\n=== 5. Docker (if installed) ===\n'
if command -v docker >/dev/null 2>&1; then
  docker system df 2>/dev/null || true
  printf 'Prune everything? (y/n) '
  read -r ans
  if [ "$ans" = "y" ]; then
    docker system prune -a -f --volumes 2>/dev/null || true
    docker builder prune -a -f 2>/dev/null || true
    printf '  Docker cleaned.\n'
  fi
else
  printf '  Docker not installed, skipping.\n'
fi

printf '\n=== 6. Node.js / npm ===\n'
if [ -d ~/.npm ]; then
  du -sh ~/.npm 2>/dev/null || true
  npm cache clean --force 2>/dev/null || true
  printf '  npm cache cleared.\n'
fi

printf '\n=== 7. Python ===\n'
pip3 cache purge 2>/dev/null || pip cache purge 2>/dev/null || true
printf '  pip cache cleared.\n'

printf '\n=== 8. Large Files (500MB+) ===\n'
printf 'Scanning for large files...\n'
find ~ -size +500M -type f \
  -not -path "*/Library/Application Support/*" \
  -not -path "*/Library/Mail/*" \
  -not -path "*/.Trash/*" \
  -not -path "*/AI-Server/.git/*" \
  -not -path "*/.ollama/*" \
  2>/dev/null | while read -r f; do
    du -sh "$f"
  done
printf '(Review and manually delete any you do not need)\n'

printf '\n=== 9. Ollama Models ===\n'
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

printf '\n=== 10. Empty Trash ===\n'
du -sh ~/.Trash 2>/dev/null || printf '  Trash is empty\n'
printf 'Empty Trash? (y/n) '
read -r ans
if [ "$ans" = "y" ]; then
  rm -rf ~/.Trash/* 2>/dev/null || true
  printf '  Trash emptied.\n'
fi

printf '\n=== Summary ===\n'
TOTAL_AFTER=$(df -h / | tail -1 | awk '{print $4}')
printf 'Free space before: %s\n' "$TOTAL_BEFORE"
printf 'Free space after:  %s\n' "$TOTAL_AFTER"
printf '\nCleanup complete.\n'
