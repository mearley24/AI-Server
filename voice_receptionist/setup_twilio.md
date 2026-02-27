# Twilio Setup Guide — Bob the Conductor

This guide walks through the one-time Twilio configuration needed to connect Bob to a real phone number.

---

## Prerequisites

- A Twilio account ([console.twilio.com](https://console.twilio.com))
- A purchased or ported phone number in your Twilio account
- Bob's server running and reachable at a public HTTPS URL (use ngrok for local dev, or the server's domain in production)

---

## Step 1 — Find your credentials

1. Log in to [console.twilio.com](https://console.twilio.com).
2. On the dashboard, copy your **Account SID** and **Auth Token**.
3. Paste them into your `.env` file:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 2 — Configure your phone number

1. In the Twilio Console, go to **Phone Numbers → Manage → Active Numbers**.
2. Click the number you want Bob to answer.
3. Scroll to **Voice & Fax** → **A Call Comes In**.
4. Set the webhook to **HTTP POST** and enter:

```
https://YOUR_SERVER_URL/incoming-call
```

5. Click **Save**.

---

## Step 3 — Verify WebSocket connectivity

Bob uses Twilio's **Media Streams** feature to send/receive raw audio over WebSocket. Twilio requires:

- The WebSocket URL must be **`wss://`** (secure WebSocket).
- The URL is auto-derived from `SERVER_URL`: `wss://YOUR_SERVER_URL/media-stream`.
- Your server must have a valid TLS certificate (Let's Encrypt works great).

### Local development with ngrok

```bash
ngrok http 3000
# Note the https://xxxx.ngrok.io URL
# Set SERVER_URL=https://xxxx.ngrok.io in .env
# Configure Twilio webhook to https://xxxx.ngrok.io/incoming-call
```

---

## Step 4 — Test the integration

```bash
# Start Bob
node server.js

# Call your Twilio number
# You should hear Bob answer within 1-2 seconds
```

Check the server console for:
```
[bob] Incoming call from +1XXXXXXXXXX
[bob] Media stream connected
[bob] OpenAI Realtime connected
[bob] Stream started | SID: MZxxx | Caller: +1XXXXXXXXXX
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bob doesn't answer | Webhook URL wrong or server not reachable |
| Silence after connect | OpenAI key missing or Realtime API not enabled |
| `TWILIO_AUTH_TOKEN` error | Token rotated — update `.env` |
| Echo / feedback | Use headset; mulaw codec mismatch |
