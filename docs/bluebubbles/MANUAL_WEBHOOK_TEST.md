# BlueBubbles Webhook — Manual Test Procedure

This document describes how to verify the BlueBubbles → Cortex webhook path end-to-end without
sending real outbound iMessages or relying on automated synthetic pings.

## Background

The BlueBubbles server (running as a LaunchAgent, `com.bluebubbles.server`) sends webhook events
to Cortex at `http://127.0.0.1:8102/hooks/bluebubbles` (or the internal Docker gateway address)
whenever an iMessage is received or sent.  A safe automatic health probe is available via:

```bash
bash scripts/bluebubbles-health.sh
# or in JSON mode:
bash scripts/bluebubbles-health.sh --json
```

That probe hits `http://127.0.0.1:8102/api/bluebubbles/health` (aggregated) and the BlueBubbles
`/api/v1/server/info` directly.  It confirms the server is reachable and returns version info,
but it does **not** exercise the webhook delivery path.

## Prerequisites

- BlueBubbles server is running: `launchctl list | grep bluebubbles`
- Cortex is healthy: `curl -s http://127.0.0.1:8102/health`
- You have access to a real iPhone or Mac Messages app on a second device

## Test steps

### Option A — Live iMessage ping (preferred)

1. From a **different device** (phone or second Mac), send a short text to Matt's number
   (`+1-970-519-3013`).
2. Wait ~10 seconds, then check the Cortex inbound counter:
   ```bash
   curl -s http://127.0.0.1:8102/api/bluebubbles/health | python3 -m json.tool
   ```
   Look for `"inbound_count"` — it should have incremented by 1.
3. Check `"last_inbound_event_at"` — should be within the last 60 seconds.
4. Optionally check Cortex logs for the event:
   ```bash
   docker logs cortex --tail 20 2>&1 | grep -i bluebubbles
   ```

### Option B — Synthetic POST to Cortex webhook (no iMessage needed)

This tests Cortex's webhook receiver **only**; it does not verify BlueBubbles server delivery.
No outbound iMessage is triggered when the message body contains the test sentinel:

```bash
bash scripts/api-post.sh http://127.0.0.1:8102/hooks/bluebubbles \
  '{"type":"new-message","data":{"chats":[],"handle":{},"message":{"text":"__WEBHOOK_SMOKE_TEST__","isFromMe":false},"tempGuid":"smoke-test"}}'
```

Expected: HTTP 200 with `{"status": "ok"}` (or similar).
The Cortex routing policy (`allow_owner_only`) will silently drop messages from unknown numbers,
so no iMessage reply will be sent. After the POST, confirm `inbound_count` incremented via the
health endpoint.

### Option C — Log inspection only

If no second device is available and you don't want to POST synthetic data:

1. Tail the Cortex log and wait for a natural event (email, heartbeat, etc.):
   ```bash
   docker logs cortex --tail 40 2>&1
   ```
2. Verify `last_ping_ok_at` in the health response is recent (< 5 min old).
3. Record in the audit log that a synthetic ping was not performed and note the last known
   good inbound event timestamp.

## Acceptance criteria

| Check | Pass condition |
|---|---|
| `scripts/bluebubbles-health.sh` exits 0 | Both cortex and server status = `healthy` |
| Server version known | Non-empty `server_version` in health JSON |
| Webhook path exercised | `inbound_count` incremented OR synthetic POST returns 200 |
| No auth credentials in output | Only host and path are logged, not password/token |

## Known limitations

- `private_api: false` means BlueBubbles uses AppleScript/accessibility instead of the private
  iMessage framework.  Delivery may be slightly slower and tapback/reaction events may not forward.
- If `inbound_count` stays 0 over many hours with a known-active iMessage account, check the
  BlueBubbles server webhook configuration in the app UI (Settings → Webhooks) to confirm the
  target URL matches `http://127.0.0.1:8102/hooks/bluebubbles` (or the Docker gateway address).

## Last automated check (from Priority 1 run 2026-04-21)

```json
{
  "cortex_health": {"status": "healthy"},
  "bluebubbles_server": {"status": "healthy", "server_version": "1.9.9", "private_api": false}
}
```
Cortex health endpoint returned `inbound_count: 0` — no iMessages received yet on this install.
Last successful server ping: 2026-04-22T01:32:54 UTC. Manual test (Option A or B) recommended
to confirm end-to-end webhook delivery before relying on inbound routing for production use.
