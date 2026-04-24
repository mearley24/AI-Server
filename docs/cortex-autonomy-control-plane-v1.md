# Cortex Autonomy Control Plane v1

## Purpose

Makes Bob's autonomy **measurable, visible, and auditable** inside Cortex.
Rather than spreading truth across STATUS_REPORT, runbooks, prompts, and
ops/verification receipts, Cortex now ingests and displays that truth through
a single endpoint and dashboard panel.

Answers 10 core questions about Bob's operational state on demand.

---

## Data Model

### AutonomyQuestion
One of the 10 readiness questions.
- `key` — machine identifier
- `label` — human-readable question
- `status` — `ok` / `warn` / `fail` / `unknown`
- `detail` — single-line evidence string

### Verification
A parsed `ops/verification/` receipt.
- `path`, `filename`, `timestamp` — location and time
- `topic` — slug extracted from filename
- `verdict` — `PASS / FAIL / PARTIAL / GAP / UNKNOWN / ARMED / CLOSED / NEEDS_MATT`
- `summary` — first meaningful lines (bounded, max 300 chars)

### HumanGate
A human-intervention marker found in repo files.
- `source` — file or path where found
- `marker` — `NEEDS_MATT / [FOLLOWUP] / ARMED / BLOCKED / waiting`
- `excerpt` — surrounding line for context

### AutonomyOverview
Full snapshot.
- `generated_at` — ISO-8601 UTC
- `overall_status` — `ok / warn / degraded`
- `human_gates` — list of HumanGate (max 20, most-recent first)
- `recent_verifications` — list of Verification (last 10)
- `questions` — list of 10 AutonomyQuestion

---

## Endpoint

```
GET /api/autonomy/overview
```

Returns `AutonomyOverview` as JSON. No auth required (loopback-only port).
Typical latency: 200–800ms (bounded file I/O + 2 async HTTP calls to BlueBubbles).

### The 10 Questions

| Key | Source | Notes |
|---|---|---|
| `is_bob_alive` | Direct SQLite count on brain.db | No self-call — avoids deadlock |
| `can_receive_messages` | Async call to `/api/bluebubbles/health` | Checks inbound_count + status |
| `can_write_memory` | Direct SQLite count on brain.db | Same DB, synchronous |
| `can_use_embeddings` | `CORTEX_EMBEDDINGS_ENABLED` env var | Config-driven |
| `can_execute_signed_tasks` | Mtime of `/data/task_runner/heartbeat.txt` | Stale if >30 min |
| `can_send_outbound` | Async call to `/api/bluebubbles/health` | Checks last_ping_ok_at |
| `what_is_blocked_on_matt` | HumanGateScanner → STATUS_REPORT.md | NEEDS_MATT count |
| `what_failed_recently` | VerificationScanner → verdicts FAIL/GAP | Last 50 files |
| `what_got_verified_recently` | VerificationScanner → verdicts PASS/CLOSED | Last 5 matching |
| `what_is_bob_doing_next` | ops/work_queue/pending/ count + recent topics | Queue-depth signal |

---

## Scanners

### VerificationScanner
- Reads up to 50 most-recent files in `ops/verification/` (by filename sort)
- Skips files >500 KB
- Bounded to first 40 lines per file
- Parses timestamp (YYYYMMDD-HHMMSS), topic, and verdict from filename + content
- Runs in thread executor to avoid blocking the async event loop

### HumanGateScanner
- Scans last 200 lines of `STATUS_REPORT.md`
- Scans filenames in `ops/runbooks/` and `.cursor/prompts/`
- Markers: `NEEDS_MATT`, `[FOLLOWUP]`, `ARMED`, `BLOCKED`, `blocked`, `waiting`, `confirmation required`
- Returns up to 20 gates, most-recent first

---

## Dashboard Panel

Added "Autonomy" tab (5th in Cortex dashboard nav) at `http://localhost:8102/dashboard`.

Shows:
1. Overall status badge (green/yellow/red)
2. 10-question grid with colored status icons
3. Human gates card (highlighted when NEEDS_MATT gates present)
4. Recent verifications list (last 5)

---

## Container Mounts Required

The following bind mounts were added to the `cortex` service in `docker-compose.yml`:

```yaml
- ./ops/verification:/app/ops/verification:ro
- ./ops/runbooks:/app/ops/runbooks:ro
- ./ops/work_queue:/app/ops/work_queue:ro
- ./.cursor/prompts:/app/.cursor/prompts:ro
- ./STATUS_REPORT.md:/app/STATUS_REPORT.md:ro
- ./data/task_runner:/data/task_runner:ro
```

---

## Current Limitations

1. **Embeddings always warn** — `CORTEX_EMBEDDINGS_ENABLED` is `0`. This is correct; embeddings are not enabled. Not a bug.
2. **`can_receive_messages` shows 0 inbound** — counters reset on each Cortex restart. The webhook is proven live (see verification `20260424-161534-bluebubbles-cortex-live-webhook.md`).
3. **Verification scanner reads filenames** — multi-segment filenames (dispatch-*, self-improve-*) appear in recent_verifications. These are valid receipts but less interesting than the audits.
4. **No persistent event/action tables** — v1 infers everything from file scans. State is rebuilt on every request (~200ms overhead).
5. **Dashboard tab requires manual JS fetch** — follows existing Cortex dashboard pattern (polling on tab open).
6. **No real-time push** — pull-only; no WebSocket or SSE yet.
7. **Image must be rebuilt** for autonomy.py to survive a `docker compose up --build` — currently injected via `docker cp` due to locked keychain.

---

## How to Extend Sources

Add new evidence to any scanner by:

1. **New verification source**: extend `VerificationScanner._parse_file()` to handle new filename patterns or content formats.
2. **New gate source**: add a `_scan_*` method to `HumanGateScanner`.
3. **New question**: add an `async def _my_new_question()` to `AutonomyAssessor` and add it to the `questions` list in `assess()`.
4. **Richer events**: emit structured JSON lines to `ops/verification/` from any service; the scanner will pick them up automatically.

---

## What Should Become v2

- **Persistent event/action/gate tables** in brain.db (SQLite migrations)
- **Service-owned event emission** — each service POSTs events to `POST /api/autonomy/event`
- **Task-runner direct status feed** — task_runner writes structured JSON heartbeats
- **Richer STATUS_REPORT parser** — extract structured entries, not just marker lines
- **Action approval UI** — Matt can ACK/dismiss gates from the dashboard
- **Reply-action integration** — x-intake reply-leg feeds into the action queue
- **Network monitoring panel** — integrate dropout-watch data
- **Real-time updates** — SSE or polling interval in the dashboard
- **Explicit autonomy score** — weighted 0–100 based on question statuses
- **Bake autonomy.py into the image** — remove the docker cp dependency
