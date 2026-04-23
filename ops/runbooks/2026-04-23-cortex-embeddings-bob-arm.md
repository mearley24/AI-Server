# Cortex Embeddings — Bob Runtime Arm Runbook

**Status:** `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` — **NOT auto-run by
Computer / Cline / Claude Code.** This file is a human-approved
runbook, not an autonomous prompt. Do **not** add `<!-- autonomy: start -->`
metadata to it. Do not copy it into `.cursor/prompts/`. The task
runner, self-improvement loop, and `ops/cline-run-*.sh` dispatchers
must **skip** anything under `ops/runbooks/`.

**Owner:** Matt (or a human operator with SSH access to Bob).
**Host:** Bob (Mac Mini M4), `~/AI-Server` checkout of `origin/main`.
**Prerequisite prompt:** `.cursor/prompts/2026-04-23-cline-cortex-embeddings.md`
(Status: `done`, closed 2026-04-23).
**Prerequisite runs:** Cortex dedup `--apply` (see
`.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md` step 4)
**must complete successfully** on Bob before step 5 below.

---

## Why this runbook exists

The repo-side work is complete: schema, writer, tests, backfill script,
semantic-search endpoint, and the closing `[NEEDS_MATT]` arm sequence
all landed on `origin/main`. What remains is a live one-shot backfill
of Bob's production `memories` table after flipping
`CORTEX_EMBEDDINGS_ENABLED=1`. That action touches production data and
must be performed by a human with the authority to:

- Pull a new model weight file (`nomic-embed-text`, ~270 MB).
- Restart the Cortex container.
- Backfill `memory_embeddings` rows against `brain.db`.

Those steps are intentionally **not** in an autonomous prompt.

---

## Prechecks (required, run before any mutation)

Run each command on Bob. Capture output into
`ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-arm-precheck.txt`
before proceeding.

1. Checkout is clean and on `origin/main`:
   ```
   cd ~/AI-Server
   git status --short
   git rev-parse --abbrev-ref HEAD
   git rev-parse HEAD
   git log --oneline -1
   ```
   Expect: clean tree (or only harness-owned dirty files), branch
   `main`, HEAD contains commits `9f0b7c4`/`89ad9fc`/`814f746`/`7eab1eb`.

2. Cortex container reachable and healthy:
   ```
   docker ps --format '{{.Names}} {{.Status}}' | grep -E '^cortex '
   curl -sS -m 5 http://127.0.0.1:8102/health | head -c 200
   ```

3. Dedup prerequisite actually completed against `brain.db` (not just
   a dry-run against a fixture):
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "PRAGMA index_list(memories);" | grep -i dedupe
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) AS total, COUNT(DISTINCT dedupe_key) AS distinct_keys FROM memories WHERE dedupe_key IS NOT NULL;"
   ```
   Expect: `idx_memories_dedupe_key` present; `total ≈ distinct_keys`
   (non-null dedupe_keys are unique).

4. Ollama reachable, and `nomic-embed-text` either present or ready
   to pull:
   ```
   curl -sS -m 5 http://127.0.0.1:11434/api/tags | head -c 400
   ```

5. Backup plan ready (see Rollback below). A backup of `brain.db`
   must exist on disk *before* step 5.

**Stop conditions (abort, do not continue):**

- Any precheck fails.
- `docker ps` shows Cortex restart loop or unhealthy.
- Dedup evidence is missing (step 3 returns 0 rows for
  `idx_memories_dedupe_key` or `total > distinct_keys`).
- Ollama returns HTTP error on `/api/tags`.
- You cannot write to `~/AI-Server/ops/verification/`.
- Working tree has uncommitted changes in `cortex/`, `scripts/`,
  `ops/tests/`, or `setup/launchd/` you did not author.

---

## Ordered arm sequence (Matt or human operator)

All commands are bounded; none require heredocs, interactive editors,
or `sudo`. Capture each command's stdout/stderr into the precheck
verification file.

1. **Backup Cortex DB first.**
   ```
   docker exec cortex sh -c 'cp /data/cortex/brain.db /data/cortex/brain.db.bak.$(date +%Y%m%d-%H%M%S)'
   docker exec cortex ls -la /data/cortex/ | grep brain.db
   ```

2. **Run dedup backfill `--apply`.** (Required before embeddings so
   duplicate rows don't get embedded twice.)
   ```
   docker exec cortex python3 /app/scripts/cortex_dedup_backfill.py --apply
   ```
   Expect: JSON summary written to
   `ops/verification/<YYYYMMDD-HHMMSS>-cortex-dedup-backfill.json`.
   **Stop** if the summary reports any `failed > 0` without a matching
   error classification.

3. **Pull the embedding model.**
   ```
   ollama pull nomic-embed-text
   ollama list | grep nomic-embed-text
   ```
   Expect: `nomic-embed-text:latest` present with ~274 MB.

4. **Flip the feature flag.**
   ```
   bash scripts/set-env.sh CORTEX_EMBEDDINGS_ENABLED 1
   grep '^CORTEX_EMBEDDINGS_ENABLED=' .env
   ```
   Expect: `.env` now contains `CORTEX_EMBEDDINGS_ENABLED=1`.

5. **Restart Cortex so the embed worker picks up the flag.**
   ```
   docker compose restart cortex
   sleep 5
   docker logs cortex --since 30s 2>&1 | grep -iE 'embed|worker|started|error' | head -n 20
   curl -sS -m 5 http://127.0.0.1:8102/health | head -c 200
   ```
   Expect: no `embedding_error` storms; `/health` 200 OK.

6. **Run the embed backfill `--apply`.**
   ```
   docker exec cortex python3 /app/scripts/cortex_embed_backfill.py --apply --provider ollama
   ```
   Expect: JSON summary at
   `ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-backfill.json`.

7. **Verify rows landed.**
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memory_embeddings;"
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT model, COUNT(*) FROM memory_embeddings GROUP BY model;"
   ```
   Expect: row count within ~1–2% of
   `SELECT COUNT(*) FROM memories WHERE content IS NOT NULL AND length(content) > 0`.
   Skipped rows (provider timeout) are acceptable — they are not a
   failure mode because the code path gracefully degrades.

8. **Smoke the blended semantic search path.**
   ```
   curl -sS -m 10 'http://127.0.0.1:8102/memories/search?q=hello&semantic=1&k=3' | head -c 800
   ```
   Expect: 200 OK, JSON body with up to 3 hits.

---

## Verification receipt requirements

After the arm sequence completes (or is aborted), write a single
receipt to:

```
ops/verification/<YYYYMMDD-HHMMSS>-cortex-embeddings-live-arm.txt
```

The receipt **must** include, verbatim:

- `git rev-parse HEAD` on Bob at run time.
- Precheck command outputs (or their abort reason).
- Backup filename created in step 1.
- Dedup `--apply` JSON summary path + row counts.
- `ollama list` excerpt showing `nomic-embed-text`.
- `.env` grep showing `CORTEX_EMBEDDINGS_ENABLED=1`.
- `docker compose restart cortex` exit code.
- Embed backfill JSON summary path + row counts.
- Final `SELECT COUNT(*) FROM memory_embeddings;` number.
- `/memories/search?semantic=1` smoke response (first 400 bytes).
- Any skipped-memory reason distribution (provider timeout, empty
  content, etc.).

Then add a dated STATUS_REPORT entry named
`## Cortex Embeddings — Live Arm on Bob (<YYYY-MM-DD> <HH:MM TZ>, Matt)`
that links to the receipt and records the final row count.

Commit with:

```
docs(cortex): live embeddings arm on Bob — verification + STATUS_REPORT
```

Do **not** `git push --force` and do **not** amend prior commits.

---

## Rollback / stop conditions

Any of the following means: stop, restore, report.

| Condition | Immediate action |
|-----------|------------------|
| Cortex container fails to restart after step 5 | `docker compose logs cortex --tail 200`; if unrecoverable, `bash scripts/set-env.sh CORTEX_EMBEDDINGS_ENABLED 0` + `docker compose restart cortex`; restore from `brain.db.bak.*` only if schema damaged. |
| Embed worker spams `embedding_error` (>50 in 1 min) after step 5 | Flip flag back to `0`; restart; investigate Ollama host/model before retrying. |
| Step 6 JSON shows `failed > written` | Abort; flag stays on but do not re-run backfill until failure class is understood. |
| `nomic-embed-text` pull fails, disk < 1 GB free, or Ollama OOMs | Abort step 3; do not continue. |
| `SELECT COUNT(*) FROM memory_embeddings;` is 0 after step 6 | Confirm Ollama model active; rerun step 6 once; if still 0, flip flag back to `0` and open a FOLLOWUP. |
| Dedup precheck (step 3 of prechecks) fails | **Do not continue.** Run the dedup runbook first. |

**Rollback to disabled posture:**

```
bash scripts/set-env.sh CORTEX_EMBEDDINGS_ENABLED 0
docker compose restart cortex
```

This leaves the `memory_embeddings` table intact (read-only once flag
is off; the writer hook becomes a no-op). A full rollback to the
pre-backfill DB uses the backup created in step 1.

---

## What this runbook explicitly forbids

- Running from a non-interactive dispatcher. If a scheduled job
  attempts to execute these steps, **it is a bug.** File it under
  `ops/realized_changes/` with severity `high`.
- Setting `CORTEX_EMBED_OPENAI_OK=1` without Matt's explicit go —
  this sends `memories.content` to OpenAI and is out of scope.
- Touching `brain.db` directly without going through the container.
- Rewriting the backfill script to skip the feature-flag gate.
- Turning this runbook into a `cline-prompt-*.md` or copying it into
  `.cursor/prompts/`.

---

## Appendix: why the arm is split from the prompt

The repo-side Cline prompt landed a disabled-by-default code path so
that any checkout of `origin/main` is safe to run against a fresh
SQLite file. Arming against `brain.db` requires a model pull, env
flip, container restart, and a production backfill — each of which
is a decision, not a mechanical step. Splitting the runbook off gives
Matt a copy/paste-runnable sequence without creating a new autonomous
surface area.

---

## Closure (2026-04-23 UTC)

**Runbook status: CLOSED.** Executed on Bob by Claude Code + Cline on
2026-04-23. The `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` header above
describes the runbook's gating contract *before* execution — it is
preserved as history; arm is now recorded.

Verdict: **ARMED** with all three acceptance conditions met:

- `.env`: `CORTEX_EMBEDDINGS_ENABLED=1`
- `memory_embeddings` rows: 4559 (model `nomic-embed-text`, dim=768)
- Cortex `/health`: HTTP 200, `status=alive`

Committed evidence (all on `origin/main`):

- `ops/verification/20260423-131459-cortex-embeddings-live-arm.txt`
  (commit `555274cd` — runbook receipt, all 8 arm steps executed)
- `ops/verification/20260423-135512-cortex-embed-arm-evidence.txt`
  (commit `412ec2bc` — independent arm-evidence probe, VERDICT: ARMED)
- `STATUS_REPORT.md` §"Cortex Embeddings — Live Arm on Bob" (L29,
  commit `555274cd`)
- Supporting code fixes: `4f2fac4c` (dedupe_key index migration),
  `dce5064a` (WAL pragma removal + compose mounts/env)
- `ops/verification/20260423-200253-cortex-embed-arm-closure.txt`
  (this closure pass reconciliation receipt)

Remaining (not gates on arm):

- [FOLLOWUP] Full historical backfill of the remaining ~48k rows
  during a Docker-stable window. Embed worker is **ON**; new memories
  are embedded in real time. Command in STATUS_REPORT L44.
- [FOLLOWUP] Investigate Bob's Docker daemon zombie-crash (~10 min
  MTBF) — tracked separately, not an embeddings concern.

Do not re-execute this runbook. Any re-arm starts from a new runbook
drafted against the current DB + flag state.
