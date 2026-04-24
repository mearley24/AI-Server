<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: data
Risk tier: medium
Trigger:   manual
Status:    done
<!-- autonomy: end -->

<!-- closure: start -->
Closed: 2026-04-24 by Claude Code (parent-agent loose-ends reconciliation).
Commits: `716b14a`, `da532f3`, `758b31f`, `bc8ffdf`, `50feea8`
— "Completed + verified (re-run)" in STATUS_REPORT.md L537.
12 tests pass (`ops/tests/test_cortex_dedup.py`).
Live `--apply` ran on Bob 2026-04-23 via arm runbook
`ops/runbooks/2026-04-23-cortex-dedup-live-apply-bob-arm.md` (`Status: DONE`);
receipts `ops/verification/20260423-173120-cortex-dedup-backfill.json` +
`20260423-173840-cortex-dedup-backfill.json` (each `rows_deleted=1`, idempotent).
Reconciliation audit: `docs/audits/2026-04-24-loose-ends-reconciliation.md`.
<!-- closure: end -->

# Cortex Cross-Source Dedup (UNIQUE / Upsert) — Cline-first

## Owner / runtime context

- Repo-side work (schema + migration + writer + tests) is runnable
  from any clean checkout of `origin/main`.
- Anything that mutates Bob's live Cortex SQLite (`data/cortex/`
  `cortex.db` or whichever path `cortex.config.DB_PATH` resolves to
  on Bob) is **[BOB_CLINE_ONLY]**. The MacBook checkout MUST use a
  scratch DB under `data/cortex/test/` instead.
- Scope anchor: `docs/audits/2026-04-23-unfinished-setup-audit.md`
  §1 "Cortex cross-source dedup (UNIQUE/upsert) and embeddings" —
  this prompt closes the **dedup / UNIQUE / upsert** half only. The
  embeddings half lives in
  `.cursor/prompts/2026-04-23-cline-cortex-embeddings.md` and is
  **not** in scope here.

## Goal

Prevent duplicate memory rows when the same logical event is seen
across multiple sources (e.g. one X post ingested by the RSS
collector and by an iMessage-forwarded URL) by adding:

1. A canonical `dedupe_key` column on `memories` (SQLite SHA-256 of
   the normalized source identity — see "Implementation tasks").
2. A partial `UNIQUE` index on `dedupe_key` (where non-null), so
   existing rows that do not yet have a key are unaffected.
3. An `UPSERT` writer path (`MemoryStore.store_or_update`) so every
   new insert computes the key and reuses the existing row id on a
   collision, merging `importance` / `access_count` / `tags` /
   `metadata` rather than duplicating the row.
4. A one-shot backfill migration that computes `dedupe_key` for
   historical rows where a canonical identity can be derived, and
   deletes only the *latest duplicate insertions* (not the first) —
   with a dry-run mode that reports candidate deletes and a live
   mode behind an explicit flag.

## Non-goals

- **Not** adding embeddings / vector search — that is the separate
  `cortex-embeddings` prompt.
- **Not** changing the `memories` category taxonomy.
- **Not** altering the public `POST /remember` API shape beyond
  adding an *optional* `dedupe_hint` field — callers that omit it
  keep working.
- **Not** touching `decisions`, `goals`, `improvement_log`, or
  `seed_data.json`.
- **Not** running the live backfill from this prompt. The backfill
  script is authored + unit-tested in repo, but the live `--apply`
  run against Bob's DB is gated as **[NEEDS_MATT]** +
  **[BOB_CLINE_ONLY]** with a mandatory backup step.
- **Not** re-writing any of the x-intake / bluebubbles ingest
  callers beyond adding `dedupe_hint` to their `POST /remember`
  payloads where obvious.

## Safety gates

- **No secrets**: never print `.env`; reading `cortex/config.py` for
  `DB_PATH` is fine.
- **No destructive data changes**: the migration phase must run as
  `--dry-run` by default and require `--apply` + a timestamped
  backup copy of the DB before it touches rows. The backup step is
  `cp $DB_PATH $DB_PATH.bak.<YYYYMMDD-HHMMSS>` — a local-file `cp`
  only, no cloud upload.
- **No external sends / posts / messages.**
- **No recurring/scheduled jobs loaded.** Migration runs one-shot,
  manually, and only on Bob under `[NEEDS_MATT]` approval.
- **Bob runtime posture**: on Bob, never run the migration while
  Cortex is serving requests. Either stop the Cortex container /
  LaunchAgent first (**[NEEDS_MATT]** — this prompt does not stop
  services) or scope the migration to a copy of the DB.
- **No sudo. No ports. No interactive editors. No heredocs.**
- **Bounded commands**: `timeout 60` on every SQLite query that
  scans the full table. `--limit 500` on any read-back query.

## Preconditions

Read in this order:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (§1 only)
- `docs/audits/x-intake-deep-dive-audit.md` (Cortex-writer section)
- `cortex/memory.py` (full — this is the primary surface)
- `cortex/engine.py` (look at `/remember` and event-to-memory writer
  paths only)
- `cortex/migrate.py` (for the existing migration-framework shape)
- `cortex/config.py` (read `DB_PATH` only)

Confirm git state:

```
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
git pull --ff-only
```

Stop if pull fails or there is unrelated dirty state in
`cortex/**` you did not author.

## Safe inspection steps (read-only, bounded)

```
python3 -c "import ast; ast.parse(open('cortex/memory.py').read()); print('ok')"
python3 -m py_compile cortex/memory.py cortex/engine.py cortex/migrate.py
grep -nE "INSERT INTO memories|UPDATE memories|dedupe|UNIQUE" cortex/memory.py cortex/engine.py | head -n 40
sed -n '19,40p' cortex/memory.py
test -n "$(python3 -c "from cortex.config import DB_PATH; print(DB_PATH)")" && echo ok-dbpath
```

On Bob only (**[BOB_CLINE_ONLY]**), inspect without mutating:

```
python3 -c "import sqlite3,os,sys; from cortex.config import DB_PATH; db=str(DB_PATH); print('db=',db,'exists=',os.path.exists(db))"
timeout 15 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" '.schema memories'
timeout 15 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" 'SELECT COUNT(*) FROM memories;'
timeout 15 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" "SELECT category, source, COUNT(*) FROM memories GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;"
```

## Implementation tasks (scoped to this one item)

Keep each task to a single reviewable commit.

1. **Schema: add `dedupe_key TEXT` column + partial UNIQUE index**
   - `ALTER TABLE memories ADD COLUMN dedupe_key TEXT` (SQLite does
     not allow adding a UNIQUE column inline, so do it this way).
   - `CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_dedupe_key
     ON memories(dedupe_key) WHERE dedupe_key IS NOT NULL;` — partial
     index means historical NULL rows do not collide.
   - All schema work goes through `_SCHEMA` + an explicit
     `_MIGRATIONS` list in `cortex/memory.py` (mirror the approach
     in `integrations/x_intake/queue_db.py` which already carries a
     `_MIGRATE_COLUMNS` list — see STATUS_REPORT reference to
     `queue_db.py`'s `set_analyzed` work).

2. **Canonical `dedupe_key` derivation**
   - New helper `MemoryStore._canonical_key(category, source,
     subcategory, dedupe_hint) -> str | None`.
   - Rules (applied in order):
     1. If `dedupe_hint` is a non-empty string, return
        `sha256("hint:" + dedupe_hint)`.
     2. Else if `source` looks like a URL, return
        `sha256("url:" + canonicalize_url(source))` where
        `canonicalize_url` lower-cases the host, strips a trailing
        slash, drops `utm_*` and `fbclid` query params, and keeps
        only the scheme/host/path/sorted-remaining-query.
     3. Else if `source` starts with `msg:` / `imessage:` /
        `bluebubbles:` / `x:` — return
        `sha256(category + ":" + source + ":" + subcategory)`.
     4. Else return `None` — row is stored as-is, un-deduped.
   - Pure function. Unit-test each branch.

3. **Writer path: `store_or_update`**
   - New `MemoryStore.store_or_update(...)` that:
     - Computes `dedupe_key`.
     - If key is `None` → behave exactly like `store(...)` today.
     - Else, within a single transaction:
       - `SELECT id FROM memories WHERE dedupe_key = ? LIMIT 1`.
       - If hit: `UPDATE` — bump `updated_at`, `access_count += 1`,
         take `max(importance_existing, importance_new)`, union
         tags (distinct), shallow-merge `metadata` JSON (new keys
         win, existing keys preserved if not set by new). **Do not**
         overwrite `content` unless the new row is longer AND the
         caller passes `overwrite_content=True`.
       - If miss: `INSERT` with the computed `dedupe_key`.
   - `engine.py` `/remember` handler accepts an optional
     `dedupe_hint` body field and forwards to `store_or_update`.
     Existing callers that do not send it keep working.

4. **One-shot backfill script**
   - `scripts/cortex_dedup_backfill.py`:
     - `--db <path>` (defaults to `cortex.config.DB_PATH`).
     - `--dry-run` (default) — prints candidate merges, no writes.
     - `--apply` — performs the merge inside a single transaction,
       writes a JSON summary to
       `ops/verification/<YYYYMMDD-HHMMSS>-cortex-dedup-backfill.json`.
     - Always prints the backup command for the caller to run
       manually: `cp <db> <db>.bak.<stamp>`. The script does **not**
       `rm` the backup.
     - Refuses to run `--apply` if the DB is opened in another
       process (`PRAGMA busy_timeout=2000` + fail on `SQLITE_BUSY`).

## Full verification / test checklist (bounded)

Every command below is bounded. Capture into the verification
artifact listed in "Required artifacts".

### V1 — Static

```
python3 -m py_compile cortex/memory.py cortex/engine.py cortex/migrate.py scripts/cortex_dedup_backfill.py
git diff --stat
```

### V2 — New unit tests under `ops/tests/`

Add `ops/tests/test_cortex_dedup.py` with at minimum:

- `test_canonical_key_uses_hint_first`
- `test_canonical_key_canonicalizes_url_host_and_strips_utm`
- `test_canonical_key_returns_none_when_source_unrecognized`
- `test_store_or_update_inserts_on_new_key`
- `test_store_or_update_merges_on_collision`
- `test_store_or_update_preserves_content_unless_overwrite`
- `test_partial_unique_index_allows_multiple_null_keys`
- `test_backfill_dry_run_writes_no_rows`
- `test_backfill_apply_collapses_duplicates_and_keeps_oldest`

Each test uses `tempfile.NamedTemporaryFile(suffix=".db")` or
`tmp_path / "cortex.db"` — **never** `cortex.config.DB_PATH` for the
production DB.

```
python3 -m pytest ops/tests/test_cortex_dedup.py -q
python3 -m pytest ops/tests/ -q -k cortex
```

### V3 — Path existence checks

```
test -f cortex/memory.py && echo ok-memory
test -f cortex/engine.py && echo ok-engine
test -f scripts/cortex_dedup_backfill.py && echo ok-backfill
test -f ops/tests/test_cortex_dedup.py && echo ok-tests
```

### V4 — Dry-run backfill against a sample fixture

In the test, or as a one-shot verification step:

```
python3 scripts/cortex_dedup_backfill.py --db /tmp/cortex-sample.db --dry-run | head -c 2000
```

The fixture must be seeded by the test with 3–5 rows that
intentionally collide on the canonical key, and the dry-run output
must list the correct merge plan.

### V5 — Integration smoke against `/remember`

Using `pytest` + FastAPI test client (do **not** start a live
server):

- POST the same URL twice via `/remember` — assert one row in
  `memories`, `access_count=2`, `updated_at` advanced.
- POST with a `dedupe_hint` — assert it wins over URL
  canonicalization.

### V6 — Live Bob inspection (**[BOB_CLINE_ONLY]**, read-only)

```
timeout 20 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NULL;"
timeout 20 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" "SELECT COUNT(*) FROM memories WHERE dedupe_key IS NOT NULL;"
timeout 20 sqlite3 "$(python3 -c 'from cortex.config import DB_PATH; print(DB_PATH)')" "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_memories_dedupe_key';"
```

### V7 — Do NOT (until Matt approves)

```
# DO NOT RUN in this prompt:
#   python3 scripts/cortex_dedup_backfill.py --apply
#   sqlite3 <live_db> "DELETE FROM memories ..."
#   any schema migration that DROPs a column
```

The `--apply` run is documented as a `[NEEDS_MATT]` +
`[BOB_CLINE_ONLY]` follow-up.

## Required artifacts

1. **STATUS_REPORT.md** — dated entry
   `Cortex Dedup (UNIQUE/Upsert) Phase-1 Author+Test (<YYYY-MM-DD>)`:
   - Commit hashes.
   - Files touched.
   - Test pass counts.
   - Explicit `[NEEDS_MATT]` callout for the live `--apply`
     backfill, with the exact command and the required backup step.
2. **Verification receipt** —
   `ops/verification/<YYYYMMDD>-<HHMMSS>-cortex-dedup.txt` with V1–V6
   output.
3. **Commits** — suggested:
   - `feat(cortex): add dedupe_key column + partial UNIQUE index`
   - `feat(cortex): store_or_update upsert path`
   - `feat(cortex): dedup backfill script (dry-run default)`
   - `test(cortex): dedup writer + backfill`
4. **Push** — `git push origin main`.
5. **Summary** — final message lists changed files, commit hashes,
   and the exact `[NEEDS_MATT]` arm sequence for the backfill.

## Stop conditions / blockers

- `ALTER TABLE memories ADD COLUMN` returns `duplicate column name`
  on Bob — someone already started this work. Read the live schema,
  report, and stop (do not overwrite).
- The UNIQUE-index creation fails on the live DB because historical
  duplicate rows already carry the same derived key — that means the
  backfill must precede the index on Bob. In that case, ship only
  tasks 2/3/4 + unit tests; leave the index creation guarded behind
  a follow-up that runs after the backfill.
- Any step requires stopping Cortex on Bob — stop and escalate as
  `[NEEDS_MATT]`.
- Diff exceeds ~300 LOC net — split.

## Closing checklist

- [ ] Schema ALTER + partial UNIQUE index added.
- [ ] `store_or_update` + canonical-key helper added, unit-tested.
- [ ] Backfill script added with dry-run default.
- [ ] Tests pass locally.
- [ ] STATUS_REPORT + verification artifact + push landed.
- [ ] `[NEEDS_MATT]` arm sequence for live backfill documented.
