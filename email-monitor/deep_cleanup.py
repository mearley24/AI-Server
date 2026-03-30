#!/usr/bin/env python3
"""
Deep mailbox cleanup — consolidates ALL old folders into the new structure,
marks handled emails as read, and deletes empty old folders.

Run on Bob: cd ~/AI-Server && python3 email-monitor/deep_cleanup.py
"""
import imaplib
import os
import sys
import logging
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("deep_cleanup")

from router import determine_folder, _load_config, _ensure_folder, _extract_email_addr

# Map old folders to new destinations
# Emails that match routing rules get routed normally
# Everything else in these folders goes to the specified default
FOLDER_MIGRATION = {
    "Snap One": "Vendor/Snap One",
    "Neuwave": "Vendor/Neuwave",
    "Education": "Vendor/Education",
    "Timber Ridge": "Projects/Shaw - Timber Ridge",
    "Monthly Payments": "Vendor/Accounting",
    "Notes": "Archive/Notes",
    "Dealer Accounts": "Vendor/Dealer Accounts",
    "Home Depot Receipts-Extras": "Vendor/Receipts",
    "Orders": "Vendor/Orders",
    "D-tools": "Vendor/D-Tools",
    "Quoted": "Archive/Quoted",
    "RMA": "Vendor/RMA",
    "Deleted Messages": None,  # Leave or trash
    "Sent Messages": None,  # Leave — these are sent mail
    "ZM_Import/Sent_Import/Sent Mail": None,  # Old import, leave
    "ZM_Import/Sent_Import": None,
    "ZM_Import": None,
    "Trash/INBOX_Import": None,  # Old import trash
    "INBOX/Notification": "Marketing-Ignore",
    "INBOX/Newsletter": "Marketing-Ignore",
}

# Folders that are already in the new structure — don't touch
PROTECTED_FOLDERS = {
    "INBOX", "Drafts", "Templates", "Snoozed", "Sent", "Spam", "Trash",
    "Archive", "Bids", "Bids/Active", "Bids/Declined",
    "Vendor", "Vendor/Snap One", "Vendor/Accounting", "Vendor/Neuwave",
    "Vendor/Education", "Vendor/Dealer Accounts", "Vendor/Receipts",
    "Vendor/Orders", "Vendor/D-Tools", "Vendor/RMA",
    "Banking", "Marketing-Ignore",
    "Projects", "Projects/Topletz - 84 Aspen Meadow",
    "Projects/Shaw - Timber Ridge", "Projects/MMH - 42 Red Spruce",
    "Archive/Notes", "Archive/Quoted",
}


def move_all_in_folder(mail, source_folder, dest_folder):
    """Move all emails from source to dest folder."""
    try:
        status, _ = mail.select(f'"{source_folder}"')
        if status != "OK":
            return 0

        _, nums = mail.search(None, "ALL")
        if not nums[0]:
            return 0

        msg_nums = nums[0].split()
        _ensure_folder(mail, dest_folder)

        # Re-select source after _ensure_folder may have changed selection
        mail.select(f'"{source_folder}"')

        for num in msg_nums:
            try:
                mail.copy(num, f'"{dest_folder}"')
                mail.store(num, "+FLAGS", "\\Deleted")
            except Exception as e:
                logger.error("  Error moving msg %s: %s", num, e)

        mail.expunge()
        logger.info("  Moved %d emails: %s → %s", len(msg_nums), source_folder, dest_folder)
        return len(msg_nums)
    except Exception as e:
        logger.error("  Error processing folder %s: %s", source_folder, e)
        return 0


def smart_route_folder(mail, source_folder, default_dest, config):
    """Route emails in a folder — use routing rules first, fall back to default."""
    try:
        status, _ = mail.select(f'"{source_folder}"')
        if status != "OK":
            return 0

        _, nums = mail.search(None, "ALL")
        if not nums[0]:
            return 0

        msg_nums = nums[0].split()
        moved = 0

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

                # Try routing rules first
                dest = determine_folder(sender_email, subject, snippet, config)
                if not dest:
                    dest = default_dest

                if dest and dest != source_folder:
                    _ensure_folder(mail, dest)
                    # Re-select source
                    mail.select(f'"{source_folder}"')
                    mail.copy(num, f'"{dest}"')
                    mail.store(num, "+FLAGS", "\\Deleted")
                    moved += 1

            except Exception as e:
                logger.error("  Error on msg %s: %s", num, e)
                continue

        if moved > 0:
            mail.expunge()
        logger.info("  Routed %d/%d emails from %s", moved, len(msg_nums), source_folder)
        return moved
    except Exception as e:
        logger.error("  Error processing %s: %s", source_folder, e)
        return 0


def mark_all_read(mail, folder):
    """Mark all emails in a folder as read."""
    try:
        status, _ = mail.select(f'"{folder}"')
        if status != "OK":
            return 0

        _, nums = mail.search(None, "UNSEEN")
        if not nums[0]:
            return 0

        msg_nums = nums[0].split()
        for num in msg_nums:
            mail.store(num, "+FLAGS", "\\Seen")

        logger.info("  Marked %d emails as read in %s", len(msg_nums), folder)
        return len(msg_nums)
    except Exception as e:
        logger.error("  Error marking read in %s: %s", folder, e)
        return 0


def delete_folder(mail, folder):
    """Delete an empty IMAP folder."""
    try:
        # Make sure we're not selected into it
        mail.select("INBOX")
        status, _ = mail.delete(f'"{folder}"')
        if status == "OK":
            logger.info("  Deleted empty folder: %s", folder)
            return True
    except Exception as e:
        logger.error("  Could not delete folder %s: %s", folder, e)
    return False


def main():
    server = os.getenv("ZOHO_IMAP_SERVER", "imappro.zoho.com")
    port = int(os.getenv("ZOHO_IMAP_PORT", "993"))
    email_addr = os.getenv("SYMPHONY_EMAIL", "")
    password = os.getenv("SYMPHONY_EMAIL_PASSWORD", "")

    if not email_addr or not password:
        print("ERROR: SYMPHONY_EMAIL and SYMPHONY_EMAIL_PASSWORD must be set")
        sys.exit(1)

    config = _load_config()
    mail = imaplib.IMAP4_SSL(server, port)
    mail.login(email_addr, password)

    total_moved = 0
    total_marked = 0
    folders_deleted = []

    # Phase 1: Migrate old folders to new structure
    print("\n=== Phase 1: Migrating old folders ===\n")
    for old_folder, new_dest in FOLDER_MIGRATION.items():
        if new_dest is None:
            logger.info("Skipping %s (leave as-is)", old_folder)
            continue

        logger.info("Processing: %s → %s", old_folder, new_dest)
        if old_folder in ("INBOX", "INBOX/Notification", "INBOX/Newsletter"):
            # These need smart routing — some emails may match specific projects
            moved = smart_route_folder(mail, old_folder, new_dest, config)
        else:
            # Bulk move — all go to the same destination
            moved = move_all_in_folder(mail, old_folder, new_dest)
        total_moved += moved

    # Phase 2: Smart-route remaining INBOX emails
    print("\n=== Phase 2: Routing remaining INBOX emails ===\n")
    logger.info("Smart-routing INBOX...")
    # For INBOX, uncategorized emails go to Archive
    moved = smart_route_folder(mail, "INBOX", "Archive", config)
    total_moved += moved

    # Phase 3: Mark all emails in organized folders as read
    print("\n=== Phase 3: Marking handled emails as read ===\n")
    folders_to_mark_read = [
        "Projects/Topletz - 84 Aspen Meadow",
        "Projects/Shaw - Timber Ridge",
        "Projects/MMH - 42 Red Spruce",
        "Bids/Active",
        "Vendor", "Vendor/Snap One", "Vendor/Accounting",
        "Vendor/Neuwave", "Vendor/Education", "Vendor/Dealer Accounts",
        "Vendor/Receipts", "Vendor/Orders", "Vendor/D-Tools", "Vendor/RMA",
        "Banking",
        "Marketing-Ignore",
        "Archive", "Archive/Notes", "Archive/Quoted",
    ]
    for folder in folders_to_mark_read:
        marked = mark_all_read(mail, folder)
        total_marked += marked

    # Phase 4: Delete empty old folders
    print("\n=== Phase 4: Cleaning up empty old folders ===\n")
    old_folders_to_delete = [
        "Snap One", "Neuwave", "Education", "Timber Ridge",
        "Monthly Payments", "Notes", "Dealer Accounts",
        "Home Depot Receipts-Extras", "Orders", "D-tools",
        "Quoted", "RMA", "Deleted Messages", "Sent Messages",
        "INBOX/Notification", "INBOX/Newsletter",
        "ZM_Import/Sent_Import/Sent Mail", "ZM_Import/Sent_Import", "ZM_Import",
        "Trash/INBOX_Import",
    ]
    for folder in old_folders_to_delete:
        # Check if empty first
        try:
            status, _ = mail.select(f'"{folder}"')
            if status != "OK":
                continue
            _, nums = mail.search(None, "ALL")
            count = len(nums[0].split()) if nums[0] else 0
            mail.select("INBOX")  # Deselect before delete
            if count == 0:
                if delete_folder(mail, folder):
                    folders_deleted.append(folder)
            else:
                logger.info("  %s still has %d emails — not deleting", folder, count)
        except:
            pass

    mail.logout()

    print(f"\n{'='*60}")
    print(f"CLEANUP COMPLETE")
    print(f"{'='*60}")
    print(f"Emails moved:    {total_moved}")
    print(f"Emails marked read: {total_marked}")
    print(f"Folders deleted: {len(folders_deleted)}")
    if folders_deleted:
        for f in folders_deleted:
            print(f"  - {f}")
    print()


if __name__ == "__main__":
    main()
