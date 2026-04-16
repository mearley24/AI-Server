#!/bin/zsh
set -euo pipefail

printf '=== Bob Emergency Disk Cleanup ===\n\n'
printf 'Free space before: '
df -h / | tail -1 | awk '{print $4}'

printf '\n=== 1. Remove benchmark Ollama models ===\n'
for model in gemma3:12b gemma3:4b phi4-mini:3.8b qwen3:4b llama3.2:1b; do
  if ollama list 2>/dev/null | grep -q "$model"; then
    printf '  Removing %s...\n' "$model"
    ollama rm "$model" 2>/dev/null || true
  fi
done
printf '  Keeping: llama3.2:3b (production)\n'
ollama list 2>/dev/null || true

printf '\n=== 2. Docker cleanup ===\n'
docker system df 2>/dev/null || true
printf '  Pruning unused images, build cache, stopped containers...\n'
docker system prune -a -f 2>/dev/null || true
docker builder prune -a -f 2>/dev/null || true
printf '  Docker cleaned.\n'

printf '\n=== 3. Old logs ===\n'
find ~/AI-Server/logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
find ~/AI-Server -name "*.log" -size +50M -delete 2>/dev/null || true
find /tmp -name "*.log" -mtime +3 -delete 2>/dev/null || true
truncate -s 0 /tmp/imessage-bridge.log 2>/dev/null || true
printf '  Old logs cleaned.\n'

printf '\n=== 4. Large files check ===\n'
find ~/AI-Server -size +100M -type f 2>/dev/null | head -20
find ~ -size +500M -type f -not -path "*/Library/*" -not -path "*/.Trash/*" -not -path "*/.ollama/*" 2>/dev/null | head -20

printf '\n=== 5. Homebrew cleanup ===\n'
if command -v brew >/dev/null 2>&1; then
  brew cleanup -s 2>/dev/null || true
  brew autoremove 2>/dev/null || true
  printf '  Homebrew cleaned.\n'
fi

printf '\n=== 6. pip cache ===\n'
pip3 cache purge 2>/dev/null || true
printf '  pip cache cleared.\n'

printf '\n=== 7. npm cache ===\n'
npm cache clean --force 2>/dev/null || true
printf '  npm cache cleared.\n'

printf '\n=== Summary ===\n'
printf 'Free space after: '
df -h / | tail -1 | awk '{print $4}'
printf '\nDone.\n'
