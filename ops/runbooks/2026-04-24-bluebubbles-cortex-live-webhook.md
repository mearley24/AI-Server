# Runbook — BlueBubbles → Cortex Live Webhook Verification (Bob, 2026-04-24)

**Status:** `DONE` — webhook leg verified live 2026-04-24 UTC.
Verdict `PASS-webhook-only`. Evidence
`ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`
(inbound_count 0→3 after external send from distinct phone number, all
3 events HTTP 200 at `/hooks/bluebubbles`, policy-dropped by
`allow_owner_only` because sender was not on `inbound.allowed_phones`).
Reaching `PASS-webhook-and-policy` requires adding a trusted test
number to `config/bluebubbles_routing.json` `inbound.allowed_phones`
— that is a separate, future gate, not a re-run of this runbook.

Human-approved companion runbook for the autonomous prompt at
`.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`
(now `Status: done`). This file is **human reference** — it is not
autonomy-tagged and must be skipped by the dispatcher (per the
autonomous-prompt standard, runbooks do not carry
`<!-- autonomy: start -->` metadata).

## Purpose

Verify, with full-leg evidence, that an iMessage sent from a **different
phone number** to Matt's BlueBubbles handle on Bob (Mac Mini M4):

1. Is accepted by the BlueBubbles server, and
2. Is POSTed to the Cortex webhook at `/hooks/bluebubbles`, and
3. Produces a normalized event on the Cortex side
   (`inbound_count` incremented + `last_inbound_event_at` updated),
4. Optionally lands on Redis `events:bluebubbles` /
   `events:imessage` lanes and (if wired) in the Cortex dedup store.

This runbook exists because the 2026-04-21 stage-2 webhook verification
produced `inbound_count = 0` (no real inbound event had arrived), and
because Matt observed self-to-self iMessage does **not** trigger the
webhook — which is expected Apple iMessage-routing behavior, not a
BlueBubbles bug.

## Source-of-truth webhook URL

From `cortex/bluebubbles.py:680` (`@app.post("/hooks/bluebubbles")`) and
`docs/bluebubbles/MANUAL_WEBHOOK_TEST.md:9`, the loopback form is:

```
http://127.0.0.1:8102/hooks/bluebubbles
```

BlueBubbles runs as a host-side LaunchAgent (`com.bluebubbles.server`),
not in Docker, so the `cortex` hostname form
(`http://cortex:8102/hooks/bluebubbles`) is **only valid from inside
the compose network** (see `docker-compose.yml` `CORTEX_URL=http://cortex:8102`
entries). Both forms are recorded in evidence; the loopback form is
the one the BlueBubbles UI should carry.

## Pre-flight

Before running the autonomous prompt, Matt confirms on Bob:

1. Cortex container is up:
   ```
   docker ps --filter name=cortex --format '{{.Names}}\t{{.Status}}'
   ```
2. BlueBubbles LaunchAgent is loaded:
   ```
   launchctl list | grep com.bluebubbles.server
   ```
3. Cortex health is green:
   ```
   curl -sS --max-time 5 http://127.0.0.1:8102/health
   ```
4. BlueBubbles aggregate health is green:
   ```
   bash scripts/bluebubbles-health.sh
   ```

If any of the above is red, do **not** run the verification prompt.
File a separate `[FOLLOWUP]` for the red item first.

## Bounded command reference

All commands below are zsh-safe per `.clinerules` — no heredocs, no
inline interpreters, no interactive editors, no `tail -f`, no
`--watch`. Each command is copy-pasteable into a Terminal tab on Bob.

### Health snapshot

```
bash scripts/bluebubbles-health.sh --json
curl -sS --max-time 5 http://127.0.0.1:8102/api/bluebubbles/health | python3 -m json.tool
```

### Routing config summary (counts only, no phone numbers)

```
test -f config/bluebubbles_routing.json && python3 -c "import json;d=json.load(open('config/bluebubbles_routing.json'));print('policy:',d.get('default_policy'));print('allowed_phones_count:',len((d.get('inbound') or {}).get('allowed_phones',[])));print('allowed_chat_guids_count:',len((d.get('inbound') or {}).get('allowed_chat_guids',[])))"
```

### Redis reachability

```
docker exec -T redis redis-cli PING
```

### Bounded Cortex log grep (2-minute window)

```
docker logs cortex --since 2m --tail 200 2>&1 | grep -E "bluebubbles|hooks/bluebubbles|webhook" | head -40
```

### Bounded poll (single iteration — the prompt loops this 12× max)

```
curl -sS --max-time 5 http://127.0.0.1:8102/api/bluebubbles/health | python3 -c "import json,sys;d=json.load(sys.stdin);print('inbound_count=',d.get('counters',{}).get('inbound_count'));print('last_inbound_event_at=',d.get('last_inbound_event_at'))"
```

## Manual coordination — external send

The external message is **not** automated. Matt coordinates,
out-of-band, a human on a different phone number sending an iMessage
to Matt's BlueBubbles handle containing only the nonce:

```
BBCX-<UTC-YYYYMMDD>-<6 hex>
```

Example (illustrative only): `BBCX-20260424-3f9a1e`.

Do **not** send from Matt's own Continuity-linked devices. Apple
routes self-to-self iMessage through a side-channel that BlueBubbles
cannot observe; that is the known quirk that motivated this runbook.

## UI check — BlueBubbles Settings Webhook URL

Matt opens the BlueBubbles Server app on Bob → Settings → Webhooks
(1.9.x) or Settings → Server → Webhook URL (earlier 1.9.x minor
versions). Record, redacted:

| Field | Expected |
|---|---|
| Webhook URL | `http://127.0.0.1:8102/hooks/bluebubbles` |
| Method | POST |
| Enabled | yes |
| Auth token in URL query string | redact to `***REDACTED***` if present |

**Do not edit.** If the field is empty, wrong, or disabled, stop and
raise `[FOLLOWUP: bluebubbles-webhook-url-mismatch]`. A separate,
explicitly-approved prompt is needed to change it
(`APPROVE: bluebubbles-webhook-url`).

## Redaction rules

Before anything lands in `ops/verification/*.md`:

- Phone numbers → last-4 form (`+1XXXXXXX1234`).
- Message bodies → nonce-only. All other text → `***REDACTED***`.
- BlueBubbles API password / token → `***REDACTED***`.
- Email addresses → local-part redacted (`***@example.com`).

## Verdict classes

One of:

- `PASS-webhook-and-policy` — inbound_count advanced **and** event
  reached processing (sender allowlisted).
- `PASS-webhook-only` — inbound_count advanced but event was
  policy-dropped. Proves the webhook leg is live; allowlist is the
  gate.
- `FAIL-no-webhook` — inbound_count did not change. Webhook delivery
  is broken; the UI URL check is the primary lead.
- `BLOCKED-no-external-sender` — no external send in this run.
- `BLOCKED-ui-inaccessible` — Settings UI not observable this run.
- `BLOCKED-unhealthy-baseline` — pre-flight red.

## Escalation paths

| Condition | Follow-up prompt (proposed) |
|---|---|
| Webhook URL mismatch | `.cursor/prompts/<date>-cline-bluebubbles-webhook-url-fix.md` gated on `APPROVE: bluebubbles-webhook-url` |
| BlueBubbles server down | `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md` re-run |
| Cortex unhealthy | separate cortex-health diagnostic prompt |
| No external sender | park this run; resume next session |
| Duplicated inbound | reference `.cursor/prompts/2026-04-23-cline-cortex-dedup-upsert.md` for dedup wiring |

## What this runbook does NOT authorize

- Editing the BlueBubbles Webhook URL field.
- Restarting BlueBubbles, Cortex, or any Docker container.
- Opening or forwarding ports.
- Sending any outbound iMessage or SMS from Bob.
- Writing secrets (BLUEBUBBLES_PASSWORD, API keys, tokens) into
  evidence files or commit messages.
- Touching harness-owned files (`.claude/**`, `.mcp.json`,
  `CLAUDE.md`, `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`).

## References

- Prompt: `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`
- Cortex handler: `cortex/bluebubbles.py:680` (`/hooks/bluebubbles`),
  `cortex/bluebubbles.py:247` (`allow_owner_only` policy).
- Manual procedure: `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md`.
- Prior verification: `ops/verification/20260421-193143-bluebubbles-webhook.md`.
- Server arming runbook: `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`.
- Reply-leg context: `ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`.
