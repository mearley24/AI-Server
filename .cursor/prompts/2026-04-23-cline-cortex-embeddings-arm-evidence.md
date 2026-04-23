<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger:   manual
Status:    done
<!-- autonomy: end -->

<!--
Closed 2026-04-23 UTC. Executed on Bob by Cline; verdict ARMED with all
three conditions met (CORTEX_EMBEDDINGS_ENABLED=1, 4559 memory_embeddings
rows nomic-embed-text, /health 200). Step 5 receipts and STATUS_REPORT
entry already committed upstream to the runbook execution (commit
555274cd). Evidence artifacts:
  - ops/verification/20260423-135512-cortex-embed-arm-evidence.txt
    (commit 412ec2bc — VERDICT: ARMED)
  - ops/verification/20260423-131459-cortex-embeddings-live-arm.txt
    (commit 555274cd — runbook live-arm receipt)
  - STATUS_REPORT.md §"Cortex Embeddings — Live Arm on Bob" (L29)
    (commit 555274cd)
  - ops/verification/20260423-200253-cortex-embed-arm-closure.txt
    (this closure pass reconciliation receipt)
Do not re-run this prompt. The runtime arm gate is closed; only the
historical-backfill [FOLLOWUP] remains and the embed worker is ON.
-->

# Cortex Embeddings — Bob Live-Arm Evidence Capture (read-only)

## Goal

The parent agent was told the runtime arm runbook
`ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md` was executed
on Bob, but the repo currently contains **no live-arm verification
receipt, no STATUS_REPORT live-arm entry, and no live backfill JSON
from `/data/cortex/brain.db`**. The only `*-cortex-embed-backfill.json`
artifact on disk points at a pytest tempdir
(`pytest-of-bob/pytest-8/...`), i.e. the 8/8 author+test run — not a
live backfill.

This prompt is **read-only**. It asks Cline (on Bob) to capture
whatever live evidence already exists on the host and commit it into
the repo, or to explicitly record that the runbook has **not** been
run yet. It must **not** execute the runbook. The runbook is
`[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` and remains gated to Matt.

## Preconditions

- Running on Bob (`~/AI-Server`), branch `main`, clean tree (or only
  harness-owned dirty files).
- Read `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md` first.
- Read current `STATUS_REPORT.md` §"Cortex Embeddings Reconciliation".
- Do **not** pull Docker images, do **not** flip env vars, do **not**
  call `ollama pull`, do **not** restart containers, do **not** run
  `scripts/cortex_embed_backfill.py --apply`.

## Operating mode

- AUTO_APPROVE: true (read-only; all commands are bounded probes).
- Hard bans: no heredocs, no interactive editors, no long-running
  watch modes, no `sudo`, no port changes, no secrets read, no
  external messages, no Docker pulls/builds, no `docker compose
  restart`, no `ollama pull`, no `--apply` runs of any backfill
  script, no mutations to `.env`.
- Verification-to-file-then-commit contract: tee each probe into
  `ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-arm-evidence.txt`,
  commit, push.

## Step plan

1. **Header.** Write UTC timestamp, host, `git rev-parse HEAD`,
   `git rev-parse --abbrev-ref HEAD`, and
   `git status --short` into the evidence file.

2. **Scan repo-owned artifacts for a prior live-arm run.** Record
   the output of each, one at a time:
   ```
   ls -la ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md
   ls -la ops/verification/ | grep -iE 'cortex-embed|embeddings-live|embed-arm'
   grep -n 'Cortex Embeddings' STATUS_REPORT.md | head -n 20
   grep -n 'live.*arm\|Live Arm' STATUS_REPORT.md | head -n 20
   git log --oneline --all -- ops/verification STATUS_REPORT.md .cursor/prompts/2026-04-23-cline-cortex-embeddings.md | head -n 30
   ```

3. **Probe the live host (read-only).** None of these mutate state.
   Bound each with `-m 5` / `--tail N` / `| head -c N`. If a command
   errors (e.g. Cortex down, Ollama down), capture the error and
   **continue**; do not try to fix it.
   ```
   docker ps --format '{{.Names}} {{.Status}}' | grep -E '^cortex ' || echo 'cortex container not running'
   curl -sS -m 5 http://127.0.0.1:8102/health | head -c 200 || echo 'cortex /health probe failed'
   grep -E '^CORTEX_EMBEDDINGS_ENABLED=' .env || echo 'CORTEX_EMBEDDINGS_ENABLED not set in .env'
   curl -sS -m 5 http://127.0.0.1:11434/api/tags | head -c 400 || echo 'ollama /api/tags probe failed'
   ```
   If Cortex is up, additionally:
   ```
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT COUNT(*) FROM memory_embeddings;" 2>&1 | head -n 5
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT model, COUNT(*) FROM memory_embeddings GROUP BY model;" 2>&1 | head -n 10
   docker exec cortex sqlite3 /data/cortex/brain.db "PRAGMA index_list(memories);" 2>&1 | head -n 20
   docker exec cortex ls -la /data/cortex/ 2>&1 | grep -E 'brain\.db' | head -n 10
   ```
   If Cortex is down, write "cortex_down=true" into the evidence
   file and skip these four commands.

4. **Classify.** Based on step 3's output, write **one** of these
   verdicts verbatim into the evidence file as a final `## Verdict`
   section:

   - `VERDICT: ARMED` — all three hold: (a) `.env` contains
     `CORTEX_EMBEDDINGS_ENABLED=1`, (b) `memory_embeddings` table
     has `> 0` rows, and (c) Cortex `/health` returns 200. In this
     case also write the row count and model distribution.
   - `VERDICT: NOT_ARMED` — `.env` has `=0` (or missing) **or**
     `memory_embeddings` count is 0. Runbook has not been executed.
   - `VERDICT: PARTIAL` — env flipped but no rows, or rows present
     but `/health` not 200. Include which subcondition failed.
   - `VERDICT: UNKNOWN` — Cortex not running, so we cannot probe the
     DB. Record `cortex_down=true` and stop.

5. **If `VERDICT: ARMED`**, also write a receipt at
   `ops/verification/<YYYYMMDD-HHMMSS>-cortex-embeddings-live-arm.txt`
   containing the verbatim requirements from the runbook's
   "Verification receipt requirements" section (see lines ~163-183
   of `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md`). Then
   append a dated STATUS_REPORT entry named
   `## Cortex Embeddings — Live Arm on Bob (<YYYY-MM-DD> <HH:MM UTC>, Cline)`
   that links to the receipt and records the final row count.
   Commit message:
   ```
   docs(cortex): live embeddings arm on Bob — verification + STATUS_REPORT
   ```

   **If verdict is anything else**, do **not** edit STATUS_REPORT
   live-arm gate, do **not** touch `[NEEDS_MATT]` markers, do **not**
   execute runbook steps. Only the evidence file is committed.

6. **Commit & push.** Stage only:
   - `ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-arm-evidence.txt`
   - (if `ARMED`) the live-arm receipt and the STATUS_REPORT edit.

   Do not stage `.claude/`, `.mcp.json`, `CLAUDE.md`, `.env`, or any
   file under `cortex/`, `scripts/`, or `ops/runbooks/`.

## Guardrails

- **Hard ban:** executing any step of
  `ops/runbooks/2026-04-23-cortex-embeddings-bob-arm.md`. The
  runbook is `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` and this prompt does
  **not** inherit that authority.
- **Hard ban:** any `--apply` invocation of a backfill script.
- **Hard ban:** mutating `.env`, touching `brain.db` outside the
  container, opening ports, rewriting the feature-flag gate.
- **Hard ban:** flipping STATUS_REPORT `[NEEDS_MATT]` markers unless
  `VERDICT: ARMED`. Stale markers with missing evidence must stay.
- No retry loops. One probe, capture, move on.

## Final report

The evidence file
`ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-arm-evidence.txt`
must contain:

- Header (timestamp, host, HEAD, branch, status).
- Step 2 grep/ls/log output (repo-owned artifact scan).
- Step 3 host probe output (container, /health, .env flag, ollama,
  sqlite row count, index list, brain.db listing).
- `## Verdict` section with one of {ARMED, NOT_ARMED, PARTIAL,
  UNKNOWN} and the supporting numbers.
- Explicit non-actions section ("did NOT pull ollama, did NOT flip
  env, did NOT restart cortex, did NOT run --apply").

Push the commit(s) to `origin/main` and stop. If `VERDICT` is
anything other than `ARMED`, the runbook remains the next
`[NEEDS_MATT]` gate; do not draft a new runbook or prompt.
