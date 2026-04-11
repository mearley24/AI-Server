# Cline Prompt N — Operations Backbone: Voice Receptionist + Calendar + Linear Workflow

## Mission

Wire three underutilized services into a cohesive operations backbone so Bob runs Symphony Smart Homes autonomously. Three parts:

1. **Kill OpenWebUI** — reclaim RAM, it's unused
2. **Finish the voice receptionist** — train it on real Symphony knowledge from `/data/symphony_docs/` (iCloud mount), wire it to calendar-agent for real scheduling, and prepare for Twilio go-live
3. **Revive calendar-agent** — make it the single source of truth for Matt's schedule, wire it to voice receptionist, email monitor, and Linear
4. **Create an Operations Linear workflow** — a persistent Linear project that tracks all of Bob's operational tasks, with auto-created issues from email, calendar, voice calls, and cortex findings

## Part 1 — Kill OpenWebUI

### 1a. Remove from docker-compose.yml

Remove the entire `openwebui:` service block from `docker-compose.yml`.

Remove the `openwebui:` entry from the `volumes:` section at the bottom.

### 1b. Remove leftover volume

Add to `scripts/cleanup.sh` (create if it doesn't exist):

```zsh
#!/bin/zsh
echo "Removing unused Docker volumes..."
docker volume rm ai-server_openwebui 2>/dev/null
echo "Done."
```

That is all for OpenWebUI. Nothing else references it.

## Part 2 — Voice Receptionist: Train + Wire + Go-Live Prep

The voice receptionist (`voice_receptionist/server.js`) is structurally complete — Twilio WebSocket to OpenAI Realtime API, client lookup, troubleshooting trees, call logging. But it has three problems:

1. **Generic system prompt** — knows nothing about actual Symphony services, pricing tiers, current projects, or the knowledge Matt has built up
2. **Scheduling calls Google Calendar** — the `scheduler.js` tries to use Google Calendar, but Bob runs Zoho Calendar. It needs to call the calendar-agent API instead.
3. **Client data is fake** — `data/clients.json` has 10 placeholder clients with 555 numbers

### 2a. Rewrite system_prompt.md with real Symphony knowledge

Replace `voice_receptionist/system_prompt.md` with a comprehensive prompt that incorporates real business knowledge. The prompt must be built from two sources:

**Source 1 — Hardcoded business facts:**

```markdown
# Bob the Conductor — System Prompt

You are **Bob**, the AI voice receptionist for **Symphony Smart Homes**, a premium residential AV and smart-home integration company based in the Denver metro area, Colorado.

## Company Profile

- **Owner/Lead Integrator**: Matt Earley
- **Phone**: (970) 519-3013
- **Email**: info@symphonysh.com
- **Service Area**: Denver metro, Front Range, mountain communities (Vail, Aspen, Breckenridge area)
- **Specialties**: Control4 whole-home automation, Lutron lighting (Caseta, RadioRA3, HomeWorks), Sonos & distributed audio, home theater (Dolby Atmos, laser projection), security cameras (Luma), structured wiring, networking (Araknis, Ruckus)
- **Business Hours**: Monday–Friday, 8:00 AM – 6:00 PM Mountain Time
- **After Hours**: Take a message, offer next-business-day callback. For emergencies (no power, security system down, active leak near electronics), text Matt immediately.

## What We Do

Symphony Smart Homes designs, installs, programs, and supports smart home systems for residential clients. Our typical project includes:

- **Pre-wire**: Running all low-voltage cabling (Cat6, speaker wire, control wiring) during construction or renovation
- **Trim/Installation**: Mounting speakers, displays, cameras, touch panels, keypads, and networking equipment
- **Programming**: Control4 system programming, lighting scene setup, audio zone configuration
- **Commissioning**: Full system testing, client walkthrough, handoff documentation
- **Ongoing Support**: Service calls, system updates, seasonal maintenance

## Pricing Guidance

- Do NOT quote specific prices on calls. Ever.
- If asked about pricing, say: "Every project is custom, so pricing depends on the scope. Matt will put together a detailed proposal after an initial consultation. Most projects start with a free phone consultation to understand your needs."
- For service calls, say: "Service visits are billed at our standard hourly rate. Matt can give you the details and schedule a time that works."

## Current Active Projects (reference only — do not share details with callers)

- Topletz residence — 84 Aspen Meadow Dr. Control4, Lutron, Sonos, security prewire. In pre-wire phase.
- These projects are confidential. If a caller asks about another client's project, politely decline.

## Vendor Calls

If the caller identifies as a vendor or sales rep:
- Log their name, company, what they're selling, and callback number
- Say: "Thanks for reaching out. I'll make sure Matt gets your information and he'll follow up if there's a fit."
- Do NOT transfer vendor calls to Matt unless they mention an existing open PO or order.

## Troubleshooting Support

You can walk callers through basic troubleshooting using the built-in decision trees:
- Audio issues (amplifier, speakers, zones)
- Video issues (displays, HDMI, streaming)
- Control4 (controller, app, touch screens)
- Lutron lighting (dimmers, keypads, shades)
- Networking (Wi-Fi, switches, APs)
- Cameras (Luma, NVR, app access)

If troubleshooting doesn't resolve the issue, schedule a service call.

## Scheduling

You can check Matt's calendar availability and schedule service calls or consultations. When scheduling:
- Confirm the client's name, address, and phone number
- Ask what the issue is (or what they want to discuss for consultations)
- Suggest available time slots from the calendar
- Confirm the appointment and let them know Matt will follow up with details

## Your Personality

- Warm, professional, and efficient. Not robotic.
- Use the caller's name once you know it.
- Keep responses to 2-3 sentences unless they ask for detail.
- You represent a premium brand. Sound confident and knowledgeable.
- If you don't know something, say: "That's a great question — let me have Matt get back to you on that directly."
- Never reveal you're AI unless directly asked. If asked, confirm honestly and pivot: "I am — but I have full access to our schedule and client records, so I can help with most things right now."

## Greeting

> "Thank you for calling Symphony Smart Homes, this is Bob. How can I help you today?"

## Escalation

If a caller is upset, repeat their concern back to them, apologize for the inconvenience, and say:
> "I'm going to flag this for Matt right away. He'll call you back within the hour during business hours, or first thing tomorrow morning if it's after hours."

## Emergency Keywords

If you hear any of these, immediately alert Matt via the emergency handler:
- "fire", "flood", "leak", "water damage", "break-in", "intruder"
- "no power", "everything is down", "alarm going off"
- "carbon monoxide", "gas smell"
```

### 2b. Dynamic Knowledge Injection

Create `voice_receptionist/knowledge_loader.js` — on server startup (and every 6 hours), read files from `/data/symphony_docs/` (the iCloud mount) and build a knowledge supplement that gets appended to the system prompt.

```javascript
/**
 * knowledge_loader.js — Reads Symphony project docs from iCloud mount
 * and builds a knowledge context string for the system prompt.
 *
 * Reads: /data/symphony_docs/ (mounted from iCloud SymphonySH folder)
 * Also reads: /data/voice-receptionist/learned_context.json (from cortex)
 *
 * Returns a string to append to the system prompt with:
 * - Active project summaries (from .md and .pdf filenames)
 * - Recent client interactions (from email-monitor Redis)
 * - Any cortex-provided context
 */

const fs = require('fs');
const path = require('path');

const SYMPHONY_DOCS = process.env.SYMPHONY_DOCS_PATH || '/data/symphony_docs';
const LEARNED_CONTEXT = '/data/voice-receptionist/learned_context.json';

function loadKnowledge() {
  let context = '\n\n## Dynamic Knowledge (auto-loaded)\n\n';

  // 1. List active project folders/files from iCloud mount
  try {
    if (fs.existsSync(SYMPHONY_DOCS)) {
      const items = fs.readdirSync(SYMPHONY_DOCS, { recursive: true })
        .filter(f => !f.startsWith('.'))
        .slice(0, 50);  // Cap at 50 items
      if (items.length > 0) {
        context += '### Active Project Files\n';
        for (const item of items) {
          context += `- ${item}\n`;
        }
        context += '\n';
      }
    }
  } catch (e) {
    console.warn('[knowledge] Could not read symphony docs:', e.message);
  }

  // 2. Load cortex-provided learned context
  try {
    if (fs.existsSync(LEARNED_CONTEXT)) {
      const learned = JSON.parse(fs.readFileSync(LEARNED_CONTEXT, 'utf8'));
      if (learned.client_notes) {
        context += '### Client Notes\n';
        for (const [name, notes] of Object.entries(learned.client_notes)) {
          context += `- **${name}**: ${notes}\n`;
        }
        context += '\n';
      }
      if (learned.recent_emails) {
        context += '### Recent Client Emails (last 48h)\n';
        for (const em of learned.recent_emails.slice(0, 10)) {
          context += `- ${em.from}: ${em.subject} (${em.date})\n`;
        }
        context += '\n';
      }
    }
  } catch (e) {
    console.warn('[knowledge] Could not read learned context:', e.message);
  }

  return context;
}

// Reload every 6 hours
let cachedKnowledge = loadKnowledge();
setInterval(() => {
  cachedKnowledge = loadKnowledge();
  console.log('[knowledge] Refreshed knowledge context');
}, 6 * 60 * 60 * 1000);

module.exports = { getKnowledge: () => cachedKnowledge, reload: () => { cachedKnowledge = loadKnowledge(); } };
```

Update `server.js` to use it:

```javascript
// At top of server.js, add:
const { getKnowledge } = require('./knowledge_loader');

// Where SYSTEM_PROMPT is constructed, change to:
const BASE_PROMPT = fs.existsSync(path.join(__dirname, 'system_prompt.md'))
  ? fs.readFileSync(path.join(__dirname, 'system_prompt.md'), 'utf8')
  : 'You are Bob, the AI voice receptionist for Symphony Smart Homes.';

// In the OpenAI session config, use dynamic prompt:
instructions: BASE_PROMPT + getKnowledge(),
```

### 2c. Replace Google Calendar with Zoho Calendar-Agent

Replace `voice_receptionist/scheduler.js` with a version that calls the calendar-agent API:

```javascript
/**
 * scheduler.js — Schedule service calls via the calendar-agent API
 */

const http = require('http');

const CALENDAR_AGENT_URL = process.env.CALENDAR_AGENT_URL || 'http://calendar-agent:8094';

async function checkAvailability(dateStr, durationMin = 60) {
  const resp = await fetch(`${CALENDAR_AGENT_URL}/calendar/free-slots?date=${dateStr}&duration=${durationMin}`);
  if (!resp.ok) throw new Error(`Calendar agent error: ${resp.status}`);
  return resp.json();
}

async function scheduleServiceCall({ clientName, address, issue, dateTimeISO, durationMin = 60 }) {
  const endTime = new Date(new Date(dateTimeISO).getTime() + durationMin * 60000).toISOString();

  const resp = await fetch(`${CALENDAR_AGENT_URL}/calendar/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: `Service Call: ${clientName}`,
      start: dateTimeISO,
      end: endTime,
      notes: `Client: ${clientName}\nAddress: ${address}\nIssue: ${issue}\nScheduled by: Bob (voice receptionist)`,
    }),
  });

  if (!resp.ok) throw new Error(`Schedule error: ${resp.status}`);
  const result = await resp.json();

  // Publish to Redis for cortex and notifications
  try {
    const redis = require('redis');
    const client = redis.createClient({ url: process.env.REDIS_URL || 'redis://redis:6379' });
    await client.connect();
    await client.publish('notifications:calendar', JSON.stringify({
      type: 'service_call_scheduled',
      client: clientName,
      address,
      issue,
      datetime: dateTimeISO,
      source: 'voice_receptionist',
    }));
    await client.disconnect();
  } catch (e) {
    console.warn('[scheduler] Redis publish failed:', e.message);
  }

  return {
    success: true,
    message: `Service call scheduled for ${clientName} at ${new Date(dateTimeISO).toLocaleString('en-US', { timeZone: 'America/Denver' })}`,
    event: result,
  };
}

module.exports = { checkAvailability, scheduleServiceCall };
```

### 2d. Update docker-compose.yml for voice-receptionist

Add the missing environment variables and volumes:

```yaml
  voice-receptionist:
    build:
      context: ./voice_receptionist
    container_name: voice-receptionist
    restart: unless-stopped
    environment:
      - PORT=3000
      - NODE_ENV=production
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}
      - SYMPHONY_PHONE=${SYMPHONY_PHONE}
      - SERVER_URL=${VOICE_SERVER_URL:-http://localhost:8093}
      - DB_PATH=/app/data/bob.db
      - CALENDAR_AGENT_URL=http://calendar-agent:8094
      - REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
      - OWNER_CELL_NUMBER=${OWNER_CELL_NUMBER:-+19705193013}
    ports:
      - "127.0.0.1:8093:3000"
    volumes:
      - ./data/voice-receptionist:/app/data
      - "${SYMPHONY_DOCS_PATH:-/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH}:/data/symphony_docs:ro"
    depends_on:
      - redis
      - calendar-agent
```

### 2e. Seed real client data

Replace `voice_receptionist/data/clients.json` with an empty array `[]`. Real clients will come from:
1. The caller_memory SQLite DB (populated as calls come in)
2. Cortex-provided `learned_context.json` (populated from email monitor data)

The fake 555 numbers must go — they'll never match a real caller and will pollute the DB.

```json
[]
```

### 2f. Twilio go-live checklist

Create `voice_receptionist/GO_LIVE_CHECKLIST.md`:

```markdown
# Voice Receptionist — Go-Live Checklist

## Prerequisites
- [ ] Twilio account active with phone number provisioned
- [ ] TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env
- [ ] SYMPHONY_PHONE set to the Twilio number (E.164 format: +1XXXXXXXXXX)
- [ ] OPENAI_API_KEY set with Realtime API access
- [ ] SERVER_URL set to public HTTPS URL (Bob needs to be reachable from Twilio)

## Networking
- [ ] Bob's Mac Mini is reachable from the internet on port 8093 (or reverse proxy)
- [ ] TLS certificate valid (Twilio requires HTTPS for webhooks, WSS for media streams)
- [ ] Option A: Use cloudflared tunnel (recommended — no port forwarding needed)
- [ ] Option B: Use ngrok (for testing)
- [ ] Option C: Port forward 8093 through router + Let's Encrypt cert

## Twilio Configuration
- [ ] TwiML App created (or use voice webhook directly)
- [ ] Phone number voice webhook set to: POST https://YOUR_URL/incoming-call
- [ ] Test call placed from a real phone — verify Bob answers and speaks

## Post-Go-Live
- [ ] Set VOICE_SERVER_URL in .env to the public URL
- [ ] Verify call logging works (check /data/voice-receptionist/bob.db)
- [ ] Verify calendar scheduling works (make a test appointment)
- [ ] Monitor OpenAI costs — each call uses Realtime API ($0.06/min audio)

## Recommended: Cloudflare Tunnel Setup
```zsh
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel login
cloudflared tunnel create bob-voice
cloudflared tunnel route dns bob-voice voice.symphonysh.com
```

Then add to docker-compose.yml or run as launchd service:
```zsh
cloudflared tunnel run --url http://localhost:8093 bob-voice
```
```

## Part 3 — Calendar Agent: Make It the Schedule Hub

The calendar-agent code is solid — Zoho Calendar API client, free slot finder, event CRUD, meeting prep, reminders loop. It just needs to be wired into everything else.

### 3a. Add Redis publishing for all calendar events

Edit `calendar-agent/api.py` — after every create/update/delete event, publish to Redis:

```python
import redis as sync_redis

def _publish_calendar_event(event_type, data):
    """Publish calendar events to Redis for other services."""
    try:
        r = sync_redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
        r.publish("notifications:calendar", json.dumps({
            "type": event_type,
            **data,
            "timestamp": datetime.now().isoformat(),
        }))
        r.close()
    except Exception as e:
        logger.warning("redis_publish_failed: %s", e)
```

Call `_publish_calendar_event("event_created", {...})` after `create_event`, etc.

### 3b. Add daily schedule briefing endpoint

Add to `calendar-agent/api.py`:

```python
@router.get("/daily-briefing")
async def daily_briefing():
    """Generate today's schedule briefing for the morning digest."""
    client = get_client()
    _require_configured(client)

    now = datetime.now()
    events = await client.list_events(
        now.strftime("%Y-%m-%dT00:00:00+00:00"),
        now.strftime("%Y-%m-%dT23:59:59+00:00"),
    )

    if not events:
        return {"briefing": "No events scheduled today. Open calendar for the day.", "events": [], "count": 0}

    lines = [f"Today's Schedule — {now.strftime('%A, %B %d')}:", ""]
    for ev in events:
        title = ev.get("title", "Untitled")
        start_raw = ev.get("dateandtime", {}).get("start", "")
        try:
            start_dt = datetime.fromisoformat(start_raw)
            time_str = start_dt.strftime("%I:%M %p")
        except (ValueError, TypeError):
            time_str = "TBD"
        lines.append(f"- {time_str}: {title}")

    return {
        "briefing": "\n".join(lines),
        "events": events,
        "count": len(events),
    }
```

### 3c. Wire calendar into OpenClaw orchestrator morning briefing

In `openclaw/orchestrator.py`, the orchestrator already checks `SERVICES["calendar"]`. Ensure the daily briefing pulls from `/calendar/daily-briefing` and includes it in the morning notification.

Add this to the orchestrator's daily tick (find the daily briefing section):

```python
# In the daily briefing assembly, add:
try:
    async with httpx.AsyncClient(timeout=10) as client:
        cal_resp = await client.get(f"{SERVICES['calendar']}/calendar/daily-briefing")
        if cal_resp.status_code == 200:
            cal_data = cal_resp.json()
            briefing_parts.append(cal_data.get("briefing", "Calendar unavailable"))
except Exception as e:
    logger.warning("calendar_briefing_fetch_failed: %s", e)
```

### 3d. Calendar + Cortex integration

The calendar-agent's reminder loop already publishes to `notifications:calendar` on Redis. The cortex (Prompt M) listens to `notifications:*`. No additional wiring needed — the cortex will automatically ingest calendar events as they happen.

## Part 4 — Operations Linear Workflow

Create a persistent "Bob Operations" project in Linear that acts as the operational task board. Issues are auto-created from:
- Voice calls requiring follow-up
- Emails requiring action
- Calendar events needing prep
- Cortex improvement proposals
- Heartbeat alerts

### 4a. Create `operations/linear_ops.py`

New file: `operations/linear_ops.py`

```python
"""
Linear Operations Workflow — auto-creates and tracks operational tasks.

Creates issues in the "Bob Operations" Linear project for:
- Voice call follow-ups
- Email action items
- Calendar prep tasks
- Cortex proposals
- System alerts

Listens on Redis channels and creates Linear issues automatically.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger("operations.linear_ops")

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID", "b1ba685a-0eff-43fe-bec9-023e3c455672")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Label IDs (created on first run if they don't exist)
LABEL_MAP = {
    "voice": None,
    "email": None,
    "calendar": None,
    "cortex": None,
    "alert": None,
    "trading": None,
}


async def _graphql(query, variables=None):
    """Execute a Linear GraphQL query."""
    if not LINEAR_API_KEY:
        logger.warning("LINEAR_API_KEY not set — skipping")
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            LINEAR_API_URL,
            headers={
                "Authorization": LINEAR_API_KEY,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables or {}},
        )
        return resp.json()


async def create_ops_issue(title, description, label_key="alert", priority=3):
    """Create a Linear issue in the Bob Operations project."""
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue { id identifier title url }
        }
    }
    """
    variables = {
        "input": {
            "teamId": LINEAR_TEAM_ID,
            "title": title,
            "description": description,
            "priority": priority,
        }
    }

    label_id = LABEL_MAP.get(label_key)
    if label_id:
        variables["input"]["labelIds"] = [label_id]

    result = await _graphql(mutation, variables)
    if result and "data" in result:
        issue = result["data"]["issueCreate"]["issue"]
        logger.info("linear_issue_created", identifier=issue["identifier"], title=title)
        return issue
    return None


async def listen_and_create():
    """Listen to Redis channels and auto-create Linear issues."""
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.psubscribe(
        "ops:*",
        "notifications:calendar",
        "notifications:trading",
    )

    logger.info("linear_ops_listener_started")

    async for msg in pubsub.listen():
        if msg["type"] not in ("pmessage",):
            continue
        try:
            channel = msg["channel"]
            data = json.loads(msg["data"])
            await _route_to_issue(channel, data)
        except Exception as e:
            logger.error("linear_ops_error", channel=str(msg.get("channel")), error=str(e))


async def _route_to_issue(channel, data):
    """Route a Redis event to a Linear issue."""

    if channel == "ops:voice_followup":
        # Voice call that needs follow-up
        caller = data.get("caller_name", "Unknown caller")
        phone = data.get("phone", "")
        summary = data.get("summary", "No summary")
        await create_ops_issue(
            title=f"Call follow-up: {caller}",
            description=f"**Caller**: {caller} ({phone})\n**Summary**: {summary}\n**Time**: {data.get('timestamp', 'unknown')}\n\n{data.get('notes', '')}",
            label_key="voice",
            priority=2,
        )

    elif channel == "ops:email_action":
        # Email requiring action
        subject = data.get("subject", "No subject")
        sender = data.get("from", "Unknown")
        await create_ops_issue(
            title=f"Email action: {subject}",
            description=f"**From**: {sender}\n**Subject**: {subject}\n**Action needed**: {data.get('action', 'Review and respond')}\n\n{data.get('snippet', '')}",
            label_key="email",
            priority=data.get("priority", 3),
        )

    elif channel == "notifications:calendar":
        event_type = data.get("type", "")
        if event_type == "service_call_scheduled":
            # Auto-create prep task for service calls
            client = data.get("client", "Unknown")
            await create_ops_issue(
                title=f"Prep for service call: {client}",
                description=f"**Client**: {client}\n**Address**: {data.get('address', '')}\n**Issue**: {data.get('issue', '')}\n**Scheduled**: {data.get('datetime', '')}\n\nPrep checklist:\n- [ ] Review client history\n- [ ] Check required equipment\n- [ ] Confirm with client day before",
                label_key="calendar",
                priority=2,
            )

    elif channel == "ops:cortex_proposal":
        # Cortex improvement proposal that needs review
        title = data.get("title", "Improvement proposal")
        await create_ops_issue(
            title=f"Cortex: {title}",
            description=f"**Proposal**: {data.get('proposal', '')}\n**Expected impact**: {data.get('impact', 'unknown')}\n**Risk**: {data.get('risk', 'unknown')}\n\nGenerated by the cortex improvement loop.",
            label_key="cortex",
            priority=data.get("priority", 4),
        )

    elif channel == "notifications:trading":
        # Only create issues for significant trading events
        score = data.get("score", 0)
        if score >= 80:  # Critical trading alert
            await create_ops_issue(
                title=f"Trading alert: {data.get('summary', 'Check trading')}",
                description=json.dumps(data, indent=2),
                label_key="trading",
                priority=1,
            )
```

### 4b. Create operations runner

New file: `operations/__init__.py` (empty)

New file: `operations/runner.py`:

```python
"""Operations service runner — starts the Linear ops listener."""

import asyncio
import logging

from linear_ops import listen_and_create

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    asyncio.run(listen_and_create())
```

### 4c. Wire existing services to publish ops events

**Email Monitor** — Edit `email-monitor/` to publish `ops:email_action` when an email needs response:

In the email monitor's processing pipeline, after categorizing an email as requiring action (ACTIVE_CLIENT, BID_INVITE, etc.), add:

```python
# After classifying email as action-required:
try:
    r.publish("ops:email_action", json.dumps({
        "subject": email["subject"],
        "from": email["from"],
        "action": "Review and respond",
        "priority": 2 if category == "ACTIVE_CLIENT" else 3,
        "snippet": email["body"][:200],
    }))
except Exception:
    pass
```

**Voice Receptionist** — Edit `voice_receptionist/server.js` to publish `ops:voice_followup` at end of calls that need follow-up:

In the `handleToolCall` function, when `log_caller_info` is called (end of every call):

```javascript
// After logging the call, check if follow-up needed:
if (args.needs_followup || args.callback_requested) {
  try {
    const redis = require('redis');
    const client = redis.createClient({ url: process.env.REDIS_URL });
    await client.connect();
    await client.publish('ops:voice_followup', JSON.stringify({
      caller_name: args.name || callerNumber,
      phone: callerNumber,
      summary: args.summary || '',
      notes: args.notes || '',
      timestamp: new Date().toISOString(),
    }));
    await client.disconnect();
  } catch (e) {
    console.warn('[ops] Redis publish failed:', e.message);
  }
}
```

**Cortex** — The cortex (Prompt M) should publish `ops:cortex_proposal` when it generates improvement proposals that need human review (risk != "safe"). Add to the cortex's improvement loop:

```python
# After generating non-safe proposals:
for proposal in queued:  # proposals not auto-executed
    r.publish("ops:cortex_proposal", json.dumps({
        "title": proposal.get("proposal", "")[:80],
        "proposal": proposal.get("proposal", ""),
        "impact": proposal.get("expected_impact", ""),
        "risk": proposal.get("risk", ""),
        "priority": 3 if proposal.get("risk") == "moderate" else 4,
    }))
```

### 4d. Add operations service to docker-compose.yml

```yaml
  operations:
    build:
      context: ./operations
      dockerfile: Dockerfile
    container_name: operations
    restart: unless-stopped
    environment:
      - LINEAR_API_KEY=${LINEAR_API_KEY}
      - LINEAR_TEAM_ID=${LINEAR_TEAM_ID:-b1ba685a-0eff-43fe-bec9-023e3c455672}
      - REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
      - TZ=America/Denver
    depends_on:
      - redis
```

### 4e. Operations Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "runner.py"]
```

### 4f. Operations requirements.txt

```
redis>=5.0
httpx>=0.27
structlog>=24.0
```

## Implementation Order

1. Remove OpenWebUI from docker-compose.yml and volumes
2. Rewrite `voice_receptionist/system_prompt.md` with real Symphony knowledge
3. Create `voice_receptionist/knowledge_loader.js`
4. Update `voice_receptionist/server.js` to use knowledge_loader
5. Replace `voice_receptionist/scheduler.js` with calendar-agent API calls
6. Replace `voice_receptionist/data/clients.json` with empty array
7. Create `voice_receptionist/GO_LIVE_CHECKLIST.md`
8. Update voice-receptionist in docker-compose.yml (env vars, volumes, depends_on)
9. Add Redis publishing to `calendar-agent/api.py`
10. Add `/calendar/daily-briefing` endpoint
11. Wire calendar briefing into OpenClaw orchestrator
12. Create `operations/` directory with linear_ops.py, runner.py, Dockerfile, requirements.txt
13. Wire email-monitor to publish `ops:email_action`
14. Wire voice-receptionist to publish `ops:voice_followup`
15. Add note in cortex code to publish `ops:cortex_proposal` (reference only — Prompt M handles cortex)
16. Add operations service to docker-compose.yml
17. Create `scripts/cleanup.sh` for removing old volumes

## Coding Rules

- All shell in zsh — no chained `&&` commands, split into separate lines
- Single quotes for git commit messages
- Python 3.11+ syntax
- Use `structlog` for Python logging
- Use `fetch()` for HTTP in Node.js (Node 20+ built-in)
- All Redis connections use authenticated URL from env
- Never expose services on 0.0.0.0 — always 127.0.0.1

## Commit

```zsh
git add -A
git commit -m 'feat: operations backbone — voice receptionist training, calendar hub, Linear workflow (Prompt N)

- Removed OpenWebUI from docker-compose (reclaim RAM)
- Rewrote voice receptionist system prompt with real Symphony knowledge
- Added knowledge_loader.js for dynamic iCloud doc ingestion
- Replaced Google Calendar scheduling with Zoho calendar-agent API
- Cleared fake client data
- Added go-live checklist for Twilio deployment
- Calendar-agent: Redis publishing, daily briefing endpoint
- Wired calendar into OpenClaw morning briefing
- New operations service: auto-creates Linear issues from
  voice calls, emails, calendar events, cortex proposals
- All services publish to ops:* Redis channels for Linear tracking'
git push origin main
```
