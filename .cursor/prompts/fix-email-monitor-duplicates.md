# Fix: Email Monitor — Duplicate Notifications on Restart

The email-monitor re-sends notifications for already-handled emails on every container restart. Root causes:

1. `poll_once()` uses `IMAP UNSEEN` to find emails but fetches with `BODY.PEEK` which does NOT mark them as read — so every restart re-fetches all unread emails
2. Emails without a `Message-ID` header get `f"unknown-{time.time()}"` — a unique value each restart, defeating the SQLite dedup (`INSERT OR IGNORE` on `message_id UNIQUE`)
3. No persistent checkpoint for which emails have already been processed

## Part 1: Fix the message_id fallback (`email-monitor/monitor.py`)

Add a deterministic hash function so the same email always gets the same ID:

```python
import hashlib

def _generate_stable_message_id(sender: str, subject: str, date_str: str) -> str:
    """Generate a stable message ID from email metadata when Message-ID header is missing."""
    raw = f"{sender}|{subject}|{date_str}".encode("utf-8", errors="replace")
    return f"<generated-{hashlib.sha256(raw).hexdigest()[:16]}@email-monitor>"
```

Then in BOTH `catchup_scan()` and `poll_once()`, replace:
```python
message_id = msg.get("Message-ID", f"unknown-{time.time()}")
```
with:
```python
message_id = msg.get("Message-ID") or _generate_stable_message_id(
    msg.get("From", ""), msg.get("Subject", ""), msg.get("Date", "")
)
```

## Part 2: Add IMAP UID-based high-water mark to poll_once()

Use IMAP UIDs (persistent across sessions unlike sequence numbers) and track the last processed UID so restarts skip already-handled emails. The `scan_state` table already exists for this purpose.

In `poll_once()`, replace the current UNSEEN search and sequence-number-based fetch with UID-based operations:

```python
async def poll_once(self) -> int:
    if not self.email_address or not self.email_password:
        logger.warning("IMAP credentials not configured — skipping poll")
        return 0

    new_count = 0
    try:
        mail = await asyncio.to_thread(self._connect_imap)
        mail.select("INBOX")

        # Use UID-based high-water mark to skip already-processed emails
        last_uid = get_scan_state("last_poll_uid") or "1"
        
        # Search for UNSEEN emails with UID greater than our checkpoint
        _, message_numbers = mail.uid("search", None, "UNSEEN", f"(UID {last_uid}:*)")
        if not message_numbers[0]:
            mail.logout()
            return 0

        msg_uids = message_numbers[0].split()
        # Filter out the checkpoint UID itself (IMAP UID range is inclusive)
        msg_uids = [u for u in msg_uids if int(u) > int(last_uid)]
        if not msg_uids:
            mail.logout()
            return 0
            
        logger.info("Found %d unread emails (UID > %s)", len(msg_uids), last_uid)

        redis_client = await self._get_redis()
        max_uid_seen = int(last_uid)

        for uid in msg_uids:
            try:
                _, msg_data = mail.uid("fetch", uid, "(RFC822.HEADER BODY.PEEK[TEXT]<0.4000>)")
                if not msg_data or not msg_data[0]:
                    continue

                # ... existing header parsing, categorization, store_email, 
                # notification logic stays the same ...
                
                # Track highest UID processed
                max_uid_seen = max(max_uid_seen, int(uid))
                
            except Exception as e:
                logger.error("Error processing email UID %s: %s", uid, e)
                continue

        # Persist the high-water mark so next restart skips these
        if max_uid_seen > int(last_uid):
            set_scan_state("last_poll_uid", str(max_uid_seen))
            
        mail.logout()
    except imaplib.IMAP4.error as e:
        logger.error("IMAP error: %s", e)
    except Exception as e:
        logger.error("Email poll error: %s", e)

    return new_count
```

Replace ALL `mail.fetch(num, ...)` calls in poll_once with `mail.uid("fetch", uid, ...)` and `mail.search(...)` with `mail.uid("search", ...)`.

## Part 3: Seed the UID high-water mark from catchup_scan()

At the end of `catchup_scan()`, save the highest UID so `poll_once()` starts from the right place. Before `mail.logout()` in catchup_scan, add:

```python
# Set the poll UID high-water mark so poll_once skips catchup-covered emails
try:
    _, uid_data = mail.uid("search", None, "ALL")
    if uid_data[0]:
        all_uids = uid_data[0].split()
        if all_uids:
            highest = all_uids[-1].decode() if isinstance(all_uids[-1], bytes) else str(all_uids[-1])
            set_scan_state("last_poll_uid", highest)
            logger.info("Set poll UID high-water mark to %s", highest)
except Exception as e:
    logger.warning("Could not set poll UID high-water mark: %s", e)
```

## File to modify
- `email-monitor/monitor.py`
