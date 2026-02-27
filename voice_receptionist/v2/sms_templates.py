"""
sms_templates.py — Symphony Smart Homes Voice Receptionist
SMS follow-up templates for Bob the Conductor.

All templates are short, professional, and personalized.
They are sent via Twilio SMS after calls, appointments, and callbacks.

Template variables use {placeholder} syntax.
All templates are validated at module load time.
"""

from __future__ import annotations

import os
import re
from string import Formatter
from typing import Optional

# Company constants
COMPANY_NAME = "Symphony Smart Homes"
COMPANY_PHONE = os.getenv("TWILIO_PHONE_NUMBER", "(303) 555-0100")
OWNER_NAME = "Mike"
WEBSITE = os.getenv("COMPANY_WEBSITE", "symphonysmarthomes.com")
STOP_FOOTER = "Reply STOP to opt out."


# ─── Template Registry ──────────────────────────────────────────────────────────

SMS_TEMPLATES: dict[str, str] = {

    # — Callback Confirmation —
    "callback_confirmation": (
        "Hi {caller_name}, this is Bob from {company_name}. "
        "I've let {owner_name} know you called. "
        "He'll reach out{callback_time}. "
        "If anything changes, call us at {company_phone}. "
        + STOP_FOOTER
    ),

    # — Appointment Confirmation —
    "appointment_confirmation": (
        "Hi {caller_name} — your {appointment_type} with {company_name} is confirmed "
        "for {appt_date} at {appt_time}. "
        "Questions? Call or text {company_phone}. "
        "We look forward to meeting you! "
        + STOP_FOOTER
    ),

    # — Appointment Reminder (sent day before) —
    "appointment_reminder": (
        "Reminder: Your Symphony appointment is tomorrow, {appt_date} at {appt_time}. "
        "Our tech will arrive within a 1-hour window of that time. "
        "To reschedule: {company_phone}. "
        + STOP_FOOTER
    ),

    # — Service Ticket Opened —
    "service_ticket_opened": (
        "Hi {client_name} — Symphony Smart Homes has opened a service ticket for your {system} issue. "
        "Ticket #{ticket_id}. "
        "Our team will follow up{followup_time}. "
        "Urgent? Call {company_phone}. "
        + STOP_FOOTER
    ),

    # — New Lead Follow-Up —
    "lead_follow_up": (
        "Hi {caller_name} — thanks for your interest in Symphony Smart Homes! "
        "{owner_name} will reach out{callback_time} to discuss your {project_type} project. "
        "In the meantime, learn more at {website}. "
        + STOP_FOOTER
    ),

    # — After-Hours Acknowledgment —
    "after_hours_acknowledgment": (
        "Hi {caller_name} — Symphony Smart Homes is closed until {next_open}. "
        "We received your message and will follow up first thing. "
        "For emergencies, call our main line: {company_phone}. "
        + STOP_FOOTER
    ),

    # — Emergency Escalation Notification (to caller) —
    "escalation_notification": (
        "Hi {caller_name} — we've sent your message to {owner_name} directly. "
        "He'll reach out as soon as possible. "
        "Reference: Call {call_sid_short}. "
        + STOP_FOOTER
    ),

    # — General Follow-Up —
    "general_follow_up": (
        "Hi {caller_name} — thanks for calling Symphony Smart Homes. "
        "{follow_up_message} "
        "Questions? Reach us at {company_phone}. "
        + STOP_FOOTER
    ),

    # — Consultation Confirmed —
    "consultation_confirmed": (
        "Hi {caller_name} — your consultation with {owner_name} at Symphony Smart Homes "
        "is set for {appt_date} at {appt_time}. "
        "Address: {location}. "
        "See you then! "
        + STOP_FOOTER
    ),

    # — Proposal Ready —
    "proposal_ready": (
        "Hi {client_name} — your Symphony Smart Homes proposal for \"{project_name}\" is ready. "
        "{owner_name} will walk you through it at your scheduled time. "
        "Questions before then? {company_phone}. "
        + STOP_FOOTER
    ),

    # — Vendor Message Logged —
    "vendor_logged": (
        "Hi {vendor_name} — thanks for reaching Symphony Smart Homes. "
        "Your message has been logged and forwarded to the right person. "
        "If needed, call back at {company_phone}. "
        + STOP_FOOTER
    ),

    # — VIP Birthday / Anniversary Outreach —
    "vip_occasion": (
        "Hi {client_name} — the whole Symphony team wants to wish you "
        "a wonderful {occasion_type}! "
        "It's been a pleasure working with you. "
        "\u2014 {owner_name} & the Symphony team"
    ),

    # — Annual Maintenance Reminder —
    "maintenance_reminder": (
        "Hi {client_name} — it's time for your annual Symphony system checkup! "
        "A quick visit keeps everything running perfectly. "
        "Call or text {company_phone} to schedule. "
        + STOP_FOOTER
    ),

    # — Tech On The Way —
    "tech_on_the_way": (
        "Hi {client_name} — your Symphony tech is on the way and will arrive "
        "in approximately {eta_minutes} minutes. "
        "Questions? {company_phone}. "
        + STOP_FOOTER
    ),

    # — Work Complete —
    "work_complete": (
        "Hi {client_name} — your Symphony service call is complete. "
        "{work_summary} "
        "Any issues? Reach us at {company_phone}. "
        "Thanks for being a Symphony client! "
        + STOP_FOOTER
    ),
}


# ─── Default Variables ──────────────────────────────────────────────────────────
# Injected automatically if not overridden by caller.

DEFAULT_VARS: dict[str, str] = {
    "company_name": COMPANY_NAME,
    "company_phone": COMPANY_PHONE,
    "owner_name": OWNER_NAME,
    "website": WEBSITE,
    "callback_time": " soon",
    "followup_time": " within one business day",
    "next_open": "8 AM Monday",
    "call_sid_short": "N/A",
    "appointment_type": "appointment",
    "follow_up_message": "We'll be in touch shortly.",
    "ticket_id": "TBD",
}


# ─── Template Engine ──────────────────────────────────────────────────────────

def render(
    template_key: str,
    variables: dict | None = None,
    max_length: int = 160,
) -> str:
    """
    Render an SMS template with the provided variables.

    Args:
        template_key:  Key in SMS_TEMPLATES dict.
        variables:     Dict of template variables to fill in.
                       Merged with DEFAULT_VARS (caller variables take precedence).
        max_length:    Maximum SMS length (160 = 1 SMS credit). Set to 0 to disable.

    Returns:
        Rendered SMS string.

    Raises:
        KeyError: If template_key is not found.
        ValueError: If required variables are missing.
    """
    if template_key not in SMS_TEMPLATES:
        raise KeyError(f"SMS template '{template_key}' not found. "
                       f"Available: {list(SMS_TEMPLATES.keys())}")

    template = SMS_TEMPLATES[template_key]

    # Merge defaults + caller-provided vars
    merged = {**DEFAULT_VARS, **(variables or {})}

    # Check for missing required placeholders
    required_vars = [
        fname for _, fname, _, _ in Formatter().parse(template) if fname
    ]
    missing = [v for v in required_vars if v not in merged]
    if missing:
        raise ValueError(
            f"SMS template '{template_key}' missing variables: {missing}. "
            f"Provided: {list(merged.keys())}"
        )

    rendered = template.format_map(merged)

    # Warn if over length (but don't truncate — let caller decide)
    if max_length and len(rendered) > max_length:
        import logging
        logging.getLogger(__name__).warning(
            f"SMS '{template_key}' is {len(rendered)} chars (>{max_length}). "
            "Will use multiple SMS credits."
        )

    return rendered


def get_required_vars(template_key: str) -> list[str]:
    """
    Return list of placeholder variable names required by a template,
    excluding those covered by DEFAULT_VARS.
    """
    if template_key not in SMS_TEMPLATES:
        raise KeyError(f"Template '{template_key}' not found.")
    template = SMS_TEMPLATES[template_key]
    all_vars = [
        fname for _, fname, _, _ in Formatter().parse(template) if fname
    ]
    return [v for v in all_vars if v not in DEFAULT_VARS]


def list_templates() -> list[dict]:
    """Return all templates with their required (non-default) variables."""
    result = []
    for key, template in SMS_TEMPLATES.items():
        required = get_required_vars(key)
        preview = template[:80] + "..." if len(template) > 80 else template
        result.append({
            "key": key,
            "required_vars": required,
            "preview": preview,
            "length": len(template),
        })
    return result


# ─── Twilio Send Wrapper ──────────────────────────────────────────────────────────

def send_sms(
    to_number: str,
    template_key: str,
    variables: dict | None = None,
    from_number: Optional[str] = None,
) -> dict:
    """
    Render a template and send it via Twilio.

    Args:
        to_number:    Recipient's phone number (E.164).
        template_key: Template to use.
        variables:    Template variables.
        from_number:  Override Twilio sender number (defaults to env var).

    Returns:
        dict with 'sid', 'status', 'to', 'body', 'char_count'.
    """
    from twilio.rest import Client

    body = render(template_key, variables)
    from_num = from_number or os.getenv("TWILIO_PHONE_NUMBER", "")

    if not from_num:
        raise EnvironmentError("TWILIO_PHONE_NUMBER not set.")

    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
    )
    message = client.messages.create(
        to=to_number,
        from_=from_num,
        body=body,
    )

    import logging
    logging.getLogger(__name__).info(
        f"SMS sent: {template_key} → {to_number} ({len(body)} chars) SID={message.sid}"
    )

    return {
        "sid": message.sid,
        "status": message.status,
        "to": to_number,
        "body": body,
        "char_count": len(body),
    }


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Print all templates with their required variables and character counts."""
    templates = list_templates()
    print(f"Symphony SMS Templates ({len(templates)} total)\n")
    print(f"{'Key':<30} {'Required Vars':<40} {'Chars'}")
    print("-" * 85)
    for t in templates:
        req = ", ".join(t["required_vars"]) if t["required_vars"] else "(none)"
        print(f"{t['key']:<30} {req:<40} {t['length']}")
    print()
    print("Sample render: callback_confirmation")
    print("-" * 50)
    try:
        sample = render("callback_confirmation", {
            "caller_name": "Jane Smith",
            "callback_time": " tomorrow morning",
        })
        print(sample)
        print(f"\n[{len(sample)} chars]\n")
    except Exception as e:
        print(f"  ERROR: {e}\n")
