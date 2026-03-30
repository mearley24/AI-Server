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
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"

# Module-level token cache
_access_token_cache = {"token": None, "expires_at": 0}


def get_access_token() -> str:
    """Get a valid Zoho access token, refreshing if expired."""
    import time

    now = time.time()
    if _access_token_cache["token"] and now < _access_token_cache["expires_at"] - 60:
        return _access_token_cache["token"]

    refresh_token = os.environ.get("ZOHO_REFRESH_TOKEN", "")
    client_id = os.environ.get("ZOHO_CLIENT_ID", "")
    client_secret = os.environ.get("ZOHO_CLIENT_SECRET", "")

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError("ZOHO_REFRESH_TOKEN, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET must be set")

    resp = requests.post(
        ZOHO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    _access_token_cache["token"] = token
    _access_token_cache["expires_at"] = now + expires_in

    logger.info("Refreshed Zoho access token (expires in %ds)", expires_in)
    return token


def get_zoho_account_id() -> str:
    """Get the primary Zoho Mail account ID (cached in env or fetched)."""
    account_id = os.environ.get("ZOHO_MAIL_ACCOUNT_ID", "")
    if account_id:
        return account_id

    token = get_access_token()
    resp = requests.get(
        ZOHO_ACCOUNTS_URL,
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
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
    try:
        token = access_token or get_access_token()
    except Exception as e:
        logger.error("Failed to get Zoho token: %s", e)
        return {"status": "error", "message": str(e)}

    account_id = get_zoho_account_id()

    # Create draft via Zoho Mail API
    draft_url = f"https://mail.zoho.com/api/accounts/{account_id}/messages"
    payload = {
        "fromAddress": from_address,
        "toAddress": to,
        "ccAddress": cc,
        "subject": subject,
        "content": body_html,
        "mode": "draft",  # CRITICAL: "mode":"draft" saves as draft. Without this, Zoho SENDS the email.
        "mailFormat": "html",
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
    try:
        token = access_token or get_access_token()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    account_id = get_zoho_account_id()

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
