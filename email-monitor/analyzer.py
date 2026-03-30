#!/usr/bin/env python3
"""
analyzer.py — LLM-powered email analysis for Symphony Smart Homes.

Uses GPT-4o-mini to generate summaries, action items, urgency levels,
and suggested replies for incoming emails. Gracefully degrades if
OPENAI_API_KEY is not set.
"""

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an email analyst for Symphony Smart Homes, a smart home / home automation business (Control4, Lutron, Crestron, Sonos, etc.). The owner is busy and needs quick, actionable summaries.

Analyze the email and return JSON with exactly these fields:
- "summary": 1-2 sentence plain English summary of what this email is about
- "action_items": bullet list (as a single string with newlines) of what needs to happen next, or "" if nothing
- "urgency": one of "immediate", "today", "this_week", "fyi"
- "suggested_reply": a short draft reply if one is warranted, or null if not

Rules:
- BID_INVITE emails are at least "today" urgency
- CLIENT_INQUIRY emails are at least "today" urgency
- Keep summaries conversational — the owner will read these on his phone
- Action items should be specific and actionable
- Only suggest a reply if one is clearly needed

Return ONLY valid JSON, no markdown fences."""


def analyze_email(
    sender: str,
    sender_name: str,
    subject: str,
    snippet: str,
    category: str,
) -> dict:
    """
    Analyze an email using GPT-4o-mini.

    Returns dict with keys: summary, action_items, urgency, suggested_reply.
    Falls back to a stub if OPENAI_API_KEY is not set or on error.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping email analysis")
        return {
            "summary": "Analysis unavailable",
            "action_items": "",
            "urgency": "fyi",
            "suggested_reply": None,
        }

    user_prompt = (
        f"From: {sender_name} <{sender}>\n"
        f"Subject: {subject}\n"
        f"Category: {category}\n"
        f"Body preview:\n{snippet[:500]}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
            temperature=0.3,
        )

        content = response.choices[0].message.content.strip()
        # Strip markdown fences if the model wraps them anyway
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)

        # Validate expected keys
        return {
            "summary": result.get("summary", ""),
            "action_items": result.get("action_items", ""),
            "urgency": result.get("urgency", "fyi"),
            "suggested_reply": result.get("suggested_reply"),
        }

    except json.JSONDecodeError as e:
        logger.error("Analyzer JSON parse error: %s — raw: %s", e, content[:200])
        return {
            "summary": "Analysis failed (parse error)",
            "action_items": "",
            "urgency": "fyi",
            "suggested_reply": None,
        }
    except Exception as e:
        logger.error("Analyzer error: %s", e)
        return {
            "summary": "Analysis unavailable",
            "action_items": "",
            "urgency": "fyi",
            "suggested_reply": None,
        }


def extract_client_preferences(
    sender_name: str,
    subject: str,
    snippet: str,
    analysis_summary: str,
) -> list[dict]:
    """Extract client preferences/concerns from an email via GPT-4o-mini.

    Returns a list of {"type": "preference|concern|requirement|style", "content": "..."}.
    Keeps it cheap: 100 token max. Returns [] if no preferences found or on error.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return []

    prompt = (
        f"Extract client preferences, concerns, or requirements from this email.\n\n"
        f"From: {sender_name}\nSubject: {subject}\n"
        f"Summary: {analysis_summary}\nPreview: {snippet[:300]}\n\n"
        f"Return JSON array of objects with 'type' (preference/concern/requirement/style) "
        f"and 'content'. Return [] if none. Max 3 items. Be specific.\n"
        f"Focus on: scheduling, product preferences, budget, communication style, worries."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        prefs = json.loads(content)
        if not isinstance(prefs, list):
            return []
        return [
            {"type": p.get("type", "preference"), "content": p.get("content", "")}
            for p in prefs[:3]
            if p.get("content")
        ]

    except Exception as e:
        logger.debug("Client preference extraction failed: %s", e)
        return []
