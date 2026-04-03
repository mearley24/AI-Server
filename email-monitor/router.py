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

# Snapshot of INBOX message IDs → sender for learn-from-moves detection
_inbox_snapshot: dict[str, str] = {}  # {message_id: sender_email}


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


def _save_config(config: dict) -> bool:
    """Save routing config back to JSON file."""
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        logger.info("Routing config saved to %s", CONFIG_PATH)
        return True
    except Exception as e:
        logger.error("Failed to save routing config: %s", e)
        return False


def _snapshot_inbox(mail: imaplib.IMAP4_SSL) -> dict[str, str]:
    """Take a snapshot of current INBOX: {message_id: sender_email}."""
    snapshot = {}
    try:
        mail.select("INBOX")
        status, msg_nums = mail.search(None, "ALL")
        if status != "OK" or not msg_nums[0]:
            return snapshot
        for num in msg_nums[0].split():
            try:
                status, data = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])")
                if status != "OK" or not data or not data[0]:
                    continue
                header = b""
                for part in data:
                    if isinstance(part, tuple):
                        header = part[1]
                        break
                decoded = header.decode("utf-8", errors="replace")
                msg_id = ""
                sender = ""
                for line in decoded.splitlines():
                    if line.lower().startswith("message-id:"):
                        msg_id = line[11:].strip()
                    elif line.lower().startswith("from:"):
                        sender = _extract_email_addr(line[5:].strip())
                if msg_id and sender:
                    snapshot[msg_id] = sender
            except Exception:
                continue
    except Exception as e:
        logger.debug("Snapshot error: %s", e)
    return snapshot


def learn_from_moves(mail: imaplib.IMAP4_SSL) -> int:
    """Detect emails manually moved out of INBOX and learn the routing rule.

    Compares current INBOX against the previous snapshot. If a message
    disappeared from INBOX, scan all folders to find where it went,
    then add the sender's domain to routing config for that folder.

    Returns the number of new rules learned.
    """
    global _inbox_snapshot
    if not _inbox_snapshot:
        # First run — no previous snapshot to compare against, skip
        logger.info("Learn-from-moves: no previous snapshot, skipping")
        return 0

    old_snapshot = _inbox_snapshot
    new_snapshot = _snapshot_inbox(mail)
    # Don't update _inbox_snapshot here — route_inbox does it after routing
    logger.info("Learn-from-moves: old=%d, new=%d", len(old_snapshot), len(new_snapshot))

    # Find message IDs that were in INBOX but are gone now
    moved_ids = set(old_snapshot.keys()) - set(new_snapshot.keys())
    if not moved_ids:
        return 0

    config = _load_config()
    learned = 0

    # Get list of all folders
    try:
        status, folder_list = mail.list()
        if status != "OK":
            return 0
    except Exception:
        return 0

    folders = []
    for item in folder_list:
        if isinstance(item, bytes):
            # Parse folder name from IMAP LIST response
            decoded = item.decode("utf-8", errors="replace")
            match = re.search(r'"([^"]+)"\s*$|\s(\S+)\s*$', decoded)
            if match:
                folder_name = match.group(1) or match.group(2)
                if folder_name and folder_name.upper() not in ("INBOX", "DRAFTS", "SENT", "TRASH", "JUNK", "OUTBOX"):
                    folders.append(folder_name)
    if folders:
        logger.info("Learn-from-moves: scanning %d folders: %s", len(folders), ", ".join(folders[:20]))

    for msg_id in moved_ids:
        sender = old_snapshot.get(msg_id, "")
        if not sender:
            continue

        domain = _extract_domain(sender)
        if not domain:
            continue

        # Skip if domain is already routed
        existing_domains = config.get("domain_routes", {})
        if domain in existing_domains:
            continue

        # Search each folder for this email (try multiple IMAP search methods)
        dest_folder = None
        # Search by FROM sender in each folder — more reliable than Message-ID on Zoho
        for folder in folders:
            try:
                status, data = mail.select(f'"{folder}"')
                logger.info("Learn-from-moves: select folder='%s' status=%s", folder, status)
                if status != "OK":
                    continue

                # Search for emails from this sender in this folder.
                # Try exact sender first, then fallback to just the domain.
                search_queries = [f'FROM "{sender}"']
                if domain:
                    search_queries.append(f'FROM "{domain}"')

                for query in search_queries:
                    status, found = mail.search(None, query)
                    found_raw = found[0].decode("utf-8", errors="replace") if found and found[0] else ""
                    logger.info(
                        "Learn-from-moves: folder='%s' query=%s status=%s found='%s'",
                        folder, query, status, found_raw[:120],
                    )
                    if status == "OK" and found and found[0] and found[0].strip():
                        dest_folder = folder
                        logger.info("Learn-from-moves: found sender=%s in folder=%s via query=%s", sender, folder, query)
                        break
                if dest_folder:
                    break
            except Exception as e:
                logger.debug("Learn-from-moves: error searching %s: %s", folder, e)
                continue

        if not dest_folder:
            # Still couldn't find it — notify via Redis so Bob can ask
            try:
                import redis as _redis
                r = _redis.from_url(
                    os.environ.get("REDIS_URL", "redis://172.18.0.100:6379"),
                    decode_responses=True, socket_timeout=2,
                )
                r.publish("notifications:email", json.dumps({
                    "title": "New sender moved from Inbox",
                    "body": f"You moved an email from {sender} ({domain}). Reply with the folder name to auto-route future emails from {domain}.",
                }))
            except Exception:
                pass
            logger.info("Learn-from-moves: couldn't locate %s, asked via iMessage", sender)
            continue

        if dest_folder:
            # Learn the rule: add domain → folder
            if "domain_routes" not in config:
                config["domain_routes"] = {}
            config["domain_routes"][domain] = dest_folder

            # Also add to marketing_patterns if it went to Marketing
            if "marketing" in dest_folder.lower():
                if "marketing_patterns" not in config:
                    config["marketing_patterns"] = []
                if domain not in config["marketing_patterns"]:
                    config["marketing_patterns"].append(domain)

            _save_config(config)
            learned += 1
            logger.info(
                "Learned routing rule: %s → %s (from manual move of %s)",
                domain, dest_folder, sender,
            )

    # Switch back to INBOX
    try:
        mail.select("INBOX")
    except Exception:
        pass

    return learned


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

        # Learn from manual moves before routing
        try:
            learned = learn_from_moves(mail)
            if learned:
                logger.info("Learned %d new routing rule(s) from manual moves", learned)
                config = _load_config()  # Reload with new rules
        except Exception as e:
            logger.warning("Learn-from-moves error: %s", e)

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

        # Take snapshot AFTER routing for next cycle's learn_from_moves
        try:
            global _inbox_snapshot
            mail.select("INBOX")
            _inbox_snapshot = _snapshot_inbox(mail)
            logger.info("Inbox snapshot: %d messages tracked", len(_inbox_snapshot))
        except Exception as e:
            logger.warning("Snapshot error: %s", e)

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
