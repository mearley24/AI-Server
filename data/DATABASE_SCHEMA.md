# Symphony AI-Server — Database Schema

All databases live under `data/` and are mounted as Docker volumes.
Row counts reflect the state at time of documentation (2026-04-11).

---

## jobs.db (`data/openclaw/jobs.db`)

Canonical job and client data synced from D-Tools. Used by `openclaw`.

| Table | Rows | Purpose |
|---|---|---|
| `jobs` | 40 | Active and historical jobs from D-Tools Cloud sync. Columns: `job_id`, `name`, `phase`, `client_name`, `dtools_project_id`, `created_at`, `updated_at`. |
| `clients` | 3 | Client contact records linked to jobs. Columns: `id`, `name`, `email`, `phone`, `address`, `company`, `notes`, `project_type`, `source`, `created_at`, `updated_at`. |
| `job_events` | 40 | Job lifecycle events (phase changes, notes, D-Tools updates). |
| `client_preferences` | 0* | Client communication preferences extracted from email analysis. Columns: `id`, `client_name`, `preference_type` (preference/concern/requirement/contact/style), `content`, `source`, `created_at`. *Backfilled on orchestrator startup — populates as emails are processed. |

---

## follow_ups.db (`data/openclaw/follow_ups.db`)

**Canonical follow-up store.** All follow-up related data lives here.

| Table | Rows | Purpose |
|---|---|---|
| `follow_ups` | 58 | Client response SLA tracking. One row per client/email thread. Tracks `last_client_ts`, `last_matthew_ts`, `last_overdue_alert_ts`, `last_followup_alert_ts`. Used by `follow_up_tracker.py`. |
| `follow_up_log` | 0* | Audit log of sent follow-up emails by the follow-up engine. One row per (job_id, interval_days). Columns: `job_id`, `interval_days`, `sent_at`, `email_id`, `template`. Used by `follow_up_engine.py`. *Populated when the engine fires (3/7/14-day intervals). |

**Note:** `follow_up_log` was previously in `jobs.db` (empty) and has been consolidated here. `follow_ups.db` is the single source of truth for all follow-up data.

---

## decision_journal.db (`data/openclaw/decision_journal.db`)

All automated decisions and pending Matt approvals. Written by `openclaw`.

| Table | Rows | Purpose |
|---|---|---|
| `decisions` | 3,457 | Every automated decision with reasoning, confidence, employee attribution, and outcome tracking. Columns: `id`, `timestamp`, `category`, `action`, `context_json`, `outcome`, `outcome_score`, `employee`, `confidence`, `outcome_at`. |
| `pending_approvals` | 103* | Items waiting on Matt's approval via iMessage. `kind` is the approval type (e.g. `email_classification`). `status` is `pending` or `expired`. *82 were auto-expired by `approval_drain.py` (>7 days old). 21 remain. |

---

## emails.db (`data/email-monitor/emails.db`)

All processed Zoho IMAP emails. Written by `email-monitor` container.

| Table | Rows | Purpose |
|---|---|---|
| `emails` | 435 | Every processed email with classification, priority, sender, subject, analysis. Columns include `message_id`, `sender`, `sender_name`, `subject`, `category`, `priority`, `received_at`, `summary`, `urgency`, `action_items`. |
| `notified_emails` | 39 | Emails that triggered iMessage notifications. |
| `scan_state` | 3 | IMAP cursor state (high-water marks for UID-based incremental polling). |

---

## brain.db (`data/cortex/brain.db`)

Cortex long-term memory, goals, improvement log. Written by the `cortex` service (port 8102).

| Table | Rows | Purpose |
|---|---|---|
| `memories` | 39 | Long-term memory entries. Columns: `id`, `category`, `subcategory`, `title`, `content`, `source`, `confidence`, `importance`, `ttl_days`, `access_count`, `last_accessed`, `tags`, `metadata`. |
| `decisions` | 0 | Cortex decision log (populated by improvement loop). |
| `goals` | 5 | Active goals with progress tracking. Columns: `id`, `title`, `target_value`, `current_value`, `unit`, `status`, `priority`, `category`, `deadline`. |
| `improvement_log` | 0 | Self-improvement action log (populated by daily improvement cycle at 5:30 AM MT). |

---

## Other databases (not in `data/openclaw/`)

| File | Service | Purpose |
|---|---|---|
| `data/openclaw/knowledge_base.db` | openclaw | Symphony product knowledge base with FTS5 search. |
| `data/openclaw/openclaw_memory.db` | openclaw | OpenClaw agent working memory and context. |
| `data/openclaw/cost_tracker.db` | openclaw | LLM API cost tracking per category/agent. |
| `data/openclaw/payments.db` | openclaw | Payment schedule tracking. |
| `data/openclaw/price_monitor.db` | openclaw | Product price monitoring. |
| `data/portal.db` | client-portal | Per-client portal tokens, document links, e-signature status. |

---

## Key rules

- **Never track runtime DB files in git.** All `.db` files are in `.gitignore`.
- **WAL mode** is enabled on all sqlite3 connections (`PRAGMA journal_mode=WAL`).
- **follow_ups.db is canonical** for all follow-up data (`follow_ups` + `follow_up_log`).
- **jobs.db is canonical** for jobs, clients, and client preferences.
- **brain.db** is managed exclusively by the Cortex service — do not write to it directly.

---

## Live snapshot (2026-04-17 reconciled)

The `memories` row count table above shows `39` — this was the seed
count. Live reality is very different and grows every minute.
Run `bash scripts/cortex-brain-snapshot.sh` to write a fresh snapshot
to `ops/verification/<stamp>-cortex-brain-snapshot.txt` (read-only).

Live row counts at 2026-04-17 09:56 MDT:

| Database | Table | Rows | Notes |
|---|---|---|---|
| `data/cortex/brain.db` | `memories` | **37,535** | 127 MB on disk. Top categories: trading_strategy (17,062), risk_management (8,450), follow_up (6,529), tech_infrastructure (3,469). |
| `data/openclaw/decision_journal.db` | `decisions` | 4,642+ | Still the canonical decision log. |
| `data/openclaw/decision_journal.db` | `pending_approvals` | 0 | Drained 2026-04-13 via Prompt T. |
| `data/openclaw/jobs.db` | `jobs` | 41 | Active client jobs. |
| `data/email-monitor/follow_ups.db` | `follow_ups` | 61 | Canonical after 2026-04-17 consolidation. |
| `data/email-monitor/emails.db` | `emails` | 452 | `read=1` bug fixed 2026-04-13. |

Backups: use `bash scripts/backup-cortex-dbs.sh --execute` to produce a
timestamped snapshot of the 5 high-value DBs under
`backups/sqlite/YYYYMMDD-HHMMSS/`.

Schema helpers (added 2026-04-17):
- `scripts/backup-cortex-dbs.sh` — SQLite `.backup` wrapper, dry-run by default.
- `scripts/cortex-brain-snapshot.sh` — read-only row-count snapshot → `ops/verification/`.
