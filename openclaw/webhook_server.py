#!/usr/bin/env python3
"""
webhook_server.py — FastAPI webhook routes for DocuSign and Stripe.

Registers two endpoints on the shared OpenClaw FastAPI app (imported from main.py):
    POST /webhook/docusign  — DocuSign Connect webhook receiver
    POST /webhook/stripe    — Stripe webhook receiver

Both endpoints:
  1. Validate the incoming request
  2. Delegate to the appropriate integration module
  3. Publish events to Redis via event_bus
  4. Return HTTP 200 immediately (required by both DocuSign and Stripe)

Mount via: app.include_router(webhook_router) in main.py
"""

from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("openclaw.webhook_server")

REDIS_URL = os.getenv("REDIS_URL", "")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
webhook_router = APIRouter(prefix="/webhook", tags=["webhooks"])

# ---------------------------------------------------------------------------
# DocuSign Connect webhook
# ---------------------------------------------------------------------------


def _parse_docusign_xml(xml_body: bytes) -> dict:
    """
    Parse DocuSign Connect XML payload (legacy format) into a dict
    compatible with DocuSignIntegration.handle_webhook().
    """
    try:
        root = ET.fromstring(xml_body)
        ns = {"ds": "http://www.docusign.net/API/3.0"}

        def _find(element, tag: str) -> str:
            found = element.find(tag, ns)
            if found is None:
                # Try without namespace
                found = element.find(tag)
            return found.text.strip() if found is not None and found.text else ""

        envelope_id = _find(root, ".//ds:EnvelopeID") or _find(root, ".//EnvelopeID")
        status = _find(root, ".//ds:Status") or _find(root, ".//Status")

        # Extract signers
        signers = []
        for signer_el in root.findall(".//ds:Signer", ns) or root.findall(".//Signer"):
            signers.append({
                "name": _find(signer_el, "ds:UserName") or _find(signer_el, "UserName"),
                "email": _find(signer_el, "ds:Email") or _find(signer_el, "Email"),
                "status": _find(signer_el, "ds:Status") or _find(signer_el, "Status"),
            })

        return {
            "envelopeId": envelope_id,
            "status": status,
            "recipients": {"signers": signers},
        }
    except ET.ParseError:
        logger.warning("webhook/docusign: failed to parse XML body, trying as JSON")
        return {}


@webhook_router.post("/docusign", summary="DocuSign Connect webhook receiver")
async def docusign_webhook(request: Request) -> Response:
    """
    Receives DocuSign Connect webhook events.

    DocuSign sends either:
      - JSON (modern Connect): Content-Type application/json
      - XML  (legacy Connect): Content-Type text/xml or application/xml

    On success: publishes ``events:docusign`` to Redis and returns 200.
    Always returns 200 to prevent DocuSign retries for non-delivery errors.
    """
    from docusign_integration import docusign

    body = await request.body()
    content_type = request.headers.get("content-type", "").lower()

    # Parse payload
    payload: dict = {}
    if "xml" in content_type:
        payload = _parse_docusign_xml(body)
        if not payload:
            # Fallback: try JSON decode
            try:
                payload = json.loads(body)
            except Exception:
                pass
    else:
        try:
            payload = json.loads(body)
        except Exception:
            logger.warning("webhook/docusign: could not parse body (len=%d)", len(body))

    if not payload:
        logger.warning("webhook/docusign: empty or unparseable payload, returning 200 anyway")
        return Response(content="OK", status_code=200)

    try:
        result = await docusign.handle_webhook(payload)
        logger.info(
            "webhook/docusign: event=%s envelope_id=%s client=%s",
            result.get("event"),
            result.get("envelope_id"),
            result.get("client_name"),
        )
    except Exception as exc:
        logger.error("webhook/docusign: handle_webhook raised: %s", exc, exc_info=True)
        # Still return 200 — log the error but don't ask DocuSign to retry
        return Response(content="OK (error logged)", status_code=200)

    return Response(content="OK", status_code=200)


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------


@webhook_router.post("/stripe", summary="Stripe payment webhook receiver")
async def stripe_webhook(request: Request) -> Response:
    """
    Receives Stripe webhook events and validates the Stripe-Signature header.

    On ``payment_intent.succeeded``, ``invoice.paid``, or
    ``checkout.session.completed``: publishes ``events:stripe_payment`` to Redis.

    Always returns 200 to prevent Stripe retries.
    """
    from stripe_billing import stripe_billing

    body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not signature:
        logger.warning("webhook/stripe: missing Stripe-Signature header")
        # Return 400 so Stripe knows the request was malformed (not a delivery failure)
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        result = await stripe_billing.handle_webhook(payload=body, signature=signature)
        logger.info(
            "webhook/stripe: event=%s amount=%d metadata=%s",
            result.get("event"),
            result.get("amount", 0),
            result.get("metadata"),
        )
    except ValueError as exc:
        # Signature verification failed — reject clearly
        logger.error("webhook/stripe: signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    except Exception as exc:
        logger.error("webhook/stripe: handle_webhook raised: %s", exc, exc_info=True)
        # Return 200 to avoid Stripe retrying a legitimate delivery failure
        return Response(content="OK (error logged)", status_code=200)

    return Response(content="OK", status_code=200)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@webhook_router.get("/health", include_in_schema=False)
async def webhook_health() -> JSONResponse:
    """Quick liveness probe for the webhook sub-router."""
    return JSONResponse({"status": "ok", "routes": ["/webhook/docusign", "/webhook/stripe"]})


# ---------------------------------------------------------------------------
# Standalone app (for running webhook_server independently or in tests)
# ---------------------------------------------------------------------------


def create_app():
    """
    Create a minimal FastAPI app that mounts only the webhook router.
    Use this when running webhook_server standalone:

        uvicorn webhook_server:app --port 8001
    """
    from fastapi import FastAPI

    _app = FastAPI(
        title="OpenClaw Webhook Server",
        description="DocuSign + Stripe webhook receivers — Symphony Smart Homes",
        version="1.0.0",
    )
    _app.include_router(webhook_router)
    return _app


app = create_app()

# ---------------------------------------------------------------------------
# How to mount into the main OpenClaw app (add to main.py):
#
#   from webhook_server import webhook_router
#   app.include_router(webhook_router)
# ---------------------------------------------------------------------------
