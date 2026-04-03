# API-8: Voice Receptionist V2 — Twilio + OpenAI Realtime

## Context Files to Read First
- voice_receptionist/v2/README.md (full architecture)
- voice_receptionist/v2/twilio_config.py
- voice_receptionist/v2/call_routing.py
- voice_receptionist/v2/call_scripts.py
- voice_receptionist/v2/caller_memory.py
- voice_receptionist/v2/emergency_handler.py
- voice_receptionist/v2/voice_analytics.py
- voice_receptionist/v2/sms_templates.py
- api/voice_webhook.py (existing voice endpoint on port 8088)

## Prompt

The Voice Receptionist V2 code is written but needs deployment wiring. Get Bob answering the Symphony phone line:

1. **Server integration** (`voice_receptionist/v2/server.py` — new):
   - FastAPI server that handles Twilio webhooks
   - `POST /voice/incoming` — TwiML response that connects to OpenAI Realtime WebSocket
   - `POST /voice/status` — call status callback (ringing, in-progress, completed)
   - `POST /voice/voicemail` — voicemail recording webhook
   - `POST /voice/transcription` — voicemail transcription webhook
   - WebSocket `/ws/realtime` — bridges Twilio media stream to OpenAI Realtime API

2. **OpenAI Realtime integration**:
   - Use the config from `openai_realtime_config.json` for session setup
   - Implement the 10 function calls (transfer_to_owner, schedule_callback, send_sms_summary, etc.)
   - Each function call routes to the appropriate module (caller_memory, sms_templates, etc.)
   - Handle voice activity detection (VAD) settings for natural conversation

3. **Caller memory** — wire SQLite database:
   - On each incoming call, check caller_memory for known callers
   - Pass caller context to the OpenAI system prompt so Bob greets them by name
   - After call, save: call duration, intent, topics discussed, sentiment, action items

4. **Emergency handler** — wire real-time scanning:
   - Process each transcript chunk through emergency_handler.py
   - P1/P2 detection sends immediate SMS to Matt (+19705193013) and iMessage
   - 5-minute cooldown per caller to prevent alert spam

5. **Docker integration**:
   - Add `voice-receptionist` service to docker-compose.yml, port 8089
   - Requires: OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
   - The existing voice_webhook.py (port 8088) handles the iPad voice interface — keep that separate

6. **Analytics**: daily summary via iMessage — total calls, new leads, support requests, missed calls, avg call duration.

Use standard logging.
