# Prompt T — Drain Pending Approvals Backlog

Read CLAUDE.md first. The STATUS_REPORT.md (in repo root) identified 103 pending approvals in decision_journal.db as a P0 issue.

## PROBLEM

`data/openclaw/decision_journal.db` has 103 rows in `pending_approvals` that are waiting on Matt. Many are likely stale. This backlog means the approval system is broken — Matt can't realistically review 103 items one by one via iMessage.

## TASK

### Step 1: Analyze the backlog

```zsh
sqlite3 data/openclaw/decision_journal.db "SELECT COUNT(*), decision_type FROM pending_approvals GROUP BY decision_type ORDER BY COUNT(*) DESC;"
sqlite3 data/openclaw/decision_journal.db "SELECT MIN(created_at), MAX(created_at) FROM pending_approvals;"
sqlite3 data/openclaw/decision_journal.db "SELECT decision_type, context, created_at FROM pending_approvals ORDER BY created_at ASC LIMIT 10;"
```

Understand what types of approvals are piling up and how old they are.

### Step 2: Build auto-expiry logic

Create `openclaw/approval_drain.py`:

1. Load all pending approvals from the DB.
2. Any approval older than 7 days gets auto-expired:
   - Set status to `expired`
   - Set outcome to `auto_expired_stale`
   - Log the expiry to Cortex: POST to `http://cortex:8102/remember` with category="system", title="Auto-expired stale approval", content=details
3. Group remaining (non-expired) approvals by `decision_type`.
4. For each group, build a summary: "{count} {type} approvals pending — oldest from {date}. Examples: {first 2 titles}."
5. Combine all group summaries into one message under 1500 characters.
6. Publish the summary to Redis channel `notifications:approval_digest`:
   ```python
   r.publish("notifications:approval_digest", json.dumps({
       "type": "approval_digest",
       "summary": combined_summary,
       "total_pending": remaining_count,
       "total_expired": expired_count,
       "groups": group_data
   }))
   ```
7. Print the summary to stdout so we can see it in this session.

### Step 3: Add recurring drain to orchestrator

In `openclaw/orchestrator.py`, add a daily check (run once per day at the 6 AM tick, same as daily briefing):

```python
from approval_drain import drain_stale_approvals

# Inside the tick loop, after daily briefing
if should_run_daily():
    expired = await drain_stale_approvals()
    if expired > 0:
        logger.info("approval_drain", expired=expired)
```

### Step 4: Add approval threshold alert

If pending approvals exceed 20 at any point, publish an alert to `notifications:high_priority`:
```python
if remaining_count > 20:
    r.publish("notifications:high_priority", json.dumps({
        "type": "approval_backlog_alert",
        "message": f"Approval backlog at {remaining_count} items. Review needed.",
        "count": remaining_count
    }))
```

### Step 5: Run it now

```zsh
docker restart openclaw
sleep 10
docker exec openclaw python -c "from approval_drain import drain_stale_approvals; import asyncio; result = asyncio.run(drain_stale_approvals()); print(result)"
```

Report: how many expired, how many remain, what types are left.

### Verification

```zsh
sqlite3 data/openclaw/decision_journal.db "SELECT status, COUNT(*) FROM pending_approvals GROUP BY status;"
curl -s http://127.0.0.1:8102/health | python3 -m json.tool
```

Cortex memory count should have increased (new entries from the drain).

Commit and push:
```zsh
git add -A
git commit -m "Add approval drain — auto-expire stale, daily cleanup, threshold alerts"
git push origin main
```
