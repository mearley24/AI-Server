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
from email.utils import parseaddr
import hashlib
import imaplib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
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
    "MARKETING": {
        "keywords": [
            "unsubscribe", "view in browser", "email preferences",
            "newsletter", "weekly digest", "monthly update",
            "recommended for you", "new properties", "now live on",
            "introducing", "announcing", "flash sale", "promo code",
            "manage subscriptions", "opt out", "update preferences",
            "you might like", "just launched", "limited time",
        ],
        "priority": "none",
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

HIGH_PRIORITY_CATEGORIES = {"BID_INVITE", "CLIENT_INQUIRY", "ACTIVE_CLIENT"}

# Active client senders loaded from routing_config.json (project_routes + active_clients)
_ACTIVE_CLIENT_EMAILS: set[str] = set()

_ROUTING_CONFIG_CACHE: dict | None = None
_ROUTING_CONFIG_MTIME: float = 0.0
_ROUTING_CONFIG_LOADED_AT: float = 0.0
_ROUTING_CONFIG_TTL_SEC = 300.0


def _routing_config_path() -> str:
    return os.path.join(os.path.dirname(__file__), "routing_config.json")


def _get_routing_config() -> dict:
    """Load routing_config.json with mtime-based cache (~5 min TTL)."""
    global _ROUTING_CONFIG_CACHE, _ROUTING_CONFIG_MTIME, _ROUTING_CONFIG_LOADED_AT
    path = _routing_config_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    now = time.time()
    if (
        _ROUTING_CONFIG_CACHE is not None
        and (now - _ROUTING_CONFIG_LOADED_AT) < _ROUTING_CONFIG_TTL_SEC
        and mtime <= _ROUTING_CONFIG_MTIME
    ):
        return _ROUTING_CONFIG_CACHE
    try:
        with open(path, encoding="utf-8") as f:
            _ROUTING_CONFIG_CACHE = json.load(f)
        _ROUTING_CONFIG_MTIME = mtime if mtime else now
        _ROUTING_CONFIG_LOADED_AT = now
    except Exception as e:
        logger.warning("Could not load routing_config: %s", e)
        if _ROUTING_CONFIG_CACHE is None:
            _ROUTING_CONFIG_CACHE = {}
    return _ROUTING_CONFIG_CACHE or {}


def _sender_email_addr(sender: str) -> str:
    _, addr = parseaddr(sender)
    a = (addr or sender or "").strip().lower()
    return a


def _route_label_to_category(route: str) -> tuple[str, str]:
    """Map IMAP folder / route label from routing_config to (category, priority)."""
    r = (route or "").strip()
    if not r:
        return "GENERAL", "low"
    if r.startswith("Marketing") or r == "Marketing-Ignore":
        return "MARKETING", "none"
    if r == "Marketing":
        return "MARKETING", "none"
    if r.startswith("Vendor"):
        return "VENDOR", "low"
    if r.startswith("Bids"):
        return "BID_INVITE", "high"
    if r in ("Notes",) or r.startswith("Personal/") or r.startswith("Banking"):
        return "MARKETING", "none"
    if r.startswith("Projects/"):
        return "ACTIVE_CLIENT", "high"
    if r == "_project_match":
        return "GENERAL", "low"
    if r.startswith("Industry/"):
        return "GENERAL", "low"
    return "GENERAL", "low"


def _lookup_route_for_sender(sender_raw: str) -> str | None:
    cfg = _get_routing_config()
    email_addr = _sender_email_addr(sender_raw)
    if not email_addr:
        return None
    cat_routes = cfg.get("category_routes") or {}
    for key, route in cat_routes.items():
        if key.lower() == email_addr:
            return route
    dom_routes = cfg.get("domain_routes") or {}
    if email_addr in dom_routes:
        return dom_routes[email_addr]
    domain = email_addr.split("@", 1)[-1] if "@" in email_addr else email_addr
    return dom_routes.get(domain)


def _load_active_client_emails() -> None:
    """Load project_routes and active_clients sender emails from routing_config.json."""
    global _ACTIVE_CLIENT_EMAILS
    try:
        config = _get_routing_config()
        addrs: set[str] = set()
        for addr in (config.get("project_routes") or {}):
            addrs.add(addr.lower())
        for addr in (config.get("active_clients") or {}):
            addrs.add(addr.lower())
        _ACTIVE_CLIENT_EMAILS = addrs
        if _ACTIVE_CLIENT_EMAILS:
            logger.info(
                "Loaded %d active client emails from routing_config",
                len(_ACTIVE_CLIENT_EMAILS),
            )
    except Exception as e:
        logger.warning("Could not load routing_config for active clients: %s", e)


# Populate active-client set on import so categorize_email works in one-off tests / CLI.
_load_active_client_emails()


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
        CREATE TABLE IF NOT EXISTS scan_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at)
    """)

    # Add analysis columns (backwards-compatible migration)
    for col, default in [
        ("analysis TEXT DEFAULT ''", "''"),
        ("summary TEXT DEFAULT ''", "''"),
        ("action_items TEXT DEFAULT ''", "''"),
        ("urgency TEXT DEFAULT 'fyi'", "'fyi'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE emails ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()
    conn.close()
    logger.info("Email database initialized at %s", db_path)


def get_scan_state(key: str, db_path: str = DB_PATH) -> Optional[str]:
    """Read a persisted scan state value."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT value FROM scan_state WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def set_scan_state(key: str, value: str, db_path: str = DB_PATH) -> None:
    """Persist a scan state value."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO scan_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Failed to save scan state %s: %s", key, e)


def _generate_stable_message_id(sender: str, subject: str, date_str: str) -> str:
    """Stable message ID when Message-ID header is missing (dedup across restarts)."""
    raw = f"{sender}|{subject}|{date_str}".encode("utf-8", errors="replace")
    return f"<generated-{hashlib.sha256(raw).hexdigest()[:16]}@email-monitor>"

def _set_poll_uid_high_water_mark(mail: imaplib.IMAP4_SSL) -> None:
    """Seed last_poll_uid from highest mailbox UID so poll_once skips already-indexed mail."""
    try:
        _, uid_data = mail.uid("search", None, "ALL")
        if not uid_data or not uid_data[0]:
            return
        all_uids = uid_data[0].split()
        if not all_uids:
            return
        last = all_uids[-1]
        highest = last.decode() if isinstance(last, bytes) else str(last)
        set_scan_state("last_poll_uid", highest)
        logger.info("Set poll UID high-water mark to %s", highest)
    except Exception as e:
        logger.warning("Could not set poll UID high-water mark: %s", e)


def categorize_email(subject: str, sender: str, body_snippet: str = "") -> tuple[str, str]:
    """
    Categorize an email: self-emails, active clients, routed senders, marketing patterns, then keywords.

    Returns:
        (category, priority)
    """
    # Skip self-sent emails (Cursor prompts, test emails, internal automation)
    email_addr = _sender_email_addr(sender)
    _own_addresses = {
        "bob@symphonysh.com",
        "admin@symphonysh.com",
        "noreply@symphonysh.com",
    }
    _zoho = os.environ.get("ZOHO_EMAIL", "").lower().strip()
    if _zoho:
        _own_addresses.add(_zoho)
    if email_addr and email_addr.lower() in _own_addresses:
        return "INTERNAL", "none"

    # Skip "Re: Cursor Prompt" by subject
    if "cursor prompt" in (subject or "").lower():
        return "INTERNAL", "none"

    if email_addr and email_addr in _ACTIVE_CLIENT_EMAILS:
        return "ACTIVE_CLIENT", "high"

    route = _lookup_route_for_sender(sender)
    if route:
        cat, pri = _route_label_to_category(route)
        if cat != "GENERAL" or route == "_project_match":
            return cat, pri

    patterns = _get_routing_config().get("marketing_patterns") or []
    text_lower = f"{subject} {body_snippet}".lower()
    if any(p.lower() in text_lower for p in patterns):
        return "MARKETING", "none"

    text = f"{subject} {sender} {body_snippet}".lower()
    for category, config in CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in text:
                return category, config["priority"]

    return "GENERAL", "low"


def _skip_notification_noise(category: str, priority: str) -> bool:
    """Skip LLM analysis and Redis publish for marketing, internal, and no-priority noise."""
    if category in ("MARKETING", "INTERNAL"):
        return True
    if (priority or "").lower() == "none":
        return True
    return False


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


def update_email_analysis(
    message_id: str,
    analysis: dict,
    db_path: str = DB_PATH,
) -> None:
    """Store LLM analysis results for an email."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE emails SET analysis = ?, summary = ?, action_items = ?, urgency = ?
               WHERE message_id = ?""",
            (
                json.dumps(analysis),
                analysis.get("summary", ""),
                analysis.get("action_items", ""),
                analysis.get("urgency", "fyi"),
                message_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def analyze_and_store(
    message_id: str,
    sender: str,
    sender_name: str,
    subject: str,
    snippet: str,
    category: str,
) -> dict:
    """Run email analysis in a thread and store results. Returns analysis dict."""
    from analyzer import analyze_email

    analysis = await asyncio.to_thread(
        analyze_email, sender, sender_name, subject, snippet, category
    )
    await asyncio.to_thread(update_email_analysis, message_id, analysis)
    logger.info("Analysis stored for %s: urgency=%s", subject[:50], analysis.get("urgency"))
    return analysis


async def publish_urgent(
    redis_client: aioredis.Redis,
    category: str,
    sender: str,
    subject: str,
) -> None:
    """Publish urgent email notification to Redis channel."""
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
    analysis: dict | None = None,
) -> None:
    """Publish any new email to Redis email:new channel."""
    payload = {
        "category": category,
        "priority": priority,
        "sender": sender,
        "subject": subject,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if analysis:
        payload["summary"] = analysis.get("summary", "")
        payload["action_items"] = analysis.get("action_items", "")
        payload["urgency"] = analysis.get("urgency", "fyi")
    message = json.dumps(payload)
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
        # How many days to look back on startup for read+unread emails
        self.catchup_days = int(os.getenv("EMAIL_CATCHUP_DAYS", "3"))
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._catchup_done = False

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Connect and authenticate to IMAP server."""
        mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
        mail.login(self.email_address, self.email_password)
        return mail

    async def catchup_scan(self) -> int:
        """
        One-time startup scan: fetch ALL emails (read or unread) since the
        last known scan timestamp. On first ever run, looks back N days.
        Persists its high-water mark in SQLite so restarts only scan new mail.

        SILENT — stores emails in SQLite but does NOT push notifications.
        This prevents a flood of alerts for old mail after a restart.
        Only poll_once() (new incoming mail) triggers notifications.
        """
        if not self.email_address or not self.email_password:
            return 0

        new_count = 0
        try:
            mail = await asyncio.to_thread(self._connect_imap)
            mail.select("INBOX")

            # Determine where to scan from
            last_scan = get_scan_state("last_catchup_date")
            if last_scan:
                since_date = last_scan
                logger.info("Catchup scan: resuming from last scan date %s", since_date)
            else:
                since_date = (datetime.now(timezone.utc) - timedelta(days=self.catchup_days)).strftime("%d-%b-%Y")
                logger.info("Catchup scan: first run, looking back %d days (since %s)", self.catchup_days, since_date)

            _, message_numbers = mail.search(None, "SINCE", since_date)
            if not message_numbers[0]:
                logger.info("Catchup scan: no emails since %s", since_date)
                # Still save the high-water mark so next restart skips this range
                set_scan_state("last_catchup_date", datetime.now(timezone.utc).strftime("%d-%b-%Y"))
                _set_poll_uid_high_water_mark(mail)
                mail.logout()
                return 0

            msg_nums = message_numbers[0].split()
            logger.info("Catchup scan: found %d emails since %s", len(msg_nums), since_date)

            redis_client = await self._get_redis()

            for num in msg_nums:
                try:
                    # Use BODY.PEEK so we don't mark anything as read
                    _, msg_data = mail.fetch(num, "(RFC822.HEADER BODY.PEEK[TEXT]<0.4000>)")
                    if not msg_data or not msg_data[0]:
                        continue

                    header_data = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                    msg = email.message_from_bytes(header_data)

                    message_id = msg.get("Message-ID") or _generate_stable_message_id(
                        msg.get("From", ""), msg.get("Subject", ""), msg.get("Date", "")
                    )
                    raw_from = decode_header_value(msg.get("From", ""))
                    subject = decode_header_value(msg.get("Subject", "(no subject)"))
                    date_str = msg.get("Date", "")

                    sender_name, sender_email_addr = email.utils.parseaddr(raw_from)
                    if not sender_name:
                        sender_name = sender_email_addr.split("@")[0] if sender_email_addr else "Unknown"

                    received_at = ""
                    if date_str:
                        parsed = email.utils.parsedate_to_datetime(date_str)
                        received_at = parsed.isoformat()
                    if not received_at:
                        received_at = datetime.now(timezone.utc).isoformat()

                    snippet = ""
                    if len(msg_data) > 1 and isinstance(msg_data[1], tuple):
                        body_bytes = msg_data[1][1]
                        if isinstance(body_bytes, bytes):
                            snippet = body_bytes.decode("utf-8", errors="replace")[:2000]

                    category, priority = categorize_email(subject, raw_from, snippet)

                    is_new = store_email(
                        message_id=message_id,
                        sender=sender_email_addr,
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
                            "Catchup (silent): [%s] from %s: %s",
                            category, sender_email_addr, subject[:80],
                        )
                        # No Redis publish — catchup is silent, just indexes

                        # Analyze emails that don't have analysis yet (skip marketing noise)
                        if not _skip_notification_noise(category, priority):
                            try:
                                await analyze_and_store(
                                    message_id, sender_email_addr, sender_name,
                                    subject, snippet, category,
                                )
                            except Exception as e:
                                logger.error("Catchup analysis failed for %s: %s", subject[:50], e)

                except Exception as e:
                    logger.error("Catchup error processing email %s: %s", num, e)
                    continue

            _set_poll_uid_high_water_mark(mail)
            mail.logout()

            # Save today as the high-water mark so next restart only scans from here
            set_scan_state("last_catchup_date", datetime.now(timezone.utc).strftime("%d-%b-%Y"))
            logger.info("Catchup scan complete (silent) — indexed %d new email(s), saved high-water mark", new_count)

        except imaplib.IMAP4.error as e:
            logger.error("Catchup IMAP error: %s", e)
        except Exception as e:
            logger.error("Catchup scan error: %s", e)

        return new_count

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

            last_uid_raw = get_scan_state("last_poll_uid") or "0"
            try:
                last_uid_int = int(last_uid_raw)
            except ValueError:
                last_uid_int = 0

            typ, data = mail.uid("search", None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                mail.logout()
                return 0

            all_unseen = data[0].split()
            msg_uids: list[str] = []
            for u in all_unseen:
                uid_s = u.decode() if isinstance(u, bytes) else str(u)
                try:
                    if int(uid_s) > last_uid_int:
                        msg_uids.append(uid_s)
                except ValueError:
                    continue

            if not msg_uids:
                mail.logout()
                return 0

            msg_uids.sort(key=lambda x: int(x))
            logger.info(
                "Found %d unread email(s) with UID > %s (poll checkpoint)",
                len(msg_uids),
                last_uid_raw,
            )

            redis_client = await self._get_redis()
            max_uid_seen = last_uid_int

            for uid in msg_uids:
                try:
                    _, msg_data = mail.uid(
                        "fetch", uid, "(RFC822.HEADER BODY.PEEK[TEXT]<0.4000>)"
                    )
                    if not msg_data or not msg_data[0]:
                        continue

                    # Parse headers
                    header_data = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                    msg = email.message_from_bytes(header_data)

                    message_id = msg.get("Message-ID") or _generate_stable_message_id(
                        msg.get("From", ""),
                        msg.get("Subject", ""),
                        msg.get("Date", ""),
                    )
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
                            snippet = body_bytes.decode("utf-8", errors="replace")[:2000]

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

                    uid_int = int(uid)
                    max_uid_seen = max(max_uid_seen, uid_int)

                    if is_new:
                        new_count += 1
                        logger.info(
                            "New email: [%s] from %s: %s",
                            category, sender_email, subject[:80],
                        )

                        # Run LLM analysis (non-blocking — runs in thread)
                        analysis = None
                        if not _skip_notification_noise(category, priority):
                            try:
                                analysis = await analyze_and_store(
                                    message_id, sender_email, sender_name,
                                    subject, snippet, category,
                                )
                            except Exception as e:
                                logger.error("Analysis failed for %s: %s", subject[:50], e)
                                analysis = None

                        # Run bid triage for BuildingConnected invites
                        if category == "BID_INVITE":
                            try:
                                from bid_triage import triage_bid_email
                                await asyncio.to_thread(triage_bid_email, sender_email, subject, snippet)
                            except Exception as e:
                                logger.error("Bid triage failed: %s", e)

                        # Auto-respond to active client emails
                        if category == "ACTIVE_CLIENT":
                            try:
                                import sys as _sys
                                # Try all expected mount paths for auto_responder.
                                _openclaw_paths = [
                                    "/app/openclaw",
                                    "/app/../openclaw",
                                    os.path.join(os.path.dirname(__file__), "..", "openclaw"),
                                ]
                                for _odir in _openclaw_paths:
                                    _resolved = os.path.abspath(_odir)
                                    if os.path.isdir(_resolved) and _resolved not in _sys.path:
                                        _sys.path.insert(0, _resolved)
                                logger.info("Auto-responder sys.path paths checked: %s", _openclaw_paths)
                                from auto_responder import auto_respond
                                await asyncio.to_thread(
                                    auto_respond, sender_email, sender_name, subject, snippet, message_id,
                                )
                            except Exception as e:
                                logger.error("Auto-respond failed: %s", e)

                        if not _skip_notification_noise(category, priority):
                            # Publish high-priority to Redis urgent channel
                            if category in HIGH_PRIORITY_CATEGORIES:
                                await publish_urgent(redis_client, category, sender_name or sender_email, subject)

                            # Publish actionable new emails to email:new channel
                            await publish_new_email(
                                redis_client, category, priority,
                                sender_name or sender_email, subject, analysis,
                            )

                except Exception as e:
                    logger.error("Error processing email UID %s: %s", uid, e)
                    continue

            if max_uid_seen > last_uid_int:
                set_scan_state("last_poll_uid", str(max_uid_seen))

            mail.logout()

        except imaplib.IMAP4.error as e:
            logger.error("IMAP error: %s", e)
        except Exception as e:
            logger.error("Email poll error: %s", e)

        return new_count

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
        _load_active_client_emails()

        # One-time catchup: scan last N days of ALL emails (read + unread)
        if not self._catchup_done:
            try:
                count = await self.catchup_scan()
                if count > 0:
                    logger.info("Catchup scan found %d new email(s)", count)
                else:
                    logger.info("Catchup scan complete — no new emails to import")
                self._catchup_done = True
            except Exception as e:
                logger.error("Catchup scan failed: %s", e)
                self._catchup_done = True  # Don't retry forever

        while self._running:
            try:
                count = await self.poll_once()
                if count > 0:
                    logger.info("Processed %d new email(s)", count)
            except Exception as e:
                logger.error("Monitor loop error: %s", e)

            # Route emails to folders after processing
            try:
                from router import route_inbox_async
                routed = await route_inbox_async(
                    self.imap_server, self.imap_port,
                    self.email_address, self.email_password,
                )
                if routed > 0:
                    logger.info("Router moved %d email(s) to folders", routed)
            except Exception as e:
                logger.error("Email routing error: %s", e)

            # Follow-up tracker: alert on overdue client responses.
            try:
                import sys as _sys
                _openclaw_dir = "/app/openclaw"  # volume mount: ./openclaw:/app/openclaw
                if os.path.isdir(_openclaw_dir) and _openclaw_dir not in _sys.path:
                    _sys.path.insert(0, _openclaw_dir)
                from follow_up_tracker import run_cycle as follow_up_run_cycle
                follow_up_result = await asyncio.to_thread(
                    follow_up_run_cycle,
                    os.environ.get("FOLLOW_UP_DB_PATH", "/data/email-monitor/follow_ups.db"),
                    DB_PATH,
                    os.environ.get("JOBS_DB_PATH", "/app/data/jobs.db"),
                )
                if (follow_up_result or {}).get("overdue_alerts", 0) or (follow_up_result or {}).get("followup_alerts", 0):
                    logger.info("Follow-up tracker alerts: %s", follow_up_result)
            except Exception as e:
                logger.error("Follow-up tracker error: %s", e)

            # Payment tracker: monitor agreement/deposit/payment status.
            try:
                import sys as _sys
                _openclaw_dir = "/app/openclaw"  # volume mount: ./openclaw:/app/openclaw
                if os.path.isdir(_openclaw_dir) and _openclaw_dir not in _sys.path:
                    _sys.path.insert(0, _openclaw_dir)
                from payment_tracker import run_cycle as payment_run_cycle
                payment_result = await asyncio.to_thread(
                    payment_run_cycle,
                    os.environ.get("PAYMENT_DB_PATH", "/data/email-monitor/payments.db"),
                    DB_PATH,
                    os.environ.get("EMAIL_ROUTING_CONFIG", os.path.join(os.path.dirname(__file__), "routing_config.json")),
                )
                if any((payment_result or {}).get(k, 0) for k in ("signed_updates", "paid_updates", "due_alerts")):
                    logger.info("Payment tracker updates: %s", payment_result)
            except Exception as e:
                logger.error("Payment tracker error: %s", e)

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
