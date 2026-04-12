# Cline Prompt Z — Cortex Dashboard Data Accuracy Fix

## Objective
Fix every tile in the Cortex dashboard (`cortex/dashboard.py` + `cortex/static/index.html`) so they all display correct, live data. The dashboard is served at `:8102/dashboard`.

---

## Diagnosed Issues (fix every one)

### 1. Follow-ups: Wrong Overdue Count
**File:** `cortex/dashboard.py`, function `api_followups()`

**Bug:** The overdue count checks `last_overdue_alert_ts IS NOT NULL`, which means "an alert was sent at some point" — not "this follow-up is currently overdue."

**Fix:** Use the same logic as `openclaw/follow_up_tracker.py::list_overdue()`:
- A follow-up is overdue when the client emailed, Matt has NOT replied (either `last_matthew_ts` is empty OR `last_client_ts > last_matthew_ts`), AND more than 4 hours have elapsed since `last_client_ts`.
- Replace the Python overdue counting loop with:
```python
now_utc = datetime.now(timezone.utc)
overdue = 0
for f in followups:
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
```
- Add `from datetime import timezone` to imports if not already present.

### 2. Decisions: Cortex Recall Returns All Memories, Not Decisions
**File:** `cortex/dashboard.py`, function `api_decisions_recent()`

**Bug:** `engine.memory.recall("", limit=limit)` returns the most recent memories of ANY category — not decisions. The "cortex decisions" list shows random memories.

**Fix:** Filter to only decision-related memories. Replace the recall call:
```python
cortex_decisions = engine.memory.recall(
    "", category="decision", limit=limit
)
```
If `recall()` does not support a `category` kwarg, use the decisions table directly:
```python
try:
    rows = engine.memory.conn.execute(
        "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    cortex_decisions = [dict(r) for r in rows]
except Exception:
    cortex_decisions = []
```

### 3. Email Path Discovery: Two Unnecessary 404s
**File:** `cortex/dashboard.py`, function `api_emails()`

**Bug:** Tries `/emails/recent` and `/api/emails` first — neither exists on the email-monitor service. This causes two 5-second timeout attempts before hitting the correct `/emails` path. On a slow network this can cause the tile to appear stuck.

**Fix:** Reorder paths to try the correct one first:
```python
for path in ("/emails", "/emails/recent", "/api/emails"):
```

### 4. Calendar Path Discovery: Same 404 Problem
**File:** `cortex/dashboard.py`, function `api_calendar()`

**Bug:** Calendar agent mounts routes at `/calendar/*` (prefix="/calendar"). The dashboard tries `/calendar/today` first which IS correct, but the other fallbacks (`/api/events`, `/events`, `/calendar`) are wrong.

**Fix:** Clean up fallback paths to match actual calendar-agent routes:
```python
for path in ("/calendar/today", "/calendar/upcoming", "/calendar/week"):
```

### 5. Wallet Tile: No Staleness Indicator
**File:** `cortex/static/index.html`, function `renderWallet()`

**Bug:** The Redis `portfolio:snapshot` can be hours old with no indicator. User sees numbers and assumes they are live.

**Fix:** In the `/api/wallet` endpoint, when reading from Redis, also read the snapshot timestamp:
```python
if snap:
    data = json.loads(snap)
    # Add staleness info
    snap_ts = data.get("timestamp") or data.get("updated_at") or data.get("ts")
    data["snapshot_age"] = snap_ts  # let frontend calculate
    for key in ("active_value", "redeemable_value", ...):
        data.setdefault(key, 0)
    return data
```
In `renderWallet()` in the HTML, show the snapshot age if available:
```javascript
const snapAge = data.snapshot_age ? timeAgo(data.snapshot_age) : '';
// Add after the stat-row:
// <div class="small">${snapAge ? 'updated ' + esc(snapAge) : 'live'}</div>
```

### 6. Activity Tile: Wrong Timestamp Extraction
**File:** `cortex/static/index.html`, function `renderActivity()`

**Bug:** The code does `const payload = e.payload || e;` then reads `e.ts || e.timestamp` — but if the timestamp is inside `payload`, it is missed. Also, the `type` display shows raw channel names.

**Fix:** Also check `payload.ts` and `payload.timestamp`:
```javascript
const when = e.ts || e.timestamp || payload.ts || payload.timestamp || '';
const msg = payload.message || payload.msg || e.message || t;
```
Display the message snippet instead of just the type when available:
```javascript
return `<li><span class="mono small">${esc(t)}</span> ${esc((msg || '').slice(0, 50))} <span class="small">${esc(timeAgo(when))}</span></li>`;
```

### 7. Service Health: Port Mismatch for Client Portal
**File:** `cortex/dashboard.py`, `SERVICES` list

**Bug:** Client Portal has `"ext_port": 8096` but in docker-compose it has NO host port mapping (comment says "No host port — accessed internally. dtools-bridge uses 8096 on the host."). The dashboard shows `:8096` next to Client Portal which is misleading — that port is D-Tools Bridge.

**Fix:** Remove `ext_port` from Client Portal or set it to the internal port with a note:
```python
{"name": "Client Portal", "host": "client-portal", "port": 8096, "ext_port": None, "optional": True},
```
In the frontend, show "internal" instead of a port when `ext_port` is null:
```javascript
<span class="port">${s.port ? ':' + esc(s.port) : 'internal'}</span>
```

### 8. Frontend: Memory Tile Passes Wrong Args
**File:** `cortex/static/index.html`, `refresh()` function

**Bug:** Line `renderMemory(health && health.memories, memories)` — `health` comes from `fetchJson('/health')` which returns `{status: "alive", memories: {total: N, by_category: {...}, ...}}`. So `health.memories` is the stats object. This is correct BUT only if `/health` succeeds. If Cortex engine fails to init, `/health` returns 503 and `health` is null, so `health.memories` throws.

**Fix:** Already handled by `health && health.memories` (short-circuit). But add null-safety in `renderMemory`:
```javascript
function renderMemory(stats, memories) {
    const host = $('memory');
    if (!stats && !memories) { host.innerHTML = unavailable(); return; }
    const total = (stats && (stats.total ?? stats.memories)) ?? 0;
    // ... rest unchanged
}
```

### 9. Footer: Memory Stats Key Mismatch
**File:** `cortex/static/index.html`, `renderFooter()`

**Bug:** `renderFooter(health && health.memories, ...)` passes the stats object, then `stats.total ?? 0` — this works. But `chunks.push(...)` shows "memories" label with no space: `<strong>5</strong>memories` renders as "5memories".

**Fix:** Add a space before each label:
```javascript
if (stats) chunks.push(`<span><strong>${stats.total ?? 0}</strong> memories</span>`);
if (wallet) chunks.push(`<span><strong>${fmtUsd(...)}</strong> AUM</span>`);
if (emails) chunks.push(`<span><strong>${emails.unread_count ?? 0}</strong> unread</span>`);
// ... same for svcs, mem, disk
```

---

## Testing

After making all changes, restart the cortex container:
```
docker compose restart cortex
```

Then verify each tile at `http://127.0.0.1:8102/dashboard`:
1. **Service Health** — dots + correct ports, Client Portal shows "internal"
2. **Email** — unread count + subjects load without delay
3. **Calendar** — today's events appear (or "no upcoming events")
4. **Follow-ups** — overdue count reflects actual waiting-on-Matt items
5. **Wallet** — shows snapshot age ("updated Xm ago")
6. **Positions** — count + exposure + top 5
7. **P&L** — daily/weekly numbers with sparkline if data exists
8. **Activity** — events with timestamps and message snippets
9. **Memory** — total count + recent titles
10. **Goals** — progress bars with percentages
11. **Decisions** — shows actual decisions, not random memories
12. **Digest** — daily summary or "no digest yet"
13. **Footer** — proper spacing: "5 memories" not "5memories"

Commit message: `fix(cortex): dashboard tile data accuracy — overdue logic, decisions filter, path ordering, footer spacing`
