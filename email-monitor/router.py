#!/usr/bin/env python3
"""
router.py — IMAP-based email routing for Symphony Smart Homes.

Moves emails from INBOX to categorized Zoho Mail folders based on
sender, domain, and content patterns. Runs after each poll_once() cycle.
"""

import imaplib
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = os.getenv(
    "EMAIL_ROUTING_CONFIG",
    str(Path(__file__).parent / "routing_config.json"),
)

# Cache for folders we've already verified/created this session
_verified_folders: set[str] = set()


def _load_config() -> dict:
    """Load routing config from JSON file."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Routing config not found at %s", CONFIG_PATH)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Invalid routing config JSON: %s", e)
        return {}


def _ensure_folder(mail: imaplib.IMAP4_SSL, folder: str) -> bool:
    """Create an IMAP folder if it doesn't exist. Returns True on success."""
    if folder in _verified_folders:
        return True

    # Zoho uses "/" as hierarchy separator
    status, _ = mail.select(f'"{folder}"')
    if status == "OK":
        _verified_folders.add(folder)
        # Switch back to INBOX
        mail.select("INBOX")
        return True

    # Folder doesn't exist — create it (and parent folders)
    parts = folder.split("/")
    for i in range(1, len(parts) + 1):
        partial = "/".join(parts[:i])
        try:
            mail.create(f'"{partial}"')
            logger.info("Created IMAP folder: %s", partial)
        except imaplib.IMAP4.error:
            pass  # Already exists

    _verified_folders.add(folder)
    mail.select("INBOX")
    return True


def _move_email(mail: imaplib.IMAP4_SSL, msg_num: bytes, folder: str) -> bool:
    """Move an email from INBOX to the target folder via COPY + DELETE."""
    try:
        _ensure_folder(mail, folder)

        # COPY to destination
        status, _ = mail.copy(msg_num, f'"{folder}"')
        if status != "OK":
            logger.error("COPY failed for msg %s to %s", msg_num, folder)
            return False

        # Mark original as deleted
        mail.store(msg_num, "+FLAGS", "\\Deleted")
        return True
    except imaplib.IMAP4.error as e:
        logger.error("Failed to move msg %s to %s: %s", msg_num, folder, e)
        return False


def _extract_email_addr(from_header: str) -> str:
    """Extract bare email address from a From header value."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower()
    # Might be a bare email
    return from_header.strip().lower()


def _extract_domain(email_addr: str) -> str:
    """Extract domain from an email address."""
    parts = email_addr.split("@")
    return parts[1] if len(parts) == 2 else ""


def _match_project(sender_email: str, config: dict) -> str | None:
    """Try to match a sender to a project folder."""
    project_routes = config.get("project_routes", {})
    for pattern, folder in project_routes.items():
        if pattern.lower() in sender_email:
            return folder
    return None


def determine_folder(
    sender_email: str,
    subject: str,
    snippet: str,
    config: dict,
) -> str | None:
    """
    Determine the destination folder for an email.

    Returns folder path string, or None to leave in INBOX.
    Priority order matches the spec.
    """
    sender_lower = sender_email.lower()
    domain = _extract_domain(sender_lower)
    combined_text = f"{subject} {snippet}".lower()

    # 1. Active client / project match (highest priority)
    project_routes = config.get("project_routes", {})
    for pattern, folder in project_routes.items():
        if pattern.lower() in sender_lower:
            return folder

    # 2. Exact sender match in category routes
    category_routes = config.get("category_routes", {})
    for pattern, folder in category_routes.items():
        if pattern.lower() == sender_lower:
            return folder

    # 3. Domain-based routing
    domain_routes = config.get("domain_routes", {})
    for pattern, folder in domain_routes.items():
        if pattern.lower() == domain or pattern.lower() in sender_lower:
            if folder == "_project_match":
                # Try to match to a project, fall back to INBOX
                project = _match_project(sender_lower, config)
                if project:
                    return project
                # Check subject/snippet for project name hints
                for _, proj_folder in project_routes.items():
                    # Extract project name from folder for fuzzy match
                    proj_name = proj_folder.split("/")[-1].split(" - ")[-1].lower()
                    if proj_name in combined_text:
                        return proj_folder
                return None  # Leave in INBOX if no project match
            return folder

    # 4. Marketing / ignore patterns (check body + subject)
    marketing_patterns = config.get("marketing_patterns", [])
    for pattern in marketing_patterns:
        if pattern.lower() in combined_text or pattern.lower() in sender_lower:
            return "Marketing-Ignore"

    # 5. No match — leave in INBOX
    return None


def route_inbox(
    imap_server: str,
    imap_port: int,
    email_address: str,
    email_password: str,
) -> int:
    """
    Scan INBOX and route emails to appropriate folders.

    Returns the number of emails moved.
    """
    config = _load_config()
    if not config:
        return 0

    moved = 0
    try:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_address, email_password)
        mail.select("INBOX")

        # Fetch ALL messages in INBOX (read and unread)
        status, message_numbers = mail.search(None, "ALL")
        if status != "OK" or not message_numbers[0]:
            mail.logout()
            return 0

        msg_nums = message_numbers[0].split()
        logger.info("Router: scanning %d INBOX messages", len(msg_nums))

        for num in msg_nums:
            try:
                # Fetch just headers + small body peek for routing
                status, msg_data = mail.fetch(
                    num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.2000>)"
                )
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                # Parse From and Subject from headers
                header_data = b""
                snippet_data = b""
                for part in msg_data:
                    if isinstance(part, tuple):
                        desc = part[0].decode("utf-8", errors="replace").upper()
                        if "HEADER" in desc:
                            header_data = part[1]
                        elif "TEXT" in desc:
                            snippet_data = part[1]

                from_header = ""
                subject = ""
                for line in header_data.decode("utf-8", errors="replace").splitlines():
                    if line.lower().startswith("from:"):
                        from_header = line[5:].strip()
                    elif line.lower().startswith("subject:"):
                        subject = line[8:].strip()

                sender_email = _extract_email_addr(from_header)
                snippet = snippet_data.decode("utf-8", errors="replace")[:2000] if snippet_data else ""

                folder = determine_folder(sender_email, subject, snippet, config)
                if folder:
                    if _move_email(mail, num, folder):
                        moved += 1
                        logger.info(
                            "Routed: %s → %s (from: %s)",
                            subject[:60], folder, sender_email,
                        )

            except Exception as e:
                logger.error("Router error on msg %s: %s", num, e)
                continue

        # Expunge deleted messages
        if moved > 0:
            mail.expunge()
            logger.info("Router: moved %d email(s), expunged from INBOX", moved)

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error("Router IMAP error: %s", e)
    except Exception as e:
        logger.error("Router error: %s", e)

    return moved


async def route_inbox_async(
    imap_server: str,
    imap_port: int,
    email_address: str,
    email_password: str,
) -> int:
    """Async wrapper for route_inbox — runs IMAP operations in a thread."""
    import asyncio
    return await asyncio.to_thread(
        route_inbox, imap_server, imap_port, email_address, email_password
    )


def route_all_folders(
    imap_server: str,
    imap_port: int,
    email_address: str,
    email_password: str,
    skip_folders: list[str] | None = None,
) -> int:
    """
    One-time cleanup: scan ALL mailbox folders and route emails
    to the correct destination based on routing rules.

    Skips folders that are already part of the new structure.
    """
    config = _load_config()
    if not config:
        return 0

    if skip_folders is None:
        skip_folders = [
            "Projects", "Bids", "Vendor", "Banking",
            "Marketing-Ignore", "Archive", "Drafts", "Trash",
            "Junk", "Spam",
        ]

    total_moved = 0
    try:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_address, email_password)

        # List all folders
        status, folder_list = mail.list()
        if status != "OK":
            logger.error("Could not list folders")
            mail.logout()
            return 0

        folders_to_scan = []
        for item in folder_list:
            decoded = item.decode("utf-8", errors="replace")
            # Extract folder name — Zoho format: '(\\flags) "/" "FolderName"'
            match = re.search(r'"([^"]*)"$', decoded)
            if not match:
                continue
            folder_name = match.group(1)

            # Skip folders that are part of the new structure
            should_skip = False
            for skip in skip_folders:
                if folder_name.startswith(skip) or folder_name == skip:
                    should_skip = True
                    break
            if should_skip:
                continue

            folders_to_scan.append(folder_name)

        logger.info("Cleanup: scanning %d folders: %s", len(folders_to_scan), folders_to_scan)

        for folder_name in folders_to_scan:
            try:
                status, _ = mail.select(f'"{folder_name}"')
                if status != "OK":
                    continue

                status, message_numbers = mail.search(None, "ALL")
                if status != "OK" or not message_numbers[0]:
                    continue

                msg_nums = message_numbers[0].split()
                logger.info("Cleanup: scanning %d emails in '%s'", len(msg_nums), folder_name)
                moved_from_folder = 0

                for num in msg_nums:
                    try:
                        status, msg_data = mail.fetch(
                            num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.2000>)"
                        )
                        if status != "OK" or not msg_data or not msg_data[0]:
                            continue

                        header_data = b""
                        snippet_data = b""
                        for part in msg_data:
                            if isinstance(part, tuple):
                                desc = part[0].decode("utf-8", errors="replace").upper()
                                if "HEADER" in desc:
                                    header_data = part[1]
                                elif "TEXT" in desc:
                                    snippet_data = part[1]

                        from_header = ""
                        subject = ""
                        for line in header_data.decode("utf-8", errors="replace").splitlines():
                            if line.lower().startswith("from:"):
                                from_header = line[5:].strip()
                            elif line.lower().startswith("subject:"):
                                subject = line[8:].strip()

                        sender_email = _extract_email_addr(from_header)
                        snippet = snippet_data.decode("utf-8", errors="replace")[:2000] if snippet_data else ""

                        dest = determine_folder(sender_email, subject, snippet, config)
                        if dest and dest != folder_name:
                            if _ensure_folder(mail, dest):
                                mail.copy(num, f'"{dest}"')
                                mail.store(num, "+FLAGS", "\\Deleted")
                                moved_from_folder += 1
                                logger.info(
                                    "Cleanup: %s → %s (from: %s, was in: %s)",
                                    subject[:50], dest, sender_email, folder_name,
                                )

                    except Exception as e:
                        logger.error("Cleanup error on msg %s in %s: %s", num, folder_name, e)
                        continue

                if moved_from_folder > 0:
                    mail.expunge()
                    total_moved += moved_from_folder
                    logger.info("Cleanup: moved %d from '%s'", moved_from_folder, folder_name)

            except Exception as e:
                logger.error("Cleanup: error scanning folder '%s': %s", folder_name, e)
                continue

        mail.logout()
        logger.info("Cleanup complete: moved %d total emails across all folders", total_moved)

    except Exception as e:
        logger.error("Cleanup error: %s", e)

    return total_moved
