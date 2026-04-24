# Cortex Dedup Live `--apply` — Bob Runtime Arm Runbook

**Status:** `DONE` — `--apply` ran successfully on 2026-04-23
(1 duplicate removed). Future re-runs follow the sequence below if
a dry-run reports `duplicates_found > 0`.

This file is a human-approved runbook, not an autonomous prompt.
Do **not** add `<!-- autonomy: start -->` metadata to it. Do not
copy it into `.cursor/prompts/`. Dispatchers under
`ops/cline-run-*.sh` must **skip** anything in `ops/runbooks/`.

**Owner:** Matt (or a human operator with shell access to Bob).
**Host:** Bob (Mac Mini M4), `~/AI-Server` checkout of `origin/main`.
**Prerequisite prompt:** `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md`
(Status: `done`, Phase-1 author+test closed).
**Scope anchor:** STATUS_REPORT entries "Cortex Dedup Phase-1
Author+Test" and "Cortex Dedup re-run verification".

---

## Why this runbook exists

Repo-side work (schema + `store_or_update` + backfill script +
12 unit tests) landed on `origin/main`. What remains is the
one-shot live backfill against Bob's production `brain.db` to
collapse any pre-existing duplicates and populate `dedupe_key` for
historical rows.

A `--apply` run on 2026-04-23 already removed 1 duplicate (see
receipts). This runbook formalises a repeatable clearance for any
future re-run (e.g. after a new ingest burst) and documents the
idempotent backfill contract. **It must not be used to perform a
destructive DELETE beyond the canonical idempotent dedup the script
implements.**

---

## Prechecks (required, run before any mutation)

Capture into
`ops/verification/<YYYYMMDD-HHMMSS>-cortex-dedup-live-apply-precheck.txt`
before proceeding.

1. Checkout clean, on `origin/main`:
   ```
   cd ~/AI-Server
   git status --short
   git rev-parse --abbrev-ref HEAD
   git rev-parse HEAD
   git log --oneline -1
   ```
   Expect: branch `main`, HEAD contains commits `716b14a` / `da532f3`
   / `758b31f` (schema + upsert + backfill).

2. Cortex container reachable and healthy (required for `docker exec`):
   ```
   docker ps --format '{{.Names}} {{.Status}}' | grep -E '^cortex '
   curl -sS -m 5 http://127.0.0.1:8102/health | head -c 200
   ```

3. Schema has the dedupe_key column + partial UNIQUE index already:
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "PRAGMA table_info(memories);" | grep -i dedupe_key
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_memories_dedupe_key';"
   ```
   Expect: `dedupe_key TEXT` column present; `idx_memories_dedupe_key`
   present with `WHERE dedupe_key IS NOT NULL` clause.

4. Dry-run first and capture the expected merge plan:
   ```
   docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --dry-run | head -c 4000
   ```
   Expect: a JSON/text summary listing candidate merges. Record
   `duplicates_found`. **If `duplicates_found == 0`, there is nothing
   to do; stop and record the no-op outcome.**

5. Row count baseline before mutation:
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NULL;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NOT NULL;"
   ```
   Record the three totals verbatim in the precheck file.

6. Confirm no other Cortex writer is contending (embed_worker is
   tolerant; manual bulk ingests are not):
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "PRAGMA busy_timeout=2000; SELECT 1;"
   ```
   Expect: `1`. A `SQLITE_BUSY` means another process has an
   exclusive lock — **stop**.

7. Free-disk check — backup file fits:
   ```
   df -h /var/lib/docker 2>/dev/null || df -h ~
   docker exec cortex du -sh /data/cortex/brain.db
   ```
   Expect: free space ≥ 3 × `brain.db` size.

**Stop conditions (abort, do not continue):**

- Any precheck returns a non-200 / SQLITE_BUSY / missing column /
  missing index.
- `git status` shows uncommitted changes in `cortex/**`,
  `scripts/cortex_dedup_backfill.py`, or `ops/tests/test_cortex_dedup.py`.
- Dry-run output shows more than **5%** of `memories` flagged for
  deletion — that is *not* an expected dedup outcome; stop and
  escalate.
- Disk check fails.

---

## Ordered arm sequence (Matt or human operator)

All commands are bounded; none require heredocs, interactive
editors, or `sudo`. Capture each command's stdout/stderr into the
precheck verification file.

1. **Backup `brain.db` (required — the backfill is destructive on
   duplicate rows).**
   ```
   docker exec cortex sh -c 'cp /data/cortex/brain.db /data/cortex/brain.db.bak.$(date +%Y%m%d-%H%M%S)'
   docker exec cortex ls -la /data/cortex/ | grep brain.db
   ```
   Record the exact `.bak.<stamp>` filename in the receipt. **Do
   not** delete earlier `.bak.*` files in this runbook.

2. **Re-run the dry-run one final time as evidence-of-plan immediately
   before `--apply`.**
   ```
   docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --dry-run | tee -a ~/AI-Server/ops/verification/<same-precheck-file>.txt | head -c 2000
   ```
   Confirm `duplicates_found` matches step 4 of prechecks. A drift
   means new writes have landed — stop and re-evaluate.

3. **Run the live backfill `--apply`.**
   ```
   docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --apply
   ```
   Expect: JSON summary written to
   `ops/verification/<YYYYMMDD-HHMMSS>-cortex-dedup-backfill.json`
   with keys `groups`, `duplicates_found`, `rows_deleted`,
   `keys_set`, `dry_run: false`. **Stop** if `rows_deleted >
   duplicates_found` or the script exits non-zero.

4. **Post-apply counts.**
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NULL;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NOT NULL;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) AS total, COUNT(DISTINCT dedupe_key) AS distinct_keys FROM memories WHERE dedupe_key IS NOT NULL;"
   ```
   Expect: `total == distinct_keys` (no dedupe_key collisions
   remaining); `COUNT(memories)_post == COUNT(memories)_pre -
   rows_deleted`.

5. **Smoke the writer path: a same-URL `/remember` twice should
   coalesce.**
   ```
   curl -sS -m 5 -X POST -H 'Content-Type: application/json' \
     http://127.0.0.1:8102/remember \
     -d '{"content":"dedup smoke","category":"test","source":"https://example.com/smoke","dedupe_hint":"dedup-smoke-<stamp>"}'
   curl -sS -m 5 -X POST -H 'Content-Type: application/json' \
     http://127.0.0.1:8102/remember \
     -d '{"content":"dedup smoke","category":"test","source":"https://example.com/smoke","dedupe_hint":"dedup-smoke-<stamp>"}'
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT id, access_count FROM memories WHERE dedupe_key IS NOT NULL AND category='test' AND source='https://example.com/smoke' ORDER BY id DESC LIMIT 2;"
   ```
   Replace `<stamp>` with a timestamp unique to the run. Expect:
   exactly one row with `access_count=2`.

6. **(Optional) Clean up the smoke row.** Preserve if useful for
   history; otherwise:
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "DELETE FROM memories WHERE category='test' AND source='https://example.com/smoke' AND dedupe_key IS NOT NULL;"
   ```
   The `DELETE` is scoped by unique `dedupe_key` — no risk of wider
   damage.

---

## Verification receipt requirements

After the arm sequence completes (or aborts), write a single
receipt to:

```
ops/verification/<YYYYMMDD-HHMMSS>-cortex-dedup-live-apply.txt
```

The receipt **must** include, verbatim:

- `git rev-parse HEAD` on Bob at run time.
- Precheck outputs (all row-count baselines + dry-run JSON).
- Backup filename created in step 1.
- Final `--apply` JSON summary path + its full content.
- Post-apply row counts from step 4 (all four queries).
- Smoke-test curl results + resulting access_count.
- Optional cleanup outcome (kept or deleted).

Then add a dated STATUS_REPORT entry named
`## Cortex Dedup — Live Apply on Bob (<YYYY-MM-DD> <HH:MM TZ>, Matt)`
linking to the receipt with pre/post counts and backup filename.

Commit with:

```
docs(cortex): live dedup apply on Bob — verification + STATUS_REPORT
```

Do **not** `git push --force` and do **not** amend prior commits.

---

## Rollback / stop conditions

| Condition | Immediate action |
|-----------|------------------|
| `--apply` exits non-zero | Do **not** re-run. Read the error class. If integrity-related, restore from `brain.db.bak.<stamp>`. |
| `rows_deleted > duplicates_found` reported in summary | Restore from backup. File a FOLLOWUP. |
| Post-apply `total != distinct_keys` where dedupe_key is non-null | Index constraint is broken — restore from backup. |
| `SELECT COUNT(*) FROM memories;` drops by >5% | Restore from backup; this is outside the expected idempotent-dedup envelope. |
| `/remember` smoke returns HTTP 5xx | Separate bug — leave DB intact; open a FOLLOWUP. |

**Restore from backup (Cortex container):**

```
docker compose stop cortex
docker exec cortex sh -c 'cp /data/cortex/brain.db.bak.<stamp> /data/cortex/brain.db'
docker compose start cortex
curl -sS -m 5 http://127.0.0.1:8102/health | head -c 200
```

Leave the `.bak.<stamp>` in place until a subsequent successful run
is confirmed.

---

## What this runbook explicitly forbids

- Running from a non-interactive dispatcher (task-runner,
  self-improvement loop, remote trigger). If a scheduled job tries
  to execute these steps, **it is a bug** — file under
  `ops/realized_changes/` severity `high`.
- Any `DELETE` / `UPDATE` against `memories` outside the
  idempotent backfill script.
- `DROP INDEX` / `DROP TABLE` / `ALTER TABLE … DROP COLUMN`.
- Editing `brain.db` directly from the host (always via
  `docker exec cortex`).
- Running without the pre-backup in step 1.
- Rewriting the backfill script to bypass the busy-lock check or to
  write outside `ops/verification/`.
- Turning this runbook into a `cline-prompt-*.md` or copying it
  into `.cursor/prompts/`.

---

## Appendix: historical arm evidence

Prior `--apply` receipts on `brain.db` (2026-04-23):

- `ops/verification/20260423-173840-cortex-dedup-backfill.json`:
  `groups=1 duplicates_found=1 rows_deleted=1 keys_set=1 dry_run=false`
- `ops/verification/20260423-190359-cortex-dedup-backfill.json`:
  `groups=1 duplicates_found=1 rows_deleted=1 keys_set=1 dry_run=false`

Both runs are idempotent — same duplicate detected and removed. The
second run (run inside the container as part of the embeddings arm)
confirms correct behaviour after a DB restore.

Live DB state as of 2026-04-24:
- `memories` total: 53,972
- `dedupe_key IS NOT NULL`: 1 (the surviving row from the duplicate group)
- `dedupe_key IS NULL`: 53,971 (historical rows with unresolvable source)
- `idx_memories_dedupe_key`: PRESENT

A subsequent `--dry-run` should report `duplicates_found=0` unless new
URL-sourced or hint-sourced duplicates have arrived via `POST /remember`.
