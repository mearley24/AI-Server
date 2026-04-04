# Activate Operations — Fix Briefing, Auto-Create Jobs, Wire Follow-ups

## Context
OpenClaw orchestrator runs every 5 minutes. D-Tools sync sees 100 opportunities (many "Won") but creates ZERO jobs because it only logs "no active job" and moves on. The jobs DB is empty, which means follow-up tracker, payment tracker, and proposal checker are all dead — they depend on jobs existing.

The daily briefing script fails because: (1) wrong email DB path, (2) it runs via macOS crontab outside Docker so it can't reach the container DB.

## Task 1: Auto-Create Jobs from D-Tools Won Opportunities

Edit `openclaw/dtools_sync.py`. At the block around line 150 where it currently logs "no active job", add logic to auto-create jobs for Won opportunities:

```python
# CURRENT (around line 150):
# No existing job match — log for pipeline visibility
logger.info("D-Tools pipeline: %s — %s (%s, $%.0f) — no active job", ...)
stats["pipeline_logged"] = stats.get("pipeline_logged", 0) + 1

# CHANGE TO:
# Auto-create job for Won opportunities
if opp.get("status") == "Won" and self._job_mgr:
    job_data = {
        "title": f"{client_name} — {project_name}",
        "client_name": client_name,
        "source": "dtools",
        "source_id": str(opp.get("id", "")),
        "status": "active",
        "value": opp.get("amount", 0),
        "address": project_name,
        "created_at": datetime.now().isoformat(),
    }
    try:
        job_id = self._job_mgr.create_job(job_data)
        logger.info("Auto-created job %s from D-Tools Won opp: %s — %s ($%.0f)",
                     job_id, client_name, project_name, opp.get("amount", 0))
        stats["jobs_created"] = stats.get("jobs_created", 0) + 1
    except Exception as e:
        logger.warning("Failed to auto-create job: %s", e)
else:
    logger.info("D-Tools pipeline: %s — %s (%s, $%.0f) — no active job",
                client_name, project_name, opp.get("status", ""), opp.get("amount", 0))
    stats["pipeline_logged"] = stats.get("pipeline_logged", 0) + 1
```

Also handle "On Hold" opportunities — create jobs with status "on_hold" so they show up in follow-ups.

Check the `JobLifecycleManager.create_job()` method in `openclaw/job_lifecycle.py` to confirm the correct method signature and required fields. Add `from datetime import datetime` import if not already present.

Prevent duplicates: before creating, check if a job with the same `source_id` already exists. The job lifecycle manager probably has a lookup method, or query the DB directly.

## Task 2: Fix Daily Briefing

Edit `openclaw/daily_briefing.py`:

1. Fix the email DB path. The DB is at `/Users/bob/AI-Server/data/email-monitor/emails.db` (when run from macOS crontab) or `/app/data/email-monitor/emails.db` (inside Docker). Update the default:
```python
EMAIL_DB_PATH = os.environ.get("EMAIL_DB_PATH", "/Users/bob/AI-Server/data/email-monitor/emails.db")
```

2. The `OWNER_PHONE_NUMBER` is set in `.env` but crontab doesn't load .env. Fix the crontab entry to source .env first. Update the crontab line to:
```
0 12 * * * cd /Users/bob/AI-Server && set -a && source .env && set +a && /opt/homebrew/bin/python3 openclaw/daily_briefing.py >> /tmp/briefing.log 2>&1
```
Note: `0 12 * * *` = 12:00 UTC = 6:00 AM MDT (Mountain Daylight Time, UTC-6).

Print the new crontab command for the user to install manually, don't try to edit crontab programmatically.

3. Make sure the briefing script can also read from the Docker-internal email DB if run inside a container. Add path fallback logic:
```python
def find_email_db():
    paths = [
        os.environ.get("EMAIL_DB_PATH", ""),
        "/Users/bob/AI-Server/data/email-monitor/emails.db",
        "/app/data/email-monitor/emails.db",
        "/data/emails.db",
    ]
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None
```

4. Check that the Twilio/iMessage sending logic works. The notification should go through the notification-hub service or directly via Twilio. Verify by looking at how the briefing sends messages and ensure it can reach the notification endpoint from outside Docker (`http://localhost:8095`).

## Task 3: Wire Follow-Up Tracker into Orchestrator

Check `openclaw/follow_up_tracker.py` — verify it's being called from the orchestrator tick. If not, add it.

In `openclaw/orchestrator.py`, the tick should call something like:
```python
await self.check_followups()
```

If that method doesn't exist, add it:
```python
async def check_followups(self):
    """Check for pending follow-ups and send reminders."""
    if not self._job_mgr:
        return
    try:
        from follow_up_tracker import FollowUpTracker
        tracker = FollowUpTracker(self._job_mgr, self.http)
        await tracker.check_and_send()
    except Exception as e:
        logger.warning("Follow-up check failed: %s", e)
```

Also check `payment_tracker.py` and `proposal_checker.py` — if they have similar check methods, wire them in too.

## Task 4: Emit Events to Mission Control

The orchestrator does work but Mission Control never sees it because nothing POSTs to the event server. Add a helper method to the orchestrator:

```python
async def emit_event(self, employee: str, event_type: str, title: str, details: dict = None):
    """Post event to Mission Control for dashboard visibility."""
    try:
        await self.http.post("http://mission-control:8098/event", json={
            "employee": employee,
            "event_type": event_type,
            "title": title,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })
    except Exception:
        pass  # Non-critical — don't break orchestrator if MC is down
```

Then sprinkle `await self.emit_event(...)` calls in key places:
- After processing new emails: `emit_event("bob", "email", f"Processed {count} new emails")`
- After D-Tools sync: `emit_event("bob", "dtools", f"Synced {stats['jobs_created']} new jobs")`
- After sending briefing: `emit_event("bob", "briefing", "Daily briefing sent")`
- After follow-up reminders: `emit_event("bob", "followup", f"Sent {count} follow-up reminders")`
- On health check failures: `emit_event("bob", "alert", f"{service} is down")`
- On trading alerts: `emit_event("bob", "trading", msg)`

## Verification

After making changes, rebuild OpenClaw:
```bash
docker compose build --no-cache openclaw && docker compose up -d openclaw
```

Then check:
```bash
sleep 30 && docker logs openclaw 2>&1 | tail -30
```

Look for:
- "Auto-created job" log lines (jobs being created from Won opps)
- No import errors or crashes
- Events being posted to mission-control

Also update the crontab for the briefing fix and print the command.
