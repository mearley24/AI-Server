#!/bin/bash
# Analyze audio_intake_worker throughput: look at the full worker.log, count
# transcription starts, completions, average durations, and identify any
# dead-time gaps.
set -u

LOG="/Users/bob/AI-Server/data/audio_intake/worker.log"
LAUNCHD_OUT="/Users/bob/AI-Server/data/audio_intake/launchd.out.log"
LAUNCHD_ERR="/Users/bob/AI-Server/data/audio_intake/launchd.err.log"

echo "=== 0. banner ==="
date '+%Y-%m-%d %H:%M:%S %z'
hostname
echo

echo "=== 1. worker.log size and line count ==="
wc -l "$LOG" 2>/dev/null || echo "worker.log missing"
ls -lah "$LOG" 2>/dev/null | awk '{print "  size:", $5, "mtime:", $6, $7, $8}'
echo

echo "=== 2. full worker.log (only INFO/WARNING/ERROR lines — skip debug) ==="
if [ -f "$LOG" ]; then
  grep -E "\[(INFO|WARNING|ERROR)\]" "$LOG" | tail -80
else
  echo "missing"
fi
echo

echo "=== 3. transcribing starts + finishes paired ==="
# Match "transcribing X" as start, "cortex_posted: id=..." or a subsequent
# "transcribing" line as end-of-previous. Print timestamps.
if [ -f "$LOG" ]; then
  grep -E "transcribing |cortex_posted:|transcribed .* in " "$LOG" | tail -40
fi
echo

echo "=== 4. launchd.out.log tail (did daemon restart, crash, etc.) ==="
if [ -f "$LAUNCHD_OUT" ]; then
  wc -l "$LAUNCHD_OUT"
  tail -30 "$LAUNCHD_OUT"
else
  echo "missing"
fi
echo

echo "=== 5. launchd.err.log tail ==="
if [ -f "$LAUNCHD_ERR" ]; then
  wc -l "$LAUNCHD_ERR"
  tail -30 "$LAUNCHD_ERR"
else
  echo "missing"
fi
echo

echo "=== 6. queue.db rows by status ==="
DB="/Users/bob/AI-Server/data/audio_intake/queue.db"
if [ -f "$DB" ]; then
  # Look at the recordings table first (likely the work table)
  echo "--- .tables ---"
  sqlite3 "$DB" ".tables"
  echo "--- recordings schema ---"
  sqlite3 "$DB" ".schema recordings" 2>/dev/null | head -20
  echo "--- recordings status counts ---"
  sqlite3 "$DB" "SELECT status, COUNT(*) FROM recordings GROUP BY status;" 2>/dev/null
  echo "--- newest 5 recordings ---"
  sqlite3 -header -column "$DB" "SELECT id, substr(original_name, 1, 30) name, status, substr(created_at,1,19) created, substr(updated_at,1,19) updated FROM recordings ORDER BY id DESC LIMIT 5;" 2>/dev/null
  echo "--- oldest 5 'stuck' rows (not processed) ---"
  sqlite3 -header -column "$DB" "SELECT id, substr(original_name, 1, 30) name, status, substr(updated_at,1,19) updated FROM recordings WHERE status != 'processed' ORDER BY updated_at LIMIT 5;" 2>/dev/null
else
  echo "missing"
fi
echo

echo "=== 7. processing dir contents (anything stuck mid-transcode?) ==="
ls -la /Users/bob/AI-Server/data/audio_intake/processing/ 2>/dev/null
echo

echo "=== 8. whisper process check ==="
ps auxww | grep -E "whisper|audio_intake_worker" | grep -v grep | head -10
echo

echo "=== 9. disk & cpu pressure snapshot ==="
df -h /Users/bob/AI-Server/data/audio_intake 2>/dev/null | tail -2
echo
# 5s top sample — CPU snapshot
echo "--- top 1-iteration (5 processes) ---"
top -l 1 -n 5 -o cpu 2>/dev/null | tail -10 || true
