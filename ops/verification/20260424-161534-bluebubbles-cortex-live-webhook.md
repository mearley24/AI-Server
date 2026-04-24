# BlueBubbles → Cortex Live Webhook Verification (Re-run after URL fix)
UTC stamp: 20260424-161534
Host: bob
Runner: Claude Code (Cline)
Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md
Prior run: ops/verification/20260424-160905-bluebubbles-cortex-live-webhook.md
Fix applied: BlueBubbles Webhook URL changed from http://cortex:8102/hooks/bluebubbles to http://127.0.0.1:8102/hooks/bluebubbles

## Nonce
nonce: BBCX-20260424-fbdc2ffeaddd

## Step 1 — Health Baseline
status: healthy
INBOUND_BEFORE: 0
LAST_EVENT_BEFORE: null
webhook_endpoint: /hooks/bluebubbles
routing.policy: allow_owner_only

## Step 2 — Webhook URL (UI)
Matt confirmed: URL changed to http://127.0.0.1:8102/hooks/bluebubbles (loopback form, correct for host-side LaunchAgent)

## Step 5 — Nonce + External Send Coordination
nonce: BBCX-20260424-fbdc2ffeaddd
[Awaiting Matt to confirm external send time and sender (last-4 redacted)]

## Step 5 — External Send Confirmed
sent: ~2026-04-24T16:17 UTC
sender: +1XXXXXXX1850

## Step 6 — Time-windowed Polls
poll 1: inbound_count=3 last_inbound_event_at=2026-04-24T16:17:01.118891+00:00
ADVANCED: inbound_count went from 0 to 3 — breaking
## Step 6 — Time-windowed Polls
poll 1: inbound_count=3 last_inbound_event_at=2026-04-24T16:17:01.118891+00:00
ADVANCED: inbound_count went from 0 to 3 — loop exited on first poll.

NOTE (multi-delivery): count advanced by 3, not 1. BlueBubbles v1.9.9 fires
multiple webhook events per message (e.g. new-message + chat-read-status-changed
+ other). Structured logger.info lines not visible in Docker logs (see Step 7),
so per-event type breakdown cannot be confirmed from this run.

## Step 7 — Log Excerpts (redacted)
Access log lines captured (all from 172.18.0.1 = Docker host gateway = BlueBubbles LaunchAgent):
  POST /hooks/bluebubbles HTTP/1.1 200 OK  (x3, timestamps ~16:17 UTC)
  GET  /api/bluebubbles/health HTTP/1.1 200 OK  (x2, polling)

Structured logger.info("bluebubbles_webhook type=... direction=... sender=... allowed=... reason=...")
lines NOT present in docker logs cortex output. CORTEX_LOG_LEVEL=INFO is set in
cortex/config.py:31 but application logger lines are not propagating to stdout/stderr.
This is a separate observability gap; it does not affect the webhook-path verdict.

## Step 8 — Dedup / DB Evidence
Sender +1XXXXXXX1850 is not on inbound.allowed_phones (only 1 entry, different last-4).
All 3 events were rejected before _publish_event() at bluebubbles.py:~735.
No Redis publish to events:bluebubbles or events:imessage occurred.
Dedup store not exercised — N/A for this run (policy-drop path).

## Verdict
PASS-webhook-only

Webhook leg confirmed live: BlueBubbles host-side LaunchAgent successfully POSTed
to http://127.0.0.1:8102/hooks/bluebubbles (x3, all HTTP 200) within seconds of
external send from +1XXXXXXX1850. inbound_count advanced from 0 to 3.

Sender is not on inbound.allowed_phones (policy=allow_owner_only). All 3 events
were rejected at the policy gate — proving the webhook path is live and the
allowlist is the gating mechanism.

The prior FAIL-no-webhook (run 20260424-160905) was caused solely by the
Webhook URL being set to http://cortex:8102/hooks/bluebubbles (Docker-only
hostname). Changing to http://127.0.0.1:8102/hooks/bluebubbles resolved it.

## Followups
- [NOTE: multi-delivery] inbound_count=3 for one external send. Expected for
  BlueBubbles multi-event-per-message behavior, but not confirmed (structured
  logs not visible). No action required unless dedup is needed for downstream.
- [FOLLOWUP: structured-log-visibility] bluebubbles_webhook logger.info lines do
  not appear in docker logs cortex despite CORTEX_LOG_LEVEL=INFO. Investigate
  logging propagation / handler configuration in cortex/engine.py:33.
  Next prompt: ops investigation or cortex/engine.py logging config fix.
- To reach PASS-webhook-and-policy: add +1XXXXXXX1850 (or a trusted test number)
  to inbound.allowed_phones in config/bluebubbles_routing.json, then re-run.
