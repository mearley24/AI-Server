# Cline Autorun — Fix Symphony Ops Tab (Cortex Dashboard)

> **Cline:** read this file top to bottom. Operate in **Plan → Act**. Restate the goal, post a short plan, then execute without further prompting unless a Guardrail (§6) forces a stop. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in §7.
>
> `AUTO_APPROVE = true`. Read `.clinerules`, `CLAUDE.md`, and `STATUS_REPORT.md` first — do not explore from scratch.

---

## 1. Role & Operating Mode

You are Cline, autonomous coding agent on **Bob** (`/Users/bob/AI-Server`, Mac Mini M4). Terminal + Docker + git + Homebrew. Verify with `read_file` / `search_files` / `ls` before editing. Conventional commits only (`fix:`, `feat:`, `docs:`, `chore:`). Never invent paths — confirm they exist first. This prompt only touches `cortex/` and `docker-compose.yml`. Do **not** modify `markup-tool`, `client-portal`, `polymarket-bot`, or `email-monitor`.

## 2. Objective

Fix four visible defects on the **Symphony Ops** tab of the Cortex dashboard (`http://127.0.0.1:8102/` or whatever port the dashboard is served on — confirm by reading `cortex/dashboard.py`):

1. **Quick Tools all fail** with `python3: can't open file '/app/tools/bob_room_mapper.py': [Errno 2] No such file or directory` (and the same for `cortex_curator.py`, `bob_project_analyzer.py`, etc.). The `cortex` container is not mounting `./tools` at `/app/tools`.
2. **"Run Improvement Cycle" returns `{"detail":"Not Found"}`**. The dashboard button POSTs to `/improve`, but the actual FastAPI route is `/improve/run` on the Cortex engine.
3. **Proposals "Templates" shows `0`** even though the proposals service is online. Shape mismatch — the proposals service returns `{proposal_templates: [...], email_templates: [...]}` but the dashboard reads `data.templates`.
4. **Markup Tool is offline.** The dashboard already prints the start command. Just launch it via launchd so it stays up.

After fixes, every Quick Tool button should produce real stdout (even if some tools exit non-zero for missing data — that's fine, we just need them to *run*). The Improvement Cycle button should return a JSON body with cycle results, not `{"detail":"Not Found"}`. Templates should show the real count (likely ≥1 since `proposals/proposal_templates/*.md` exists in the repo). Markup Tool should flip to online within 30s of the launchd load.

## 3. Environment

- **Host:** Bob (Mac Mini M4), repo `/Users/bob/AI-Server`, branch `main`
- **Key files to read first (do not skip):**
  - `.clinerules`, `CLAUDE.md`, `STATUS_REPORT.md`
  - `cortex/dashboard.py` — confirm `symphony_run_tool`, `symphony_proposals_templates`, `PROPOSALS_URL`, and which port it listens on
  - `cortex/engine.py` — confirm `/improve/run` signature and any auth
  - `cortex/static/index.html` — `loadProposalTemplates()`, `triggerImprovement()`, Quick Tools buttons (lines ~470–600, ~1360–1500 as of latest `main`)
  - `docker-compose.yml` — `cortex` service block (volumes list)
  - `tools/` — confirm the scripts referenced by `symphony_run_tool` actually exist on disk (`bob_room_mapper.py`, `cortex_curator.py`, etc.)
  - `proposals/api_server.py` — confirm the `/proposals/templates/list` response shape
  - `proposals/proposal_templates/` — count the `.md` files so you know what the UI should show
- **Services touched (allowed):** `cortex` (recompose), `markup-tool` (start only — do not edit its code). Do NOT touch `markup-tool` source, `client-portal`, `polymarket-bot`, `email-monitor`.

## 4. Step Plan

### Phase A — Verify current state (read-only)

```bash
cd /Users/bob/AI-Server
git pull --ff-only

# A1. Confirm tools exist on host
ls tools/bob_room_mapper.py tools/cortex_curator.py tools/bob_project_analyzer.py \
     tools/bob_proposal_to_dtools.py tools/bob_build_inventory.py \
     tools/bob_fetch_manuals.py tools/knowledge_graph.py tools/bob_maintenance.py

# A2. Confirm tools are NOT mounted inside cortex container
docker compose exec cortex ls /app/tools 2>&1 | head -5    # expected: No such file or directory

# A3. Confirm /improve/run is the real route
docker compose exec cortex python -c "from cortex.engine import app; \
  print([r.path for r in app.routes if 'improve' in r.path])"

# A4. Confirm proposals template response shape
curl -s http://127.0.0.1:8091/proposals/templates/list | python3 -m json.tool | head -20

# A5. Confirm markup tool status
curl -sf http://127.0.0.1:8088/health 2>&1 | head -3 || echo "markup offline"
ls ~/Library/LaunchAgents/com.symphony.markup-tool.plist 2>/dev/null || echo "no launchd for markup"
```

### Phase B — Fix #1: Mount `./tools` into the `cortex` container

Edit `docker-compose.yml`. Find the `cortex:` service block and add one line to its `volumes:` list:

```yaml
  cortex:
    ...
    volumes:
      - ./cortex:/app/cortex
      - ./data/cortex:/data/cortex
      - ./data/openclaw:/app/data/openclaw:ro
      - ./polymarket-bot/knowledge:/app/knowledge:ro
      - ./data/x_intake:/data/x_intake:ro
      - ./tools:/app/tools:ro                       # <-- ADD THIS LINE
```

Use read-only (`:ro`) — Cortex never writes to `tools/`. Matches the pattern already used by `dtools-bridge` at line ~422.

Then recompose **only cortex** (no full stack restart):

```bash
docker compose up -d --no-deps cortex
# wait for health
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8102/health >/dev/null; then echo "cortex healthy"; break; fi
  sleep 2
done
docker compose exec cortex ls /app/tools | head -10        # should now list the .py files
```

### Phase C — Fix #2: Point "Run Improvement Cycle" at the real route

**Pick the LEAST invasive fix.** Inspect `cortex/engine.py` to see if `/improve/run` requires POST body / auth. It's almost certainly a bare `POST /improve/run`. Then edit `cortex/static/index.html`:

Find `async function triggerImprovement()` (around line 1490). Change:

```js
const r = await fetch('/improve', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
```

to:

```js
const r = await fetch('/improve/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
```

If the dashboard runs on a different port than the engine (read `cortex/dashboard.py` to confirm), add a proxy endpoint to `cortex/dashboard.py` that forwards to `{CORTEX_ENGINE_URL}/improve/run` — mirror the pattern already used for `symphony_proposals_generate`. Otherwise the one-line HTML fix is enough.

After the edit:

```bash
# Rebuild static only — no restart needed if dashboard serves files from disk
curl -s -X POST http://127.0.0.1:8102/improve/run -H 'Content-Type: application/json' -d '{}' | head -40
```

Expect a JSON body (not `{"detail":"Not Found"}`). If the cycle is long-running, it may stream — that's fine.

### Phase D — Fix #3: Proposals Templates count

Two acceptable fixes — **pick the proxy-side one** so we don't have to ship frontend changes every time the proposals API shape shifts.

Edit `cortex/dashboard.py`, function `symphony_proposals_templates` (around line 1066). Change from:

```python
@app.get("/api/symphony/proposals/templates")
async def symphony_proposals_templates():
    data = await _safe_get(f"{PROPOSALS_URL}/proposals/templates/list")
    return data or {"templates": [], "error": "proposals service unavailable"}
```

to:

```python
@app.get("/api/symphony/proposals/templates")
async def symphony_proposals_templates():
    data = await _safe_get(f"{PROPOSALS_URL}/proposals/templates/list")
    if not data:
        return {"templates": [], "error": "proposals service unavailable"}
    # Normalize upstream shape — proposals returns {proposal_templates, email_templates}
    templates = data.get("templates")
    if templates is None:
        templates = data.get("proposal_templates") or []
    return {"templates": templates, "email_templates": data.get("email_templates", [])}
```

Recompose cortex:

```bash
docker compose up -d --no-deps cortex
curl -s http://127.0.0.1:8102/api/symphony/proposals/templates | python3 -m json.tool
```

Expect `{"templates": ["full_automation", ...], "email_templates": [...]}` with count > 0.

### Phase E — Fix #4: Bring Markup Tool online via launchd

Create `~/Library/LaunchAgents/com.symphony.markup-tool.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.symphony.markup-tool</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/bob/AI-Server/tools/markup_app/server.py</string>
    <string>--port</string><string>8088</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/bob/AI-Server</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/bob/AI-Server/logs/markup-tool.out.log</string>
  <key>StandardErrorPath</key><string>/Users/bob/AI-Server/logs/markup-tool.err.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string></dict>
</dict>
</plist>
```

Load it:

```bash
mkdir -p /Users/bob/AI-Server/logs
launchctl unload ~/Library/LaunchAgents/com.symphony.markup-tool.plist 2>/dev/null || true
launchctl load -w ~/Library/LaunchAgents/com.symphony.markup-tool.plist
sleep 3
curl -sf http://127.0.0.1:8088/health && echo "MARKUP ONLINE" || echo "MARKUP FAILED — tail logs/markup-tool.err.log"
```

If it fails, tail the error log and report — **do not** start hacking on `tools/markup_app/server.py`. That's off-limits.

### Phase F — Verify in-browser

```bash
# Open the dashboard and spot-check each panel
open http://127.0.0.1:8102/
```

Manually click (or `curl`-verify):

- ✅ Quick Tools → "Room Mapper" → stderr no longer contains `No such file or directory`
- ✅ Quick Tools → "Cortex Curator" → same
- ✅ "Run Improvement Cycle" → returns a JSON object, dashboard renders it
- ✅ Proposals → Templates count > 0, dropdown populated
- ✅ Markup Tool tile → flips to "online"

### Phase G — Commit

```bash
git add docker-compose.yml cortex/dashboard.py cortex/static/index.html
git -c user.email="$(git config user.email)" -c user.name="$(git config user.name)" \
  commit -m "fix(cortex): mount tools volume, fix improve route, normalize templates shape"

# launchd plist — commit a template version into the repo if conventional
mkdir -p ops/launchd
cp ~/Library/LaunchAgents/com.symphony.markup-tool.plist ops/launchd/com.symphony.markup-tool.plist
git add ops/launchd/com.symphony.markup-tool.plist
git commit -m "chore(ops): add launchd plist for markup-tool (port 8088)"

git push origin main
```

## 5. Acceptance Criteria

- [ ] `docker compose exec cortex ls /app/tools` lists the Bob tool scripts
- [ ] Clicking any Quick Tools button yields a non-empty `stdout` field (or a legitimate runtime error — NOT `[Errno 2]`)
- [ ] `curl -X POST http://127.0.0.1:8102/improve/run -d '{}'` returns 200 with a JSON body
- [ ] `curl http://127.0.0.1:8102/api/symphony/proposals/templates | jq '.templates | length'` returns a number ≥ 1
- [ ] Symphony Ops tab shows Templates count matches the `jq` result
- [ ] `curl -sf http://127.0.0.1:8088/health` returns 200 within 10s of launchd load
- [ ] Markup Tool tile on the dashboard flips to "online" (may need a page refresh — document this if true)
- [ ] Everything committed to `main`, pushed, no dangling local changes
- [ ] `STATUS_REPORT.md` updated with one-line entry under "Recently fixed"

## 6. Guardrails — STOP if any of these trigger

- `docker-compose.yml` has any pending uncommitted edits from another branch
- `cortex` container fails healthcheck after the volume change → roll back the volume line, recompose, report
- `/improve/run` requires auth / a specific payload not currently sent → pause, dump the FastAPI signature into the Final Report, and ask before patching
- `proposals/proposal_templates/` directory is empty (no templates seeded) → stop; the shape fix is still right but the count will legitimately be 0 — note this in Final Report
- `tools/markup_app/server.py` exits non-zero → DO NOT edit its source; dump stderr and stop

## 7. Final Report (produce when done)

Markdown, ≤ 40 lines:

1. **Fixes applied** — one line each (files touched + key change)
2. **Commit SHAs** — both of them, with the blob URLs
3. **Verification evidence** — paste the actual JSON/curl output for each acceptance criterion (one short block per criterion)
4. **Remaining concerns** — anything that surfaced (e.g. a Quick Tool that runs but errors with real data, a missing env var in `tools/*.py`, etc.)
5. **Suggested follow-up** — only if meaningful
