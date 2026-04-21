You are working on AI-Server on Bob.

Goal
Bring the AI-Server stack back to a known-good state on Bob, with x-intake running, the realized-change watcher and x-intake listener watchdog in place, and a clear health report written to ops/verification so Matt can see if X links and autonomy are actually working right now.

Rules
- No heredocs
- No inline interpreters
- No docker logs -f, docker compose logs -f, tail -f, watch
- No interactive editors
- Keep scope limited to AI-Server on Bob
- Prefer bounded diagnostics and small, safe changes
- Do not touch private keys, secrets, or funding; assume creds and funding are unchanged
- Do not invent new services; use existing patterns from STATUSREPORT and prior Z-series work

Steps

1. Sync and basic repo sanity
   - cd ~/AI-Server
   - bash scripts/pull.sh
   - git status
   - Record in your notes whether there are uncommitted changes.

2. Rebuild and restart x-intake cleanly
   - Inspect docker-compose.yml and any docker-compose.*.yml to locate the x-intake service definition.
   - Note the image/build, environment (LAB_MODE, TZ, Redis URL, etc.), and volume mounts (data/x_intake/queue.db, data/transcripts, data/bookmarks).
   - Run:
     - docker compose build x-intake
     - docker compose up -d x-intake
   - Then run:
     - docker compose ps x-intake
     - docker compose logs --tail=80 x-intake
   - Confirm from logs that:
     - the Redis listener starts without fatal errors
     - queue DB mounts succeed
     - the HTTP health endpoint on :8101 reports healthy.
   - Do not use -f anywhere.

3. Implement or confirm x-intake listener watchdog (Z14)
   - Using STATUSREPORT.md and existing Z14 notes as reference, locate the x-intake listener code (the Redis subscription that listens on events:imessage and enqueues into queue.db).
   - Implement a lightweight watchdog in the existing x-intake process, following these constraints:
     - Store the listener Task or handle when you start the Redis subscription.
     - Add a periodic check (for example every 10–20 seconds) that:
       - verifies the task is still running,
       - restarts it if it has crashed,
       - logs a bounded message when a restart happens.
     - Do not introduce nested asyncio.new_event_loop calls inside the listener path; call async functions directly from the existing event loop.
     - Keep the watchdog logic small and local to the x-intake service.
   - Rebuild and restart x-intake again:
     - docker compose build x-intake
     - docker compose up -d x-intake
   - Verify with bounded logs:
     - docker compose logs --tail=80 x-intake
   - Confirm the watchdog is visible in logs when you simulate or detect a listener restart.

4. Realized-change watcher under launchd
   - Using existing launchd plists in the repo and STATUSREPORT, locate the plist for the realized-change watcher on Bob (name will be like com.symphony.realized-change-watcher or similar).
   - From the plist and scripts, determine:
     - which user / domain it should run under (gui/$(id -u) vs system),
     - what command it executes (likely a Python or shell script inside AI-Server),
     - where logs go.
   - Fix the launchd domain and bootstrap so that the watcher actually runs, using the same pattern you already use for the iMessage bridge LaunchAgent. For example:
     - unload any broken system-domain registration,
     - load it correctly as a user agent,
     - start it via launchctl kickstart.
   - Verify with bounded commands:
     - launchctl list | grep realized
     - ps aux | grep realized-change | head
   - Do not change the watcher’s core logic; just make sure it is loaded and running.

5. X-intake lane live check
   - With x-intake and the watcher up, perform a bounded end-to-end check on Bob:
     - Identify from STATUSREPORT.md and docs which iMessage account / lane should trigger x-intake.
     - From the host (not inside Docker), send yourself a single test X link via that lane.
     - Wait a short, fixed time (for example 60–120 seconds).
   - Collect evidence without streaming logs:
     - ls -l data/x_intake/queue.db
     - sqlite3 data/x_intake/queue.db "select count(*) from queue;"
     - tail -80 /tmp/imessage-bridge.log
     - docker compose logs --tail=80 x-intake
   - Summarize in your notes whether:
     - the bridge saw the message and logged the X link,
     - x-intake enqueued anything into queue.db,
     - x-intake attempted analysis without fatal errors,
     - any obvious error paths were hit.

6. User-facing visibility for X intake (minimal)
   - Without building a large UI, add a very small, existing-pattern diagnostic surface for the X lane, choosing one of:
     - a minimal CLI script (for example ops/tools/x_intake_recent.py) that prints the N most recent queue entries and their status; or
     - a single, simple HTTP endpoint on an existing internal service that returns a JSON snapshot of:
       - last N X items seen,
       - their timestamps,
       - their queue / processing status.
   - Use existing patterns for logging and HTTP within AI-Server; do not introduce new frameworks.
   - Ensure the surface is read-only and does not modify the queue.

7. Health report in ops/verification
   - Create a new verification file in ops/verification with a timestamped name such as:
     - ops/verification/YYYYMMDD-HHMMSS-x-intake-and-autonomy-lane-health.txt
   - In that file, write a concise report that includes:
     - Git commit hash on Bob for AI-Server.
     - docker compose ps snapshot for x-intake and any directly related services (Redis, bridge proxy if applicable).
     - Launchd status line for the realized-change watcher.
     - Evidence for the last X-link test (bridge log snippet, queue.db count before/after, x-intake log summary).
     - Whether the x-intake listener watchdog is implemented and observed in logs.
     - Whether the minimal X-intake visibility surface works (CLI or endpoint).
     - A short classification: IN PLACE, PARTIAL, or BROKEN for:
       - x-intake ingestion
       - x-intake durability
       - realized-change watcher runtime
       - user-facing visibility for X intake.

8. STATUSREPORT update
   - Open STATUSREPORT.md using non-interactive tools and update or add a short section summarizing:
     - the x-intake rebuild and watchdog,
     - the current state of the realized-change watcher,
     - how to quickly check X-intake health (which CLI or endpoint, and the new ops/verification file name).
   - Keep the edit minimal and factual; do not rewrite the entire report.

9. Commit and push
   - If you modified code or STATUSREPORT.md, run:
     - git status
     - git add .
     - git commit -m "Harden x-intake and realized-change watcher on Bob; add lane health report"
     - git push

Output
- x-intake rebuilt and running on Bob with a simple listener watchdog in place
- realized-change watcher actually loaded and running under launchd
- a minimal, working way to see recent X-intake items and their status
- a new ops/verification/*-x-intake-and-autonomy-lane-health.txt report describing evidence
- STATUSREPORT.md updated with the current state and a quick “how to check” note
