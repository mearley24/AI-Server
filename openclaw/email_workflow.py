"""
Symphony Smart Homes — Email Draft Workflow
Bob NEVER sends emails directly. All outbound emails go through this flow:

1. Bob drafts email in Zoho Mail drafts folder
2. Bob notifies Matthew via iMessage: "Email draft ready for review: [subject]"
3. Matthew reviews in Zoho, makes changes or sends
4. If Matthew requests changes via iMessage, Bob updates the draft
5. Only Matthew hits send

This module provides the draft_email() function used by all Bob subsystems
(email_monitor, openclaw, job_lifecycle, etc.)
"""

import os
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

ZOHO_ACCOUNTS_URL = "https://mail.zoho.com/api/accounts"


def get_zoho_account_id(access_token: str) -> str:
    """Get the primary Zoho Mail account ID."""
    resp = requests.get(
        ZOHO_ACCOUNTS_URL,
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["accountId"]


def draft_email(
    to: str,
    subject: str,
    body_html: str,
    cc: str = "",
    from_address: str = "info@symphonysh.com",
    access_token: Optional[str] = None,
    notify_matthew: bool = True,
) -> dict:
    """
    Create a draft email in Zoho Mail. Does NOT send.

    Args:
        to: Recipient email address
        subject: Email subject line
        body_html: HTML body content
        cc: CC recipients (optional)
        from_address: Sender address (default: info@symphonysh.com)
        access_token: Zoho OAuth token (falls back to env)
        notify_matthew: Whether to send iMessage notification (default True)

    Returns:
        dict with draft_id, subject, and status
    """
    token = access_token or os.environ.get("ZOHO_MAIL_ACCESS_TOKEN")
    if not token:
        logger.error("ZOHO_MAIL_ACCESS_TOKEN not set")
        return {"status": "error", "message": "No Zoho token"}

    account_id = get_zoho_account_id(token)

    # Create draft via Zoho Mail API
    draft_url = f"https://mail.zoho.com/api/accounts/{account_id}/messages"
    payload = {
        "fromAddress": from_address,
        "toAddress": to,
        "ccAddress": cc,
        "subject": subject,
        "content": body_html,
        "action": "draft",  # Save as draft, do NOT send
    }

    resp = requests.post(
        draft_url,
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    resp.raise_for_status()
    result = resp.json()

    draft_id = result.get("data", {}).get("messageId", "unknown")
    logger.info(f"Draft created in Zoho: {subject} (ID: {draft_id})")

    # Notify Matthew via iMessage
    if notify_matthew:
        _notify_matthew(subject, to)

    return {
        "status": "draft_created",
        "draft_id": draft_id,
        "subject": subject,
        "to": to,
        "message": f"Draft saved in Zoho. Awaiting Matthew's review.",
    }


def _notify_matthew(subject: str, to: str):
    """Send iMessage to Matthew that a draft is ready for review."""
    try:
        # Use the iMessage bridge on Bob
        imessage_url = os.environ.get("IMESSAGE_WEBHOOK_URL", "http://localhost:8098/send")
        owner_phone = os.environ.get("OWNER_PHONE_NUMBER", "")

        if not owner_phone:
            logger.warning("OWNER_PHONE_NUMBER not set, skipping iMessage notification")
            return

        message = (
            f"Email draft ready for review\n"
            f"To: {to}\n"
            f"Subject: {subject}\n\n"
            f"Open Zoho Mail drafts to review and send."
        )

        requests.post(
            imessage_url,
            json={"to": owner_phone, "message": message},
            timeout=10,
        )
        logger.info(f"Notified Matthew about draft: {subject}")
    except Exception as e:
        logger.warning(f"Failed to notify via iMessage: {e}")


def update_draft(
    draft_id: str,
    body_html: str,
    subject: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Update an existing draft after Matthew requests changes.
    Called when Matthew replies to the iMessage with edits.
    """
    token = access_token or os.environ.get("ZOHO_MAIL_ACCESS_TOKEN")
    if not token:
        return {"status": "error", "message": "No Zoho token"}

    account_id = get_zoho_account_id(token)

    update_url = f"https://mail.zoho.com/api/accounts/{account_id}/messages/{draft_id}"
    payload = {"content": body_html, "action": "draft"}
    if subject:
        payload["subject"] = subject

    resp = requests.put(
        update_url,
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    resp.raise_for_status()

    logger.info(f"Draft updated: {draft_id}")
    _notify_matthew(subject or "(updated draft)", "")

    return {"status": "draft_updated", "draft_id": draft_id}


# Convenience functions for common email types

def draft_proposal_email(client_name: str, client_email: str, proposal_ref: str, total: str) -> dict:
    """Draft a proposal delivery email."""
    subject = f"Symphony Smart Homes — Deliverables Package & Proposal {proposal_ref}"
    body = f"""
    <p>Hi {client_name},</p>
    <p>Please find attached the deliverables package and proposal {proposal_ref}
    (total: {total}) for your review.</p>
    <p>The package includes:</p>
    <ul>
        <li>Rack elevation drawing</li>
        <li>Network topology & VLAN architecture</li>
        <li>Lighting load schedule</li>
        <li>Updated scope summary with change log</li>
    </ul>
    <p>Please review at your convenience and let me know if you have any questions
    or would like to discuss any items.</p>
    <p>Best regards,<br>
    Matthew Earley<br>
    Symphony Smart Homes<br>
    (970) 519-3013 | info@symphonysh.com</p>
    """
    return draft_email(to=client_email, subject=subject, body_html=body)


def draft_followup_email(client_name: str, client_email: str, context: str) -> dict:
    """Draft a follow-up email."""
    subject = f"Symphony Smart Homes — Follow Up"
    body = f"""
    <p>Hi {client_name},</p>
    <p>{context}</p>
    <p>Best regards,<br>
    Matthew Earley<br>
    Symphony Smart Homes<br>
    (970) 519-3013 | info@symphonysh.com</p>
    """
    return draft_email(to=client_email, subject=subject, body_html=body)
