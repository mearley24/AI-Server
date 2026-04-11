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
        logger.info("linear_issue_created identifier=%s title=%s", issue["identifier"], title)
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
            logger.error("linear_ops_error channel=%s error=%s", str(msg.get("channel")), str(e))


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
