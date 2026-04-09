#!/usr/bin/env python3
"""
docusign_integration.py — DocuSign eSignature integration for Symphony Smart Homes.

Uses JWT Grant (server-to-server) auth via the docusign-esign SDK.
Sends agreements for digital signature and handles webhook events.

Environment variables:
    DOCUSIGN_ACCOUNT_ID       — DocuSign account GUID
    DOCUSIGN_INTEGRATION_KEY  — OAuth2 integration / client key
    DOCUSIGN_USER_ID          — API user ID (impersonation user)
    DOCUSIGN_PRIVATE_KEY      — RSA private key, base64-encoded multiline PEM
    DOCUSIGN_BASE_URL         — API base (default: https://demo.docusign.net/restapi)
    REDIS_URL                 — Redis for event publishing (optional)
    DEV_MODE                  — "true" to return mock data when credentials missing
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("openclaw.docusign")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
DOCUSIGN_ACCOUNT_ID = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
DOCUSIGN_INTEGRATION_KEY = os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
DOCUSIGN_USER_ID = os.getenv("DOCUSIGN_USER_ID", "")
DOCUSIGN_PRIVATE_KEY_B64 = os.getenv("DOCUSIGN_PRIVATE_KEY", "")
DOCUSIGN_BASE_URL = os.getenv(
    "DOCUSIGN_BASE_URL", "https://demo.docusign.net/restapi"
)
REDIS_URL = os.getenv("REDIS_URL", "")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

# JWT token scope required for eSignature REST API
DOCUSIGN_SCOPES = ["signature", "impersonation"]

# OAuth host derived from base URL
# demo → account-d.docusign.com  |  prod → account.docusign.com
def _oauth_host() -> str:
    if "demo.docusign" in DOCUSIGN_BASE_URL:
        return "account-d.docusign.com"
    return "account.docusign.com"


def _decode_private_key() -> Optional[str]:
    """Decode base64-encoded private key from env, or return as-is if already PEM."""
    if not DOCUSIGN_PRIVATE_KEY_B64:
        return None
    val = DOCUSIGN_PRIVATE_KEY_B64.strip()
    # If it's already a PEM block, return directly
    if val.startswith("-----"):
        return val
    # Otherwise decode base64
    try:
        return base64.b64decode(val).decode("utf-8")
    except Exception:
        logger.warning("docusign: failed to decode DOCUSIGN_PRIVATE_KEY as base64")
        return val


def _credentials_present() -> bool:
    return all([
        DOCUSIGN_ACCOUNT_ID,
        DOCUSIGN_INTEGRATION_KEY,
        DOCUSIGN_USER_ID,
        DOCUSIGN_PRIVATE_KEY_B64,
    ])


def _dev_warning(method: str) -> None:
    logger.warning(
        "docusign.%s: credentials missing — returning mock data (DEV_MODE=%s)",
        method, DEV_MODE,
    )


# ---------------------------------------------------------------------------
# DocuSignIntegration class
# ---------------------------------------------------------------------------
class DocuSignIntegration:
    """
    Server-to-server DocuSign eSignature integration using JWT Grant auth.

    All public methods are async; they run blocking SDK calls in a thread pool
    to avoid blocking the FastAPI event loop.
    """

    def __init__(self) -> None:
        if not _credentials_present():
            logger.warning(
                "DocuSignIntegration: one or more credentials are missing. "
                "Set DOCUSIGN_ACCOUNT_ID, DOCUSIGN_INTEGRATION_KEY, "
                "DOCUSIGN_USER_ID, and DOCUSIGN_PRIVATE_KEY in .env"
            )
        self._api_client = None  # lazy-init on first use

    # ------------------------------------------------------------------
    # Internal: SDK client management
    # ------------------------------------------------------------------

    def _get_api_client(self):
        """Build (or return cached) an authenticated DocuSign ApiClient."""
        import docusign_esign as ds

        if self._api_client is not None:
            return self._api_client

        private_key = _decode_private_key()
        if not private_key:
            raise RuntimeError("DOCUSIGN_PRIVATE_KEY is not set or could not be decoded")

        api_client = ds.ApiClient()
        api_client.set_base_path(DOCUSIGN_BASE_URL)
        api_client.set_oauth_host_name(_oauth_host())

        # Request JWT user token (valid 1 hour)
        token_response = api_client.request_jwt_user_token(
            client_id=DOCUSIGN_INTEGRATION_KEY,
            user_id=DOCUSIGN_USER_ID,
            oauth_host_name=_oauth_host(),
            private_key_bytes=private_key.encode("utf-8"),
            expires_in=3600,
            scopes=DOCUSIGN_SCOPES,
        )
        access_token = token_response.access_token
        api_client.set_default_header("Authorization", f"Bearer {access_token}")

        self._api_client = api_client
        logger.info("docusign: JWT token acquired, api_client ready")
        return api_client

    def _make_envelope(
        self,
        pdf_path: str,
        client_name: str,
        client_email: str,
        signer_name: str,
        signer_email: str,
        document_name: str,
        email_subject: str,
        email_body: str,
    ):
        """Build a DocuSign EnvelopeDefinition with two signers and sign-here tabs."""
        import docusign_esign as ds

        # Read PDF bytes
        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        # Document
        document = ds.Document(
            document_base64=pdf_b64,
            name=document_name,
            file_extension="pdf",
            document_id="1",
        )

        # Signer 1 — client
        client_signer = ds.Signer(
            email=client_email,
            name=client_name,
            recipient_id="1",
            routing_order="1",
            tabs=ds.Tabs(
                sign_here_tabs=[
                    ds.SignHere(
                        anchor_string="/sig1/",
                        anchor_units="pixels",
                        anchor_x_offset="0",
                        anchor_y_offset="0",
                    )
                ],
                date_signed_tabs=[
                    ds.DateSigned(
                        anchor_string="/date1/",
                        anchor_units="pixels",
                        anchor_x_offset="0",
                        anchor_y_offset="0",
                    )
                ],
            ),
        )

        # Signer 2 — Symphony side (Matthew Earley)
        symphony_signer = ds.Signer(
            email=signer_email,
            name=signer_name,
            recipient_id="2",
            routing_order="2",
            tabs=ds.Tabs(
                sign_here_tabs=[
                    ds.SignHere(
                        anchor_string="/sig2/",
                        anchor_units="pixels",
                        anchor_x_offset="0",
                        anchor_y_offset="0",
                    )
                ],
                date_signed_tabs=[
                    ds.DateSigned(
                        anchor_string="/date2/",
                        anchor_units="pixels",
                        anchor_x_offset="0",
                        anchor_y_offset="0",
                    )
                ],
            ),
        )

        envelope_definition = ds.EnvelopeDefinition(
            email_subject=email_subject,
            email_blurb=email_body,
            documents=[document],
            recipients=ds.Recipients(signers=[client_signer, symphony_signer]),
            status="sent",  # "sent" creates and sends immediately; "created" = draft
        )
        return envelope_definition

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_for_signature(
        self,
        pdf_path: str,
        client_name: str,
        client_email: str,
        signer_name: str = "Matthew Earley",
        signer_email: str = "info@symphonysh.com",
        document_name: str = "Symphony Smart Homes Agreement",
        email_subject: str = "Please sign: Symphony Smart Homes Agreement",
        email_body: str = (
            "Please review and sign the attached Symphony Smart Homes agreement. "
            "If you have questions, contact us at info@symphonysh.com or (970) 519-3013."
        ),
    ) -> dict:
        """
        Send a PDF agreement for digital signature.

        Returns:
            {
                "envelope_id": str,
                "status": str,          # "sent" | "created"
                "signing_url": str,     # embedded signing URL for client
            }
        """
        if not _credentials_present():
            _dev_warning("send_for_signature")
            return {
                "envelope_id": "mock-envelope-id-dev",
                "status": "sent",
                "signing_url": "https://demo.docusign.net/signing/mock",
            }

        def _sync_send():
            import docusign_esign as ds

            api_client = self._get_api_client()
            envelopes_api = ds.EnvelopesApi(api_client)

            envelope_def = self._make_envelope(
                pdf_path=pdf_path,
                client_name=client_name,
                client_email=client_email,
                signer_name=signer_name,
                signer_email=signer_email,
                document_name=document_name,
                email_subject=email_subject,
                email_body=email_body,
            )

            # Create and send envelope
            summary = envelopes_api.create_envelope(
                account_id=DOCUSIGN_ACCOUNT_ID,
                envelope_definition=envelope_def,
            )
            envelope_id = summary.envelope_id

            # Generate embedded signing URL for client (recipient_id "1")
            view_request = ds.RecipientViewRequest(
                authentication_method="None",
                client_user_id="client-1",
                recipient_id="1",
                return_url="https://www.symphonysh.com/signed",
                user_name=client_name,
                email=client_email,
            )
            # Update envelope recipient with client_user_id so embedded works
            envelopes_api.update_recipients(
                account_id=DOCUSIGN_ACCOUNT_ID,
                envelope_id=envelope_id,
                recipients=ds.Recipients(
                    signers=[
                        ds.Signer(
                            email=client_email,
                            name=client_name,
                            recipient_id="1",
                            routing_order="1",
                            client_user_id="client-1",
                        )
                    ]
                ),
            )
            view_result = envelopes_api.create_recipient_view(
                account_id=DOCUSIGN_ACCOUNT_ID,
                envelope_id=envelope_id,
                recipient_view_request=view_request,
            )

            return {
                "envelope_id": envelope_id,
                "status": summary.status,
                "signing_url": view_result.url,
            }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _sync_send)
        logger.info(
            "docusign: envelope sent envelope_id=%s client=%s",
            result["envelope_id"], client_email,
        )
        return result

    async def get_envelope_status(self, envelope_id: str) -> dict:
        """
        Return current envelope status.

        Returns:
            {
                "status": "completed" | "sent" | "delivered" | "declined" | "voided",
                "completed_at": str,   # ISO 8601 or "" if not yet complete
            }
        """
        if not _credentials_present():
            _dev_warning("get_envelope_status")
            return {"status": "sent", "completed_at": ""}

        def _sync_status():
            import docusign_esign as ds

            api_client = self._get_api_client()
            envelopes_api = ds.EnvelopesApi(api_client)
            envelope = envelopes_api.get_envelope(
                account_id=DOCUSIGN_ACCOUNT_ID,
                envelope_id=envelope_id,
            )
            completed_at = ""
            if envelope.completed_date_time:
                completed_at = str(envelope.completed_date_time)
            return {
                "status": envelope.status or "",
                "completed_at": completed_at,
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_status)

    async def download_signed_document(
        self, envelope_id: str, output_path: str
    ) -> str:
        """
        Download the signed, merged PDF for a completed envelope.

        Returns:
            output_path (str) where the file was saved.
        """
        if not _credentials_present():
            _dev_warning("download_signed_document")
            return output_path

        def _sync_download():
            import docusign_esign as ds

            api_client = self._get_api_client()
            envelopes_api = ds.EnvelopesApi(api_client)
            # "combined" = all documents merged into one PDF
            pdf_bytes = envelopes_api.get_document(
                account_id=DOCUSIGN_ACCOUNT_ID,
                envelope_id=envelope_id,
                document_id="combined",
            )
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as fh:
                fh.write(pdf_bytes)
            return output_path

        loop = asyncio.get_event_loop()
        path = await loop.run_in_executor(None, _sync_download)
        logger.info("docusign: signed document saved to %s", path)
        return path

    async def handle_webhook(self, payload: dict) -> dict:
        """
        Process a DocuSign Connect webhook event payload.

        Publishes ``events:docusign`` to Redis if REDIS_URL is set.

        Returns:
            {
                "event": "envelope_completed" | "envelope_declined" | "envelope_sent" | "unknown",
                "envelope_id": str,
                "client_name": str,
            }
        """
        # DocuSign Connect payload structure (XML-decoded or JSON-decoded)
        envelope_summary = payload.get("envelopeSummary", payload)
        envelope_id = (
            envelope_summary.get("envelopeId")
            or payload.get("envelopeId")
            or ""
        )
        raw_status = (
            envelope_summary.get("status")
            or payload.get("status")
            or ""
        ).lower()

        # Map DocuSign status → our event name
        event_map = {
            "completed": "envelope_completed",
            "declined": "envelope_declined",
            "sent": "envelope_sent",
            "delivered": "envelope_delivered",
            "voided": "envelope_voided",
        }
        event = event_map.get(raw_status, "unknown")

        # Extract client name from first signer recipient if available
        client_name = ""
        try:
            recipients = envelope_summary.get("recipients", {})
            signers = recipients.get("signers", [])
            if signers:
                client_name = signers[0].get("name", "")
        except Exception:
            pass

        result = {
            "event": event,
            "envelope_id": envelope_id,
            "client_name": client_name,
        }

        # Publish to Redis
        if REDIS_URL:
            try:
                from event_bus import publish_and_log
                publish_and_log(
                    redis_url=REDIS_URL,
                    channel="events:docusign",
                    payload=result,
                )
                logger.info("docusign: published %s to Redis", event)
            except Exception as exc:
                logger.warning("docusign: Redis publish failed: %s", exc)

        return result


# ---------------------------------------------------------------------------
# Module-level singleton (imported by webhook_server.py)
# ---------------------------------------------------------------------------
docusign = DocuSignIntegration()
