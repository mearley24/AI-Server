<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: messaging
Risk tier: high
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# X-Intake Reply-Leg Phases 2–6 — Executor / Router (Cline-first)

## Owner / runtime context

- Repo-side authoring, unit-testing, and fixture-driven integration
  testing is runnable from any clean checkout of `origin/main`.
- Any end-to-end test that touches live BlueBubbles (outbound
  iMessage), the production Cortex DB, or Bob's live `x-intake`
  Docker container is **[BOB_CLINE_ONLY]** and **[NEEDS_MATT]**. No
  step in this prompt sends a real reply without Matt's in-session
  approval to a **test-only** recipient (his own number), in a
  `CORTEX_REPLY_DRY_RUN=1` or equivalent **test mode** with a
  single-message send cap.
- Scope anchor: `docs/audits/2026-04-23-unfinished-setup-audit.md`
  §1 "End-to-end one-message source-driven loop for x-intake beyond
  the webhook / ingest scaffolding" + `docs/audits/x-intake-deep-
  dive-audit.md` reply-action module discussion. Phase 1 is
  already landed:
  `integrations/x_intake/reply_actions/{parser.py,action_store.py,
  formatter.py}`. **Phases 2–6 are the scope of this prompt.**

## Goal

Deliver an executor/router so an inbound iMessage reply like
`"1"` or `"reply 2"` can be resolved to a stored
`ActionContext`, validated, executed through an explicit
**allowlisted** handler, and acknowledged back to the original
thread — all with test-mode and dry-run guards on. End state:

- Phase 2: inbound-reply listener subscribes to
  `events:imessage` / `events:bluebubbles`, feeds
  `parse_reply(...)` + `ActionStore.lookup(...)`.
- Phase 3: action-context validator (expiry, slot validity, idempotency
  via `used_at` / `used_slot`).
- Phase 4: **executor-router** that dispatches to a small set of
  allowlisted handler functions — no dynamic import, no remote-code
  loading, no shell-out except the already-allowlisted Cortex /
  BlueBubbles helpers.
- Phase 5: outbound ACK via the consolidated
  `cortex.bluebubbles.send_text` path (see
  `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md`
  — that prompt should land first so the executor has a stable
  outbound helper).
- Phase 6: end-to-end integration test with fixture data proving
  webhook → parser → store → executor → ACK with zero real network
  egress.

## Non-goals

- **Not** adding new handlers beyond the minimal allowlisted set
  needed for the smoke path (e.g. `cortex_remember`,
  `cortex_dismiss`, `escalate_to_matt`). New handlers require their
  own prompt.
- **Not** wiring any scheduled/recurring job. Reply handling is
  event-driven and runs inside the existing x-intake container.
- **Not** touching Phase 1 modules beyond additive imports.
- **Not** changing the inbound webhook shape.
- **Not** modifying BlueBubbles server config.
- **Not** sending real iMessages from this prompt unless Matt
  explicitly enables **test mode** in-session; even then, capped at
  **one message to his own number**.
- **Not** reaching beyond the x-intake + cortex repo boundary.
- **Not** persisting any secret into DB, log, or artifact.

## Safety gates

- **No secrets**: never `cat .env`, never print BlueBubbles API
  password, never log reply-context payloads that contain tokens.
  Redact by default in any log line produced by the executor.
- **No destructive data changes**: the executor never `DELETE`s
  from `memories`; `cortex_dismiss` marks a memory
  `importance=0` + `metadata.dismissed_at` — reversible.
- **No external sends / posts / messages unless explicitly
  approved** via the local approved reply path and **test mode**:
  - Default `CORTEX_REPLY_DRY_RUN=1` (or equivalent) **on** in the
    PR. Outbound path writes to a log + returns a stub success.
  - Flipping to `CORTEX_REPLY_DRY_RUN=0` on Bob is a separate
    **[NEEDS_MATT]** step and must be gated by a
    `ALLOWED_TEST_RECIPIENTS` allowlist (Matt's own phone number
    only, from `.env`).
- **No recurring/scheduled jobs loaded.** No new launchd plist, no
  cron. The listener runs inside the already-loaded x-intake
  container.
- **Bob runtime actions are [BOB_CLINE_ONLY]**.
- **No sudo. No new open ports. No public exposure.** The executor
  runs inside the existing Docker network.
- **Executor sandboxing**:
  - Handlers are declared in a module-level `HANDLER_REGISTRY:
    dict[str, Callable]` — **no** reflection or `getattr(mod, name)`.
  - Handler names come from a fixed enum / frozenset in code, not
    from the inbound payload.
  - Per-action idempotency via `ActionStore.mark_used(action_id,
    slot)`; second-click is a no-op + logged.
  - Per-user rate limit: ≤ 10 executed actions per rolling 60 s,
    enforced in-process.
  - Every handler has a hard `timeout=8` on any outbound HTTP.
- **No heredocs. No interactive editors. No `tail -f` / `--watch`.
  Bounded commands only.**

## Preconditions

Read in this order:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (§1 + §5)
- `docs/audits/x-intake-deep-dive-audit.md` (reply-action design
  section — full read; this is the authoritative spec)
- `integrations/x_intake/reply_actions/__init__.py`
- `integrations/x_intake/reply_actions/parser.py`
- `integrations/x_intake/reply_actions/action_store.py`
- `integrations/x_intake/reply_actions/formatter.py`
- `integrations/x_intake/main.py` (Redis listener; lines around
  the `events:imessage` subscription + watchdog)
- `cortex/bluebubbles.py` (`send_text` — the only sanctioned
  outbound path)
- `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md`
  — this prompt **requires** the consolidated `send_text` to be
  landed. Stop if the consolidation work isn't in `origin/main`.

Confirm git state:

```
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
git pull --ff-only
grep -nE "send_text" cortex/bluebubbles.py | head -n 8
```

## Safe inspection steps (read-only, bounded)

```
python3 -c "import ast; ast.parse(open('integrations/x_intake/reply_actions/parser.py').read()); print('ok-parser')"
python3 -c "import ast; ast.parse(open('integrations/x_intake/reply_actions/action_store.py').read()); print('ok-store')"
python3 -m py_compile integrations/x_intake/reply_actions/parser.py integrations/x_intake/reply_actions/action_store.py integrations/x_intake/reply_actions/formatter.py
grep -nE "events:imessage|events:bluebubbles|subscribe" integrations/x_intake/main.py | head -n 30
```

On Bob only (**[BOB_CLINE_ONLY]**):

```
timeout 5 docker exec x-intake python3 -c "import redis,os; r=redis.from_url(os.environ['REDIS_URL']); print(r.pubsub_numsub('events:imessage'))"
timeout 5 docker exec x-intake ls -la /data/x_intake/ | head -n 20
```

## Implementation tasks (scoped to this one item — Phases 2–6 only)

Each phase is a discrete commit. Keep diffs reviewable.

### Phase 2 — Inbound-reply listener

- New module `integrations/x_intake/reply_actions/listener.py`:
  - `async def run_listener(redis_url, action_store, dispatcher,
    send_ack)`
  - Subscribes to `events:imessage`. For each event:
    - Extract `text`, `thread_guid`, `author_handle`,
      `event_id`.
    - `parsed = parse_reply(text, action_store.list_open_slots(
      thread_guid))`.
    - If `not parsed.matched`: ignore (no ACK — noise suppression).
    - Else: `context = action_store.lookup(parsed.slot,
      thread_guid)`; if `None` or `expired` → ignore.
    - Else: hand to `dispatcher.dispatch(parsed.slot, context)`.
  - Reconnect logic mirrors the existing `main.py` listener (5 s
    backoff, watchdog restart every 10 s).
  - Bounded memory: no in-process queue of unseen events;
    reconnect drops nothing that wasn't already in Redis.

### Phase 3 — Validator

- Add `ActionStore.mark_used(action_id, slot)` if not already
  present. On double-click: raise `AlreadyUsed` (exception class in
  the module); the listener catches and logs, does not ACK again.
- Add `ActionStore.list_open_slots(thread_guid, now=None)` that
  returns the `frozenset[int]` of not-yet-used, not-yet-expired
  slots for the most recent action context in a thread.
- Unit tests cover: expired, used, valid, missing thread.

### Phase 4 — Executor-router

- New module
  `integrations/x_intake/reply_actions/dispatcher.py`:
  - `HANDLER_REGISTRY: dict[str, Callable[[ActionContext], Awaitable[dict]]]`
  - Baseline handlers (minimum allowlisted set):
    - `cortex_remember(ctx)` — POST to local Cortex `/remember`
      (category + source + content carried on the context).
    - `cortex_dismiss(ctx)` — PATCH/POST to flip importance to 0 on
      a memory id carried on the context.
    - `escalate_to_matt(ctx)` — write a note + enqueue an iMessage
      ACK only (no upload, no external share).
  - `async def dispatch(slot, ctx)`:
    - Reads `ctx.context["slot_handler_map"]` (written by the
      upstream card formatter in Phase 1 / earlier work) to map
      `slot -> handler_name`.
    - Validates `handler_name in HANDLER_REGISTRY`. If not → log
      + ACK "action not recognized".
    - Applies rate-limit + idempotency guards (module-level
      `deque` with timestamps per `author_handle`).
    - Invokes handler with `timeout=8`.
    - Catches all exceptions → returns a sanitized failure dict
      (no traceback to iMessage).

### Phase 5 — Outbound ACK via consolidated send path

- New thin helper
  `integrations/x_intake/reply_actions/ack.py`:
  - `async def send_ack(thread_guid, text, *, dry_run: bool)`
  - If `dry_run`: write to a bounded in-memory ring buffer + to
    `data/x_intake/reply_acks.ndjson` (append-only); return a stub
    success.
  - Else: call `cortex.bluebubbles.send_text(thread_guid, text)`.
  - The executor only ever calls `send_ack`.
- Config: `CORTEX_REPLY_DRY_RUN=1` by default in the
  `docker-compose.yml` + `.env.example` stanza added for x-intake.
  Flipping to `0` requires Matt + `ALLOWED_TEST_RECIPIENTS` set in
  `.env`.

### Phase 6 — End-to-end integration test (fixture-driven, offline)

- `ops/tests/test_reply_leg_e2e.py`:
  - Stand up an in-process fake Redis (no real server) — use
    `fakeredis` if available; if not, a minimal
    `asyncio.Queue`-based stub in the test file.
  - Seed an `ActionStore` (tmp DB) with one open action, 2 slots
    mapped to `cortex_remember` / `cortex_dismiss`.
  - Mock `cortex.bluebubbles.send_text` via `respx` /
    `httpx.MockTransport`.
  - Publish an `events:imessage` payload with `text="reply 1"`
    and assert:
    - `ActionStore.mark_used` was called with `(action_id, 1)`.
    - The Cortex `/remember` POST was captured by the mock
      transport with the expected body.
    - The `send_ack` dry-run wrote one line to the ring buffer.
    - A second publish with `text="1"` is a no-op (idempotency).
    - A third publish with `text="9"` is ignored (invalid slot).
    - A fourth publish after `ctx.expires_at` is ignored.

## Full verification / test checklist (bounded)

### V1 — Static

```
python3 -m py_compile integrations/x_intake/reply_actions/listener.py integrations/x_intake/reply_actions/dispatcher.py integrations/x_intake/reply_actions/ack.py
python3 -m py_compile integrations/x_intake/main.py integrations/x_intake/reply_actions/action_store.py integrations/x_intake/reply_actions/parser.py
git diff --stat
grep -nE "HANDLER_REGISTRY|dry_run" integrations/x_intake/reply_actions/dispatcher.py integrations/x_intake/reply_actions/ack.py | head -n 30
```

### V2 — Path existence

```
test -f integrations/x_intake/reply_actions/listener.py && echo ok-listener
test -f integrations/x_intake/reply_actions/dispatcher.py && echo ok-dispatcher
test -f integrations/x_intake/reply_actions/ack.py && echo ok-ack
test -f ops/tests/test_reply_leg_e2e.py && echo ok-e2e
```

### V3 — Unit + integration tests

```
python3 -m pytest ops/tests/test_reply_leg_e2e.py -q
python3 -m pytest integrations/x_intake/reply_actions -q 2>/dev/null || true
python3 -m pytest ops/tests/ -q -k reply
```

### V4 — Security / guardrail smoke

Add `ops/tests/test_reply_leg_guards.py`:

- `test_unknown_handler_name_not_executed` — payload with
  `slot_handler_map = {"1": "os.system"}` → dispatcher rejects.
- `test_rate_limit_caps_per_handle` — 11 rapid dispatches → 11th
  is dropped + logged.
- `test_dry_run_never_calls_send_text` — mock transport asserts
  zero outbound HTTP when `CORTEX_REPLY_DRY_RUN=1`.
- `test_expired_context_ignored`.
- `test_already_used_action_is_noop`.

```
python3 -m pytest ops/tests/test_reply_leg_guards.py -q
```

### V5 — Docker compose surface check

```
grep -nE "CORTEX_REPLY_DRY_RUN|ALLOWED_TEST_RECIPIENTS" docker-compose.yml .env.example | head -n 20
grep -nE "CORTEX_REPLY_DRY_RUN" integrations/x_intake/**/*.py 2>/dev/null | head -n 20
```

### V6 — Live Bob smoke (**[BOB_CLINE_ONLY]**, **[NEEDS_MATT]**, opt-in only)

Skip unless Matt explicitly approves in-session AND confirms
`CORTEX_REPLY_DRY_RUN=1`:

```
timeout 5 docker exec x-intake python3 -c "from integrations.x_intake.reply_actions.dispatcher import HANDLER_REGISTRY; print(sorted(HANDLER_REGISTRY))"
timeout 10 docker logs --tail 200 x-intake | head -c 4000
```

The only live-send test allowed — and only if Matt explicitly
approves — is a single dry-run = 0 exchange to **Matt's own
number** where the payload is obviously a test string prefixed
with `[bob-reply-test]`. Do not broadcast. Do not send to any
non-allowlisted recipient.

### V7 — Do NOT

```
# DO NOT RUN in this prompt:
#   unset CORTEX_REPLY_DRY_RUN; restart container
#   publish synthetic events to events:imessage on the prod Redis
#   docker-compose up -d --build (outside the test environment)
#   send any message to a recipient not in ALLOWED_TEST_RECIPIENTS
```

## Required artifacts

1. **STATUS_REPORT.md** — dated entry
   `X-Intake Reply-Leg Phases 2–6 — Author+Test (<YYYY-MM-DD>)`:
   - Commits landed.
   - Files touched.
   - Test pass counts.
   - Explicit note: **outbound ACKs remain in `CORTEX_REPLY_DRY_RUN=1`
     mode** after this prompt. Flipping to live is a separate
     `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` with the
     `ALLOWED_TEST_RECIPIENTS` allowlist.
2. **Verification receipt** —
   `ops/verification/<YYYYMMDD>-<HHMMSS>-x-intake-reply-leg-phases-2-6.txt`
   with V1–V5 output (V6 only if Matt approved).
3. **Commits** — suggested (one per phase):
   - `feat(x-intake/reply): phase 2 inbound-reply listener`
   - `feat(x-intake/reply): phase 3 validator + mark_used`
   - `feat(x-intake/reply): phase 4 executor-router + handler registry`
   - `feat(x-intake/reply): phase 5 outbound ACK (dry-run default)`
   - `test(x-intake/reply): phase 6 e2e + guardrail coverage`
4. **Push** — `git push origin main`.
5. **Summary** — final message lists changed files, commit hashes,
   and the exact `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` arm sequence
   for enabling live sends (allowlist first, flag second, one-shot
   test second).

## Stop conditions / blockers

- The consolidated `cortex.bluebubbles.send_text` from the
  attachment-bodies prompt is not in `origin/main` yet — stop and
  land that first.
- Any attempt to add a handler that requires reflection /
  `importlib` / `getattr` by string — stop. The registry is
  explicit by design.
- Diff exceeds ~700 LOC net across Phases 2–6 — split into
  Phase 2+3, Phase 4, Phase 5+6 sub-prompts.
- The live Redis listener on Bob is already wedged (per
  STATUS_REPORT's prior x-intake notes) — stop; that is an
  operational issue, not a code issue.
- Any step requires sudo, opening a port, or modifying the
  BlueBubbles server — stop.

## Closing checklist

- [ ] Phases 2–6 landed behind `CORTEX_REPLY_DRY_RUN=1` default.
- [ ] `HANDLER_REGISTRY` is explicit + unit-tested.
- [ ] No outbound iMessage is sent in any automated test.
- [ ] Rate limit + idempotency + expiry + allowlist all covered.
- [ ] STATUS_REPORT + verification artifact + push landed.
- [ ] `[NEEDS_MATT]` live-enable sequence documented verbatim.
