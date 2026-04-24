# BlueBubbles → Cortex Live Webhook Verification

UTC stamp: 20260424-154222
Host: bob (Bobs-Mac-mini.local, Mac Mini M4)
Runner: Claude Code
Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md

## Nonce

nonce: BBCX-20260424-ad0c6a
(This string was sent by external sender in Step 5)

---

## Step 1 — Health baseline

```
bluebubbles-health.sh --json:
{"cortex_health":{"status":"healthy","reason":null},
 "bluebubbles_server":{"status":"healthy","reason":null,"server_version":"1.9.9","private_api":false}}

/api/bluebubbles/health:
status: healthy
inbound_count: 0             ← INBOUND_BEFORE = 0
last_inbound_event_at: None  ← LAST_EVENT_BEFORE = None
webhook_endpoint: /hooks/bluebubbles
routing_policy: allow_owner_only
```

Both Cortex and BlueBubbles server healthy. Step 1 PASS.

---

## Step 2 — Webhook URL (UI)

Matt confirmed: `correct` — URL configured as `http://127.0.0.1:8102/hooks/bluebubbles`

This is the correct form for a host-side LaunchAgent reaching Cortex on the Docker port binding.

---

## Step 3 — Cortex receiver contract

```
cortex/bluebubbles.py:680 — @app.post("/hooks/bluebubbles", ...) — handler registered
routing policy: allow_owner_only
allowed_phones_count: 1  (Matt's number)
allowed_chat_guids_count: 0
```

Expected behavior: any inbound POST to `/hooks/bluebubbles` increments `inbound_count` regardless
of sender. The allowlist governs whether the event proceeds to Redis publish.

---

## Step 4 — Redis lane prep

```
redis: Up (healthy)
redis-cli PING: PONG
channels: events:bluebubbles, events:imessage (pubsub — no LLEN applicable)
```

---

## Step 5 — Nonce + external send coordination

Nonce: BBCX-20260424-ad0c6a
External sender: distinct phone number (not Matt's primary)
Matt confirmed: sent
UTC approximate send time: ~2026-04-24T15:43:00Z

---

## Step 6 — Time-windowed polls (12 × 10s = 120s)

| Poll | Elapsed | inbound_count | last_inbound_event_at |
|------|---------|---------------|-----------------------|
| 1    | 0s      | 0             | None                  |
| 2    | 10s     | 0             | None                  |
| 3    | 20s     | 0             | None                  |
| 4    | 30s     | 0             | None                  |
| 5    | 40s     | 0             | None                  |
| 6    | 50s     | 0             | None (private_api=False noted) |
| 7    | 60s     | 0             | None                  |
| 8    | 70s     | 0             | None                  |
| final| 120s+  | 0             | None                  |

`inbound_count` did not advance in the 120-second window.
No `POST /hooks/bluebubbles` found in Cortex logs over the full 10-minute window.

---

## Step 7 — Log excerpts (redacted)

Cortex logs showed only:
- `GET /health` health-check polls
- `GET /api/bluebubbles/health` health-check polls
- `POST /remember` from Docker-internal services (172.18.0.x)
- Zero `POST /hooks/bluebubbles` entries

No webhook delivery attempt reached Cortex.

---

## Step 8 — Dedup / DB evidence

N/A — no inbound event arrived; nothing to dedup.

---

## Root cause analysis

**`private_api: false`** — BlueBubbles server is running WITHOUT the Private API enabled.

With Private API disabled, BlueBubbles can only observe iMessages that are:
- Sent through BlueBubbles' own interface, OR
- Received by the Mac **and** intercepted via the private Apple framework hooks that
  require the Private API to be active.

Without Private API, incoming iMessages received by Mac Messages.app are NOT forwarded
as webhook events. This is why:
- `inbound_count` has been 0 throughout all sessions
- The external send in Step 5 did not produce a webhook (message was delivered via
  Apple to the Mac Messages.app, but BlueBubbles did not intercept it)

This is NOT a Cortex configuration issue, NOT a webhook URL issue, and NOT a network
issue. It is a BlueBubbles server configuration gap.

**Fix required:** Enable Private API in BlueBubbles Server Settings.
See: https://docs.bluebubbles.app/server/private-api-setup

Private API setup on Apple Silicon (Bob = M4) requires:
1. BlueBubbles Server → Settings → Private API → Enable
2. Install the Private API helper (requires Apple Developer account or AltStore)
3. Grant accessibility permissions
4. Restart BlueBubbles server

This is a `[NEEDS_MATT]` action in the BlueBubbles UI and is outside the scope of
any automated prompt — it requires manual steps in System Settings and the
BlueBubbles UI.

---

## Verdict

**`FAIL-no-webhook`**

`inbound_count` did not change after a confirmed external iMessage send.
Webhook URL is correctly configured (`http://127.0.0.1:8102/hooks/bluebubbles`).
Cortex `/hooks/bluebubbles` handler is correctly registered.
Root cause: BlueBubbles Private API is disabled (`private_api: false`).
Without Private API, incoming iMessages are not forwarded as webhook events.

---

## Followups

- `[FOLLOWUP: bluebubbles-private-api-disabled]` — Enable Private API in BlueBubbles Server
  Settings. Follow https://docs.bluebubbles.app/server/private-api-setup.
  Once enabled, `private_api: true` will appear in health probe and incoming iMessages
  will trigger webhook delivery to `http://127.0.0.1:8102/hooks/bluebubbles`.
  No code changes needed in Cortex or the repo — the pipeline is ready and waiting.
  Proposed follow-up prompt: `.cursor/prompts/2026-04-25-cline-bluebubbles-private-api-verify.md`
  (to be written after Matt enables Private API).
