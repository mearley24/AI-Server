# Phase 1 — Reply-Actions Foundation (X-Intake Interactive Loop)

<!-- autonomy: start -->
Category: messaging
Risk tier: medium
Trigger:   manual
Status:    active
<!-- autonomy: end -->

You are Cline/Claude running inside the `AI-Server` repo. This is an
**implementation** task for **Phase 1 only** of the reply-action loop
design. Do **not** implement the Docker testbed, the prototype-spin
action, or the mute-author action in this phase. Do **not** inspect or
print secrets. Do **not** send messages (no outbound iMessage /
BlueBubbles / X posts) while running this.

The reply-actions design from
`docs/audits/x-intake-deep-dive-audit.md` §3 and the schema at
`config/reply_actions.schema.json` are considered **LGTM**. Build
against them as-is.

---

## Goal

Ship a minimal, safe, testable reply-action foundation so that an
x-intake outbound message carries action IDs + numbered options, and
an inbound BlueBubbles/iMessage reply like `1`, `2`, `reply 1`,
`option 2` dispatches the matching non-risky action exactly once.

Actions in scope for Phase 1:

| Slot | Key              | Phase-1 behavior                                  |
|------|------------------|---------------------------------------------------|
| 1    | `build_card`     | Fully implemented                                 |
| 2    | `deep_research`  | Fully implemented                                 |
| 3    | `prototype`      | **Pending-approval stub only** — no execution     |
| 4    | `save_to_cortex` | Fully implemented                                 |
| 5    | `mute_author`    | **Pending-approval stub only** — no execution     |
| 6    | `open_thread`    | Fully implemented                                 |

For slots 3 and 5, the reply must produce a reply acknowledgement
("confirmation required / not implemented yet") **or** write a pending
approval row in the existing approvals flow — whichever is cheaper to
add without breaking existing approvals. Either path is acceptable;
pick one, document the choice in the verification artifact.

**Keep the existing one-message outbound contract.** Do not split the
x-intake outbound into multi-message threads. The trailing options
block must fit inside the same iMessage.

---

## Preconditions

Read first (do not skim past — these are the source of truth for this
phase):

1. `config/reply_actions.schema.json` — action catalog, parsing rules,
   safety rules. The schema is authoritative for slot numbers, keys,
   and expiry windows.
2. `docs/audits/x-intake-deep-dive-audit.md` §3 Reply-Action Loop and
   §4 Safety & Idempotency.
3. `integrations/x_intake/main.py` and `integrations/x_intake/
   post_fetcher.py` — the outbound composer and where the options
   block gets appended.
4. `integrations/bluebubbles_*` or the existing BlueBubbles inbound
   handler — the reply ingestion path you will extend with the
   reply-parser.
5. `STATUS_REPORT.md` — conventions for the status update you will
   append at the end of the run.

Health checks to run before changes:

- `git status` is clean (no unrelated dirty files that would bleed into
  the commit).
- `git rev-parse --abbrev-ref HEAD` is `main`.
- `python3 -c "import json; json.load(open('config/reply_actions.schema.json'))"`
  parses without error.

---

## Operating mode

- `AUTO_APPROVE = true` — no human prompts mid-run.
- **Hard safety rules** (non-negotiable):
  - No trading, no money movement, no order placement, no wallet ops.
  - No new secrets; no printing or echoing existing secrets.
  - No external comms except the existing local BlueBubbles/iMessage
    reply path that already exists. No new email, X posts, webhooks,
    or outbound to new phone numbers.
  - No Docker testbed enablement. Do not touch `docker/testbed/*`,
    `scripts/testbed-*.sh`, or any compose file for the testbed.
  - Bounded commands only. No `tail -f`, no `watch`, no interactive
    editors, no `<<EOF` heredocs, no backgrounded daemons.
  - No deletions of existing files outside the change set.
- **Verification-to-file then commit** contract:
  - Write verification output to
    `ops/verification/YYYYMMDD-HHMMSS-phase-1-reply-actions.txt`.
  - Commit (`feat(reply-actions): phase 1 foundation ...`) and push to
    `origin/main`.

---

## Step plan

### Step 1 — Outbound: append action block

In the x-intake outbound composer, after the summary is built and
before send:

1. Generate a per-message `action_id` per schema `global_settings.id_length_bytes`
   (6 bytes hex by default). Use `secrets.token_hex(6)`.
2. Persist `{action_id, message_id, post_url, summary, author_handle,
   created_at, expiry_at}` to a new JSONL at
   `data/x_intake/outbound_actions.jsonl` (append-only, one row per
   outbound). Expiry default = 86400 s; slots with shorter expiry (3,
   5, 6 per schema) use their own value when they are the only action.
3. Render the trailing options block per schema
   `outbound_format.example`. Keep the full block ≤ 120 chars on the
   options line; the ID line is separate. Example:

   ```
   Reply 1 — card  |  2 — research  |  4 — save  |  6 — open
   ID:a3f9c1 · exp 24h
   ```

   Phase-1 options list must **include** slots 3 and 5 so users can
   see the full menu, but dispatch of those slots is the stub path in
   Step 3.

### Step 2 — Inbound: reply parser

In the BlueBubbles/iMessage inbound handler (the path that already
consumes Redis `events:imessage` or equivalent):

1. Before existing routing, check if the message is a reply to a
   known `action_id`. Two resolution strategies, in order:
   a. Explicit `ID:xxxxxx` substring in the reply body.
   b. Implicit: reply is a short token (1–3 chars after
      normalization) **and** the thread's most recent outbound with
      an unexpired `action_id` is resolvable via chat GUID /
      conversation ID.
2. Normalize per schema `parsing_rules.normalization`: strip
   whitespace, lowercase, remove punctuation except digits. Accept
   `reply`, `r` prefixes; allow bare digit.
3. If the parsed slot is not in 1..6, log "unrecognized" and do
   nothing (schema `unrecognized_token_behavior = ignore_and_log`).
4. If multiple distinct slot digits appear in the body, ignore and
   log (`ambiguity_policy = do_nothing_and_log`).

### Step 3 — Dispatcher

Add `integrations/x_intake/reply_actions.py` (or equivalent module
alongside the existing x-intake code). Responsibilities:

1. **Idempotency** — before dispatching, check the audit log
   (`data/x_intake/reply_action_audit.jsonl`) for an existing
   successful row with the same `action_id`. If found within the
   `dedupe_window_seconds`, no-op. Repeated identical replies must
   execute the action **at most once**.
2. **Expiry** — if `now > expiry_at` for this `action_id`, emit a
   single "expired" reply (per schema `expired_reply_behavior`) and
   do not execute.
3. **Dispatch map** for Phase 1:
   - 1 → `handlers.build_card(payload)`
   - 2 → `handlers.deep_research(payload)`
   - 3 → pending-approval stub: write to the existing approvals queue
     **or** send a single reply "Prototype action not implemented
     yet — confirmation required". Do not spin any container.
   - 4 → `handlers.save_to_cortex(payload)`
   - 5 → pending-approval stub: write to the existing approvals queue
     **or** send a single reply "Mute author not implemented yet —
     confirmation required". Do not modify any mute list.
   - 6 → `handlers.open_thread(payload)` (invokes local macOS `open`
     on Bob — reuse the existing mechanism if one already exists;
     otherwise add a minimal local shell-out with no external I/O).
4. **Audit** — every dispatch (including stubs, expired, and
   unrecognized) appends one row to
   `data/x_intake/reply_action_audit.jsonl` with the fields listed in
   schema `safety_rules.audit_fields`.

### Step 4 — Tests

If a `tests/` directory exists and is used for this code, add:

- `tests/test_reply_action_parser.py` — table-driven cases for the
  parser: `"1"`, `"Reply 2"`, `"r 4"`, `"option 6"`, `"12"` (two
  digits → unrecognized), `" hello 1 "` (ok, slot 1),
  `"maybe"` (unrecognized).
- `tests/test_reply_action_dispatch.py` — covers:
  - Happy path: slot 1 dispatches once, writes audit row.
  - Duplicate reply within dedupe window: second call no-ops.
  - Expired action_id: no execution, expired ack emitted.
  - Slot 3 and slot 5: stub path only, no handler side effects.

If no test framework is wired up for this subsystem, skip and note it
in the verification artifact — do **not** stand up a new test runner
for this phase.

### Step 5 — Verification

Produce `ops/verification/YYYYMMDD-HHMMSS-phase-1-reply-actions.txt`
containing:

1. `git status` (should be clean after commit).
2. Output of the unit tests if they were added.
3. Synthetic inbound reply cases exercised end-to-end (can be a
   Python one-liner invoking the parser + dispatcher in-process; no
   real BlueBubbles traffic).
4. Duplicate reply test result.
5. Expired action_id test result.
6. `grep -n "Phase 1 reply-actions" STATUS_REPORT.md` to confirm the
   status line landed.
7. Final `git log -1 --oneline`.

### Step 6 — STATUS_REPORT

Append (do not rewrite) a short section to `STATUS_REPORT.md` under
today's date heading (create the date heading if absent):

```
### Phase 1 reply-actions foundation — <YYYY-MM-DD>

- Outbound x-intake messages now carry ID:<hex> and a numbered options
  block.
- Inbound parser handles `1`, `reply 1`, `r1`, `option 2`, bare digits.
- Slots 1, 2, 4, 6 dispatch; slots 3, 5 return pending-approval stubs.
- Idempotency + expiry enforced via
  data/x_intake/reply_action_audit.jsonl.
- Verification: ops/verification/<file>.txt
```

### Step 7 — Commit + push

```
git add -A
git commit -m "feat(reply-actions): phase 1 foundation — parser, dispatcher, outbound IDs"
git push origin main
```

---

## Guardrails

- Do not touch trading, Kraken, Polymarket, or treasury code paths.
- Do not add new network egress. `open_thread` uses local `open` on
  Bob; all other handlers must stay within existing service boundaries.
- Do not modify `docker-compose.yml`, `docker-compose.telegram.yml`, or
  any file under `docker/testbed/` if that path exists.
- Do not add new secrets; do not read from `.env` beyond what existing
  code already reads.
- No `tail -f`, `watch`, `vim`, `nano`, heredocs, or multi-line
  inline interpreters in any script added.

## Final report (must be returned in the agent's final message)

- **Changed files** — list with one-line purpose each.
- **Tests** — added / skipped / results summary.
- **Verification artifact** — absolute path under `ops/verification/`.
- **Commit hash** — short SHA of the Phase 1 commit.
- **How to use reply actions** — 3-bullet operator quickstart:
  1. What a Phase-1 outbound looks like.
  2. What replies are accepted (`1`, `reply 1`, `r1`, `option 2`).
  3. Which slots actually execute vs. stub (1/2/4/6 execute; 3/5
     stub; unrecognized and expired are ignored-with-log).
