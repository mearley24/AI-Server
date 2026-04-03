# API-6: Hermes Multi-Platform Messaging

## Context Files to Read First
- scripts/imessage-server.py
- notification-hub/main.py
- email-monitor/router.py
- email-monitor/notifier.py
- AGENTS.md (iPad voice interface section)
- integrations/telegram/telegram_bot.py

## Prompt

Build Hermes — a unified messaging layer so Bob can respond on any platform from a single interface:

1. **Message Bus** (`hermes/message_bus.py`):
   - Unified message format: `{platform, sender, recipient, text, attachments, thread_id, timestamp}`
   - Inbound handlers: receive messages from iMessage (port 8199), Telegram, email (Zoho IMAP), voice (Twilio)
   - Outbound handlers: send replies through the same channel the message arrived on
   - Redis pub/sub channel `hermes:inbound` for all incoming, `hermes:outbound` for all outgoing
   - Message dedup (same message from multiple platforms = process once)

2. **Platform Adapters** (`hermes/adapters/`):
   - `imessage.py` — wraps the existing imessage-server.py HTTP API
   - `telegram.py` — wraps the existing telegram_bot.py
   - `email.py` — wraps the existing email-monitor for send/receive
   - `voice.py` — wraps Twilio for SMS (text-based fallback for voice)
   - Each adapter implements: `send(message)`, `receive() -> AsyncIterator[Message]`, `health() -> bool`

3. **Router** (`hermes/router.py`):
   - Route incoming messages to the right handler (Bob's brain / OpenClaw / auto-responder)
   - Priority: client messages → owner messages → vendor messages → everything else
   - Caller ID resolution: map phone numbers, email addresses, and Telegram usernames to a single contact record
   - Contact registry in SQLite: `hermes/contacts.db`

4. **Cross-Platform Threading**:
   - If a client emails, Bob responds via email. If they then text about the same topic, Bob has context from the email thread.
   - Store conversation history per contact (not per platform) in SQLite
   - Context window: last 10 messages across all platforms for that contact

5. Add to docker-compose.yml as `hermes` service. Depends on Redis.

6. Health endpoint at `/health`. WebSocket at `/ws/messages` for Mission Control integration.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
