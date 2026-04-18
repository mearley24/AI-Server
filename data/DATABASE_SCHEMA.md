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

## Live snapshot (2026-04-18 reconciled)

The `memories` row count table above shows `39` — this was the seed
count. Live reality grows every minute.
Run `bash scripts/cortex-brain-snapshot.sh` to write a fresh snapshot
to `ops/verification/<stamp>-cortex-brain-snapshot.txt` (read-only).

Live row counts at 2026-04-18 12:10 MDT:

| Database | Table | Rows | Notes |
|---|---|---|---|
| `data/cortex/brain.db` | `memories` | **45,294** | ~146 MB on disk. 25,173 rows written in the last 24 h. Top categories: trading_strategy (19,751 / 44 %), risk_management (10,700 / 24 %), follow_up (8,048 / 18 %), tech_infrastructure (4,425 / 10 %). |
| `data/cortex/brain.db` | `goals` | 5 | All `status='active'`. |
| `data/cortex/brain.db` | `improvement_log` | 8 | Populated on demand via `/improve/run`. |
| `data/openclaw/decision_journal.db` | `decisions` | 7,968 | +3,326 since 2026-04-17 audit. |
| `data/openclaw/decision_journal.db` | `pending_approvals` | **474 pending** (+103 expired, +63 skipped) | ⚠ Regressed since the 2026-04-13 Prompt T drain. All 474 are `kind=email_classification`. No auto-drain scheduled. |
| `data/openclaw/jobs.db` | `jobs` | 41 | Active client jobs. |
| `data/openclaw/follow_ups.db` | `follow_ups` | 60 | ⚠ Openclaw writer, actively updated (see "Known regressions"). |
| `data/email-monitor/follow_ups.db` | `follow_ups` | 61 | ⚠ Ghost — stopped updating 2026-04-17 but file is still present. |
| `data/email-monitor/email-monitor/follow_ups.db` | `follow_ups` | 37 | ⚠ Doublenested path-stacking regression, email-monitor writer, actively updated. |
| `data/email-monitor/emails.db` | `emails` | 569 | `read=1` bug fix holds (0 rows marked `read=1`). |

Backups: use `bash scripts/backup-cortex-dbs.sh --execute` to produce a
timestamped snapshot of the 5 high-value DBs under
`backups/sqlite/YYYYMMDD-HHMMSS/`.

Schema helpers (added 2026-04-17):
- `scripts/backup-cortex-dbs.sh` — SQLite `.backup` wrapper, dry-run by default.
- `scripts/cortex-brain-snapshot.sh` — read-only row-count snapshot → `ops/verification/`.

---

## Known regressions (2026-04-18)

Carried over from the 2026-04-18 re-audit
(`ops/verification/20260418-121300-memory-state-knowledge-audit.txt`).
These are documented here so the next agent does not rediscover them
from scratch.

### follow_ups.db split — THREE live files

There are **three live `follow_ups.db` files** with **two different
schemas** and **two active writers**:

| Path | Rows | Schema | Writer | Last `updated_at` |
|---|---|---|---|---|
| `data/openclaw/follow_ups.db` | 60 | `follow_ups` + `follow_up_log` + `idx_ful_job` | openclaw orchestrator (via `self._data_dir / "follow_ups.db"`) | 2026-04-18T16:46:48Z |
| `data/email-monitor/follow_ups.db` | 61 | `follow_ups` + `follow_up_log` (different column layout) | — (ghost; stopped updating 2026-04-17) | 2026-04-17T13:41:24Z |
| `data/email-monitor/email-monitor/follow_ups.db` | 37 | `follow_ups` only (no `follow_up_log`) | email-monitor/monitor.py via path-stacking (compose mount `./data/email-monitor:/data` + default path `/data/email-monitor/follow_ups.db`) | 2026-04-18T16:48:50Z |

Retired tombstones are still present alongside the live files:
- `data/openclaw/follow_ups.db.retired-20260417-074319`
- `data/email-monitor/email-monitor/follow_ups.db.retired-20260417-074319`

**Do not pick a "winner" in a casual cleanup pass.** A proper fix
requires (a) a single `FOLLOW_UP_DB_PATH` env that both containers
respect, (b) unifying the two live schemas with a migration
(openclaw's `follow_up_log` has `job_id INTEGER`, email-monitor's has
`job_id TEXT` + `client_email`), and (c) a compose drift check that
fails if either container can write to more than one path. Queue this
as its own prompt; it is medium-risk.

### cortex.db is orphaned

`data/cortex/cortex.db` (122 KB, 21 entries, 10 neural_paths, 6
recurring_problems) is a leftover from an earlier Cortex iteration
and **is not referenced by the current engine**. `cortex/config.py`
points `DB_PATH` at `brain.db`. Last touched 2026-04-11. Either adopt
the `recurring_problems` table for a structured mistakes registry
(promising — see the audit's §6) or archive the file under `backups/`.

### Apple Notes ingestion broken since 2026-04-15

`scripts/export_notes.py` cannot read `NoteStore.sqlite` because
Full Disk Access is not granted to the launchd interpreter. See
`/tmp/notes-sync.log` — repeating `PermissionError: [Errno 1]
Operation not permitted`. Fix is a one-time System Settings →
Privacy & Security → Full Disk Access grant to `/usr/bin/python3.9`
and `/bin/zsh`. Notes-to-Cortex pipeline has been silent for 3+
days; no recent Apple Notes content is reaching `brain.db`.

### cortex/memory.py CATEGORIES drift

The declared `CATEGORIES` set in `cortex/memory.py` does **not**
include `trading_strategy`, `risk_management`, or
`tech_infrastructure` — yet those three categories own
~78 % of `brain.db`. `remember()` does not enforce the set, so the
declared list is currently fiction. A future prompt should either
update the set or add a validation layer that at least logs writes
for uncanonical categories.

### Dormant auxiliary DBs

- `data/openclaw/cost_tracker.db` — no writes since 2026-04-05 (13 days)
- `data/openclaw/price_monitor.db` — no writes since 2026-04-10 (8 days)

Both are in the schema but neither has a known live pipeline.
Document the intended owner or mark decommissioned.

---

## Merge-conflict protections

`.gitattributes` currently whitelists two generated-file families
with `merge=ours`:

```
knowledge/markup_exports/.session_tracking.json merge=ours
data/cortex/digests/**                          merge=ours
```

The `merge=ours` driver only fires on **automatic** merges. It does
not help when a local edit + pull produces a "both modified" state —
that case falls to `ops/task_runner_preflight.py`, which calls
`git checkout --ours <path>` for the whitelisted patterns. Preflight
is advisory: it writes `ops/verification/<stamp>-preflight.txt` and
commits any safe auto-resolutions.

If a pull leaves either of those two paths in UU state and preflight
has not ticked (or the launchd job is not loaded), heal it by hand
with:

```
git checkout --ours <path>
git add <path>
```

The 2026-04-18 audit found `data/cortex/digests/2026-04-17.md` in
UU state at task start; the preflight had not self-triggered.

## Cross-references

- Full audit: `ops/verification/20260418-121300-memory-state-knowledge-audit.txt`
- Final report: `ops/verification/20260418-121300-memory-state-knowledge-final.txt` (companion)
- Prior audit: `ops/verification/20260417-095615-memory-state-knowledge-audit.txt`
- Prior final: `ops/verification/20260417-095900-memory-state-knowledge-final.txt`
