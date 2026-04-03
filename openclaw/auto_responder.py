"""Auto responder that drafts decision-aware client replies in Zoho."""

import email
import imaplib
import json
import logging
import os
import re
import sys

import redis
from openai import OpenAI

# Ensure openclaw/ is importable (module lives alongside email_workflow, client_tracker)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

logger = logging.getLogger("openclaw.auto_responder")

SYSTEM_PROMPT = """You are drafting an email for Matthew Earley at Symphony Smart Homes.

FORMAT RULES:
1. Lead with decisions/action items at the top, ordered by priority
2. Each decision references a section: "(See Section X for details)"
3. Supporting detail in numbered sections below
4. Keep paragraphs short
5. Keep key points easy to scan
6. One or two topics max
7. Professional but direct tone
8. Sign off as Matt with full signature
9. No version numbers in client-facing content

SIGNATURE:
Matt

Matthew Earley
Symphony Smart Homes
(970) 519-3013 | info@symphonysh.com

OUTPUT:
Return ONLY email body HTML fragments using <p>, <ul>, <li>, <br>. No wrappers.
"""

PRODUCT_KEYWORDS = [
    "tv", "television", "speaker", "camera", "switch", "dimmer",
    "amp", "amplifier", "display", "mount", "rack", "ups",
    "router", "access point", "projector", "screen", "receiver",
    "soundbar", "subwoofer", "thermostat", "shade", "blind",
    "keypad", "touchscreen", "remote", "matrix", "hdmi",
]


def _fetch_full_email(message_id: str) -> tuple[str, list[str]]:
    """Fetch full body and attachment names from IMAP by Message-ID."""
    imap_server = os.environ.get("ZOHO_IMAP_SERVER", "imappro.zoho.com")
    imap_port = int(os.environ.get("ZOHO_IMAP_PORT", "993"))
    email_address = os.environ.get("SYMPHONY_EMAIL", "")
    email_password = os.environ.get("SYMPHONY_EMAIL_PASSWORD", "")
    if not (message_id and email_address and email_password):
        return "", []

    try:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_address, email_password)
        mail.select("INBOX")
        status, found = mail.search(None, f'HEADER Message-ID "{message_id}"')
        if status != "OK" or not found or not found[0]:
            mail.logout()
            return "", []
        msg_num = found[0].split()[-1]
        status, data = mail.fetch(msg_num, "(RFC822)")
        mail.logout()
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return "", []

        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        text_parts: list[str] = []
        attachments: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                disp = (part.get("Content-Disposition") or "").lower()
                filename = part.get_filename()
                if filename:
                    attachments.append(filename)
                if "attachment" in disp:
                    continue
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True) or b""
                    text_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        else:
            payload = msg.get_payload(decode=True) or b""
            text_parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(text_parts).strip(), attachments
    except Exception as exc:
        logger.warning("Failed to fetch full email %s: %s", message_id, exc)
        return "", []


def _resolve_project_key(sender_email: str) -> str:
    """Infer proposal_checker project key from routing config folder mapping."""
    routing_path = os.path.join(_THIS_DIR, "..", "email-monitor", "routing_config.json")
    try:
        with open(routing_path) as f:
            cfg = json.load(f)
        folder = cfg.get("project_routes", {}).get(sender_email.lower(), "")
        folder_lower = str(folder).lower()
        from proposal_checker import CONFIRMED_DECISIONS
        for key, info in CONFIRMED_DECISIONS.items():
            if key in folder_lower:
                return key
            pname = str(info.get("project_name", "")).lower()
            if pname and pname in folder_lower:
                return key
    except Exception:
        pass
    return "topletz"


def _find_decision_matches(message_text: str, project_key: str) -> tuple[list[dict], bool]:
    """Return decision matches and whether request appears net-new."""
    from proposal_checker import CONFIRMED_DECISIONS

    project = CONFIRMED_DECISIONS.get(project_key, {})
    decisions = project.get("decisions", [])
    txt = (message_text or "").lower()
    matches: list[dict] = []
    for dec in decisions:
        item = dec.get("item", "")
        detail = dec.get("decision", "")
        tokens = [t for t in re.findall(r"[a-z0-9]+", f"{item} {detail}".lower()) if len(t) > 3]
        if any(tok in txt for tok in tokens[:10]):
            matches.append(dec)
    return matches[:5], len(matches) == 0


def _link_products_and_skus(html: str) -> str:
    """Hyperlink likely product/SKU references to product pages/search."""
    sku_pattern = re.compile(r"\b([A-Z]{2,6}-[A-Z0-9]{2,}(?:-[A-Z0-9]{1,})*)\b")
    known_terms = ["Control4", "Lutron", "Qolsys", "Araknis", "WattBox", "Luma", "Sonos", "Episode"]

    def _sku_link(match: re.Match) -> str:
        sku = match.group(1)
        url = f"https://www.snapav.com/shop/en/snapav/search/{sku}"
        return f'<a href="{url}">{sku}</a>'

    html = sku_pattern.sub(_sku_link, html)
    for term in known_terms:
        url = f"https://www.google.com/search?q={term}+product"
        html = re.sub(rf"\b({re.escape(term)})\b", rf'<a href="{url}">\1</a>', html, flags=re.IGNORECASE)
    return html


def _strip_version_references(text: str) -> str:
    """Remove version references from client-facing content."""
    text = re.sub(r"\bversion\s+[a-z0-9.\-_]+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bv\d+(?:\.\d+){1,}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text)
    return text


def _notify_draft_ready(subject: str, sender_name: str, sender_email: str) -> None:
    """Send iMessage notification via Redis bridge."""
    msg = f"[DRAFT] Response to {sender_name or sender_email} re: {subject} — review in Zoho"
    payload = {"title": "[DRAFT]", "body": msg}
    try:
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True, socket_timeout=2)
        r.publish("notifications:email", json.dumps(payload))
        logger.info("Published draft notification: %s", msg)
    except Exception as exc:
        logger.warning("Failed to publish draft notification: %s", exc)


def auto_respond(
    sender_email: str,
    sender_name: str,
    subject: str,
    snippet: str,
    message_id: str,
) -> dict:
    """Draft a decision-aware reply to an active client email."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping auto-respond")
        return {"status": "skipped", "reason": "no_api_key"}

    full_email, attachments = _fetch_full_email(message_id)
    full_or_snippet = (full_email or snippet or "").strip()
    project_key = _resolve_project_key(sender_email)
    decision_matches, is_new_request = _find_decision_matches(full_or_snippet, project_key)
    decision_lines = [f"- {d.get('item')}: {d.get('decision')}" for d in decision_matches]

    mode_note = (
        "This appears to be a NEW request not in confirmed decisions. Flag for Matt review."
        if is_new_request
        else "This appears to reference previously confirmed decisions. Respond with those decisions clearly."
    )
    attachment_note = (
        f"Client sent attachments: {', '.join(attachments)}. Explicitly flag for Matt review."
        if attachments
        else "No attachments detected."
    )

    research_context = ""
    if any(kw in full_or_snippet.lower() for kw in PRODUCT_KEYWORDS):
        research_context = "Product-related terms detected; keep response practical and concise."

    user_prompt = (
        f"FROM: {sender_name} <{sender_email}>\n"
        f"SUBJECT: {subject}\n"
        f"EMAIL BODY (FULL):\n{full_or_snippet}\n\n"
        f"PROJECT KEY: {project_key}\n"
        f"DECISION MATCHES:\n{chr(10).join(decision_lines) if decision_lines else '- none'}\n\n"
        f"{mode_note}\n{attachment_note}\n{research_context}\n"
        "Address the sender by first name. Keep it concise and actionable."
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
        draft_html = (response.choices[0].message.content or "").strip()
        draft_html = _strip_version_references(draft_html)
        draft_html = _link_products_and_skus(draft_html)
    except Exception as exc:
        logger.error("OpenAI call failed for auto-respond: %s", exc)
        return {"status": "error", "reason": f"openai_error: {exc}"}

    reply_subject = subject if subject.lower().startswith("re:") else f"RE: {subject}"
    try:
        from email_workflow import draft_email
        result = draft_email(
            to=sender_email,
            subject=reply_subject,
            body_html=draft_html,
            notify_matthew=False,
        )
    except Exception as exc:
        logger.error("Failed to create Zoho draft: %s", exc)
        return {"status": "error", "reason": f"zoho_draft_error: {exc}"}

    _notify_draft_ready(subject=subject, sender_name=sender_name, sender_email=sender_email)
    logger.info("Auto-respond draft created: RE: %s -> %s", subject[:60], sender_email)
    return {
        "status": "draft_created",
        "subject": reply_subject,
        "to": sender_email,
        "draft_id": result.get("draft_id", ""),
        "decision_matches": [d.get("item", "") for d in decision_matches],
        "new_request": is_new_request,
        "attachments": attachments,
    }
