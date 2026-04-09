#!/usr/bin/env python3
"""
stripe_billing.py — Stripe payment integration for Symphony Smart Homes.

Supports ACH bank transfer (preferred) and card payments via Payment Links
and Stripe Invoices. Webhook validation and Redis event publishing included.

Environment variables:
    STRIPE_SECRET_KEY       — sk_live_... or sk_test_...
    STRIPE_WEBHOOK_SECRET   — whsec_... for webhook signature validation
    STRIPE_PUBLISHABLE_KEY  — pk_live_... (used for frontend/metadata only)
    REDIS_URL               — Redis URL for event publishing (optional)
    DEV_MODE                — "true" to return mock data when credentials missing
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("openclaw.stripe_billing")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

# Symphony Smart Homes defaults
COMPANY_NAME = "Symphony Smart Homes"
COMPANY_EMAIL = "info@symphonysh.com"
COMPANY_PHONE = "(970) 519-3013"
COMPANY_ADDRESS = "45 Aspen Glen Ct, Edwards, CO 81632"


def _credentials_present() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _dev_warning(method: str) -> None:
    logger.warning(
        "stripe_billing.%s: STRIPE_SECRET_KEY missing — returning mock data",
        method,
    )


def _get_stripe():
    """Return the stripe module configured with the secret key."""
    import stripe as _stripe

    _stripe.api_key = STRIPE_SECRET_KEY
    return _stripe


# ---------------------------------------------------------------------------
# StripeBilling class
# ---------------------------------------------------------------------------
class StripeBilling:
    """
    Async-friendly Stripe integration for deposit collection and invoicing.

    ACH bank transfer (us_bank_account) is listed first as the preferred method;
    card is accepted as a fallback per Symphony's billing practices.
    """

    def __init__(self) -> None:
        if not _credentials_present():
            logger.warning(
                "StripeBilling: STRIPE_SECRET_KEY not set. "
                "Payments will not function until the key is provided."
            )

    # ------------------------------------------------------------------
    # Customer helpers
    # ------------------------------------------------------------------

    def _find_or_create_customer(self, stripe, client_name: str, client_email: str) -> str:
        """Return existing Stripe customer ID or create a new one."""
        existing = stripe.Customer.search(query=f'email:"{client_email}"', limit=1)
        if existing.data:
            cust_id = existing.data[0].id
            logger.debug("stripe: found existing customer %s for %s", cust_id, client_email)
            return cust_id

        customer = stripe.Customer.create(
            name=client_name,
            email=client_email,
            metadata={"source": "symphony_smart_homes"},
        )
        logger.info("stripe: created customer %s (%s)", customer.id, client_email)
        return customer.id

    # ------------------------------------------------------------------
    # Payment Link
    # ------------------------------------------------------------------

    async def create_payment_link(
        self,
        amount_cents: int,
        description: str,
        client_name: str,
        client_email: str,
        metadata: Optional[dict] = None,
        payment_methods: Optional[list] = None,
    ) -> dict:
        """
        Create a Stripe Payment Link for deposit collection.

        Args:
            amount_cents:    Amount in cents (e.g. 3854956 = $38,549.56)
            description:     Line-item description shown on checkout
            client_name:     Client's full name
            client_email:    Client's email for receipt
            metadata:        Extra key-value metadata (e.g. job_id, phase)
            payment_methods: List of payment method types; defaults to ACH + card

        Returns:
            {
                "payment_link_url": str,
                "payment_intent_id": str,   # "" if not yet attached
                "price_id": str,
            }
        """
        if payment_methods is None:
            payment_methods = ["us_bank_account", "card"]

        if not _credentials_present():
            _dev_warning("create_payment_link")
            return {
                "payment_link_url": "https://buy.stripe.com/mock_test_link",
                "payment_intent_id": "",
                "price_id": "price_mock",
            }

        import asyncio

        def _sync():
            stripe = _get_stripe()

            # Create a one-time price for this specific job
            price = stripe.Price.create(
                unit_amount=amount_cents,
                currency="usd",
                product_data={
                    "name": description,
                    "metadata": {"company": COMPANY_NAME},
                },
            )

            # Build payment link
            link_params: dict = {
                "line_items": [{"price": price.id, "quantity": 1}],
                "payment_method_types": payment_methods,
                "metadata": metadata or {},
                "after_completion": {
                    "type": "redirect",
                    "redirect": {"url": "https://www.symphonysh.com/payment-confirmed"},
                },
                "custom_text": {
                    "submit": {
                        "message": (
                            f"Payment to {COMPANY_NAME} — "
                            f"{COMPANY_PHONE} | {COMPANY_ADDRESS}"
                        )
                    }
                },
            }

            # Pre-fill customer email if supported
            link_params["customer_creation"] = "always"

            payment_link = stripe.PaymentLink.create(**link_params)

            logger.info(
                "stripe: payment link created url=%s amount_cents=%d client=%s",
                payment_link.url, amount_cents, client_email,
            )
            return {
                "payment_link_url": payment_link.url,
                "payment_intent_id": "",  # created when customer pays
                "price_id": price.id,
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------

    async def create_invoice(
        self,
        client_name: str,
        client_email: str,
        line_items: list[dict],
        due_days: int = 14,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Create and finalize a Stripe Invoice with line items.

        Args:
            client_name:  Client's full name
            client_email: Client's email
            line_items:   [{"description": str, "amount_cents": int}, ...]
            due_days:     Days until invoice is due (default 14)
            metadata:     Extra key-value metadata

        Returns:
            {
                "invoice_id": str,
                "invoice_url": str,          # PDF download URL
                "hosted_invoice_url": str,   # Hosted payment page
            }
        """
        if not _credentials_present():
            _dev_warning("create_invoice")
            return {
                "invoice_id": "in_mock",
                "invoice_url": "https://invoice.stripe.com/mock.pdf",
                "hosted_invoice_url": "https://invoice.stripe.com/mock",
            }

        import asyncio

        def _sync():
            stripe = _get_stripe()
            meta = metadata or {}

            # Find/create customer
            customer_id = self._find_or_create_customer(stripe, client_name, client_email)

            # Add invoice items
            for item in line_items:
                stripe.InvoiceItem.create(
                    customer=customer_id,
                    amount=item["amount_cents"],
                    currency="usd",
                    description=item["description"],
                    metadata=meta,
                )

            # Create and finalize invoice
            invoice = stripe.Invoice.create(
                customer=customer_id,
                collection_method="send_invoice",
                days_until_due=due_days,
                metadata=meta,
                custom_fields=[
                    {"name": "Project", "value": meta.get("project_name", "Symphony Smart Homes")},
                    {"name": "Quote Ref", "value": meta.get("quote_ref", "")},
                ],
                footer=(
                    f"{COMPANY_NAME} | {COMPANY_ADDRESS} | "
                    f"{COMPANY_PHONE} | {COMPANY_EMAIL}"
                ),
                payment_settings={
                    "payment_method_types": ["us_bank_account", "card"],
                },
            )

            finalized = stripe.Invoice.finalize_invoice(invoice.id)
            # Send to customer
            stripe.Invoice.send_invoice(finalized.id)

            logger.info(
                "stripe: invoice created id=%s client=%s items=%d",
                finalized.id, client_email, len(line_items),
            )
            return {
                "invoice_id": finalized.id,
                "invoice_url": finalized.invoice_pdf or "",
                "hosted_invoice_url": finalized.hosted_invoice_url or "",
            }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync)

    # ------------------------------------------------------------------
    # Webhook handler
    # ------------------------------------------------------------------

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """
        Validate and process a Stripe webhook event.

        On ``payment_intent.succeeded``, publishes ``events:stripe_payment`` to Redis.

        Args:
            payload:    Raw request body bytes
            signature:  Value of the ``Stripe-Signature`` header

        Returns:
            {
                "event": "payment_succeeded" | "payment_failed" |
                         "invoice_paid" | "checkout_completed" | "unhandled",
                "amount": int,       # cents
                "metadata": dict,
                "stripe_event_id": str,
            }
        """
        if not _credentials_present():
            _dev_warning("handle_webhook")
            return {
                "event": "unhandled",
                "amount": 0,
                "metadata": {},
                "stripe_event_id": "",
            }

        import asyncio

        def _sync():
            stripe = _get_stripe()

            # Validate signature
            try:
                event = stripe.Webhook.construct_event(
                    payload=payload,
                    sig_header=signature,
                    secret=STRIPE_WEBHOOK_SECRET,
                )
            except stripe.error.SignatureVerificationError as exc:
                logger.error("stripe: webhook signature verification failed: %s", exc)
                raise ValueError("Invalid Stripe webhook signature") from exc

            event_type = event["type"]
            event_id = event["id"]
            data_obj = event["data"]["object"]

            # Map event types
            result: dict = {
                "stripe_event_id": event_id,
                "amount": 0,
                "metadata": {},
                "event": "unhandled",
            }

            if event_type == "payment_intent.succeeded":
                result["event"] = "payment_succeeded"
                result["amount"] = data_obj.get("amount_received", 0)
                result["metadata"] = dict(data_obj.get("metadata", {}))

            elif event_type == "payment_intent.payment_failed":
                result["event"] = "payment_failed"
                result["amount"] = data_obj.get("amount", 0)
                result["metadata"] = dict(data_obj.get("metadata", {}))

            elif event_type == "invoice.paid":
                result["event"] = "invoice_paid"
                result["amount"] = data_obj.get("amount_paid", 0)
                result["metadata"] = dict(data_obj.get("metadata", {}))

            elif event_type == "checkout.session.completed":
                result["event"] = "checkout_completed"
                result["amount"] = data_obj.get("amount_total", 0)
                result["metadata"] = dict(data_obj.get("metadata", {}))

            else:
                logger.debug("stripe: unhandled event type=%s id=%s", event_type, event_id)

            return result

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _sync)

        # Publish to Redis for succeeded payments
        if result["event"] in ("payment_succeeded", "invoice_paid", "checkout_completed"):
            if REDIS_URL:
                try:
                    from event_bus import publish_and_log
                    publish_and_log(
                        redis_url=REDIS_URL,
                        channel="events:stripe_payment",
                        payload=result,
                    )
                    logger.info(
                        "stripe: published %s to Redis amount=%d",
                        result["event"], result["amount"],
                    )
                except Exception as exc:
                    logger.warning("stripe: Redis publish failed: %s", exc)

        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
stripe_billing = StripeBilling()
