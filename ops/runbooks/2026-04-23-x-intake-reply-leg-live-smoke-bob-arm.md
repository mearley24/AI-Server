# X-Intake Reply-Leg Live Smoke — Bob Runtime Arm Runbook

**Status:** `PARTIAL-PASS` (2026-04-24 17:42 UTC) — chain proven end-to-end
through to the BlueBubbles API (webhook → reply_listener → cortex_remember
→ Cortex /remember 200 → send_ack); outbound `send_text` blocked by macOS
26 apple-script hang. Three code-fixes landed during the smoke. Tracked as
`[FOLLOWUP: bluebubbles-send-method]` in STATUS_REPORT.md.
Receipts: `ops/verification/20260424-174246-x-intake-reply-leg-live-smoke.txt`
(final), `20260424-165559-x-intake-reply-leg-live-smoke.txt`,
`20260424-163523-x-intake-reply-leg-live-smoke-precheck.txt`,
`20260424-084105-x-intake-reply-leg-live-smoke-precheck.txt` (initial).
Final closure audit: `docs/audits/2026-04-25-final-closure-and-exposure-audit.md`.

`[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` + **[EXTERNAL_SEND]**
— **NOT auto-run by Computer / Cline / Claude Code / task-runner /
self-improvement loop.** This file is a human-approved runbook, not
an autonomous prompt. Do **not** add `<!-- autonomy: start -->`
metadata. Do not copy into `.cursor/prompts/`. Dispatchers under
`ops/cline-run-*.sh` must **skip** anything in `ops/runbooks/`.

**Owner:** Matt — and *only* Matt — because step 4 sends a real
iMessage from Bob via BlueBubbles. The send target must be **Matt's
own number** only.
**Host:** Bob (Mac Mini M4), `~/AI-Server` checkout of `origin/main`.
**Prerequisite prompt:** `.cursor/prompts/2026-04-23-cline-x-intake-reply-leg-phases-2-6.md`
(Status: `done`, Phases 2–6 author+test closed).
**Scope anchor:** STATUS_REPORT entry "X-Intake Reply-Leg Phases 2–6
— Author+Test"; Audit §1 "End-to-end one-message source-driven loop".

---

## Why this runbook exists

Repo-side work — listener + dispatcher + ACK + 11 tests — landed
on `origin/main`. `CORTEX_REPLY_DRY_RUN=1` ships as the default
posture, and `ALLOWED_TEST_RECIPIENTS` is an empty allowlist. What
remains is a single supervised smoke that:

1. Writes `ALLOWED_TEST_RECIPIENTS` to Matt's own number only.
2. Flips `CORTEX_REPLY_DRY_RUN=0` just long enough to exercise the
   path end-to-end.
3. Sends **one** reply to Matt's own number.
4. Restores `CORTEX_REPLY_DRY_RUN=1` immediately.

Sending any other message, to any other recipient, is out of scope.
The runbook is designed so that an accidental re-run with
`ALLOWED_TEST_RECIPIENTS` empty would send zero messages.

---

## Prechecks (required, run before any live flip)

Capture into
`ops/verification/<YYYYMMDD-HHMMSS>-x-intake-reply-leg-live-smoke-precheck.txt`
before proceeding.

1. Checkout clean, on `origin/main`:
   ```
   cd ~/AI-Server
   git status --short
   git rev-parse --abbrev-ref HEAD
   git rev-parse HEAD
   git log --oneline -1
   ```
   Expect: branch `main`, HEAD contains commits `6aa2102`, `7bc0f5e`,
   `cce41c4`, `c0b9d1f` (Phases 2–6).

2. x-intake container healthy and up-to-date:
   ```
   docker ps --format '{{.Names}} {{.Status}}' | grep -E '^x-intake '
   docker exec x-intake python3 -c "import sys; sys.path.insert(0,'/app'); from reply_actions.dispatcher import HANDLER_REGISTRY; print(sorted(HANDLER_REGISTRY))"
   ```
   Expect: `['cortex_dismiss', 'cortex_remember', 'escalate_to_matt']`.
   If `ModuleNotFoundError: No module named 'reply_actions'`, the image is
   stale (built before Phases 2-6). Rebuild first:
   `docker compose up -d --build x-intake`

3. **Current flag state — must be in the DRY_RUN=1 posture before
   starting:**
   ```
   grep -E '^CORTEX_REPLY_DRY_RUN=|^ALLOWED_TEST_RECIPIENTS=' .env || echo "flags absent from .env"
   docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
   ```
   Expect: `.env` has `CORTEX_REPLY_DRY_RUN=1` (or unset → defaults
   to 1 in code); `ALLOWED_TEST_RECIPIENTS` empty or unset. **Stop**
   if `DRY=0` already — that is unexpected posture and must be
   investigated before sending anything.

4. BlueBubbles server reachable from Bob and responds to a status
   ping (**no message send**):
   ```
   bash scripts/bluebubbles-health.sh --json | head -c 1200
   ```
   Expect: `blubebubbles_server` field reports `status` of `up` /
   `healthy`.

5. ACK ring-buffer / ndjson location exists and is writable:
   ```
   docker exec x-intake sh -c 'mkdir -p /data/x_intake && test -w /data/x_intake && echo ok-writable'
   docker exec x-intake sh -c 'test -f /data/x_intake/reply_acks.ndjson && wc -l /data/x_intake/reply_acks.ndjson || echo "file not yet created"'
   ```

6. Seed a test action in the `ActionStore` so the reply actually
   resolves. Use the container's helper CLI if one exists, or a
   bounded inline Python call:
   ```
   docker exec x-intake python3 -c "
   from integrations.x_intake.reply_actions.action_store import ActionStore, ActionContext
   import time, uuid
   a = ActionStore()
   ctx = ActionContext(
     action_id=str(uuid.uuid4()),
     thread_guid='<matts-imessage-thread-guid>',
     slots={1: {'handler':'cortex_remember', 'args':{'content':'reply-leg smoke','category':'test'}}},
     expires_at=int(time.time())+300,
   )
   a.put(ctx)
   print('seeded:', ctx.action_id)
   "
   ```
   Replace `<matts-imessage-thread-guid>` with the real GUID from
   Matt's own BlueBubbles thread. **Do not hard-code any non-Matt
   GUID.**

**Stop conditions (abort, do not continue):**

- Any precheck returns an error.
- `DRY=0` already.
- `HANDLER_REGISTRY` is missing the expected three handlers.
- `/data/x_intake/` not writable.
- BlueBubbles server unhealthy.
- Dirty tree in `integrations/x_intake/reply_actions/`.

---

## Ordered arm sequence (Matt only)

All steps must be performed in one continuous session. If you are
interrupted between step 2 and step 6, **the first action on
resumption is step 6** (restore DRY_RUN=1). Do not leave the system
in a DRY_RUN=0 posture unattended.

1. **Set the allowlist to Matt's own iMessage handle only.** Use the
   existing helper (`scripts/set-env.sh`) — no hand-editing of
   `.env`:
   ```
   bash scripts/set-env.sh ALLOWED_TEST_RECIPIENTS "iMessage;-;+1XXXXXXXXXX"
   grep '^ALLOWED_TEST_RECIPIENTS=' .env
   ```
   Replace `+1XXXXXXXXXX` with Matt's own phone number (E.164). The
   allowlist format matches BlueBubbles' address prefix.

2. **Flip DRY_RUN=0.** (Short-lived — the goal is to flip back within
   minutes.)
   ```
   bash scripts/set-env.sh CORTEX_REPLY_DRY_RUN 0
   grep '^CORTEX_REPLY_DRY_RUN=' .env
   ```

3. **Rebuild+restart x-intake** so the new env takes effect:
   ```
   docker compose up -d --build x-intake
   sleep 6
   docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
   docker logs --tail 60 x-intake | head -c 3000
   ```
   Expect: logs show listener subscribed; `DRY=0`; `ALLOW=` shows
   only Matt's number.

4. **Single end-to-end send** — Matt sends `reply 1` (or `1`) from
   his own iPhone to his own Bob-routed thread, so the event flows:
   `iMessage → BlueBubbles → events:imessage → listener → parser →
   ActionStore.lookup → dispatcher → cortex_remember → send_ack
   (DRY=0) → send_text → BlueBubbles → Matt's iPhone`.
   Wait ≤ 60 s. Do **not** send a second message in this window.

   - Reply content to send: `[bob-reply-test] reply 1`
     (the `[bob-reply-test]` prefix is a visual marker that this was
     the gated smoke).
   - Target thread: Matt's own number's conversation.

5. **Inspect evidence immediately** (bounded):
   ```
   docker logs --since 2m x-intake 2>&1 | grep -E 'reply_actions|dispatcher|send_ack|send_text' | head -n 40
   docker exec x-intake sh -c 'tail -n 20 /data/x_intake/reply_acks.ndjson' 2>/dev/null
   docker exec cortex sqlite3 /data/cortex/brain.db "SELECT id, category, source, content FROM memories WHERE category='test' AND content LIKE '%reply-leg smoke%' ORDER BY id DESC LIMIT 3;"
   ```
   Expect: listener log line for the inbound reply; `send_ack`
   written (non-dry-run) followed by a successful `send_text`
   HTTP 200; one new memory row in Cortex.

6. **Restore DRY_RUN=1 and clear the allowlist.** Do this
   immediately after capturing evidence, even if step 5 shows
   partial failure:
   ```
   bash scripts/set-env.sh CORTEX_REPLY_DRY_RUN 1
   bash scripts/set-env.sh ALLOWED_TEST_RECIPIENTS ""
   docker compose up -d --build x-intake
   sleep 4
   docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
   ```
   Expect: `DRY=1`, `ALLOW=` empty.

7. **Confirm no further outbound sends are possible** until the next
   supervised smoke:
   ```
   docker exec x-intake python3 -c "
   from integrations.x_intake.reply_actions.ack import send_ack
   import asyncio
   r = asyncio.run(send_ack(thread_guid='bogus', text='should not send', dry_run=False))
   print('result:', r)
   "
   ```
   The call should refuse or route through the allowlist check and
   fall back to the dry-run ring buffer; no BlueBubbles POST should
   be visible in the subsequent `docker logs` tail.

---

## Verification receipt requirements

After the arm sequence completes (even on abort after step 2), write
a single receipt to:

```
ops/verification/<YYYYMMDD-HHMMSS>-x-intake-reply-leg-live-smoke.txt
```

The receipt **must** include, verbatim:

- `git rev-parse HEAD` on Bob at run time.
- Precheck outputs (flag state + handler registry + writability).
- Pre-flip `.env` grep for both flags.
- Post-flip `.env` grep for both flags (showing DRY=0 with Matt's
  number only).
- Seeded `action_id`.
- The actual iMessage body Matt sent (prefix `[bob-reply-test]`).
- x-intake log excerpt showing the listener + dispatcher + `send_ack`
  + `send_text` path.
- `reply_acks.ndjson` tail.
- Cortex `SELECT` result showing the new memory row.
- Final post-restore `.env` grep showing DRY=1 + `ALLOW=` empty.
- Timestamp of step 6 — the DRY=0 window duration must be recorded.

Then add a dated STATUS_REPORT entry named
`## X-Intake Reply-Leg — Live Smoke on Bob (<YYYY-MM-DD> <HH:MM TZ>, Matt)`
that:

- Records the above.
- **Strikes through** the `[NEEDS_MATT] X-intake reply-leg live
  smoke` bullet with `~~...~~ ✅`.

Commit with:

```
docs(x-intake): live reply-leg smoke on Bob — verification + STATUS_REPORT
```

Do **not** `git push --force` and do **not** amend prior commits.

---

## Rollback / stop conditions

**At any sign of trouble, immediately run step 6 (restore DRY=1 +
empty allowlist + rebuild).** That is the rollback.

| Condition | Immediate action |
|-----------|------------------|
| Step 3 shows `DRY=1` in the container after flip | Container did not pick up new env. Rerun `docker compose up -d --build x-intake`. If still wrong after one retry, abort + rollback. |
| Listener does not log inbound reply within 60 s | Abort + rollback. Investigate Redis pubsub / BlueBubbles webhook ingress. |
| `send_text` returns 5xx | Abort + rollback. Do **not** retry the send from this runbook. |
| Any iMessage sent to any recipient that is not Matt | **Severe.** Abort + rollback. File an `ops/realized_changes/` severity `critical` entry, not a FOLLOWUP. |
| Listener sends more than one reply in the window | Abort + rollback. Idempotency regression. |
| Unknown handler name appears in log | Abort + rollback. Dispatcher safety guard regression. |

**Emergency rollback (single command chain):**

```
bash scripts/set-env.sh CORTEX_REPLY_DRY_RUN 1 && \
bash scripts/set-env.sh ALLOWED_TEST_RECIPIENTS "" && \
docker compose up -d --build x-intake && \
sleep 4 && \
docker exec x-intake sh -c 'echo "DRY=$CORTEX_REPLY_DRY_RUN | ALLOW=$ALLOWED_TEST_RECIPIENTS"'
```

---

## What this runbook explicitly forbids

- **Sending any iMessage to a recipient other than Matt's own
  number.** This is the single hardest gate in the runbook.
- Running with `ALLOWED_TEST_RECIPIENTS` containing more than one
  handle, or containing a group thread GUID.
- Leaving `DRY_RUN=0` after the smoke window. The runbook mandates
  immediate restore in step 6.
- Running from a non-interactive dispatcher. If a scheduled job
  attempts these steps, **it is a critical bug**.
- Editing BlueBubbles server config or opening a new port.
- Using `publish` on the production Redis to inject synthetic
  `events:imessage` payloads. The smoke must ride the real inbound
  path.
- Rewriting `send_ack` to bypass the allowlist.
- Copying this runbook into `.cursor/prompts/` or adding autonomy
  metadata.

---

## Appendix: safer alternative (dry-run-only smoke)

If Matt is not available to supervise a live send, a **dry-run-only**
version of steps 1–5 can be run to exercise listener → dispatcher →
ring-buffer without any BlueBubbles egress:

1. Leave `CORTEX_REPLY_DRY_RUN=1` set.
2. Seed an action (precheck 6).
3. Matt sends `reply 1` from his own iPhone as usual.
4. Inspect `reply_acks.ndjson` for the dry-run stub and Cortex for
   the new memory row.

This exercises every moving part except the real `send_text`. It is
safe to run on any day with zero risk of external egress. Any claim
of "reply-leg verified end-to-end" from this path must note that
the outbound BlueBubbles leg was *not* exercised.
