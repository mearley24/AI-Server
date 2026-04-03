# API-6: Hermes Multi-Platform Messaging — Wire Channels Into notification-hub

## The Problem

Bob currently sends notifications via iMessage only, through `scripts/imessage-server.py`. `notification-hub/main.py` exists as a central notification dispatcher but does not yet route messages to different channels based on message type or recipient. `integrations/telegram/telegram_bot.py` and `symphony/email/client.py` (Zoho) exist but are not connected to notification-hub. The goal is to wire these together so any service in the stack publishes one notification event to Redis and Hermes routes it to the right channel — iMessage for Matt alerts, Zoho email for client communications, Telegram as a future stub.

## Context Files to Read First

- `notification-hub/main.py` (the current dispatcher — read every line, understand its current routing logic and what channels it already supports)
- `scripts/imessage-server.py` (the iMessage bridge — understand what Redis channel it listens on, the message format it expects, and how it sends)
- `integrations/telegram/telegram_bot.py` (understand what is already implemented vs stubbed)
- `symphony/email/client.py` (Zoho email client — understand its send method signature and auth mechanism)
- `scripts/start_hermes.sh` (the startup script — understand how these processes are launched)
- `email-monitor/router.py` (for understanding the existing Redis pub/sub patterns in use)

## Prompt

Read the existing code first — understand what `notification-hub/main.py` already does, what Redis channel `imessage-server.py` listens on, and what the Zoho and Telegram clients already know how to do. The job is to add channel routing to notification-hub and wire the existing channel clients into it.

### 1. Understand the Existing iMessage Bridge

Read `scripts/imessage-server.py` and document:

- What Redis channel does it subscribe to? (likely `notifications:imessage` or similar)
- What message format does it expect? (JSON with `to`, `message`, and optionally `priority`?)
- Does it handle failure gracefully if the recipient is not online?

This is the gold standard — it already works. Build the other channels to match its patterns.

### 2. Extend notification-hub/main.py — Channel Routing

Add a routing layer to `notification-hub/main.py`. The routing logic should be driven by two fields in the notification payload: `channel` (explicit override) and `message_type` (for auto-routing).

**New unified endpoint — `POST /api/send`:**

```python
class NotificationRequest(BaseModel):
    recipient: str          # "Matt", "client:john@example.com", "broadcast"
    message: str            # The text to send
    channel: str = "auto"   # "auto" | "imessage" | "email" | "telegram"
    priority: str = "normal"  # "normal" | "high" | "urgent"
    message_type: str = "general"  # "alert" | "trade" | "client_comm" | "system_log" | "general"
    subject: str = ""       # Email subject (only for email channel)
    thread_id: str = ""     # Optional — for reply threading
    metadata: dict = {}     # Any extra context (market name, trade amount, etc.)

@app.post("/api/send")
async def send_notification(req: NotificationRequest):
    channel = resolve_channel(req)
    result = await dispatch(req, channel)
    return {"status": "ok", "channel": channel, "message_id": result.get("message_id")}
```

**Channel resolution logic — `resolve_channel(req)` function:**

```python
def resolve_channel(req: NotificationRequest) -> str:
    if req.channel != "auto":
        return req.channel  # explicit override — trust it
    
    # Auto-routing rules
    if req.message_type in ("alert", "trade") and req.priority in ("high", "urgent"):
        return "imessage"  # Fast alerts → iMessage
    
    if req.recipient.startswith("client:"):
        return "email"  # Client communications → always email (professional)
    
    if req.message_type == "system_log":
        return "telegram"  # Debug/system logs → Telegram (future stub)
    
    if req.priority == "urgent":
        return "both_imessage_email"  # Urgent (portfolio drop, VPN down) → both
    
    if req.recipient == "Matt":
        return "imessage"  # Matt's personal alerts → iMessage
    
    return "imessage"  # Default fallback
```

### 3. Wire iMessage Channel

In notification-hub, add an `imessage` dispatcher that publishes to the Redis channel `imessage-server.py` already listens on:

```python
async def send_imessage(req: NotificationRequest) -> dict:
    payload = {
        "to": req.recipient if req.recipient != "Matt" else MATT_PHONE_NUMBER,
        "message": req.message,
        "priority": req.priority,
    }
    redis_client.publish(IMESSAGE_REDIS_CHANNEL, json.dumps(payload))
    msg_id = f"imsg_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    await store_thread(req.thread_id, msg_id, "imessage", req.message)
    return {"message_id": msg_id}
```

Replace `IMESSAGE_REDIS_CHANNEL` with the actual channel name from `imessage-server.py`.
Store `MATT_PHONE_NUMBER` in `.env` as `MATT_PHONE_NUMBER` — do not hardcode it.

### 4. Wire Zoho Email Channel

Read `symphony/email/client.py` for the send method signature, then add an `email` dispatcher:

```python
async def send_email(req: NotificationRequest) -> dict:
    from symphony.email.client import ZohoEmailClient  # use actual class name from the file
    
    client = ZohoEmailClient()  # or however it's instantiated — read the constructor
    
    recipient_email = req.recipient
    if req.recipient.startswith("client:"):
        recipient_email = req.recipient[len("client:"):]
    
    subject = req.subject or f"Message from Bob — {datetime.now().strftime('%b %d')}"
    
    msg_id = await client.send(
        to=recipient_email,
        subject=subject,
        body=req.message,
    )
    
    await store_thread(req.thread_id, msg_id, "email", req.message)
    return {"message_id": msg_id}
```

If `ZohoEmailClient` already handles auth via env vars, do not add new auth code. If it requires explicit credentials, pull them from `.env` using `os.getenv`.

### 5. Wire Telegram Channel (Stub)

Read `integrations/telegram/telegram_bot.py`:

- If it already has a `send_message` method: wire it in as the Telegram dispatcher
- If it is a listener-only bot: add a stub that logs the message and returns a fake message_id

```python
async def send_telegram(req: NotificationRequest) -> dict:
    try:
        from integrations.telegram.telegram_bot import TelegramBot  # actual class name
        bot = TelegramBot()
        msg_id = await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=req.message)
        return {"message_id": str(msg_id)}
    except Exception as e:
        logger.warning(f"Telegram send failed (stub mode): {e}")
        return {"message_id": f"telegram_stub_{int(time.time())}"}
```

This should never crash the notification-hub — Telegram is non-critical.

### 6. Handle "both_imessage_email" for Urgent Alerts

```python
async def dispatch(req: NotificationRequest, channel: str) -> dict:
    if channel == "both_imessage_email":
        results = await asyncio.gather(
            send_imessage(req),
            send_email(req),
            return_exceptions=True
        )
        return {"message_id": f"multi_{int(time.time())}"}
    elif channel == "imessage":
        return await send_imessage(req)
    elif channel == "email":
        return await send_email(req)
    elif channel == "telegram":
        return await send_telegram(req)
    else:
        logger.warning(f"Unknown channel: {channel}. Falling back to iMessage.")
        return await send_imessage(req)
```

### 7. Add Redis Pub/Sub Listener

Services should be able to publish a notification to Redis without calling the HTTP endpoint. Add a Redis subscriber in notification-hub that listens on multiple channels:

```python
async def redis_listener():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(
        "notifications:email",    # → Zoho email
        "notifications:imessage", # → iMessage (already used by imessage-server.py — do NOT conflict)
        "notifications:telegram", # → Telegram
        "notifications:send",     # → auto-route
    )
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        channel_override = {
            "notifications:email": "email",
            "notifications:imessage": "imessage",
            "notifications:telegram": "telegram",
            "notifications:send": "auto",
        }.get(message["channel"], "auto")
        req = NotificationRequest(**payload, channel=channel_override)
        await dispatch(req, resolve_channel(req))
```

**IMPORTANT**: Check if `imessage-server.py` already subscribes to `notifications:imessage`. If so, do NOT have notification-hub also subscribe to that same channel — you will get duplicate messages. Use `notifications:send` as the unified inbound channel and let notification-hub route to the right downstream subscriber.

### 8. Conversation Threading

Add a simple thread tracker in Redis:

```python
async def store_thread(thread_id: str, message_id: str, channel: str, message: str):
    if not thread_id:
        return
    key = f"hermes:thread:{thread_id}"
    entry = {
        "message_id": message_id,
        "channel": channel,
        "message": message[:200],
        "timestamp": time.time(),
    }
    redis_client.rpush(key, json.dumps(entry))
    redis_client.expire(key, 60 * 60 * 24 * 30)  # 30 days
```

### 9. Test Each Channel

Add a test script at `tests/test_hermes.py`:

```python
import httpx

base = "http://localhost:8099"  # or whatever port notification-hub runs on — read main.py

# Test 1: iMessage to Matt
r = httpx.post(f"{base}/api/send", json={
    "recipient": "Matt",
    "message": "Hermes test — iMessage channel working",
    "channel": "imessage",
    "priority": "normal",
})
print("iMessage:", r.json())

# Test 2: Email to client
r = httpx.post(f"{base}/api/send", json={
    "recipient": "client:test@example.com",
    "message": "Hermes test — email channel working",
    "subject": "Test from Bob",
    "channel": "email",
})
print("Email:", r.json())

# Test 3: Auto-route an urgent alert
r = httpx.post(f"{base}/api/send", json={
    "recipient": "Matt",
    "message": "TEST: Portfolio dropped 15%",
    "message_type": "alert",
    "priority": "urgent",
    "channel": "auto",
})
print("Urgent auto-route:", r.json())
```

Run `python tests/test_hermes.py` and verify each test returns `"status": "ok"`. If Zoho or iMessage cannot connect in the test environment, verify the dispatcher at least attempted to call the correct client and logged the failure — a connection error is acceptable, missing dispatch logic is not.
