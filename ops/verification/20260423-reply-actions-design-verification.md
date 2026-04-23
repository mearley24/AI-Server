# Reply-Actions Design Verification

**Timestamp**: 2026-04-23  
**Type**: Audit-only verification (no runtime changes)  
**Related artifacts**:
- `docs/audits/x-intake-deep-dive-audit.md`
- `config/reply_actions.schema.json`

---

## Checks Performed

### Files Read (audit scope)

| File | Purpose |
|------|---------|
| `integrations/x_intake/main.py` | Listener, LLM routing, reply send path, action queue thresholds |
| `integrations/x_intake/post_fetcher.py` | Fetch fallback chain, thread context |
| `integrations/x_intake/analyzer.py` | LLM analysis pipeline |
| `integrations/x_intake/queue_db.py` | SQLite schema, status inference |
| `integrations/x_intake/action_queue.py` | High-relevance action enqueue |
| `integrations/x_intake/video_transcriber.py` | yt-dlp + Whisper path |
| `integrations/x_intake/transcript_analyst.py` | Deep transcript analysis |
| `integrations/x_alpha_collector/collector.py` | RSSHub poller, SeenPostDB |
| `cortex/bluebubbles.py` | Webhook normalization, inbound routing, send client |
| `cortex/engine.py` | /remember endpoint, background loops |
| `cortex/memory.py` | MemoryStore schema, remember(), query() |
| `notification-hub/main.py` | Outbound dispatcher, allowlist |
| `docker-compose.yml` | Service definitions, volumes, resource limits |

### Greps Run

| Pattern | Result |
|---------|--------|
| `_PROCESSED_URLS` | Found `main.py:64-84` — in-memory dedup dict confirmed |
| `is_reply` | Found `post_fetcher.py` — parent hydration trigger confirmed |
| `fetch_thread_context=False` | Found `post_fetcher.py:479` — recursion guard confirmed |
| `events:imessage` | Found `main.py:880`, `cortex/bluebubbles.py:569` — Redis channel confirmed |
| `in_reply_to` | Found `cortex/bluebubbles.py:313` — extracted but not consumed |
| `reply_action` | Not found — confirms no existing implementation |
| `action_router` | Not found — confirms not implemented |
| `/remember` | Found `main.py:568`, `cortex/engine.py:283` — write path confirmed |
| `UNIQUE.*url` | Not found in `cortex/memory.py` — duplicate write gap confirmed |
| `embedding` | Not found in cortex/ — no vector store confirmed |
| `action_id` | Not found in x_intake — confirms per-message ID not yet implemented |
| `SeenPostDB` | Found `x_alpha_collector/collector.py:69` — 7-day JSON dedup confirmed |
| `diygod/rsshub:latest` | Found `docker-compose.yml` — unpinned image confirmed |

---

## Architecture Assumptions Made

1. **BlueBubbles is the canonical inbound channel** — all iMessage/BlueBubbles traffic flows through `cortex/bluebubbles.py` webhook → Redis. Assumption: the legacy iMessage bridge at `host.docker.internal:8199` is outbound-only and not the inbound path for new deployments. _Confidence: High — code confirms inbound is BlueBubbles webhook._

2. **Cortex /remember is the only write target from x-intake** — no direct SQLite writes outside of queue_db and action_queue. _Confidence: High — grep of `brain.db` from x_intake directory returned no hits._

3. **Ollama is the primary LLM** — qwen3:8b at `OLLAMA_HOST=http://192.168.1.189:11434` (external host). Latency estimate of 4–12 s assumes GPU inference on M4; if Ollama is on a different host or CPU-only, latency may be higher. _Confidence: Medium — env var suggests external host, exact hardware not confirmed._

4. **No existing reply callback infrastructure** — grep for `action_id`, `reply_action`, `action_router` returned no hits. The design starts from scratch. _Confidence: High._

5. **x-alpha-collector is not Dockerized** — no compose service found; appears to run as a host process or is not currently active. _Confidence: Medium — no service found, `data/x_alpha_seen.json` exists (2B file), collector logic exists._

---

## Open Questions

| ID | Question | Impact |
|----|----------|--------|
| OQ-01 | Is Ollama running on Bob (M4 GPU) or a separate host? The `OLLAMA_HOST` env var suggests `192.168.1.189` — is this Bob's local IP or another machine? Affects latency estimates significantly. | Latency targets |
| OQ-02 | Is x-alpha-collector currently running as a launchd agent or Docker service? The compose file has no entry for it, but the watchlist.json is populated. | Source coverage |
| OQ-03 | Is the iMessage bridge at `host.docker.internal:8199` still active alongside BlueBubbles, or has it been fully replaced? x-intake's `_send_reply` still targets the bridge URL. | Reply routing |
| OQ-04 | Does `cortex/memory.py` have any periodic dedup/prune job beyond TTL expiry? The missing UNIQUE constraint means duplicates accumulate. | Memory noise |
| OQ-05 | What is the actual p95 latency measured at runtime? The audit estimates are based on code inspection only. | Phase 6 metric calibration |
| OQ-06 | Is `x-intake-lab` (port 8103) the intended testbed, or should the new testbed be fully separate from it? | Testbed design |

---

## Phased Implementation Plan

### Phase 0 — Audit Only (this phase — COMPLETE)
**Artifacts**:
- `docs/audits/x-intake-deep-dive-audit.md` ✓
- `config/reply_actions.schema.json` ✓
- `ops/verification/20260423-reply-actions-design-verification.md` ✓ (this file)
- `STATUS_REPORT.md` entry ✓

**Gate**: Matt reviews audit + schema; confirms action catalog and safety rules before Phase 1.

---

### Phase 1 — Design Sign-Off
**Artifacts**:
- Finalized `config/reply_actions.schema.json` (any changes from Matt's review)
- `docs/testbed-promotion.md` — promotion flow for testbed → production
- Updated audit with OQ answers

**Owner review checkpoint**: Matt confirms action catalog, safety rules (especially confirm-required list), expiry window, and testbed architecture.

**Gate**: Matt replies "LGTM on reply-actions design" or equivalent commit comment.

---

### Phase 2 — Testbed Container
**Artifacts**:
- `docker/testbed/Dockerfile.testbed` — pinned base image, no secrets baked in
- `docker/testbed/docker-compose.testbed.yml` — isolated network, resource limits, ro mounts
- `scripts/testbed-teardown.sh <prototype_id>` — stop + rm + prune volumes/networks
- `docs/testbed-promotion.md` — promotion path docs

**No production compose changes.**

**Gate**: Testbed starts, passes network-isolation smoke test (`curl google.com` should fail), teardown script leaves no dangling volumes.

---

### Phase 3 — Reply Parser
**Artifacts**:
- `integrations/x_intake/reply_parser.py` — pure function: `parse_reply(raw: str, schema: dict) -> ParsedReply | None`
- `tests/test_reply_parser.py` — unit tests covering: numeric direct, prefixed forms, case variants, ambiguous multi-token, unrecognized, empty

**Not wired to execution.** Parser is imported but not called by any live path.

**Gate**: All unit tests pass. No integration changes required.

---

### Phase 4 — Action Router
**Artifacts**:
- `integrations/x_intake/reply_actions/__init__.py`
- `integrations/x_intake/reply_actions/router.py` — resolves `(message_id, parsed_slot) → action handler`; dry-run mode first
- `integrations/x_intake/reply_actions/handlers/*.py` — one module per action key
- `integrations/x_intake/reply_actions/audit_log.py` — JSONL writer to `data/x_intake/reply_action_audit.jsonl`
- `integrations/x_intake/action_id_store.py` — SQLite-backed store for `(action_id → message context, expiry)`

**Wired into `cortex/bluebubbles.py`** inbound path: when a reply matches a known action_id, route to handler instead of re-analyzing.

**Dry-run default**: Feature flag `REPLY_ACTIONS_ENABLED=false` in `.env`; all routing logs but does not execute handlers.

**Gate**: Dry-run log shows correct routing for test replies. No handler executes yet.

---

### Phase 5 — Self-Improvement Integration
**Artifacts**:
- `ops/self_improvement/reply_action_card.md` — card template for action outcomes
- Update `ops/learning_miner.py` to scan `data/x_intake/reply_action_audit.jsonl`
- `ops/verification/<stamp>-reply-actions-learning-integration.md` — verification report

**Gate**: Miner picks up action outcomes; digest includes reply-action stats.

---

### Phase 6 — Production Rollout
**Artifacts**:
- `REPLY_ACTIONS_ENABLED=true` in `.env` (via `scripts/set-env.sh`)
- Per-action feature flags in `config/reply_actions.schema.json` (`enabled: true/false`)
- `ops/verification/<stamp>-reply-actions-production.md` — rollout verification

**Default**: Rollout is per-action, feature-flagged. Start with `build_card` (slot 1) and `save_to_cortex` (slot 4) — lowest risk. `prototype` (slot 3) last.

**Rollback**: `bash scripts/set-env.sh REPLY_ACTIONS_ENABLED false && docker restart x-intake`

**Gate**: 7-day audit log shows false-action-rate < 2%, duplicate rate < 1%, no unintended side effects.

---

## Success Metrics (Phase 6 judgement criteria)

| Metric | Definition | Target |
|--------|-----------|--------|
| Median tweet-to-card latency | Time from Redis event receipt to iMessage bridge POST | ≤ 5 s |
| p95 tweet-to-card latency | 95th percentile of above | ≤ 15 s |
| % links with useful card | Outbound messages where summary ≥ 30 words AND (action ≠ none OR relevance ≥ 40 OR type ≠ info) | ≥ 80% |
| Duplicate outbound rate | % outbound messages within 24h with identical (url, summary) | < 1% |
| False action rate | % executed actions flagged by Matt as wrong-action-for-reply | < 2% |
| Time-to-prototype | Wall-clock minutes from Reply 3 reply to running, isolated testbed container | ≤ 3 min |
| Rollback safety | Every phase documented with a single-command or PR-revert rollback path | 100% |
| One-message guarantee | No more than 1 outbound card per unique tweet URL per 10 min window | Enforced by `_PROCESSED_URLS` + cross-source dedup |

---

## Denylist Enforcement

The following actions are permanently excluded from the reply-action system and must not appear in any handler:

- Trading orders (Polymarket, Kraken, any exchange)
- Money movement (ACH, wallet funding, crypto transfer)
- Sending external email to new recipients
- Posting to X/Twitter
- Sending iMessage to new phone numbers not in allowlist
- Modifying production docker-compose.yml
- Dropping or truncating any database

These map to the `hard_denylist` array in `config/reply_actions.schema.json`. Any handler that attempts a denylist action must throw `DenylistViolationError` and abort without side effects. The approval flow in `ops/approvals/` is the only path for these operations.

---

## Verification Summary

- **Files read**: 13 source files, 1 compose file
- **Greps run**: 14 pattern searches
- **Runtime changes**: 0
- **Secrets inspected**: 0
- **Messages sent**: 0
- **Assumptions**: 5 (listed above with confidence levels)
- **Open questions**: 6 (listed above)
