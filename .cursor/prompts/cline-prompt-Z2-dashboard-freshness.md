# Cline Prompt Z2 — Dashboard Freshness Filters + Stale Data Cleanup

## Objective
The Cortex dashboard shows stale emails and follow-ups from months ago as current. Add freshness filters so only recent data appears, and flush the old data.

---

## Part 1: Flush Stale Data

Run these commands to reset the stale state:

```zsh
sqlite3 data/email-monitor/emails.db "UPDATE emails SET read = 1 WHERE read = 0"
sqlite3 data/openclaw/follow_ups.db "DELETE FROM follow_ups WHERE last_client_ts < datetime('now', '-30 days')"
```

## Part 2: Dashboard API Freshness Filters

### Fix 1: `/api/emails` — Only show recent unread emails

**File:** `cortex/dashboard.py`, function `api_emails()`

After fetching emails from email-monitor, filter to only emails from the last 7 days for the unread count. The dashboard should reflect what needs attention NOW, not historical inbox state.

Replace the unread counting logic:

```python
from datetime import datetime, timezone, timedelta

# ... inside api_emails after getting the emails list ...
seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
recent_emails = [
    e for e in emails
    if (e.get("received_at") or e.get("date") or "") >= seven_days_ago
]
unread = sum(
    1 for e in recent_emails if not e.get("read") and not e.get("processed")
)
return {"emails": recent_emails[:20], "unread_count": unread}
```

### Fix 2: `/api/followups` — Only count genuinely overdue items

**File:** `cortex/dashboard.py`, function `api_followups()`

The follow-ups tile should only show entries where:
- The client emailed in the last 30 days (not ancient entries)
- Matt genuinely hasn't replied (waiting_on_matt logic already fixed in Z)

After the existing overdue counting loop, add a recency filter:

```python
thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
recent_followups = [
    f for f in followups
    if (f.get("last_client_ts") or "") >= thirty_days_ago
]
# Re-count overdue from only recent entries
overdue = 0
for f in recent_followups:
    last_client = f.get("last_client_ts")
    last_matthew = f.get("last_matthew_ts")
    if not last_client:
        continue
    try:
        client_dt = datetime.fromisoformat(last_client)
        if client_dt.tzinfo is None:
            client_dt = client_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        continue
    waiting_on_matt = (not last_matthew) or (last_client > last_matthew)
    if waiting_on_matt and (now_utc - client_dt).total_seconds() >= 4 * 3600:
        overdue += 1

return {
    "followups": recent_followups[:20],
    "total": len(recent_followups),
    "overdue_count": overdue,
    "as_of": now_utc.isoformat(),
}
```

### Fix 3: Frontend — Show "as of" timestamp on email and follow-up tiles

**File:** `cortex/static/index.html`

In `renderEmails()`, add a small timestamp showing when the data is from:
```javascript
// After the unread count display, add:
const emailAge = data.as_of ? timeAgo(data.as_of) : '';
// Include: <div class="small">updated ${esc(emailAge)}</div>
```

Same for `renderFollowups()`.

---

## Testing

```zsh
docker compose restart cortex
```

Verify at `http://127.0.0.1:8102/dashboard`:
- Email tile should show 0 unread (or only genuinely new emails)
- Follow-ups should show 0 overdue (or only recent real ones)
- Both tiles should indicate freshness

Commit message: `fix(cortex): dashboard freshness filters — hide stale emails and follow-ups`
