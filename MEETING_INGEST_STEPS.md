# Meeting Audio — One-Paste Seed Run (Bert → Bob)

This document hands off a **single block** for Matt to paste on **Bert** (the M2 MacBook Pro) that rsyncs the ~9 GB of July 2024 WAV recordings to Bob, triggers the meeting audio worker, and polls the queue until every file is in a terminal state (`done` or `failed`).

No multi-step instructions. No heredocs. No inline `#` comments on command lines. Bounded commands only — zsh-safe.

---

## Prereqs (already in place, do not re-verify manually)

| Item | Expected state |
|---|---|
| Bob tailnet FQDN | `bobs-mac-mini.tailbcf3fe.ts.net` (IP 100.89.1.51) |
| Bert SSH → Bob | pubkey already placed for user `bob` (from the Phase-4 BlueBubbles install) |
| Bert audio source dirs | `~/Documents/Audio Recordings/RECORD/` and `~/Documents/Audio Recordings/MEETING/` |
| Bob worker | `/Users/bob/AI-Server/scripts/audio_intake_worker.py` + launchd `com.symphony.audio-intake` (10-minute interval, `RunAtLoad=true`) |
| Bob incoming dir | `/Users/bob/AI-Server/data/audio_intake/incoming/` |
| Bob queue DB | `/Users/bob/AI-Server/data/audio_intake/queue.db` (table `audio_intake_queue` already created) |
| Whisper model | `ggml-large-v3.bin` (2.9 GB) under `~/AI-Server/models/whisper/`, Metal-accelerated |

---

## The paste block (run on Bert as user `Matt`, in Terminal)

Paste this whole block into Bert's Terminal. It:

1. Checks Tailscale + SSH handshake.
2. Ensures the incoming dir exists on Bob.
3. rsyncs both source dirs to Bob's `data/audio_intake/incoming/` — idempotent + resume-safe.
4. Triggers the worker once on Bob (launchd will keep running it every 10 min regardless).
5. Polls the queue every 60s until every row is `done` / `failed` (max 90 minutes).
6. Prints a final per-file report.

If it gets interrupted (laptop lid closed, WiFi drop), just paste it again — rsync picks up where it left off and the worker holds a single-instance lock.

```bash
BOB="bob@bobs-mac-mini.tailbcf3fe.ts.net"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG="/tmp/audio-seed-run-${STAMP}.log"

{
set -euo pipefail

echo "=== 0. Tailscale check (Bert side) ==="
tailscale status | grep -E "bobs-mac-mini|100\.89\.1\.51" || { echo "Bob not in tailnet — abort"; exit 1; }

echo "=== 1. SSH handshake to Bob ==="
ssh -o BatchMode=yes -o ConnectTimeout=5 "$BOB" "echo bob-reachable"

echo "=== 2. Ensure incoming dir exists on Bob ==="
ssh "$BOB" "mkdir -p /Users/bob/AI-Server/data/audio_intake/incoming"

echo "=== 3. rsync both source dirs (idempotent, progress, resume on blips) ==="
rsync -avh --partial --progress --stats \
  "$HOME/Documents/Audio Recordings/RECORD/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"
rsync -avh --partial --progress --stats \
  "$HOME/Documents/Audio Recordings/MEETING/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"

echo "=== 4. Count files landed on Bob ==="
LANDED=$(ssh "$BOB" "ls -1 /Users/bob/AI-Server/data/audio_intake/incoming/ 2>/dev/null | wc -l | tr -d ' '")
echo "files-on-bob: $LANDED"

echo "=== 5. Trigger the worker immediately on Bob ==="
ssh "$BOB" "cd /Users/bob/AI-Server && nohup /usr/bin/python3 scripts/audio_intake_worker.py > /tmp/audio_intake_kick.log 2>&1 & echo kicked pid=\$!"

echo "=== 6. Poll queue until every row is terminal or 90 min passes ==="
DEADLINE=$(($(date +%s) + 5400))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  SUMMARY=$(ssh "$BOB" "sqlite3 /Users/bob/AI-Server/data/audio_intake/queue.db \"SELECT status, COUNT(*) FROM audio_intake_queue GROUP BY status\"" 2>/dev/null || echo "queue-missing")
  echo "[$(date '+%H:%M:%S')] $SUMMARY"
  NONTERMINAL=$(ssh "$BOB" "sqlite3 /Users/bob/AI-Server/data/audio_intake/queue.db \"SELECT COUNT(*) FROM audio_intake_queue WHERE status NOT IN ('done','failed')\"" 2>/dev/null || echo "1")
  if [ "$NONTERMINAL" = "0" ] && [ "$SUMMARY" != "queue-missing" ]; then
    echo "all rows terminal — exiting poll loop"
    break
  fi
  sleep 60
done

echo "=== 7. Final per-file report ==="
ssh "$BOB" "sqlite3 -header -column /Users/bob/AI-Server/data/audio_intake/queue.db \"SELECT id, original_name, status, source_date, substr(error_msg,1,40) AS err FROM audio_intake_queue ORDER BY id\""

echo "=== 8. Transcripts written ==="
ssh "$BOB" "ls -1 /Users/bob/AI-Server/data/transcripts/meetings/ 2>/dev/null | head -30"

echo "=== 9. Cortex meeting_intel sample (first 2KB) ==="
ssh "$BOB" "curl -s http://127.0.0.1:8102/api/meetings/recent | head -c 2000"
echo ""

echo "=== 10. Delete hint (NOT auto-executed — review above first) ==="
echo "    rm -rf ~/Documents/Audio\\ Recordings/RECORD/2024*"
echo "    rm -rf ~/Documents/Audio\\ Recordings/MEETING/2024*"
} 2>&1 | tee "$LOG"

echo ""
echo "=== 11. Push log to Bob's repo for agent review (per ops/AGENT_VERIFICATION_PROTOCOL.md) ==="
REMOTE_PATH="/Users/bob/AI-Server/ops/verification/${STAMP}-audio-seed-run.txt"
ssh "$BOB" "mkdir -p /Users/bob/AI-Server/ops/verification"
scp "$LOG" "${BOB}:${REMOTE_PATH}"
ssh "$BOB" "cd /Users/bob/AI-Server && git -c user.email='earleystream@gmail.com' -c user.name='Perplexity Computer' add ops/verification/${STAMP}-audio-seed-run.txt && git -c user.email='earleystream@gmail.com' -c user.name='Perplexity Computer' commit -m 'ops: audio seed-run log ${STAMP}' && git push origin main 2>&1 | tail -3"
echo ""
echo "DONE. Seed-run log committed. Reply to the agent: 'seed run pushed'."
```

---

## After the run — verify on Bob

From Bob (or via SSH from Bert), after every row shows `done`:

```bash
ls -1 ~/AI-Server/data/transcripts/meetings/ | head
curl -s http://127.0.0.1:8102/api/meetings/recent | python3 -m json.tool | head -80
```

Each meeting will show up as:

- A durable `.md` artifact under `data/transcripts/meetings/<YYYY-MM-DD>__<slug>.md` with Summary / Participants / Clients / Projects / Decisions / Action Items / Dollar Amounts / Topics + the raw transcript.
- A `meeting_intel` memory in Cortex (`brain.db`) — searchable by client name, project, date, or topic through the usual Cortex `/memories` and `/query` endpoints.
- A row in `data/audio_intake/queue.db` (`status='done'`, `cortex_memory_id` populated, `transcript_path` set).
- A **Meetings** tile on the Cortex dashboard (`http://localhost:8102/dashboard`, column 3 between X Intake and Daily Digest).

The launchd job `com.symphony.audio-intake` runs every 10 minutes from then on, so any new audio dropped into `~/AI-Server/data/audio_intake/incoming/` (whether from Bert, Dropbox, AirDrop, or another box) is auto-processed the same way.

---

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| Rows stuck at `transcribing` | whisper-cli OOM on very long recordings | Move the file to `data/audio_intake/failed/`, reset its row to `status='pending'`, and re-run the worker manually with `/usr/bin/python3 ~/AI-Server/scripts/audio_intake_worker.py` — the worker has a 2-hour subprocess timeout per file. |
| All rows `failed` with cortex error | Cortex down | `docker compose up -d cortex`, then clear and re-enqueue failed rows. |
| `summary` empty but status `done` | LLM unreachable (Ollama + no OpenAI key) | Set `OPENAI_API_KEY` in `.env` (or bring Ollama up), delete the `done` rows, move originals from `processed/` back to `incoming/`, and let the launchd job pick them up on the next tick. |
| Worker never runs | launchd not loaded | `launchctl load ~/Library/LaunchAgents/com.symphony.audio-intake.plist` then verify with `launchctl list \| grep com.symphony.audio-intake`. |
