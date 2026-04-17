# Cline Autorun — Audio Router + Soundscapes Pipeline (Bob)

> **Cline:** read this file top to bottom. Operate in **Act mode only** (no planning mode). Restate the goal in one line, then execute without further prompting unless a Guardrail (§6) forces a stop. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in §8.
>
> `AUTO_APPROVE = true`. Read `.clinerules`, `CLAUDE.md`, `STATUS_REPORT.md`, and `ops/AGENT_VERIFICATION_PROTOCOL.md` first — do not explore from scratch.

---

## 1. Role & Operating Mode

You are Cline on **Bob** (`/Users/bob/AI-Server`, Mac Mini M4). This prompt extends the existing meeting audio pipeline (prompt: `cline-prompt-meeting-audio-intake.md`, already shipped as of commit `9d53f2b`). **Do not rewrite the meeting worker.** You are adding a classifier + a parallel soundscape worker and wiring the intake worker to route between them.

Matt's actual audio backlog is a mix — some are meetings, some are nature/ambient recordings he wants preserved as seed material for Bob's forthcoming "music hemisphere." The current pipeline would hallucinate meeting metadata on the nature clips. This prompt fixes that.

## 2. Objective

Build a **YAMNet-based audio router** and a **soundscape worker** that:

1. Classifies every file in `~/AI-Server/data/audio_intake/incoming/` using YAMNet (AudioSet 521-class) + a simple speech-ratio heuristic.
2. Writes a **triage report** to `ops/verification/<timestamp>-audio-triage.txt`, commits + pushes, and **stops** (Matt's approval gate).
3. On approval (Matt replies `proceed` out-of-band; the next worker run re-reads `data/audio_intake/.router_approved` flag file), routes each file to either the existing meeting worker or the new soundscape worker.
4. Soundscape worker: preserves original WAV under `~/AI-Server/data/soundscapes/<yyyy-mm>/<slug>.wav`, transcodes to AAC `.m4a` for quick preview, extracts YAMNet tags + duration + peak-RMS, generates a 1-2 sentence vibe caption via Ollama (fallback OpenAI), indexes to Cortex as `soundscape_intel` memory with all tags queryable.
5. Cortex gets a new endpoint `GET /api/soundscapes/recent` and a matching dashboard tile.
6. Meeting worker remains untouched in its core logic; the only change is that the intake worker calls the router first and only hands speech-dominant files to the meeting worker.

## 3. Environment

- **Host:** Bob, `/Users/bob/AI-Server`, branch `main`
- **Key files to read first:**
  - `.clinerules` — especially the Agent Verification Protocol section (ops/AGENT_VERIFICATION_PROTOCOL.md) and zsh rules
  - `CLAUDE.md`
  - `STATUS_REPORT.md`
  - `scripts/audio_intake_worker.py` — existing meeting worker (DO NOT rewrite; only add a router-check at the top of its main loop)
  - `ops/AGENT_VERIFICATION_PROTOCOL.md` — every bash block you produce for Matt must end with tee-to-file + commit + push; every prompt-prone command (ssh, sudo, etc.) must be pre-empted
  - `cortex/dashboard.py` — model the `/api/soundscapes/recent` after `/api/meetings/recent`
  - `cortex/static/index.html` — model the Soundscapes tile after the Meetings tile (column 3)
- **Services:** Cortex on `http://127.0.0.1:8102`. No new Docker containers — this is a host-side launchd pattern, same as the meeting worker.
- **Off-limits (DO NOT MODIFY):** `markup-tool` (8088), `client-portal`, `polymarket-bot`, `email-monitor`, `scripts/imessage-server.py`, `integrations/x_intake/transcript_analyst.py`.

## 4. Step Plan

### Phase A — Install YAMNet

```bash
cd /Users/bob/AI-Server
mkdir -p models/yamnet

echo "=== install tensorflow (CPU, macOS) and tensorflow-hub ==="
/opt/homebrew/bin/python3 -m pip install --upgrade --quiet tensorflow tensorflow-hub resampy soundfile 2>&1 | tail -5

echo "=== cache YAMNet model locally so we don't hit TF Hub on every run ==="
/opt/homebrew/bin/python3 -c "
import os, tensorflow_hub as hub
os.environ['TFHUB_CACHE_DIR'] = '/Users/bob/AI-Server/models/yamnet'
m = hub.load('https://tfhub.dev/google/yamnet/1')
print('YAMNet loaded, class count:', m.class_map_path().numpy().decode())
"

echo "=== pull AudioSet class map for tag names ==="
curl -fsSL -o models/yamnet/yamnet_class_map.csv \
  https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv
ls -lh models/yamnet/
```

Commit: `feat(audio-router): install YAMNet + class map`

### Phase B — Router script

Create `scripts/audio_router.py`. Responsibilities:

- `classify(path) -> dict` with keys: `top_tags` (list of `(name, score)` pairs, top 5), `speech_ratio` (0.0-1.0, fraction of frames where the top-1 class starts with `Speech`/`Conversation`), `music_ratio`, `nature_ratio` (sum of `Animal`, `Natural sounds`, `Wind`, `Water`, `Thunder`, `Bird`, etc.), `duration_sec`, `peak_rms`, `sample_rate`.
- `route(classification) -> str` returns one of: `"meeting"`, `"soundscape"`, `"review"`.
  - `"meeting"` when `speech_ratio >= 0.35` AND top-1 tag class is speech-like.
  - `"soundscape"` when `speech_ratio < 0.15` AND (`nature_ratio >= 0.25` OR `music_ratio >= 0.25`).
  - `"review"` for everything else — parked for manual decision.
- CLI: `python3 audio_router.py classify <file>` prints JSON. `python3 audio_router.py triage <dir>` classifies every audio file in dir, prints JSON array, and (if `--write-report`) tees to the triage report file.

Key implementation notes:

- Resample to 16kHz mono for YAMNet (it requires this).
- Use `soundfile` for loading WAV/FLAC, `resampy` for resampling, `ffmpeg` subprocess for m4a/mp3/aac (whisper-cli is also present, use it only if you need extra codec support).
- Cache the YAMNet model as a module-global so the `triage` subcommand doesn't reload per file.

Commit: `feat(audio-router): YAMNet-based classifier + CLI`

### Phase C — Soundscape worker

Create `scripts/soundscape_worker.py`. Responsibilities:

- Input: a single audio file path (called by the intake worker when the router returns `soundscape`).
- Steps:
  1. Compute a slug from filename + source date (YYYY-MM from mtime or filename regex).
  2. Destination: `~/AI-Server/data/soundscapes/<YYYY-MM>/<slug>.wav` (copy, not move yet — move happens at the end).
  3. Transcode: `ffmpeg -i <wav> -c:a aac -b:a 192k <slug>.m4a` in the same dir.
  4. Write tag JSON to `<slug>.tags.json` with the full router classification output.
  5. Vibe caption: Ollama call to `http://192.168.1.189:11434/api/generate` with model `qwen3:8b`, prompt asks for "one to two sentences describing the acoustic character of these sound tags for a musician browsing a sound library: <top 8 tags with scores>". Fallback to OpenAI if Ollama unreachable. Timeout 30s. Store in `<slug>.caption.txt` and log it.
  6. Insert row in `data/soundscapes/soundscapes.db` (schema below).
  7. POST to Cortex `/remember` with category `soundscape_intel`, the caption as content, and tags in metadata so they're queryable.
  8. Move the original file from `incoming/` to `processed/` (same as meeting worker does).

Schema for `data/soundscapes/soundscapes.db`:

```sql
CREATE TABLE IF NOT EXISTS soundscapes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  original_name TEXT NOT NULL,
  source_date TEXT,
  duration_sec REAL,
  peak_rms REAL,
  sample_rate INTEGER,
  wav_path TEXT,
  m4a_path TEXT,
  tags_json TEXT,         -- full YAMNet top-10
  top_tag TEXT,           -- convenience: top-1 class name
  speech_ratio REAL,
  music_ratio REAL,
  nature_ratio REAL,
  vibe_caption TEXT,
  cortex_memory_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_soundscapes_top_tag ON soundscapes(top_tag);
CREATE INDEX IF NOT EXISTS idx_soundscapes_date ON soundscapes(source_date);
```

Commit: `feat(soundscape-worker): preserve + tag + caption + Cortex-index`

### Phase D — Wire router into intake worker

In `scripts/audio_intake_worker.py`, add a new first step inside the per-file loop:

```python
from audio_router import classify, route

classification = classify(file_path)
destination = route(classification)
if destination == "soundscape":
    log.info(f"router: {file_path.name} -> soundscape ({classification['top_tags'][0]})")
    subprocess.run(["/opt/homebrew/bin/python3", str(ROOT / "scripts/soundscape_worker.py"), str(file_path)], check=True, timeout=300)
    continue  # skip meeting flow entirely
elif destination == "review":
    log.warning(f"router: {file_path.name} -> review (unclear classification)")
    shutil.move(str(file_path), str(ROOT / "data/audio_intake/review" / file_path.name))
    # write the classification alongside so Matt can see why
    (ROOT / "data/audio_intake/review" / f"{file_path.stem}.router.json").write_text(json.dumps(classification, indent=2))
    continue
# else: meeting — fall through to existing transcribe+analyze flow
```

Create the `data/audio_intake/review/` dir in the same spot the worker creates `incoming/processing/processed/failed/`.

**Crucially:** gate the whole routing step behind a flag file check. Before running the router at all, the worker checks for `data/audio_intake/.router_approved`. If missing, it writes a triage report (see Phase E) and exits without processing any file. Once Matt touches that flag file, the worker proceeds on the next tick.

```python
APPROVAL_FLAG = ROOT / "data/audio_intake/.router_approved"
if not APPROVAL_FLAG.exists() and any(INCOMING.glob("*")):
    log.info("router-approval flag missing — writing triage report and exiting")
    write_triage_report()
    return
```

Commit: `feat(audio-intake): wire router in front of meeting flow + approval gate`

### Phase E — Triage report writer

In `scripts/audio_router.py`, add a `write_triage_report(incoming_dir, out_path)` function that:

- Classifies every file in `incoming/`
- Produces a human-readable table with columns: `file | size | duration | top tag (score) | speech% | music% | nature% | proposed route`
- Ends with a "To proceed" block:

  ```
  =================================================
  Review above. If the classifications look right:
     touch /Users/bob/AI-Server/data/audio_intake/.router_approved
  If you want to override any file, edit:
     /Users/bob/AI-Server/data/audio_intake/router_overrides.json
  with {"filename.wav": "meeting"} or {"filename.wav": "soundscape"}.
  Then touch the flag file.
  =================================================
  ```

The intake worker's Phase D gate writes this report to `ops/verification/<timestamp>-audio-triage.txt` AND commits + pushes it (via a helper that calls git with the author override). Use `subprocess.run` with `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` env vars set to `Perplexity Computer` / `earleystream@gmail.com`.

Commit: `feat(audio-router): triage report + approval gate + override map`

### Phase F — Cortex endpoint + dashboard tile

- `cortex/dashboard.py`: add `GET /api/soundscapes/recent?limit=20` — SELECT from soundscapes.db joined with Cortex memories if `cortex_memory_id` is set.
- `cortex/static/index.html`: add a `#soundscapes-card` card in column 3, next to Meetings. Same style. Tile shows count + last 5 slugs + top tags.
- Keep all existing tiles intact.

Commit: `feat(cortex): soundscapes recent endpoint + dashboard tile`

### Phase G — STATUS_REPORT + README update

Append to STATUS_REPORT.md a "Reference: Audio Router Pipeline" section with:
- Router decision rules (thresholds)
- Triage → approval gate flow
- How to reroute a misclassified file (move between dirs + re-run)
- Where soundscapes live + how to query them

Commit: `docs: audio router + soundscapes pipeline reference`

### Phase H — Kick the first triage run

This is the part where you produce a bash block for Matt following the Agent Verification Protocol. The block:

1. Runs `audio_router.py triage /Users/bob/AI-Server/data/audio_intake/incoming/ --write-report` (after Matt has rsync'd his 17 files in — see below)
2. Tees output to `ops/verification/<timestamp>-audio-triage.txt`
3. Commits + pushes

Also update `MEETING_INGEST_STEPS.md` to note that the one-paste Bert seed block stays the same (it still rsyncs files to `incoming/`), but the worker will NOT auto-transcribe until the router flag is set. Change the polling loop's success condition to account for the `review/` directory too.

Commit: `docs: router approval gate in ingest steps`

---

## 5. Acceptance Criteria (all must pass)

- [ ] YAMNet loads and classifies a test file without errors
- [ ] `audio_router.py classify <file>` prints valid JSON
- [ ] `audio_router.py triage <dir>` writes a readable report
- [ ] `soundscape_worker.py <file>` on a test clip: creates `.wav` + `.m4a` + `.tags.json` + `.caption.txt`, inserts a row, POSTs to Cortex
- [ ] Intake worker with empty `.router_approved` flag + files in incoming: writes triage report, commits, pushes, exits without processing
- [ ] Intake worker with `.router_approved` flag + files in incoming: correctly routes each file and processes
- [ ] Cortex `GET /api/soundscapes/recent` returns `[]` (before any files processed) then populated JSON after
- [ ] Dashboard shows Soundscapes tile
- [ ] Meeting worker still works end-to-end for speech-dominant files (regression: no change to transcribe_and_analyze behavior)
- [ ] No changes to off-limits services (git log confirms)

## 6. Guardrails

- **DO NOT** touch `transcript_analyst.py`, `markup-tool`, `client-portal`, `polymarket-bot`, `email-monitor`, `imessage-server.py`.
- **DO NOT** add a Docker container. This is host-side launchd, same as meeting worker.
- **DO NOT** auto-execute on the 17 files — the approval gate is mandatory.
- **DO NOT** produce a bash block for Matt that can prompt interactively — read `ops/AGENT_VERIFICATION_PROTOCOL.md` §"Interactive-prompt hazards" and pre-empt every one.
- **DO NOT** use `#` inline comments in any bash block you hand Matt (zsh-hostile per `.clinerules`).
- **DO NOT** delete originals from Bert (that's Matt's manual step after verification).

## 7. Final Report Format

```
## Audio Router + Soundscapes — Final Report

### Commits
- <hash> <subject>
- ...

### Files created
- scripts/audio_router.py (<lines>)
- scripts/soundscape_worker.py (<lines>)
- cortex/... (endpoints, dashboard tile)
- data/soundscapes/ (tree)
- models/yamnet/ (cached model)

### Sanity checks
- YAMNet classify on test clip: <top tag + score>
- Soundscape worker on test clip: <files produced>
- Meeting worker regression test: <status>
- Cortex endpoint: <HTTP 200, body sample>
- Dashboard tile: <loading | populated | empty>

### Approval gate status
- `.router_approved` flag: <present | absent>
- Triage report: <path, committed as <hash>>

### Next step for Matt
[One paragraph pointing to the triage report and how to approve / override]
```

---

## 8. Verification block (for Matt to paste after you finish)

At the very end of your final report, include this block for Matt to paste on Bob. It MUST follow `ops/AGENT_VERIFICATION_PROTOCOL.md` (tee + commit + push, no interactive prompts):

```bash
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="/Users/bob/AI-Server/ops/verification/${STAMP}-audio-router-verify.txt"
mkdir -p /Users/bob/AI-Server/ops/verification

{
echo "=============================================="
echo "AUDIO ROUTER VERIFICATION — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=============================================="

echo ""
echo "=== 1. YAMNet model on disk ==="
ls -lh /Users/bob/AI-Server/models/yamnet/

echo ""
echo "=== 2. Router script sanity ==="
/opt/homebrew/bin/python3 /Users/bob/AI-Server/scripts/audio_router.py --help 2>&1 | head -20

echo ""
echo "=== 3. Soundscape worker sanity ==="
/opt/homebrew/bin/python3 /Users/bob/AI-Server/scripts/soundscape_worker.py --help 2>&1 | head -20

echo ""
echo "=== 4. Approval flag status ==="
ls -la /Users/bob/AI-Server/data/audio_intake/.router_approved 2>/dev/null || echo "(flag absent — triage gate active)"

echo ""
echo "=== 5. Soundscapes DB schema ==="
sqlite3 /Users/bob/AI-Server/data/soundscapes/soundscapes.db ".schema soundscapes" 2>/dev/null || echo "(DB not yet created)"

echo ""
echo "=== 6. Cortex soundscapes endpoint ==="
curl -sS -m 5 -o /dev/null -w "HTTP: %{http_code}\n" http://127.0.0.1:8102/api/soundscapes/recent
curl -sS -m 5 http://127.0.0.1:8102/api/soundscapes/recent | head -c 400
echo ""

echo ""
echo "=== 7. Dashboard soundscapes tile markers ==="
grep -n -iE "soundscapes|soundscape_intel" /Users/bob/AI-Server/cortex/static/index.html | head -10
grep -n -E "soundscapes/recent|soundscape_intel" /Users/bob/AI-Server/cortex/dashboard.py | head -10

echo ""
echo "=== 8. Guardrail audit (since 2026-04-17) ==="
cd /Users/bob/AI-Server
for P in markup-tool client-portal polymarket-bot email-monitor scripts/imessage-server.py integrations/x_intake/transcript_analyst.py; do
  echo "--- $P ---"
  git log --since="2026-04-17 08:00" --oneline -- "$P" 2>/dev/null
done
echo "--- docker-compose.yml ---"
git log --since="2026-04-17 08:00" --oneline -- docker-compose.yml 2>/dev/null

echo ""
echo "=== 9. Recent commits ==="
git log -12 --pretty=format:"%h  %an <%ae>  %s"

echo ""
echo "=============================================="
echo "END"
echo "=============================================="
} > "$OUT" 2>&1

cd /Users/bob/AI-Server
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" add "$OUT"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" commit -m "ops: audio router verification ${STAMP}"
git push origin main 2>&1 | tail -3
echo "DONE. Reply to the agent: 'router verify pushed'."
```

AUTO_APPROVE: true
