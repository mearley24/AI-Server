# BlueBubbles → Cortex Fully-Live Webhook Verification — 2026-04-24

<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must
be zsh-safe: no heredocs, no inline interpreters, no interactive
editors, no long-running watch modes (no tail -f, no --watch, no npm
run dev). Use bounded commands: timeout, --lines N, --since, head/sed
-n ranges. -->

<!-- autonomy: start -->
Category: messaging
Risk tier: high
Trigger:   manual
Status:    active
<!-- autonomy: end -->

**Title:** BlueBubbles → Cortex Fully-Live Webhook Verification — confirm
an inbound iMessage from a **different** number reaches the BlueBubbles
server webhook and lands on Cortex `/hooks/bluebubbles`, producing
normalized Cortex evidence. Prior runs (2026-04-21 webhook stage-2,
2026-04-23 bluebubbles-health-plist) established the server + health
endpoint are reachable but `inbound_count` was still `0`. Matt also
reported self-to-self iMessage does not trigger a webhook — that is an
expected iMessage-routing quirk, not a bug; full-leg proof requires a
message from a distinct phone number.

**Owner:** Matt, on **Bob** (Mac Mini M4), via Cline. Not the
task-runner, not the self-improvement loop, not any auto-dispatcher.
This prompt reads live state and writes evidence only. All runtime
mutation, including any BlueBubbles Settings UI change, public port
change, service restart, or config edit, is deferred to a follow-up
prompt gated on an explicit `[NEEDS_MATT]` approval string in-chat.

**Prerequisite reading (in order):**

1. `/CLAUDE.md`
2. `.clinerules`
3. `ops/AGENT_VERIFICATION_PROTOCOL.md`
4. `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
5. `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md` — the human test procedure
   this prompt wraps in an autonomous shape.
6. `ops/verification/20260421-193143-bluebubbles-webhook.md` — prior
   webhook stage-2 verification (inbound_count=0 baseline).
7. `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md` —
   server/plist arming runbook.
8. `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` —
   companion runbook for this prompt (bounded command reference).
9. `cortex/bluebubbles.py` — `/hooks/bluebubbles` handler,
   `/api/bluebubbles/health`, routing policy
   (`allow_owner_only` → `is_inbound_allowed`), redis publish lanes
   (`events:bluebubbles`, `events:imessage`).
10. `config/bluebubbles_routing.json` (if present) — owner phone +
    allowed_phones entries that govern sender-allowlist decisions.
11. `STATUS_REPORT.md` — grep for `bluebubbles`, `webhook`,
    `inbound_count`, read the enclosing entries.

---

## Goal

Produce a single bounded, read-only evidence capture on Bob that proves
(or disproves) a fresh inbound iMessage from a **different phone
number** reaches:

1. The **BlueBubbles server** (sent outbound webhook),
2. The **Cortex** `/hooks/bluebubbles` handler (incremented
   `inbound_count`, new `last_inbound_event_at`),
3. The **Redis** `events:bluebubbles` / `events:imessage` lanes (normalized
   envelope arrived), and
4. The **Cortex message DB / dedup store** if one is wired (per existing
   dedup work) — evidence is path + count only, no message bodies
   beyond the test nonce.

Write the full report to
`ops/verification/YYYYMMDD-HHMMSS-bluebubbles-cortex-live-webhook.md`,
update `STATUS_REPORT.md` with a one-line pointer, commit and push.

This prompt does **not** send any outbound iMessage or SMS, does **not**
open any public port, does **not** restart any service, and does
**not** mutate any config. Every such change is deferred to a follow-up
prompt gated on `[NEEDS_MATT]`.

## Non-goals

- **No outbound iMessage / SMS send by automation.** The external
  message must be sent manually by a human on a *different* phone
  number, coordinated by Matt out-of-band. This prompt only instructs
  Matt to arrange the send; it never triggers one.
- **No BlueBubbles Settings UI mutation.** Reading the current
  `Server URL` / `Webhook URL` fields by screenshot or config-safe
  text description is allowed; *changing* them requires an explicit
  follow-up prompt carrying `APPROVE: bluebubbles-webhook-url` and is
  out of scope for this run.
- **No public port changes.** Cortex must not be re-bound to `0.0.0.0`,
  port-forwarded, or exposed beyond Bob's loopback during verification.
  Host-side BlueBubbles already reaches Cortex on `127.0.0.1:8102`
  because the LaunchAgent runs on Bob, not inside Docker.
- **No Docker restart, no `docker restart cortex`, no `docker kill`.**
  If Cortex is unhealthy at the start, stop and hand back
  `[FOLLOWUP: cortex-unhealthy]`.
- **No launchctl bootstrap/bootout/kickstart on
  `com.bluebubbles.server`.** The server should already be running per
  the 2026-04-23 arming runbook.
- **No `sudo`, no destructive git operations, no harness-owned file
  edits** (`.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`). Preserve any
  pre-existing dirty working tree.
- **No `tail -f`, no `--follow`, no `watch`, no unbounded log reads.**
  Use `--tail N` / `--since` / `-n` / `head` ranges. All event-watching
  in Step 6 uses **time-windowed polling** (at most 12 polls, 10 s
  apart, total ≤ 120 s).
- **No secret printing.** Do not `cat .env*`. Do not print
  `BLUEBUBBLES_PASSWORD`, `BLUEBUBBLES_SERVER_URL` (the host-side URL
  may carry a password query string on BlueBubbles), or any API key.
  When a field contains a secret, redact to `***REDACTED***` and
  record only the key name.
- **No phone-number / message-body logging** beyond:
  - the test nonce string (chosen by this prompt),
  - sender redaction to `+1XXXXXXX1234` (last-4 digits only),
  - Cortex-assigned event IDs, counts, and timestamps.

## Context

Matt reported: "one follow-up remaining: live BlueBubbles → Cortex
webhook path. Self-to-self iMessage doesn't trigger webhook." This
matches Apple's expected iMessage-routing behavior (a message you send
to yourself does not traverse your own Messages-app inbox in a way that
BlueBubbles can observe), which is why prior stage-2 verification
showed `inbound_count: 0` despite the server and Cortex both reporting
healthy.

Source-of-truth webhook URL, per `cortex/bluebubbles.py:680` +
`docs/bluebubbles/MANUAL_WEBHOOK_TEST.md:9`, is:

```
http://127.0.0.1:8102/hooks/bluebubbles
```

Matt's parent-agent briefing referenced
`http://cortex:8102/hooks/bluebubbles`. That form is **only valid from
inside the Docker network** (the `cortex` hostname resolves via the
compose network — see `docker-compose.yml` `CORTEX_URL=http://cortex:8102`
entries). BlueBubbles runs as a **host-side LaunchAgent**
(`com.bluebubbles.server`), not in Docker, so the correct target from
the server's perspective is the loopback form
`http://127.0.0.1:8102/hooks/bluebubbles`. Capture *both* forms in
evidence so future readers see the distinction.

Cortex's `allow_owner_only` routing policy
(`cortex/bluebubbles.py:247`) will drop messages from senders that are
not on `inbound.allowed_phones` / `allowed_emails` /
`allowed_chat_guids`. To observe a `webhook_ok` event without also
seeing `policy_drop`, the external sender's number must be on the
allowlist — or the test must accept that the inbound event reaches the
handler, increments `inbound_count`, but is then dropped with a
`source=policy_drop` reason in the log. Record whichever outcome
actually occurs; both prove the webhook leg is live.

## Operating mode

- `AUTO_APPROVE = true` for read-only evidence commands. Any action
  that would mutate runtime state is **not** auto-approved and must be
  deferred to a follow-up prompt with an explicit in-chat approval
  string.
- Bounded commands only: `timeout`, `--tail N`, `--since`, `-n N`,
  `head -n`, `sed -n 'A,Bp'`. No heredocs, no inline interpreters,
  no interactive editors.
- Verification-to-file-then-commit contract per
  `ops/AGENT_VERIFICATION_PROTOCOL.md`.

## Safety gates

- **`[NEEDS_MATT]` for UI inspection.** The BlueBubbles Settings UI
  check (Step 2) is a *manual* observation by Matt. The prompt
  describes what to look for and asks Matt to paste a redacted
  screenshot description or config-safe text into the verification
  file. No agent clicks into the UI.
- **`[NEEDS_MATT]` for any settings change.** If the `Webhook URL`
  field is empty, wrong, or points somewhere else, **stop**. Record
  the mismatch in the verification file. Do not edit the field.
  Return `[FOLLOWUP: bluebubbles-webhook-url-mismatch]` and propose a
  separate prompt carrying `APPROVE: bluebubbles-webhook-url`.
- **`[NEEDS_MATT]` for the external send.** The inbound message must
  come from a phone number **not equal to Matt's iMessage address on
  Bob**. The prompt does not send it. It describes the nonce Matt
  should ask the external participant to include in the message body
  (e.g. `BBCX-<UTC-date>-<short-random>`), and Matt coordinates the
  send out-of-band.
- **Secrets redaction.** Every piece of evidence passes through a
  redaction pass before landing in
  `ops/verification/*-bluebubbles-cortex-live-webhook.md`.
  Phone numbers → last-4 only. Message bodies → nonce-only;
  everything else elided.

---

## Step plan

Each step is bounded and emits a labeled section into the verification
file. Stop at the first `STOP` condition in Step 10.

### Step 0 — Timestamp and verification-file bootstrap

- `STAMP=$(date -u +%Y%m%d-%H%M%S)`
- `OUT=ops/verification/${STAMP}-bluebubbles-cortex-live-webhook.md`
- `printf '# BlueBubbles → Cortex Live Webhook Verification\n' > "$OUT"`
- `printf 'UTC stamp: %s\n' "$STAMP" >> "$OUT"`
- `printf 'Host: bob\nRunner: Claude Code (Cline)\nPrompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md\n\n' >> "$OUT"`
- `printf '## Nonce\n' >> "$OUT"`
- `NONCE="BBCX-$(date -u +%Y%m%d)-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"`
- `printf 'nonce: %s\n' "$NONCE" >> "$OUT"`
- Record `NONCE` in a session note so Step 6 can grep for it.

### Step 1 — Health baseline

Bounded, read-only, no auth header (Cortex health endpoint is
allowlisted for loopback):

- `bash scripts/bluebubbles-health.sh --json | tee -a "$OUT"` — captures
  both `cortex_health.status` and `bluebubbles_server.status`.
- `curl -sS --max-time 5 http://127.0.0.1:8102/api/bluebubbles/health | python3 -m json.tool | tee -a "$OUT"`
- Record `counters.inbound_count` as `INBOUND_BEFORE` in the file.
- Record `last_inbound_event_at` as `LAST_EVENT_BEFORE` in the file.
- Record `webhook_endpoint` field (should be `/hooks/bluebubbles`) and
  `routing.policy` (expected `allow_owner_only`).

Stop condition: Cortex status != `healthy` **or** BlueBubbles server
status != `healthy`. Emit `[FOLLOWUP: cortex-or-bluebubbles-unhealthy]`
and exit.

### Step 2 — BlueBubbles Settings UI Webhook URL check `[NEEDS_MATT]`

Matt opens the BlueBubbles Server app on Bob → Settings → Webhooks (or
Settings → Server → Webhook URL, depending on the 1.9.x UI version)
and inspects the configured URL(s).

Acceptable target forms (record exactly which appears):

- `http://127.0.0.1:8102/hooks/bluebubbles` ← preferred, because
  BlueBubbles runs on-host and Cortex is bound to loopback.
- `http://localhost:8102/hooks/bluebubbles` ← equivalent.
- `http://host.docker.internal:8102/hooks/bluebubbles` ← only valid if
  BlueBubbles were containerized, which it is not on Bob.
- `http://cortex:8102/hooks/bluebubbles` ← **invalid from host-side
  BlueBubbles**; `cortex` hostname only resolves inside the Docker
  compose network. If this appears, it is the root cause Matt asked
  about.

Matt pastes one of the following into the verification file under
`## Step 2 — Webhook URL (UI)`:

- a redacted screenshot description (e.g. `"Webhook URL: http://127.0.0.1:8102/hooks/bluebubbles — HTTP POST — enabled — no auth token visible"`), or
- a text line verbatim (no secrets; if the URL contains a query-string
  password, redact as `?password=***REDACTED***`).

Stop condition: Webhook URL field is empty, disabled, or points
outside loopback/localhost. Record mismatch under `[FOLLOWUP:
bluebubbles-webhook-url-mismatch]` and exit. Do not edit the field.

### Step 3 — Cortex receiver contract (read-only, code + config)

- `grep -n "/hooks/bluebubbles" cortex/bluebubbles.py | head -5 >> "$OUT"`
- `grep -n "allow_owner_only\|allowed_phones\|blocked_phones" cortex/bluebubbles.py | head -20 >> "$OUT"`
- If `config/bluebubbles_routing.json` exists:
  - `python3 -c "import json,sys;d=json.load(open('config/bluebubbles_routing.json'));print('policy:',d.get('default_policy'));print('allowed_phones_count:',len((d.get('inbound') or {}).get('allowed_phones',[])));print('allowed_chat_guids_count:',len((d.get('inbound') or {}).get('allowed_chat_guids',[])))"` → append.
  - **Never print phone numbers.** Only counts and the policy string.
- Record expected behavior in the file: the inbound leg will always
  fire (Cortex will increment `inbound_count` on every well-formed
  payload). The allowlist decides whether the event proceeds to
  processing (`webhook_allowed`) or is dropped (`webhook_dropped`).
  Both outcomes **prove the webhook path is live**; only the first
  proves end-to-end policy coverage.

### Step 4 — Redis lane prep (bounded)

- `docker ps --filter name=redis --format '{{.Names}}\t{{.Status}}' | head -5 >> "$OUT"`
- `docker exec -T redis redis-cli PING | head -1 >> "$OUT"`
- Record `events:bluebubbles` / `events:imessage` channel names in the
  file.
- **Do not** run `SUBSCRIBE` (unbounded). Use `XLEN` / `LLEN` polling
  in Step 6 instead if the lanes are streams/lists, or skip to log
  grep if they are pubsub-only (`events:*` are publish-only).

### Step 5 — Nonce + manual send coordination `[NEEDS_MATT]`

Matt arranges, **out-of-band**, for a human on a distinct phone number
(not Matt's primary number, not a forwarded number on Matt's
Continuity-linked devices) to send an iMessage to Matt's BlueBubbles
handle containing **only** the nonce string printed in Step 0.

- Nonce template: `BBCX-<UTC-YYYYMMDD>-<6 hex>`
- Example (illustrative): `BBCX-20260424-3f9a1e`
- Agent writes the nonce into the verification file.
- Agent **does not** send the message. Agent **does not** DM anyone.
- If no external sender is available in the current session, stop and
  emit `[FOLLOWUP: external-sender-unavailable]`. Resume in a later
  run.

### Step 6 — Time-windowed inbound polling (≤ 120 s, bounded)

Poll the Cortex health endpoint and Docker logs in a bounded loop.
**No `tail -f`.** All polls are single-shot curl / docker-logs calls.

Pseudocode (Cline expands into zsh-safe one-liners):

- loop `i` from 1 to 12:
  - `sleep 10`
  - `curl -sS --max-time 5 http://127.0.0.1:8102/api/bluebubbles/health | python3 -c "import json,sys;d=json.load(sys.stdin);print('inbound_count=',d.get('counters',{}).get('inbound_count'));print('last_inbound_event_at=',d.get('last_inbound_event_at'))"` → append to `$OUT` under `### poll i`.
  - `docker logs cortex --since 2m --tail 200 2>&1 | grep -E "bluebubbles|hooks/bluebubbles|webhook" | head -40` → append (body redacted in Step 7).
  - If `inbound_count > INBOUND_BEFORE`, mark `INBOUND_AFTER` and break.

After the loop:

- If `inbound_count` did not advance → `[FOLLOWUP: no-inbound-event-in-window]` and continue to Step 7 with the null result.
- If `inbound_count` advanced by exactly 1 → `PASS (expected-single)`.
- If `inbound_count` advanced by > 1 → `NOTE (multi-delivery)`; check
  dedup evidence in Step 8.

### Step 7 — Log + body redaction

Scrub Cortex log excerpts captured in Step 6 before they land in the
verification file:

- Replace sender phone numbers with last-4 form (`+1XXXXXXX1234`).
- Replace message body with nonce-only (`text='BBCX-…'` preserved; any
  other text → `***REDACTED***`).
- Replace BlueBubbles API password / token query strings with
  `password=***REDACTED***`.
- Preserve event IDs, Cortex-assigned UUIDs, timestamps, policy
  decision strings (`sender_allowlisted`, `policy_drop`, etc.),
  response codes.

### Step 8 — Dedup / DB evidence (if wired)

Per prior 2026-04-23 cortex-dedup upsert work:

- If `cortex/bluebubbles.py` writes to a Cortex message DB / dedup
  store, confirm the nonce appears exactly once. Use a bounded SQL /
  redis query (e.g. `docker exec -T cortex python3 -c "…"` with a
  redaction pass), or skip with `N/A — dedup store not wired for
  inbound` if the prior work has not landed.
- Expected outcome: single-message behavior — one row/event per
  distinct `guid` — no duplicate inbound. If duplicates appear,
  record under `[FOLLOWUP: duplicated-inbound]`.
- If the message was fragmented (Cortex received > 1 event for a
  single-send), record under `[FOLLOWUP: fragmented-inbound]`.

### Step 9 — Pass/fail classification

Write a **Verdict** section in `$OUT` with exactly one of:

| Class | Meaning |
|---|---|
| `PASS-webhook-and-policy` | `inbound_count` incremented and event reached processing (sender allowlisted). |
| `PASS-webhook-only` | `inbound_count` incremented but event was policy-dropped. Proves webhook leg is live; allowlist is the gate. |
| `FAIL-no-webhook` | `inbound_count` did not change after external send. Webhook delivery broken; Step 2 URL check is the primary lead. |
| `BLOCKED-no-external-sender` | Step 5 did not produce an external send in this run. No conclusion. |
| `BLOCKED-ui-inaccessible` | Step 2 could not be completed. No conclusion. |
| `BLOCKED-unhealthy-baseline` | Step 1 did not pass. No test run. |

### Step 10 — STATUS_REPORT update + commit/push

- Append to `STATUS_REPORT.md` a single dated entry:

```
## BlueBubbles → Cortex Live Webhook Verification (YYYY-MM-DD UTC, Claude Code)
- Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md
- Runbook: ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md
- Evidence: ops/verification/<STAMP>-bluebubbles-cortex-live-webhook.md
- Verdict: <PASS-... | FAIL-... | BLOCKED-...>
- [FOLLOWUP: ...] (if any, from Steps 2/5/6/8)
```

- Commit with an `ops(bluebubbles):` prefix, one-line subject, body
  names the verdict + followups.
- `git push` on the current branch only. Do not force-push. Do not
  touch other branches. Do not touch tags.

## Stop conditions (hard)

The agent **must** halt and emit the matching `[FOLLOWUP: ...]` line
rather than attempting remediation:

- BlueBubbles Settings UI `Webhook URL` is empty, wrong, or disabled.
  → `[FOLLOWUP: bluebubbles-webhook-url-mismatch]`. Propose a follow-up
  prompt gated on `APPROVE: bluebubbles-webhook-url`.
- BlueBubbles server is not running or unreachable from loopback.
  → `[FOLLOWUP: bluebubbles-server-down]`.
- Cortex `/api/bluebubbles/health` returns non-200 or
  `status != healthy`. → `[FOLLOWUP: cortex-bluebubbles-unhealthy]`.
- No external sender available in this session. →
  `[FOLLOWUP: external-sender-unavailable]`.
- Poll window elapsed without `inbound_count` advance. →
  `[FOLLOWUP: no-inbound-event-in-window]`.
- Duplicated or fragmented inbound observed. →
  `[FOLLOWUP: duplicated-inbound]` / `[FOLLOWUP: fragmented-inbound]`.
- Any log line threatens to land unredacted secrets in the
  verification file. → abort write, redact, resume.

## Guardrails summary (risk tier: high)

- **No outbound message send** by this prompt or any tool it invokes.
- **No UI mutation**, **no config mutation**, **no port change**,
  **no service restart**.
- **No secrets printed**, **no phone numbers printed** beyond last-4
  redaction.
- **No `tail -f` / `--follow` / `watch`**. All event watching is
  time-windowed poll, ≤ 12 polls × 10 s.
- **No writes** to `.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`,
  `ops/runbooks/**` (this prompt's companion runbook is created
  once by the parent-agent repo pass and not edited autonomously
  after that).
- **Preserve pre-existing dirty working tree.** If the checkout has
  uncommitted edits in unrelated files, do not stage or revert them.

## Final report

Write to:

`ops/verification/<STAMP>-bluebubbles-cortex-live-webhook.md`

Required sections (in order):

1. Header (stamp, runner, prompt path, host).
2. `## Nonce` — nonce string.
3. `## Step 1 — Health baseline` — full JSON, counters recorded.
4. `## Step 2 — Webhook URL (UI)` — Matt-provided description,
   redacted.
5. `## Step 3 — Cortex receiver contract` — grep output + routing
   summary (counts only, no numbers).
6. `## Step 4 — Redis lane prep` — PING + channel names.
7. `## Step 5 — Nonce + external send coordination` — nonce string +
   record of who sent (redacted) and approximate UTC send time, as
   reported by Matt.
8. `## Step 6 — Time-windowed polls` — 12 poll records max, each with
   `inbound_count` / `last_inbound_event_at`.
9. `## Step 7 — Log excerpts (redacted)`.
10. `## Step 8 — Dedup / DB evidence` (or `N/A`).
11. `## Verdict` — one of the six class labels.
12. `## Followups` — one bullet per `[FOLLOWUP: ...]`, each with a
    proposed next prompt path.

Then commit and push per Step 10.

---

_Drafted by Claude Code on 2026-04-24 (parent-agent repo pass,
AUTO_APPROVE=false for runtime actions). This pass **did not** execute
any runtime step — no curl, no docker, no BlueBubbles UI inspection,
no external message. The prompt is the deliverable; execution happens
when Matt runs it on Bob via Cline._
