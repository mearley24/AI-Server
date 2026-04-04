# API-8: Voice Receptionist V2 — Twilio + OpenAI Realtime

## The Vision

Symphony's phone line is answered by Bob — a live AI voice receptionist that greets callers by name, remembers past conversations, qualifies leads, routes emergencies instantly, and sends follow-up SMS. No voicemail, no hold music, no missed calls. The V2 code files exist and are complete; they need to be wired into a running server.

Read the existing code first.

## Context Files to Read First

- `voice_receptionist/v2/call_routing.py`
- `voice_receptionist/v2/call_scripts.py`
- `voice_receptionist/v2/caller_memory.py`
- `voice_receptionist/v2/emergency_handler.py`
- `voice_receptionist/v2/sms_templates.py`
- `voice_receptionist/v2/twilio_config.py`
- `voice_receptionist/v2/voice_analytics.py`
- `voice_receptionist/docker-entrypoint.sh`
- `voice_receptionist/package.json`
- `voice_receptionist/data/clients.json`

## Prompt

The V2 module files are written and architecturally sound. Wire them into a working server that answers the Symphony phone line 24/7:

### 1. Understand the Architecture

Before writing any code:
- Read all `v2/*.py` files end to end — understand what each class and function does, what it expects as input, and what it returns
- Read `docker-entrypoint.sh` and `package.json` to understand the current runtime and startup sequence
- Read `data/clients.json` to understand the client data model (how callers are matched, what fields exist)
- Map the call flow: Twilio webhook → call_routing.py → OpenAI Realtime → caller_memory.py → response → sms_templates.py → voice_analytics.py

### 2. Build the Server Entry Point (`voice_receptionist/v2/server.py` — new file)

Create a FastAPI server that ties all v2 modules together:

```python
# Webhook routes Twilio calls into
POST /voice/incoming     # TwiML response — connects call to OpenAI Realtime WebSocket
POST /voice/status       # Call status callbacks (initiated, ringing, in-progress, completed)
POST /voice/voicemail    # Voicemail recording webhook
POST /voice/transcription  # Voicemail transcription webhook
POST /sms/incoming       # Inbound SMS handling

# WebSocket: bridges Twilio media stream to OpenAI Realtime API
WebSocket /ws/realtime
```

The `/voice/incoming` handler must:
1. Parse the Twilio request (From, To, CallSid)
2. Call `call_routing.route_call()` to determine how to handle this caller
3. If routed to Bob: return TwiML that starts a `<Stream>` to `/ws/realtime`
4. If routed to emergency: return TwiML that dials Matt's cell immediately

### 3. Wire OpenAI Realtime API

The WebSocket `/ws/realtime` endpoint bridges two streams: Twilio ↔ OpenAI Realtime.

- Load session config from `openai_realtime_config.json` (voice, VAD settings, system prompt)
- On connection: look up caller via `caller_memory.get_caller_context(from_number)` and inject into system prompt so Bob greets them by name and knows their history
- Forward Twilio audio chunks (G.711 μ-law) to OpenAI Realtime as `input_audio_buffer.append` events
- Forward OpenAI `response.audio.delta` events back to Twilio as media stream messages
- Handle OpenAI function call events: `transfer_to_owner`, `schedule_callback`, `send_sms_summary`, `log_call_intent` — route each to the appropriate v2 module
- On call end: save the full transcript and call metadata

The 10 function calls defined in `call_scripts.py` must each be implemented:
- `transfer_to_owner` → `call_routing.transfer_to_matt()`
- `schedule_callback` → store in Redis, notify Matt via iMessage
- `send_sms_summary` → `sms_templates.send_call_summary()`
- `log_call_intent` → `voice_analytics.log_intent()`
- `check_appointment` → query Redis for existing appointments
- `create_lead` → create Linear ticket, notify Matt
- `get_service_hours` → return from `twilio_config.SERVICE_HOURS`
- `escalate_emergency` → `emergency_handler.escalate()`
- `confirm_appointment` → update Redis, send confirmation SMS
- `request_callback_time` → parse preferred time, store in Redis

### 4. Wire Caller Memory (Redis-backed)

`caller_memory.py` must query Redis on every incoming call:

```python
# On incoming call
context = caller_memory.get_caller_context(from_number)
# Returns: {name, company, call_history, is_known_client, last_call_date, notes}

# After call ends
caller_memory.save_call(from_number, {
    "duration": call_duration,
    "intent": classified_intent,
    "topics": topic_list,
    "sentiment": sentiment_score,
    "action_items": action_list,
    "transcript": full_transcript
})
```

Redis key pattern: `caller:{e164_number}` — hash with all caller fields.
Previous call history: `caller_calls:{e164_number}` — list of call records (keep last 20).
Known clients from `data/clients.json` pre-seeded into Redis at server startup.

### 5. Wire Emergency Handler (Real-Time Scanning)

`emergency_handler.py` must run on every transcript chunk during an active call:

```python
# Called on every OpenAI response.audio_transcript.delta event
result = emergency_handler.scan_transcript_chunk(text_chunk, call_sid)

if result.is_emergency:
    # Immediately break into the call
    # Send SMS to Matt: +19705193013
    # Send iMessage to Matt
    # Transfer call to Matt's cell
    # Log to Redis with 5-minute cooldown key: emergency_cooldown:{from_number}
```

Emergency keywords live in `emergency_handler.py` — do not hardcode, use the existing list.
P1 (life safety): immediate transfer + SMS.
P2 (system down, urgent service): SMS + notify, Bob continues call.
5-minute cooldown per caller to prevent alert flooding.

### 6. Wire SMS Templates (Post-Call Follow-Up)

`sms_templates.py` sends follow-up SMS after calls based on intent:

```python
# Triggered by voice_analytics.log_intent() after call completes
intent_to_template = {
    "new_lead": sms_templates.LEAD_FOLLOWUP,
    "appointment_confirmed": sms_templates.APPOINTMENT_CONFIRMATION,
    "service_request": sms_templates.SERVICE_TICKET_CREATED,
    "general_inquiry": sms_templates.GENERAL_FOLLOWUP,
}
# Templates use caller name and relevant details from the call
# Sent via Twilio SMS from the same Symphony phone number
```

Only send SMS if the call lasted >30 seconds (filter out hang-ups).
Log all SMS sends in Redis: `sms_log:{call_sid}`.

### 7. Wire Voice Analytics

`voice_analytics.py` logs call data to Redis on call completion:

```python
voice_analytics.log_call({
    "call_sid": call_sid,
    "from_number": from_number,
    "duration_seconds": duration,
    "intent": intent,
    "sentiment": sentiment,  # positive / neutral / negative
    "outcome": outcome,      # lead_created / appointment_set / transferred / voicemail / hangup
    "timestamp": utc_now
})
```

Redis keys:
- `calls:daily:{YYYY-MM-DD}` — list of call SIDs for the day
- `calls:stats:{YYYY-MM-DD}` — aggregated stats (count, total_duration, lead_count, missed)
- `calls:detail:{call_sid}` — full call record

Daily analytics summary sent via iMessage to Matt at 6 PM: total calls, new leads, service requests, missed calls, average call duration.

### 8. Docker Integration

Add `voice-receptionist` service to `docker-compose.yml`:

```yaml
voice-receptionist:
  build: ./voice_receptionist
  ports:
    - "8089:8089"
  environment:
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
    - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}
    - TWILIO_PHONE_NUMBER=${TWILIO_PHONE_NUMBER}
    - REDIS_URL=redis://172.18.0.100:6379
    - MATT_CELL=+19705193013
  depends_on:
    - redis
  restart: unless-stopped
```

The existing `api/voice_webhook.py` on port 8088 handles the iPad voice interface — do NOT merge these. Keep them as separate services.

Twilio webhook URL must be set in the Twilio console to point to `https://{BOB_PUBLIC_URL}/voice/incoming`. The public URL is set via `TWILIO_WEBHOOK_BASE_URL` env var.

### 9. Test: Simulate an Incoming Call

After wiring everything:

```bash
# Simulate Twilio POST to /voice/incoming
curl -X POST http://localhost:8089/voice/incoming \
  -d "From=+13035551234&To=+17205559876&CallSid=CAtest1234&Direction=inbound"

# Expected: TwiML response with <Connect><Stream> pointing to /ws/realtime

# Check Redis for caller lookup
redis-cli HGETALL "caller:+13035551234"

# Check analytics after call
redis-cli HGETALL "calls:stats:$(date +%Y-%m-%d)"
```

Verify: routing fires, OpenAI Realtime connects, caller memory loads, SMS sent after call, analytics logged.

Use standard logging. All log messages prefixed with `[voice-receptionist]`.
