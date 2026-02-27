# Bob the Conductor — Phase 2 Voice Receptionist
**Symphony Smart Homes | Twilio + OpenAI Realtime API**

---

## Overview

Bob the Conductor is Symphony Smart Homes' AI voice receptionist. Phase 2 is a complete rebuild of the original proof-of-concept, now running on the OpenAI Realtime API with full Twilio integration, persistent caller memory, and a Telegram-based owner dashboard.

Bob handles all inbound calls to Symphony's business line — qualifying leads, supporting existing clients, routing emergencies, and logging everything to a local SQLite database.

---

## Architecture

```
Inbound Call (Twilio)
        ↓
  twilio_config.py          ← TwiML app, webhook handlers, TwiML builders
        ↓
  call_routing.py           ← Caller ID resolution, business hours check,
                               intent detection, script selection
        ↓
  call_scripts.py           ← System prompts and greeting scripts per intent
        ↓
  OpenAI Realtime API       ← openai_realtime_config.json defines session,
  (WebSocket)                  tools, and behavior policies
        ↓
  [During Call]
  emergency_handler.py      ← Real-time keyword scan, P1/P2/P3 severity,
                               SMS + Telegram alerts to owner
        ↓
  [After Call]
  caller_memory.py          ← SQLite: call history, client data, topics,
                               sentiment, callback requests
  sms_templates.py          ← Templated SMS follow-ups to caller
  voice_analytics.py        ← Daily/weekly Telegram digests, CSV export
```

---

## File Reference

| File | Purpose |
|------|---------|
| `call_scripts.py` | All Bob's conversation scripts and system prompts. 6 script types: general incoming, known client support, sales inquiry, after-hours, vendor call, appointment reminder. |
| `call_routing.py` | Intelligent routing engine. Resolves caller ID, checks business hours, detects intent via keyword matching, selects appropriate script. |
| `twilio_config.py` | Complete Twilio integration: TwiML app setup, phone number configuration, TwiML response builders, webhook handlers (incoming, status, voicemail, transcription). |
| `caller_memory.py` | SQLite-backed CRM. Tracks every caller, all call events, topics, sentiment, escalations, callbacks, VIP flags, birthdays/anniversaries. |
| `emergency_handler.py` | Real-time emergency detection with P1/P2/P3 keyword classification. Dispatches SMS and Telegram alerts with cool-down logic. |
| `voice_analytics.py` | Analytics engine: daily/weekly summaries, top callers, escalation reports, CSV export, Telegram digest formatting. |
| `sms_templates.py` | 15 SMS templates with a template engine, variable validation, and Twilio send wrapper. |
| `openai_realtime_config.json` | Complete OpenAI Realtime session config: model, audio formats, VAD settings, 10 tool definitions, behavior policies. |
| `.env.example` | All environment variables with descriptions. Copy to `.env` and fill in. |

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A Twilio account with a phone number
- An OpenAI API key with Realtime API access
- A publicly accessible server (or ngrok for local dev)

### 2. Install Dependencies

```bash
pip install twilio openai python-dotenv
```

For full production deployment, also install:
```bash
pip install fastapi uvicorn websockets python-multipart
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual values
```

Minimum required variables:
```
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1303...
SERVER_BASE_URL=https://your-server.example.com
OWNER_CELL_NUMBER=+1303...
```

### 4. Initialize Twilio

```python
from twilio_config import get_or_create_twiml_app, configure_phone_number
import os

app_sid = get_or_create_twiml_app()
print(f"TwiML App SID: {app_sid}")

configure_phone_number(os.getenv("TWILIO_PHONE_NUMBER"), app_sid)
print("Phone number configured!")
```

### 5. Run Setup Check

```bash
python twilio_config.py
# Outputs JSON health check
```

---

## Call Flow

### Inbound Call

1. Twilio receives the call and hits `/voice/incoming` on your server
2. `twilio_config.handle_incoming_call()` builds TwiML that connects the call to a WebSocket
3. `call_routing.CallRouter.route()` determines:
   - Is the caller a known client? (checks `caller_memory`)
   - Is it business hours?
   - What's the intent? (keyword detection on any initial context)
   - Which script to use?
4. The selected script's `system_prompt` is sent to the OpenAI Realtime API to configure Bob's behavior
5. Bob speaks the `initial_greeting` when the call connects
6. Bob handles the call, using function calls (tools) to take actions

### During the Call

- `emergency_handler.EmergencyHandler.process_transcript_chunk()` scans each transcript fragment
- If P1/P2 keywords detected: SMS + Telegram alert sent to owner immediately
- Bob uses function calls to:
  - Transfer to owner
  - Schedule callbacks
  - Log information
  - Send SMS follow-ups

### After the Call

- `caller_memory.CallerMemory.log_call()` saves everything
- `sms_templates.send_sms()` sends a follow-up text to the caller
- `voice_analytics` data is updated automatically

---

## Call Scripts

Bob has 6 built-in scripts in `call_scripts.py`:

| Script Key | Used When |
|------------|-----------|
| `general_incoming` | Unknown caller, no specific intent detected |
| `known_client_support` | Caller ID matched in database + support intent |
| `sales_inquiry` | Keywords suggest new project interest |
| `after_hours` | Call received outside business hours (M-F 8am-6pm MT) |
| `vendor_call` | Keywords suggest vendor or sales rep |
| `appointment_reminder` | Outbound call to confirm an appointment |

---

## Available Tools (OpenAI Function Calls)

Bob can call 10 functions during a call:

| Tool | When to Use |
|------|-------------|
| `transfer_to_owner` | Caller requests human, or situation requires Mike |
| `schedule_callback` | Caller wants a return call at a specific time |
| `send_sms_summary` | After any call with useful info to send |
| `log_caller_info` | End of every call — always call this |
| `check_appointment_availability` | Caller wants to schedule something |
| `schedule_consultation` | New lead wants to meet with owner |
| `schedule_service_call` | Existing client needs a tech |
| `log_support_ticket` | Existing client has a system issue |
| `send_owner_emergency_text` | P1/P2 emergency detected during call |
| `log_vendor_call` | Vendor or sales rep calling |

---

## Emergency System

The emergency handler (`emergency_handler.py`) runs in parallel with every call:

- **P1** — Life/safety (fire, flood, intruder, no power): Immediate SMS + Telegram
- **P2** — Major failure (cameras offline, locks not working, internet down): Alert owner
- **P3** — Significant issue (single device not working): Log only

Cool-down: Max 1 alert per caller per 5 minutes to prevent spam.

---

## Caller Memory

The SQLite database (`caller_memory.db`) stores:

- **Callers table**: Name, company, email, VIP flag, birthday, anniversary, D-Tools project ID, preferred contact method, installed systems
- **Call events table**: Full call log with intent, sentiment, topics, escalation status, transcription, recording URL

The database is used to:
1. Personalize Bob's greeting for known clients
2. Provide context in the system prompt ("this client has Lutron lighting and Control4")
3. Power the daily/weekly analytics digest
4. Support the Telegram bot's /search and /callbacks commands

---

## Analytics

`voice_analytics.py` provides:

```python
from voice_analytics import (
    format_telegram_daily_digest,
    format_telegram_weekly_report,
    export_calls_csv,
    get_top_callers,
)

# Get today's digest (Telegram-formatted)
digest = format_telegram_daily_digest()

# Export last 30 days as CSV
csv_data = export_calls_csv(days=30)
```

---

## SMS Templates

15 templates in `sms_templates.py`:

```python
from sms_templates import render, send_sms

# Render without sending
msg = render("callback_confirmation", {
    "caller_name": "Jane Smith",
    "callback_time": " tomorrow morning",
})

# Render and send via Twilio
result = send_sms(
    to_number="+13035551234",
    template_key="appointment_confirmation",
    variables={
        "caller_name": "Jane Smith",
        "appointment_type": "consultation",
        "appt_date": "Tuesday, March 4",
        "appt_time": "10:00 AM",
    },
)
```

---

## Environment Variables Reference

See `.env.example` for the full list. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✔️ | OpenAI API key |
| `TWILIO_ACCOUNT_SID` | ✔️ | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | ✔️ | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | ✔️ | Your Twilio phone number (E.164) |
| `SERVER_BASE_URL` | ✔️ | Public URL for Twilio webhooks |
| `OWNER_CELL_NUMBER` | ✔️ | Owner's cell for emergency alerts |
| `TELEGRAM_BOT_TOKEN` | Optional | Enables Telegram notifications |
| `TELEGRAM_OWNER_CHAT_ID` | Optional | Owner's Telegram chat ID |
| `CALLER_MEMORY_DB` | Optional | SQLite DB path (default: ./caller_memory.db) |
| `RECORDING_ENABLED` | Optional | Enable call recording (default: true) |

---

## Webhook Endpoints Required

Your server must expose these endpoints:

| Method | Path | Handler |
|--------|------|---------|
| POST | `/voice/incoming` | `handle_incoming_call()` |
| POST | `/voice/status` | `handle_status_callback()` |
| POST | `/voice/fallback` | `build_fallback_twiml()` |
| POST | `/voice/voicemail-done` | `handle_voicemail_done()` |
| POST | `/voice/transcription` | `handle_transcription_callback()` |
| POST | `/voice/recording-status` | `handle_recording_status()` |
| POST | `/sms/incoming` | `handle_incoming_sms()` |

---

## Testing

### Unit Tests

Each module has a built-in smoke test:

```bash
python caller_memory.py   # CallerMemory smoke test
python twilio_config.py   # Twilio setup health check
python sms_templates.py   # Template render test
python voice_analytics.py # Sample digest output
```

### Call Routing Test

```python
from call_routing import CallRouter

router = CallRouter()

# Test after-hours routing
result = router.route("+13035551234", initial_text="")
print(result["script_key"])  # → after_hours (if called outside business hours)

# Test sales inquiry routing
result = router.route("+10000000000", initial_text="I'm interested in a new home theater")
print(result["script_key"])  # → sales_inquiry
```

---

## Production Deployment Notes

1. **HTTPS required**: Twilio only sends webhooks to HTTPS endpoints. Use a valid SSL certificate.
2. **Validate webhook signatures**: `validate_twilio_signature()` in `twilio_config.py` — use this in production.
3. **SQLite concurrent access**: The WAL mode in `caller_memory.py` handles concurrent calls safely. For very high volume, migrate to PostgreSQL.
4. **Recording compliance**: Check your state's call recording consent laws. Colorado is a one-party consent state.
5. **Environment variables**: Never commit `.env` to source control. Use a secrets manager in production.

---

## Phase 3 Roadmap

- [ ] FastAPI server scaffold with all webhook endpoints
- [ ] WebSocket bridge between Twilio Media Streams and OpenAI Realtime
- [ ] Telegram bot integration (dashboard, /search, /callbacks, /digest)
- [ ] D-Tools CRM sync for project-linked caller context
- [ ] Google Calendar integration for real-time availability checking
- [ ] Outbound call capability (appointment reminders, VIP birthday calls)
- [ ] Multi-location support (different scripts per branch)

---

*Phase 2 built February 2026 | Symphony Smart Homes — Bob the Conductor v2.0*
