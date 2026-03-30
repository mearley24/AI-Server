#!/usr/bin/env python3
"""
bid_triage.py — BuildingConnected bid invite triage for Symphony Smart Homes.

Parses BuildingConnected bid invite emails, evaluates fit against Symphony's
trade capabilities and service territory, and notifies Matthew via iMessage
with a BID/PASS/REVIEW recommendation.
"""

import json
import logging
import os
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "bid_config.json"

def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load bid config: %s", e)
        return {"symphony_trades": [], "symphony_territory": [], "pass_trades": []}

_config = _load_config()

SYMPHONY_TRADES = [t.lower() for t in _config.get("symphony_trades", [])]
SYMPHONY_TERRITORY = [t.lower() for t in _config.get("symphony_territory", [])]
PASS_TRADES = [t.lower() for t in _config.get("pass_trades", [])]

# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

def parse_bc_email(sender: str, subject: str, body: str) -> dict:
    """
    Parse a BuildingConnected bid invite email and extract project details.

    Returns a dict with keys:
        project_name, gc_name, company, location, bid_due, scope, rfp_link,
        bidding_link, not_bidding_link
    """
    details = {
        "project_name": "",
        "gc_name": "",
        "company": "",
        "location": "",
        "bid_due": "",
        "scope": "",
        "rfp_link": "",
        "bidding_link": "",
        "not_bidding_link": "",
    }

    text = f"{subject}\n{body}"

    # --- GC name and company ---
    # Pattern: "{Name} from {Company} has invited you to bid on"
    invite_match = re.search(
        r"([A-Z][a-zA-Z\s.'-]+?)\s+from\s+(.+?)\s+has\s+invited\s+you\s+to\s+bid\s+on",
        text,
    )
    if invite_match:
        details["gc_name"] = invite_match.group(1).strip()
        details["company"] = invite_match.group(2).strip()

    # --- Project name ---
    # Text after "bid on" up to a line break, period, or separator
    project_match = re.search(
        r"has\s+invited\s+you\s+to\s+bid\s+on\s+(.+?)(?:\s*[\n\r.|])",
        text,
    )
    if project_match:
        details["project_name"] = project_match.group(1).strip().rstrip(".")
    elif subject:
        # Fallback: use subject line, stripping common prefixes
        clean = re.sub(r"^(Re:|Fwd?:|Bid\s+Invitation\s*[-:]?\s*)", "", subject, flags=re.IGNORECASE).strip()
        details["project_name"] = clean

    # --- Location ---
    loc_match = re.search(r"Location\s*:\s*(.+)", text, re.IGNORECASE)
    if loc_match:
        details["location"] = loc_match.group(1).strip().split("\n")[0].strip()

    # --- Bid due date ---
    due_match = re.search(r"Bid\s+Due\s*:\s*(.+)", text, re.IGNORECASE)
    if due_match:
        details["bid_due"] = due_match.group(1).strip().split("\n")[0].strip()

    # --- RFP link ---
    rfp_match = re.search(r"(https?://app\.buildingconnected\.com/(?:goto|rfps)/[^\s\"<>]+)", text)
    if rfp_match:
        details["rfp_link"] = rfp_match.group(1)

    # --- Bidding / Not Bidding links ---
    bidding_match = re.search(r"(https?://[^\s\"<>]+\?state=BIDDING[^\s\"<>]*)", text)
    if bidding_match:
        details["bidding_link"] = bidding_match.group(1)

    not_bidding_match = re.search(r"(https?://[^\s\"<>]+\?state=NOT_BIDDING[^\s\"<>]*)", text)
    if not_bidding_match:
        details["not_bidding_link"] = not_bidding_match.group(1)

    # --- Scope / trades ---
    # Pull from subject line and body keywords
    scope_keywords = _extract_scope(subject, body)
    details["scope"] = ", ".join(scope_keywords) if scope_keywords else "Not specified"

    return details


def _extract_scope(subject: str, body: str) -> list[str]:
    """Extract trade/scope keywords from subject and body text."""
    text = f"{subject} {body}".lower()
    found = []
    seen = set()

    # Check against known Symphony trades
    for trade in SYMPHONY_TRADES:
        if trade in text and trade not in seen:
            found.append(trade)
            seen.add(trade)

    # Check against known pass trades
    for trade in PASS_TRADES:
        if trade in text and trade not in seen:
            found.append(trade)
            seen.add(trade)

    return found


# ---------------------------------------------------------------------------
# Fit evaluation
# ---------------------------------------------------------------------------

def evaluate_fit(details: dict) -> tuple[str, str]:
    """
    Evaluate whether a bid invite is a fit for Symphony Smart Homes.

    Returns:
        (recommendation, reason) where recommendation is BID, PASS, or REVIEW.
    """
    scope_text = details.get("scope", "").lower()
    location_text = details.get("location", "").lower()

    # Check territory match
    in_territory = False
    matched_territory = ""
    for place in SYMPHONY_TERRITORY:
        if place in location_text:
            in_territory = True
            matched_territory = place
            break

    # Check scope match
    has_symphony_trade = False
    has_pass_trade = False
    matched_trades = []
    pass_trades_found = []

    for trade in SYMPHONY_TRADES:
        if trade in scope_text:
            has_symphony_trade = True
            matched_trades.append(trade)

    for trade in PASS_TRADES:
        if trade in scope_text:
            has_pass_trade = True
            pass_trades_found.append(trade)

    # No scope extracted — needs manual review
    if scope_text in ("not specified", ""):
        if in_territory:
            return "REVIEW", f"In territory ({matched_territory}) but scope unclear — check RFP"
        return "REVIEW", "Scope and location unclear — check RFP"

    # Pure pass trades, nothing Symphony does
    if has_pass_trade and not has_symphony_trade:
        trades_str = ", ".join(pass_trades_found[:3])
        return "PASS", f"Scope is {trades_str} — not Symphony trades"

    # Symphony trades found
    if has_symphony_trade:
        trades_str = ", ".join(matched_trades[:3])
        if in_territory:
            return "BID", f"{trades_str} in {matched_territory}"
        elif location_text:
            return "REVIEW", f"Scope matches ({trades_str}) but location ({details['location']}) may be outside territory"
        else:
            return "REVIEW", f"Scope matches ({trades_str}) but location unknown"

    # Has trades but none match Symphony or pass lists
    if in_territory:
        return "REVIEW", f"In territory ({matched_territory}) but scope doesn't clearly match — check RFP"

    return "REVIEW", "Could not determine fit — check RFP manually"


# ---------------------------------------------------------------------------
# iMessage notification
# ---------------------------------------------------------------------------

def notify_matthew(message: str) -> None:
    """Send an iMessage notification via the bridge webhook."""
    url = os.getenv("IMESSAGE_WEBHOOK_URL", "http://localhost:8098/send")
    phone = os.getenv("OWNER_PHONE_NUMBER", "")
    if not phone:
        logger.warning("OWNER_PHONE_NUMBER not set — skipping iMessage notification")
        return
    try:
        resp = requests.post(url, json={"to": phone, "message": message}, timeout=10)
        resp.raise_for_status()
        logger.info("Bid triage notification sent to Matthew")
    except Exception as e:
        logger.error("Failed to send bid triage iMessage: %s", e)


def format_notification(details: dict, recommendation: str, reason: str) -> str:
    """Format the bid triage notification message."""
    lines = [
        f"New Bid Invite: {details['project_name']}",
        f"GC: {details['gc_name']} ({details['company']})" if details["gc_name"] else f"GC: {details['company'] or 'Unknown'}",
        f"Location: {details['location'] or 'Not specified'}",
        f"Scope: {details['scope']}",
        f"Due: {details['bid_due'] or 'Not specified'}",
        f"Recommendation: {recommendation}",
        f"Reason: {reason}",
    ]

    if details["rfp_link"]:
        lines.append(f"\nView RFP: {details['rfp_link']}")

    lines.append("Reply BID or PASS")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def triage_bid_email(sender: str, subject: str, body: str) -> dict:
    """
    Full triage pipeline for a BuildingConnected bid invite email.

    1. Parse the email to extract project details
    2. Evaluate fit against Symphony's profile
    3. Notify Matthew via iMessage

    Returns the triage result dict.
    """
    logger.info("Triaging bid invite: %s", subject[:80])

    # Parse
    details = parse_bc_email(sender, subject, body)
    logger.info(
        "Parsed bid: project=%s, gc=%s, location=%s, scope=%s",
        details["project_name"][:50],
        details["gc_name"],
        details["location"][:50] if details["location"] else "?",
        details["scope"][:50],
    )

    # Evaluate
    recommendation, reason = evaluate_fit(details)
    logger.info("Bid recommendation: %s — %s", recommendation, reason)

    # Notify
    message = format_notification(details, recommendation, reason)
    notify_matthew(message)

    return {
        **details,
        "recommendation": recommendation,
        "reason": reason,
    }
