# Symphony Ops — Engineering Backlog

> **Scope:** This is the **engineering / process** backlog for the AI-Server
> repo. It is **not** the Linear client-ops queue. Linear is reserved for
> live client/business operations (leads, jobs, follow-ups, scope changes).
> See `ops/PROCESS_POLICY.md` for the split.
>
> **Why this file exists:** We tried to land these as Linear issues on
> 2026-04-25. Linear's free-tier active-issue cap blocked creation. The
> right fix is to move engineering work *out* of Linear entirely, not pay
> to fit it in. This file is the durable, repo-native replacement.
>
> **Authoritative status:** When an item lands, update its block here
> (status → `done`, add receipt link), append a dated line in
> `STATUS_REPORT.md`, and drop a receipt under `ops/verification/` if a
> live smoke or external verify was involved.
>
> Last updated: 2026-04-25

---

## Conventions

Each item uses this shape so it can be parsed by the
`/api/process/backlog` endpoint and by future tooling:

```
### <numeric id>. <Title>
- **Status:** todo | in-progress | blocked | done | skip
- **Owner:** unassigned | <name>
- **Lane:** <subsystem>
- **Why:** one paragraph on the operational reason
- **Definition of done:** what evidence proves it landed
- **Source:** receipts, prompts, or commits that motivated this item
- **Risk:** low | medium | high (default low)
- **Duplicate-risk:** notes on what this could collide with
```

Status legend: `todo` (not started), `in-progress` (someone is on it),
`blocked` (waiting on Matt or upstream), `done` (lands + receipt),
`skip` (decided not to do; keep for history).

---

## Active backlog (9 approved)

### 1. Voice Receptionist — surface recent calls in Cortex

- **Status:** todo
- **Owner:** unassigned
- **Lane:** voice / cortex
- **Why:** `cortex/dashboard.py::symphony_voice_receptionist` returns a
  stable empty contract today. The receptionist's SQLite call log is
  in-container; Cortex should mirror it so the operator can see recent
  calls / missed calls / voicemails without `docker exec`.
- **Definition of done:** `recent_calls`, `missed_calls`, `voicemails`
  arrays populated from a Cortex sync worker reading the
  voice-receptionist DB; existing `planned` contract preserved;
  receipt under `ops/verification/<stamp>-voice-receptionist-cortex/`.
- **Source:** `cortex/dashboard.py:1289-1354`,
  `voice_receptionist/`, `ops/tests/test_dashboard_assets.py:273`.
- **Risk:** low
- **Duplicate-risk:** the `ops:voice_followup` Redis path already
  emits per-call events; do not double-write to Linear from the new
  worker — Cortex only.

### 2. Proposals — Zoho live send

- **Status:** todo
- **Owner:** unassigned
- **Lane:** proposals / zoho
- **Why:** `cortex/dashboard.py::symphony_proposals_generate` produces
  a proposal artifact via the proposals service but does not actually
  send through Zoho. Live send needs creds, deliverability hardening,
  and a verification smoke.
- **Definition of done:** end-to-end smoke: generate → Zoho send →
  delivery confirmation in `email-monitor`; receipt under
  `ops/verification/<stamp>-proposals-zoho-send/`; toggle gated on
  env so a dry-run path remains.
- **Source:** `proposals/`, `cortex/dashboard.py:1356-1374`,
  `email-monitor/`.
- **Risk:** medium (touches outbound email, real client comms).
- **Duplicate-risk:** existing `agreement/generate` POST on the
  Symphony tab; keep proposals vs agreements clearly separate.

### 3. Follow-Up Engine — real fire path

- **Status:** todo
- **Owner:** unassigned
- **Lane:** openclaw / follow-ups
- **Why:** `openclaw/follow_up_engine.py` posts a Linear comment on
  the 14-day silent-client milestone but the broader real-fire path
  (timed nudges + delivery via iMessage/email) needs verification.
- **Definition of done:** at least one full firing under
  observation; receipt; STATUS_REPORT entry; existing Linear
  comment behavior preserved (this is one of the *kept* Linear paths
  per `ops/PROCESS_POLICY.md`).
- **Source:** `openclaw/follow_up_engine.py:330,542-593`,
  `STATUS_REPORT.md` follow-up trail.
- **Risk:** medium
- **Duplicate-risk:** `cortex/dashboard.py::/api/followups` queries
  the same DB — do not introduce a second source of truth.

### 4. D-Tools — liveness probe + Cortex surfacing

- **Status:** todo
- **Owner:** unassigned
- **Lane:** dtools-bridge
- **Why:** D-Tools-derived items only flow into Linear today as a
  side-effect of email matching (`LinearEmailSync`). There is no
  direct D-Tools liveness/health surface in Cortex.
- **Definition of done:** `/api/symphony/dtools/health` (or
  similar) on Cortex returns liveness + last sync timestamp; tool
  registry entry in `TOOL_REGISTRY` updated; receipt.
- **Source:** `integrations/`, `clawwork/`, `openclaw/`.
- **Risk:** low (read-only).
- **Duplicate-risk:** make sure the Cortex probe doesn't re-emit
  Redis events that the operations listener (currently dormant)
  would forward to Linear.

### 5. Client Intelligence — periodic backfill + review queue

- **Status:** todo
- **Owner:** unassigned
- **Lane:** intelligence / cortex
- **Why:** the intel-briefing endpoint exists (`/api/intel-briefing/preview`)
  but there is no scheduled backfill of client signals into a review
  queue an operator can clear.
- **Definition of done:** scheduled backfill job (launchd or
  task-runner) writes to a queue table; Cortex exposes a read
  endpoint + dashboard card for the queue; approve/dismiss actions
  parallel to x-intake's pattern.
- **Source:** `cortex/dashboard.py:1458-1466` (intel-briefing),
  x-intake review pattern at `cortex/dashboard.py:925-959`.
- **Risk:** low
- **Duplicate-risk:** do not duplicate x-intake. This is for
  client-attached signals, not generic feed signals.

### 6. x-intake — live ACK smoke

- **Status:** todo
- **Owner:** unassigned
- **Lane:** x-intake / cortex
- **Why:** the reply-leg live smoke is `PARTIAL-PASS` at
  `ops/verification/20260424-174246-x-intake-reply-leg-live-smoke.txt`
  (listener/dispatch/cortex_remember/send_ack proven; outbound
  `send_text` blocked by macOS 26 AppleScript hang). A refreshed live
  smoke is needed once the BlueBubbles send-method workaround lands.
- **Definition of done:** end-to-end ACK with receipt under a fresh
  `ops/verification/<stamp>-x-intake-reply-leg-live-smoke/` directory;
  STATUS_REPORT entry transitions PARTIAL-PASS → PASS.
- **Source:**
  `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`,
  `[FOLLOWUP: bluebubbles-send-method]` in `STATUS_REPORT.md`.
- **Risk:** low
- **Duplicate-risk:** `[FOLLOWUP: bluebubbles-send-method]` is the
  upstream blocker — do not file as a separate item; resolution there
  unblocks this one.

### 7. Daily Briefing v2 — decision

- **Status:** blocked (decision)
- **Owner:** matt
- **Lane:** intel-briefing / autonomy
- **Why:** Daily Briefing v1 is in service; v2 is sketched but the
  shape (what goes in, who gets it, where it lands) needs an
  operator decision before code work.
- **Definition of done:** decision recorded in
  `ops/PROCESS_POLICY.md` or a new `docs/daily-briefing-v2.md` with
  the chosen shape; backlog item then transitions to `todo`.
- **Source:** intel-briefing endpoints in `cortex/dashboard.py`,
  prior briefing prompts in `.cursor/prompts/`.
- **Risk:** low (decision only)
- **Duplicate-risk:** must not collide with the Client Intelligence
  review queue (item 5) — those are different audiences.

### 8. Notification Hub — README + Cortex surfacing

- **Status:** todo
- **Owner:** unassigned
- **Lane:** notification-hub / cortex
- **Why:** `notification-hub/` is in service on `:8095` but lacks a
  README explaining channel topology, and Cortex does not surface
  its health on the dashboard.
- **Definition of done:** `notification-hub/README.md` (channels,
  publishers, consumers, env); `/api/notifications/health` on
  Cortex; tool-registry entry confirmed; receipt.
- **Source:** `notification-hub/`, `PORTS.md:8095`.
- **Risk:** low
- **Duplicate-risk:** the dormant `operations/linear_ops.py` listens
  on `notifications:trading` and `notifications:calendar` — be
  explicit in the README that those bridges are not currently in
  compose.

### 9. Mobile Gateway — unified action queue

- **Status:** todo
- **Owner:** unassigned
- **Lane:** mobile / ios-app / telegram
- **Why:** action queues exist independently for x-intake approvals,
  reply-actions, and iMessage approvals. The mobile/Telegram surface
  needs a unified queue endpoint instead of per-feature endpoints.
- **Definition of done:** `/api/mobile/queue` (or similar) returns a
  uniform shape across action sources; iOS app + Telegram remote
  consume it; receipts for both clients.
- **Source:** `ios-app/`, `telegram-bob-remote/`,
  `cortex/dashboard.py` x-intake + reply-action endpoints.
- **Risk:** medium (touches multiple client surfaces).
- **Duplicate-risk:** preserve per-source endpoints in parallel
  during cutover; the unified endpoint is additive.

---

## Skipped / done (do not refile)

These were considered for the Linear push but should **not** be
recreated as backlog items. Kept here so the decision is durable.

### S1. Reply-Actions Phase 1 — DONE

- **Status:** done
- **Note:** Phase 1 foundation merged. Tests:
  `tests/test_reply_actions.py`. Subsequent phases tracked under
  follow-ups in `STATUS_REPORT.md`, not here.

### S2. BlueBubbles webhook leg — DONE (residual folded)

- **Status:** done (with residual)
- **Note:** Live webhook verified 2026-04-24 — receipt
  `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`
  (`PASS-webhook-only`). Remaining outbound send issue is folded
  into item 6 (x-intake live ACK smoke) via
  `[FOLLOWUP: bluebubbles-send-method]`. Do not refile.

### S3. Network monitoring — DONE

- **Status:** done
- **Note:** `network-dropout-watch` LaunchAgent armed and verified
  healthy 2026-04-23. Phase-2 prompt drafted for the
  `security_utils` import fix. Tracked in `STATUS_REPORT.md`; no
  separate backlog entry needed.

### S4. Markup detector — HOLD / verify-stale

- **Status:** skip
- **Note:** Markup tool is `online` per `/api/symphony/markup/health`
  and the host launchd unit. No active work item; revisit only if a
  staleness signal appears. Do not file as ongoing backlog.

---

## Change log

- 2026-04-25 — file created. Replaces the failed Linear push
  triggered by free-tier active-issue cap. Source dedup facts:
  `/tmp/claude_code_output.md` (Linear coverage audit by Claude
  Code, 2026-04-25).
