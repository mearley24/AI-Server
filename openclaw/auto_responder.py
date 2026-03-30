"""
Auto Responder — drafts replies to active client emails.

When the email monitor detects an email from an active client, this module:
1. Loads the client profile from client_tracker (preferences, project context)
2. Optionally runs product research if the email mentions products
3. Calls GPT-4o-mini to draft a response following Symphony's email formatting rules
4. Saves the draft to Zoho Mail via email_workflow.draft_email()
5. Notifies Matthew via iMessage that a draft is ready

Bob NEVER sends emails. All drafts require Matthew's review.
"""

import json
import logging
import os
import sys
from typing import Optional

# Ensure openclaw/ is importable (module lives alongside email_workflow, client_tracker)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from openai import OpenAI

logger = logging.getLogger("openclaw.auto_responder")

# ---------------------------------------------------------------------------
# Symphony email formatting system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are drafting an email for Matthew Earley at Symphony Smart Homes.

FORMAT RULES:
1. Lead with decisions/action items at the top, ordered by priority
2. Each decision references a section: "(See Section X for details)"
3. Supporting detail in numbered sections below
4. Keep paragraphs short — nothing buried in dense text
5. Key points easy to scan — use bullet points that breathe
6. One or two topics max per email — don't overwhelm
7. Professional but direct tone — not overly formal
8. Sign off as Matt, with full Symphony signature block

SIGNATURE:
Matt

Matthew Earley
Symphony Smart Homes
(970) 519-3013 | info@symphonysh.com

CONTEXT:
- Symphony Smart Homes is a residential/commercial AV, lighting, network, and automation integrator in Eagle County, Colorado
- Always confirm scope alignment before proceeding
- Never promise something not in the proposal
- Reference specific proposal numbers (Q-196, P-119, etc.) when relevant

OUTPUT:
Return ONLY the email body in plain HTML (no <html>/<head>/<body> wrappers). \
Use <p>, <ul>, <li>, <br> tags for structure. Do not include the subject line.\
"""

# ---------------------------------------------------------------------------
# Product mention detection (triggers research agent)
# ---------------------------------------------------------------------------

PRODUCT_KEYWORDS = [
    "tv", "television", "speaker", "camera", "switch", "dimmer",
    "amp", "amplifier", "display", "mount", "rack", "ups",
    "router", "access point", "projector", "screen", "receiver",
    "soundbar", "subwoofer", "thermostat", "shade", "blind",
    "keypad", "touchscreen", "remote", "matrix", "hdmi",
]


def has_product_mentions(text: str) -> bool:
    """Return True if the text references product categories."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PRODUCT_KEYWORDS)


# ---------------------------------------------------------------------------
# Client profile loader
# ---------------------------------------------------------------------------

def _load_client_profile(sender_email: str, sender_name: str) -> dict:
    """Try to load a client profile from client_tracker by name or email."""
    try:
        from client_tracker import ClientTracker

        db_path = os.environ.get("JOBS_DB_PATH", "/app/data/jobs.db")
        tracker = ClientTracker(db_path=db_path)

        # Try by name first (strip possible email domain from sender_name)
        name = sender_name.strip() if sender_name else ""
        if name:
            profile = tracker.get_client_profile(name)
            if profile.get("email") or profile.get("preferences"):
                return profile
            # Try last name only
            parts = name.split()
            if len(parts) > 1:
                profile = tracker.get_client_profile(parts[-1])
                if profile.get("email") or profile.get("preferences"):
                    return profile

        return {}
    except Exception as e:
        logger.debug("Could not load client profile for %s: %s", sender_email, e)
        return {}


# ---------------------------------------------------------------------------
# Core auto-respond function
# ---------------------------------------------------------------------------

def auto_respond(
    sender_email: str,
    sender_name: str,
    subject: str,
    snippet: str,
    message_id: str,
) -> dict:
    """
    Draft a reply to an active client email.

    Called from monitor.py when an ACTIVE_CLIENT email is detected.
    Returns a dict with the draft result or error info.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping auto-respond")
        return {"status": "skipped", "reason": "no_api_key"}

    # 1. Load client profile
    profile = _load_client_profile(sender_email, sender_name)
    profile_context = ""
    if profile:
        parts = []
        if profile.get("project_type"):
            parts.append(f"Project type: {profile['project_type']}")
        if profile.get("notes"):
            parts.append(f"Notes: {profile['notes']}")
        for pref in profile.get("preferences", [])[:5]:
            parts.append(f"Preference: {pref['content']}")
        for concern in profile.get("concerns", [])[:3]:
            parts.append(f"Concern: {concern['content']}")
        for req in profile.get("requirements", [])[:3]:
            parts.append(f"Requirement: {req['content']}")
        if parts:
            profile_context = "\n\nCLIENT PROFILE:\n" + "\n".join(parts)

    # 2. Optional product research
    research_context = ""
    if has_product_mentions(f"{subject} {snippet}"):
        try:
            from research_agent import research_products

            research = research_products(
                query=f"Product mentions in email from {sender_name}: {subject}. Context: {snippet[:300]}",
                context="Client is asking about products for a smart home project in Eagle County, CO.",
            )
            if research:
                research_context = f"\n\nPRODUCT RESEARCH:\n{research[:1500]}"
        except Exception as e:
            logger.debug("Product research skipped: %s", e)

    # 3. Build prompt and call GPT-4o-mini
    user_prompt = (
        f"Draft a reply to this email.\n\n"
        f"FROM: {sender_name} <{sender_email}>\n"
        f"SUBJECT: {subject}\n"
        f"EMAIL BODY:\n{snippet}\n"
        f"{profile_context}"
        f"{research_context}\n\n"
        f"Draft a professional reply as Matt. "
        f"Address the sender by first name. "
        f"Keep it concise and actionable."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1000,
            temperature=0.4,
        )
        draft_html = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI call failed for auto-respond: %s", e)
        return {"status": "error", "reason": f"openai_error: {e}"}

    # 4. Save draft to Zoho via email_workflow
    reply_subject = subject if subject.lower().startswith("re:") else f"RE: {subject}"

    try:
        from email_workflow import draft_email

        result = draft_email(
            to=sender_email,
            subject=reply_subject,
            body_html=draft_html,
            notify_matthew=False,  # We send our own custom notification below
        )
    except Exception as e:
        logger.error("Failed to create Zoho draft: %s", e)
        return {"status": "error", "reason": f"zoho_draft_error: {e}"}

    # 5. Notify Matthew via iMessage with custom message
    _notify_draft_ready(subject, sender_name)

    logger.info("Auto-respond draft created: RE: %s → %s", subject[:60], sender_email)
    return {
        "status": "draft_created",
        "subject": reply_subject,
        "to": sender_email,
        "draft_id": result.get("draft_id", ""),
        "had_product_research": bool(research_context),
    }


def _notify_draft_ready(subject: str, sender_name: str) -> None:
    """Send iMessage notification that a draft reply is ready."""
    import requests as req

    url = os.environ.get("IMESSAGE_WEBHOOK_URL", "http://localhost:8098/send")
    phone = os.environ.get("OWNER_PHONE_NUMBER", "")
    if not phone:
        logger.warning("OWNER_PHONE_NUMBER not set — skipping notification")
        return

    message = f"Draft ready: RE: {subject}\nFrom: {sender_name}\n\nCheck Zoho drafts to review and send."

    try:
        req.post(url, json={"to": phone, "message": message}, timeout=10)
        logger.info("Notified Matthew about auto-respond draft: %s", subject[:60])
    except Exception as e:
        logger.warning("Failed to send iMessage notification: %s", e)
