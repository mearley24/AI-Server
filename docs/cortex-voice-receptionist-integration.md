# Cortex ↔ Voice Receptionist — Integration Plan

**Status:** planned (read-only surface live in Cortex 2026-04-25)
**Scope:** how Cortex should ingest Bob the Conductor's call activity and
turn calls into actionable items in the dashboard.

## Today

| Surface                              | Wired? |
|--------------------------------------|--------|
| `TOOL_REGISTRY` entry (Symphony tab) | ✅ live |
| `GET /api/symphony/voice-receptionist` (status + planned-fields contract) | ✅ live |
| Overview "Calls" card                | ✅ live (empty state) |
| Symphony tab "Voice Receptionist" card | ✅ live (status + planned fields) |
| Redis `ops:voice_followup` → Linear  | ✅ live (`operations/linear_ops.py`) |
| Cortex memory ingestion of calls     | ❌ planned |
| Recent calls / voicemail / transcripts in dashboard | ❌ planned |
| Suggested follow-up actions (text · email · intake · escalate) | ❌ planned |

The voice receptionist runs at `voice_receptionist/` (container port 3000,
exposed on host `127.0.0.1:8093`). It already persists calls to a SQLite
log inside the container (`bob_data` volume) and publishes follow-up
intent to Redis channel `ops:voice_followup` whenever the agent decides a
call needs human follow-up. `operations/linear_ops.py` already subscribes
to that channel and creates Linear issues.

## Planned ingestion path

1. **Sync worker (Cortex → voice-receptionist):** small Cortex worker
   that polls or subscribes to a `voice-receptionist`-side endpoint
   exposing recent call records (currently the SQLite `call_log` table
   referenced from `voice_receptionist/call_logger.js`). Exposing a
   `/calls/recent` JSON endpoint on the receptionist is the minimal
   change required on that side.
2. **Cortex storage:** mirror call records into Cortex memory as
   `kind=call` entries with: caller name/phone, started_at, duration,
   outcome (answered/missed/voicemail), transcript excerpt, any matched
   client/project, and the Linear issue id if one was created.
3. **Action surface:** the Overview "Calls" card and the Symphony
   "Voice Receptionist" card both already declare the intended action
   set (`send_text`, `send_email`, `create_intake`, `escalate_to_matt`,
   `schedule_callback`). These map to existing Symphony services
   (BlueBubbles for SMS, Email Monitor for email, X-Intake for intake,
   notification-hub for escalation) — wire each as a POST endpoint on
   the Cortex side once the call records are flowing.

## Hard rules

- **Read-only on Twilio.** Cortex must not place calls, send SMS via
  Twilio, or modify Twilio number config. All outbound messaging routes
  through BlueBubbles / Email Monitor / notification-hub.
- **No fake data.** The card renders an honest empty state — never seed
  example calls.
- **Bind stays loopback.** The receptionist remains
  `127.0.0.1:8093` on Bob; reach it from Tailscale only via
  `tailscale serve` (see [TAILSCALE_ACCESS.md](TAILSCALE_ACCESS.md)).

## Files

- `cortex/dashboard.py` — `TOOL_REGISTRY` entry + `/api/symphony/voice-receptionist`
- `cortex/static/index.html` — Overview "Calls" card + Symphony "Voice Receptionist" card
- `cortex/static/dashboard.js` — `renderCalls`, `renderCallsSymphony`, `loadVoiceReceptionist`
- `voice_receptionist/server.js` — already publishes `ops:voice_followup`
- `operations/linear_ops.py` — already routes `ops:voice_followup` to Linear

## Next increments

1. Add `GET /calls/recent?limit=20` to `voice_receptionist/server.js`
   reading from the SQLite call log (read-only, no Twilio interaction).
2. Add a Cortex-side fetcher for that endpoint and surface real records
   in the existing UI cards.
3. Wire the action buttons (`send_text`, `create_intake`, …) once the
   call list is rendering live data.
