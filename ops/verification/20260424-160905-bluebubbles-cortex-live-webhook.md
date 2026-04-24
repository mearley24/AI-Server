# BlueBubbles → Cortex Live Webhook Verification
UTC stamp: 20260424-160905
Host: bob
Runner: Claude Code (Cline)
Prompt: .cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md

## Nonce
nonce: BBCX-20260424-17a268a9c930


## Step 1 — Health Baseline
{"cortex_health": {"status": "healthy", "reason": null}, "bluebubbles_server": {"status": "healthy", "reason": null, "server_version": "1.9.9", "private_api": true}}
{
    "status": "healthy",
    "reason": null,
    "ping": {
        "ok": true,
        "latency_ms": 262.9,
        "server_version": "1.9.9",
        "private_api": true,
        "macos_version": "26.3.0"
    },
    "configured": true,
    "server_url_configured": true,
    "webhook_endpoint": "/hooks/bluebubbles",
    "routing": {
        "policy": "allow_owner_only",
        "inbound_allowed_phones": [
            "+19705193013"
        ],
        "inbound_allowed_emails": [
            "mearley24@me.com"
        ],
        "inbound_allowed_chat_guids": [],
        "inbound_blocked_phones": [],
        "outbound_allowed_phones": [
            "+19705193013"
        ],
        "outbound_allowed_chat_guids": [],
        "config_path": "/app/config/bluebubbles_routing.json",
        "loaded": true
    },
    "counters": {
        "inbound_count": 0,
        "outbound_count": 0,
        "outbound_failure_count": 0
    },
    "last_inbound_event_at": null,
    "last_outbound_send_at": null,
    "last_outbound_error": null,
    "last_ping_ok_at": "2026-04-24T16:09:28.838757+00:00",
    "last_ping_error": null,
    "last_ping_latency_ms": 262.9
}

INBOUND_BEFORE: 0
LAST_EVENT_BEFORE: null
webhook_endpoint: /hooks/bluebubbles
routing.policy: allow_owner_only

Step 1 result: PASS (cortex healthy, bluebubbles healthy)

## Step 3 — Cortex Receiver Contract
10:- ``register_bluebubbles_routes`` — attaches ``POST /hooks/bluebubbles`` and
680:    @app.post("/hooks/bluebubbles", tags=["bluebubbles"])
762:            "webhook_endpoint": "/hooks/bluebubbles",
132:    "inbound_count": 0,
217:            "policy": cfg.get("default_policy", "allow_owner_only"),
218:            "inbound_allowed_phones": list(inbound.get("allowed_phones", []) or []),
221:            "inbound_blocked_phones": list(inbound.get("blocked_phones", []) or []),
222:            "outbound_allowed_phones": list(outbound.get("allowed_phones", []) or []),
228:    def is_inbound_allowed(
247:        policy = cfg.get("default_policy", "allow_owner_only")
258:        blocked_phones = {self._norm_phone(p) for p in inbound.get("blocked_phones", []) or []}
260:        if sid_phone and sid_phone in blocked_phones:
268:            self._norm_phone(p) for p in inbound.get("allowed_phones", []) or []
301:        allowed_phones = {self._norm_phone(p) for p in outbound.get("allowed_phones") or []}
306:        if dst and dst in allowed_phones:
698:        _bump("inbound_count")
702:        ok, reason = routing.is_inbound_allowed(
765:                "inbound_count": snapshot.get("inbound_count", 0),
policy: allow_owner_only
allowed_phones_count: 1
allowed_chat_guids_count: 0

Routing summary: policy=allow_owner_only, inbound_allowed_phones_count=1, inbound_allowed_chat_guids_count=0
Note: inbound_count is bumped at line 698 (before is_inbound_allowed check at line 702). Both webhook_allowed and policy_drop outcomes prove the webhook path is live.

## Step 4 — Redis Lane Prep
redis	Up 4 minutes (healthy)
Pubsub lanes: events:bluebubbles, events:imessage (publish-only — polling via XLEN/LLEN not applicable for pubsub channels)

Pubsub lanes: events:bluebubbles, events:imessage (publish-only — no XLEN/LLEN applicable)

PING: PONG
Pubsub lanes: events:bluebubbles, events:imessage (publish-only)

Step 4 result: Redis healthy, lanes named.

## Step 2 — Webhook URL (UI) [NEEDS_MATT]
[Awaiting Matt to inspect BlueBubbles Settings → Webhooks and paste description below]

## Step 5 — Nonce + External Send Coordination [NEEDS_MATT]
nonce: BBCX-20260424-17a268a9c930

External sender must send this nonce string (and only this string) as an iMessage to Matt's BlueBubbles handle on Bob, from a phone number OTHER than Matt's primary number.

[Awaiting Matt to confirm external send time and sender (last-4 redacted)]

