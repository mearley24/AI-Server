# Bob the Conductor — AI Voice Receptionist

Bob is Symphony Smart Homes' always-on phone receptionist powered by **Twilio** (call handling) and **OpenAI's Realtime API** (gpt-4o-realtime, bidirectional audio streaming). He answers calls, looks up client accounts, walks through guided troubleshooting, schedules service visits on Google Calendar, and sends a nightly summary of every call to the team.

---

## Architecture

```
Inbound Call
    │
    ▼
Twilio Voice → /incoming-call → TwiML <Connect><Stream>
    │
    ▼ (WebSocket)
Node.js server (server.js)
    │          │
    ▼          ▼
OpenAI      Business logic
Realtime    ┌──────────────────┐
API         │ client_lookup.js │ ← SQLite clients DB
(gpt-4o)    │ troubleshoot.js  │ ← decision trees
            │ scheduler.js     │ ← Google Calendar
            │ call_logger.js   │ ← SQLite call log
            └──────────────────┘
```

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/mearley24/AI-Server.git
cd AI-Server/voice_receptionist
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in Twilio, OpenAI, Google Calendar credentials
```

### 3. Seed client database

```bash
node scripts/seed_clients.js
```

### 4. Run locally (with ngrok for Twilio webhooks)

```bash
ngrok http 3000
# Copy the HTTPS URL, set SERVER_URL in .env, configure Twilio webhook
node server.js
```

### 5. Production (Docker)

```bash
docker compose up -d
```

---

## Environment Variables

See `.env.example` for the full list. Required variables:

| Variable | Description |
|---|---|
| `SERVER_URL` | Public HTTPS URL (used for Twilio signature & WS URL) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (E.164) |
| `OPENAI_API_KEY` | OpenAI key with Realtime API access |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | Path to GCP service-account JSON |
| `GOOGLE_CALENDAR_ID` | Calendar ID for scheduling |
| `SENDGRID_API_KEY` | SendGrid key for daily summary emails |

---

## File Overview

| File | Purpose |
|---|---|
| `server.js` | Express + WebSocket server; Twilio ↔ OpenAI bridge |
| `client_lookup.js` | Find client record by phone number or name |
| `troubleshoot.js` | AV/network troubleshooting decision-tree engine |
| `scheduler.js` | Google Calendar service-call scheduling |
| `call_logger.js` | Log call events to SQLite |
| `scripts/seed_clients.js` | Populate client database with sample data |
| `scripts/daily_summary.js` | Send nightly email digest of call logs |
| `data/clients.json` | Source-of-truth client records (edit to customize) |
| `system_prompt.md` | Bob's full system prompt for the Realtime model |
| `setup_twilio.md` | Step-by-step Twilio configuration guide |

---

## Deployment

See the **Mission Control** deployment dashboard at `dashboard/index.html` for a complete, step-by-step guide.
