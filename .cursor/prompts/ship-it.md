# Ship It — Final Pass: Verify, Polish, Harden

## Context
Two status documents describe what's done vs remaining:
- `.cursor/prompts/perplexity-computer-ai-server-status.md` — the authoritative status
- `.cursor/prompts/final-wiring-gaps.md` — original gap list (now mostly implemented)

**Gaps 1-7 from final-wiring-gaps are implemented.** This prompt handles everything that's left: verification, Mission Control polish, operational hardening, and end-to-end testing.

**Read each file referenced below before editing. Do not re-implement anything that already works.**

---

## PHASE 1: Verify What Shipped (run first, fix any failures)

### 1a. Orchestrator Tick Verification
Read `openclaw/orchestrator.py`. Confirm these methods exist AND are called in the tick:
- `check_emails()`
- `check_followups()`
- `check_payments()`
- `check_calendar()`
- `check_pipeline()` or `check_trading()`
- `sync_dtools()`
- `check_health()`
- `check_silent_services()`
- `scan_knowledge()`
- `consolidate_memories()`
- `maybe_send_briefing()`

If any method exists but isn't called in the tick, add it. If any is missing entirely, note it but don't build from scratch — just add a stub that logs a warning.

### 1b. Event Bus Verification
Confirm `openclaw/event_bus.py` has `publish_and_log()` and that the orchestrator calls it (via `self._redis_publish` or `self._publish` or direct calls). Count the publish calls in orchestrator — should be 8+. If fewer than 6, add missing emissions at:
- After `check_emails` completes
- After `sync_dtools` completes  
- After `check_health` completes
- After `check_calendar` completes
- After follow-up or payment events fire

### 1c. Outcome Listener Running
Check `openclaw/main.py` — confirm `OutcomeListener` is imported and started as a background task in the lifespan/startup. If not, add it:
```python
from outcome_listener import OutcomeListener
# In startup:
listener = OutcomeListener(journal, redis_url)
asyncio.create_task(listener.run())
```

### 1d. Approval Bridge
Check that `scripts/imessage-server.py` has `try_approval_reply()` and that it's called when messages arrive. Check that `POST /internal/approval` exists in `openclaw/main.py`. If the route exists but returns 404 in practice, check the path prefix and FastAPI router mounting.

### 1e. D-Tools Job Creation
Read `openclaw/dtools_sync.py` — confirm it has auto-create logic for Won/On Hold opps with duplicate checking via `get_job_by_dtools_id()` or similar. The jobs DB (`DATA_DIR/jobs.db`) should have a `jobs` table with `d_tools_id` or `source_id` column.

---

## PHASE 2: Mission Control Polish

### 2a. Settings View
Edit `mission_control/static/index.html` — find the Settings view (likely `#view-settings` or similar). Replace placeholder content with:

```html
<h3>Service Ports</h3>
<table>
  <tr><td>Mission Control</td><td>:8098</td></tr>
  <tr><td>OpenClaw</td><td>:8099 (internal :3000)</td></tr>
  <tr><td>Email Monitor</td><td>:8092</td></tr>
  <tr><td>Calendar Agent</td><td>:8094</td></tr>
  <tr><td>Notification Hub</td><td>:8095</td></tr>
  <tr><td>D-Tools Bridge</td><td>:8091</td></tr>
  <tr><td>Polymarket Bot</td><td>:8430 (via vpn)</td></tr>
  <tr><td>Redis</td><td>:6379</td></tr>
  <tr><td>Open WebUI</td><td>:3000</td></tr>
  <tr><td>Context Preprocessor</td><td>:8028</td></tr>
</table>

<h3>Quick Links</h3>
<ul>
  <li><a href="/api/services">Service Health API</a></li>
  <li><a href="/api/intelligence">Intelligence Summary</a></li>
  <li><a href="/api/decisions/recent">Recent Decisions</a></li>
  <li><a href="/events">Event Log</a></li>
  <li><a href="/digest">Daily Digest</a></li>
  <li><a href="/status">System Status</a></li>
</ul>

<h3>Configuration</h3>
<p>Timezone: America/Denver (MDT)</p>
<p>Orchestrator tick: 5 minutes</p>
<p>Auto-responder: <span id="autoResponderStatus">checking...</span></p>
```

Fetch `/status` to populate the auto-responder status dynamically.

Style: same dark theme, use existing CSS classes from the dashboard.

### 2b. Digest Modal — Markdown Rendering
Add `marked.min.js` from CDN:
```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

In the digest modal render function, replace `textContent` with:
```javascript
digestContent.innerHTML = marked.parse(text);
```

Add basic styling for rendered markdown (headers, lists, code blocks) inside the modal:
```css
.digest-content h1, .digest-content h2, .digest-content h3 { margin-top: 12px; }
.digest-content ul, .digest-content ol { padding-left: 20px; }
.digest-content code { font-family: var(--mono); background: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 3px; }
.digest-content pre { background: rgba(255,255,255,0.04); padding: 10px; border-radius: 6px; overflow-x: auto; }
```

### 2c. Trading View — Mobile + Offline
In the trading nav view (`loadTradingView` or similar):

**Mobile:** Wrap position tables in a horizontal scroll container:
```css
.trading-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
```

**Offline banner:** When the bot fetch fails, show a banner instead of breaking:
```javascript
try {
    const resp = await fetch('/api/trading/bot-status');
    if (!resp.ok) throw new Error('Bot unreachable');
    // ... render data
} catch(e) {
    container.innerHTML = `
        <div class="offline-banner">Trading bot offline — showing last cached data</div>
        ${cachedHTML || '<div class="empty">No cached data available</div>'}
    `;
}
```

Cache the last successful trading response in `localStorage` so there's always something to show.

### 2d. Expanded Tile Details
Check each tile's expanded view against the spec in `mission-control-final.md` §6:
- **Services expanded**: verify `checked_at` / last check time appears if the API returns it
- **System expanded**: show container uptime from the `/api/system` response if available
- **Email expanded**: show full subject lines (not truncated) when expanded
- **Calendar expanded**: show full event descriptions when expanded

Only add what the API already returns — don't modify the API just for expanded views.

---

## PHASE 3: Operational Hardening

### 3a. Backup Cron
`scripts/backup-data.sh` exists (26 lines). Verify it backs up the right DBs. Print the crontab line for the user to install:
```
echo ""
echo "=== INSTALL BACKUP CRON ==="
echo "Run this on the host (not in Docker):"
echo "  crontab -e"
echo "  Add this line:"
echo "  0 4 * * * /Users/bob/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1"
echo ""
```

### 3b. Polymarket Bot → events:log
The bot PUBLISHes to Redis channels but doesn't write to `events:log` (the durable audit list). Two options:

**Option A (preferred, no bot changes):** Add a Redis subscriber in OpenClaw that listens to bot channels and copies to `events:log`:
```python
# In outcome_listener.py or a new background task:
# Subscribe to any channel the bot publishes on
# On each message, LPUSH to events:log
```

**Option B:** Add `events:log` LPUSH in the bot's notification code. This requires editing `polymarket-bot/` which is riskier.

Go with Option A — add the subscription in OpenClaw's outcome_listener.

### 3c. Approval Side Effects
Currently, approving a decision via iMessage just logs it. Wire actual execution:

Read `openclaw/approval_bridge.py` (25 lines) — it has a `_resolve` handler pattern. Check if the orchestrator registers a handler via `set_resolve_handler()`. If not, add in orchestrator `__init__`:

```python
from approval_bridge import set_resolve_handler
set_resolve_handler(self._execute_approved_action)
```

Then implement `_execute_approved_action()`:
```python
async def _execute_approved_action(self, decision_id: int, granted: bool, edit_note: str):
    decision = self._journal.get_by_id(decision_id)
    if not decision:
        return
    if granted:
        # Check decision category and execute
        if decision.category == "followup" and "draft" in decision.action:
            # Send the follow-up email
            pass  # Look at the decision context for the email draft
        elif decision.category == "email" and "draft" in decision.action:
            # Send the email draft
            pass
        self._journal.update_outcome(decision_id, "approved_and_executed", 1.0)
    else:
        self._journal.update_outcome(decision_id, "rejected_by_owner", 0.0)
```

Start simple — just log + score. Actual email sending can come later. The important thing is the approval flow is end-to-end.

---

## PHASE 4: End-to-End Smoke Test

**Preferred:** run the maintained script from the repo root (uses log strings that match `openclaw/orchestrator.py`, jobs path fallback, and tolerates empty grep results):

```bash
chmod +x scripts/smoke-test.sh   # once
./scripts/smoke-test.sh
```

Rebuild first when you have code changes:

```bash
SMOKE_REBUILD=1 SMOKE_SLEEP=90 ./scripts/smoke-test.sh
```

**What changed vs the old inline block:** (1) Orchestrator grep targets real lines such as `Orchestrator tick at`, `Trading check completed`, `D-Tools sync: N created`, not `tick_complete` / `check_emails` (those substrings do not appear in logs). (2) Jobs DB tries `/app/data/jobs.db` then `/app/data/openclaw/jobs.db`. (3) Silent check looks for `silent_service` (the warning line); empty output is OK when every heartbeat source is healthy. (4) “Errors” grep is narrowed to reduce noise; empty is good.

Print the results. If any section looks wrong, note the fix needed.
