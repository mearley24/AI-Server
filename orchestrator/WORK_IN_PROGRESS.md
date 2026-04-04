# Work In Progress

## Current State
Last session: 2026-04-04

## Active
- Orchestrator ticking every 5 min with full event bus
- Follow-up + payment trackers wired into tick
- D-Tools auto-job creation for Won / On Hold opportunities
- Decision journal logging + outcome listener running
- Mission Control: sidebar, digest markdown, settings, core/optional badges
- D-Tools Bridge health: liveness-only `/health`, deep check via `/snapshot`
- Weekly learning wired into pattern engine Sunday tick
- Continuous learning script mines decision journal + cost tracker

## Needs Verification on Host
- Follow-up / payment DBs populating with real data
- D-Tools "Won" string matching actual API responses
- Redis `events:log` filling over time
- Backup cron installed (`0 4 * * * ~/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1`)
- `knowledge/cortex/learnings.md` growing after Sunday learning runs

## Queued
- Enable `AUTO_RESPONDER_ENABLED` when ready for auto-drafted replies
- Approval execution (send email on grant, not just journal + notify)
- Polymarket → unified `events:log` LPUSH (currently PUBLISH only)
- Client scoring pipeline (`client_tracker.compute_scores()`)
- Relationship maintenance (14-day no-contact alerts)
