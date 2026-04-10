-- close-all-gaps-april10.md --
-- Run with Claude Code: cd ~/AI-Server && claude --
-- Read .clinerules first for full project context --

GOAL: Close every remaining gap in the Symphony AI-Server. Six tasks, all independent. Build each one, verify it works, commit after each.

IMPORTANT RULES:
- Use `bash scripts/pull.sh` instead of bare `git pull`
- Never use vim, nano, or crontab -e — one-liner commands only
- Shell scripts use set -euo pipefail
- Python uses PEP 8, type hints, docstrings on public functions
- All Redis connections MUST use password: redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
- OpenClaw code is bind-mounted at ./openclaw:/app — Python-only edits just need `docker restart openclaw`
- Test everything before committing


TASK 1: X-INTAKE DEEP ANALYSIS
-------------------------------
Problem: x-intake only reads the surface tweet text (oembed). Threads, video transcription, and linked content are not being processed. The analysis Bob sends back via iMessage is shallow and useless.

Current state:
- integrations/x_intake/main.py — rewritten today with LLM analysis + Matt's relevance profile
- integrations/x_intake/post_fetcher.py — has thread_context support but only fetches parent post, not full thread replies
- integrations/x_intake/video_transcriber.py — process_x_video() exists, yt-dlp + Whisper are installed in the container
- The container has ffmpeg, yt-dlp, openai, httpx in requirements.txt

What to fix:
1. In post_fetcher.py: When fetching a post, also fetch ALL replies by the same author (thread continuation). Use the fxtwitter/vxtwitter API conversation endpoint or fetch replies by conversation_id. Concatenate all thread posts in order.
2. In main.py _analyze_url(): When the post contains a link to a GitHub repo, article, or external resource, fetch that URL and include a summary in the LLM analysis. Use httpx to GET the page, extract the README or article text (first 3000 chars), pass it to the LLM.
3. In main.py _analyze_url(): The video transcription path (process_x_video) must actually run inside the container. Verify yt-dlp works by adding a try/except with logging around the download step. If the post has no video but has images, skip transcription silently.
4. Wire Cortex into x-intake: After analysis, POST the result to http://cortex:8102/api/entries with category="x_intake", content=summary, tags=["x", author, post_type]. Before analysis, GET http://cortex:8102/api/paths/relevant?q={author} to see if Cortex knows anything about this author.
5. The iMessage reply should be substantive: include the thread content summary, any video transcript highlights, linked resource takeaways, relevance score, and a concrete action item. Not just the first tweet's text.

Test: Send an X link via Redis publish and verify x-intake logs show full pipeline execution:
docker compose exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 PUBLISH events:imessage '{"text":"https://x.com/sharbel/status/2042184918600458712"}'


TASK 2: FOLLOW-UP ENGINE AUTO-SEND
------------------------------------
Problem: follow_up_tracker.py tracks follow-ups in SQLite but only publishes to Redis notifications:email channel. It never actually drafts or sends follow-up emails. The follow-up templates exist in the job lifecycle but auto-send was never wired.

Current state:
- openclaw/follow_up_tracker.py — tracks due dates, publishes to NOTIFY_CHANNEL
- openclaw/follow_up_engine.py — exists but needs verification
- follow_ups.db has 57 rows
- Zoho email credentials are in .env (ZOHO_EMAIL, ZOHO_APP_PASSWORD)

What to build:
1. In follow_up_engine.py: When a follow-up is due (day 3, 7, or 14 after proposal sent), draft an email using the job's client name, project name, and proposal date. Use GPT-4o-mini to generate a professional, brief follow-up email.
2. Do NOT auto-send. Instead: publish the draft to Redis channel notifications:approval with the draft text. The iMessage bridge picks this up and texts Matt "Follow-up draft for [client]: [preview]. Reply YES to send."
3. On YES reply, send via Zoho IMAP/SMTP (same pattern as email-monitor).
4. Log the sent follow-up in Cortex: POST to http://cortex:8102/api/entries with category="follow_up", content="Sent day X follow-up to [client]".

Test: Verify follow_up_engine runs on the orchestrator tick without errors:
docker restart openclaw && sleep 30 && docker logs openclaw --tail 30 2>&1 | grep -i follow


TASK 3: CORTEX INTEGRATION — WIRE ALL SERVICES
-------------------------------------------------
Problem: Cortex is running on port 8102 but only openclaw and mission-control are wired to it. Every other service should be feeding it data and querying it before making decisions.

Services to wire:
1. email-monitor/monitor.py — After classifying an email, POST to Cortex: {"category": "email", "content": "Email from [sender]: [subject] — classified as [category]", "tags": ["email", sender, category]}
2. x-intake/main.py — Already covered in Task 1 above
3. openclaw/daily_briefing.py — Before generating the briefing, GET /api/paths/relevant?q=daily+briefing to include any neural path insights. After sending, POST the briefing content to Cortex.
4. openclaw/follow_up_tracker.py — When a follow-up becomes due, POST to Cortex.
5. notification-hub/main.py — After sending any high-priority notification, POST to Cortex with category="notification".
6. polymarket-bot — this one is inside its own container. Add a simple function that POSTs to http://cortex:8102/api/entries after each trade or significant decision. Add CORTEX_URL=http://cortex:8102 to docker-compose.yml environment for polymarket-bot.

For all POSTs, use a try/except wrapper so Cortex being down never crashes the calling service. Log warnings only.

Test: Check Cortex entry count grows after triggering some events:
curl -s http://localhost:8102/api/stats


TASK 4: DAILY BRIEFING IMPROVEMENTS
--------------------------------------
Problem: The daily briefing fires at 6 AM and is confirmed working. But it should include more context now that Cortex exists.

What to add:
1. Query Cortex for neural paths with confidence > 70 that were updated in the last 24h. Include a "Patterns Detected" section in the briefing.
2. Query Cortex for the most recent 5 entries. Include a "Recent Activity" summary.
3. Include client portal status: any pending signatures or overdue deposits.
4. Include x-intake stats: how many links were analyzed in the last 24h, top insights.

Keep the briefing under 2000 characters for iMessage readability.

Test: Trigger a manual briefing:
docker compose exec openclaw python -c "from daily_briefing import DailyBriefing; import asyncio; asyncio.run(DailyBriefing().send())"


TASK 5: PULL SCRIPT HARDENING
-------------------------------
Problem: Bob's repo gets into broken states from merge conflicts, stale stashes, and dirty working directories. The pull script was patched today to detect conflict markers, but it needs to be more robust.

Current scripts/pull.sh: stash → pull --rebase → stash pop → checkout dropout_watch_status.json → scan for conflict markers

What to add:
1. Before pull: `git diff --name-only` to log what files have local changes. If any Python files are modified locally, warn but continue (the conflict marker scanner will catch issues).
2. After pull: verify every Python file in openclaw/, email-monitor/, notification-hub/, integrations/ compiles cleanly: `python3 -m py_compile <file>`. If any fail, reset that file to origin/main and log it.
3. After pull: if docker-compose.yml changed, automatically run `docker compose up -d` to pick up new service definitions.
4. Add a `--verify` flag that runs the smoke test after pulling.

Test: Run the script and verify it completes cleanly:
bash scripts/pull.sh --verify


TASK 6: DROPBOX ORGANIZER FIX
-------------------------------
Problem: The Dropbox organizer LaunchAgent was installed on Apr 8 but failed with "Input/output error" on launchctl load. It's supposed to watch for new files in ~/Dropbox root and auto-move them into the correct project's Client/ folder.

Current state:
- scripts/com.symphonysh.dropbox-organizer.plist — exists but broken python path
- The plist needs to use /opt/homebrew/bin/python3 (not /usr/bin/python3)
- Bob's Dropbox is at ~/Dropbox/ (confirmed)

What to fix:
1. Read the current plist and fix the python path to /opt/homebrew/bin/python3
2. Read/write the organizer Python script (referenced in the plist). It should:
   - Watch ~/Dropbox/ root for new PDF files
   - Match them to projects by name (e.g., "Topletz" → Topletz/Client/)
   - Archive old versions with timestamp before replacing
   - Log actions to /tmp/dropbox-organizer.log
3. Make sure the plist uses StandardOutPath and StandardErrorPath pointing to /tmp/dropbox-organizer.log
4. Provide the one-liner to load it:
   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphonysh.dropbox-organizer.plist 2>/dev/null; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.symphonysh.dropbox-organizer.plist

Test: Drop a test PDF in ~/Dropbox/ root and verify it gets moved.


COMMIT STRATEGY:
Commit after each task with a descriptive message. Do NOT squash into one commit.
Final verification: `docker ps` should show all containers healthy.
