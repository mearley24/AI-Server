# Lessons Learned — April 4, 2026

## What Was Claimed Working vs What Actually Broke

This documents every manual fix Matt or Computer had to make during the April 4 session. Bob and the team need to learn from each one so it never happens again.

### 1. Agreement PDF had wrong pricing
- **Claimed:** Agreement was up to date in Dropbox Client folder
- **Reality:** Agreement still showed $63,019.17 (V4 pricing from March 31). Proposal was updated to $57,683.09 but agreement was never regenerated.
- **Manual fix:** Computer regenerated the entire 6-page agreement PDF from scratch with correct numbers
- **Root cause:** No system links proposal price changes to agreement regeneration. D-Tools price changes don't trigger downstream document updates.
- **Bob should:** When D-Tools proposal total changes, flag ALL project documents that contain pricing (agreement, deliverables, payment schedule) as stale. Never send a document package where the numbers don't match across all docs.

### 2. Deliverables PDF had wrong lighting schedule
- **Claimed:** Deliverables were current
- **Reality:** Deliverables showed 41 lighting devices (25 KD + 11 APD + 5 SW) from the original scope. The current proposal has 18 devices (16 KD + 2 SW). Payment schedule still showed $63K numbers. Change log was missing deviations 6-9.
- **Manual fix:** Computer regenerated the entire 12-page deliverables from scratch
- **Root cause:** Deliverables were generated March 31 and never updated when Steve confirmed the switch reduction. No system tracks "which documents contain scope-dependent content."
- **Bob should:** Maintain a dependency map: lighting schedule appears in deliverables → when lighting scope changes, deliverables are stale. Payment schedule appears in agreement AND deliverables → when pricing changes, both are stale.

### 3. TV Mount Recommendations referenced wrong ceiling mount
- **Claimed:** TV mount doc was current (April 1 date)
- **Reality:** Doc still says "Peerless-AV PLCM-2 ceiling mount for the Hearth Room remains as specified" — but we determined on April 3 that PLCM-2 doesn't fit the Hisense 100" (wrong VESA, wrong weight). Chief XCM7000 is the replacement. Also still references Legrand back boxes instead of Strong VersaBox.
- **Manual fix:** Needs regeneration (in progress)
- **Root cause:** The April 3 email discussion about ceiling mounts and back boxes never triggered a document update flag.
- **Bob should:** When an email thread discusses a specific product/component that appears in project documents, flag those documents as potentially stale.

### 4. Dropbox share links were wrong format
- **Claimed:** Dropbox links were shared with Steve
- **Reality:** Steve couldn't open them because they were `/preview/` format links that require a Dropbox account. Should be `scl/fi/` format links.
- **Manual fix:** Matt manually generated new share links from Dropbox web UI
- **Root cause:** The original links were generated as preview links, not public share links.
- **Bob should:** ALWAYS use `scl/fi/` format Dropbox links. NEVER use `/preview/` links. Test every share link in an incognito browser before sending to a client.

### 5. Signature wasn't on any documents
- **Claimed:** Documents were ready to send
- **Reality:** None of the four Client folder documents had Matt's signature. No system for auto-signing.
- **Manual fix:** Matt wrote signature on iPad, Computer processed it (transparent background, navy ink), regenerated agreement with signature embedded
- **Root cause:** No signature automation existed. Documents were generated unsigned.
- **Bob should:** Every client-facing document gets Matt's signature (at `knowledge/brand/matt_earley_signature.png`) and today's date automatically. No unsigned documents leave the system.

### 6. Git pull constantly broken by data files
- **Claimed:** `git pull` works
- **Reality:** Every single `git pull` failed due to `data/network_watch/dropout_watch_status.json` conflicts. Required 2-3 manual attempts every time.
- **Manual fix:** Created `scripts/pull.sh` that nukes the file before every git operation
- **Root cause:** Runtime data files being tracked by git. `.gitignore` didn't cover all data files.
- **Bob should:** `scripts/pull.sh` is the ONLY way to pull. Never bare `git pull`. Also verify `.gitignore` covers all `data/**/*.json` and `data/**/*.db` files.

### 7. Dropbox not installed on Bob
- **Claimed:** Bob has access to project files
- **Reality:** Dropbox was installed via brew but never launched/signed in. Bob had no filesystem access to any project documents.
- **Manual fix:** Matt launched Dropbox app, signed in, waited for sync
- **Root cause:** `brew install --cask dropbox` installs but doesn't launch or authenticate.
- **Bob should:** After any new app installation, verify it's actually running and authenticated. Check with `ls ~/Library/CloudStorage/Dropbox*/ 2>/dev/null`.

### 8. iCloud not signed in on Bob
- **Claimed:** iCloud file watcher running
- **Reality:** iCloud watch process was running (PID 57482) but getting "Logged out - iCloud Drive is not configured." Zero files accessible.
- **Manual fix:** Matt physically signed Bob into iCloud via System Settings
- **Root cause:** Bob was never signed into iCloud. The launchd service ran but had nothing to watch.
- **Bob should:** On startup/restart, verify iCloud is signed in: `brctl status 2>/dev/null | head -5`. If "not configured," alert Matt.

### 9. Daily briefing couldn't find email DB
- **Claimed:** Daily briefing works
- **Reality:** Briefing script looked for `/data/emails.db` which doesn't exist. Actual path is `/app/data/email-monitor/emails.db` (Docker) or `/Users/bob/AI-Server/data/email-monitor/emails.db` (crontab).
- **Manual fix:** Added `_find_email_db()` path fallback in the Cursor prompt
- **Root cause:** Hardcoded path that was wrong from day one. Never tested.
- **Bob should:** Every script that reads a file should have path fallback logic. Never hardcode a single path.

### 10. Mission Control fonts too small
- **Claimed:** Dashboard rebuilt and working
- **Reality:** Dashboard tiles filled the viewport but all text was 9-11px — unreadable. Multiple rounds of font size adjustments needed.
- **Manual fix:** Computer edited CSS multiple times, then wrote a Cursor prompt for `clamp()` responsive sizing
- **Root cause:** The "compact Apple tiles" redesign prompt made everything too small without testing at real screen sizes.
- **Bob should:** After any UI change, screenshot at 1280px and 375px and verify readability before deploying.

### 11. Jobs DB empty — D-Tools sync created zero jobs
- **Claimed:** D-Tools sync working, auto-creating jobs
- **Reality:** D-Tools sync scanned 100 opportunities but logged "no active job" for every single one and moved on. Zero jobs in the database. This blocked the ENTIRE downstream pipeline: follow-ups, payments, proposals, daily briefing.
- **Manual fix:** Wrote Cursor prompt to add auto-creation logic for Won/On Hold opportunities
- **Root cause:** The sync was built to FIND existing jobs, not CREATE them. Nobody noticed because the jobs table was never checked.
- **Bob should:** After any "pipeline" feature is deployed, verify the pipeline actually has data flowing through it. Empty tables = dead pipeline.

### 12. Multiple Cursor prompts claimed "done" but files didn't exist
- **Claimed:** Decision journal, confidence, pattern engine, continuous learning, task board, etc. all working
- **Reality:** AGENTS.md referenced 10 files that didn't exist in the repo. Cursor reported them as implemented but the actual Python files were never created.
- **Manual fix:** Wrote `finish-line.md` and `wrap-it-up.md` prompts to actually create every missing file
- **Root cause:** Cursor may have created files locally but they were never committed/pushed. Or Cursor reported planning to create them but didn't actually do it.
- **Bob should:** After every Cursor prompt, run a verification: for each file the prompt claims to create, check `ls -la [file]` and `wc -l [file]`. If it doesn't exist or is 0 lines, it wasn't created.

---

## System Changes Needed (Cursor Prompt Below)

Based on the above, here's what needs to be built/fixed:

### A. Document Staleness Detection
Create `openclaw/doc_staleness.py`:
- Maintains a registry of project documents and what data they contain
- When pricing changes (D-Tools sync detects new total) → flag agreement + deliverables as stale
- When scope changes (email classified as scope change) → flag relevant docs based on DOC_IMPACT_MAP
- When a doc is flagged stale, publish `events:documents` / `doc.stale` event
- Send notification to Matt: "[Project] Agreement is stale — pricing changed from $X to $Y. Reply UPDATE to regenerate."

### B. Document Regeneration Pipeline
Create `openclaw/doc_generator.py`:
- Wraps `tools/generate_agreement.py` with auto-population from jobs DB + D-Tools data
- Auto-applies signature from `knowledge/brand/matt_earley_signature.png`
- Auto-applies today's date
- Auto-publishes to Dropbox Client folder (replace in place)
- Generates: agreement, deliverables, TV recommendations
- Only runs after Matt approves (via iMessage approval flow)

### C. Dropbox Link Validator
Add to `openclaw/orchestrator.py` — before any email with Dropbox links is sent:
- Verify each link is `scl/fi/` format (not `/preview/`)
- Verify the link returns HTTP 200 (file exists and is accessible)
- If validation fails, alert and block the email

### D. Post-Deploy Verification
Create `scripts/verify-deploy.sh`:
- After any `docker compose up`, check:
  - All expected files exist (from a manifest)
  - All DB tables have rows (jobs, decisions, follow_ups, payments)
  - All API endpoints return 200
  - Redis events:log has entries
  - Dropbox is syncing
  - iCloud is connected
- Run automatically after `symphony-ship.sh`

### E. Linear Issue Auto-Update
When D-Tools pricing changes or scope changes are confirmed:
- Update the relevant Linear issues with new pricing
- Close resolved scope issues
- Open new issues for document regeneration tasks

### F. Startup Health Verification
Add to orchestrator first-tick:
- Check iCloud: `brctl status` → if not configured, alert
- Check Dropbox: `ls ~/Library/CloudStorage/Dropbox*/` → if empty, alert
- Check all DB files exist and have tables
- Check signature file exists at `knowledge/brand/matt_earley_signature.png`
- Check `.env` has all required keys (without logging values)

---

## Implementation

Build all of the above. After building, run the full smoke test. Then update AGENTS.md with these lessons so every future session starts with this knowledge.

## Verification
```bash
docker compose build --no-cache openclaw
docker compose up -d openclaw
sleep 60

echo "=== Doc staleness check ==="
docker exec openclaw python3 -c "from doc_staleness import DocStalenessTracker; print('OK')"

echo "=== Doc generator check ==="  
docker exec openclaw python3 -c "from doc_generator import DocGenerator; print('OK')"

echo "=== Startup health ==="
docker logs openclaw 2>&1 | grep "health_check\|icloud\|dropbox\|signature\|stale" | tail -10

echo "=== Smoke test ==="
./scripts/smoke-test.sh
```
