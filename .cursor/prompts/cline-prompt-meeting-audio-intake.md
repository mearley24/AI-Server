# Cline Autorun — Meeting Audio Transcription → Cortex Ingestion (Bob)

> **Cline:** read this file top to bottom. Operate in **Act mode only** (no planning mode — Matt has never used it). Restate the goal in one line, then execute without further prompting unless a Guardrail (§6) forces a stop. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in §8.
>
> `AUTO_APPROVE = true`. Read `.clinerules`, `CLAUDE.md`, and `STATUS_REPORT.md` first — do not explore from scratch.

---

## 1. Role & Operating Mode

You are Cline, autonomous coding agent on **Bob** (`/Users/bob/AI-Server`, Mac Mini M4). You have terminal + Docker + git + Homebrew access. Verify with `read_file` / `search_files` / `ls` before editing. Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`). Never invent code paths — confirm they exist first. Preserve existing `transcript_analyst.py` behavior — we're **adding** an audio pipeline, not replacing the video pipeline.

## 2. Objective

Build a persistent **meeting audio ingestion pipeline** that runs on Bob. It:

1. Accepts `.wav`/`.m4a`/`.mp3`/`.flac` files dropped into `~/AI-Server/data/audio_intake/incoming/`.
2. Transcribes each with `whisper.cpp` (large-v3 model, Metal-accelerated on the M4).
3. Analyzes each transcript with the existing `transcript_analyst.py` (summary, participants, decisions, action items, projects, clients, dollar amounts).
4. Writes durable artifacts to `~/AI-Server/data/transcripts/meetings/<source_date>__<slug>.md`.
5. Ingests structured output into Cortex as `meeting_intel` memories (searchable by client name, project, date, topic).
6. Moves processed originals to `~/AI-Server/data/audio_intake/processed/` and logs per-file status to a SQLite queue at `~/AI-Server/data/audio_intake/queue.db`.
7. Sends an iMessage summary to Matt when the batch completes (N processed, M failed, top clients/projects mentioned).
8. Registers a launchd job so future drops auto-process every 10 minutes without manual intervention.

This handles Matt's backlog of **17 meeting WAV files from July 2024** currently sitting on Bert (the M2 MacBook Pro) at `~/Documents/Audio Recordings/RECORD/` and `~/Documents/Audio Recordings/MEETING/` — totaling ~9 GB. After transcription + ingestion, originals will be safe to delete from Bert.

## 3. Environment

- **Host:** Bob (Mac Mini M4), repo at `/Users/bob/AI-Server`
- **Branch:** `main`
- **Key files to read first:**
  - `.clinerules`
  - `CLAUDE.md`
  - `STATUS_REPORT.md` — read the `## Reference: Transcript AI Analysis Pipeline` and `## Reference: Transcript Integration Verification` sections for prior art
  - `integrations/x_intake/transcript_analyst.py` — reuse this for audio transcripts too
  - `integrations/x_intake/queue_db.py` — model the new `audio_intake_queue` after this
  - `cortex/dashboard.py` — add a new endpoint `GET /api/meetings/recent`
  - `cortex/static/index.html` — add a "Meetings" mini-tile to the existing dashboard if there's a clean spot (do not refactor the layout)
  - `docker-compose.yml` — DO NOT add a new container; this runs as a host-side launchd job on Bob (same pattern as `scripts/imessage-server.py`)
- **Services touched:** Cortex (`POST http://cortex:8102/remember` — or `http://127.0.0.1:8102/remember` since we're on the host). Do NOT touch `markup-tool` (8088), `client-portal`, `polymarket-bot`, or `email-monitor`.

## 4. Step Plan

### Phase A — Install whisper.cpp

```bash
cd /Users/bob/AI-Server

# A1. Install whisper.cpp via Homebrew (Metal-accelerated on M4)
brew install whisper-cpp 2>&1 | tail -20

# A2. Pull the large-v3 model (~3 GB). If disk is tight (<10 GB free), fall back to medium (~1.5 GB).
mkdir -p ~/AI-Server/models/whisper
FREE_GB=$(df -g / | awk 'NR==2 {print $4}')
if [ "$FREE_GB" -lt 10 ]; then
  MODEL=medium
  MODEL_FILE=ggml-medium.bin
else
  MODEL=large-v3
  MODEL_FILE=ggml-large-v3.bin
fi
echo "Using model: $MODEL"

# whisper-cpp formula sometimes ships with a download helper. Otherwise use curl.
if [ ! -f ~/AI-Server/models/whisper/$MODEL_FILE ]; then
  curl -L --fail -o ~/AI-Server/models/whisper/$MODEL_FILE \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_FILE
fi
ls -lh ~/AI-Server/models/whisper/
```

Commit: `chore(bob): install whisper.cpp and pull $MODEL model`

### Phase B — Directory + queue schema

```bash
mkdir -p ~/AI-Server/data/audio_intake/{incoming,processing,processed,failed}
mkdir -p ~/AI-Server/data/transcripts/meetings

# Create the queue DB schema
sqlite3 ~/AI-Server/data/audio_intake/queue.db <<'SQL'
CREATE TABLE IF NOT EXISTS audio_intake_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_path TEXT NOT NULL,
  original_name TEXT NOT NULL,
  source_date TEXT,                -- YYYY-MM-DD parsed from filename or file mtime
  size_bytes INTEGER,
  duration_sec REAL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending, transcribing, analyzing, done, failed
  transcript_path TEXT,
  summary TEXT,
  participants TEXT,               -- JSON array
  projects TEXT,                   -- JSON array
  clients TEXT,                    -- JSON array
  action_items TEXT,               -- JSON array
  dollar_amounts TEXT,             -- JSON array
  cortex_memory_id TEXT,
  error_msg TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON audio_intake_queue(status);
CREATE INDEX IF NOT EXISTS idx_date ON audio_intake_queue(source_date);
SQL
```

### Phase C — The worker script

Create `scripts/audio_intake_worker.py`:

```python
#!/usr/bin/env python3
"""
Audio Intake Worker — transcribes meeting audio with whisper.cpp, analyzes with
transcript_analyst, and ingests structured output into Cortex.

Runs on Bob as a host-side launchd job every 10 minutes. Safe to re-run; uses
file locking to prevent double-processing.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- Config ---
ROOT = Path(os.environ.get("AI_SERVER_ROOT", "/Users/bob/AI-Server"))
INCOMING = ROOT / "data/audio_intake/incoming"
PROCESSING = ROOT / "data/audio_intake/processing"
PROCESSED = ROOT / "data/audio_intake/processed"
FAILED = ROOT / "data/audio_intake/failed"
TRANSCRIPTS = ROOT / "data/transcripts/meetings"
QUEUE_DB = ROOT / "data/audio_intake/queue.db"
MODELS_DIR = ROOT / "models/whisper"
LOCK_FILE = ROOT / "data/audio_intake/.worker.lock"
CORTEX_URL = os.environ.get("CORTEX_URL", "http://127.0.0.1:8102")

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "data/audio_intake/worker.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("audio_intake")


def acquire_lock() -> bool:
    """Single-instance lock so overlapping launchd runs don't double-process."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Stale lock?
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            return False  # still running
        except (ValueError, ProcessLookupError):
            LOCK_FILE.unlink()
            return acquire_lock()


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def pick_model() -> Path:
    for name in ("ggml-large-v3.bin", "ggml-medium.bin", "ggml-small.bin"):
        p = MODELS_DIR / name
        if p.exists():
            return p
    raise RuntimeError(f"No whisper model found in {MODELS_DIR}")


def parse_date_from_name(name: str) -> str | None:
    # Handles 20240712, 2024-07-12, 07-12-2024, etc.
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def slug(text: str, max_len: int = 40) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return t[:max_len] or "meeting"


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def enqueue(path: Path) -> int:
    source_date = parse_date_from_name(path.name)
    if not source_date:
        mt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        source_date = mt.strftime("%Y-%m-%d")
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO audio_intake_queue
               (source_path, original_name, source_date, size_bytes, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (str(path), path.name, source_date, path.stat().st_size),
        )
        return cur.lastrowid


def mark(row_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE audio_intake_queue SET {sets} WHERE id = ?",
                     (*fields.values(), row_id))


def transcribe(audio_path: Path, out_dir: Path) -> Path:
    """Run whisper.cpp, return path to the .txt output."""
    model = pick_model()
    out_prefix = out_dir / audio_path.stem
    cmd = [
        "whisper-cli",
        "-m", str(model),
        "-f", str(audio_path),
        "-otxt",
        "-of", str(out_prefix),
        "-l", "en",
        "-t", str(os.cpu_count() or 8),
        "-pp",  # print-progress
    ]
    log.info("transcribing %s with %s", audio_path.name, model.name)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if res.returncode != 0:
        raise RuntimeError(f"whisper failed: {res.stderr[-1000:]}")
    txt = out_prefix.with_suffix(".txt")
    if not txt.exists():
        raise RuntimeError(f"whisper produced no output at {txt}")
    return txt


def analyze_with_llm(transcript_text: str) -> dict:
    """Call the existing transcript_analyst module (sync wrapper)."""
    # Import lazily to let the worker start even if the module has issues
    sys.path.insert(0, str(ROOT))
    from integrations.x_intake.transcript_analyst import analyze_transcript

    # transcript_analyst.analyze_transcript returns a dict with keys:
    # summary, flags, quotes, strategies, participants, action_items, etc.
    # If its signature differs, adapt here and log the actual signature.
    try:
        return analyze_transcript(transcript_text, source="meeting_audio")
    except TypeError:
        return analyze_transcript(transcript_text)


def post_to_cortex(payload: dict) -> str | None:
    try:
        r = requests.post(
            f"{CORTEX_URL}/remember",
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("id")
    except Exception as e:
        log.error("cortex POST failed: %s", e)
        return None


def write_markdown(row: sqlite3.Row, transcript_text: str, analysis: dict) -> Path:
    date = row["source_date"]
    topic = (analysis.get("summary") or row["original_name"])[:60]
    fname = f"{date}__{slug(topic)}.md"
    path = TRANSCRIPTS / fname
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Meeting — {date}",
        "",
        f"**Source file:** `{row['original_name']}`",
        f"**Ingested:** {datetime.now(tz=timezone.utc).isoformat()}",
        "",
        "## Summary",
        analysis.get("summary", "(no summary)"),
        "",
    ]
    for key in ("participants", "clients", "projects", "action_items", "dollar_amounts"):
        val = analysis.get(key) or []
        if val:
            lines.append(f"## {key.replace('_', ' ').title()}")
            for item in val:
                lines.append(f"- {item}")
            lines.append("")
    lines.extend(["## Transcript", "", transcript_text])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def process_one(row: sqlite3.Row) -> None:
    src = Path(row["source_path"])
    if not src.exists():
        mark(row["id"], status="failed", error_msg=f"source missing: {src}")
        return
    proc_path = PROCESSING / src.name
    shutil.move(str(src), str(proc_path))
    mark(row["id"], status="transcribing", source_path=str(proc_path))

    try:
        txt_path = transcribe(proc_path, PROCESSING)
        transcript_text = txt_path.read_text(encoding="utf-8", errors="replace")

        mark(row["id"], status="analyzing")
        analysis = analyze_with_llm(transcript_text)

        row = db().execute(
            "SELECT * FROM audio_intake_queue WHERE id = ?", (row["id"],)
        ).fetchone()
        md_path = write_markdown(row, transcript_text, analysis)

        cortex_payload = {
            "kind": "meeting_intel",
            "source": "audio_intake",
            "date": row["source_date"],
            "summary": analysis.get("summary"),
            "participants": analysis.get("participants", []),
            "clients": analysis.get("clients", []),
            "projects": analysis.get("projects", []),
            "action_items": analysis.get("action_items", []),
            "dollar_amounts": analysis.get("dollar_amounts", []),
            "transcript_path": str(md_path),
            "original_file": row["original_name"],
        }
        mem_id = post_to_cortex(cortex_payload)

        mark(
            row["id"],
            status="done",
            transcript_path=str(md_path),
            summary=analysis.get("summary", "")[:2000],
            participants=json.dumps(analysis.get("participants", [])),
            projects=json.dumps(analysis.get("projects", [])),
            clients=json.dumps(analysis.get("clients", [])),
            action_items=json.dumps(analysis.get("action_items", [])),
            dollar_amounts=json.dumps(analysis.get("dollar_amounts", [])),
            cortex_memory_id=mem_id,
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        # Move original to processed; cleanup intermediate .txt
        final = PROCESSED / proc_path.name
        shutil.move(str(proc_path), str(final))
        try:
            txt_path.unlink()
        except FileNotFoundError:
            pass
        log.info("done: %s → %s (cortex %s)", row["original_name"], md_path.name, mem_id)
    except Exception as e:
        log.exception("failed on %s", row["original_name"])
        try:
            shutil.move(str(proc_path), str(FAILED / proc_path.name))
        except Exception:
            pass
        mark(row["id"], status="failed", error_msg=str(e)[:1000])


def send_imessage_summary(counts: dict) -> None:
    """Use the same pattern scripts/imessage-server.py uses to send."""
    script = ROOT / "scripts/send_imessage.sh"
    if not script.exists():
        log.info("no send_imessage.sh; skipping notification")
        return
    body = (
        f"Meeting audio batch done: "
        f"{counts['done']} transcribed, {counts['failed']} failed. "
        f"Top clients: {', '.join(counts['top_clients'][:3]) or '—'}. "
        f"Top projects: {', '.join(counts['top_projects'][:3]) or '—'}."
    )
    subprocess.run([str(script), body], check=False)


def main() -> int:
    if not acquire_lock():
        log.info("another worker instance is running; exiting")
        return 0
    try:
        # 1. Scan incoming for new files
        INCOMING.mkdir(parents=True, exist_ok=True)
        new_files = [
            p for p in INCOMING.iterdir()
            if p.is_file() and p.suffix.lower() in {".wav", ".m4a", ".mp3", ".flac", ".aac"}
        ]
        for p in new_files:
            enqueue(p)

        # 2. Drain pending queue
        rows = list(db().execute(
            "SELECT * FROM audio_intake_queue WHERE status IN ('pending','transcribing','analyzing') "
            "ORDER BY id ASC"
        ).fetchall())
        log.info("pending/stuck rows: %d", len(rows))

        start_done = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='done'"
        ).fetchone()[0]
        start_failed = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='failed'"
        ).fetchone()[0]

        for row in rows:
            process_one(row)

        end_done = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='done'"
        ).fetchone()[0]
        end_failed = db().execute(
            "SELECT COUNT(*) FROM audio_intake_queue WHERE status='failed'"
        ).fetchone()[0]

        delta_done = end_done - start_done
        delta_failed = end_failed - start_failed

        if delta_done or delta_failed:
            # Aggregate top clients/projects this run
            recent = db().execute(
                "SELECT clients, projects FROM audio_intake_queue "
                "WHERE status='done' ORDER BY id DESC LIMIT ?", (delta_done,)
            ).fetchall()
            cc, pp = {}, {}
            for r in recent:
                for c in json.loads(r["clients"] or "[]"):
                    cc[c] = cc.get(c, 0) + 1
                for p in json.loads(r["projects"] or "[]"):
                    pp[p] = pp.get(p, 0) + 1
            top_c = sorted(cc, key=cc.get, reverse=True)
            top_p = sorted(pp, key=pp.get, reverse=True)
            send_imessage_summary({
                "done": delta_done,
                "failed": delta_failed,
                "top_clients": top_c,
                "top_projects": top_p,
            })
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x scripts/audio_intake_worker.py
```

Commit: `feat(audio-intake): whisper.cpp + transcript_analyst + Cortex worker`

### Phase D — launchd job (every 10 minutes)

Write `~/Library/LaunchAgents/com.symphony.audio-intake.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.symphony.audio-intake</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/bob/AI-Server/scripts/audio_intake_worker.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>AI_SERVER_ROOT</key>
    <string>/Users/bob/AI-Server</string>
    <key>CORTEX_URL</key>
    <string>http://127.0.0.1:8102</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key>
  <integer>600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/bob/AI-Server/data/audio_intake/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/bob/AI-Server/data/audio_intake/launchd.err.log</string>
</dict>
</plist>
```

Load it:

```bash
launchctl unload ~/Library/LaunchAgents/com.symphony.audio-intake.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.symphony.audio-intake.plist
launchctl list | grep com.symphony.audio-intake
```

Also commit a copy at `scripts/launchd/com.symphony.audio-intake.plist` for version control.

Commit: `feat(audio-intake): launchd job — every 10 min`

### Phase E — Cortex dashboard surface (optional, but do it)

Add to `cortex/dashboard.py`:

```python
@app.get("/api/meetings/recent")
def meetings_recent(limit: int = 20):
    conn = sqlite3.connect("/data/audio_intake/queue.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, original_name, source_date, status, summary, "
        "participants, clients, projects, action_items, cortex_memory_id "
        "FROM audio_intake_queue ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
```

Mount the queue db read-only into the cortex container (edit `docker-compose.yml` cortex service):

```yaml
cortex:
  volumes:
    - ./data/audio_intake:/data/audio_intake:ro
    # ... keep existing mounts
```

Add a small tile to `cortex/static/index.html` — look for the existing X Intake tile and mirror the pattern for "Meetings" showing count of `status='done'` today + 3 most recent titles. Do not refactor the layout.

Restart cortex:

```bash
docker compose up -d --build cortex
curl -s http://127.0.0.1:8102/api/meetings/recent | python3 -m json.tool | head -40
```

Commit: `feat(cortex): meetings recent endpoint + dashboard tile`

### Phase F — Seed run: pull Matt's 17 WAVs from Bert over Tailscale

This runs on **Bert** (the M2 MacBook Pro, login user `Matt`), not Bob. Cline writes this as `MEETING_INGEST_STEPS.md` in the repo root and mentions it in the final report so Matt can paste **one single block** on Bert and walk away — the block handles rsync, immediate worker trigger, and status polling until every file lands in `done` or `failed` (max 90 min wall-clock). NO multi-step instructions. NO inline `#` comments (zsh-hostile).

**Known environment facts for the seed run (do not re-derive):**
- Bob tailnet FQDN: `bobs-mac-mini.tailbcf3fe.ts.net` (IP 100.89.1.51) — Bert's Tailscale is the sandboxed GUI cask build, so use the FQDN, not short `bobs-mac-mini`, and never `--ssh`.
- SSH from Bert → Bob uses Bob's account `bob` via native macOS Remote Login (pubkey already placed during Phase 4 BB work).
- Audio source dirs on Bert: `~/Documents/Audio Recordings/RECORD/` and `~/Documents/Audio Recordings/MEETING/`.

```markdown
## One-paste seed run (run on Bert as user Matt)

Paste this whole block into Bert's Terminal. It rsyncs the 17 WAVs to Bob, triggers the worker once, then polls every 60s for up to 90 minutes until every row in the queue is `done` or `failed`. Safe to re-run — rsync is idempotent and the worker holds a file lock.

```bash
set -euo pipefail
BOB="bob@bobs-mac-mini.tailbcf3fe.ts.net"
echo "=== 0. Tailscale check (Bert side) ==="
tailscale status | grep -E "bobs-mac-mini|100\.89\.1\.51" || { echo "Bob not in tailnet — abort"; exit 1; }

echo "=== 1. SSH handshake to Bob ==="
ssh -o BatchMode=yes -o ConnectTimeout=5 "$BOB" "echo bob-reachable"

echo "=== 2. Ensure incoming dir exists on Bob ==="
ssh "$BOB" "mkdir -p /Users/bob/AI-Server/data/audio_intake/incoming"

echo "=== 3. rsync both source dirs (idempotent, progress, resume on network blips) ==="
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
ssh "$BOB" "cd /Users/bob/AI-Server && nohup python3 scripts/audio_intake_worker.py > /tmp/audio_intake_kick.log 2>&1 & echo kicked pid=\$!"

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

echo "=== 8. DONE — review output above. If every row is 'done', originals on Bert are safe to delete with: ==="
echo "    rm -rf ~/Documents/Audio\\ Recordings/RECORD/2024*"
echo "    rm -rf ~/Documents/Audio\\ Recordings/MEETING/2024*"
```
```

Commit: `docs: meeting audio ingestion — one-paste Bert seed-run block`

### Phase G — STATUS_REPORT update

Append:

```
## Reference: Meeting Audio Intake Pipeline (<date>)

### What was built
- `scripts/audio_intake_worker.py` — whisper.cpp + transcript_analyst + Cortex POST, with lock file, SQLite queue, structured markdown output
- `data/audio_intake/{incoming,processing,processed,failed}` + `queue.db`
- `data/transcripts/meetings/<date>__<slug>.md` artifact format
- launchd job `com.symphony.audio-intake` running every 10 minutes
- Cortex endpoint `GET /api/meetings/recent` + dashboard tile
- `MEETING_INGEST_STEPS.md` — rsync + trigger instructions for Bert

### How to use
Drop any .wav/.m4a/.mp3/.flac/.aac into `~/AI-Server/data/audio_intake/incoming/`.
Within 10 minutes (or instantly if you run the script manually), the file will
be transcribed, analyzed, written to `data/transcripts/meetings/`, ingested
into Cortex as a `meeting_intel` memory, and moved to `processed/`. Failures
land in `failed/` and are visible in the queue DB.

### Known limits
- Whisper model is currently <large-v3 | medium> (depending on disk at install time).
- Language is forced to English; multilingual support is a future change.
- `transcript_analyst.py` is the same module x-intake uses; any breakage there breaks both pipelines.
```

## 5. Acceptance Criteria (all must pass)

- [ ] `whisper-cli --help 2>&1 | head -3` prints usage on Bob.
- [ ] `ls -lh ~/AI-Server/models/whisper/` shows at least one `ggml-*.bin` file >1 GB.
- [ ] `ls -d ~/AI-Server/data/audio_intake/{incoming,processing,processed,failed}` all exist.
- [ ] `sqlite3 ~/AI-Server/data/audio_intake/queue.db ".schema audio_intake_queue"` returns the expected columns.
- [ ] `launchctl list | grep com.symphony.audio-intake` returns a line (loaded).
- [ ] Running `python3 scripts/audio_intake_worker.py` on an empty `incoming/` exits 0 within 5 seconds with "pending/stuck rows: 0" in the log.
- [ ] `curl -s http://127.0.0.1:8102/api/meetings/recent` returns `[]` (valid empty JSON array).
- [ ] `git log --oneline origin/main..HEAD` shows 4–6 conventional commits, all pushed.
- [ ] `MEETING_INGEST_STEPS.md` exists at the repo root.
- [ ] `STATUS_REPORT.md` has a new `## Reference: Meeting Audio Intake Pipeline` section.

## 6. Guardrails

Stop and surface to the user if any of these are true:

- A change would touch `markup-tool` (8088), `client-portal`, `polymarket-bot`, or `email-monitor`.
- `brew install whisper-cpp` fails (try `brew install whisper-cpp --build-from-source` once; if that also fails, stop and report).
- `transcript_analyst.analyze_transcript` signature differs materially from what the worker expects (document the actual signature and adapt — do not rewrite the analyst).
- Disk space would drop below 5 GB free after pulling the model (use `medium` model instead, or stop).
- A new Docker container would be required — we're deliberately using a host-side launchd job.

## 7. Do NOT

- Don't add whisper as a Docker service.
- Don't delete anything in `~/Documents/Audio Recordings/` from Bob — that path is on Bert. Matt will delete originals after verification.
- Don't change the x-intake transcript pipeline — share the analyst, don't refactor it.
- Don't expose the Cortex dashboard to the public — same rules as everything else, tailnet or localhost only.

## 8. Final Report Format

Reply in chat with exactly this structure:

````markdown
**Summary:** <2–4 sentences on what was built>

**Files changed:**
- <path> — <one-line purpose>
- ...

**Commits:**
- <sha> — <message>
- ...

**Verification:**
```
<paste: whisper-cli --help head, ls models, launchctl list | grep audio-intake, curl /api/meetings/recent>
```

**MEETING_INGEST_STEPS.md created:** yes/no — path

**Known gaps / follow-ups:** <bullets or "none">
````

---

### Quick-fill variables

```
GOAL: Audio → transcript → Cortex pipeline for meeting recordings
REPO: /Users/bob/AI-Server
HOST: Bob (Mac Mini M4)
SOURCE: Bert (M2), ~9 GB of July 2024 meeting WAVs
TEST_CMD: python3 scripts/audio_intake_worker.py && launchctl list | grep audio-intake
OFF_LIMITS: markup-tool (8088), client-portal, polymarket-bot, email-monitor, Docker
AUTO_APPROVE: true
```
