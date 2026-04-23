<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: data
Risk tier: medium
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# Cortex Embeddings — Local-First Vector Index for Memories (Cline-first, Phase-1 Author+Test)

## Owner / runtime context

- Repo-side work (schema + writer + tests + dry-run backfill) is
  runnable from any clean checkout of `origin/main`.
- Live embedding of Bob's production `memories` table is
  **[BOB_CLINE_ONLY]** and **[NEEDS_MATT]** — not executed from this
  prompt. This prompt authors + tests the code path; the one-shot
  backfill run on Bob is gated.
- Scope anchor: `docs/audits/2026-04-23-unfinished-setup-audit.md`
  §1 "Cortex cross-source dedup (UNIQUE/upsert) and embeddings" —
  this prompt closes the **embeddings** half only. Dedup lives in
  `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md`.
- **Order of operations**: the dedup prompt must land before any
  live backfill of embeddings, so we don't embed the same row
  multiple times. Document this ordering in STATUS_REPORT.

## Goal

Add a local-first semantic search layer over `memories.content` so
`engine.recall(question)` and `/memories/search` can blend keyword +
vector hits. Minimum viable shape:

1. A sibling `memory_embeddings` table (one-to-one with `memories`
   by `memory_id`, FK-style but SQLite-loose) holding
   `embedding BLOB NOT NULL`, `dim INTEGER NOT NULL`,
   `model TEXT NOT NULL`, `created_at TEXT NOT NULL`.
2. A small `EmbeddingWriter` abstraction in
   `cortex/embeddings.py` with pluggable providers:
   - **Local (default)**: Ollama `nomic-embed-text` (768-dim) via
     `http://127.0.0.1:11434/api/embeddings`.
   - **Fallback**: OpenAI `text-embedding-3-small` (1536-dim),
     used only if Ollama is unreachable AND `OPENAI_API_KEY` is
     present AND an opt-in env var `CORTEX_EMBED_OPENAI_OK=1` is
     set. Default posture: local-only.
   - **Null-provider** (for tests): returns a deterministic
     hash-based vector so unit tests don't need a network.
3. Hooks on `MemoryStore.store_or_update` (from the dedup prompt)
   and `MemoryStore.store` (legacy path) to enqueue embedding
   writes **asynchronously** to a bounded worker queue. Never block
   the write path on a provider call.
4. A query helper `MemoryStore.search_semantic(query, k=5)` that:
   - Embeds `query` via the same provider.
   - Loads all `memory_embeddings` rows for the current `model`,
     computes cosine similarity in-process (NumPy if available,
     pure-Python fallback otherwise), and returns the top-k
     `memory_id`s + scores.
5. A `scripts/cortex_embed_backfill.py` (dry-run default,
   `--apply` gated) that walks `memories` in batches of 100 and
   fills missing rows in `memory_embeddings`.

## Non-goals

- **Not** introducing a vector DB (FAISS, Chroma, pgvector, etc.).
  SQLite BLOB + in-process cosine is enough for current corpus
  size. A follow-up can swap providers once the writer path exists.
- **Not** changing the HTTP shape of `/memories/search` beyond an
  optional `semantic=1` flag. Default behavior unchanged.
- **Not** re-embedding on every `UPDATE` — only when `content`
  meaningfully changes (digest-compare `sha256(content[:4096])`
  against the stored digest).
- **Not** streaming partial embeddings or quantizing.
- **Not** doing the live Bob backfill from this prompt. Authoring +
  tests + dry-run only.
- **Not** touching `decisions`, `goals`, `improvement_log`.
- **Not** adding a new port or webhook.

## Safety gates

- **No secrets**: never print `OPENAI_API_KEY`. The OpenAI path is
  opt-in; default is local.
- **No destructive data changes**: `memory_embeddings` is a brand-new
  table; no ALTER on `memories`. Backfill script only writes new
  rows; it never deletes memory content.
- **No external sends / posts / messages.** Provider calls are
  model-inference only.
- **Ollama calls are `127.0.0.1` local only** by default. OpenAI
  calls require explicit `CORTEX_EMBED_OPENAI_OK=1` and a real key
  — absent either, the writer falls back to null-provider + logs
  `embedding_skipped=provider_unavailable`.
- **No recurring/scheduled jobs loaded in this prompt.** The
  embedding worker is an in-process async task spawned on Cortex
  startup *after* this prompt lands, and is gated by a config flag
  `CORTEX_EMBEDDINGS_ENABLED` that defaults to **false** in this
  PR. Flipping it to true on Bob is a separate `[NEEDS_MATT]`.
- **Bob runtime**: do not stop/start Cortex from this prompt. The
  code lands behind the disabled flag; Matt flips it after review.
- **No sudo. No new port. No interactive editors. No heredocs. No
  `tail -f`, no `--watch`.**
- **Bounded commands**: every provider call uses `timeout=10` at the
  client level (`httpx.AsyncClient(timeout=10)`). Tests use
  `respx` / `httpx.MockTransport`.

## Preconditions

Read in this order:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (§1 only)
- `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md` — read
  the *order of operations* note; embeddings assume dedup has
  landed.
- `cortex/memory.py` (full)
- `cortex/engine.py` (`/memories`, `/memories/search`, and the
  recall path)
- `cortex/config.py` (for `DB_PATH` and where to add
  `CORTEX_EMBEDDINGS_ENABLED`, `CORTEX_EMBED_OPENAI_OK`)
- `integrations/x_intake/main.py` Ollama-first-then-OpenAI pattern
  — reuse the same fallback shape to avoid inventing a new one.

Confirm git state:

```
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
git pull --ff-only
```

## Safe inspection steps (read-only, bounded)

```
python3 -c "import ast; ast.parse(open('cortex/memory.py').read()); print('ok')"
python3 -m py_compile cortex/memory.py cortex/engine.py cortex/config.py
grep -nE "recall|/memories/search|embedding" cortex/memory.py cortex/engine.py | head -n 40
grep -nE "OLLAMA|embedding|nomic" integrations/x_intake/main.py | head -n 20
```

On Bob only (**[BOB_CLINE_ONLY]**):

```
curl -sS -m 5 http://127.0.0.1:11434/api/tags | head -c 400
timeout 10 curl -sS http://127.0.0.1:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"hello"}' -H 'content-type: application/json' | head -c 400
```

If Ollama is unreachable on Bob, record that and proceed — this
prompt does not install Ollama models. The code is designed to
gracefully skip embedding writes when the provider is down.

## Implementation tasks (scoped to this one item)

1. **Schema: new `memory_embeddings` table**
   - Add to `cortex/memory.py`'s `_SCHEMA`:
     - `memory_id TEXT PRIMARY KEY`
     - `embedding BLOB NOT NULL`
     - `dim INTEGER NOT NULL`
     - `model TEXT NOT NULL`
     - `content_digest TEXT NOT NULL` (sha256 of `content[:4096]`)
     - `created_at TEXT NOT NULL DEFAULT (...)`
     - `updated_at TEXT NOT NULL DEFAULT (...)`
   - Index: `CREATE INDEX IF NOT EXISTS idx_memory_emb_model
     ON memory_embeddings(model);`
   - No FK (SQLite in this repo isn't run with `PRAGMA foreign_keys
     = ON`), but a defensive cleanup path deletes orphans on
     `memory` delete.

2. **`cortex/embeddings.py` — new module**
   - `class EmbeddingProvider(Protocol): async def embed(text: str)
     -> list[float]`.
   - `OllamaProvider` (default), `OpenAIProvider` (opt-in),
     `NullProvider` (deterministic hash, test-only).
   - `async def pack_vector(vec: list[float]) -> bytes` using
     `struct.pack('<' + 'f'*len(vec), *vec)`; `unpack_vector` for
     the reverse. Both pure functions, unit-testable.
   - Global factory `get_provider()` reads config + env.

3. **Writer hook**
   - `MemoryStore.store(...)` and
     `MemoryStore.store_or_update(...)` enqueue
     `(memory_id, content)` on an `asyncio.Queue` owned by the
     Cortex engine. Writer task:
     - Pulls from queue, calls `provider.embed(content[:4096])`
       with `timeout=10`.
     - On success: `INSERT OR REPLACE INTO memory_embeddings`.
     - On exception or timeout: log + continue. **Never** retry
       more than once per memory per startup (tracked in-memory).
   - Gate: if `CORTEX_EMBEDDINGS_ENABLED != "1"`, the enqueue is a
     no-op. Default in this PR is **disabled**.

4. **Query path**
   - `MemoryStore.search_semantic(query, k=5)`:
     - Embed query via provider.
     - `SELECT memory_id, embedding FROM memory_embeddings WHERE
       model = ?` — iterate, compute cosine similarity, keep top-k
       in a bounded heap.
     - Return `[{"memory_id": ..., "score": ...}, ...]`.
   - Extend `/memories/search?semantic=1` in `engine.py` to merge
     semantic hits with the existing keyword path (union by
     `memory_id`, rank by weighted sum — simple and auditable).

5. **Backfill script**
   - `scripts/cortex_embed_backfill.py`:
     - `--db`, `--model` (default `nomic-embed-text`),
       `--provider` (`ollama|openai|null`, default `ollama`),
       `--dry-run` (default), `--apply`.
     - Processes in batches of 100; writes progress every batch to
       stdout.
     - Respects the same `CORTEX_EMBED_OPENAI_OK` gate.
     - On `--apply`, writes a summary JSON to
       `ops/verification/<YYYYMMDD-HHMMSS>-cortex-embed-backfill.json`.

## Full verification / test checklist (bounded)

### V1 — Static

```
python3 -m py_compile cortex/memory.py cortex/engine.py cortex/embeddings.py scripts/cortex_embed_backfill.py
git diff --stat
```

### V2 — Unit tests under `ops/tests/`

Add `ops/tests/test_cortex_embeddings.py` with at minimum:

- `test_pack_unpack_roundtrip_preserves_floats`
- `test_null_provider_is_deterministic`
- `test_writer_is_noop_when_disabled`
- `test_writer_writes_row_when_enabled_with_null_provider`
- `test_writer_skips_on_provider_timeout`
- `test_search_semantic_returns_top_k_by_cosine`
- `test_backfill_dry_run_writes_no_rows`
- `test_backfill_apply_populates_missing_rows_only`

Tests use `NullProvider` + a `tmp_path / "cortex.db"` — no network,
no real Ollama, no real OpenAI.

```
python3 -m pytest ops/tests/test_cortex_embeddings.py -q
python3 -m pytest ops/tests/ -q -k embedding
```

### V3 — Path existence

```
test -f cortex/embeddings.py && echo ok-emb
test -f scripts/cortex_embed_backfill.py && echo ok-backfill
test -f ops/tests/test_cortex_embeddings.py && echo ok-tests
```

### V4 — Dry-run backfill against a sample fixture

Seed a `/tmp/cortex-sample.db` in the test with 10 `memories` rows,
run backfill `--dry-run`, and assert the reported count equals the
number of missing embeddings. Also run `--apply` against the same
temp DB with the `NullProvider` and assert 10 rows land in
`memory_embeddings`.

### V5 — Integration smoke against `/memories/search?semantic=1`

Using FastAPI test client:
- Seed 3 memories, all embedded via `NullProvider` in the test.
- Call `/memories/search?semantic=1&q=...` and assert ordered
  response + 200 status.

### V6 — Live Ollama probe (**[BOB_CLINE_ONLY]**, optional)

Only if Matt is running this on Bob, capture:

```
timeout 10 curl -sS http://127.0.0.1:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}' -H 'content-type: application/json' | head -c 600
```

If it fails, record the error in the verification artifact. The
code path gracefully degrades.

### V7 — Do NOT (until Matt approves)

```
# DO NOT RUN in this prompt:
#   python3 scripts/cortex_embed_backfill.py --apply  (on live DB)
#   export CORTEX_EMBEDDINGS_ENABLED=1                (flipping the flag)
#   any prompt or launchd job that starts a long-lived embedder
```

## Required artifacts

1. **STATUS_REPORT.md** — dated entry
   `Cortex Embeddings Phase-1 Author+Test (<YYYY-MM-DD>)`:
   - Commits landed.
   - Files touched.
   - Test summary.
   - Default posture: **disabled** via `CORTEX_EMBEDDINGS_ENABLED=0`.
   - Explicit `[NEEDS_MATT]` for: (a) run the
     `cortex_dedup_backfill.py --apply` from the dedup prompt
     FIRST, (b) flip the env flag on Bob, (c) run
     `cortex_embed_backfill.py --apply`.
2. **Verification receipt** —
   `ops/verification/<YYYYMMDD>-<HHMMSS>-cortex-embeddings.txt`
   with V1–V5 output (V6 only if run on Bob).
3. **Commits** — suggested:
   - `feat(cortex): memory_embeddings table + schema`
   - `feat(cortex): embeddings module (ollama/openai/null)`
   - `feat(cortex): async writer hook gated by feature flag`
   - `feat(cortex): semantic search endpoint flag`
   - `feat(cortex): embed backfill script (dry-run default)`
   - `test(cortex): embeddings + backfill`
4. **Push** — `git push origin main`.
5. **Summary** — final message lists changed files, commit hashes,
   and the exact `[NEEDS_MATT]` ordered arm sequence:
   1. Dedup backfill `--apply` (from the dedup prompt).
   2. `export CORTEX_EMBEDDINGS_ENABLED=1` in Cortex's env/.env.
   3. Restart Cortex service/container.
   4. `python3 scripts/cortex_embed_backfill.py --apply
      --provider ollama`.

## Stop conditions / blockers

- The dedup prompt has not landed yet — stop and report; embeddings
  without dedup will store duplicate vectors.
- `sqlite3` in the test environment lacks `BLOB` support (shouldn't
  happen on stock Python) — stop.
- Ollama unreachable on Bob AND OpenAI opt-in flag unset AND Matt
  explicitly wants a live backfill — out of scope here; leave
  `[FOLLOWUP]`.
- Any step would require `sudo`, new port, or pulling a new model
  weights file — stop; those are infra, not repo-safe.
- Diff exceeds ~400 LOC net — split across multiple commits but
  land them in the same PR.

## Closing checklist

- [ ] `memory_embeddings` schema added.
- [ ] `cortex/embeddings.py` module with three providers.
- [ ] Writer hook gated by `CORTEX_EMBEDDINGS_ENABLED` (default off).
- [ ] `/memories/search?semantic=1` path.
- [ ] Backfill script with dry-run default.
- [ ] All tests pass with `NullProvider`.
- [ ] STATUS_REPORT + verification artifact + push landed.
- [ ] Ordered `[NEEDS_MATT]` arm sequence documented verbatim.
