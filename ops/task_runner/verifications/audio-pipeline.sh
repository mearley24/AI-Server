#!/bin/bash
# Verification dump for the audio intake pipeline.
# Exploratory — one failure should not short-circuit the rest of the dump.
set -u

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
whoami
echo

echo "=== 1. audio_intake tree counts ==="
for sub in incoming processing processed failed; do
  dir="/Users/bob/AI-Server/data/audio_intake/$sub"
  if [ -d "$dir" ]; then
    n=$(ls -1 "$dir" 2>/dev/null | wc -l | tr -d ' ')
    echo "$sub: $n files"
  else
    echo "$sub: MISSING"
  fi
done
echo

echo "=== 2. newest incoming files ==="
ls -laht /Users/bob/AI-Server/data/audio_intake/incoming/ 2>/dev/null | head -15 || true
echo

echo "=== 3. worker log tail ==="
tail -40 /Users/bob/AI-Server/data/audio_intake/worker.log 2>/dev/null || echo "no worker.log"
echo

echo "=== 4. launchd audio-intake status ==="
launchctl list | grep -i audio-intake || echo "no audio-intake agent loaded"
echo

echo "=== 5. queue.db row counts ==="
DB="/Users/bob/AI-Server/data/audio_intake/queue.db"
if [ -f "$DB" ]; then
  sqlite3 "$DB" ".tables" 2>/dev/null || true
  for t in recordings meetings transcripts jobs; do
    if sqlite3 "$DB" "SELECT 1 FROM $t LIMIT 1;" >/dev/null 2>&1; then
      n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM $t;" 2>/dev/null)
      echo "$t: $n rows"
    fi
  done
else
  echo "queue.db missing"
fi
echo

echo "=== 6. disk pressure ==="
df -h /Users/bob/AI-Server/data/audio_intake 2>/dev/null | tail -2
echo

echo "=== 7. task-runner heartbeat ==="
cat /Users/bob/AI-Server/data/task_runner/heartbeat.txt 2>/dev/null || echo "no heartbeat yet"
