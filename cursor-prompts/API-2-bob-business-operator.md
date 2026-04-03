# API-2: Bob as Business Operator — Wire Email → Orchestrator → Action

## The Problem

Bob's business-operator stack has been partially built but is not connected. `orchestrator/core/bob_orchestrator.py` is a 91-line action runner that knows how to dispatch tasks but has no inbound trigger — nothing calls it when an email arrives. `email-monitor/router.py` routes incoming emails to categories but does not call bob_orchestrator when something actionable lands. `openclaw/auto_responder.py` can draft responses but is not told when to fire. `email-monitor/bid_triage.py` can analyze bid invites but never sends its summaries anywhere. The goal is to wire these existing pieces into a single coherent pipeline: email arrives → router categorizes → bob_orchestrator decides → action executes (draft reply, analyze bid, alert Matt).

## Context Files to Read First

- `orchestrator/core/bob_orchestrator.py` (the 91-line dispatcher — read every line)
- `openclaw/orchestrator.py` (higher-level orchestrator — understand how it relates to bob_orchestrator)
- `openclaw/auto_responder.py` (Zoho draft builder — read its draft method signature)
- `email-monitor/router.py` (categorizes inbound emails — read its output format)
- `email-monitor/bid_triage.py` (bid analysis — read its analyze method)
- `email-monitor/monitor.py` (the polling loop — where new emails are first seen)
- `agents/bob_conductor.yml` (if it exists — Bob's decision configuration)

## Prompt

Read the existing code first — understand the action runner API in bob_orchestrator.py, the routing output format from router.py, and what auto_responder.py and bid_triage.py already know how to do. The job is to wire these together, not rewrite them.

### 1. Understand bob_orchestrator.py

Read the existing 91 lines:

- What actions does it already know how to dispatch? (List them in a comment at the top of the file)
- What is its input format — does it accept an `action_type` string, a dict, a dataclass?
- Does it already have a `dispatch(action)` or `run(task)` method? Use that method name
- If it has a Redis pub/sub listener or an HTTP endpoint stub, wire that up — do not add a second listener

The goal is to make bob_orchestrator the **single decision point** between email events and outbound actions. Every email that requires a response flows through it.

### 2. Wire email-monitor → bob_orchestrator

In `email-monitor/router.py` (or `monitor.py` — wherever categorization happens):

After an email is categorized as actionable, call bob_orchestrator with the categorized result. Do this by importing bob_orchestrator OR by publishing to a Redis channel that bob_orchestrator already listens on — check which pattern the existing code uses.

If bob_orchestrator does not yet listen on Redis, add a listener:

```python
# In bob_orchestrator.py
async def listen_for_emails(self):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("email:actionable")
    async for message in pubsub.listen():
        if message["type"] == "message":
            payload = json.loads(message["data"])
            await self.handle_email_event(payload)
```

In router.py, publish when an actionable email is categorized:

```python
redis_client.publish("email:actionable", json.dumps({
    "email_id": email["id"],
    "from": email["from"],
    "subject": email["subject"],
    "category": category,  # "proposal_request", "bid_invite", "schedule_inquiry", "client_question", etc.
    "body_snippet": email["body"][:500],
    "full_body": email["body"],
}))
```

Use the same Redis connection already used in the email-monitor stack (check the existing `redis_client` setup — do not create a second connection).

### 3. Wire auto_responder.py for Known Patterns

In `bob_orchestrator.py`, add a `handle_email_event(payload)` method:

```python
async def handle_email_event(self, payload: dict):
    category = payload["category"]
    
    if category == "proposal_request":
        await self.draft_proposal_response(payload)
    elif category == "schedule_inquiry":
        await self.draft_schedule_response(payload)
    elif category == "bid_invite":
        await self.triage_bid(payload)
    elif category == "client_question":
        await self.draft_question_response(payload)
    else:
        await self.escalate_to_matt(payload, reason=f"Unknown category: {category}")
```

For `draft_proposal_response` and `draft_schedule_response`:

- Call `auto_responder.draft_response(email_id, template_key, context)` — use the exact method signature already in auto_responder.py
- If auto_responder.py already has template keys, use them. If not, add entries to `agents/bob_conductor.yml` (see step 5)
- The draft goes into Zoho as a draft (not sent) — confirm auto_responder already does this and does not send

### 4. Wire bid_triage.py → iMessage Alert

For `triage_bid`:

- Call `bid_triage.analyze(email_payload)` — use the existing method signature
- Take the returned summary (whatever format bid_triage already produces)
- Send it to Matt via iMessage using the existing iMessage bridge:

```python
# Post to Redis channel that imessage-server.py listens on
redis_client.publish("notifications:imessage", json.dumps({
    "to": "Matt",  # use the phone number/contact already configured
    "message": f"New bid invite: {summary}",
    "priority": "high"
}))
```

Check `scripts/imessage-server.py` for the exact Redis channel and message format it expects — use that exact format.

### 5. Decision Matrix in agents/bob_conductor.yml

Create or update `agents/bob_conductor.yml` with the routing table bob_orchestrator reads:

```yaml
email_actions:
  proposal_request:
    action: draft_response
    template: proposal_acknowledgment
    notify_matt: false
    auto_draft: true

  bid_invite:
    action: triage_bid
    notify_matt: true
    notify_channel: imessage
    auto_draft: false

  schedule_inquiry:
    action: draft_response
    template: schedule_availability
    notify_matt: false
    auto_draft: true

  client_question:
    action: draft_response
    template: general_acknowledgment
    notify_matt: true  # always flag new client questions for Matt
    auto_draft: true

  unknown:
    action: escalate
    notify_matt: true
    notify_channel: imessage

response_templates:
  proposal_acknowledgment: "Thank you for reaching out. Matt will review your project details and follow up within 24 hours."
  schedule_availability: "Thank you for your interest in scheduling time with Matt. I'll check availability and confirm shortly."
  general_acknowledgment: "Thank you for your message. This has been flagged for Matt's review and he'll respond shortly."
```

In bob_orchestrator.py, load this YAML at startup and use it to drive the `handle_email_event` dispatch — do not hardcode category → action mappings in Python.

### 6. End-to-End Test

Add a test script at `tests/test_bob_orchestrator.py`:

```python
# Simulate an inbound email event flowing through the pipeline
test_email = {
    "email_id": "test-001",
    "from": "test@example.com",
    "subject": "Bid Invitation - Hotel AV Project",
    "category": "bid_invite",
    "body_snippet": "We are inviting qualified AV contractors to bid...",
    "full_body": "We are inviting qualified AV contractors to bid on our upcoming hotel renovation project.",
}

# Publish to Redis as router.py would
import redis, json
r = redis.Redis(host="localhost", port=6379)
r.publish("email:actionable", json.dumps(test_email))
print("Published test email event. Check logs for bob_orchestrator response.")
```

Run it and verify in logs:
- bob_orchestrator received the event
- bid_triage.analyze was called
- A Redis publish to `notifications:imessage` was made with the bid summary

If Zoho or iMessage are not available in the test environment, verify the code reaches the point of trying to call them — a connection error is fine, a missing method call is not.
