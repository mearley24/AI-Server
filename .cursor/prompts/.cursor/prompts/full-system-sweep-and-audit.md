You are working on AI-Server on Bob.

Goal
Perform a full-system sweep of AI-Server (and symphonysh if referenced), compare the current live state to what STATUSREPORT.md claims, update the audit so it is up to date (IN PLACE / PARTIAL / MISSING / NEXT 5 ITEMS), and write a separate verification file in ops/verification that clearly lists what is still missing or fragile.

Rules
- No heredocs
- No inline interpreters
- No docker logs -f, docker compose logs -f, tail -f, watch
- No interactive editors
- Operate only on Bob, against the local AI-Server repo (and symphonysh only if STATUSREPORT.md references it)
- Prefer bounded diagnostics and small, safe edits
- Do not touch secrets, API keys, or wallet funding
- Do not introduce new services; reason from what already exists
- Keep STATUSREPORT.md edits minimal and factual, not a rewrite

High-level questions to answer
1. Which systems and workflows are actually IN PLACE vs PARTIAL vs MISSING today?
2. Where does the current runtime differ from STATUSREPORT.md?
3. What are the top 5 gaps that should be worked next?

Areas to include (at minimum)
- X intake (iMessage → Redis → x-intake → analysis → visibility)
- Transcript pipeline (storage, analysis, integration into memory/insight)
- Dashboard and operational visibility (queues, errors, background jobs)
- Background automation (task runner, autonomy sweep, realized-change watcher)
- Trading / Polymarket bot and redeemer visibility
- Email / calendar / follow-up classification pipeline
- Deployment / verification discipline (how you know a deploy is actually live)
- Monitoring / governance (logs, audit trail, thresholds, review queues)
- symphonysh state (if STATUSREPORT.md still tracks it)

Steps

1. Sync and snapshot
   - cd ~/AI-Server
   - bash scripts/pull.sh
   - git status
   - Record in your own notes whether there are local changes.
   - Capture a bounded runtime snapshot:
     - docker compose ps
     - launchctl list | grep symphony | head
     - ls ops/verification | tail -20

2. Read existing STATUSREPORT audit
   - Open STATUSREPORT.md in a non-interactive way and locate:
     - the previous systems audit section with IN PLACE / PARTIAL / MISSING
     - the current “NEXT 5 ITEMS” list
   - Summarize what the existing audit thinks is:
     - IN PLACE
     - PARTIAL
     - MISSING
   - Do not change anything yet; just understand the prior baseline.

3. Runtime verification per area (bounded)
   For each area listed under “Areas to include”, perform bounded checks that confirm whether the previous status is still accurate.

   Examples (adapt as needed, but keep each bounded):
   - X intake:
     - docker compose ps x-intake
     - docker compose logs --tail=60 x-intake
     - ls -l data/x_intake/queue.db || true
   - Transcript pipeline:
     - search for transcript / transcription storage locations
     - locate the service(s) that read and analyze transcripts
     - look for recent logs or artifacts (files, DB writes)
   - Dashboard / ops visibility:
     - identify which dashboards or scripts show queue / error state
     - confirm they still run and reflect reality
   - Background automation:
     - docker compose ps for task runner, schedulers, bots
     - launchctl list for any AI-Server launch agents (realized-change watcher, imessage bridge, etc.)
   - Trading / Polymarket:
     - docker compose ps polymarket-bot (or equivalent)
     - docker compose logs --tail=80 polymarket-bot
   - Email / calendar:
     - locate email-monitor, calendar, follow-up services
     - inspect bounded logs to confirm classification is actually happening
   - Deployment / verification:
     - scan ops/verification for the most recent entries by topic
     - check that recent code changes have corresponding verification files

   As you go, write your findings into a temporary in-memory summary grouped by area.

4. Derive IN PLACE / PARTIAL / MISSING now
   - For each area, decide:
     - IN PLACE if:
       - the code exists,
       - the service runs,
       - there is concrete evidence of recent, correct behavior,
       - and there is at least minimal observability.
     - PARTIAL if:
       - the code or service exists and sometimes runs,
       - or observability is weak,
       - or critical pieces like return paths, watchdogs, or approval flows are missing.
     - MISSING if:
       - the capability is not implemented,
       - or the service is dead and has no current owner / path to repair.
   - Capture 1–3 sentences of evidence for each classification, referencing:
     - runtime checks,
     - STATUSREPORT.md contents,
     - ops/verification artifacts.

5. Compute the new “NEXT 5 ITEMS”
   - From all PARTIAL and MISSING items, choose the 5 highest-leverage gaps.
   - Each item should be phrased as:
     - “Do X so that Y is reliably true.”
   - Examples:
     - “Add a durable x-intake listener watchdog so ingestion doesn’t die silently.”
     - “Wire transcripts into the memory/insight pipeline so they produce usable outputs, not just storage.”
     - “Add a small ‘recent X links’ surface so Bob can see what was ingested.”
   - These should be concrete enough to become their own future Cline prompts.

6. Update STATUSREPORT.md
   - Update or add a single “Systems Audit (YYYY-MM-DD)” section in STATUSREPORT.md that includes:
     - a table or bullet list per area with IN PLACE / PARTIAL / MISSING and a one-line justification,
     - the refreshed “NEXT 5 ITEMS” list.
   - Do not rewrite old historical sections; just add the new audit block or clearly mark the previous one as superseded by the new date.

7. Write a verification file in ops/verification
   - Create a new file:
     - ops/verification/YYYYMMDD-HHMMSS-full-system-sweep-and-audit.txt
   - In that file, include:
     - the current Git commit hash for AI-Server on Bob
     - the docker compose ps snapshot you used
     - a copy of the IN PLACE / PARTIAL / MISSING per area
     - the new NEXT 5 ITEMS list
     - any notable discrepancies between what STATUSREPORT.md used to say and what is actually true now
   - Keep it concise but explicit; this file is the artifact Matt and other agents can read later without re-running the audit.

8. Commit and push
   - If STATUSREPORT.md or other repo files changed, run:
     - git status
     - git add STATUSREPORT.md ops/verification/YYYYMMDD-HHMMSS-full-system-sweep-and-audit.txt
     - git commit -m "Full system sweep and audit; refresh IN PLACE/PARTIAL/MISSING and NEXT 5 items"
     - git push

Output
- STATUSREPORT.md has a new, dated Systems Audit section that reflects the current reality (IN PLACE / PARTIAL / MISSING) across all major systems, plus an updated NEXT 5 ITEMS list.
- ops/verification/*-full-system-sweep-and-audit.txt contains the evidence and decisions for this sweep.
- Any obvious discrepancies between prior audit claims and current runtime are documented.
- The repo is pushed so Bert and future agents can pull the updated audit without pasting logs.