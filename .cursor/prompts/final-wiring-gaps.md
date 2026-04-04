# Final Wiring Gaps — Everything That's Built But Not Connected

## Context
The AI-Server has substantial code across 38 OpenClaw modules, 14 trading strategies, Mission Control dashboard, and extensive scripts. Cursor built most modules from prompts — but many aren't wired into the orchestrator tick or don't talk to each other. This prompt connects the last loose wires.

**Read each file before editing.** Many modules are real (300+ lines with working logic). The gap is always wiring — the orchestrator doesn't call them, or events don't flow through.

### Implementation status (2026-04)

| Gap | In code |
|-----|---------|
| **1–2** Follow-up + payment trackers | **`check_followups()`** / **`check_payments()`** on tick after emails; DBs under `DATA_DIR` (`follow_ups.db`, `payments.db`); Redis events `client.followup_alert`, `job.payment_received` |
| **3** D-Tools auto jobs | **`get_job_by_dtools_id`** + **`dtools_sync`** auto-create for Won / On Hold |
| **4** Daily briefing email DB | **`daily_briefing._find_email_db()`** + optional **dotenv** |
| **5** Redis persistence | **`redis/redis.conf`** + compose mount (already present) |
| **6** More orchestrator emissions | **`email.processed`**, **`calendar.checked`**, **`jobs.synced`**, **`health.checked`**, **`briefing.sent`** |
| **7** Outcome listener | Already started in **`main.py`** — more bus traffic from gap 6 |
| **8–9** Mission Control | Shipped: Settings, digest markdown (`marked`), trading cache/banner; optional Remediator/ClawWork excluded from core badge |
| **10** Auto-responder | Wired in **`check_emails()`** — set **`AUTO_RESPONDER_ENABLED=true`** for up to one **ACTIVE_CLIENT** Zoho draft per tick; startup logs status |

---

## GAP 1: Follow-Up Tracker Not Wired (P0 — real money)

`openclaw/follow_up_tracker.py` (205 lines) exists with full logic. The orchestrator NEVER calls it.

**Edit `openclaw/orchestrator.py`:**
Find where `check_emails`, `check_calendar`, `sync_dtools` etc are called in the tick. Add:

```python
async def check_followups(self):
    """Check for pending follow-ups and send reminders."""
    try:
        from follow_up_tracker import FollowUpTracker
        tracker = FollowUpTracker(self._job_mgr, self._http)
        results = await tracker.check_and_send()
        if results and results.get("sent", 0) > 0:
            self._publish("events:clients", {
                "type": "client.followup_sent",
                "employee": "bob",
                "title": f"Sent {results['sent']} follow-up(s)",
                "data": results
            })
    except Exception as e:
        logger.warning("check_followups failed: %s", e)
```

Look at `follow_up_tracker.py` to confirm the actual class name, constructor args, and method names. Adapt the code above to match what exists.

Add `await self.check_followups()` to the tick, after `check_emails()`.

## GAP 2: Payment Tracker Not Wired (P0 — real money)

`openclaw/payment_tracker.py` (224 lines) exists. The orchestrator NEVER calls it.

**Same pattern as above.** Add `check_payments()` method and call it in the tick:

```python
async def check_payments(self):
    try:
        from payment_tracker import PaymentTracker
        tracker = PaymentTracker(self._job_mgr)
        results = await tracker.check_pending()
        if results and results.get("received", 0) > 0:
            self._publish("events:jobs", {
                "type": "job.payment_received",
                "employee": "bob",
                "title": f"Payment received: {results.get('details', '')}",
                "data": results
            })
    except Exception as e:
        logger.warning("check_payments failed: %s", e)
```

Read `payment_tracker.py` first for actual method signatures.

## GAP 3: D-Tools Auto-Create Jobs from Won Opportunities (P0)

`openclaw/dtools_sync.py` (245 lines) scans D-Tools but creates ZERO jobs. Line ~150 just logs "no active job" and moves on.

**Edit `openclaw/dtools_sync.py`:**
After the "no active job" log line, add auto-creation for Won/On Hold opportunities:

```python
if opp.get("status") in ("Won", "On Hold") and self._job_mgr:
    # Check for duplicate first
    existing = self._job_mgr.find_by_source_id(str(opp.get("id", "")))
    if not existing:
        job_data = {
            "title": f"{client_name} — {project_name}",
            "client_name": client_name,
            "source": "dtools",
            "source_id": str(opp.get("id", "")),
            "status": "active" if opp.get("status") == "Won" else "on_hold",
            "value": opp.get("amount", 0),
            "address": project_name,
        }
        try:
            job_id = self._job_mgr.create_job(job_data)
            stats["jobs_created"] += 1
        except Exception as e:
            logger.warning("Auto-create job failed: %s", e)
```

Read `job_lifecycle.py` to confirm `create_job()` and `find_by_source_id()` exist. If `find_by_source_id` doesn't exist, add it (simple SELECT by source_id).

## GAP 4: Daily Briefing Path Fix (P0)

`openclaw/daily_briefing.py` line 33 still has:
```python
EMAIL_DB_PATH = os.environ.get("EMAIL_DB_PATH", "/data/emails.db")
```

The actual DB is at `/app/data/email-monitor/emails.db` (inside Docker) or `/Users/bob/AI-Server/data/email-monitor/emails.db` (from crontab).

**Fix:** Replace with path fallback:
```python
def _find_email_db():
    for p in [
        os.environ.get("EMAIL_DB_PATH", ""),
        "/app/data/email-monitor/emails.db",
        "/Users/bob/AI-Server/data/email-monitor/emails.db",
        "/data/emails.db",
    ]:
        if p and os.path.exists(p):
            return p
    return None

EMAIL_DB_PATH = _find_email_db()
```

Also add `from dotenv import load_dotenv; load_dotenv()` at the top (for crontab runs that need .env).

Also ensure `OWNER_PHONE_NUMBER` is read with dotenv loaded.

## GAP 5: Redis Persistence Config (P1)

Docker compose already uses `redis-server /usr/local/etc/redis/redis.conf` but the file doesn't exist in the repo.

**Create `redis/redis.conf`:**
```
save 300 1
save 60 100
appendonly yes
appendfsync everysec
maxmemory 512mb
maxmemory-policy allkeys-lru
```

**Verify docker-compose.yml** mounts it:
```yaml
redis:
  volumes:
    - redis_data:/data
    - ./redis/redis.conf:/usr/local/etc/redis/redis.conf
```

If the volume mount isn't there, add it.

## GAP 6: More Event Emissions from Orchestrator (P1)

The orchestrator only has 4 `publish_and_log` calls. It should emit events at every meaningful decision point. Scan the tick methods and add:

- `check_emails()`: emit `events:email` / `email.processed` with count
- `sync_dtools()`: emit `events:jobs` / `jobs.synced` with stats (jobs_created, pipeline_logged)
- `check_health()`: emit `events:system` / `health.checked` with healthy/total counts
- `check_calendar()`: emit `events:calendar` / `calendar.checked` with event count
- `maybe_send_briefing()`: emit `events:system` / `briefing.sent`

Use the existing `self._publish()` helper or `publish_and_log()` from `event_bus.py`.

## GAP 7: Outcome Loop Has Few Triggers (P1)

`outcome_listener.py` (178 lines) exists and subscribes to Redis. But the orchestrator only has 2 `update_outcome` references. The listener needs the events to fire.

**The fix is in GAP 6** — once the orchestrator emits more events, the outcome listener will pick them up and score decisions. Verify `outcome_listener.py` is started as a background task in `openclaw/main.py`:

```python
# In main.py startup / lifespan:
from outcome_listener import OutcomeListener
listener = OutcomeListener(journal, redis_url)
asyncio.create_task(listener.run())
```

If it's not started, add it.

## GAP 8: Mission Control — Settings View & Digest (P2)

From the handoff document, these are still thin:

**Settings view:** Replace placeholder with useful info:
- Service ports table (from docker-compose)
- Links to: Mission Control repo, orchestrator logs, daily briefing log
- Current timezone display
- Redis connection status
- Last backup timestamp (read from backup log)

**Digest modal:** The `GET /digest` response comes as plain text. Either:
- Add a simple markdown→HTML renderer (use a 2KB library like `marked.min.js` from CDN)
- Or have the server return HTML instead of markdown

## GAP 9: Trading View Polish (P2)

The trading nav view (`loadTradingView()`) works but needs:
- Better table formatting for positions (sortable by value)
- Mobile-friendly tables (horizontal scroll)
- Error state when bot is unreachable (show last cached data + "Bot offline" banner)

## GAP 10: Auto-Responder (P2) — done (enable via env)

`openclaw/auto_responder.py` is called from **`orchestrator.check_emails()`** when **`AUTO_RESPONDER_ENABLED`** is `true` / `1` / `yes`. Only **`ACTIVE_CLIENT`** category is auto-drafted, **at most one per tick** (first matching new email). Startup logs whether auto-respond is on.

Future: vendor ack / bid triage can extend `auto_responder` or separate handlers; classification already feeds the decision journal.

---

## Verification

After all changes:
```bash
docker compose build --no-cache openclaw mission-control
docker compose up -d openclaw mission-control
sleep 60

echo "=== EVENTS FLOWING ==="
docker exec redis redis-cli LRANGE events:log 0 10

echo "=== ORCHESTRATOR ==="
docker logs openclaw 2>&1 | grep "followup\|payment\|jobs_created\|publish\|email.processed" | tail -15

echo "=== JOBS DB ==="
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/jobs.db')
for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
    c = conn.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
    print(f'{t[0]}: {c} rows')
"

echo "=== DECISION JOURNAL ==="
docker exec openclaw python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/decision_journal.db')
for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
    c = conn.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
    print(f'{t[0]}: {c} rows')
"

echo "=== REDIS PERSISTENCE ==="
docker exec redis redis-cli CONFIG GET appendonly
```

Expected after fix:
- `events:log` has entries from each tick (email, calendar, dtools, health, trading)
- Follow-up tracker runs and finds due follow-ups
- Payment tracker checks pending payments
- D-Tools Won opps create jobs (jobs DB no longer empty)
- Daily briefing finds the email DB
- Redis has AOF persistence
- Outcome listener is running and scoring decisions as events arrive
