#!/usr/bin/env python3
"""
monitor.py — IMAP email monitoring loop for Symphony Smart Homes.

Connects to Zoho IMAP, polls for new unread emails, categorizes them,
stores metadata in SQLite, and publishes urgent ones to Redis.
"""

import asyncio
import email
import email.header
import email.utils
import imaplib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES = {
    "BID_INVITE": {
        "keywords": [
            "buildingconnected", "bid invitation", "rfp", "rfq",
            "request for proposal", "request for quote", "invitation to bid",
            "bid opportunity", "procore", "planhub",
        ],
        "priority": "high",
    },
    "CLIENT_INQUIRY": {
        "keywords": [
            "consultation", "new client", "inquiry", "interested in",
            "smart home", "home automation", "quote request", "estimate",
            "would like to discuss", "looking for help",
        ],
        "priority": "high",
    },
    "FOLLOW_UP_NEEDED": {
        "keywords": [
            "following up", "just checking", "any update", "circling back",
            "wanted to follow up", "haven't heard", "status update",
        ],
        "priority": "medium",
    },
    "VENDOR": {
        "keywords": [
            "distributor", "supplier", "snap one", "anixter", "wesco",
            "d-tools", "control4", "lutron", "crestron", "sonos",
            "order confirmation", "shipping notification", "tracking",
        ],
        "priority": "low",
    },
    "SCHEDULING": {
        "keywords": [
            "appointment", "meeting", "schedule", "calendar",
            "site visit", "walkthrough", "install date", "reschedule",
        ],
        "priority": "medium",
    },
    "INVOICE": {
        "keywords": [
            "invoice", "payment", "billing", "receipt", "past due",
            "accounts payable", "accounts receivable", "remittance",
        ],
        "priority": "medium",
    },
}

HIGH_PRIORITY_CATEGORIES = {"BID_INVITE", "CLIENT_INQUIRY"}

DB_PATH = os.getenv("EMAIL_DB_PATH", "/data/emails.db")


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize SQLite database with emails table."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            sender TEXT NOT NULL,
            sender_name TEXT DEFAULT '',
            subject TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'GENERAL',
            priority TEXT NOT NULL DEFAULT 'low',
            received_at TEXT NOT NULL,
            stored_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0,
            responded INTEGER NOT NULL DEFAULT 0,
            snippet TEXT DEFAULT '',
            raw_headers TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at)
    """)
    conn.commit()
    conn.close()
    logger.info("Email database initialized at %s", db_path)


def categorize_email(subject: str, sender: str, body_snippet: str = "") -> tuple[str, str]:
    """
    Categorize an email based on keyword matching.

    Returns:
        (category, priority)
    """
    text = f"{subject} {sender} {body_snippet}".lower()

    for category, config in CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in text:
                return category, config["priority"]

    return "GENERAL", "low"


def decode_header_value(value: str) -> str:
    """Decode MIME-encoded email header value."""
    if not value:
        return ""
    decoded_parts = email.header.decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def store_email(
    message_id: str,
    sender: str,
    sender_name: str,
    subject: str,
    category: str,
    priority: str,
    received_at: str,
    snippet: str = "",
    db_path: str = DB_PATH,
) -> bool:
    """
    Store email metadata in SQLite. Returns True if new, False if duplicate.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO emails
               (message_id, sender, sender_name, subject, category, priority,
                received_at, stored_at, snippet)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id, sender, sender_name, subject, category, priority,
                received_at, datetime.now(timezone.utc).isoformat(), snippet,
            ),
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


async def publish_urgent(
    redis_client: aioredis.Redis,
    category: str,
    sender: str,
    subject: str,
) -> None:
    """Publish urgent email notification to Redis channel."""
    import json
    message = json.dumps({
        "category": category,
        "sender": sender,
        "subject": subject,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await redis_client.publish("email:urgent", message)
    logger.info("Published urgent email to Redis: %s from %s", category, sender)


async def publish_new_email(
    redis_client: aioredis.Redis,
    category: str,
    priority: str,
    sender: str,
    subject: str,
) -> None:
    """Publish any new email to Redis email:new channel."""
    import json
    message = json.dumps({
        "category": category,
        "priority": priority,
        "sender": sender,
        "subject": subject,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await redis_client.publish("email:new", message)
    logger.info("Published new email to Redis: [%s/%s] from %s", category, priority, sender)


class EmailMonitor:
    """IMAP email monitoring loop."""

    def __init__(self):
        self.imap_server = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
        self.imap_port = int(os.getenv("ZOHO_IMAP_PORT", "993"))
        self.email_address = os.getenv("SYMPHONY_EMAIL", "")
        self.email_password = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")
        self.poll_interval = int(os.getenv("EMAIL_POLL_INTERVAL", "60"))
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        self._redis: Optional[aioredis.Redis] = None
        self._running = False

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Connect and authenticate to IMAP server."""
        mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
        mail.login(self.email_address, self.email_password)
        return mail

    async def poll_once(self) -> int:
        """
        Poll for new unread emails, categorize and store them.
        Returns count of new emails processed.
        """
        if not self.email_address or not self.email_password:
            logger.warning("IMAP credentials not configured — skipping poll")
            return 0

        new_count = 0
        try:
            mail = await asyncio.to_thread(self._connect_imap)
            mail.select("INBOX")

            _, message_numbers = mail.search(None, "UNSEEN")
            if not message_numbers[0]:
                mail.logout()
                return 0

            msg_nums = message_numbers[0].split()
            logger.info("Found %d unread emails", len(msg_nums))

            redis_client = await self._get_redis()

            for num in msg_nums:
                try:
                    _, msg_data = mail.fetch(num, "(RFC822.HEADER BODY.PEEK[TEXT]<0.500>)")
                    if not msg_data or not msg_data[0]:
                        continue

                    # Parse headers
                    header_data = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                    msg = email.message_from_bytes(header_data)

                    message_id = msg.get("Message-ID", f"unknown-{time.time()}")
                    raw_from = decode_header_value(msg.get("From", ""))
                    subject = decode_header_value(msg.get("Subject", "(no subject)"))
                    date_str = msg.get("Date", "")

                    # Parse sender
                    sender_name, sender_email = email.utils.parseaddr(raw_from)
                    if not sender_name:
                        sender_name = sender_email.split("@")[0] if sender_email else "Unknown"

                    # Parse date
                    received_at = ""
                    if date_str:
                        parsed = email.utils.parsedate_to_datetime(date_str)
                        received_at = parsed.isoformat()
                    if not received_at:
                        received_at = datetime.now(timezone.utc).isoformat()

                    # Get body snippet
                    snippet = ""
                    if len(msg_data) > 1 and isinstance(msg_data[1], tuple):
                        body_bytes = msg_data[1][1]
                        if isinstance(body_bytes, bytes):
                            snippet = body_bytes.decode("utf-8", errors="replace")[:300]

                    # Categorize
                    category, priority = categorize_email(subject, raw_from, snippet)

                    # Store
                    is_new = store_email(
                        message_id=message_id,
                        sender=sender_email,
                        sender_name=sender_name,
                        subject=subject,
                        category=category,
                        priority=priority,
                        received_at=received_at,
                        snippet=snippet,
                    )

                    if is_new:
                        new_count += 1
                        logger.info(
                            "New email: [%s] from %s: %s",
                            category, sender_email, subject[:80],
                        )

                        # Publish high-priority to Redis urgent channel
                        if category in HIGH_PRIORITY_CATEGORIES:
                            await publish_urgent(redis_client, category, sender_name or sender_email, subject)

                        # Publish ALL new emails to email:new channel
                        await publish_new_email(redis_client, category, priority, sender_name or sender_email, subject)

                except Exception as e:
                    logger.error("Error processing email %s: %s", num, e)
                    continue

            mail.logout()

        except imaplib.IMAP4.error as e:
            logger.error("IMAP error: %s", e)
        except Exception as e:
            logger.error("Email poll error: %s", e)

        return new_count

    async def run(self) -> None:
        """Main monitoring loop."""
        self._running = True

        if not self.email_address or not self.email_password:
            logger.warning("Email monitoring disabled — no credentials configured")
        else:
            logger.info(
                "Email monitor starting: %s@%s:%d, poll every %ds",
                self.email_address, self.imap_server, self.imap_port, self.poll_interval,
            )

        init_db()

        while self._running:
            try:
                count = await self.poll_once()
                if count > 0:
                    logger.info("Processed %d new email(s)", count)
            except Exception as e:
                logger.error("Monitor loop error: %s", e)

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
