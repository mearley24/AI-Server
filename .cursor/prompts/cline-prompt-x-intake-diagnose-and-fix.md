# Cline Autorun — X-Intake Diagnose & Fix (end-to-end)

> **Cline:** read this file top to bottom. Operate in **Plan → Act**. Restate the goal, post a short plan, then execute without further prompting unless a Guardrail (§9) forces a stop. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in §10.
>
> `AUTO_APPROVE = true`. Read `.clinerules` and `CLAUDE.md` first — do not explore from scratch.

---

## 1. Role & Operating Mode

You are Cline, autonomous coding agent on **Bob** (`/Users/bob/AI-Server`). You have terminal + Docker + git. Always verify with `read_file` / `search_files` / `docker inspect` before editing. Use conventional commits (`fix:`, `feat:`, `docs:`). Never invent code paths — confirm they exist first.

## 2. Objective

The x-intake pipeline has three visible symptoms today:

1. **Items queue but never get analyzed** — rows land in `data/x_intake/queue.db` but `analyzed` stays 0, no summary / flags / transcript back-reference.
2. **Transcripts missing or lost** — `.md` files in `data/transcripts/` are not being produced (or are lost on container restart) for containerized x-intake runs.
3. **Dashboard blank / wrong data** — the Cortex X Intake tab shows nothing, stale data, or errors.

All three are downstream of the same class of problems documented in `STATUS_REPORT.md` — volume mounts not actually applied to the running container, transcript analyst writing to ephemeral container paths, `transcript_path` not persisted, or listener watchdog masking silent analyze failures.

**Deliver:** a running x-intake that (a) has both volume mounts live, (b) writes durable transcripts, (c) marks rows `analyzed=1` with `transcript_path` populated, (d) renders correctly in the Cortex dashboard. Plus a status-report update and regression-resistant logging.

## 3. Environment

- **Host:** Bob (Mac Mini M4), repo at `/Users/bob/AI-Server`
- **Branch:** `main`
- **Key files to read first:**
  - `.clinerules`
  - `CLAUDE.md`
  - `STATUS_REPORT.md` — specifically the `## Reference: X-Intake Listener Failure (§Z14)`, `## Reference: X Intake Review Queue (2026-04-13)`, `## Reference: Transcript Integration Verification (2026-04-13 live audit)`, and `### 2 — X Intake Workflow` sections
  - `integrations/x_intake/main.py`
  - `integrations/x_intake/queue_db.py`
  - `integrations/x_intake/video_transcriber.py`
  - `integrations/x_intake/transcript_analyst.py`
  - `docker-compose.yml` (the `x-intake:` service block)
  - `cortex/dashboard.py` (x-intake endpoints)
  - `cortex/static/index.html` (X Intake tab)
- **Services touched:** `x-intake` (port 8101), `cortex` (port 8102). Do NOT touch `polymarket-bot`, `email-monitor`, `markup-tool` (8088), or `client-portal`.

## 4. Step Plan

### Phase A — Diagnose (read-only, no changes yet)

Run each command, capture the output verbatim, and include it in the Final Report.

```bash
cd /Users/bob/AI-Server

# A1. Confirm the running x-intake container has both expected volume mounts
docker inspect x-intake --format '{{json .Mounts}}' | python3 -m json.tool

# A2. Confirm TRANSCRIPT_DIR env is set on the running container
docker inspect x-intake --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E "TRANSCRIPT_DIR|REDIS|QUEUE"

# A3. Queue DB size + row breakdown
ls -la data/x_intake/queue.db
sqlite3 data/x_intake/queue.db "SELECT status, analyzed, has_transcript, COUNT(*) FROM x_intake_queue GROUP BY status, analyzed, has_transcript ORDER BY 1,2,3"

# A4. Last 10 rows (most recent) — see what's actually stored
sqlite3 data/x_intake/queue.db "SELECT id, substr(url,1,60), status, analyzed, has_transcript, transcript_path, substr(summary,1,60), created_at FROM x_intake_queue ORDER BY id DESC LIMIT 10"

# A5. Transcript dir contents
ls -la data/transcripts/ | head -20
find data/transcripts/ -name "*.md" -mtime -3 -printf "%T@ %p %s bytes\n" 2>/dev/null | sort -n | tail -10

# A6. x-intake container logs — look for analyze errors, listener resets, transcriber exceptions
docker logs x-intake --tail 300 2>&1 | tail -200

# A7. Cortex dashboard endpoint responses (what the UI actually sees)
curl -s http://127.0.0.1:8102/api/x-intake/stats | python3 -m json.tool
curl -s 'http://127.0.0.1:8102/api/x-intake/items?limit=5' | python3 -m json.tool
curl -s http://127.0.0.1:8101/health

# A8. Listener watchdog — prove it's actually subscribed right now
docker exec x-intake python3 -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); print(r.pubsub_numsub('events:imessage'))"
```

### Phase B — Classify findings

Based on Phase A, determine which of these is true (there may be more than one). Only fix what's actually broken — do not perform unnecessary rebuilds.

- **B1 — Volumes not mounted.** `A1` shows fewer than 2 mounts, or the `Source` is not the repo's `./data/x_intake` / `./data/transcripts`, or `TRANSCRIPT_DIR` is missing from `A2`.
- **B2 — Queue schema stale.** `A4` errors on `analyzed` or `transcript_path` column → `queue_db.py` migration didn't run inside the container → stale image.
- **B3 — Analyze path silently failing.** `A4` shows rows with `analyzed=0` that are >10 minutes old AND `A6` shows no corresponding `_analyze_url` error lines (i.e. errors are being swallowed). Or `A6` shows `asyncio.new_event_loop()` anti-pattern still present.
- **B4 — Transcriber producing no files.** `A5` is empty or only contains files older than the last iMessage URL with a video; or files exist in the container but not in `./data/transcripts/` on the host.
- **B5 — Dashboard plumbing broken.** `A7` returns error/empty while `A4` shows data → `cortex/dashboard.py` proxying to x-intake is broken or reading a wrong DB path.
- **B6 — Listener dead.** `A8` returns `0` subscribers for `events:imessage`.

### Phase C — Fixes (only apply the ones required by B)

Apply the minimum set. Commit each fix as its own commit.

#### C1 — If B1 (volume mounts)

Verify `docker-compose.yml` has both mounts on the `x-intake` service:

```yaml
x-intake:
  # ...
  environment:
    - TRANSCRIPT_DIR=/data/transcripts
    # ... rest unchanged
  volumes:
    - ./data/x_intake:/data/x_intake
    - ./data/transcripts:/data/transcripts
    # ... keep any other existing volumes
```

If missing, add them. Then:

```bash
docker compose up -d --build --force-recreate x-intake
# Re-run A1/A2 to confirm mounts are now live
```

Commit: `fix(x-intake): ensure transcripts & queue volumes are mounted on running container`

#### C2 — If B2 (schema stale)

`queue_db.py` already has auto-migration (adds `analyzed`, `transcript_path` if missing). Forcing a rebuild fixes it:

```bash
docker compose up -d --build --force-recreate x-intake
```

Then confirm columns exist:

```bash
sqlite3 data/x_intake/queue.db ".schema x_intake_queue"
```

#### C3 — If B3 (silent analyze failures)

Edit `integrations/x_intake/main.py` to make `_analyze_url` failures loud and recoverable:

- Wrap the analyze body in try/except and on exception: log `logger.exception("_analyze_url failed for %s", url)`, mark the queue row `analyzed=0, status='error', error_msg=str(e)[:500]` (add `error_msg TEXT` column to schema if missing — `queue_db.py` auto-migration pattern), and do **not** swallow.
- Confirm the `asyncio.new_event_loop()` anti-pattern is gone (§Z14 fix) — there should be no `asyncio.new_event_loop()` calls in `main.py` or `transcript_analyst.py`. If any remain, replace with `await _analyze_url(url)` in async callers or `asyncio.run(_analyze_url(url))` in sync ones.
- Add a one-shot backfill helper at the bottom of `main.py` (behind a CLI flag like `python -m integrations.x_intake.main --reanalyze-stuck`) that re-queues rows where `analyzed=0 AND created_at < datetime('now','-10 minutes')`.

After editing, rebuild:

```bash
docker compose up -d --build x-intake
docker exec x-intake python -m integrations.x_intake.main --reanalyze-stuck
```

Commit: `fix(x-intake): loud errors + backfill CLI for stuck analyze rows`

#### C4 — If B4 (transcripts)

- Confirm `video_transcriber.save_transcript()` is using `os.environ.get("TRANSCRIPT_DIR", …)` and not a hard-coded `~/AI-Server/data/transcripts`. If it is, fix it to honor the env var.
- Confirm `integrations/x_intake/main.py::_analyze_url` writes the returned `transcript_path` into the queue DB via `queue_db.set_transcript(row_id, path)` (add if missing).
- Send a known-good test URL with a video through the pipeline (see Phase D) and verify a .md file lands in `./data/transcripts/` on the host and `transcript_path` is populated.

Commit: `fix(x-intake): persist transcript_path and honor TRANSCRIPT_DIR env`

#### C5 — If B5 (dashboard)

Check `cortex/dashboard.py`:

- `/api/x-intake/items` must open `data/x_intake/queue.db` at the path bind-mounted into the cortex container (the cortex service also needs `./data/x_intake:/data/x_intake:ro` mounted — verify with `docker inspect cortex --format '{{json .Mounts}}'`).
- If the cortex container can't see `queue.db`, add the read-only mount to the `cortex:` service block in `docker-compose.yml` and `docker compose up -d --build cortex`.
- Open the Cortex UI at `http://127.0.0.1:8102/` and click the **X Intake** tab. Confirm rows render and counts are live.

Commit: `fix(cortex): mount x_intake queue db read-only into dashboard container`

#### C6 — If B6 (listener dead)

The watchdog should already handle this (§Z14 complete per status report). If `A8` still returned 0, the watchdog logic itself is broken:

- Grep `integrations/x_intake/main.py` for `_listener_watchdog`. Confirm it's scheduled on startup (`asyncio.create_task(_listener_watchdog())` in the FastAPI startup event).
- Confirm it checks `r.pubsub_numsub('events:imessage')` every ≤10s and re-subscribes when count is 0.
- If the watchdog exists but the task reference is being garbage-collected, store it on `app.state.listener_watchdog_task`.

Commit: `fix(x-intake): keep listener watchdog task referenced so GC doesn't kill it`

### Phase D — End-to-end regression test

```bash
# D1. Pick a known-good X/Twitter URL with a short video. Post it via iMessage
#     to the number that routes to events:imessage, OR publish directly:
docker exec x-intake python3 -c "
import redis, os, json, time
r = redis.from_url(os.environ['REDIS_URL'])
r.publish('events:imessage', json.dumps({
    'text': 'https://x.com/_/status/TEST_ID',
    'source': 'regression_test',
    'timestamp': time.time()
}))
print('published')
"

# D2. Wait 60s, then:
sleep 60
sqlite3 data/x_intake/queue.db "SELECT id, status, analyzed, has_transcript, transcript_path, substr(summary,1,80) FROM x_intake_queue ORDER BY id DESC LIMIT 3"
ls -la data/transcripts/ | tail -5

# D3. Dashboard round-trip
curl -s 'http://127.0.0.1:8102/api/x-intake/items?limit=3' | python3 -m json.tool | head -40

# D4. Screenshot dashboard (optional)
#     open http://127.0.0.1:8102/  → X Intake tab → confirm row is there with summary
```

Expected: at least one row has `analyzed=1`, `has_transcript=1` (for URLs with video), `transcript_path` is a real file that exists, and the dashboard API returns it.

### Phase E — Status report update

Append a new section at the bottom of `STATUS_REPORT.md`:

```
## Reference: X-Intake Diagnose & Fix (YYYY-MM-DD)

### Phase A findings (what was broken)
- <copy the Phase A diagnostics here, trimmed>

### Fixes applied
- <list the C1–C6 items that were actually applied, with commit SHAs>

### Regression test results
- <paste Phase D output>

### Remaining known limits
- <anything intentionally not fixed, with reason>
```

Also update the `## Now` and `## Next` top-of-file sections: move any closed x-intake items to `## Done`, add any newly-discovered follow-ups to `## Later`.

Commit: `docs(status): x-intake diagnose & fix <date>`

## 5. Acceptance Criteria

All must pass:

- [ ] `docker inspect x-intake` shows **both** `./data/x_intake` and `./data/transcripts` mounted, and `TRANSCRIPT_DIR=/data/transcripts` in env.
- [ ] `sqlite3 data/x_intake/queue.db ".schema x_intake_queue"` includes `analyzed`, `has_transcript`, `transcript_path`.
- [ ] `docker exec x-intake python3 -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); print(r.pubsub_numsub('events:imessage'))"` returns ≥ 1 subscriber.
- [ ] After Phase D test URL, at least one row has `analyzed=1` within 120 seconds.
- [ ] `curl http://127.0.0.1:8102/api/x-intake/items?limit=5` returns the test row as JSON.
- [ ] `docker logs x-intake --tail 200` shows **zero** `asyncio.new_event_loop` lines and zero unhandled `Traceback`s in the last hour.
- [ ] `STATUS_REPORT.md` has a new `## Reference: X-Intake Diagnose & Fix` section with actual diagnostics pasted in.
- [ ] `git log --oneline origin/main..HEAD` shows between 1 and 6 commits, all conventional-commit prefixed.

## 6. Guardrails

Stop and surface to the user if any of these are true:

- A fix requires changing `markup-tool` (8088), `client-portal`, `polymarket-bot`, or `email-monitor`.
- A fix requires a new top-level dependency or a new exposed port.
- More than 6 files need to be edited (scope creep — re-plan first).
- Any attempt to wipe `queue.db` or `data/transcripts/` — these are production data. Migrate in place or `ALTER TABLE`; never drop.
- Phase A shows the cortex container can't reach `x-intake` on the Docker network (that's a compose networking issue, separate from this prompt).

## 7. Final Report Format

Reply in chat with exactly this structure:

````markdown
**Summary:** <2–4 sentences on what was actually broken and what was fixed>

**Phase A diagnostics:**
```
<paste the A1–A8 outputs, trimmed if enormous>
```

**Classification:** <which of B1–B6 were true>

**Fixes applied:**
- <commit SHA> — <message>
- ...

**Phase D regression test:**
```
<paste output>
```

**STATUS_REPORT.md updated:** yes / no

**Known gaps / follow-ups:** <bullets or "none">
````

---

### Quick-fill variables

```
GOAL: Restore x-intake: queue analyze, transcript persistence, dashboard render
REPO: /Users/bob/AI-Server
SERVICES: x-intake (8101), cortex (8102)
OFF_LIMITS: markup-tool (8088), client-portal, polymarket-bot, email-monitor
TEST_CMD: bash scripts/pull.sh && docker compose up -d --build x-intake && curl -s http://127.0.0.1:8101/health
AUTO_APPROVE: true
```
